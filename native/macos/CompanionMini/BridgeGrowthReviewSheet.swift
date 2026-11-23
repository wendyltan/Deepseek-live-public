import Foundation
import SwiftUI

// R235 review-only Mac interface. Human buttons are the only mutation path.
// An independent, pre-configured and mode-0600 admin credential is required;
// no private tokens appear in UI state, process arguments or logs.
// Existing E1b local memory is separate from the new DSH growth queue.
private struct WhaleGrowthCandidate: Identifiable {
    let id: String
    let text: String
    let status: String
    let source: String
}
@MainActor
private final class WhaleGrowthReviewModel: ObservableObject {
    @Published var configured = false
    @Published var revision = 0
    @Published var version = 0
    @Published var activeCount = 0
    @Published var suggestionsEnabled = false
    @Published var candidates: [WhaleGrowthCandidate] = []
    @Published var busy = false
    @Published var notice = "人格成长审核尚未连接；不会自动学习或修改原记忆。"
    private nonisolated static func send(_ action: String,
                                         payload: [String:Any] = [:]) -> [String:Any]? {
        let sourceRoot = CompanionProjectPaths.rootURL.path
        let script = URL(fileURLWithPath: sourceRoot)
            .appendingPathComponent("scripts/r235_native_growth_review.mjs")
        guard FileManager.default.fileExists(atPath: script.path),
              let inputData = try? JSONSerialization.data(withJSONObject: [
                  "action": action, "payload": payload]) else {return nil}
        let task = Process()
        task.executableURL = URL(fileURLWithPath: "/opt/homebrew/bin/node")
        task.arguments = [script.path]
        task.currentDirectoryURL = URL(fileURLWithPath: sourceRoot)
        let input = Pipe()
        let output = Pipe()
        task.standardInput = input
        task.standardOutput = output
        task.standardError = Pipe()
        do {
            try task.run()
            input.fileHandleForWriting.write(inputData)
            input.fileHandleForWriting.closeFile()
            task.waitUntilExit()
            let data = output.fileHandleForReading.readDataToEndOfFile()
            guard data.count <= 65536,
                  let value = String(data:data,encoding:.utf8),
                  value.hasPrefix("GROWTH_REVIEW_RESULT "),
                  let answer = try? JSONSerialization.jsonObject(
                    with:Data(value.dropFirst("GROWTH_REVIEW_RESULT ".count).utf8))
                    as? [String:Any] else {return nil}
            return answer
        } catch {return nil}
    }
    func perform(_ action:String, payload:[String:Any]=[:]) {
        guard !busy else{return}
        busy = true
        notice = "正在确认本机 Bridge 的真实回执…"
        let service = self
        DispatchQueue.global(qos:.userInitiated).async {
            // Bridge secrets never move to this view: only the native helper
            // may read separately privileged files on the current Mac.
            // Using a dedicated background queue avoids freezing the UI.
            let answer = WhaleGrowthReviewModel.send(action,payload:payload)
            DispatchQueue.main.async {
                service.busy = false
                guard let answer else {
                    service.configured = false
                    service.notice = "审核服务未就绪；未作修改。"
                    return
                }
                service.configured = answer["configured"] as? Bool == true
                if !service.configured {
                    service.notice = "正式 Bridge 的独立管理员凭据尚未配置；成长审核保持关闭。"
                    return
                }
                if answer["ok"] as? Bool != true {
                    let reason=String(describing:answer["error"] ?? "unknown")
                    switch reason {
                    case "memory_not_enabled", "growth_disabled":
                        service.notice = "正式 Bridge 尚未加载人格成长功能，请核验插件版本与配置。"
                    case "memory_user_consent_required":
                        service.notice = "请先授权本机逐条审核，才可开启主动建议。"
                    case "growth_revision_conflict":
                        service.notice = "审核列表已变化，请刷新后再确认。"
                    default:
                        service.notice = "Bridge 暂未完成操作（\(reason)），请检查设备诊断。"
                    }
                    return
                }
                if action == "status" {
                    service.version = answer["version"] as? Int ?? service.version
                    service.revision = answer["revision"] as? Int ?? service.revision
                    service.activeCount = answer["active_count"] as? Int ?? service.activeCount
                    service.suggestionsEnabled = answer["suggestions_enabled"] as? Bool == true
                    service.notice = "仅已审核事实会生效；本窗口不会自行提炼对话。"
                } else if action == "list" {
                    let rows = answer["candidates"] as? [[String:Any]] ?? []
                    service.candidates = rows.compactMap { x in
                        guard let id=x["id"] as? String,
                              let value=x["text"] as? String,
                              let status=x["status"] as? String,
                              id.count==36, value.count<=512 else{return nil}
                        return WhaleGrowthCandidate(id:id,text:value,status:status,
                            source:x["source"] as? String ?? "user_explicit")
                    }
                } else {
                    service.notice = "Bridge 已确认操作；重新读取审核清单。"
                }
                if action == "status" {
                    service.perform("list")
                } else if action != "list" {
                    service.perform("status")
                }
            }
        }
    }
    func refresh(){
        perform("status")
    }
}
struct BridgeGrowthReviewSheet: View {
    @Binding var isPresented: Bool
    var embedded: Bool = false
    @StateObject private var model = WhaleGrowthReviewModel()
    @State private var proposedText = ""
    @State private var confirmConsent = false
    @State private var pendingSuggestions = false
    @State private var confirmProposal = false
    @State private var pendingDecision: (id:String,decision:String)?
    @State private var pendingRollback = false
    @State private var rollbackVersion = "0"
    var body: some View {
        VStack(alignment:.leading, spacing:14) {
            HStack {
                Label("人格成长",systemImage:"person.text.rectangle")
                    .font(.title3.weight(.semibold))
                Spacer()
                if !embedded {
                    Button("关闭"){isPresented=false}
                }
            }
            VStack(alignment:.leading,spacing:8) {
                Text("这里决定大肥鱼以后怎么说话、怎么互动。例如：回答更简洁、少用技术术语。")
                    .font(.callout)
                Text("你说过的长期交流偏好 → 大肥鱼提出建议 → 你逐条批准 → 新版本生效。")
                    .font(.callout).foregroundStyle(.secondary)
                Text("姓名、喜好、生活经历等个人事实，请用旁边的「已记住／添加记忆」。两类内容分开审核。")
                    .font(.caption).foregroundStyle(.secondary)
            }
            .frame(maxWidth:.infinity,alignment:.leading)
            .padding(14)
            .background(Color(nsColor:.controlBackgroundColor),
                        in:RoundedRectangle(cornerRadius:13))
            if model.configured {
                HStack {
                    Text("人格成长版本：\(model.version)")
                    Text("已批准：\(model.activeCount) 条")
                    Spacer()
                    Button("刷新"){model.refresh()}
                        .disabled(model.busy)
                }
                .font(.subheadline)
                HStack {
                    Text(model.suggestionsEnabled ? "主动建议：开启" : "主动建议：关闭")
                        .font(.subheadline)
                    Spacer()
                    Button(model.suggestionsEnabled ? "关闭主动建议" : "允许主动提出建议") {
                        pendingSuggestions = true
                    }.disabled(model.busy)
                }
                Text("开启后仅从已完成的可信对话里提议交流方式变化；不会自动生效，也不会额外调用模型。")
                    .font(.caption).foregroundStyle(.secondary)
                Divider()
                Text("候选审核").font(.headline)
                if model.candidates.isEmpty {
                    Text("当前暂无待审核候选。")
                        .foregroundStyle(.secondary)
                }
                VStack(alignment:.leading,spacing:10) {
                        ForEach(model.candidates) { item in
                            VStack(alignment:.leading,spacing:8) {
                                HStack {
                                    Text(item.source == "assistant_suggested" ?
                                         "来自对话的建议" : "手动添加")
                                        .font(.caption).foregroundStyle(.secondary)
                                    Spacer()
                                }
                                Text(item.text).textSelection(.enabled)
                                HStack {
                                    Text("待审核").font(.caption).foregroundStyle(.secondary)
                                    Spacer()
                                    Button("拒绝"){pendingDecision=(item.id,"reject")}
                                    Button("批准"){pendingDecision=(item.id,"accept")}
                                }
                            }
                            .padding(10).background(.quaternary.opacity(0.4),
                                                    in:RoundedRectangle(cornerRadius:10))
                        }
                }
                TextField("手动提出一种希望大肥鱼改变的交流方式",text:$proposedText)
                    .textFieldStyle(.roundedBorder)
                Button("提交候选，等待人工审核"){confirmProposal=true}
                    .disabled(model.busy || proposedText.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty)
                HStack {
                    TextField("回滚至版本",text:$rollbackVersion)
                        .frame(width:100).textFieldStyle(.roundedBorder)
                    Button("查看并确认回滚"){pendingRollback=true}
                        .disabled(model.busy)
                }
                Button("授权我逐条批准后保存人格成长"){confirmConsent=true}
                    .disabled(model.busy)
            } else {
                ContentUnavailableView("尚未启用 Bridge 人格成长",
                    systemImage:"lock.shield",
                    description:Text("独立管理密钥和正式成长开关未配置。这里不自动启用、创建凭据或从聊天提取记忆。"))
                Button("重新检查"){model.refresh()}
                    .disabled(model.busy)
            }
            Text(model.notice).font(.footnote).foregroundStyle(.secondary)
        }
        .padding(embedded ? 0 : 20)
        .frame(minWidth:embedded ? nil : 640,minHeight:embedded ? nil : 560)
        .onAppear {model.refresh()}
        .confirmationDialog("允许从日常对话中主动提出成长候选吗？",
             isPresented:$pendingSuggestions) {
            Button(model.suggestionsEnabled ? "确认关闭" : "确认开启") {
                model.perform("suggestions",payload:[
                    "allow": !model.suggestionsEnabled,
                    "expectedRevision": model.revision
                ])
            }
            Button("取消",role:.cancel){}
        } message: {Text("只产生待审核候选，不会自动更新人格。关闭后不再产生新候选，已有候选仍可人工处理。") }
        .confirmationDialog("允许以后逐条手动审核和保存人格成长吗？",
             isPresented:$confirmConsent) {
            Button("确认允许"){model.perform("consent")}
            Button("取消",role:.cancel){}
        } message: {Text("不会开启自动学习；独立管理员授权须先由你配置。")}
        .confirmationDialog("要保存这条待审核候选吗？",
             isPresented:$confirmProposal) {
            Button("提交候选"){
                model.perform("propose",payload:["text":proposedText])
                proposedText=""
            }
            Button("取消",role:.cancel){}
        }
        .confirmationDialog("将这条候选的审核决定提交给 Bridge？",
             isPresented:Binding(get:{pendingDecision != nil},
                                 set:{if !$0 {pendingDecision=nil}})) {
            Button("提交审核决定"){
                if let item=pendingDecision {
                    model.perform(item.decision,payload:[
                        "id":item.id,"expectedRevision":model.revision])
                }
                pendingDecision=nil
            }
            Button("取消",role:.cancel){pendingDecision=nil}
        }
        .confirmationDialog("确认回滚已审核人格版本？",
             isPresented:$pendingRollback) {
            Button("执行回滚",role:.destructive){
                if let v=Int(rollbackVersion),v>=0 {
                    model.perform("rollback",payload:[
                        "toVersion":v,"expectedRevision":model.revision])
                }
            }
            Button("取消",role:.cancel){}
        } message: {
            Text("只回滚当前可用人格事实，不能清除已写入的旧 DSH 会话历史或备份。")
        }
    }
}
