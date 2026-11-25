// SPDX-License-Identifier: MIT
import AppKit
import Combine
import SwiftUI

extension CompanionManagementCenter {
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

    var conversations:some View {
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
                    let retainedTask=Self.shouldRetainCarriedTask(snapshot:store.snapshot)
                        ? carriedTask : nil
                    let active=store.activeTaskConversation ?? retainedTask
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

}
