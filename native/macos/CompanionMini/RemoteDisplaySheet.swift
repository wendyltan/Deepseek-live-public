// SPDX-License-Identifier: MIT
// Actual USB LVGL RGB565 full-display snapshot: not AMOLED optical proof.
// Mac voice process is paused during the bounded exclusive USB monitor.
import AppKit
import SwiftUI

struct RemoteDisplaySheet: View {
    @ObservedObject var store: CompanionStore
    @Environment(\.dismiss) private var dismiss
    @State private var feedback = ""
    @State private var monitorTask: Process?
    @State private var screenshot: NSImage?
    @State private var screenshotTime: Date?
    @State private var receiptCRC = ""
    @State private var screenshotPath = ""
    @State private var frameCount = 0
    @State private var autoSnapshots = false
    @State private var lastAutoRequestAt = Date.distantPast

    private var dir: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/Deepseek-live/display-diagnostics/r92-live",
                                   isDirectory:true)
    }
    private var active: Bool { monitorTask?.isRunning == true }
    private var wirelessReserved:Bool {
        let wireless=VerifiedWiFiGateway.read()
        return wireless?.active_devices == 1 || wireless?.pending_dsh_jobs == 1
    }
    private var fresh: Bool {
        guard let status=store.snapshot else {return false}
        return Date().timeIntervalSince1970-status.updated_at_unix <= 30 &&
               status.session_verified == true && store.espVerified
    }
    private var age: String {
        guard let date=screenshotTime else{return "未接收真实像素"}
        let sec=Int(max(0,Date().timeIntervalSince(date)))
        return "\(sec)秒"
    }
    private var pixelFresh: Bool {
        guard let date=screenshotTime else {return false}
        return Date().timeIntervalSince(date) <= 35
    }
    private func refreshPixels() {
        let metadata=dir.appendingPathComponent("esp32-rendered-screen.json")
        let file=dir.appendingPathComponent("esp32-rendered-screen.png")
        guard let raw=try? Data(contentsOf:metadata),raw.count<4096,
              let dict=try? JSONSerialization.jsonObject(with:raw) as? [String:Any],
              dict["source"] as? String == "physical_esp32_lvgl_snapshot_over_usb",
              dict["esp32_pixel_data_received"] as? Bool == true,
              dict["optical_amoled_panel_verified"] as? Bool == false,
              dict["width"] as? Int == 480,
              dict["height"] as? Int == 480,
              let seconds=dict["captured_at_unix"] as? Double,
              seconds.isFinite && seconds <= Date().timeIntervalSince1970+5,
              Date().timeIntervalSince1970-seconds <= 86400,
              let crc=dict["crc32"] as? String,crc.count==8,
              let image=NSImage(contentsOf:file),
              image.size.width>=480 && image.size.height>=480 else {return}
        let stamp=Date(timeIntervalSince1970:seconds)
        if screenshotTime != stamp {
            screenshot=image
            screenshotTime=stamp
            receiptCRC=crc
            screenshotPath=file.path
            frameCount+=1
        }
    }
    // R136: the existing voice worker is the ONLY USB serial owner.
    // This action writes a small private request and NEVER opens the USB port,
    // launches a Python monitor, stops LaunchAgent or records user audio.
    private func requestSafeFrame() {
        guard fresh, !active,
              !wirelessReserved,
              store.snapshot?.phase == "idle",
              let session=store.snapshot?.session_id,
              !session.isEmpty else {
            feedback="实体会话未就绪或旧监控正在运行，未发起安全截图。";return
        }
        let folder=FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(
                "Library/Application Support/Deepseek-live/companion-native")
        let file=folder.appendingPathComponent("screen-single-request.json")
        guard !FileManager.default.fileExists(atPath:file.path) else {
            feedback="已有截图请求待处理；请等待回执。";return
        }
        let request:[String:Any]=[
            "schema":1,"capture":"single","session_id":session,
            "at":Date().timeIntervalSince1970]
        guard let data=try? JSONSerialization.data(withJSONObject:request),
              data.count < 512 else {
            feedback="安全截图请求编码失败。";return
        }
        do {
            try FileManager.default.createDirectory(at:folder,
                withIntermediateDirectories:true,
                attributes:[.posixPermissions:0o700])
            try data.write(to:file,options:.atomic)
            try FileManager.default.setAttributes([.posixPermissions:0o600],
                                                  ofItemAtPath:file.path)
            feedback="已提交给当前语音后台的单帧取图队列；不抢USB、不暂停语音。需要R133板端协议。等待完整CRC后自动显示。"
        } catch {
            feedback="无法提交单帧请求，语音服务和设备均未改变。"
        }
    }

    // Best-effort polling, not video. The verified voice worker owns USB;
    // never open a competing USB session or interrupt live speech.
    private func pollSafeSnapshot() {
        guard autoSnapshots, !active, fresh,
              store.snapshot?.phase == "idle",
              store.snapshot?.screen_capture_status != "capturing",
              !wirelessReserved,
              Date().timeIntervalSince(lastAutoRequestAt) >= 30 else { return }
        let pending=FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(
              "Library/Application Support/Deepseek-live/companion-native/screen-single-request.json")
        guard !FileManager.default.fileExists(atPath:pending.path) else { return }
        lastAutoRequestAt=Date()
        requestSafeFrame()
    }

    private func startMonitor() {
        guard !active,
              ESPUSBSerialPresence.detected else {
            feedback="未检测到 ESP32 实体 USB 端口，未打开监控。"
            return
        }
        let alert=NSAlert()
        alert.messageText="启动 ESP32 实际软件像素监控"
        alert.informativeText="将在 Mac 上独占 ESP32 USB 约95秒，每9秒取一次完整480×480 LVGL画面。监控期间临时暂停语音服务，结束后自动恢复。不使用摄像头，因此不能排除 AMOLED 硬件显示异常。旧R61固件不支持此功能，会安全退出。"
        alert.alertStyle = .informational
        alert.addButton(withTitle:"开始监控")
        alert.addButton(withTitle:"取消")
        guard alert.runModal() == .alertFirstButtonReturn else {return}
        let python=CompanionProjectPaths.idfPython
        let working=CompanionProjectPaths.rootURL.path
        let script=working+"/scripts/r92_screen_monitor.py"
        guard FileManager.default.isExecutableFile(atPath:python),
              FileManager.default.fileExists(atPath:script) else {
            feedback="监控工具尚未安装，未打开串口。"
            return
        }
        let task=Process()
        task.executableURL=URL(fileURLWithPath:python)
        task.currentDirectoryURL=URL(fileURLWithPath:working)
        task.arguments=["-m","scripts.r92_screen_monitor","--duration","95"]
        let log=dir.appendingPathComponent("monitor-last.log")
        do {
            try FileManager.default.createDirectory(at:dir,withIntermediateDirectories:true,
                attributes:[.posixPermissions:0o700])
            FileManager.default.createFile(atPath:log.path,contents:nil,
                attributes:[.posixPermissions:0o600])
            let handle=try FileHandle(forWritingTo:log)
            task.standardOutput=handle
            task.standardError=handle
            task.terminationHandler={t in
                DispatchQueue.main.async {
                    self.monitorTask=nil
                    self.refreshPixels()
                    self.feedback=t.terminationStatus==0
                        ? "监控完成，语音服务应已恢复；请核实画面时间。"
                        : "监控结束或设备协议不匹配；详细原因见诊断日志。"
                }
                try? handle.close()
            }
            try task.run()
            monitorTask=task
            feedback="正在读取真实 LVGL 像素，语音服务暂时让出 USB…"
        } catch {
            monitorTask=nil
            feedback="无法启动监控程序；未读取任何像素。"
        }
    }
    private func stopMonitor() {
        guard let task=monitorTask,task.isRunning else {return}
        task.terminate()  // Python SIGTERM handler exits and restores voice LaunchAgent.
        feedback="正在结束监控，等待恢复 Mac 语音服务…"
    }

    var body: some View {
        VStack(alignment:.leading,spacing:11) {
            HStack {
                Image(systemName:"display").foregroundStyle(.blue)
                Text("ESP32 · 真实软件像素监控")
                    .font(.system(size:18,weight:.semibold))
                Spacer()
                Button("关闭"){dismiss()}
            }
            Text("左侧来源是 ESP32 经 USB 返回的整个 LVGL 渲染画面（480×480），不是 Mac 模拟图；它仍不等于 AMOLED 面板的光学照片。")
                .font(.system(size:12,weight:.medium))
                .foregroundStyle(.orange)
                .fixedSize(horizontal:false,vertical:true)
            HStack(alignment:.top,spacing:18){
                VStack(alignment:.leading,spacing:8){
                    ZStack {
                        RoundedRectangle(cornerRadius:13)
                            .fill(Color(nsColor:.controlBackgroundColor))
                        if let screenshot=screenshot {
                            Image(nsImage:screenshot)
                                .resizable()
                                .interpolation(.none)
                                .scaledToFit()
                                .frame(width:440,height:440)
                        } else {
                            ContentUnavailableView(
                                "尚未取得 ESP32 全屏像素",
                                systemImage:"display.trianglebadge.exclamationmark",
                                description:Text("请检查实际固件是否提供 DFSCREEN2 协议，或在设备连接后启动USB软件像素监控")
                            ).frame(width:420,height:420)
                        }
                    }.frame(width:448,height:448)
                    Text(pixelFresh ? "设备软件截图 · 最近\(age)" : "最近截图：\(age)（可能已过期）")
                        .font(.system(size:11))
                        .foregroundStyle(pixelFresh ? Color.green:.secondary)
                }
                VStack(alignment:.leading,spacing:11){
                    Label(active ? "正在独占 USB 截屏（语音暂停）" :
                          (fresh ? "语音实体会话已验证" : "当前语音连接未验证"),
                          systemImage:active ? "dot.radiowaves.left.and.right":"cable.connector")
                        .foregroundStyle(active ? .orange : (fresh ? .green:.secondary))
                    LabeledContent("画面来源",value:screenshot == nil ? "尚无回执" : "ESP32 LVGL 渲染")
                    LabeledContent("分辨率",value:screenshot == nil ? "未知":"480 × 480")
                    LabeledContent("最新画面距离现在",value:age)
                    LabeledContent("画面变化次数",value:String(frameCount))
                    LabeledContent("像素 CRC32",value:receiptCRC.isEmpty ? "未验证":receiptCRC)
                    LabeledContent("已批准的SD动画",value:store.motionPackageVerified ? "已验证":"未验证")
                    LabeledContent("AMOLED实体发光",value:"没有摄像头，不能证明")
                    Divider()
                    Text("按需刷新为低帧率的真实截图，单帧通常需要约10秒。仅在语音空闲时向同一USB Owner请求；播报、录音或超时均跳过。不是连续视频，也不能证明AMOLED光学显示。")
                        .font(.system(size:11)).foregroundStyle(.secondary)
                        .fixedSize(horizontal:false,vertical:true)
                    Spacer(minLength:8)
                    Button("安全单帧截图 · 不暂停语音") {requestSafeFrame()}
                        .buttonStyle(.borderedProminent)
                        .disabled(!fresh || active)
                        .help("同一语音串口Owner执行，完整CRC才发布；实机R133及之后需要支持DFSCREEN3")
                    if let current=store.snapshot?.screen_capture_status,
                       !current.isEmpty {
                        Text("单帧请求状态："+current)
                            .font(.system(size:11))
                            .foregroundStyle(.secondary)
                    }
                    Toggle("窗口打开时每30秒取一帧（USB空闲）",isOn:$autoSnapshots)
                        .toggleStyle(.switch)
                        .disabled(!fresh || active)
                        .help("低帧率，按需排队，每次CRC完整才发布。不会停止语音服务。")
                    if autoSnapshots {
                        Text("仅本窗口打开期间采集。设备录音、播报或Wi-Fi连接时跳过；收到完整CRC后才更新，不是实时视频。")
                            .font(.system(size:11))
                            .foregroundStyle(.secondary)
                    }
                    Button("在访达查看诊断截图") {
                        if !screenshotPath.isEmpty {
                            NSWorkspace.shared.activateFileViewerSelecting(
                                [URL(fileURLWithPath:screenshotPath)])
                        }
                    }.disabled(screenshotPath.isEmpty)
                }
                .frame(maxWidth:.infinity,alignment:.leading)
                .font(.system(size:12))
            }
            if !feedback.isEmpty {
                Text(feedback).font(.system(size:11)).foregroundStyle(.secondary)
            }
        }
        .padding(18)
        .frame(width:900,height:565)
        .onAppear{refreshPixels()}
        .onDisappear{autoSnapshots=false}
        .onReceive(Timer.publish(every:1.5,on:.main,in:.common).autoconnect()) { _ in
            refreshPixels()
            pollSafeSnapshot()
        }
    }
}
