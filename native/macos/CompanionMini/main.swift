// SPDX-License-Identifier: MIT
// Native macOS ESP32 companion: read-only model state + explicitly user-approved settings / E1b changes. No WebView, Mac mic, or paid calls.
import AppKit
import SwiftUI

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
