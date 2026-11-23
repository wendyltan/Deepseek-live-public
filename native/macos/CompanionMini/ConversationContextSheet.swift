// R677 context management for real native DSH sessions.
// No fake token counters, no LLM auto-compaction and no automatic rotation.
// A fresh context is user-triggered; old verified dialogue is archived.
import AppKit
import SwiftUI

struct R677ContextStatus:Decodable {
    let ok:Bool
    let current_session:String?
    let current_session_label:String?
    let current_session_kind:String?
    let previous_new_session_failed:Bool?
    let visible_turns:Int?
    let history_capacity_turns:Int?
    let context_usage_tokens:Int?
    let context_window_tokens:Int?
    let context_usage_percent:Double?
    let context_recorded_at_unix:Double?
    let fresh_context_recommended:Bool?
    let new_session_supported:Bool?
    let past_archives:Int?
    let old_archive:String?
    let old_turns:Int?
    let error:String?
}
private struct R677ArchiveSummary:Decodable,Identifiable {
    let id:String
    let turns:Int
    let archived_at_unix:Double
}
private struct R677ArchiveIndex:Decodable {
    let ok:Bool
    let archives:[R677ArchiveSummary]?
}
private struct R677HistoryRow:Decodable {
    let user:String
    let assistant:String
    let origin:String?
}
private struct R677ArchiveDetail:Decodable {
    let ok:Bool
    let id:String?
    let turns:[R677HistoryRow]?
}
private struct R677RawReply:Decodable {
    let ok:Bool
    let new_session:String?
    let old_archive:String?
    let old_turns:Int?
    let error:String?
}
struct R677ConversationContextSheet:View {
    @Environment(\.dismiss) private var dismiss
    @State private var info:R677ContextStatus?=nil
    @State private var archives:[R677ArchiveSummary]=[]
    @State private var selected:R677ArchiveDetail?=nil
    @State private var busy=false
    @State private var confirmNew=false
    @State private var message=""
    fileprivate nonisolated static func invoke(_ args:[String],limit:Int)->Data? {
        guard args.count>=1 && args.count<=4,
              ["status","archives","archive","new"].contains(args[0]),
              args.allSatisfy({$0.utf8.count<=90}) else {return nil}
        let url=CompanionProjectPaths.rootURL
            .appendingPathComponent("scripts/r677_context_rotation.py")
        guard FileManager.default.fileExists(atPath:url.path) else{return nil}
        let task=Process()
        task.executableURL=URL(fileURLWithPath:CompanionProjectPaths.python)
        task.currentDirectoryURL=CompanionProjectPaths.rootURL
        task.arguments=[url.path]+args
        let output=Pipe()
        task.standardOutput=output
        task.standardError=Pipe()
        do {
            try task.run()
            let data=output.fileHandleForReading.readDataToEndOfFile()
            task.waitUntilExit()
            return data.count<=limit ? data : nil
        } catch {return nil}
    }
    private func refresh(){
        guard !busy else{return}
        busy=true
        Task {
            let result=await Task.detached(priority:.utility){
                let status=Self.invoke(["status"],limit:8192)
                    .flatMap{try? JSONDecoder().decode(R677ContextStatus.self,from:$0)}
                let rows=Self.invoke(["archives"],limit:16384)
                    .flatMap{try? JSONDecoder().decode(R677ArchiveIndex.self,from:$0)}
                return (status,rows)
            }.value
            busy=false
            info=result.0?.ok == true ? result.0 : nil
            archives=result.1?.ok == true ? (result.1?.archives ?? []) : []
            if info == nil {message="当前会话状态无法核实；不执行自动切换。"}
        }
    }
    private func openArchive(_ id:String) {
        guard !busy && id.count==24 && id.allSatisfy({$0.isHexDigit}) else{return}
        busy=true
        Task {
            let archive=await Task.detached(priority:.utility){
                Self.invoke(["archive","--id",id],limit:240000)
                    .flatMap{try? JSONDecoder().decode(R677ArchiveDetail.self,from:$0)}
            }.value
            busy=false
            selected = archive?.ok == true ? archive : nil
            if selected==nil {message="旧会话档案无法通过私有来源验证。"}
        }
    }
    private func startNew(){
        guard !busy else{return}
        busy=true
        message="正在归档旧对话并切换新的 DSH 会话，结果以重新连接的真实回执为准。"
        Task {
            let response=await Task.detached(priority:.utility){
                Self.invoke(["new","--confirm",
                    "NEW_ISOLATED_DSH_CONTEXT_KEEP_ARCHIVE"],limit:8192)
                    .flatMap{try? JSONDecoder().decode(R677RawReply.self,from:$0)}
            }.value
            busy=false
            if let response,response.ok == true {
                message="新会话已生效，旧的 \(response.old_turns ?? 0) 条对话已只读归档。原生长期记忆保留。"
                info=nil
                selected=nil
                R678ContextSummaryModel.shared.refresh()
                refresh()
            }else{
                message="切换未完成：\(response?.error ?? "无法验证所有权")。没有自动创建模型任务；可核对服务和回滚记录。"
            }
        }
    }
    var body:some View {
        VStack(alignment:.leading,spacing:13){
            HStack {
                Text("DSH 上下文管理").font(.title2.weight(.semibold))
                Spacer()
                Button("刷新"){refresh()}.disabled(busy)
                Button("关闭"){dismiss()}.disabled(busy)
            }
            if let info {
                HStack(spacing:14) {
                    Label(info.current_session_label ?? "当前会话",
                          systemImage:"bubble.left.and.text.bubble.right")
                        .font(.headline)
                    Text("\(info.visible_turns ?? 0) 条 · ID \(String((info.current_session ?? "").prefix(8)))")
                        .font(.callout).foregroundStyle(.secondary)
                }
                if let percent=info.context_usage_percent,
                   let used=info.context_usage_tokens,
                   let limit=info.context_window_tokens,limit>0 {
                    HStack {
                        Text("上下文占用").font(.callout.weight(.medium))
                        Spacer()
                        Text(String(format:"%.1f%%",percent))
                            .font(.title3.weight(.semibold)).monospacedDigit()
                    }
                    ProgressView(value: min(1.0,max(0.0,percent/100.0)))
                        .tint(Color.accentColor)
                    Text("DSH 原生上下文压力：\(used.formatted()) / \(limit.formatted()) Tokens（最近一次记录，并非累计计费量）")
                        .font(.caption).foregroundStyle(.secondary)
                }else{
                    Text("新会话尚无 Token 压力记录；第一次完成回复后更新实际占比。")
                        .font(.callout).foregroundStyle(.secondary)
                }
                if info.previous_new_session_failed == true {
                    Text("上一次新建未生效，当前仍在原会话。旧会话已备份，没有清空历史。")
                        .font(.callout.weight(.medium)).foregroundStyle(.orange)
                }
                if info.fresh_context_recommended == true {
                    Label("上下文已达75%，建议归档后开启新会话。",
                          systemImage:"exclamationmark.circle")
                        .font(.callout).foregroundStyle(.orange)
                }
                Text("新建会话使用独立的原生 DSH 上下文；历史对话保留为只读档案，已批准的长期记忆和人物设定不清除。电脑任务或无线网关繁忙时会拒绝切换。")
                    .font(.callout).foregroundStyle(.secondary)
                HStack {
                    Button("新建独立会话") {confirmNew=true}
                        .buttonStyle(.borderedProminent)
                        .disabled(busy || info.new_session_supported != true)
                    if busy {ProgressView().controlSize(.small)}
                }
            }else{
                Text("尚未取得当前 DSH 会话的可靠状态。")
                    .foregroundStyle(.secondary)
            }
            Divider()
            Text("旧会话档案").font(.headline)
            if archives.isEmpty {
                Text("暂无已归档会话；当前历史不会因查看此页而改变。")
                    .font(.callout).foregroundStyle(.secondary)
            } else {
                ScrollView(.horizontal) {
                    HStack(spacing:8) {
                        ForEach(archives){row in
                            Button("\(row.id == info?.current_session ? "当前会话备份" : "旧会话") · \(row.turns) 条 · \(Date(timeIntervalSince1970:row.archived_at_unix).formatted(date:.abbreviated,time:.shortened))"){
                                openArchive(row.id)
                            }
                            .buttonStyle(.bordered).disabled(busy)
                        }
                    }
                }
            }
            if let selected,let rows=selected.turns {
                Text("只读归档 · \(rows.count) 条").font(.headline)
                ScrollView{
                    LazyVStack(alignment:.leading,spacing:10){
                        ForEach(Array(rows.enumerated()),id:\.offset){_,turn in
                            Text("你：\(turn.user)").font(.callout.weight(.medium))
                                .textSelection(.enabled)
                            Text("大肥鱼：\(turn.assistant)").font(.callout)
                                .textSelection(.enabled)
                            Divider()
                        }
                    }
                }
                .frame(minHeight:130,maxHeight:260)
            }
            if !message.isEmpty {
                Text(message).font(.callout).foregroundStyle(.secondary)
                    .textSelection(.enabled)
            }
        }
        .padding(22).frame(minWidth:730,minHeight:390)
        .alert("新建独立 DSH 会话？",isPresented:$confirmNew) {
            Button("保留旧记录并新建"){startNew()}
            Button("取消",role:.cancel){}
        }message:{
            Text("旧对话将归档，不进入新的模型上下文。已批准的长期记忆会保留。需要设备处于 Wi-Fi 空闲状态；会短暂断开并由原监督进程重新连接。不会自动发起付费模型请求。")
        }
        .task{refresh()}
    }
}


// Live shared read-only snapshot for both 近期对话 and DSH 上下文管理.
// Polls only a local owner-private helper, never calls a model or tool task.
@MainActor
final class R678ContextSummaryModel:ObservableObject {
    static let shared=R678ContextSummaryModel()
    @Published private(set) var info:R677ContextStatus?=nil
    private var loading=false
    func refresh(){
        guard !loading else{return}
        loading=true
        Task {
            let result=await Task.detached(priority:.utility){
                R677ConversationContextSheet.invoke(["status"],limit:8192)
                    .flatMap{try? JSONDecoder().decode(R677ContextStatus.self,from:$0)}
            }.value
            loading=false
            if let result,result.ok {info=result}
        }
    }
}
