// SPDX-License-Identifier: MIT
// Native macOS ESP32 companion: read-only model state + explicitly user-approved settings / E1b changes. No WebView, Mac mic, or paid calls.
import AppKit
import SwiftUI

struct CompanionStep: Decodable {
    let phase: String
    let label: String
}

struct ConversationPreview: Decodable {
    var speech_id: String? = nil
    let user: String
    let assistant: String
    let origin: String
    let progress: [String]?
}

private struct VerifiedConversationArchive: Decodable {
    let schema:Int
    let session_id:String
    let session_verified:Bool
    let turns:[ConversationPreview]
}

struct CompanionSnapshot: Decodable {
    let schema: Int
    let updated_at_unix: Double
    let phase: String
    let session_id: String?
    let session_verified: Bool?
    let model_id: String?
    let model_confirmed: Bool?
    let answer_origin: String?
    let answer_verified: Bool?
    let user_text: String?
    let answer_text: String?
    let answer_speech_id: String?
    let spoken_progress_text: String?
    let turn_progress: [String]?
    let current_task_id: String?
    let reasoning_observed: Bool?
    let steps: [CompanionStep]?
    let model_selection_source: String?
    let search_enabled: Bool?
    let search_supported: Bool?
    let board_battery_valid: Bool?
    let board_battery_percent: Int?
    let board_telemetry_at_unix: Double?
    let board_clock_hhmm: String?
    let wake_capability_verified: Bool?
    let voice_streaming_enabled: Bool?
    let voice_audio_diagnostics: String?
    // Only true after an actual DFSD3 user-write protocol handshake.
    // Current R121 has not provided this capability receipt.
    let screen_capture_status: String?
    let screen_capture_crc32: String?
    let sd_install_capability_verified: Bool?
    let tool_execution_verified: Bool?
    let last_outcome: String?
    let animation_id: String?
    let animation: String?
    let esp32_frame_motion_id: String?
    let esp32_frame_verified: Bool?
    let conversation_preview: [ConversationPreview]?
    let voice_preprocessor_last: String?
    let voice_preprocessor_original_chars: Int?
    let voice_preprocessor_spoken_chars: Int?
}

// Always derive counts from the bundled, SHA-tested catalog. A preserved
// 35-motion baseline is never a ceiling on future additions.
private enum MotionCatalogSummary {
    static let text:String = {
        guard let url=Bundle.main.url(forResource:"motion-catalog",withExtension:"json"),
              let data=try? Data(contentsOf:url),data.count<100_000,
              let raw=try? JSONSerialization.jsonObject(with:data) as? [String:Any],
              raw["schema"] as? Int == 1,
              let total=raw["count"] as? Int,total>0,total<10000,
              let selected=raw["selectedCount"] as? Int,selected>0,selected<=total,
              let entries=raw["motions"] as? [[String:Any]],entries.count==total,
              entries.filter({ $0["inCurrentPackage"] as? Bool == true }).count==selected
        else { return "素材清单不可用 · 请重新构建" }
        return "\(total) 个素材 · 已选 \(selected) 个（可继续增加）"
    }()
}

// Authenticated by the existing real ESP USB probes and the official DSH
// bind receipt from the *same* process. Never treat mere port presence as DSH.
private struct PhysicalDeviceLink: Decodable {
    let schema: Int
    let started_at_unix: Double
    let session_id: String
    let esp32_verified: Bool
    let selected35_verified: Bool
    let usb_port: String
    let voice_source: String
}

// R317: observed service status comes from the private read-only manager.
private struct CompanionServiceStatus: Decodable {
    let dsh_ready:Bool
    let dsh_running:Bool
    let voice_running:Bool
    let voice_verified:Bool
    let tts_ready:Bool
    let usb_present:Bool
    let lan_occupied:Bool
}
private struct CompanionServiceReceipt: Decodable {
    let ok:Bool
    let detail:String
    let status:CompanionServiceStatus?
}

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
        tool.executableURL=URL(fileURLWithPath:"/opt/homebrew/bin/python3.12")
        tool.arguments=[FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/Deepseek-live/companion-native/r109_service_manager.py").path,action]
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

// Semantic macOS system colors adapt automatically to light and dark mode.
// The device pixels stay unchanged; only Mac-native controls use this palette.
private enum DeepSeekPalette {
    static let background = Color(nsColor: .windowBackgroundColor)
    static let panel = Color(nsColor: .controlBackgroundColor)
    static let panelAlt = Color(nsColor: .underPageBackgroundColor)
    static let accent = Color(nsColor: .controlAccentColor)
    static let foreground = Color(nsColor: .labelColor)
    static let secondary = Color(nsColor: .secondaryLabelColor)
    static let border = Color(nsColor: .separatorColor)
}

// Device detection is a *hint*, never a proof of authenticated USB handshake.
// Reject ambiguous modems; the Python serial owner verifies ESP VID/PID.
enum ESPUSBSerialPresence {
    static func currentPort() -> String? {
        guard let names = try? FileManager.default.contentsOfDirectory(atPath: "/dev") else {
            return nil
        }
        let matches = names.filter { $0.hasPrefix("cu.usbmodem") }
                           .sorted()
        return matches.count == 1 ? "/dev/" + matches[0] : nil
    }
    static var detected: Bool { currentPort() != nil }
}
// Only structured, owner-local memory metadata enters the UI. Never load any
// Markdown fact bodies or infer memory has been enabled from missing files.
private struct MemoryEntryInfo: Decodable, Identifiable {
    let id_short: String
    let file_name: String
    let revision: Int
    let updated_at_unix: Double
    let source: String
    var id: String { file_name }
}
private struct AutoMemoryEntry: Decodable, Identifiable {
    let id: String
    let category: String
    let value: String
    let text: String
    let created_at: Double
    let source: String
}
private struct AutoMemoryList: Decodable {
    let schema: Int
    let items: [AutoMemoryEntry]
}
private struct VoiceMemoryCandidate: Decodable, Identifiable {
    let id: String
    let text: String
    let created_at: Double
}
private struct VoiceMemoryQueue: Decodable {
    let schema: Int
    let items: [VoiceMemoryCandidate]
}
private struct R308UnifiedMemoryItem: Decodable, Identifiable {
    let id: String
    let revision: Int
    let text: String
    let source: String
    let updated_at_unix: Double
    var originLabel: String {
        source == "verified_esp32_user_voice" ? "语音记住" : "手动添加"
    }
}
private struct MemoryOverviewSnapshot: Decodable {
    let schema: Int
    let source: String
    let generated_at_unix: Double
    let manual_write: Bool
    let auto_extraction: Bool
    let item_count: Int
    let recent: [MemoryEntryInfo]
    let redaction: String
    let vault_path: String?
}
@MainActor
private final class MemoryOverviewModel: ObservableObject {
    @Published private(set) var snapshot: MemoryOverviewSnapshot?
    @Published private(set) var notice = "尚未连接经授权的长期记忆库"
    @Published private(set) var preferencesExist = false
    @Published private(set) var candidates: [VoiceMemoryCandidate] = []
    @Published private(set) var automaticFacts: [AutoMemoryEntry] = []
    @Published private(set) var verifiedVoiceMode = "未读取到有效设置"
    @Published private(set) var voiceMode = "off"
    @Published private(set) var manualWriteAllowed = false
    @Published private(set) var manualCount: Int? = nil
    @Published private(set) var unifiedFacts: [R308UnifiedMemoryItem] = []
    @Published private(set) var manualStatusIssue = ""
    // The macOS user chooses access explicitly. Retain the scope only for
    // this App lifetime; never automatically ask for access or persist paths
    // to unrelated user volumes.
    private var selectedExternalDiskAccess: URL? = nil
    private var selectedExternalDiskScoped = false

    func requestExternalDiskAccess() {
        let panel=NSOpenPanel()
        panel.canChooseDirectories=true
        panel.canChooseFiles=false
        panel.allowsMultipleSelection=false
        panel.canCreateDirectories=false
        panel.prompt="选择并刷新"
        panel.message="请选择已连接的 ExtSSD 磁盘，允许大肥鱼查看本机记忆库。"
        let project=CompanionProjectPaths.rootURL.standardizedFileURL
        panel.directoryURL=project.deletingLastPathComponent()
        guard panel.runModal() == .OK, let chosen=panel.url else {return}
        let value=chosen.standardizedFileURL.resolvingSymlinksInPath().path
        let trusted=project.resolvingSymlinksInPath().path
        let allowed=[trusted,
                     (trusted as NSString).deletingLastPathComponent,
                     ((trusted as NSString).deletingLastPathComponent as NSString)
                         .deletingLastPathComponent]
        guard allowed.contains(value) else {
            manualStatusIssue="选择的不是大肥鱼项目磁盘，未更改访问范围。"
            return
        }
        if selectedExternalDiskScoped {
            selectedExternalDiskAccess?.stopAccessingSecurityScopedResource()
        }
        selectedExternalDiskScoped=chosen.startAccessingSecurityScopedResource()
        selectedExternalDiskAccess=chosen
        refresh()
    }

    private static let base = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("Library/Application Support/Deepseek-live")
    private static let overviewURL = base.appendingPathComponent("companion-native/memory-overview.json")
    private static let preferenceURL = base.appendingPathComponent("companion-local/user-preferences.json")
    private static let candidateURL = base.appendingPathComponent("companion-native/voice-memory-candidates.json")
    private static let automaticURL = base.appendingPathComponent("companion-native/memory-auto-v1.json")
    private static let voiceModeURL = base.appendingPathComponent("companion-native/memory-candidate-mode.json")

    private func safeRegularFile(_ url: URL, maxSize: Int) -> Bool {
        guard let values = try? url.resourceValues(forKeys: [.isRegularFileKey, .isSymbolicLinkKey]),
              values.isRegularFile == true, values.isSymbolicLink != true,
              let metadata = try? FileManager.default.attributesOfItem(atPath: url.path),
              let fileSize = metadata[.size] as? NSNumber,
              let permissions = metadata[.posixPermissions] as? NSNumber,
              permissions.intValue & 0o077 == 0,
              fileSize.intValue > 0 && fileSize.intValue <= maxSize else { return false }
        return true
    }

    // Query the actual E1b vault consent and count. The old overview JSON is a
    // cached metadata export, potentially several days old; it is not
    // authoritative for deciding whether a button is usable.
    private var memoryStatusRequestID = 0
    // Never block the SwiftUI MainActor while Node checks the signed E1b vault.
    // Permission flags remain closed until the latest trusted response arrives.
    private func readManualStatus() {
        memoryStatusRequestID += 1
        let requestID=memoryStatusRequestID
        manualWriteAllowed=false
        manualCount=nil
        unifiedFacts=[]
        manualStatusIssue="正在核验本机长期记忆…"
        DispatchQueue.global(qos:.userInitiated).async { [weak self] in
            let result=Self.fetchManualStatus()
            DispatchQueue.main.async { [weak self] in
                guard let self,self.memoryStatusRequestID==requestID else {return}
                self.applyManualStatus(result)
            }
        }
    }

    nonisolated private static func fetchManualStatus() -> Data? {
        let root=CompanionProjectPaths.rootURL
        let script=root.appendingPathComponent("scripts/r308_unified_memory.mjs")
        guard FileManager.default.fileExists(atPath:script.path) else {
            return Data("R308_DIAGNOSTIC_DISK_UNAVAILABLE".utf8)
        }
        let task=Process(),input=Pipe(),output=Pipe(),errors=Pipe()
        task.executableURL=URL(fileURLWithPath:"/opt/homebrew/bin/node")
        task.arguments=[script.path,"status"]
        task.currentDirectoryURL=root
        task.standardInput=input
        task.standardOutput=output
        task.standardError=errors
        do {
            try task.run()
            input.fileHandleForWriting.write(Data("{}".utf8))
            input.fileHandleForWriting.closeFile()
            // Drain the pipe BEFORE waitUntilExit: a vault with many items
            // can exceed the pipe's kernel buffer. Waiting first deadlocks
            // the background reader and leaves the memory list spinning.
            let bytes=output.fileHandleForReading.readDataToEndOfFile()
            let errorBytes=errors.fileHandleForReading.readDataToEndOfFile()
            task.waitUntilExit()
            if task.terminationStatus != 0 {
                let errorText=String(data:errorBytes.prefix(4096),encoding:.utf8) ?? ""
                if errorText.contains("memory_already_open") {
                    return Data("R308_DIAGNOSTIC_VAULT_LOCKED".utf8)
                }
                if errorText.localizedCaseInsensitiveContains("operation not permitted") ||
                   errorText.localizedCaseInsensitiveContains("permission denied") {
                    return Data("R308_DIAGNOSTIC_ACCESS_DENIED".utf8)
                }
                return Data("R308_DIAGNOSTIC_BACKEND_ERROR".utf8)
            }
            return bytes.count <= 100_000 ? bytes : Data("R308_DIAGNOSTIC_OVERSIZE".utf8)
        } catch {return Data("R308_DIAGNOSTIC_LAUNCH_ERROR".utf8)}
    }

    private func applyManualStatus(_ result:Data?) {
        let prefix="R308_UNIFIED_RESULT "
        let failureCode=result.flatMap{String(data:$0,encoding:.utf8)} ?? ""
        guard let bytes=result,
              let line=String(data:bytes,encoding:.utf8),
              line.hasPrefix(prefix),
              let payload=try? JSONSerialization.jsonObject(
                  with:Data(line.dropFirst(prefix.count).utf8)) as? [String:Any],
              payload["ok"] as? Bool == true,
              let count=payload["count"] as? Int,
              count>=0 && count<=128,
              let write=payload["manual_write"] as? Bool else {
            switch failureCode {
            case "R308_DIAGNOSTIC_VAULT_LOCKED":
                manualStatusIssue="记忆库被占用或上次异常退出留下锁。请稍后点击更新列表；持续出现时需要检查后台锁状态。"
            case "R308_DIAGNOSTIC_DISK_UNAVAILABLE", "R308_DIAGNOSTIC_ACCESS_DENIED":
                manualStatusIssue="项目磁盘未连接或应用没有访问权限。请点击「选择外接盘并授权」。"
            case "R308_DIAGNOSTIC_LAUNCH_ERROR":
                manualStatusIssue="本机记忆管理程序无法启动，请检查 Node 和项目安装状态。"
            default:
                manualStatusIssue="记忆库读取异常（非确认的权限问题）。请检查后台连接或数据完整性后重试。"
            }
            return
        }
        manualWriteAllowed=write
        manualCount=count
        manualStatusIssue=""
        guard let rows=payload["items"] as? [[String:Any]],
              rows.count==count,
              let json=try? JSONSerialization.data(withJSONObject:rows),
              let items=try? JSONDecoder().decode(
                  [R308UnifiedMemoryItem].self,from:json),
              items.allSatisfy({row in
                row.id.range(
                    of:#"^[a-f0-9]{8}-[a-f0-9]{4}-[1-8][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$"#,
                    options:.regularExpression) != nil &&
                row.revision>=1 && row.revision<=10000 &&
                row.text.count>0 && row.text.count<=512 &&
                ["user_explicit","verified_esp32_user_voice"].contains(row.source) &&
                row.updated_at_unix.isFinite
              }) else {
            manualStatusIssue="记忆已连接，但列表读取异常；请刷新后再保存。"
            manualWriteAllowed=false
            return
        }
        unifiedFacts=items.sorted{$0.updated_at_unix>$1.updated_at_unix}
    }

    func removeUnifiedFact(id:String,revision:Int)->String {
        guard unifiedFacts.contains(where:{$0.id==id&&$0.revision==revision}) else {
            return "记忆编号已变化，请刷新后重试"
        }
        let root=CompanionProjectPaths.rootURL
        let script=root.appendingPathComponent("scripts/r308_unified_memory.mjs")
        guard FileManager.default.fileExists(atPath:script.path),
              let data=try? JSONSerialization.data(withJSONObject:[
                "id":id,"revision":revision,"confirm":"确认删除这一条记忆"]) else {
            return "记忆管理程序不可用"
        }
        let task=Process(),input=Pipe(),output=Pipe()
        task.executableURL=URL(fileURLWithPath:"/opt/homebrew/bin/node")
        task.arguments=[script.path,"remove"]
        task.currentDirectoryURL=root
        task.standardInput=input
        task.standardOutput=output
        task.standardError=Pipe()
        do {
            try task.run()
            input.fileHandleForWriting.write(data)
            input.fileHandleForWriting.closeFile()
            task.waitUntilExit()
            let result=output.fileHandleForReading.readDataToEndOfFile()
            let prefix="R308_UNIFIED_RESULT "
            guard task.terminationStatus==0,result.count<1024,
                  let line=String(data:result,encoding:.utf8),
                  line.hasPrefix(prefix),
                  let json=try? JSONSerialization.jsonObject(
                    with:Data(line.dropFirst(prefix.count).utf8)) as? [String:Any],
                  json["ok"] as? Bool == true,
                  json["removed"] as? Bool == true else {
                return "本机没有确认删除，请刷新后再试"
            }
            refresh()
            return "已从统一记忆中删除这一条（其他历史备份不在此操作范围）"
        } catch{return "记忆管理操作失败"}
    }

    func setVoiceMode(_ requested: String) -> String {
        guard ["off","auto","review"].contains(requested),
              let folder = Optional(Self.voiceModeURL.deletingLastPathComponent()),
              let attrs = try? FileManager.default.attributesOfItem(atPath:folder.path),
              let folderMode = attrs[.posixPermissions] as? NSNumber,
              folderMode.intValue & 0o077 == 0,
              !(FileManager.default.fileExists(atPath:Self.voiceModeURL.path) &&
                  !safeRegularFile(Self.voiceModeURL,maxSize:512)),
              let data = try? JSONSerialization.data(
                    withJSONObject:["schema":1,"mode":requested]) else {
            return "设置没有通过本机隐私检查，未改变"
        }
        do {
            try data.write(to:Self.voiceModeURL,options:.atomic)
            try FileManager.default.setAttributes([.posixPermissions:0o600],
                ofItemAtPath:Self.voiceModeURL.path)
            refresh()
            guard voiceMode == requested else {return "未能确认保存，原设置仍需核对"}
            return "语音记忆设置已保存"
        } catch {return "设置写入失败，请检查本机权限"}
    }

    func discardCandidate(id: String) -> String {
        guard id.range(of:#"^[a-f0-9]{32}$"#,
                       options:.regularExpression) != nil else {
            return "无效的候选编号"
        }
        let root=CompanionProjectPaths.rootURL
        let script=root.appendingPathComponent("scripts/r307_voice_review_admin.py")
        guard FileManager.default.fileExists(atPath:script.path) else {
            return "审核管理程序不可用"
        }
        let task=Process(), output=Pipe()
        task.executableURL=URL(fileURLWithPath:"/opt/homebrew/bin/python3.12")
        task.arguments=[script.path,"discard",id]
        task.currentDirectoryURL=root
        task.standardOutput=output
        task.standardError=Pipe()
        do {
            try task.run();task.waitUntilExit()
            let bytes=output.fileHandleForReading.readDataToEndOfFile()
            guard task.terminationStatus == 0, bytes.count < 1024,
                  let response=try? JSONSerialization.jsonObject(
                    with:bytes) as? [String:Any],
                  response["removed"] as? Bool == true else {
                return "候选未处理，请刷新列表后重试"
            }
            refresh()
            return "这条建议已从待审核列表移除"
        } catch {return "本机审核操作失败"}
    }

    func refreshCandidates() {
        candidates = []
        if safeRegularFile(Self.candidateURL,maxSize:32768),
           let raw = try? Data(contentsOf:Self.candidateURL),
           let list = try? JSONDecoder().decode(VoiceMemoryQueue.self,from:raw),
           list.schema == 1 && list.items.count <= 24 {
            candidates=list.items.filter {
                $0.text.count > 0 && $0.text.count <= 200 &&
                $0.created_at <= Date().timeIntervalSince1970 + 5 &&
                Date().timeIntervalSince1970 - $0.created_at <= 14*86400
            }
        }
    }

    func refresh() {
        readManualStatus()
        voiceMode = "off"
        verifiedVoiceMode = "未读取到有效设置（不会自动保存）"
        if safeRegularFile(Self.voiceModeURL,maxSize:512),
           let data = try? Data(contentsOf:Self.voiceModeURL),
           let obj = try? JSONSerialization.jsonObject(with:data) as? [String:Any],
           obj["schema"] as? Int == 1,
           let mode = obj["mode"] as? String {
            switch mode {
            case "auto":
                voiceMode = "auto"
                verifiedVoiceMode = "自动保存少量明确的称呼与喜好（不经审核）"
            case "review":
                voiceMode = "review"
                verifiedVoiceMode = "从日常语音整理建议，由我逐条审核"
            default:
                voiceMode = "off"
                verifiedVoiceMode = "不从语音自动保存"
            }
        }
        preferencesExist = safeRegularFile(Self.preferenceURL, maxSize: 8192)
        refreshCandidates()
        automaticFacts = []
        snapshot = nil
        notice = "尚未连接经授权的长期记忆库"
        let url = Self.overviewURL
        guard safeRegularFile(url, maxSize: 16384),
              let data = try? Data(contentsOf: url),
              let overview = try? JSONDecoder().decode(MemoryOverviewSnapshot.self, from: data),
              overview.schema == 1, overview.source == "e1b_manual_memory",
              overview.redaction == "metadata_only_no_content",
              overview.auto_extraction == false, overview.item_count >= 0,
              overview.item_count <= 128, overview.recent.count <= 12,
              overview.recent.count <= overview.item_count,
              overview.generated_at_unix.isFinite,
              overview.generated_at_unix <= Date().timeIntervalSince1970 + 5 else { return }
        snapshot = overview
        if Date().timeIntervalSince1970 - overview.generated_at_unix > 86400 {
            notice = "摘要超过24小时未更新，建议核对原始记忆库"
        } else {
            notice = "仅展示文件元信息，正文默认隐藏"
        }
    }

    // Only a user's actual button confirmation can reach this trusted one-shot
    // E1b command. Never called by a model event, timer, or voice transcript.
    func performConfirmed(_ action: String, text: String, confirmation: String) -> String {
        guard ["consent", "save"].contains(action), text.count <= 1024,
              let data = try? JSONSerialization.data(withJSONObject: [
                "text": text, "confirm": confirmation
              ].filter { action == "save" || $0.key == "confirm" }) else {
            return "参数无效，未作任何修改"
        }
        let executable = URL(fileURLWithPath: "/opt/homebrew/bin/node")
        let project = CompanionProjectPaths.rootURL
        let script = project.appendingPathComponent("scripts/r32_native_memory_action.mjs")
        guard FileManager.default.fileExists(atPath: executable.path),
              FileManager.default.fileExists(atPath: script.path) else {
            return "记忆管理程序不可用"
        }
        let task = Process()
        task.executableURL = executable
        task.arguments = [script.path, action]
        task.currentDirectoryURL = project
        let input = Pipe()
        let output = Pipe()
        task.standardInput = input
        task.standardOutput = output
        task.standardError = Pipe()
        do {
            try task.run()
            input.fileHandleForWriting.write(data)
            input.fileHandleForWriting.closeFile()
            task.waitUntilExit()
            guard task.terminationStatus == 0 else {
                return "操作失败；请检查用户许可和记忆库状态"
            }
            let result = output.fileHandleForReading.readDataToEndOfFile()
            let prefix="NATIVE_MEMORY_RESULT "
            guard result.count < 2048,
                  let line=String(data:result,encoding:.utf8),
                  line.hasPrefix(prefix),
                  let status=try? JSONSerialization.jsonObject(
                    with:Data(line.dropFirst(prefix.count).utf8)) as? [String:Any],
                  status["ok"] as? Bool == true,
                  status["action"] as? String == action,
                  status["manual_write"] as? Bool == true,
                  status.keys.contains("revision") else {
                return "记忆库没有返回可核实的保存结果，请刷新后核对，避免重复保存"
            }
            if action=="save" &&
               ((status["revision"] as? Int) ?? 0) < 1 {
                return "记忆库没有返回有效版本号，请刷新后核对"
            }
            refresh()
            return action == "consent" ? "已允许逐条手动保存" : "已保存这条明确确认的本地记忆"
        } catch {
            return "记忆管理程序启动失败"
        }
    }

    // One user-initiated deletion, never from voice/model actions.
    func removeAutomaticFact(id: String) -> String {
        guard id.range(of:#"^[a-f0-9]{32}$"#,options:.regularExpression) != nil,
              let script=Optional(URL(fileURLWithPath:
                CompanionProjectPaths.script("r38_memory_admin.py"))),
              FileManager.default.fileExists(atPath:script.path) else {
            return "记忆条目无效"
        }
        let task=Process()
        task.executableURL=URL(fileURLWithPath:"/opt/homebrew/bin/python3.12")
        task.arguments=[script.path,"remove",id]
        task.currentDirectoryURL=script.deletingLastPathComponent().deletingLastPathComponent()
        let output=Pipe();task.standardOutput=output;task.standardError=Pipe()
        do {
            try task.run();task.waitUntilExit()
            let result=output.fileHandleForReading.readDataToEndOfFile()
            guard task.terminationStatus==0,
                  let obj=try? JSONSerialization.jsonObject(with:result) as? [String:Any],
                  obj["removed"] as? Bool == true else { return "删除未被本地记忆库确认" }
            refresh()
            return "已从大肥鱼本机自动记忆库删除该条。其他备份不包含在此操作中。"
        }catch{return "无法执行本机记忆删除"}
    }
    func revealPreferences() {
        guard safeRegularFile(Self.preferenceURL, maxSize: 8192) else { return }
        NSWorkspace.shared.activateFileViewerSelecting([Self.preferenceURL])
    }

    func revealMemoryFile(_ entry: MemoryEntryInfo) {
        guard let overview = snapshot, let directory = overview.vault_path,
              directory.hasPrefix(CompanionProjectPaths.rootURL.path+"/"),
              entry.file_name.range(
                of: #"^[0-9a-fA-F-]{36}\.md$"#,
                options: .regularExpression) != nil else { return }
        let fileURL = URL(fileURLWithPath: directory, isDirectory: true)
            .appendingPathComponent(entry.file_name)
        let resolved = fileURL.resolvingSymlinksInPath()
        guard resolved.path.hasPrefix(CompanionProjectPaths.rootURL.path+"/"),
              safeRegularFile(fileURL, maxSize: 8193) else { return }
        NSWorkspace.shared.activateFileViewerSelecting([fileURL])
    }
}

// R307: simple owner-facing information architecture, replacing the 650pt
// dense technical memory inventory. Full content stays private on this Mac.
private enum R307MemoryTab: String, CaseIterable, Identifiable {
    case saved = "已记住"
    case add = "添加记忆"
    case review = "记忆建议"
    case growth = "人格成长"
    var id: Self {self}
}

struct MemoryOverviewSheet: View {
    @StateObject private var model = MemoryOverviewModel()
    @Binding var isPresented: Bool
    var embedded: Bool = false
    @State private var selectedTab:R307MemoryTab = .saved
    @State private var draft = ""
    @State private var actionNotice = ""
    @State private var inlineSaveStep = "idle" // idle / consent / save
    @State private var pendingUnifiedDelete: R308UnifiedMemoryItem? = nil
    @State private var pendingVoiceDismiss: VoiceMemoryCandidate? = nil
    @State private var fromVoiceCandidateID:String? = nil
    @State private var fromVoiceCandidateText:String? = nil
    @State private var showTechnicalFiles = false

    private var manualDisplayCount:String {
        model.manualCount.map(String.init) ?? "未能读取"
    }
    private var readyToSave: Bool {
        !draft.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty &&
        draft.count <= 512
    }

    private var pageHeader: some View {
        VStack(alignment:.leading,spacing:13) {
            HStack(alignment:.top) {
                VStack(alignment:.leading,spacing:4) {
                    Label("大肥鱼的本地记忆",systemImage:"brain.head.profile")
                        .font(.system(size:22,weight:.semibold))
                        .foregroundStyle(DeepSeekPalette.foreground)
                    Text("记录你想让大肥鱼记住的事，所有保存操作都在这台 Mac 上进行。")
                        .font(.system(size:13))
                        .foregroundStyle(DeepSeekPalette.secondary)
                }
                Spacer()
                Button("更新列表",systemImage:"arrow.clockwise"){model.refresh()}
                    .buttonStyle(.bordered)
                    .help("重新读取这台Mac已经保存的记忆和待审核内容")
                    .accessibilityLabel("更新本机记忆列表")
                if !embedded {
                    Button("关闭"){isPresented=false}
                        .buttonStyle(.bordered)
                }
            }
            HStack(spacing:16) {
                VStack(alignment:.leading,spacing:3) {
                    Text("大肥鱼已记住")
                        .font(.system(size:13)).foregroundStyle(DeepSeekPalette.secondary)
                    Text(manualDisplayCount + " 条")
                        .font(.system(size:22,weight:.semibold))
                }
                Divider().frame(height:34)
                VStack(alignment:.leading,spacing:3) {
                    Text("待你确认")
                        .font(.system(size:13)).foregroundStyle(DeepSeekPalette.secondary)
                    Text("\(model.candidates.count) 条")
                        .font(.system(size:22,weight:.semibold))
                }
                Spacer()
                if !model.candidates.isEmpty && selectedTab != .review {
                    Button("查看待审核（\(model.candidates.count)）",systemImage:"text.badge.checkmark") {
                        selectedTab = .review
                        model.refreshCandidates()
                    }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.large)
                    .accessibilityIdentifier("r673-open-voice-memory-review")
                } else if selectedTab == .saved {
                    Button("添加一条记忆",systemImage:"plus") {
                        selectedTab = .add
                    }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.large)
                }
            }
            .padding(.horizontal,18)
            .padding(.vertical,16)
            .background(DeepSeekPalette.panelAlt,
                        in:RoundedRectangle(cornerRadius:14))
            Picker("记忆操作",selection:$selectedTab) {
                ForEach(R307MemoryTab.allCases){tab in
                    Text(tab.rawValue).tag(tab)
                }
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .controlSize(.large)
        }
    }

    private var savedPage:some View {
        VStack(alignment:.leading,spacing:16) {
            if let pending=model.candidates.first {
                VStack(alignment:.leading,spacing:9) {
                    Label("有 \(model.candidates.count) 条语音记忆等待确认",systemImage:"brain.head.profile")
                        .font(.system(size:15,weight:.semibold))
                    Text(pending.text).font(.system(size:15)).textSelection(.enabled)
                    Text("只生成了待审记录，尚未写入长期记忆。")
                        .font(.system(size:12)).foregroundStyle(DeepSeekPalette.secondary)
                    Button("立即审核这条语音记忆") {
                        model.refreshCandidates()
                        selectedTab = .review
                    }
                    .buttonStyle(.borderedProminent)
                    .accessibilityIdentifier("r673-memory-review-from-saved")
                }
                .frame(maxWidth:.infinity,alignment:.leading)
                .padding(16)
                .background(DeepSeekPalette.panelAlt,
                            in:RoundedRectangle(cornerRadius:14))
            }
            HStack(alignment:.firstTextBaseline) {
                Text("大肥鱼记住的事")
                    .font(.system(size:18,weight:.semibold))
                Spacer()
                Text("手动添加和语音记住的内容统一保存在这里")
                    .font(.system(size:13)).foregroundStyle(DeepSeekPalette.secondary)
            }
            if model.manualCount == nil || !model.manualStatusIssue.isEmpty {
                Label(model.manualStatusIssue.isEmpty ?
                      "暂时无法读取本机记忆库，请检查外置项目磁盘后点击刷新。" :
                      model.manualStatusIssue,
                      systemImage:"externaldrive.badge.exclamationmark")
                    .font(.system(size:13))
                    .foregroundStyle(DeepSeekPalette.secondary)
                    .padding(18)
                    .frame(maxWidth:.infinity,alignment:.leading)
            } else if model.unifiedFacts.isEmpty {
                VStack(alignment:.leading,spacing:12) {
                    Label("还没有保存的记忆",systemImage:"book.closed")
                        .font(.system(size:15,weight:.medium))
                    Text("点击上方「添加一条记忆」，写下一件希望大肥鱼记住的事。")
                        .font(.system(size:13)).foregroundStyle(DeepSeekPalette.secondary)
                }
                .padding(18)
                .frame(maxWidth:.infinity,alignment:.leading)
                .background(DeepSeekPalette.panel,
                            in:RoundedRectangle(cornerRadius:14))
            } else {
                LazyVStack(alignment:.leading,spacing:10) {
                    ForEach(model.unifiedFacts) { entry in
                        HStack(alignment:.top,spacing:14) {
                            Image(systemName:"checkmark.circle.fill")
                                .foregroundStyle(DeepSeekPalette.accent)
                                .padding(.top,3)
                            VStack(alignment:.leading,spacing:8) {
                                Text(entry.text)
                                    .font(.system(size:14))
                                    .textSelection(.enabled)
                                    .frame(maxWidth:.infinity,alignment:.leading)
                                Text(entry.originLabel)
                                    .font(.system(size:13))
                                    .foregroundStyle(DeepSeekPalette.secondary)
                            }
                            Spacer(minLength:8)
                            Button("删除",role:.destructive){
                                pendingUnifiedDelete=entry
                            }
                            .buttonStyle(.bordered)
                        }
                        .padding(16)
                        .background(DeepSeekPalette.panel,
                                    in:RoundedRectangle(cornerRadius:14))
                    }
                }
            }
            DisclosureGroup("以后从语音中记住新内容") {
                VStack(alignment:.leading,spacing:10) {
                    Text(model.voiceMode == "auto" ?
                         "只会直接保存少量明确的称呼和喜好；其他内容不会自动保存。" :
                         model.voiceMode == "review" ?
                         "只整理待审核建议，确认后才会保存；也可以手动添加。" :
                         "当前不从语音收集记忆；仍可以手动添加。")
                        .font(.system(size:13))
                        .foregroundStyle(DeepSeekPalette.secondary)
                    Picker("语音记忆方式",
                           selection:Binding(get:{model.voiceMode},
                                             set:{actionNotice=model.setVoiceMode($0)})) {
                        Text("直接保存少量明确偏好").tag("auto")
                        Text("整理日常聊天，先让我审核").tag("review")
                        Text("关闭语音记忆").tag("off")
                    }
                    Text("当前：\(model.verifiedVoiceMode)。只分析可信设备上的新语音，不回扫历史聊天。")
                        .font(.system(size:13))
                        .foregroundStyle(DeepSeekPalette.secondary)
                }
                .padding(.top,10)
            }
            .font(.system(size:13,weight:.medium))
            .padding(.horizontal,4)
        }
    }

    private var addPage:some View {
        VStack(alignment:.leading,spacing:16) {
            Text("写下一件希望大肥鱼记住的事")
                .font(.system(size:18,weight:.semibold))
            Text("例如常用设备、喜欢的饮品或一项明确的个人偏好。一次只保存一条，内容不会自动上传或从聊天中提取。")
                .font(.system(size:13))
                .foregroundStyle(DeepSeekPalette.secondary)
                .fixedSize(horizontal:false,vertical:true)
            VStack(alignment:.leading,spacing:10) {
                Text("要记住的内容")
                    .font(.system(size:13,weight:.medium))
                TextField("例如：我偏好酸甜均衡的手冲咖啡",
                          text:$draft,axis:.vertical)
                    .lineLimit(3...6)
                    .textFieldStyle(.roundedBorder)
                    .font(.system(size:15))
                    .accessibilityIdentifier("r307-manual-memory-input")
                    .onChange(of:draft){_,_ in
                        inlineSaveStep="idle"
                    }
                HStack {
                    Text("建议写成完整的一句话。仅此条内容会被保存。")
                        .font(.system(size:13))
                        .foregroundStyle(DeepSeekPalette.secondary)
                    Spacer()
                    Text("\(draft.count)/512")
                        .font(.system(size:12,design:.monospaced))
                        .foregroundStyle(draft.count>512 ? .red :
                            DeepSeekPalette.secondary)
                }
                if let id=fromVoiceCandidateID,!id.isEmpty {
                    Label("这条内容来自待审核语音记录，保存成功后会从待处理列表移除。",
                          systemImage:"checkmark.shield")
                        .font(.system(size:13))
                        .foregroundStyle(DeepSeekPalette.secondary)
                }
            }
            .padding(18)
            .background(DeepSeekPalette.panel,
                        in:RoundedRectangle(cornerRadius:14))

            VStack(alignment:.leading,spacing:12) {
                HStack(spacing:10) {
                    Image(systemName:model.manualWriteAllowed ?
                          "checkmark.shield.fill":"lock.shield")
                        .foregroundStyle(model.manualWriteAllowed ?
                            DeepSeekPalette.accent:DeepSeekPalette.secondary)
                    Text(model.manualCount == nil ? "本机记忆库尚未连接" :
                         model.manualWriteAllowed ? "可以直接保存到本机记忆" :
                         "首次保存需要先授权")
                        .font(.system(size:13,weight:.medium))
                    Spacer()
                    if model.manualCount == nil || !model.manualStatusIssue.isEmpty {
                        Button("检查记忆库连接"){model.refresh()}
                            .buttonStyle(.bordered)
                            .help("重新读取记忆库真实状态，不新增任何记忆")
                    }
                    if model.manualCount == nil {
                        Button("选择外接盘并授权"){
                            model.requestExternalDiskAccess()
                        }
                        .buttonStyle(.bordered)
                        .help("由你选择 ExtSSD，macOS 决定是否要求访问许可")
                    }
                }
                if model.manualCount == nil {
                    Text(model.manualStatusIssue)
                        .font(.system(size:13))
                        .foregroundStyle(.red)
                } else if !model.manualStatusIssue.isEmpty {
                    Text(model.manualStatusIssue)
                        .font(.system(size:13))
                        .foregroundStyle(DeepSeekPalette.secondary)
                }
                Button("保存这条记忆") {
                    guard readyToSave else {return}
                    inlineSaveStep = model.manualWriteAllowed ? "save" : "consent"
                    actionNotice = ""
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .disabled(!readyToSave || model.manualCount == nil)
                .accessibilityIdentifier("r309-manual-memory-save")
                if !readyToSave {
                    Text(draft.count>512 ? "超过512字，请缩短后保存。" :
                         "输入文字后，「保存这条记忆」即可点击。")
                        .font(.system(size:13))
                        .foregroundStyle(DeepSeekPalette.secondary)
                }
                if inlineSaveStep == "consent" {
                    VStack(alignment:.leading,spacing:10) {
                        Label("首次使用需要授权",systemImage:"lock.shield")
                            .font(.system(size:14,weight:.semibold))
                        Text("仅允许你逐条确认后保存到这台 Mac，不会自动收集聊天。授权成功后再确认本条内容。")
                            .font(.system(size:13))
                            .foregroundStyle(DeepSeekPalette.secondary)
                        HStack {
                            Button("同意开启手动保存") {
                                let result=model.performConfirmed("consent",
                                   text:"",confirmation:"同意手动保存")
                                actionNotice=result
                                if result.hasPrefix("已允许") {
                                    inlineSaveStep="save"
                                }
                            }
                            .buttonStyle(.borderedProminent)
                            Button("取消"){inlineSaveStep="idle"}
                                .buttonStyle(.bordered)
                        }
                    }
                    .padding(14)
                    .background(DeepSeekPalette.panel,
                        in:RoundedRectangle(cornerRadius:12))
                } else if inlineSaveStep == "save" {
                    VStack(alignment:.leading,spacing:10) {
                        Label("确认保存当前输入的这一条？",
                              systemImage:"checkmark.shield")
                            .font(.system(size:14,weight:.semibold))
                        Text("本次只保存输入框中的文字，成功后显示在「已记住」。")
                            .font(.system(size:13))
                            .foregroundStyle(DeepSeekPalette.secondary)
                        HStack {
                            Button("确认保存这一条记忆") {
                                let savedText=draft.trimmingCharacters(
                                    in:.whitespacesAndNewlines)
                                let unchanged=savedText == fromVoiceCandidateText
                                let result=model.performConfirmed("save",
                                     text:draft,confirmation:"确认保存这一条")
                                actionNotice=result
                                if result.hasPrefix("已保存") {
                                    draft=""
                                    if let id=fromVoiceCandidateID,unchanged {
                                        let followup=model.discardCandidate(id:id)
                                        if !followup.hasPrefix("这条建议已") {
                                            actionNotice=result+"；"+followup
                                        }
                                    } else if fromVoiceCandidateID != nil {
                                        actionNotice=result+"；原候选内容已修改，请另行处理原待审记录"
                                    }
                                    fromVoiceCandidateID=nil
                                    fromVoiceCandidateText=nil
                                    inlineSaveStep="idle"
                                    selectedTab = .saved
                                }
                            }
                            .buttonStyle(.borderedProminent)
                            .disabled(!readyToSave)
                            Button("取消"){inlineSaveStep="idle"}
                                .buttonStyle(.bordered)
                        }
                    }
                    .padding(14)
                    .background(DeepSeekPalette.panel,
                        in:RoundedRectangle(cornerRadius:12))
                }
            }
            .padding(16)
            .background(DeepSeekPalette.panelAlt,
                        in:RoundedRectangle(cornerRadius:14))
            Text("保存位置：Mac 本机长期记忆库。它与大肥鱼的说话风格设置相互独立，保存后也不会自动读取所有聊天记录。")
                .font(.system(size:13))
                .foregroundStyle(DeepSeekPalette.secondary)
            Spacer(minLength:12)
        }
    }

    private var reviewPage:some View {
        VStack(alignment:.leading,spacing:16) {
            Text("等你确认的语音记忆")
                .font(.system(size:18,weight:.semibold))
            Text("大肥鱼会从可信语音中整理长期偏好、计划与生活习惯，类似内容合并为建议。只有你确认保存后才会进入长期记忆。")
                .font(.system(size:13))
                .foregroundStyle(DeepSeekPalette.secondary)
            if model.candidates.isEmpty {
                VStack(alignment:.leading,spacing:10) {
                    Label("目前没有待审核的语音记录",systemImage:"checkmark.circle")
                        .font(.system(size:15,weight:.medium))
                    Text("说说日常习惯、正在推进的计划或长期喜好；也可随时到「添加记忆」手动填写。")
                        .font(.system(size:13))
                        .foregroundStyle(DeepSeekPalette.secondary)
                }
                .frame(maxWidth:.infinity,alignment:.leading)
                .padding(18)
                .background(DeepSeekPalette.panel,
                            in:RoundedRectangle(cornerRadius:14))
            } else {
                ForEach(model.candidates) { item in
                    VStack(alignment:.leading,spacing:11) {
                        Text(item.text).font(.system(size:15))
                        Text("来自可信语音 · 仅供审核，尚未保存")
                            .font(.system(size:13))
                            .foregroundStyle(DeepSeekPalette.secondary)
                        HStack(spacing:10) {
                            Button("查看并保存到长期记忆") {
                                draft=item.text
                                fromVoiceCandidateID=item.id
                                fromVoiceCandidateText=item.text
                                selectedTab = .add
                            }
                            .buttonStyle(.borderedProminent)
                            Button("忽略这条"){pendingVoiceDismiss=item}
                                .buttonStyle(.bordered)
                        }
                    }
                    .frame(maxWidth:.infinity,alignment:.leading)
                    .padding(16)
                    .background(DeepSeekPalette.panel,
                                in:RoundedRectangle(cornerRadius:14))
                }
            }
            Spacer(minLength:12)
        }
    }

    var body:some View {
        VStack(alignment:.leading,spacing:0) {
            pageHeader
                .padding(22)
            Divider()
            ScrollView {
                Group {
                    switch selectedTab {
                    case .saved: savedPage
                    case .add: addPage
                    case .review: reviewPage
                    case .growth: BridgeGrowthReviewSheet(
                        isPresented:.constant(false),embedded:true)
                    }
                }
                .frame(maxWidth:.infinity,alignment:.leading)
                .padding(22)
            }
            .frame(maxWidth:.infinity,maxHeight:.infinity)
            Divider()
            HStack(spacing:10) {
                Image(systemName:"lock.shield")
                    .foregroundStyle(DeepSeekPalette.secondary)
                Text(actionNotice.isEmpty ?
                     "记忆保存在这台 Mac；删除本机记录不代表删除其他历史或备份。" :
                     actionNotice)
                    .font(.system(size:13))
                    .foregroundStyle(DeepSeekPalette.secondary)
                    .lineLimit(2)
                Spacer(minLength:10)
            }
            .padding(.horizontal,22)
            .padding(.vertical,12)
        }
        .frame(width:embedded ? nil : 760,height:embedded ? nil : 715)
        .frame(maxWidth:embedded ? .infinity : nil,
               maxHeight:embedded ? .infinity : nil)
        .background(DeepSeekPalette.background)
        .onAppear {
            model.refresh()
            // When a real pending suggestion exists, land on the review
            // action instead of the default saved list. Do not auto-approve.
            if !model.candidates.isEmpty { selectedTab = .review }
        }
        .onReceive(Timer.publish(every:4,on:.main,in:.common).autoconnect()) { _ in
            // R673: a Wi-Fi voice proposal may arrive while this page stays
            // on 已记住. Poll the private review queue regardless of tab,
            // without writing memory or interrupting an in-progress form.
            let previouslyEmpty = model.candidates.isEmpty
            model.refreshCandidates()
            if previouslyEmpty && !model.candidates.isEmpty && selectedTab == .saved {
                selectedTab = .review
            }
        }
        .confirmationDialog("忽略这条待审核语音记忆？",
                            isPresented:Binding(get:{pendingVoiceDismiss != nil},
                                set:{if !$0 {pendingVoiceDismiss=nil}})) {
            Button("从待审核中移除",role:.destructive) {
                if let item=pendingVoiceDismiss {
                    actionNotice=model.discardCandidate(id:item.id)
                }
                pendingVoiceDismiss=nil
            }
            Button("取消",role:.cancel){pendingVoiceDismiss=nil}
        } message: {
            Text("这条候选还没有保存为长期记忆；忽略只会移除这一条待审核记录。")
        }
        .confirmationDialog("确认删除这一条记忆？",
                            isPresented:Binding(get:{pendingUnifiedDelete != nil},
                                set:{if !$0 {pendingUnifiedDelete=nil}})) {
            Button("删除这一条记忆",role:.destructive) {
                if let entry=pendingUnifiedDelete {
                    actionNotice=model.removeUnifiedFact(
                        id:entry.id,revision:entry.revision)
                }
                pendingUnifiedDelete=nil
            }
            Button("取消",role:.cancel){pendingUnifiedDelete=nil}
        } message: {
            Text("将从 Mac 统一记忆库删除此条。以前的对话与备份不受影响。")
        }
    }
}

// R307: keep the actual private, on-disk voice-memory policy in one place
// across both the compact settings panel and the native Preferences sheet.
// NSImageView honours animated GIF frames. SwiftUI Image(nsImage:) only
// reliably shows a still thumbnail on some macOS versions.
struct PrivateMotionPlayer: NSViewRepresentable {
    let url: URL

    func makeNSView(context: Context) -> NSView {
        // A naked NSImageView adopts the GIF's 240px intrinsic size and can
        // escape SwiftUI's 156x156 frame. Explicit AppKit clipping/constraints
        // keep the approved animated character INSIDE its own display card.
        let clip = NSView(frame: NSRect(x: 0, y: 0, width: 156, height: 156))
        clip.wantsLayer = true
        clip.layer?.masksToBounds = true
        clip.layer?.cornerRadius = 10
        let motion = NSImageView(frame: clip.bounds)
        motion.translatesAutoresizingMaskIntoConstraints = false
        motion.imageScaling = .scaleProportionallyUpOrDown
        motion.imageAlignment = .alignCenter
        motion.animates = true
        motion.setContentHuggingPriority(.defaultLow, for: .horizontal)
        motion.setContentHuggingPriority(.defaultLow, for: .vertical)
        motion.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        motion.setContentCompressionResistancePriority(.defaultLow, for: .vertical)
        clip.addSubview(motion)
        NSLayoutConstraint.activate([
            motion.leadingAnchor.constraint(equalTo: clip.leadingAnchor),
            motion.trailingAnchor.constraint(equalTo: clip.trailingAnchor),
            motion.topAnchor.constraint(equalTo: clip.topAnchor),
            motion.bottomAnchor.constraint(equalTo: clip.bottomAnchor)
        ])
        return clip
    }

    func updateNSView(_ view: NSView, context: Context) {
        guard let motion = view.subviews.first as? NSImageView else { return }
        // Private GIF asset revisions are atomically swapped by the builder.
        // Invalidate the AppKit image on mtime changes instead of displaying
        // the cached old/dithered frame until the whole app restarts.
        let resourceValues = try? url.resourceValues(forKeys: [.contentModificationDateKey])
        let modified = resourceValues?.contentModificationDate?.timeIntervalSince1970 ?? 0
        let identity = url.path + "@" + String(modified)
        if motion.toolTip != identity {
            motion.image = NSImage(contentsOf: url)
            motion.toolTip = identity
            motion.animates = true
        }
    }

    static func dismantleNSView(_ view: NSView, coordinator: ()) {
        (view.subviews.first as? NSImageView)?.image = nil
    }
}

// Explicit user preference ONLY. It never enables a Mac microphone and never
// claims ESP32 has the corresponding on-device WakeNet model installed.
struct ESPWakeSettingsSheet: View {
    @Binding var isPresented: Bool
    let hardwareReady: Bool
    @State private var phrase = "你好大肥鱼"
    @State private var notice = ""
    private let choices = ["你好大肥鱼", "大肥鱼"]
    private var preferenceURL: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/Deepseek-live/companion-native/esp-wake-preferences.json")
    }
    private func readPreference() {
        guard let data = try? Data(contentsOf: preferenceURL),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              obj["schema"] as? Int == 1,
              let saved = obj["requested_phrase"] as? String,
              choices.contains(saved) else { return }
        phrase = saved
    }
    private func savePreference() {
        let target = preferenceURL
        do {
            let parent = target.deletingLastPathComponent()
            try FileManager.default.createDirectory(at: parent,
                withIntermediateDirectories: true,
                attributes: [.posixPermissions: 0o700])
            guard let attributes = try? FileManager.default.attributesOfItem(atPath: parent.path),
                  let permissions = attributes[.posixPermissions] as? NSNumber,
                  permissions.intValue & 0o077 == 0 else {
                throw NSError(domain: "ESPWake", code: 1)
            }
            let payload: [String: Any] = [
                "schema": 1, "requested_phrase": phrase,
                "applied_to_device": false, "requires_device_wakenet_model": true,
                "recording_source": "esp32_only"]
            let bytes = try JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys])
            try bytes.write(to: target, options: [.atomic])
            try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: target.path)
            notice = "已保存称呼偏好；没有改变板端唤醒模型。是否能识别请实际测试。"
        } catch { notice = "保存失败，请检查本机私有目录权限。" }
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 15) {
            Text("ESP32 语音唤醒").font(.system(size: 18, weight: .bold))
            Text("唯一拾音设备：ESP32-S3 板载麦克风。Mac 不监听任何麦克风。")
                .font(.system(size: 12))
            Picker("期望唤醒词", selection: $phrase) {
                ForEach(choices, id: \.self) { Text($0).tag($0) }
            }
            Text(hardwareReady
                 ? "设备识别能力已有协议回执；本页只保存称呼偏好，不会修改板端唤醒词。请用真实呼唤验证识别效果。"
                 : "设备唤醒能力尚未确认；本页只保存称呼偏好，不会改变当前固件或启动录音。")
                .font(.system(size: 12))
                .foregroundStyle(DeepSeekPalette.secondary)
            if !notice.isEmpty { Text(notice).font(.system(size: 12)) }
            HStack {
                Button("保存偏好") { savePreference() }
                Spacer()
                Button("关闭") { isPresented = false }
            }
        }
        .padding(22).frame(width: 390)
        .foregroundStyle(DeepSeekPalette.foreground)
        .background(DeepSeekPalette.background)
        .onAppear { readPreference() }
    }
}

// R32 square-native Mac companion. Same visual grammar as the accepted
// ESP32 HTML; status read-only from the validated physical ESP/DSH session.
private struct CompanionMiniView: View {
    @ObservedObject var store: CompanionStore
    let openManagement: () -> Void
    @State private var showHistory = false
    // R535: the same verified speech_id receipt is published before TTS and
    // updated upon synthesis/ESP ACK. Force a read while the sheet is OPEN,
    // independent of whether the Mac companion status phase changes.
    @State private var spokenHistoryRefreshTick = 0
    @State private var showMotionLibrary = false
    @State private var showRemoteDisplay = false
    @State private var showMemory = false
    @State private var showVoice = false
    @State private var showDiagnostics = false
    @State private var pendingSheetNavigation: String? = nil
    @State private var compactWindow = false
    @State private var verifiedWiFi:VerifiedWiFiGateway? = nil
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @AppStorage("dafeiyu.r32.idleSeconds") private var idleSeconds = 90
    @State private var localReaction: String? = nil
    @State private var reactionIndex = 0
    @State private var lastIdleDance = Date()

    private let size: CGFloat = 480
    // AppKit indexed GIF is color-converted ~2-3 RGB units darker than a
    // SwiftUI sRGB fill on this Mac. Use perceptually matched screen color,
    // while the decoded private DFSP source itself stays #EEF7FF.
    private let softBlue = Color(nsColor: .windowBackgroundColor)
    private let line = Color(nsColor: .separatorColor)
    private let ink = Color(nsColor: .labelColor)
    private let subdued = Color(nsColor: .secondaryLabelColor)

    private var activeMotionFile: URL? {
        if store.snapshot?.phase == "idle", let localReaction {
            return store.motionFile(for: localReaction) ?? store.motionFile
        }
        return store.motionFile
    }
    // SwiftUI must finish dismissing one sheet before presenting another.
    // Merely DispatchQueue.main.async from a sheet button loses the next
    // presentation on some macOS versions.
    private func finishPendingSheetNavigation() {
        guard let destination=pendingSheetNavigation else {return}
        pendingSheetNavigation=nil
        switch destination {
        case "pixels": showRemoteDisplay=true
        case "motions": showMotionLibrary=true
        case "voice": showVoice=true
        case "memory": showMemory=true
        case "diagnostics": showDiagnostics=true
        default: break
        }
    }

    private func localTouchMotion() {
        guard store.snapshot?.phase == "idle" else { return }
        let allowed = ["m014", "m015", "m016", "m023"]
        let next = allowed[reactionIndex % allowed.count]
        reactionIndex += 1
        localReaction = next
        lastIdleDance = Date()
        DispatchQueue.main.asyncAfter(deadline: .now() + 2.7) {
            if localReaction == next { localReaction = nil }
        }
    }
    private var verifiedTransport:VerifiedCompanionTransport {
        VerifiedCompanionTransport.resolve(usbVerified:store.bothVerified,wifi:verifiedWiFi)
    }
    private var liveStatus: String {
        if verifiedTransport.isWiFi { return "ESP32 Wi-Fi 已鉴权 · " + verifiedTransport.phaseDescription }
        if wirelessReserved { return "Wi-Fi 连接核验中 · 请查看管理中心" }
        if store.bothVerified && store.localTTSReady { return "ESP32＋DSH＋语音合成已就绪" }
        if store.bothVerified { return "ESP32＋DSH 已连 · Qwen语音未就绪" }
        if store.connecting { return "正在后台连接 DSH＋ESP32…" }
        if store.espVerified { return "ESP32 已验证 · DSH 未建立" }
        if store.connected { return "DSH 会话在线 · ESP32 未验证" }
        if ESPUSBSerialPresence.detected {
            return "ESP32 USB 已接入 · 语音未连接"
        }
        return "ESP32 USB 未接入 · 语音未连接"
    }
    private var wirelessReserved:Bool {
        verifiedWiFi?.active_devices == 1 || verifiedWiFi?.pending_dsh_jobs == 1
    }
    private var statusColor: Color {
        verifiedTransport.isConnected && !(wirelessReserved && !verifiedTransport.isWiFi)
            ? Color(red: 0.31, green: 0.76, blue: 0.66) : Color.orange.opacity(0.75)
    }
    private func button(_ symbol: String, label: String,
                        emphasized: Bool = false, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: symbol)
                .font(.system(size: 22, weight: .medium))
                .foregroundStyle(emphasized ? Color(red: 0.16, green: 0.53, blue: 0.72) :
                                 Color(red: 0.34, green: 0.54, blue: 0.66))
                .frame(width: 55, height: 55)
                .background(emphasized ? Color(nsColor: .selectedContentBackgroundColor).opacity(0.25) : Color(nsColor: .controlBackgroundColor),
                            in: RoundedRectangle(cornerRadius: 17))
                .overlay(RoundedRectangle(cornerRadius: 17)
                    .stroke(emphasized ? Color(red: 0.70, green: 0.87, blue: 0.93) : line))
        }
        .buttonStyle(.plain)
        .help(label)
        .accessibilityLabel(label)
    }

    var body: some View {
        VStack(spacing: 0) {
            if compactWindow {
                HStack(spacing: 11) {
                    Button {
                        compactWindow = false
                    } label: {
                        Image(systemName:"arrow.up.left.and.arrow.down.right")
                    }.help("展开大肥鱼窗口").accessibilityLabel("展开大肥鱼窗口")
                    Circle().fill(statusColor).frame(width:8,height:8)
                    Text(liveStatus).lineLimit(1)
                    Spacer()
                    Text(verifiedTransport.isWiFi || wirelessReserved ? "模型待确认" : store.verifiedModelBadge)
                        .font(.system(size:11,weight:.semibold))
                        .padding(.horizontal,9).padding(.vertical,5)
                        .background(Color(nsColor: .controlBackgroundColor).opacity(0.90),in:Capsule())
                        .help("只显示官方DSH当前会话确认的模型")
                    Button(verifiedTransport.isWiFi || wirelessReserved ? "查看连接" : store.bothVerified ? "核验语音" : "连接语音") {
                        if verifiedTransport.isWiFi || wirelessReserved { openManagement() }
                        else { store.connectSession() }
                    }.help(verifiedTransport.isWiFi || wirelessReserved ? "无线连接由管理中心核验；不启动USB语音" : "手动核验当前官方 DSH 会话")
                    Button {
                        NSApp.terminate(nil)
                    } label: {Image(systemName:"xmark")}
                    .help("退出大肥鱼窗口（语音后台继续运行）")
                    .accessibilityLabel("退出大肥鱼窗口")
                }
                .font(.system(size:12,weight:.medium))
                .foregroundStyle(ink)
                .padding(.horizontal,21)
                .frame(width:496,height:74)
                .background(softBlue)
            } else {
            ZStack(alignment: .topLeading) {
                softBlue
                HStack(spacing: 8) {
                    Button {
                        NSApp.terminate(nil)
                    } label: {Image(systemName:"xmark")}
                        .help("退出 Mac 大肥鱼（ESP32 语音后台继续运行）")
                        .accessibilityLabel("退出大肥鱼窗口")
                    Button {
                        compactWindow = true
                    } label: {Image(systemName:"minus")}
                        .help("缩小为桌面状态条，可再次展开")
                        .accessibilityLabel("缩小桌面窗口")
                    Circle().fill(statusColor).frame(width: 7, height: 7)
                    Text(liveStatus).lineLimit(1)
                    Spacer(minLength: 3)
                    Text(verifiedTransport.isWiFi || wirelessReserved ? "模型待确认" : store.verifiedModelBadge)
                        .font(.system(size:11,weight:.semibold))
                        .padding(.horizontal,9).padding(.vertical,5)
                        .background(Color(nsColor: .controlBackgroundColor).opacity(0.90),in:Capsule())
                        .help("只显示官方DSH当前会话确认的模型")
                    Button(verifiedTransport.isWiFi || wirelessReserved ? "查看连接" : store.bothVerified ? "核验语音" : "连接语音") {
                        if verifiedTransport.isWiFi || wirelessReserved { openManagement() }
                        else { store.connectSession() }
                    }.help(verifiedTransport.isWiFi || wirelessReserved ? "无线连接由管理中心核验；不启动USB语音" : "手动核验或连接官方 DSH 会话")
                }
                .buttonStyle(.plain)
                .font(.system(size: 12, weight: .medium))
                .foregroundStyle(subdued)
                .frame(width: 444, height: 28)
                .position(x: 240, y: 30)

                Button(action: localTouchMotion) {
                    Group {
                        if let file = activeMotionFile {
                            PrivateMotionPlayer(url: file)
                                .frame(width: 318, height: 318)
                        } else {
                            VStack(spacing: 9) {
                                Image(systemName: "sparkles").font(.system(size: 24))
                                Text("动画素材准备中").font(.system(size: 12))
                            }
                            .foregroundStyle(subdued)
                            .frame(width: 318, height: 318)
                        }
                    }
                }
                .buttonStyle(.plain)
                .help("Mac端角色本地预览动作；不会远程点击ESP32，也不会采集音频或调用模型")
                .accessibilityLabel("预览Mac本地角色动画，不触发设备触摸")
                .position(x: 205, y: 242)

                button("slider.horizontal.3",label:"打开管理中心"){
                    openManagement()
                }
                .position(x: 438, y: 257)

                HStack(spacing: 7) {
                    Circle().fill(store.snapshot?.phase == "error" ? Color.orange :
                        (store.snapshot?.phase == "listening" ? Color.red.opacity(0.7) : statusColor))
                        .frame(width: 7, height: 7)
                    Text(verifiedTransport.isWiFi ? verifiedTransport.phaseDescription : store.phase)
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundStyle(ink)
                        .lineLimit(1)
                    Spacer(minLength: 5)
                    Text(localReaction != nil && store.snapshot?.phase == "idle"
                         ? "Mac本地预览"
                         : (store.espVerified &&
                            store.snapshot?.esp32_frame_verified == true &&
                            store.snapshot?.esp32_frame_motion_id == store.snapshot?.animation_id
                            ? "设备首帧已确认"
                            : "本地状态 · 非逐帧同步"))
                        .font(.system(size: 10))
                        .foregroundStyle(subdued)
                        .lineLimit(1)
                }
                .padding(.horizontal, 12)
                .frame(width: 442, height: 37)
                .background(Color(nsColor: .controlBackgroundColor).opacity(0.90),in:RoundedRectangle(cornerRadius:11))
                .overlay(RoundedRectangle(cornerRadius:11).stroke(line.opacity(0.7)))
                .position(x: 240, y: 445)
            }
            .frame(width: size, height: size)
            .clipShape(RoundedRectangle(cornerRadius: 5))
            .overlay(RoundedRectangle(cornerRadius: 5).stroke(line.opacity(0.65)))
            .padding(8)
            .background(Color(red:0.14,green:0.21,blue:0.26),
                        in:RoundedRectangle(cornerRadius: 12))
            }
        }
        .frame(width: 496, height: compactWindow ? 74 : 496)
        .background(softBlue)
        .clipShape(RoundedRectangle(cornerRadius: 12))

        .onChange(of:compactWindow) { _,small in
            guard let panel=NSApp.windows.first(where:{$0 is CompanionWindow}) else {return}
            let current=panel.frame
            let height:CGFloat=small ? 74 : 496
            panel.setFrame(NSRect(x:current.minX,y:current.maxY-height,
                                  width:496,height:height),display:true,animate:!reduceMotion)
        }
        .onAppear { verifiedWiFi=VerifiedWiFiGateway.read() }
        .onReceive(Timer.publish(every: 1, on: .main, in: .common).autoconnect()) { now in
            let latestWiFi=VerifiedWiFiGateway.read()
            if let previous=verifiedWiFi,let latest=latestWiFi {
                if !previous.sameVisibleStatus(as:latest) {
                    verifiedWiFi=latest
                }
            } else if (verifiedWiFi == nil) != (latestWiFi == nil) {
                verifiedWiFi=latestWiFi
            }
            guard !reduceMotion, idleSeconds > 0, store.snapshot?.phase == "idle" else {
                lastIdleDance = now
                return
            }
            if now.timeIntervalSince(lastIdleDance) >= Double(idleSeconds) {
                localTouchMotion()
            }
        }
        .sheet(isPresented:$showVoice) { voiceSheet }
        .sheet(isPresented:$showHistory) {
            historySheet
                .onReceive(Timer.publish(every:0.6,on:.main,in:.common).autoconnect()) { _ in
                    // One lightweight same-session read while visible. Never
                    // triggers TTS, playback or DSH calls.
                    spokenHistoryRefreshTick &+= 1
                }
        }
        .sheet(isPresented:$showMotionLibrary) { MotionLibrarySheet(store:store) }
        .sheet(isPresented:$showRemoteDisplay) { RemoteDisplaySheet(store:store) }
        .sheet(isPresented:$showDiagnostics,onDismiss:finishPendingSheetNavigation) {
            CompanionDiagnosticsHubSheet(
                store:store,
                openPixels:{pendingSheetNavigation="pixels";showDiagnostics=false},
                openMotions:{pendingSheetNavigation="motions";showDiagnostics=false},
                openVoice:{pendingSheetNavigation="voice";showDiagnostics=false})
        }
        .sheet(isPresented:$showMemory) {
            MemoryOverviewSheet(isPresented: $showMemory)
        }
    }

    private func sheetHeader(_ title:String,_ symbol:String, close:@escaping () -> Void) -> some View {
        HStack(spacing: 8) {
            Image(systemName:symbol).foregroundStyle(Color(red:0.29,green:0.64,blue:0.77))
            Text(title).font(.system(size:17,weight:.semibold)).foregroundStyle(ink)
            Spacer()
            Button("关闭",action:close).buttonStyle(.bordered)
        }
    }
    private var voiceSheet:some View {
        VStack(alignment:.leading,spacing:16){
            sheetHeader("ESP32 语音","mic") { showVoice=false }
            Label(store.phase,systemImage:"waveform")
                .font(.system(size:16,weight:.semibold))
            Text("录音的唯一入口是 ESP32 实体板载麦克风。Mac 窗口只显示真实的监听、识别、模型回复及扬声器播放状态。")
            Text(store.connectionDiagnostic)
                .font(.system(size:12))
                .foregroundStyle(subdued)
                .fixedSize(horizontal:false,vertical:true)
            Text(store.snapshot?.wake_capability_verified == true && store.bothVerified
                 ? "设备声学唤醒能力已有实体握手；具体热词以已安装模型回执为准，点按麦克风仍可手动录音。"
                 : "当前可以点按 ESP32 麦克风开始／结束录音。只有实体热词能力验证和 Mac 服务都在线，免触碰唤醒才会生效。")
                .foregroundStyle(subdued)
            HStack(spacing:6) {
                Circle().fill(statusColor).frame(width:8,height:8)
                Text(store.physicalLink).font(.system(size:12))
            }
            if store.snapshot?.voice_streaming_enabled == true && store.bothVerified {
                Label("渐进式 PCM2 已经在实体语音服务中启用",systemImage:"waveform.path")
                    .font(.system(size:11)).foregroundStyle(subdued)
            }
            Spacer(minLength:0)
        }
        .padding(22).frame(width:390,height:270)
        .foregroundStyle(ink).background(Color(nsColor: .windowBackgroundColor))
    }
    private func formattedAssistant(_ value: String) -> Text {
        // Render bounded read-only model Markdown; never run HTML or scripts.
        // Invalid/incomplete Markdown must still remain legible as plain text.
        if let rendered = try? AttributedString(markdown: value) {
            return Text(rendered)
        }
        return Text(value)
    }
    private func speechBubble(_ sentence: String, user: Bool, source: String = "") -> some View {
        HStack(alignment: .bottom, spacing: 8) {
            if user { Spacer(minLength: 64) }
            VStack(alignment: user ? .trailing : .leading, spacing: 5) {
                Text(user ? "你" : "大肥鱼" + (source.isEmpty ? "" : " · " + source))
                    .font(.system(size: 10, weight: .medium))
                    .foregroundStyle(subdued)
                Group {
                    if user {
                        Text(sentence).font(.system(size:13))
                            .textSelection(.enabled)
                    } else {
                        ReadableMarkdownView(source:sentence)
                    }
                }
                    .foregroundStyle(ink)
                    .padding(.horizontal, 13).padding(.vertical, 11)
                    .background(user ? Color(nsColor: .controlAccentColor).opacity(0.15)
                                     : Color(nsColor: .controlBackgroundColor),
                                in: RoundedRectangle(cornerRadius: 15))
            }
            .frame(maxWidth: 312, alignment: user ? .trailing : .leading)
            if !user { Spacer(minLength: 64) }
        }
        .frame(maxWidth: .infinity)
    }
    private var historySheet:some View {
        let _ = spokenHistoryRefreshTick
        // Both the floating "最近会话" sheet and the management center must
        // show the exact synthesized script of an authenticated speech turn.
        // Keep latest receipt and bounded same-session archive read-only.
        let verifiedID=store.conversationSessionID
        return VStack(alignment:.leading,spacing:10) {
            sheetHeader("最近会话","bubble.left.and.bubble.right"){showHistory=false}
            HStack {
                Image(systemName: "clock.arrow.circlepath")
                Text("当前会话的近期回合 · 逐句显示 · 非永久历史")
            }
            .font(.system(size:11)).foregroundStyle(subdued)
            ScrollViewReader { reader in
            ScrollView {
                LazyVStack(spacing: 14) {
                    if !store.conversationPreview.isEmpty {
                        ForEach(Array(store.conversationPreview.enumerated()),id:\.offset){_,turn in
                            let spoken=R531VerifiedSpokenDisplay.resolve(
                                turn:turn,sessionID:verifiedID)
                            speechBubble(String(turn.user.prefix(600)),user:true)
                            ForEach(turn.progress ?? [],id:\.self) { line in
                                speechBubble(line,user:false,source:"任务进度")
                            }
                            speechBubble(spoken?.0 ?? turn.assistant,user:false,
                                 source:spoken?.1 ?? (turn.origin == "model" ? "DSH" :
                                   (turn.origin == "failed" ? "处理失败" :
                                   (turn.origin == "memory" ? "已核实记忆" :
                                   (turn.origin == "weather" ? "Open-Meteo 天气" :
                                   (turn.origin == "weather_unavailable" ? "天气暂不可用" : "本地回复"))))))
                            R683PhoneSearchOriginalView(turn:turn)
                        }
                    }
                    if let active=store.activeTaskConversation {
                        speechBubble(active.0,user:true)
                        ForEach(active.1,id:\.self) {line in
                            speechBubble(line,user:false,source:"处理中")
                        }
                    }
                    if store.conversationPreview.isEmpty &&
                       store.activeTaskConversation == nil &&
                       store.snapshot?.user_text != nil {
                        speechBubble(store.lastQuestion,user:true)
                        speechBubble(store.lastAnswer,user:false,source:store.originLabel)
                    } else if store.conversationPreview.isEmpty &&
                              store.activeTaskConversation == nil {
                        Text("当前没有可验证的近期对话。")
                            .font(.system(size:12)).foregroundStyle(subdued)
                            .frame(maxWidth:.infinity).padding(.top,60)
                    }
                    Color.clear.frame(height:1).id("r683-history-tail")
                }
                .padding(.vertical,8)
            }
            .onAppear { reader.scrollTo("r683-history-tail",anchor:.bottom) }
            .onChange(of:store.conversationPreview.count) { _,_ in
                reader.scrollTo("r683-history-tail",anchor:.bottom)
            }
            }
            DisclosureGroup("诊断过程（\(store.recentSteps.count) 条）") {
                VStack(alignment:.leading,spacing:7) {
                    ForEach(Array(store.recentSteps.enumerated()),id:\.offset){_,step in
                        Text("· "+step.label).font(.system(size:11)).foregroundStyle(subdued)
                    }
                    Text(store.verifiedToolLabel).font(.system(size:10))
                        .foregroundStyle(subdued)
                }
            }
            .font(.system(size:12))
        }
        .padding(20).frame(width:445,height:555)
        .foregroundStyle(ink).background(Color(nsColor: .windowBackgroundColor))
    }

}

// Borderless transparent host removes the native light titlebar corner
// artifacts. The native quit / compact / restore controls remain in SwiftUI.
private final class CompanionWindow: NSPanel {
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { true }
}

@main
@MainActor
final class CompanionMiniApplication: NSObject, NSApplicationDelegate, NSWindowDelegate {
    private var window: NSPanel?
    private var managementWindow: NSWindow?
    private var navigator = ManagementNavigation()
    private var store: CompanionStore?

    static func main() {
        let app = NSApplication.shared
        let delegate = CompanionMiniApplication()
        app.delegate = delegate
        app.setActivationPolicy(.regular)
        app.run()
        _ = delegate
    }

    @objc private func openManagementMenu(_ sender:Any?) {
        // Reliable direct way back to the overview and device-follow preview.
        openManagementCenter(section:.overview)
    }
    @objc private func openAnimationsMenu(_ sender:Any?) {
        openManagementCenter(section:.animations)
    }
    @objc private func openCompanionMenu(_ sender:Any?) {
        window?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps:true)
    }
    @objc private func closeActiveWindow(_ sender:Any?) {
        guard let active=NSApp.keyWindow else{return}
        if active === managementWindow {
            active.performClose(sender)
        } else if active === window {
            active.orderOut(nil)
        }
    }
    @objc private func minimizeActiveWindow(_ sender:Any?) {
        guard let active=NSApp.keyWindow,active === managementWindow else{return}
        active.performMiniaturize(sender)
    }
    @objc private func openSettingsMenu(_ sender:Any?) {
        // Single settings owner: the management center's preferences section.
        // Avoid a third, divergent settings surface.
        openManagementCenter(section:.preferences)
    }
    private func openManagementCenter(section:ManagementSection?=nil) {
        guard let model=store else{return}
        if let section {navigator.section=section}
        if managementWindow == nil {
            let pane=NSWindow(contentRect:NSRect(x:0,y:0,width:1230,height:860),
                              styleMask:[.titled,.closable,.miniaturizable,.resizable],
                              backing:.buffered,defer:false)
            pane.title="大肥鱼 · 管理中心"
            pane.isReleasedWhenClosed=false
            pane.delegate=self
            pane.minSize=NSSize(width:920,height:720)
            pane.contentView=NSHostingView(rootView:
                CompanionManagementCenter(store:model,navigation:navigator))
            pane.center()
            managementWindow=pane
        }
        // Do not let the always-on-top pet obscure the management workspace.
        // Closing this normal window returns to the original floating pet.
        window?.orderOut(nil)
        managementWindow?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps:true)
    }
    func windowWillClose(_ notification:Notification) {
        guard let closing=notification.object as? NSWindow else{return}
        if closing === managementWindow { window?.orderFrontRegardless() }
    }
    private func configureMainMenu() {
        let top=NSMenu()
        let appItem=NSMenuItem()
        top.addItem(appItem)
        let appMenu=NSMenu(title:"大肥鱼")
        appItem.submenu=appMenu
        let settings=NSMenuItem(title:"设置…",action:#selector(openSettingsMenu(_:)),
                                keyEquivalent:",")
        settings.keyEquivalentModifierMask=[.command]
        settings.target=self
        appMenu.addItem(settings)
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle:"退出大肥鱼",action:#selector(NSApplication.terminate(_:)),
                        keyEquivalent:"q")
        let viewItem=NSMenuItem()
        top.addItem(viewItem)
        let viewMenu=NSMenu(title:"窗口")
        viewItem.submenu=viewMenu
        let closeItem=NSMenuItem(title:"关闭窗口",action:#selector(closeActiveWindow(_:)),
                                 keyEquivalent:"w")
        closeItem.target=self
        viewMenu.addItem(closeItem)
        let minimizeItem=NSMenuItem(title:"最小化窗口",action:#selector(minimizeActiveWindow(_:)),
                                    keyEquivalent:"m")
        minimizeItem.target=self
        viewMenu.addItem(minimizeItem)
        viewMenu.addItem(.separator())
        let manager=NSMenuItem(title:"管理中心",action:#selector(openManagementMenu(_:)),
                               keyEquivalent:"1")
        manager.target=self
        viewMenu.addItem(manager)
        let motions=NSMenuItem(title:"动画与规则",action:#selector(openAnimationsMenu(_:)),
                               keyEquivalent:"2")
        motions.target=self
        viewMenu.addItem(motions)
        let companion=NSMenuItem(title:"显示桌宠",action:#selector(openCompanionMenu(_:)),
                                 keyEquivalent:"0")
        companion.target=self
        viewMenu.addItem(companion)
        NSApp.mainMenu=top
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        configureMainMenu()
        // R676: real CUA question polling and visible approval must work
        // without opening the management center first.
        R675ComputerQuestionModel.shared.startMonitoring()
        let model = CompanionStore()
        store = model
        let panel = CompanionWindow(
            contentRect: NSRect(x: 200, y: 200, width: 496, height: 496),
            styleMask: [.borderless],
            backing: .buffered, defer: false)
        panel.title = "大肥鱼"
        panel.hasShadow = true
        panel.isFloatingPanel = true
        panel.level = .floating
        panel.isMovableByWindowBackground = true
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        panel.hidesOnDeactivate = false
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.contentView = NSHostingView(rootView: CompanionMiniView(store: model,
            openManagement:{[weak self] in self?.openManagementCenter()}))
        panel.center()
        panel.orderFrontRegardless()
        window = panel
        // The UI attaches to an already verified session in CompanionStore.init.
        // If the user intentionally stopped/unloaded the voice LaunchAgent,
        // merely opening this window must NOT secretly kickstart the ESP mic.
        // Restart is an explicit Settings > Connect Session click.
    }

    func applicationWillTerminate(_ notification: Notification) {
        // The user-level voice service is independent from the UI lifecycle.
        // Closing/upgrading the app must not silently terminate ESP32 audio.
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        false // closing a settings sheet or main window does not kill the USB session
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows: Bool) -> Bool {
        window?.makeKeyAndOrderFront(nil)
        return true
    }
}
