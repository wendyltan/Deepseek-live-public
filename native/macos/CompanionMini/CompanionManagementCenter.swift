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
    @State var showContextManager=false
    @State var pendingMemorySuggestions=0
    // Keep a verified task's native progress while the JSON projector
    // temporarily omits current_task_id during polling/recomposition.
    @State var carriedTask:(String,[String])?=nil
    @State private var carriedTaskID:String?=nil
    @StateObject var computerApproval=R675ComputerQuestionModel.shared
    @StateObject var contextSummary=R678ContextSummaryModel.shared
    @State private var lastContextRefresh=Date.distantPast
    @State var replyComparison:R499ReplyComparison?=nil
    // A completed turn keeps its verified spoken script after the receipt
    // changes to the next turn or a transient snapshot read fails.
    @State var spokenByOriginal:[String:String]=[:]
    @State var spokenByID:[String:String]=[:]
    @State var ambiguousOriginals:Set<String>=[]
    @State var spokenSessionID:String?=nil
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
    private var diagnostics:some View {
        CompanionDiagnosticsHubSheet(
            store:store, embedded:true,
            openPixels:{showPixels=true},
            openMotions:{navigation.section = .animations},
            openVoice:{showVoiceGuide=true})
        .frame(maxWidth:.infinity,maxHeight:.infinity,alignment:.topLeading)
    }

}
