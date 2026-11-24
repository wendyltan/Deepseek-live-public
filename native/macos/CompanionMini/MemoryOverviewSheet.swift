// SPDX-License-Identifier: MIT
// Local owner-approved memory management sheet & E1b review queue for CompanionMini.
import AppKit
import SwiftUI

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
        let script=root.appendingPathComponent("scripts/companion_cli.py")
        guard FileManager.default.fileExists(atPath:script.path) else {
            return Data("R308_DIAGNOSTIC_DISK_UNAVAILABLE".utf8)
        }
        let task=Process(),input=Pipe(),output=Pipe(),errors=Pipe()
        task.executableURL=URL(fileURLWithPath:CompanionProjectPaths.python)
        task.arguments=[script.path,"memory",CompanionProjectPaths.node,"status"]
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
        let script=root.appendingPathComponent("scripts/companion_cli.py")
        guard FileManager.default.fileExists(atPath:script.path),
              let data=try? JSONSerialization.data(withJSONObject:[
                "id":id,"revision":revision,"confirm":"确认删除这一条记忆"]) else {
            return "记忆管理程序不可用"
        }
        let task=Process(),input=Pipe(),output=Pipe()
        task.executableURL=URL(fileURLWithPath:CompanionProjectPaths.python)
        task.arguments=[script.path,"memory",CompanionProjectPaths.node,"remove"]
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
        let script=root.appendingPathComponent("scripts/companion_cli.py")
        guard FileManager.default.fileExists(atPath:script.path) else {
            return "审核管理程序不可用"
        }
        let task=Process(), output=Pipe()
        task.executableURL=URL(fileURLWithPath:CompanionProjectPaths.python)
        task.arguments=[script.path,"voice-review","discard",id]
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
        let executable = URL(fileURLWithPath: CompanionProjectPaths.python)
        let nodeExecutable = CompanionProjectPaths.node
        let project = CompanionProjectPaths.rootURL
        let script = project.appendingPathComponent("scripts/companion_cli.py")
        guard FileManager.default.isExecutableFile(atPath: executable.path),
              FileManager.default.isExecutableFile(atPath: nodeExecutable),
              FileManager.default.fileExists(atPath: script.path) else {
            return "记忆管理程序不可用"
        }
        let task = Process()
        task.executableURL = executable
        task.arguments = [script.path,"memory-action",nodeExecutable,action]
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
                CompanionProjectPaths.script("companion_cli.py"))),
              FileManager.default.fileExists(atPath:script.path) else {
            return "记忆条目无效"
        }
        let task=Process()
        task.executableURL=URL(fileURLWithPath:CompanionProjectPaths.python)
        task.arguments=[script.path,"memory-admin","remove",id]
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
