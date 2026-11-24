// SPDX-License-Identifier: MIT
// Extracted from main.swift: observable device, gateway, memory, and TTS state store.
import AppKit
import SwiftUI

@MainActor
final class CompanionStore: ObservableObject {
    @Published private(set) var snapshot: CompanionSnapshot?
    @Published private(set) var notice = "尚未接入已验证的会话状态"
    private var poller: Timer?
    @Published private(set) var serviceRequested = false
    @Published private(set) var connecting = false
    @Published private(set) var localTTSReady = false
    private var nextTTSCheck: TimeInterval = 0
    @Published private(set) var launchStatus = "正在检查本机服务"
    @Published private(set) var dshServiceState = "检测中"
    @Published private(set) var voiceServiceState = "检测中"
    @Published private(set) var serviceBusy = false
    private var nextServiceCheck:TimeInterval = 0
    private var nextStartupRetry:TimeInterval = 0
    private var startupRetries = 0
    @Published private(set) var physicalLink: String = "ESP32 尚未确认"
    @Published private(set) var connectionDiagnostic = "尚未检查后台服务"
    private var nextDiagnosticCheck: TimeInterval = 0
    @Published private(set) var searchChangeNotice: String = ""
    @Published private(set) var modelChangeNotice: String = ""
    // Keep authenticated, bounded conversation visible during a transient
    // status rotation. Never use this cache as a proof of live connectivity.
    @Published private(set) var lastVerifiedPreview: [ConversationPreview] = []
    private var previewSessionID: String? = nil
    private var lastHistoryReadAt:TimeInterval = 0
    // R634: the archive may be polled repeatedly while the user interacts;
    // identical read-only bytes must never invalidate SwiftUI's full layout.
    private var lastVerifiedHistoryBytes: Data? = nil
    private var lastSnapshotBytes: Data? = nil
    private static let historyURL:URL = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("Library/Application Support/Deepseek-live/companion-native/conversation-history-v3.json")

    private func reloadVerifiedHistory(_ sid:String,now:TimeInterval){
        if now-lastHistoryReadAt<1.2{return}
        lastHistoryReadAt=now
        let url=Self.historyURL
        guard let attrs=try? FileManager.default.attributesOfItem(atPath:url.path),
              attrs[.type] as? FileAttributeType == .typeRegular,
              let permissions=attrs[.posixPermissions] as? NSNumber,
              permissions.intValue & 0o077 == 0,
              let owner=attrs[.ownerAccountID] as? NSNumber,
              owner.intValue == Int(getuid()),
              let bytes=attrs[.size] as? NSNumber,
              bytes.intValue > 20 && bytes.intValue <= 220_000,
              let raw=try? Data(contentsOf:url),
              raw != lastVerifiedHistoryBytes,
              let archive=try? JSONDecoder().decode(VerifiedConversationArchive.self,from:raw),
              archive.schema==3, archive.session_verified,
              archive.session_id==sid, archive.turns.count<=120,
              archive.turns.allSatisfy({$0.user.count<=400 && $0.assistant.count<=900 &&
                ["model","preset","memory","clock","weather","weather_unavailable","failed"].contains($0.origin) &&
                ($0.progress ?? []).count<=8 && ($0.progress ?? []).allSatisfy({$0.count<=100})})
        else{return}
        lastVerifiedHistoryBytes=raw
        lastVerifiedPreview=archive.turns
    }
    // R216: a single failed atomic-read poll must not blank the entire UI.
    // Display may retain a snapshot briefly, but actions fail closed.
    @Published private(set) var snapshotReadHealthy = false
    private var lastTrustedSnapshotAt:TimeInterval = 0
    private let transientReadGraceSeconds:TimeInterval = 3.0
    private var requestedModel:String? = nil
    private var requestedModelAt:TimeInterval = 0

    private var link: PhysicalDeviceLink?

    var running: Bool { serviceRequested || bothVerified }
    var espVerified: Bool {
        snapshotReadHealthy && snapshot?.session_verified == true &&
        Date().timeIntervalSince1970 - (snapshot?.updated_at_unix ?? 0) <= 30 &&
        link?.esp32_verified == true &&
        link?.voice_source == "esp32_onboard_mic" &&
        link?.usb_port == "esp32_s3_usb_serial_jtag" &&
        ESPUSBSerialPresence.detected
    }
    var motionPackageVerified: Bool {
        espVerified && link?.selected35_verified == true
    }
    var bothVerified: Bool {
        espVerified && link?.session_id == snapshot?.session_id &&
        snapshot?.session_verified == true
    }

    // Future trusted bridge adapter writes atomic snapshots here. The mini app
    // never writes this file or infers model/source from plain response content.
    static let snapshotURL: URL = {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/Deepseek-live/companion-native/status.json")
    }()

    init() {
        refresh()
        // Dynamic, read-only attach comes from the same-session verified link
        // and snapshot; a previously running R29 agent is never kickstarted
        // merely because the UI opens.
        // DSH fact callbacks write atomically; 0.6s UI refresh prevents a
        // multi-second apparent "frozen" desktop fish while thinking/tools run.
        poller = Timer.scheduledTimer(withTimeInterval: 0.6, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.refresh() }
        }
        // R159: Onboard SD uploads have *exclusive USB ownership*.
        // Never auto-restart the voice LaunchAgent while the SD owner is
        // writing: that USB contest reset the device in a real R156 upload.
        let sdExclusive = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/Deepseek-live/companion-native/sd-install-exclusive.json")
        if FileManager.default.fileExists(atPath:sdExclusive.path) {
            launchStatus="实体SD正在由唯一USB通道同步；此次打开不会启动语音后台。"
        } else {
            nextStartupRetry=Date().timeIntervalSince1970+25
            // R448: opening the Mac UI must not request USB ownership while an
            // authenticated wireless device or in-flight wireless task exists.
            let wireless=VerifiedWiFiGateway.read()
            if wireless?.active_devices == 1 || wireless?.pending_dsh_jobs == 1 {
                launchStatus="无线语音正在使用；Mac窗口只读取状态，不重连USB"
            } else {
                Task { @MainActor [weak self] in self?.connectSession() }
            }
        }
    }

    private func receiveTTSHealth(_ healthy:Bool) {
        localTTSReady=healthy
    }
    private func receiveVoiceDiagnostic(_ diagnosis:String) {
        connectionDiagnostic=diagnosis
    }
    private func applyServiceStatus(_ state:CompanionServiceStatus?) {
        guard let state else {
            dshServiceState="未能读取"
            voiceServiceState="未能读取"
            return
        }
        dshServiceState=state.dsh_ready ? "已就绪" :
            (state.dsh_running ? "进程运行 · 健康未通过" : "尚未运行")
        voiceServiceState=state.voice_verified ? "实体会话已验证" :
            (state.lan_occupied ? "Wi-Fi 会话正在使用" :
                state.voice_running ? "进程运行 · 连接待核实" :
                state.usb_present ? "未启动" : "USB 未接入")
        serviceRequested=state.voice_running
    }
    private func receiveConnectResult(_ result:(Bool,String,CompanionServiceStatus?)) {
        connecting=false
        serviceBusy=false
        applyServiceStatus(result.2)
        launchStatus=result.1
        nextDiagnosticCheck=0
        nextServiceCheck=Date().timeIntervalSince1970+5
    }
    private func receiveServiceStatus(_ state:CompanionServiceStatus?) {
        if connecting {return}
        applyServiceStatus(state)
    }
    private func receiveStopResult(_ didStop:Bool) {
        connecting=false
        if didStop {
            serviceRequested=false
            snapshotReadHealthy=false
            lastTrustedSnapshotAt=0
            snapshot=nil
            link=nil
            physicalLink="ESP32 语音服务已停止"
            launchStatus="语音服务已停止，可重新连接"
        } else {
            launchStatus="停止服务未成功，请检查后台状态"
        }
    }

    private func safe(_ input: String?, maximum: Int) -> String {
        String((input ?? "").prefix(maximum)).trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private func markSnapshotUnavailable(_ message:String, now:TimeInterval) {
        snapshotReadHealthy = false
        notice = message
        // Keep the last VERIFIED identity/animation on screen only for a very
        // brief read gap; never treat this as live approval/USB availability.
        if snapshot == nil || lastTrustedSnapshotAt <= 0 ||
            now - lastTrustedSnapshotAt > transientReadGraceSeconds {
            snapshot = nil
            lastSnapshotBytes = nil
        }
    }

    private func refresh() {
        refreshDeviceLink()
        // Human-readable local process diagnostics are separate from trusted
        // DSH session receipts. Never imply that a USB cable equals a bind.
        let now = Date().timeIntervalSince1970
        if now >= nextServiceCheck {
            nextServiceCheck=now+12
            if !connecting {
                Task.detached(priority:.utility) { [weak self] in
                    let result=Self.runConnectionManager("status")
                    await self?.receiveServiceStatus(result.2)
                }
            }
        }
        // R317: bounded cold-login retry for late-mounted ExtSSD / DSH.
        // Status remains authoritative; no model turn or unsolicited mic ARM.
        if now >= nextStartupRetry && startupRetries<4 &&
           !connecting && !bothVerified && ESPUSBSerialPresence.detected {
            let exclusive=FileManager.default.homeDirectoryForCurrentUser
                .appendingPathComponent("Library/Application Support/Deepseek-live/companion-native/sd-install-exclusive.json")
            nextStartupRetry=now+35
            startupRetries+=1
            let wireless=VerifiedWiFiGateway.read()
            if !FileManager.default.fileExists(atPath:exclusive.path) &&
                wireless?.active_devices != 1 && wireless?.pending_dsh_jobs != 1 {
                connectSession()
            }
        }
        if now >= nextTTSCheck {
            nextTTSCheck = now + 8
            Task.detached(priority:.utility) { [weak self] in
                var ready = false
                for candidate in ["http://127.0.0.1:8906/health", "http://127.0.0.1:8907/health"] {
                    guard !ready, let url=URL(string:candidate) else { continue }
                    var request=URLRequest(url:url)
                    request.timeoutInterval=2
                    if let (data,_) = try? await URLSession.shared.data(for:request),
                       let json=try? JSONSerialization.jsonObject(with:data) as? [String:Any] {
                        ready=(json["ready"] as? Bool == true) &&
                              (json["error"] == nil || json["error"] is NSNull)
                    }
                }
                await self?.receiveTTSHealth(ready)
            }
        }
        if now >= nextDiagnosticCheck {
            nextDiagnosticCheck = now + 12
            Task.detached(priority:.utility) { [weak self] in
                let diagnosis=Self.backgroundVoiceDiagnostic()
                await self?.receiveVoiceDiagnostic(diagnosis)
            }
        }
        let url = Self.snapshotURL
        let path = url.path
        guard let attrs = try? FileManager.default.attributesOfItem(atPath: path),
              attrs[.type] as? FileAttributeType == .typeRegular,
              let size = attrs[.size] as? NSNumber,
              size.intValue > 0 && size.intValue <= 32_768 else {
            markSnapshotUnavailable("状态读取短暂中断；等待已验证数据",now:now)
            return
        }
        do {
            let raw = try Data(contentsOf: url)
            guard raw.count <= 32_768 else { throw CocoaError(.fileReadTooLarge) }
            let parsed = try JSONDecoder().decode(CompanionSnapshot.self, from: raw)
            guard parsed.schema == 1,
                  parsed.updated_at_unix.isFinite,
                  parsed.updated_at_unix <= now + 5,
                  ["idle", "listening", "transcribing", "thinking", "tool_pending",
                   "approval_pending", "voice_generating", "speaking", "error"].contains(parsed.phase)
            else {
                markSnapshotUnavailable("状态过期或格式不受支持",now:now)
                return
            }
            let fresh = now - parsed.updated_at_unix <= 30
            let privateHistoryAnchor = (attrs[.ownerAccountID] as? NSNumber)?.intValue == Int(getuid()) &&
                ((attrs[.posixPermissions] as? NSNumber)?.intValue ?? 511) & 0o077 == 0
            if parsed.session_verified != true || parsed.session_id?.isEmpty != false ||
                (!fresh && !privateHistoryAnchor) {
                previewSessionID = nil
                lastVerifiedPreview = []
            }
            if (fresh || privateHistoryAnchor), parsed.session_verified == true,
               let sid = parsed.session_id, !sid.isEmpty {
                if previewSessionID != sid {
                    // Different official session: never attribute an older
                    // conversation to the new model/session.
                    previewSessionID = sid
                    lastVerifiedHistoryBytes = nil
                    lastVerifiedPreview = []
                }
                if let turns=parsed.conversation_preview, !turns.isEmpty,
                   fresh && lastVerifiedPreview.count < turns.count {
                    lastVerifiedPreview=turns
                }
                reloadVerifiedHistory(sid,now:now)
            }
            guard fresh else {
                markSnapshotUnavailable("状态过期，显示已验证的对话历史",now:now)
                return
            }
            // Status may be rewritten with the same trusted contents by the
            // process poller. A redundant @Published snapshot causes the
            // entire chat Markdown/layout graph to run on every 600ms tick.
            if lastSnapshotBytes != raw {
                lastSnapshotBytes = raw
                snapshot = parsed
            }
            snapshotReadHealthy = true
            lastTrustedSnapshotAt = now
            notice = ""
            if let wanted=requestedModel {
                if parsed.session_verified == true &&
                   parsed.model_confirmed == true &&
                   parsed.model_selection_source == "dsh_native_session" &&
                   parsed.model_id == wanted {
                    modelChangeNotice="已由官方DSH实际确认切换为 "+wanted
                    requestedModel=nil
                } else if now-requestedModelAt>50 {
                    modelChangeNotice="DSH未在限定时间内确认模型切换；以当前会话实际模型为准"
                    requestedModel=nil
                }
            }
        } catch {
            markSnapshotUnavailable("状态文件无法验证",now:now)
        }
    }

    // This only reads a 0600, atomic host proof written *after* the physical
    // board handshake and the official Harness session bind. The Mac app never
    // guesses the board's readiness based solely on a tty device filename.
    private func refreshDeviceLink() {
        // Read verifiable device receipts even when this Mac UI was opened
        // before the backend LaunchAgent. No self-claimed connection.
        let home = FileManager.default.homeDirectoryForCurrentUser
        let url = home.appendingPathComponent("Library/Application Support/Deepseek-live/companion-native/device-link.json")
        guard let info = try? url.resourceValues(forKeys: [.isRegularFileKey,.isSymbolicLinkKey]),
              info.isRegularFile == true, info.isSymbolicLink != true,
              let raw = try? Data(contentsOf: url),raw.count < 1024,
              let receipt = try? JSONDecoder().decode(PhysicalDeviceLink.self,from: raw),
              receipt.schema == 1,receipt.started_at_unix.isFinite,
              receipt.started_at_unix <= Date().timeIntervalSince1970 + 5,
              Date().timeIntervalSince1970 - receipt.started_at_unix < 86400,
              receipt.session_id.range(of:#"^(?:[a-f0-9]{32}|[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12})$"#,options:.regularExpression) != nil
        else { link=nil;physicalLink="正在核验 ESP32 实体连接";return }
        link = receipt
        physicalLink = !espVerified ? "ESP32 连接未核实" :
            (motionPackageVerified ? "ESP32 已握手 · SD历史包已确认" :
                                    "ESP32 已握手 · SD动画降级，语音仍可用")
    }

    private func recentVoiceBlockReason() -> String? {
        let url=FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/Deepseek-live/companion-native/r29-live-session.log")
        guard let info=try? url.resourceValues(forKeys:[
                  .isRegularFileKey,.isSymbolicLinkKey,.fileSizeKey,.contentModificationDateKey]),
              info.isRegularFile == true, info.isSymbolicLink != true,
              let size=info.fileSize, size > 0 && size < 524_288,
              let modified=info.contentModificationDate,
              Date().timeIntervalSince(modified) >= -5,
              Date().timeIntervalSince(modified) < 3600,
              let text=try? String(contentsOf:url,encoding:.utf8),
              let failure=text.split(separator:"\n").last(where:{
                  $0.hasPrefix("H10_PREFLIGHT_BLOCKED")
              }) else { return nil }
        if failure.contains("HTTP 429") {
            return "ESP32 USB 在线，但 DSH 返回 HTTP 429；语音会话未建立"
        }
        if failure.contains("H10_VERSION_ACK_MISSING") {
            return "ESP32 USB 在线，但 H10 握手超时；语音会话未建立"
        }
        return "ESP32 USB 在线，但后台预检失败；请查看日志"
    }

    private func refreshVoiceWorkerDiagnostic() {
        guard ESPUSBSerialPresence.detected else {
            connectionDiagnostic="未发现 ESP32 USB；请检查设备连接"
            return
        }
        let name="gui/\(getuid())/local.deepseeklive.r29.voice"
        let worker=Process()
        worker.executableURL=URL(fileURLWithPath:"/bin/launchctl")
        worker.arguments=["print",name]
        let pipe=Pipe()
        worker.standardOutput=pipe
        worker.standardError=Pipe()
        do {
            try worker.run()
            let output=pipe.fileHandleForReading.readDataToEndOfFile()
            worker.waitUntilExit()
            guard worker.terminationStatus==0 else {
                connectionDiagnostic="ESP32 USB 在线；Mac 语音后台未启动"
                return
            }
            let report=String(data:output,encoding:.utf8) ?? ""
            if report.contains("state = spawn scheduled") {
                connectionDiagnostic=recentVoiceBlockReason() ?? "ESP32 USB 在线；Mac 语音后台正在失败重试"
            }else if report.range(of:#"(?m)^\s*pid = [0-9]+\s*$"#,
                                   options:.regularExpression) != nil {
                connectionDiagnostic="语音进程已启动；仍需验证 DSH 会话和板载麦克风"
            }else {
                connectionDiagnostic="ESP32 USB 在线；语音进程尚未就绪"
            }
        } catch {
            connectionDiagnostic="ESP32 USB 在线；无法检查 Mac 语音后台"
        }
    }

    // The actual microphone worker runs as a user LaunchAgent from a
    // private, 0700 local runtime. LaunchServices cannot reliably initialize
    // Python while scanning large external virtualenv directories.
    private func runLaunchctl(_ args: [String]) -> Bool {
        let command=Process()
        command.executableURL=URL(fileURLWithPath: "/bin/launchctl")
        command.arguments=args
        command.standardOutput=Pipe()
        command.standardError=Pipe()
        do {
            try command.run()
            command.waitUntilExit()
            return command.terminationStatus == 0
        } catch { return false }
    }

    // Check launchd's real PID; a previously clicked button is not proof
    // of a live process. Never kickstart a running voice worker mid-turn.
    private func voiceWorkerAlive(_ name: String) -> Bool {
        let command = Process()
        command.executableURL=URL(fileURLWithPath:"/bin/launchctl")
        command.arguments=["print",name]
        let output=Pipe()
        command.standardOutput=output
        command.standardError=Pipe()
        do {
            try command.run()
            let bytes=output.fileHandleForReading.readDataToEndOfFile()
            command.waitUntilExit()
            guard command.terminationStatus == 0,
                  let message=String(data:bytes,encoding:.utf8) else { return false }
            return message.range(of:#"(?m)^\s*pid = [0-9]+\s*$"#,options:.regularExpression) != nil
        } catch { return false }
    }

    // All subprocess waits run on a detached worker. The UI and 0.6-second
    // status timer NEVER synchronously wait for launchctl or DSH startup.
    private nonisolated static func backgroundVoiceDiagnostic() -> String {
        guard ESPUSBSerialPresence.detected else {
            return "ESP32 USB 未检测到"
        }
        let command=Process()
        command.executableURL=URL(fileURLWithPath:"/bin/launchctl")
        command.arguments=["print","gui/\(getuid())/local.deepseeklive.r29.voice"]
        let output=Pipe()
        command.standardOutput=output
        command.standardError=Pipe()
        do {
            try command.run()
            let raw=output.fileHandleForReading.readDataToEndOfFile()
            command.waitUntilExit()
            if command.terminationStatus != 0 {
                return "ESP32 USB 已发现，Mac 语音后台未启动"
            }
            let report=String(data:raw,encoding:.utf8) ?? ""
            if report.contains("state = spawn scheduled") {
                return "ESP32 USB 已发现，语音后台启动失败并等待重试；DSH未验证"
            }
            if report.range(of:#"(?m)^\s*pid = [0-9]+\s*$"#,
                            options:.regularExpression) != nil {
                return "语音进程正在运行；等待 ESP32 和 DSH 双重连接确认"
            }
            return "ESP32 USB 已发现，语音后台尚未就绪"
        } catch {
            return "ESP32 USB 已发现，无法查询语音后台状态"
        }
    }

    private nonisolated static func runConnectionManager(_ action:String = "all")
        -> (Bool,String,CompanionServiceStatus?) {
        let tool=Process()
        tool.executableURL=URL(fileURLWithPath:CompanionProjectPaths.python)
        tool.arguments=[CompanionProjectPaths.script("companion_cli.py"),"connection",action]
        let pipe=Pipe()
        tool.standardOutput=pipe
        tool.standardError=Pipe()
        do {
            // A hung external SSD / Python loader must not leave the GUI
            // spinning forever. File lives in private INTERNAL app runtime.
            let done=DispatchSemaphore(value:0)
            tool.terminationHandler={ _ in done.signal() }
            try tool.run()
            guard done.wait(timeout:.now()+30) == .success else {
                if tool.isRunning { tool.terminate() }
                return (false,"服务操作超过30秒；请检查磁盘挂载和服务日志",nil)
            }
            let bytes=pipe.fileHandleForReading.readDataToEndOfFile()
            guard tool.terminationStatus == 0,
                  let receipt=try? JSONDecoder().decode(CompanionServiceReceipt.self,from:bytes) else {
                return (false,"服务管理程序没有返回有效状态；请检查本机日志",nil)
            }
            return (receipt.ok,String(receipt.detail.prefix(235)),receipt.status)
        } catch {
            return (false,"无法启动服务管理程序；未尝试录音或付费请求",nil)
        }
    }

    func connectSession() {
        guard !connecting else { return }
        connecting=true
        serviceBusy=true
        launchStatus="正在核验 DSH、TTS 与 ESP32 USB 语音…"
        Task.detached(priority:.userInitiated) { [weak self] in
            let result=Self.runConnectionManager("all")
            await self?.receiveConnectResult(result)
        }
    }

    // R320: user-initiated LAN gateway recovery through the installed launchd
    // owner supervisor. Never launch a second WSS server or interrupt a turn.
    func startWiFiGateway() {
        guard !connecting else {return}
        connecting=true
        launchStatus="正在检查 Wi-Fi 网关及 USB / 无线切换服务…"
        Task.detached(priority:.userInitiated) { [weak self] in
            let label="gui/\(getuid())/local.deepseeklive.r319.transport-supervisor"
            let check=Process()
            check.executableURL=URL(fileURLWithPath:"/bin/launchctl")
            check.arguments=["print",label]
            check.standardOutput=Pipe()
            check.standardError=Pipe()
            let message:String
            do {
                try check.run()
                check.waitUntilExit()
                if check.terminationStatus != 0 {
                    message="无线切换服务未安装；请检查 R319 LaunchAgent"
                } else if let pipe=check.standardOutput as? Pipe,
                          let raw=String(data:pipe.fileHandleForReading.readDataToEndOfFile(),encoding:.utf8),
                          raw.range(of:#"(?m)^\s*pid = [0-9]+\s*$"#,options:.regularExpression) != nil {
                    message="切换管理器已运行；网关是否启动、ESP32是否连接请查看 Wi-Fi / WSS 状态"
                } else {
                    let output=Process()
                    output.executableURL=URL(fileURLWithPath:"/bin/launchctl")
                    output.arguments=["kickstart",label]
                    output.standardOutput=Pipe()
                    output.standardError=Pipe()
                    try output.run()
                    output.waitUntilExit()
                    message=output.terminationStatus == 0
                        ? "已请求启动无线切换管理器；请查看下方 Wi-Fi / WSS 连接状态"
                        : "启动请求失败；请检查本机无线网关日志"
                }
            } catch {
                message="无法启动无线切换管理器：\(error.localizedDescription)"
            }
            await self?.receiveGatewayStart(message)
        }
    }
    private func receiveGatewayStart(_ message:String) {
        connecting=false
        launchStatus=message
    }

    func startDshService() {
        runServiceAction("start-dsh",message:"正在检查并按需启动官方 DSH…")
    }
    func startVoiceService() {
        runServiceAction("start-voice",message:"正在核验并按需启动 ESP32 USB 语音…")
    }
    private func runServiceAction(_ action:String,message:String) {
        guard !connecting else {return}
        connecting=true
        serviceBusy=true
        launchStatus=message
        Task.detached(priority:.userInitiated) { [weak self] in
            let result=Self.runConnectionManager(action)
            await self?.receiveConnectResult(result)
        }
    }

    func requestModel(_ wanted: String) {
        guard bothVerified, snapshot?.phase == "idle",
              ["deepseek-flash","deepseek-v4-pro"].contains(wanted),
              let sid=snapshot?.session_id else {
            modelChangeNotice="实体会话未验证或正在对话，未发送模型请求";return
        }
        if snapshot?.model_id == wanted {
            modelChangeNotice="当前已是这一模型，无须切换";return
        }
        let target=FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/Deepseek-live/companion-native/model-switch-request.json")
        let request:[String:Any]=["schema":1,"session_id":sid,
                                  "model":wanted,"at":Date().timeIntervalSince1970]
        guard let bytes=try? JSONSerialization.data(withJSONObject:request) else {return}
        do {
            try bytes.write(to:target,options:.atomic)
            try FileManager.default.setAttributes([.posixPermissions:0o600],ofItemAtPath:target.path)
            requestedModel=wanted
            requestedModelAt=Date().timeIntervalSince1970
            modelChangeNotice="已发送切换请求；必须等官方DSH实际确认后才算生效"
        }catch {modelChangeNotice="模型控制请求未成功保存"}
    }

    func toggleSearch() {
        guard bothVerified, snapshot?.search_supported == true,
              let sid=snapshot?.session_id else { return }
        let enable=snapshot?.search_enabled != true
        let folder=FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/Deepseek-live/companion-native")
        let target=folder.appendingPathComponent("search-request.json")
        let request: [String:Any] = ["schema":1,"session_id":sid,
             "enabled":enable,"at":Date().timeIntervalSince1970]
        guard let raw=try? JSONSerialization.data(withJSONObject:request) else {return}
        do {
            try raw.write(to:target,options:.atomic)
            try FileManager.default.setAttributes([.posixPermissions:0o600],ofItemAtPath:target.path)
            searchChangeNotice=enable ? "已提交开启请求，等待DSH确认" : "已提交关闭请求，等待DSH确认"
        } catch { searchChangeNotice="联网搜索设置提交失败" }
    }

    // User preference only: review suggestions are kept in a bounded owner-
    // private queue; this never grants automatic long-term fact writes.
    func configureMemoryCandidateMode(_ value: String) {
        guard ["manual","review","off","auto"].contains(value) else { return }
        let folder=FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/Deepseek-live/companion-native")
        let target=folder.appendingPathComponent("memory-candidate-mode.json")
        let mode = value == "auto" ? "auto" : (value == "review" ? "review" : "off")
        let payload:[String:Any]=["schema":1,"mode":mode]
        guard let bytes=try? JSONSerialization.data(withJSONObject:payload) else{return}
        do {
            try FileManager.default.createDirectory(at:folder,withIntermediateDirectories:true)
            try bytes.write(to:target,options:.atomic)
            try FileManager.default.setAttributes([.posixPermissions:0o600],ofItemAtPath:target.path)
        } catch {
            launchStatus="记忆候选偏好保存失败"
        }
    }

    func stopSession() {
        guard !connecting else { return }
        // Explicit Stop overrides this app launch's bounded auto-retry.
        // Never silently undo the owner's decision seconds later.
        startupRetries=4
        nextStartupRetry=Double.greatestFiniteMagnitude
        connecting=true
        launchStatus="正在后台停止语音进程…"
        Task.detached(priority:.userInitiated) { [weak self] in
            let worker=Process()
            worker.executableURL=URL(fileURLWithPath:"/bin/launchctl")
            worker.arguments=["bootout","gui/\(getuid())/local.deepseeklive.r29.voice"]
            worker.standardOutput=Pipe()
            worker.standardError=Pipe()
            var stopped=false
            do {
                try worker.run()
                worker.waitUntilExit()
                stopped=(worker.terminationStatus==0)
            } catch {}
            let didStop=stopped
            await self?.receiveStopResult(didStop)
        }
    }

    // Only load a known selected ID, never arbitrary paths from a status file.
    var motionID: String {
        let value = snapshot?.animation_id ?? "m000"
        return value.range(of: #"^m[0-9]{3}$"#, options: .regularExpression) == nil
            ? "m000" : value
    }
    var motionLabel: String {
        guard let s = snapshot, let text = s.animation, !text.isEmpty else {
            return "待机 · 原版动画预览（暂无可信会话）"
        }
        return "已选动作 · " + String(text.prefix(24))
    }
    var motionFile: URL? { motionFile(for: motionID) }
    func motionFile(for selectedID: String) -> URL? {
        guard selectedID.range(of: #"^m[0-9]{3}$"#, options: .regularExpression) != nil else { return nil }
        let parent = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/Deepseek-live/companion-native/motions-light-r32")
        // R173: both Mac panels use the SAME real 240x240 / 8fps DFSP
        // rendered GIF. Preserve the original 35 approved light previews;
        // 71 newly installed clips live only in a separate private folder.
        let newFolder = parent.deletingLastPathComponent()
            .appendingPathComponent("motion-previews-light-r173",isDirectory:true)
        let candidates = [
            parent.appendingPathComponent(selectedID.uppercased()+".gif"),
            newFolder.appendingPathComponent(selectedID.uppercased()+".gif")
        ]
        for url in candidates {
            guard let values = try? url.resourceValues(forKeys:
                      [.isRegularFileKey,.isSymbolicLinkKey,.fileSizeKey]),
                  values.isRegularFile == true, values.isSymbolicLink != true,
                  let bytes=values.fileSize,
                  bytes>5000 && bytes<8_000_000 else{continue}
            return url
        }
        return nil
    }

    var connected: Bool { snapshot?.session_verified == true }
    var deviceTrial: Bool { snapshot != nil && snapshot?.session_verified != true }
    var phase: String {
        switch snapshot?.phase {
        case "idle": "待机"
        case "listening": "正在聆听"
        case "transcribing": "语音识别中"
        case "thinking": "等待模型响应"
        case "tool_pending": "工具执行中"
        case "approval_pending": "等待用户审批"
        case "voice_generating": "正在合成语音"
        case "speaking": "语音播放中"
        case "error": "出现错误"
        default: "未连接"
        }
    }
    var sessionLabel: String {
        guard let s = snapshot, s.session_verified == true else { return "尚未核验会话" }
        let id = safe(s.session_id, maximum: 80)
        return id.isEmpty ? "尚未核验会话" : id
    }
    var modelLabel: String {
        guard let s = snapshot, s.model_confirmed == true else { return "模型尚未确认" }
        let model = safe(s.model_id, maximum: 80)
        return model.isEmpty ? "模型尚未确认" : model
    }
    var originLabel: String {
        guard let s = snapshot, s.answer_verified == true else { return "来源未核实" }
        switch s.answer_origin {
        case "preset": return "经验证的预置回复"
        case "memory": return "用户明确检索的本地记忆"
        case "clock": return "Mac 系统时间"
        case "weather": return "Open-Meteo 天气模型"
        case "weather_unavailable": return "天气服务暂不可用"
        case "model": return "经验证的模型实时生成"
        default: return "来源未核实"
        }
    }
    var recentSteps: [CompanionStep] {
        Array((snapshot?.steps ?? []).suffix(4))
    }
    var activeSearch: String {
        guard let state = snapshot, state.session_verified == true else { return "未确认" }
        if state.search_supported != true { return "不可用" }
        return state.search_enabled == true ? "已启用" : "未启用"
    }
    var verifiedToolLabel: String {
        snapshot?.tool_execution_verified == true ? "工具有原生回执" : "工具结果未确认"
    }
    var conversationSessionID: String? {
        if let current = snapshot {
            return current.session_verified == true && current.session_id == previewSessionID ? previewSessionID : nil
        }
        return previewSessionID
    }
    var conversationPreview: [ConversationPreview] {
        // Display only: 120 verified turns from private same-session archive remain
        // while voice is playing; not a source of live DSH authority.
        // Old verified turns remain while the voice worker
        // restarts or its atomic snapshot temporarily has an empty list.
        // Never show a previous session's transcript during reconnect, or
        // use a stale preview to imply an unverified identity was trusted.
        if let current = snapshot {
            // A new/unverified session must never inherit another session's
            // private conversation, even for display-only retention.
            guard current.session_verified == true,
                  current.session_id == previewSessionID else { return [] }
            let fresh = current.conversation_preview ?? []
            return Array((lastVerifiedPreview.count >= fresh.count
                          ? lastVerifiedPreview : fresh).suffix(120))
        }
        // Private, verified same-session history is display-only.
        guard conversationSessionID != nil else { return [] }
        return Array(lastVerifiedPreview.suffix(120))
    }
    var activeTaskConversation: (String,[String])? {
        // The authoritative same-session, ongoing native task only.
        // Not the last assistant text, not a stale JSON, not a made-up stage.
        guard snapshotReadHealthy,
              let state=snapshot,state.session_verified==true,
              state.session_id==previewSessionID,
              let tid=state.current_task_id,!tid.isEmpty,
              let question=state.user_text,!question.isEmpty else {return nil}
        var entries=(state.turn_progress ?? []).filter({!$0.isEmpty && $0.count<=100})
        if entries.count>8 {entries=Array(entries.suffix(8))}
        if entries.isEmpty {entries=["正在等待已验证的任务进度"]}
        return (String(question.prefix(600)),entries)
    }
    var verifiedModelBadge: String {
        guard bothVerified, snapshot?.model_confirmed == true,
              snapshot?.model_selection_source == "dsh_native_session"
        else { return "模型待确认" }
        switch snapshot?.model_id {
        case "deepseek-flash": return "Flash"
        case "deepseek-v4-pro": return "Pro"
        default: return "模型待确认"
        }
    }
    var lastQuestion: String {
        let text = safe(snapshot?.user_text, maximum: 600)
        return text.isEmpty ? "尚无已核验的用户消息" : text
    }
    var lastAnswer: String {
        guard snapshot?.answer_verified == true else {
            return "等待同一会话中的真实回复与来源确认。"
        }
        let text = safe(snapshot?.answer_text, maximum: 2_000)
        return text.isEmpty ? "暂无已核验的回复内容" : text
    }
}

