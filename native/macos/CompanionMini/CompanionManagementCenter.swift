// SPDX-License-Identifier: MIT
// R175 native Mac control center. The existing floating companion remains a
// separate scene. Only the already authorized CompanionStore owns data.
import AppKit
import Combine
import SwiftUI

enum ManagementSection: String, CaseIterable, Identifiable {
    case overview = "概览"
    case animations = "动画管理"
    case conversations = "对话记录"
    case memory = "我的记忆"
    case plugins = "插件与扩展"
    case diagnostics = "设备诊断"
    case preferences = "偏好设置"
    var id:Self { self }
    var icon:String {
        switch self {
        case .overview: return "macmini"
        case .animations: return "square.stack"
        case .conversations: return "bubble.left.and.bubble.right"
        case .memory: return "brain.head.profile"
        case .plugins: return "puzzlepiece.extension"
        case .diagnostics: return "waveform.path.ecg"
        case .preferences: return "gearshape"
        }
    }
}
@MainActor
final class ManagementNavigation: ObservableObject {
    @Published var section: ManagementSection = .overview
}

private enum AnimationWorkspace:String,CaseIterable {
    case library="素材库"
    case rules="触发规则"
}

private enum CompanionPreviewMode:String,CaseIterable {
    case following="跟随设备"
    case local="本地预览"
}

// R499: read-only, single-current-session TTS text comparison. This source
// is separate from the model's original answer and is NOT evidence the board
// has completely played the PCM. Reject stale, wrong-session, public or
// symlinked local files.
private struct R499SpeechSegment: Decodable {
    let text:String
    let audio_ms:Int
}

private struct R499ReplyComparison: Decodable {
    let speech_id:String?
    let schema:Int
    let session_id:String
    let generated_at_unix:Double
    let origin:String
    let original_text:String
    let spoken_text:String
    let final_spoken_text:String?
    let voice_profile_id:String?
    let original_chars:Int
    let spoken_chars:Int
    let segments:[R499SpeechSegment]?
    let tts_generated:Bool
    let device_playback_verified:Bool
}

private enum R499ComparisonReader {
    static func read(for sessionID:String) -> R499ReplyComparison? {
        let url=FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/Deepseek-live/companion-native/reply-speech-comparison-v1.json")
        guard let props=try? url.resourceValues(forKeys:[.isRegularFileKey,.isSymbolicLinkKey]),
              props.isRegularFile==true,props.isSymbolicLink != true,
              let attrs=try? FileManager.default.attributesOfItem(atPath:url.path),
              ((attrs[.posixPermissions] as? NSNumber)?.intValue ?? 511) & 0o077 == 0,
              (attrs[.ownerAccountID] as? NSNumber)?.intValue == Int(getuid()),
              let size=(attrs[.size] as? NSNumber)?.intValue,
              size>20,size<=48_000,
              let raw=try? Data(contentsOf:url),
              let record=try? JSONDecoder().decode(R499ReplyComparison.self,from:raw)
        else {return nil}
        let now=Date().timeIntervalSince1970
        guard record.schema==1,record.session_id==sessionID,
              record.generated_at_unix.isFinite,
              now-record.generated_at_unix >= -5,
              now-record.generated_at_unix <= 7*86400,
              ["official_dsh_verified","verified_mac_local_datetime",
               "verified_open_meteo_weather","local_weather_source_unavailable"].contains(record.origin),
              record.original_chars==record.original_text.unicodeScalars.count,
              record.spoken_chars==record.spoken_text.unicodeScalars.count,
              record.original_chars>0,record.original_chars<=12_000,
              record.spoken_chars>0,record.spoken_chars<=8_000 else {return nil}
        if let final=record.final_spoken_text {
            guard !final.isEmpty && record.spoken_text.hasSuffix(final) else{return nil}
        }
        if let profile=record.voice_profile_id {
            guard ["dafeiyu-qwen3-d10","dafeiyu-r503-qwen06-long-trial"].contains(profile) else {
                return nil
            }
        }
        if let parts=record.segments, !parts.isEmpty {
            guard parts.count<=64,
                  parts.allSatisfy({$0.audio_ms>=100 && $0.audio_ms<=180_000}),
                  parts.map(\.text).joined()==record.spoken_text else {return nil}
        }
        return record
    }
}

// R520: private, same-session history of fully synthesized speech. This is
// display data, not proof of physical ESP32 speaker playback.
private struct R520SpokenRecord: Decodable {
    let speech_id:String?
    let original_text:String
    let spoken_text:String
    let final_spoken_text:String?
    let generated_at_unix:Double
}
private struct R520SpokenArchive: Decodable {
    let schema:Int
    let session_id:String
    let records:[R520SpokenRecord]
}
private enum R520SpokenHistoryReader {
    static func read(for sessionID:String) -> [R520SpokenRecord]? {
        let url=FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/Deepseek-live/companion-native/reply-speech-history-v1.json")
        guard let props=try? url.resourceValues(forKeys:[.isRegularFileKey,.isSymbolicLinkKey]),
              props.isRegularFile==true,props.isSymbolicLink != true,
              let attrs=try? FileManager.default.attributesOfItem(atPath:url.path),
              ((attrs[.posixPermissions] as? NSNumber)?.intValue ?? 511) & 0o077 == 0,
              (attrs[.ownerAccountID] as? NSNumber)?.intValue == Int(getuid()),
              let size=(attrs[.size] as? NSNumber)?.intValue,
              size>20,size<=800_000,
              let raw=try? Data(contentsOf:url),
              let archive=try? JSONDecoder().decode(R520SpokenArchive.self,from:raw),
              archive.schema==1,archive.session_id==sessionID,
              archive.records.count<=120 else {return nil}
        let now=Date().timeIntervalSince1970
        guard archive.records.allSatisfy({item in
            item.generated_at_unix.isFinite &&
            item.generated_at_unix <= now+5 &&
            item.original_text.count>0 && item.original_text.count<=12_000 &&
            item.spoken_text.count>0 && item.spoken_text.count<=8_000 &&
            (item.final_spoken_text == nil || (
                !(item.final_spoken_text ?? "").isEmpty &&
                item.spoken_text.hasSuffix(item.final_spoken_text ?? "")))
        }) else {return nil}
        return archive.records
    }
}

// R683: the default chat remains the verified spoken script. For a trusted
// read-only phone search the exact DSH tool-backed answer stays reachable
// without replacing speech with raw text or adding permanent UI controls.
struct R683PhoneSearchOriginalView: View {
    let turn:ConversationPreview
    @State private var expanded=false
    private var eligible:Bool {
        turn.origin == "model" &&
        (turn.user.contains("手机") || turn.user.lowercased().contains("pinky")) &&
        (turn.user.contains("搜索") || turn.user.contains("搜一下") ||
         turn.user.contains("搜一搜")) &&
        (turn.user.contains("只看") || turn.user.contains("只查看") ||
         turn.user.contains("仅查看")) &&
        turn.assistant.count>=12 && turn.assistant.count<=900 &&
        (turn.assistant.contains("商品") || turn.assistant.contains("搜索结果"))
    }
    var body:some View {
        if eligible {
            DisclosureGroup(isExpanded:$expanded) {
                ReadableMarkdownView(source:turn.assistant)
                    .padding(.vertical,7)
                    .frame(maxWidth:.infinity,alignment:.leading)
            } label: {
                Label("查看原始手机搜索结果",systemImage:"list.bullet.rectangle")
                    .font(.system(size:12,weight:.medium))
            }
            .foregroundStyle(.secondary)
            .padding(.horizontal,13)
            .padding(.vertical,9)
            .background(Color(nsColor:.controlBackgroundColor).opacity(0.65),
                        in:RoundedRectangle(cornerRadius:10))
            .frame(maxWidth:650,alignment:.leading)
            .accessibilityIdentifier("r683-original-phone-search-result")
        }
    }
}

// R531: one trusted per-turn spoken-script resolver for both Mac views.
// The original answer remains in the DSH history; this changes display only.
// The projector intentionally truncates preview answers to 900 characters,
// while the verified speech record retains the complete original answer.
enum R531VerifiedSpokenDisplay {
    static func matches(_ full:String, preview:String) -> Bool {
        full == preview || (preview.count == 900 && full.hasPrefix(preview))
    }
    static func resolve(turn:ConversationPreview, sessionID:String?) -> (String,String)? {
        guard let sid=sessionID,!sid.isEmpty,
              let id=turn.speech_id,
              id.range(of:#"^[0-9a-f]{32}$"#,options:.regularExpression) != nil
        else {return nil}
        let current=R499ComparisonReader.read(for:sid)
        if let current,
           current.speech_id==id,
           matches(current.original_text,preview:turn.assistant) {
            // R535: R511 already publishes the exact verified TTS plan before
            // synthesis. A pending plan is not playable audio, but it IS the
            // text that the board will hear if synthesis completes. Render it
            // immediately rather than waiting for a playback completion ACK.
            if !current.tts_generated {
                return (current.final_spoken_text ?? current.spoken_text,
                        "结果朗读稿 · 合成中")
            }
            return (current.final_spoken_text ?? current.spoken_text,
                    current.device_playback_verified ? "结果朗读稿 · 设备已完成播放" : "结果朗读稿 · 已合成")
        }
        let records=R520SpokenHistoryReader.read(for:sid) ?? []
        if let matched=records.last(where:{$0.speech_id==id &&
                         matches($0.original_text,preview:turn.assistant)}) {
            return (matched.final_spoken_text ?? matched.spoken_text,
                    "已合成结果朗读稿")
        }
        return nil
    }
}

// R317: explicit, non-destructive local service recovery buttons.
// A started PID and an authenticated ESP32 speech session are different facts.
private struct R459ServiceState: Decodable {
    let enabled:Bool
    let loaded:Bool
    let running:Bool
}
private struct R459SwitchReceipt: Decodable {
    let schema:Int
    let ok:Bool
    let reason:String?
    let services:[String:R459ServiceState]?
}

// R459 service switches represent actual persisted launchctl decisions.
// Never fabricate a DSH/tts power toggle: those are shared backends.
struct CompanionServiceControlsView: View {
    @ObservedObject var store:CompanionStore
    var compact:Bool = false
    @State private var wirelessBusy=false
    @State private var services:[String:R459ServiceState]=[:]
    @State private var applying:String?=nil
    @State private var pendingOff:String?=nil
    @State private var showTurnOff=false
    @State private var notice=""

    private func refreshWirelessBusy() {
        let status=VerifiedWiFiGateway.read()
        wirelessBusy=status?.active_devices == 1 || status?.pending_dsh_jobs == 1
    }

    private nonisolated static func manager(_ args:[String]) -> R459SwitchReceipt? {
        let command=Process()
        command.executableURL=URL(fileURLWithPath:CompanionProjectPaths.python)
        command.arguments=[
            CompanionProjectPaths.script("r459_service_switches.py")
        ]+args
        command.standardError=Pipe()
        let output=Pipe()
        command.standardOutput=output
        do {
            try command.run()
            command.waitUntilExit()
            guard command.terminationStatus==0 else{return nil}
            let bytes=output.fileHandleForReading.readDataToEndOfFile()
            guard bytes.count<8192 else{return nil}
            return try JSONDecoder().decode(R459SwitchReceipt.self,from:bytes)
        } catch {return nil}
    }

    private func refreshServices() {
        guard applying==nil else{return}
        Task.detached(priority:.utility) {
            let receipt=Self.manager(["status"])
            await MainActor.run {
                guard applying==nil else{return}
                if let receipt,receipt.schema==1,receipt.ok,
                   let result=receipt.services {
                    services=result
                } else {
                    services=[:]
                    notice="无法读取 Mac 服务开关的真实状态。"
                }
            }
        }
    }

    private func localReason(_ code:String?) -> String {
        switch code {
        case "wireless_conversation_active","wireless_owner_unverified",
             "wifi_gateway_running","wireless_status_stale":
            return "无线设备或网关仍在工作，请先结束当前无线会话"
        case "voice_not_idle","voice_not_verified","usb_state_unavailable":
            return "USB语音尚未确认空闲，暂不允许停止"
        case "status_read_failed","launchctl_read_failed":
            return "macOS服务状态读取失败"
        case "missing_or_untrusted_launchagent","launchagent_owner_mismatch":
            return "启动配置未经核验，请检查本机服务安装"
        case "bootout_failed","bootstrap_failed":
            return "系统没有完成启停，请查看本机日志"
        case "readback_mismatch","service_still_loaded":
            return "系统回读与请求不一致，开关已恢复真实状态"
        default:
            return "系统未确认本次操作"
        }
    }

    private func change(_ service:String,_ enabled:Bool) {
        guard applying==nil,services[service] != nil else{return}
        if !enabled {
            pendingOff=service
            showTurnOff=true
            return
        }
        apply(service,true)
    }

    private func apply(_ service:String,_ enabled:Bool) {
        guard applying==nil else{return}
        applying=service
        notice="正在通过 macOS 系统服务管理器核实变更…"
        Task.detached(priority:.userInitiated) {
            let reply=Self.manager([service,enabled ? "on":"off"])
            await MainActor.run {
                applying=nil
                if let reply,reply.schema==1,
                   let actual=reply.services {
                    services=actual
                    if reply.ok &&
                       actual[service]?.enabled==enabled {
                        notice=enabled ? "已开启服务托管；实际连接状态以运行回执为准。"
                                       : "已关闭服务托管，Mac 已确认服务退出。"
                    } else {
                        notice=localReason(reply.reason)+"；已按系统实际状态显示。"
                    }
                } else {
                    services=[:]
                    notice="服务操作没有可信回执，开关状态暂不确认。"
                }
            }
        }
    }

    private func serviceSwitch(_ key:String,_ title:String,
                               _ detail:String) -> some View {
        HStack(alignment:.center,spacing:14) {
            VStack(alignment:.leading,spacing:4) {
                Text(title).font(.system(size:13,weight:.medium))
                Text(detail)
                    .font(.system(size:11)).foregroundStyle(.secondary)
                    .fixedSize(horizontal:false,vertical:true)
                if let live=services[key] {
                    Text(live.running ? "系统确认正在运行" :
                         live.enabled ? "已允许启动 · 等待条件满足":"已停用")
                        .font(.system(size:11))
                        .foregroundStyle(.secondary)
                }
            }
            Spacer(minLength:8)
            Toggle(title,isOn:Binding(
                get:{services[key]?.enabled == true},
                set:{change(key,$0)}))
                .labelsHidden()
                .toggleStyle(.switch)
                .disabled(services[key]==nil || applying != nil ||
                          store.connecting || wirelessBusy ||
                          (key=="usb" && !canSafelyChangeVoice))
                .accessibilityLabel(title)
                .accessibilityHint("切换的是 macOS LaunchAgent 托管许可；只在有实际读回时更新。")
                .accessibilityIdentifier("r459-switch-"+key)
        }
    }

    private var canSafelyChangeVoice:Bool {
        guard let info=store.snapshot,
              info.session_verified == true,
              Date().timeIntervalSince1970-info.updated_at_unix<12 else {
            // A currently unloaded service cannot have a fresh USB snapshot.
            return services["usb"]?.loaded == false
        }
        return info.phase=="idle" && !store.connecting
    }

    private func recover() {
        if store.dshServiceState != "已就绪" {
            store.startDshService()
        } else if services["transport"]?.enabled == true &&
                  services["transport"]?.running == false {
            store.startWiFiGateway()
        } else if services["usb"]?.enabled == true &&
                  services["usb"]?.running == false && !wirelessBusy {
            store.startVoiceService()
        } else {
            refreshServices()
            notice="服务托管状态已刷新；连接状态仍以设备与会话回执为准。"
        }
    }

    var body:some View {
        VStack(alignment:.leading,spacing:13) {
            if !compact {
                Text("Mac 后台服务").font(.system(size:16,weight:.semibold))
            }
            serviceSwitch("usb","USB 语音服务",
                          "只管理USB通道，使用无线通话时不可切换。")
            Divider()
            serviceSwitch("transport","自动管理 USB / Wi-Fi 通道",
                          "随设备连接方式自动切换唯一语音通道。")
            Divider()
            HStack(alignment:.center,spacing:12) {
                VStack(alignment:.leading,spacing:5) {
                    LabeledContent("官方 DSH",value:store.dshServiceState)
                    LabeledContent("Qwen 声音",value:store.localTTSReady ? "就绪":"尚未就绪")
                }
                Spacer(minLength:10)
                Button("检查并修复"){recover()}
                    .disabled(applying != nil || store.connecting || wirelessBusy)
                    .help("仅在服务异常时恢复所需服务，不关闭共享DSH或Qwen")
            }
            if wirelessBusy {
                Label("无线设备正在使用，服务切换已锁定",systemImage:"lock.shield")
                    .font(.caption).foregroundStyle(.secondary)
            }
            if applying != nil || store.connecting {
                ProgressView("正在核验后台服务…").controlSize(.small)
            }
            if !notice.isEmpty {
                Text(notice)
                    .font(.system(size:11)).foregroundStyle(.secondary)
                    .fixedSize(horizontal:false,vertical:true)
            }
            if !store.launchStatus.isEmpty {
                Text(store.launchStatus)
                    .font(.system(size:11)).foregroundStyle(.secondary)
                    .fixedSize(horizontal:false,vertical:true)
            }
        }
        .font(.system(size:13))
        .accessibilityIdentifier("r317-service-controls")
        .confirmationDialog("确认关闭这项服务？",
                            isPresented:$showTurnOff,titleVisibility:.visible) {
            Button("关闭服务",role:.destructive) {
                if let service=pendingOff {apply(service,false)}
                pendingOff=nil
            }
            Button("取消",role:.cancel){pendingOff=nil}
        } message: {
            Text(pendingOff=="transport" ?
                 "关闭后Mac不会自动在USB与Wi-Fi之间切换；不会中断正在进行的对话，繁忙时操作会被拒绝。" :
                 "关闭USB语音后台后无法使用USB录音与播报，重新打开开关可恢复。Wi-Fi通话中不能关闭。")
        }
        .onAppear {refreshWirelessBusy();refreshServices()}
        .onReceive(Timer.publish(every:5,on:.main,in:.common).autoconnect()) { _ in
            refreshWirelessBusy()
            refreshServices()
        }
    }
}

struct CompanionManagementCenter: View {
    @ObservedObject var store: CompanionStore
    @ObservedObject var navigation:ManagementNavigation
    @State private var animationWorkspace:AnimationWorkspace = .library
    @State private var previewMode:CompanionPreviewMode = .following
    @State private var localPreviewID="m037"
    @State private var selectedMotionID="m000"
    @State private var unsavedRules:[String:String]? = nil
    @State private var showPersonaEditor=false
    @StateObject private var personaModel=PersonaOverviewModel()
    @State private var showPixels=false
    @State private var showVoiceGuide=false
    @State private var showContextManager=false
    @State private var pendingMemorySuggestions=0
    // Keep a verified task's native progress while the JSON projector
    // temporarily omits current_task_id during polling/recomposition.
    @State private var carriedTask:(String,[String])?=nil
    @State private var carriedTaskID:String?=nil
    @StateObject private var computerApproval=R675ComputerQuestionModel.shared
    @StateObject private var contextSummary=R678ContextSummaryModel.shared
    @State private var lastContextRefresh=Date.distantPast
    @State private var replyComparison:R499ReplyComparison?=nil
    // A completed turn keeps its verified spoken script after the receipt
    // changes to the next turn or a transient snapshot read fails.
    @State private var spokenByOriginal:[String:String]=[:]
    @State private var spokenByID:[String:String]=[:]
    @State private var ambiguousOriginals:Set<String>=[]
    @State private var spokenSessionID:String?=nil
    @State private var r634HistoryStamp:String?=nil
    @State private var r634ComparisonStamp:String?=nil

    private static func trustedReadOnlyStamp(_ name:String,
                                             maxSize:Int)->String? {
        let url=FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/Deepseek-live/companion-native/")
            .appendingPathComponent(name)
        guard let attrs=try? FileManager.default.attributesOfItem(atPath:url.path),
              attrs[.type] as? FileAttributeType == .typeRegular,
              let mode=attrs[.posixPermissions] as? NSNumber,
              mode.intValue & 0o077 == 0,
              let owner=attrs[.ownerAccountID] as? NSNumber,
              owner.intValue == Int(getuid()),
              let size=attrs[.size] as? NSNumber,
              size.intValue>20 && size.intValue<=maxSize,
              let date=attrs[.modificationDate] as? Date,
              let flags=try? url.resourceValues(forKeys:[.isRegularFileKey,.isSymbolicLinkKey]),
              flags.isRegularFile==true && flags.isSymbolicLink != true
        else {return nil}
        return "\(date.timeIntervalSince1970):\(size.intValue)"
    }

    private func refreshReplyComparison() {
        guard let sid=store.conversationSessionID else { return }
        if spokenSessionID != sid {
            spokenByOriginal=[:]
            spokenByID=[:]
            ambiguousOriginals=[]
            replyComparison=nil
            spokenSessionID=sid
            r634HistoryStamp=nil
            r634ComparisonStamp=nil
        }
        // R634: snapshots are atomically rewritten, and the UI timer runs
        // every 600ms. Re-publishing identical @State dictionaries repeatedly
        // forces expensive full SwiftUI chat layout on the main thread.
        let historyStamp=Self.trustedReadOnlyStamp(
            "reply-speech-history-v1.json",maxSize:800_000)
        if let stamp=historyStamp,stamp != r634HistoryStamp,
           let archived=R520SpokenHistoryReader.read(for:sid) {
            var byID=spokenByID
            var byOriginal=spokenByOriginal
            var ambiguous=ambiguousOriginals
            var grouped:[String:[String]]=[:]
            for item in archived {
                if let id=item.speech_id {byID[id]=item.spoken_text}
                grouped[item.original_text,default:[]].append(item.spoken_text)
            }
            for (original,values) in grouped {
                if values.count==1 {
                    byOriginal[original]=values[0]
                } else {
                    ambiguous.insert(original)
                    byOriginal.removeValue(forKey:original)
                }
            }
            if byID != spokenByID {spokenByID=byID}
            if byOriginal != spokenByOriginal {spokenByOriginal=byOriginal}
            if ambiguous != ambiguousOriginals {ambiguousOriginals=ambiguous}
            r634HistoryStamp=stamp
        }
        let comparisonStamp=Self.trustedReadOnlyStamp(
            "reply-speech-comparison-v1.json",maxSize:48_000)
        if let stamp=comparisonStamp,stamp != r634ComparisonStamp,
           let record=R499ComparisonReader.read(for:sid) {
            replyComparison=record
            if record.tts_generated,let id=record.speech_id,
               spokenByID[id] != record.spoken_text {
                spokenByID[id]=record.spoken_text
            }
            r634ComparisonStamp=stamp
        }
    }


    private var provenDeviceID:String? {
        guard store.espVerified,let status=store.snapshot,
              status.esp32_frame_verified==true,
              let id=status.esp32_frame_motion_id,
              id.range(of:#"^m[0-9]{3}$"#,options:.regularExpression) != nil else {
            return nil
        }
        return id
    }
    // Same physical state contract as the existing 1s verified projector;
    // no claim of exact optical or frame synchronization.
    private var previewID:String? {
        previewMode == .local ? localPreviewID : provenDeviceID
    }
    private var connected:Bool {store.bothVerified} // USB only.
    @State private var wifiStatus:VerifiedWiFiGateway? = nil
    private var verifiedTransport:VerifiedCompanionTransport {
        VerifiedCompanionTransport.resolve(usbVerified:connected,wifi:wifiStatus)
    }
    private var wifiConnected:Bool {verifiedTransport.isWiFi}
    private var wifiPending:Bool {
        !wifiConnected && (wifiStatus?.active_devices == 1 ||
                           wifiStatus?.pending_dsh_jobs == 1)
    }
    private var connectionHeadline:String {
        if wifiConnected { return "ESP32 已通过 Wi-Fi 连接 Mac" }
        if wifiPending { return "无线连接正在核验" }
        if connected { return "ESP32 已通过 USB 连接 Mac" }
        return "大肥鱼管理中心"
    }
    private var connectionSubtitle:String {
        if wifiConnected { return "当前语音通道 · Wi-Fi / WSS · \(wifiStatus?.phaseDescription ?? "待确认")" }
        if wifiPending { return "无线网关仍有设备或任务，尚未收到鉴权完成回执" }
        if connected { return "当前语音通道 · USB · \(store.phase)" }
        return "没有已验证的语音通道 · 查看连接状态"
    }

    // Privacy-safe navigation count; reading suggestions never modifies E1b.
    private static func trustedPendingCount() -> Int {
        let url=FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/Deepseek-live/companion-native/voice-memory-candidates.json")
        guard let attrs=try? FileManager.default.attributesOfItem(atPath:url.path),
              (attrs[.type] as? FileAttributeType) == .typeRegular,
              (((attrs[.posixPermissions] as? NSNumber)?.intValue ?? 1) & 0o077) == 0,
              ((attrs[.size] as? NSNumber)?.intValue ?? 32769) <= 32768,
              let raw=try? Data(contentsOf:url),
              let obj=try? JSONSerialization.jsonObject(with:raw) as? [String:Any],
              obj["schema"] as? Int == 1,let rows=obj["items"] as? [[String:Any]],
              rows.count <= 24 else {return 0}
        let now=Date().timeIntervalSince1970
        return rows.filter { row in
            guard let stamp=row["created_at"] as? Double else {return false}
            return now-stamp >= -5 && now-stamp <= 14*86400
        }.count
    }

    var body:some View {
        // R206: a fixed, noncollapsible sidebar. NavigationSplitView can
        // automatically collapse its List when the 106-rule inspector reports
        // an expansive minimum width. The user then loses every navigation
        // control including the way back to Overview.
        HStack(spacing:0) {
            VStack(alignment:.leading,spacing:6) {
                HStack(spacing:12) {
                    if let url=Bundle.main.url(forResource:"deepseek-live-icon",withExtension:"png"),
                       let icon=NSImage(contentsOf:url) {
                        Image(nsImage:icon).resizable().scaledToFit()
                            .frame(width:42,height:42)
                            .clipShape(RoundedRectangle(cornerRadius:11))
                    }
                    VStack(alignment:.leading,spacing:3) {
                        Text("大肥鱼").font(.system(size:16,weight:.semibold))
                        Text("管理中心").font(.system(size:11)).foregroundStyle(.secondary)
                    }
                }
                .padding(.horizontal,8)
                .padding(.top,12)
                .padding(.bottom,22)
                ForEach(ManagementSection.allCases){ section in
                    Button {
                        navigation.section=section
                    } label: {
                        HStack(spacing:12) {
                            Image(systemName:section.icon)
                                .font(.system(size:14,weight:.medium))
                                .frame(width:20)
                            Text(section.rawValue)
                            Spacer(minLength:0)
                            if section == .memory && pendingMemorySuggestions > 0 {
                                Text("\(pendingMemorySuggestions)")
                                    .font(.caption.weight(.semibold))
                                    .foregroundStyle(Color.accentColor)
                                    .padding(.horizontal,7).padding(.vertical,3)
                                    .background(Color.accentColor.opacity(0.12),in:Capsule())
                                    .accessibilityLabel("待审核记忆 \(pendingMemorySuggestions) 条")
                            }
                        }
                        .font(.system(size:14,weight:
                            navigation.section==section ? .semibold : .regular))
                        .foregroundStyle(navigation.section==section ?
                            Color.accentColor : Color.primary)
                        .padding(.horizontal,12).padding(.vertical,13)
                        .background(navigation.section==section ?
                            Color.accentColor.opacity(0.12) : Color.clear,
                            in:RoundedRectangle(cornerRadius:11))
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("r206-sidebar-"+section.rawValue)
                }
                Spacer(minLength:0)
                Text("本地资料保存在这台 Mac")
                    .font(.system(size:13))
                    .foregroundStyle(.secondary)
                    .padding(.horizontal,12)
                    .padding(.bottom,10)
            }
            .padding(12)
            .frame(width:220)
            .background(Color.accentColor.opacity(0.055))
            .background(Color(nsColor:.windowBackgroundColor))
            Divider()
            VStack(spacing:0) {
                HStack {
                    Text(navigation.section.rawValue)
                        .font(.system(size:20,weight:.semibold))
                    Spacer()
                    // Reconnect belongs beside the connection state, not
                    // in a global "refresh everything" position.
                }
                .padding(.horizontal,26).padding(.vertical,18)
                Divider()
                // Native CUA question must remain reachable even when the
                // user is viewing a different management-center section.
                if computerApproval.pending != nil && navigation.section != .conversations {
                    HStack(spacing:12) {
                        Image(systemName:"hand.raised").foregroundStyle(Color.accentColor)
                        Text("Mac 电脑任务正在等待你的原生授权选择")
                            .font(.system(size:14,weight:.medium))
                        Spacer()
                        Button("查看并决定") {navigation.section = .conversations}
                            .buttonStyle(.borderedProminent)
                    }
                    .padding(.horizontal,26).padding(.vertical,12)
                    Divider()
                }
                // Show a real review action, not only a sidebar count. No
                // interruption, system notification, or automatic approval.
                if pendingMemorySuggestions > 0 && navigation.section != .memory {
                    HStack(spacing:12) {
                        Image(systemName:"brain.head.profile")
                            .foregroundStyle(Color.accentColor)
                        Text("有 \(pendingMemorySuggestions) 条语音记忆等你确认")
                            .font(.system(size:14,weight:.medium))
                        Spacer(minLength:8)
                        Button("查看记忆建议") { navigation.section = .memory }
                            .buttonStyle(.borderedProminent)
                            .accessibilityIdentifier("r553-open-pending-memory")
                    }
                    .padding(.horizontal,26).padding(.vertical,12)
                    .background(Color.accentColor.opacity(0.075))
                    Divider()
                }
                Group {
                    switch navigation.section {
                    case .overview: overview
                    case .animations: animations
                    case .conversations: conversations
                    case .memory: MemoryOverviewSheet(isPresented:.constant(true),embedded:true)
                    case .plugins: CompanionPluginsView()
                    case .diagnostics: diagnostics
                    case .preferences: CompanionPreferencesView(store:store,embedded:true,
                        openDiagnostics:{navigation.section = .diagnostics},
                        openMemory:{navigation.section = .memory})
                    }
                }
                .frame(maxWidth:.infinity,maxHeight:.infinity,alignment:.top)
            }
            .frame(maxWidth:.infinity,maxHeight:.infinity,alignment:.top)
            .background(Color(nsColor:.windowBackgroundColor))
        }
        .frame(minWidth:920,minHeight:720)
        .onAppear {
            wifiStatus=VerifiedWiFiGateway.read()
            pendingMemorySuggestions=Self.trustedPendingCount()
            computerApproval.refresh()
            contextSummary.refresh()
            lastContextRefresh=Date()
            refreshReplyComparison()
        }
        .onReceive(Timer.publish(every:0.6,on:.main,in:.common).autoconnect()) { _ in
            // An incomplete projector revision may momentarily hide a live
            // CUA stage. Do not flash the progress bubble away between reads.
            // Clear only on a verified terminal/idle state of this Session.
            if let tid=store.snapshot?.current_task_id,
               let live=store.activeTaskConversation {
                if tid == carriedTaskID,let previous=carriedTask {
                    var lines=previous.1
                    for item in live.1 where !lines.contains(item) {lines.append(item)}
                    carriedTask=(live.0,Array(lines.suffix(8)))
                } else {
                    carriedTaskID=tid
                    carriedTask=live
                }
            } else if store.snapshot?.session_verified == true &&
                      store.snapshot?.phase == "idle" {
                carriedTaskID=nil
                carriedTask=nil
            }
            if navigation.section == .conversations {
                refreshReplyComparison()
                if Date().timeIntervalSince(lastContextRefresh)>9 {
                    lastContextRefresh=Date()
                    contextSummary.refresh()
                }
            }
        }
        .onChange(of:navigation.section) { _,section in
            if section == .conversations {
                refreshReplyComparison()
                contextSummary.refresh()
                lastContextRefresh=Date()
            }
        }
        .onReceive(Timer.publish(every:2,on:.main,in:.common).autoconnect()) { _ in
            computerApproval.refresh()
        }
        .onReceive(Timer.publish(every:4,on:.main,in:.common).autoconnect()) { _ in
            let latest=VerifiedWiFiGateway.read()
            if let before=wifiStatus,let next=latest {
                if !before.sameVisibleStatus(as:next) {wifiStatus=next}
            } else if (wifiStatus == nil) != (latest == nil) {
                wifiStatus=latest
            }
            let count=Self.trustedPendingCount()
            if pendingMemorySuggestions != count {pendingMemorySuggestions=count}
        }
        .sheet(isPresented:$showPersonaEditor) {
            PersonaEditorSheet(model:personaModel,isPresented:$showPersonaEditor)
        }
        .sheet(isPresented:$showPixels) {
            RemoteDisplaySheet(store:store)
        }
        .sheet(isPresented:$showVoiceGuide) {
            CompanionVoiceGuideView(store:store)
        }
    }

    private var overview:some View {
        GeometryReader { window in
            ScrollView {
                VStack(alignment:.leading,spacing:24) {
                    HStack(alignment:.center) {
                        VStack(alignment:.leading,spacing:6) {
                            Text(connectionHeadline)
                                .font(.system(size:24,weight:.semibold))
                            Text(connectionSubtitle)
                                .font(.system(size:13)).foregroundStyle(.secondary)
                        }
                        Spacer()
                        if wifiConnected {
                            Label("无线通道已鉴权",systemImage:"wifi")
                                .font(.system(size:13,weight:.medium))
                                .foregroundStyle(.secondary)
                        } else if connected {
                            Label(store.verifiedModelBadge,systemImage:"sparkle")
                                .font(.system(size:13,weight:.medium))
                                .foregroundStyle(.secondary)
                        }
                    }
                    HStack(alignment:.top,spacing:18) {
                        VStack(alignment:.leading,spacing:14) {
                            HStack {
                                Text("动画预览").font(.system(size:16,weight:.semibold))
                                Spacer()
                                if let id=provenDeviceID {
                                    Text("设备 \(id.uppercased())")
                                        .font(.system(size:11,design:.monospaced))
                                        .foregroundStyle(.secondary)
                                }
                            }
                            Picker("预览模式",selection:$previewMode) {
                                ForEach(CompanionPreviewMode.allCases,id:\.self){mode in
                                    Text(mode.rawValue).tag(mode)
                                }
                            }
                            .pickerStyle(.segmented)
                            .labelsHidden()
                            if previewMode == .local {
                                Picker("本机动画",selection:$localPreviewID) {
                                    ForEach(0..<106,id:\.self){number in
                                        let id=String(format:"m%03d",number)
                                        Text(id.uppercased()).tag(id)
                                    }
                                }.frame(maxWidth:.infinity)
                            }
                            if let id=previewID,let gif=store.motionFile(for:id) {
                                PrivateMotionPlayer(url:gif)
                                    .id(id)
                                    .frame(maxWidth:.infinity)
                                    .frame(height:min(380,max(300,window.size.height*0.48)))
                                    .background(Color.accentColor.opacity(0.045))
                                    .clipShape(RoundedRectangle(cornerRadius:12))
                            } else {
                                ContentUnavailableView(
                                    previewMode == .local ? "本地动画预览不可用" : "尚无设备动作回执",
                                    systemImage:"display",
                                    description:Text(previewMode == .local
                                        ? "请检查本机预览素材是否就绪"
                                        : "设备发送下一次可信首帧回执后会显示"))
                                    .frame(maxWidth:.infinity)
                                    .frame(height:min(380,max(300,window.size.height*0.48)))
                                    .background(Color.accentColor.opacity(0.045),
                                                in:RoundedRectangle(cornerRadius:12))
                            }
                            Text(previewMode == .local
                                ? "仅在Mac播放，不控制ESP32"
                                : provenDeviceID != nil
                                  ? "设备最近确认的动作 · 不保证逐帧同相"
                                  : "设备首帧尚未确认 · 不使用本地动作冒充")
                                .font(.system(size:12))
                                .foregroundStyle(.secondary)
                        }
                        .padding(20)
                        .background(Color.primary.opacity(0.035),
                                    in:RoundedRectangle(cornerRadius:16))
                        .frame(maxWidth:.infinity,alignment:.leading)
                        VStack(alignment:.leading,spacing:14) {
                            VStack(alignment:.leading,spacing:15) {
                                HStack {
                                    Label("连接概况",systemImage:"dot.radiowaves.left.and.right")
                                        .font(.system(size:16,weight:.semibold))
                                    Spacer()
                                    Image(systemName: verifiedTransport.isConnected && !wifiPending
                                          ? "checkmark.circle.fill" : "exclamationmark.circle")
                                        .foregroundStyle(verifiedTransport.isConnected && !wifiPending
                                            ? Color.green : Color.orange)
                                        .accessibilityLabel(verifiedTransport.isConnected && !wifiPending
                                            ? "有已验证连接" : "连接待核验")
                                }
                                Text(wifiConnected ? "Wi-Fi · 已鉴权" :
                                     wifiPending ? "无线连接待核验" :
                                     connected ? "USB · 已验证" : "设备连接待核验")
                                    .font(.system(size:14,weight:.medium))
                                if wifiConnected {
                                    Text(wifiStatus?.phaseDescription ?? "无线阶段尚未确认")
                                        .font(.system(size:12)).foregroundStyle(.secondary)
                                    LabeledContent("持续唤醒",
                                        value:wifiStatus?.prewake_enabled == true ? "已开启" : "未确认开启")
                                        .font(.system(size:12))
                                } else if wifiPending {
                                    Text("正在验证无线设备身份；请等待实时回执")
                                        .font(.callout).foregroundStyle(.secondary)
                                } else if connected {
                                    Text(store.phase)
                                        .font(.system(size:12)).foregroundStyle(.secondary)
                                } else {
                                    Text("详细连接状态及服务恢复操作在设备诊断中查看。")
                                        .font(.system(size:12)).foregroundStyle(.secondary)
                                        .fixedSize(horizontal:false,vertical:true)
                                }
                                Divider()
                                HStack(spacing:10) {
                                    Button("连接与诊断",systemImage:"stethoscope") {
                                        navigation.section = .diagnostics
                                    }
                                    Button("动画规则",systemImage:"square.stack") {
                                        navigation.section = .animations
                                        animationWorkspace = .rules
                                    }
                                }
                                .buttonStyle(.bordered)
                                .controlSize(.regular)
                            }
                            .padding(20)
                            .background(Color.primary.opacity(0.035),
                                        in:RoundedRectangle(cornerRadius:16))
                            .frame(maxWidth:.infinity,alignment:.leading)
                            PersonaSummaryCard(model:personaModel,openEditor:{
                                showPersonaEditor=true
                            })
                            .frame(maxWidth:.infinity,alignment:.leading)
                        }
                        .frame(maxWidth:370,alignment:.leading)
                    }
                    .frame(maxWidth:.infinity,alignment:.topLeading)
                    Spacer(minLength:0)
                }
                .padding(28)
                .frame(maxWidth:.infinity,
                       minHeight:max(490,window.size.height-12),alignment:.topLeading)
            }
        }
    }

    private var animations:some View {
        VStack(spacing:0) {
            HStack {
                Picker("管理内容",selection:$animationWorkspace) {
                    ForEach(AnimationWorkspace.allCases,id:\.self){ tab in
                        Text(tab.rawValue).tag(tab)
                    }
                }
                .pickerStyle(.segmented)
                .controlSize(.large)
                .frame(width:325)
                Spacer()
                Text("修改先保存于Mac，应用仍需实体授权")
                    .foregroundStyle(.secondary)
                    .font(.system(size:12))
            }
            .padding(.horizontal,24)
            .padding(.vertical,16)
            .background(Color.accentColor.opacity(0.035))
            Divider()
            Group {
                switch animationWorkspace {
                case .library:
                    MotionLibrarySheet(store:store,embedded:true,
                        openRules:{animationWorkspace = .rules},
                        sharedSelection:$selectedMotionID)
                case .rules:
                    MotionTriggers106Sheet(store:store,
                        onClose:{animationWorkspace = .library},
                        embedded:true,
                        sharedSelection:$selectedMotionID,
                        sessionChanges:$unsavedRules)
                }
            }
            .frame(maxWidth:.infinity,maxHeight:.infinity,alignment:.topLeading)
        }
        .frame(maxWidth:.infinity,maxHeight:.infinity)
    }

    // R205: same left/right conversational rhythm as the floating History
    // sheet. The model's source Markdown is read-only, rendered with the
    // shared bounded component; never display literal ** markers as prose.
    private func chatBubble(_ content:String, user:Bool, origin:String="") -> some View {
        HStack(alignment:.top,spacing:10) {
            if user {Spacer(minLength:58)}
            if !user {
                Image(systemName:"sparkles")
                    .font(.system(size:12,weight:.semibold))
                    .foregroundStyle(Color.accentColor)
                    .frame(width:30,height:30)
                    .background(Color.accentColor.opacity(0.10),in:Circle())
            }
            VStack(alignment:user ? .trailing : .leading,spacing:5) {
                Text(user ? "你" : "大肥鱼 · " + (origin.isEmpty ? "原始回答" : origin))
                    .font(.system(size:11,weight:.semibold))
                    .foregroundStyle(.secondary)
                Group {
                    if user {
                        Text(content).font(.system(size:13))
                            .textSelection(.enabled)
                    } else {
                        ReadableMarkdownView(source:content)
                    }
                }
                .frame(maxWidth:650,alignment:.leading)
                .padding(.horizontal,18).padding(.vertical,15)
                .background(user ?
                    Color(nsColor:.controlAccentColor).opacity(0.13) :
                    Color(nsColor:.windowBackgroundColor),
                    in:RoundedRectangle(cornerRadius:14))
            }
            if !user {Spacer(minLength:58)}
        }
        .frame(maxWidth:.infinity)
    }
    // Show the verified spoken script in its own conversation bubble only
    // when it is bound to the exact original answer of that same turn.
    private func displayedAssistant(_ turn:ConversationPreview, index:Int, count:Int) -> (String,String) {
        let original = (turn.assistant,"原始回复")
        guard let sessionID = store.conversationSessionID, spokenSessionID == sessionID else {
            return original
        }
        if let id=turn.speech_id {
            if let record=replyComparison,record.speech_id==id {
                if record.tts_generated {
                    let final=record.final_spoken_text ?? record.spoken_text
                    return (final,record.device_playback_verified ? "结果朗读稿 · 已播放" :
                            (final == turn.assistant ? "回复" : "已合成结果朗读稿"))
                }
                if let completed=spokenByID[id] {return (completed,"已合成朗读稿")}
                let generating=store.snapshot?.answer_speech_id==id &&
                    ["voice_generating","speaking"].contains(store.snapshot?.phase ?? "")
                return (record.final_spoken_text ?? record.spoken_text,
                        generating ? "结果朗读稿 · 合成中" : "结果朗读稿 · 未完成")
            }
            if let completed=spokenByID[id] {return (completed,"已合成朗读稿")}
        } else if !ambiguousOriginals.contains(turn.assistant),
                  store.conversationPreview.filter({$0.assistant==turn.assistant}).count==1,
                  let spoken=spokenByOriginal[turn.assistant] {
            return (spoken,"已合成朗读稿")
        }
        return original
    }

    private func displayedSpokenProgress() -> String? {
        guard let state=store.snapshot,state.session_verified==true,
              ["thinking","tool_pending","approval_pending"].contains(state.phase),
              let text=state.spoken_progress_text?.trimmingCharacters(in:.whitespacesAndNewlines),
              !text.isEmpty,text.count<=200 else {return nil}
        return text
    }

    private var conversations:some View {
        VStack(alignment:.leading,spacing:18) {
            HStack {
                VStack(alignment:.leading,spacing:3) {
                    Text("近期对话").font(.system(size:21,weight:.semibold))
                    Text("显示原始回复或核实后的朗读稿；旧的待审批提示属于历史内容。")
                        .foregroundStyle(.secondary)
                        .font(.system(size:13))
                }
                Spacer()
                Button("上下文与新会话") {showContextManager=true}
                    .buttonStyle(.bordered)
                    .accessibilityIdentifier("r677-context-archive-new-session")
                    .sheet(isPresented:$showContextManager){R677ConversationContextSheet()}
            }
            if let context=contextSummary.info {
                VStack(alignment:.leading,spacing:7) {
                    HStack(spacing:12) {
                        Label(context.current_session_label ?? "当前 DSH 会话",
                              systemImage:"checkmark.circle")
                            .font(.system(size:14,weight:.semibold))
                        if let id=context.current_session {
                            Text("会话 ID：\(String(id.prefix(8)))")
                                .font(.system(size:12,design:.monospaced))
                                .foregroundStyle(.secondary)
                        }
                        Text("本会话 \(context.visible_turns ?? 0) 条")
                            .font(.caption).foregroundStyle(.secondary)
                        Spacer()
                        if let percent=context.context_usage_percent {
                            Text(String(format:"上下文 %.1f%%",percent))
                                .font(.system(size:15,weight:.semibold))
                                .monospacedDigit()
                        } else {
                            Text("新会话 · 待首轮 Token 记录")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                    }
                    if let pct=context.context_usage_percent {
                        ProgressView(value:min(100,max(0,pct)),total:100)
                            .tint(Color.accentColor)
                        if let used=context.context_usage_tokens,
                           let limit=context.context_window_tokens {
                            Text("DSH 当前上下文压力 \(used.formatted()) / \(limit.formatted()) Tokens · 最近一次原生记录")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                    }
                    if context.previous_new_session_failed == true {
                        Text("上次新建未成功，仍在原会话；历史备份已保留。")
                            .font(.caption.weight(.medium)).foregroundStyle(.orange)
                    }
                    Text("这里仅显示当前会话；旧对话可到「上下文与新会话」中查看只读档案。")
                        .font(.caption).foregroundStyle(.secondary)
                }
                .padding(12)
                .frame(maxWidth:.infinity,alignment:.leading)
                .background(Color.accentColor.opacity(0.045),
                            in:RoundedRectangle(cornerRadius:11))
            }
            HStack {
                Text("当前实际待审批语音记忆：\(pendingMemorySuggestions) 条")
                    .font(.caption).foregroundStyle(.secondary)
                Spacer()
                if computerApproval.pending != nil {
                    Text("Mac 电脑操作等待本人授权").font(.caption.weight(.semibold))
                }
            }
            R675ComputerQuestionPanel(model:computerApproval)
            ScrollViewReader { reader in
            ScrollView {
                LazyVStack(alignment:.leading,spacing:18) {
                    let progress=displayedSpokenProgress()
                    let active=store.activeTaskConversation ?? carriedTask
                    if store.conversationPreview.isEmpty && progress == nil &&
                       active == nil {
                        ContentUnavailableView("暂无已验证对话",
                                               systemImage:"bubble.left")
                            .frame(maxWidth:.infinity,minHeight:220)
                    } else {
                        ForEach(Array(store.conversationPreview.enumerated()),id:\.offset) {index,turn in
                            // R536: the R535 0.6s management-center timer may
                            // temporarily retain a PENDING @State snapshot
                            // after the native backend overwrites it with
                            // verified final PCM and playback ACK.
                            // Resolve the CURRENT trusted same-session receipt
                            // first; only use legacy cached selector as fallback.
                            // This is the same shared, tested R531 resolver
                            // as the floating "最近会话" view.
                            let verified=R531VerifiedSpokenDisplay.resolve(
                                turn:turn,sessionID:store.conversationSessionID)
                            let display=verified ?? displayedAssistant(
                                turn,index:index,count:store.conversationPreview.count)
                            VStack(spacing:9) {
                                chatBubble(String(turn.user.prefix(650)),user:true)
                                ForEach(turn.progress ?? [],id:\.self) { line in
                                    chatBubble(line,user:false,origin:"任务进度")
                                }
                                chatBubble(display.0,user:false,origin:display.1)
                                R683PhoneSearchOriginalView(turn:turn)
                            }
                            .frame(maxWidth:.infinity)
                        }
                        if let active {
                            chatBubble(active.0,user:true)
                            ForEach(active.1,id:\.self) { line in
                                chatBubble(line,user:false,origin:"处理中")
                            }
                        } else if let progress {
                            chatBubble(progress,user:false,origin:"任务进度")
                        }
                    }
                    Color.clear.frame(height:1).id("r683-conversation-tail")
                }
                .padding(20)
                .frame(maxWidth:800,alignment:.leading)
                .frame(maxWidth:.infinity,alignment:.center)
            }
            .frame(maxWidth:.infinity,maxHeight:.infinity)
            .background(Color.primary.opacity(0.035),in:RoundedRectangle(cornerRadius:16))
            .onAppear { reader.scrollTo("r683-conversation-tail",anchor:.bottom) }
            .onChange(of:store.conversationPreview.count) { _,_ in
                reader.scrollTo("r683-conversation-tail",anchor:.bottom)
            }
            }
        }
        .padding(26)
    }

    private var diagnostics:some View {
        CompanionDiagnosticsHubSheet(
            store:store, embedded:true,
            openPixels:{showPixels=true},
            openMotions:{navigation.section = .animations},
            openVoice:{showVoiceGuide=true})
        .frame(maxWidth:.infinity,maxHeight:.infinity,alignment:.topLeading)
    }

}

// Native Preferences uses the same live store and existing preference keys.
// It does not open the microphone, mutate NVS, or fake unavailable wake models.
struct CompanionPreferencesView:View {
    @ObservedObject var store:CompanionStore
    @AppStorage("dafeiyu.r32.idleSeconds") private var idleSeconds=90
    @State private var showWake=false
    @State private var showMemory=false
    var embedded:Bool = false
    var openDiagnostics:(() -> Void)? = nil
    var openMemory:(() -> Void)? = nil
    var body:some View {
        Form {
            Section("会话") {
                LabeledContent("当前模型",value:store.modelLabel)
                HStack(spacing:9) {
                    Button("Flash"){store.requestModel("deepseek-flash")}
                    Button("Pro"){store.requestModel("deepseek-v4-pro")}
                    Spacer()
                    Text("仅在DSH确认后生效")
                        .foregroundStyle(.secondary)
                        .font(.system(size:11))
                }
                .disabled(!store.bothVerified || store.snapshot?.phase != "idle")
                if !store.modelChangeNotice.isEmpty {
                    Text(store.modelChangeNotice)
                        .font(.system(size:11)).foregroundStyle(.secondary)
                }
                HStack {
                    LabeledContent("联网搜索",value:store.activeSearch)
                    Button(store.snapshot?.search_enabled == true ? "关闭搜索" : "开启搜索") {
                        store.toggleSearch()
                    }
                    .disabled(!store.bothVerified ||
                              store.snapshot?.search_supported != true)
                }
                if !store.searchChangeNotice.isEmpty {
                    Text(store.searchChangeNotice)
                        .font(.system(size:11)).foregroundStyle(.secondary)
                }
            }
            Section("电脑操作权限") {
                R676ComputerPreconsentSettings()
            }
            Section("记忆") {
                Text("日常对话生成审核建议、手动添加以及已保存记忆，在同一页面管理。")
                    .font(.callout).foregroundStyle(.secondary)
                Button("管理记忆建议与手动添加") {
                    if let openMemory {openMemory()}
                    else {showMemory=true}
                }
            }
            Section("桌宠") {
                Picker("本地待机动作间隔",selection:$idleSeconds) {
                    Text("关闭").tag(0)
                    Text("60秒").tag(60)
                    Text("90秒").tag(90)
                    Text("120秒").tag(120)
                }
            }
            Section("设备与语音") {
                LabeledContent("拾音来源",value:"ESP32板载麦克风")
                Button("连接、持续唤醒与后台服务") { openDiagnostics?() }
                    .disabled(openDiagnostics == nil)
                VoicePreprocessorSettingsView()
                Button("查看板载唤醒能力"){showWake=true}
                Text("唤醒设置由当前设备配对与网关回执确认；真实声学效果仍需人工验收。")
                    .font(.system(size:11)).foregroundStyle(.secondary)
            }
        }
        .formStyle(.grouped)
        .padding(14)
        .frame(minWidth:embedded ? nil : 500,minHeight:embedded ? nil : 540)
        .sheet(isPresented:$showWake) {
            ESPWakeSettingsSheet(isPresented:$showWake,
                 hardwareReady:store.snapshot?.wake_capability_verified == true)
        }
        .sheet(isPresented:$showMemory) {
            MemoryOverviewSheet(isPresented:$showMemory)
        }
    }
}

struct CompanionVoiceGuideView:View {
    @ObservedObject var store:CompanionStore
    @Environment(\.dismiss) private var dismiss
    var body:some View {
        VStack(alignment:.leading,spacing:14) {
            HStack {
                Text("实体语音说明").font(.title2.weight(.semibold))
                Spacer()
                Button("关闭"){dismiss()}
            }
            LabeledContent("连接状态",value:VerifiedWiFiGateway.read()?.connected == true ?
                           "ESP32无线已鉴权" :
                           store.bothVerified ? "ESP32与DSH已验证" : "尚未验证")
            LabeledContent("语音通道",value:VerifiedWiFiGateway.read()?.connected == true ?
                           "Wi-Fi / WSS（以网关回执为准）" :
                           store.snapshot?.voice_streaming_enabled == true ?
                           "设备PCM2流式" : "尚未确认")
            Divider()
            Text("触摸模式下由ESP32开始或结束拾音；无线唤醒需通过真人验收。Mac不使用内建麦克风，也不会因打开这个页面自动录音。")
            Text("当前可用：询问时间、基础帮助、经过DSH验证的问答和经确认的会话模型选择。")
            Text("无线自定义唤醒与连续对话请以当前实机验收结果为准；Mac不会使用自身麦克风。")
                .foregroundStyle(.secondary)
            Spacer()
        }
        .padding(24)
        .frame(width:530,height:355)
    }
}


// R675: Native computer-use authorization from the ACTUAL DSH User Questions
// waterfall. These are explicit human decisions, never ambient tool approval.
// Polling is display-only; network credentials stay in the local Python proxy.
struct R675ComputerQuestion:Decodable,Identifiable {
    let task_id:String
    let request_id:String
    let question_id:String
    let question:String
    let detail:String
    let header:String
    let options:[String]
    var id:String {request_id}
}
private struct R675ComputerReply:Decodable {
    let ok:Bool
    let pending:R675ComputerQuestion?
    let submitted:Bool?
}
@MainActor
final class R675ComputerQuestionModel:ObservableObject {
    static let shared=R675ComputerQuestionModel()
    private var lastPresentedQuestionID:String?=nil
    private var activeQuestionWindow:NSWindow?=nil
    private var pollingTimer:Timer?=nil
    func startMonitoring(){
        guard pollingTimer == nil else {return}
        refresh()
        // Runs independently of management window visibility. A real
        // native CUA question can arrive while the pet is on the desktop.
        pollingTimer=Timer.scheduledTimer(withTimeInterval:1.5,repeats:true){
            [weak self] _ in
            Task { @MainActor in self?.refresh() }
        }
    }
    private func reconcileWindow(){
        guard let pending else {
            activeQuestionWindow?.close()
            activeQuestionWindow=nil
            lastPresentedQuestionID=nil
            return
        }
        guard lastPresentedQuestionID != pending.request_id else{return}
        activeQuestionWindow?.close()
        let pane=NSWindow(
            contentRect:NSRect(x:0,y:0,width:640,height:410),
            styleMask:[.titled,.closable,.resizable],
            backing:.buffered,defer:false)
        pane.title="大肥鱼 · 原生电脑操作授权"
        pane.isReleasedWhenClosed=false
        pane.level = .floating
        pane.minSize=NSSize(width:480,height:285)
        pane.contentView=NSHostingView(rootView:
            ScrollView {R675ComputerQuestionPanel(model:self)}
                .frame(minWidth:480,minHeight:280))
        pane.center()
        activeQuestionWindow=pane
        lastPresentedQuestionID=pending.request_id
        pane.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps:true)
    }
    @Published private(set) var pending:R675ComputerQuestion?=nil
    @Published private(set) var busy=false
    @Published private(set) var notice=""
    private nonisolated static func send(_ action:String,payload:[String:String]=[:])->R675ComputerReply? {
        let project=CompanionProjectPaths.rootURL
        let helper=project.appendingPathComponent("scripts/r675_computer_question.py")
        guard ["status","decide"].contains(action),
              FileManager.default.fileExists(atPath:helper.path),
              let body=try? JSONSerialization.data(withJSONObject:payload) else{return nil}
        let task=Process()
        task.executableURL=URL(fileURLWithPath:"/opt/homebrew/bin/python3.12")
        task.arguments=[helper.path,action]
        task.currentDirectoryURL=project
        let input=Pipe(),output=Pipe()
        task.standardInput=input
        task.standardOutput=output
        task.standardError=Pipe()
        do {
            try task.run()
            input.fileHandleForWriting.write(body)
            input.fileHandleForWriting.closeFile()
            let data=output.fileHandleForReading.readDataToEndOfFile()
            task.waitUntilExit()
            guard task.terminationStatus==0,data.count<=8192 else{return nil}
            return try JSONDecoder().decode(R675ComputerReply.self,from:data)
        }catch{return nil}
    }
    func refresh(){
        guard !busy else{return}
        busy=true
        Task {
            let fresh=await Task.detached(priority:.utility) {
                Self.send("status")
            }.value
            busy=false
            if let fresh,fresh.ok {
                pending=fresh.pending
                reconcileWindow()
            } else {
                // A transient status transport failure must not erase
                // an already visible request and imply cancellation.
                notice="当前无法核实授权状态；不会自动作出选择。"
            }
        }
    }
    func choose(_ choice:String){
        guard !busy,let q=pending,q.options.contains(choice) else{return}
        busy=true
        notice="正在把你的选择交给原生 DSH，等待实际任务回执。"
        let data=["task_id":q.task_id,"request_id":q.request_id,
                  "question_id":q.question_id,"choice":choice]
        Task {
            let answer=await Task.detached(priority:.userInitiated) {
                Self.send("decide",payload:data)
            }.value
            busy=false
            notice=answer?.ok==true && answer?.submitted==true
                ? "已提交本次人工选择；仍需等待原生工具确认结果。"
                : "原生问题已结束或未收到确认，没有自动批准。"
            pending=nil
            reconcileWindow()
            refresh()
        }
    }
}
private struct R675ComputerQuestionPanel:View {
    @ObservedObject var model:R675ComputerQuestionModel
    var body:some View {
        if let q=model.pending {
            VStack(alignment:.leading,spacing:10) {
                Label(q.header.isEmpty ? "Mac 电脑操作需要本人授权" : q.header,
                      systemImage:"hand.raised")
                    .font(.headline)
                Text(q.question).font(.body).textSelection(.enabled)
                if !q.detail.isEmpty {
                    Text(q.detail).font(.callout).textSelection(.enabled)
                        .foregroundStyle(.secondary)
                }
                HStack(spacing:9) {
                    ForEach(q.options,id:\.self){label in
                        Button(label){model.choose(label)}
                            .buttonStyle(.borderedProminent)
                            .disabled(model.busy)
                    }
                }
                Text("以上是当前原生 DSH 提供的真实授权选项。启用通用电脑操作开关后，新的常规应用访问请求无需逐次确认；系统权限和其他敏感操作审批仍独立。")
                    .font(.caption).foregroundStyle(.secondary)
                if !model.notice.isEmpty {Text(model.notice).font(.caption)}
            }
            .padding(16)
            .background(Color(nsColor:.controlBackgroundColor),
                        in:RoundedRectangle(cornerRadius:13))
            .accessibilityIdentifier("r675-native-cua-real-approval")
        }
    }
}

private struct R676ComputerConsentReply:Decodable {
    let ok:Bool
    let enabled:Bool?
}
@MainActor
private struct R676ComputerPreconsentSettings:View {
    @State private var enabled=false
    @State private var checked=false
    @State private var busy=false
    @State private var requested:Bool?=nil
    @State private var confirm=false
    @State private var notice="当前未读取到已验证的本机授权"
    private nonisolated static func call(_ action:String)->R676ComputerConsentReply? {
        let root=CompanionProjectPaths.rootURL
        let script=root.appendingPathComponent("scripts/r676_computer_preconsent.py")
        guard ["status","allow","revoke"].contains(action),
              FileManager.default.fileExists(atPath:script.path) else {return nil}
        let p=Process()
        p.executableURL=URL(fileURLWithPath:CompanionProjectPaths.python)
        p.currentDirectoryURL=root
        var args=[script.path,action]
        if action != "status" {
            args += ["--confirm",action=="allow"
                ? "CONFIRM_ALL_MAC_APPS_PRECONSENT"
                : "REVOKE_ALL_MAC_APPS_PRECONSENT"]
        }
        p.arguments=args
        let out=Pipe()
        p.standardOutput=out
        p.standardError=Pipe()
        do {
            try p.run()
            let bytes=out.fileHandleForReading.readDataToEndOfFile()
            p.waitUntilExit()
            guard p.terminationStatus==0,bytes.count<=4096 else {return nil}
            return try JSONDecoder().decode(R676ComputerConsentReply.self,from:bytes)
        }catch{return nil}
    }
    private func execute(_ action:String){
        guard !busy else{return}
        busy=true
        Task {
            let result=await Task.detached(priority:.utility) {
                Self.call(action)
            }.value
            busy=false
            if let result,result.ok,let actual=result.enabled {
                enabled=actual
                checked=true
                notice=actual
                  ? "已保存通用授权：未来的原生 CUA 应用访问请求可直接执行。"
                  : "通用授权已关闭；新的应用访问请求恢复单次确认。"
            } else {
                notice="本机未能确认授权变更，原授权状态保持不变。"
            }
        }
    }
    private func openPrivacy(_ page:String){
        guard let url=URL(string:
            "x-apple.systempreferences:com.apple.preference.security?"+page)
        else{return}
        NSWorkspace.shared.open(url)
    }
    var body:some View {
        VStack(alignment:.leading,spacing:10) {
            Toggle(isOn:Binding(
                get:{enabled},
                set:{newValue in requested=newValue;confirm=true}
            )) {
                Text("允许大肥鱼操作 Mac")
                    .font(.body.weight(.medium))
            }
            .disabled(!checked || busy)
            Text("单个总开关，适用于通过原生 CUA 访问的 Mac 应用：读取窗口、截图和常规界面操作。默认关闭。")
                .font(.caption).foregroundStyle(.secondary)
            Text("macOS 的辅助功能、屏幕录制由系统单独管理；其他受控或敏感任务仍保留独立审批。关闭本开关对以后新发起的应用访问生效，不能撤销已经执行的操作。")
                .font(.caption).foregroundStyle(.secondary)
            HStack(spacing:10) {
                Button("辅助功能权限") {openPrivacy("Privacy_Accessibility")}
                    .buttonStyle(.bordered)
                Button("屏幕录制权限") {openPrivacy("Privacy_ScreenCapture")}
                    .buttonStyle(.bordered)
                Button("刷新授权状态") {execute("status")}
                    .buttonStyle(.bordered)
            }
            Text(notice).font(.caption).foregroundStyle(.secondary)
        }
        .alert(requested == true ? "允许操作所有 Mac 应用？"
                                : "关闭通用电脑操作授权？",
               isPresented:$confirm) {
            Button("确认"){execute(requested == true ? "allow" : "revoke")}
            Button("取消",role:.cancel){requested=nil}
        } message: {
            Text(requested == true
                ? "这会让大肥鱼在以后电脑任务中免除逐个应用的 CUA 访问确认，但不会突破 macOS 系统权限或其他敏感操作审批。"
                : "关闭后，新的电脑应用访问请求将恢复人工确认。")
        }
        .task {if !checked {execute("status")}}
    }
}
