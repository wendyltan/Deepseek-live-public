// SPDX-License-Identifier: MIT
// R310: Hidden-by-default, owner-reviewed Markdown persona editor.
// Always reads the actual official DSH source; never edits credentials,
// invokes a model, or claims an already-bound Agent hot-reloaded its prompt.
import AppKit
import Foundation
import SwiftUI

private struct PersonaDSHState: Decodable {
    let configured: Bool
    let reads_on_new_agent: Bool
    let layered_runtime: Bool
    let voice_full_persona: Bool
    let plugin_version: String
    let active_session_verified: Bool
    let persona_hot_reload_ready: Bool?
    let voice_persona_short_ready: Bool?
}
private struct PersonaGrowthState: Decodable {
    let status: String
    let version: Int?
    let approved: Int?
    let pending: Int?
}
private struct PersonaEditorReceipt: Decodable {
    let ok: Bool
    let action: String
    let source: String
    let text: String
    let core: String
    let style: String
    let core_preview: String
    let style_preview: String
    let sha256: String
    let bytes: Int
    let growth: PersonaGrowthState
    let dsh: PersonaDSHState
    let saved: Bool?
    let unchanged: Bool?
    let backup_created: Bool?
}

@MainActor
final class PersonaOverviewModel: ObservableObject {
    @Published private(set) var loaded = false
    @Published private(set) var text = ""
    @Published private(set) var sha256 = ""
    @Published private(set) var bytes = 0
    @Published private(set) var core = ""
    @Published private(set) var style = ""
    @Published private(set) var corePreview = "正在读取大肥鱼的人设"
    @Published private(set) var stylePreview = "请稍后查看"
    @Published private(set) var growthVersion = "未取得"
    @Published private(set) var approvedCount = 0
    @Published private(set) var pendingCount = 0
    @Published private(set) var dshStatus = "正在读取人设使用状态"
    @Published private(set) var voiceStatus = ""
    @Published private(set) var notice = ""
    @Published private(set) var saving = false

    private static var root:URL {CompanionProjectPaths.rootURL}
    private static let script = root.appendingPathComponent("scripts/companion_cli.py")

    private func request(_ action:String, draft:String? = nil,
                         expectedSHA:String? = nil)->PersonaEditorReceipt? {
        guard ["status","save"].contains(action),
              FileManager.default.fileExists(atPath:Self.script.path),
              FileManager.default.isExecutableFile(atPath:CompanionProjectPaths.python) else {
            notice="正式人设编辑程序暂不可用，未修改任何文件。"
            return nil
        }
        let task=Process(), input=Pipe(), output=Pipe()
        task.executableURL=URL(fileURLWithPath:CompanionProjectPaths.python)
        task.arguments=[Self.script.path,"persona",CompanionProjectPaths.node,action]
        task.currentDirectoryURL=Self.root
        task.standardInput=input
        task.standardOutput=output
        task.standardError=Pipe()
        let payload:[String:Any]
        if action=="save",let draft,let expectedSHA {
            payload=["text":draft,"expected_sha256":expectedSHA,
                     "confirmation":"确认保存这版人设"]
        } else {
            payload=[:]
        }
        guard let data=try? JSONSerialization.data(withJSONObject:payload),
              data.count<=11_000 else {
            notice="人设文本超过允许大小，未保存。"
            return nil
        }
        do {
            try task.run()
            input.fileHandleForWriting.write(data)
            input.fileHandleForWriting.closeFile()
            task.waitUntilExit()
            let raw=output.fileHandleForReading.readDataToEndOfFile()
            let prefix="R310_PERSONA_RESULT "
            guard task.terminationStatus==0,raw.count<=25_000,
                  let line=String(data:raw,encoding:.utf8),
                  line.hasPrefix(prefix),
                  let result=try? JSONDecoder().decode(PersonaEditorReceipt.self,
                     from:Data(line.dropFirst(prefix.count).utf8)),
                  result.ok && result.action==action,
                  result.sha256.range(of:#"^[a-f0-9]{64}$"#,
                                     options:.regularExpression) != nil,
                  result.bytes>0 && result.bytes<=8192 else {
                notice="没有保存成功。文件可能已在其他地方修改，请关闭后重新打开再试；原有内容未被覆盖。"
                return nil
            }
            return result
        } catch {
            notice="启动人设编辑程序失败。请检查外置磁盘权限。"
            return nil
        }
    }
    private func accept(_ result:PersonaEditorReceipt) {
        loaded=true
        text=result.text
        sha256=result.sha256
        bytes=result.bytes
        core=result.core
        style=result.style
        corePreview=result.core_preview
        stylePreview=result.style_preview
        if result.growth.status=="available" {
            growthVersion="v\(result.growth.version ?? 0)"
            approvedCount=result.growth.approved ?? 0
            pendingCount=result.growth.pending ?? 0
        } else {
            growthVersion="未取得"
            approvedCount=0
            pendingCount=0
        }
        if result.dsh.configured &&
           result.dsh.persona_hot_reload_ready == true {
            dshStatus="普通对话：已开启动态读取人设"
        } else if result.dsh.configured && result.dsh.reads_on_new_agent {
            dshStatus="普通对话：新会话可读取人设"
        } else {
            dshStatus="暂未确认人设已接入 DSH"
        }
        voiceStatus=result.dsh.voice_persona_short_ready == true ?
            "语音回答：使用同一人设的精简版本" :
            "语音回答：尚未确认使用人设更新"
    }
    func refresh() {
        guard !saving else{return}
        if let result=request("status") {
            accept(result)
            notice=""
        }
    }
    @discardableResult
    func save(_ draft:String, basedOn expectedSHA:String)->Bool {
        guard !saving else{return false}
        saving=true
        defer{saving=false}
        guard let result=request("save",draft:draft,expectedSHA:expectedSHA) else{
            return false
        }
        guard result.saved == true || result.unchanged == true else {
            notice="未收到可验证的保存状态。"
            return false
        }
        accept(result)
        notice=result.saved == true ?
          "已保存，新旧版本均有记录。DSH 后续组装回答时会读取新内容，真实对话效果仍需确认。" :
          "内容没有变化，原人设保持不变。"
        return true
    }
}

// An editorial reading layout for the original V1's seven plain-text paragraphs.
// These headings are display-only; not added to the DSH source file.
enum PersonaReadingLayout {
    // Legacy V1 headings are associated with semantic anchors, not row index.
    // Reordering / adding a paragraph cannot mislabel an unrelated section.
    private static let anchors:[(String,String)] = [
        ("你叫 DeepSeek", "大肥鱼是谁"),
        ("你的底色是", "性格与反应"),
        ("你特别爱吃", "喜欢的事"),
        ("和用户闲聊时", "日常聊天"),
        ("当用户真的需要帮助", "认真做事"),
        ("语音回答要适合", "语音表达"),
        ("已获得用户允许", "记忆与界限")
    ]
    static func preview(_ text:String)->String {
        let paragraphs=text.components(separatedBy:"\n")
            .map{$0.trimmingCharacters(in:.whitespacesAndNewlines)}
            .filter{!$0.isEmpty}
        // Real owner-written Markdown always takes precedence.
        guard paragraphs.count>=5,
              !paragraphs.contains(where:{$0.hasPrefix("#") ||
                                           $0.hasPrefix("- ") ||
                                           $0.hasPrefix(">") ||
                                           $0.hasPrefix("* ")}) else{return text}
        var used=Set<String>()
        return paragraphs.map { paragraph in
            guard let item=anchors.first(where:{paragraph.hasPrefix($0.0)}),
                  used.insert(item.1).inserted else{return paragraph}
            return "## \(item.1)\n\n\(paragraph)"
        }.joined(separator:"\n\n")
    }
}

struct PersonaSummaryCard: View {
    @ObservedObject var model:PersonaOverviewModel
    let openEditor:()->Void
    var body:some View {
        VStack(alignment:.leading,spacing:12) {
            HStack(spacing:8) {
                Label("大肥鱼的人设",systemImage:"person.text.rectangle")
                    .font(.system(size:16,weight:.semibold))
                Spacer()
                Button("查看与编辑",systemImage:"square.and.pencil"){
                    openEditor()
                }
                .buttonStyle(.bordered)
                .accessibilityIdentifier("r310-persona-editor-open")
            }
            Text(model.corePreview)
                .font(.system(size:13))
                .lineSpacing(3)
                .lineLimit(3)
                .frame(maxWidth:.infinity,alignment:.leading)
            Text("身份、性格、聊天习惯及表达方式")
                .font(.system(size:12))
                .foregroundStyle(.secondary)
            Divider()
            Label(model.dshStatus,systemImage:"checkmark.circle")
                .font(.system(size:12))
                .foregroundStyle(.secondary)
                .lineLimit(2)
        }
        .padding(18)
        .background(Color.primary.opacity(0.035),
                    in:RoundedRectangle(cornerRadius:14))
        .onAppear{model.refresh()}
    }
}

struct PersonaEditorSheet:View {
    @ObservedObject var model:PersonaOverviewModel
    @Binding var isPresented:Bool
    @State private var draft=""
    @State private var revision=""
    @State private var selectedView="预览"
    @State private var confirmationVisible=false
    @State private var discardVisible=false
    @State private var localNotice=""
    @State private var showFileDetails=false

    private var changed:Bool {draft != model.text}
    private var sizeBytes:Int {draft.lengthOfBytes(using:.utf8)}
    private var validDraft:Bool {
        sizeBytes<=8192 &&
        draft.trimmingCharacters(in:.whitespacesAndNewlines).count>=30
    }
    var body:some View {
        VStack(alignment:.leading,spacing:0) {
            HStack(alignment:.center,spacing:12) {
                VStack(alignment:.leading,spacing:5) {
                    Label("大肥鱼的人设",systemImage:"text.book.closed")
                        .font(.system(size:21,weight:.semibold))
                    Text("先阅读，想调整时切换到编辑。保存前会再次确认。")
                        .font(.system(size:13))
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Button("关闭"){
                    if changed {discardVisible=true}
                    else {isPresented=false}
                }
                .buttonStyle(.bordered)
            }
            .padding(.horizontal,24).padding(.vertical,20)
            Divider()
            HStack(spacing:14) {
                Picker("查看方式",selection:$selectedView) {
                    Text("预览").tag("预览")
                    Text("编辑").tag("编辑")
                }
                .pickerStyle(.segmented)
                .frame(width:190)
                Spacer()
                Text(changed ? "有未保存的修改" : "当前已保存版本")
                    .font(.system(size:12,weight:changed ? .semibold : .regular))
                    .foregroundStyle(changed ? Color.accentColor : Color.secondary)
            }
            .padding(.horizontal,24).padding(.vertical,14)
            Group {
                if selectedView=="编辑" {
                    VStack(alignment:.leading,spacing:10) {
                        HStack {
                            Text("编辑人设正文")
                                .font(.system(size:14,weight:.semibold))
                            Spacer()
                            Text("支持 Markdown 语法")
                                .font(.system(size:12))
                                .foregroundStyle(.secondary)
                        }
                        TextEditor(text:$draft)
                            .font(.system(size:14,design:.monospaced))
                            .lineSpacing(5)
                            .padding(12)
                            .background(Color(nsColor:.textBackgroundColor),
                                        in:RoundedRectangle(cornerRadius:10))
                            .accessibilityIdentifier("r310-persona-markdown-texteditor")
                            .onChange(of:draft){_,_ in confirmationVisible=false}
                        HStack(spacing:10) {
                            Text("写标题用 ##、列表用 -、强调用 **文字**；切回预览查看效果。")
                                .font(.system(size:12))
                                .foregroundStyle(.secondary)
                            Spacer(minLength:4)
                            if sizeBytes>7000 {
                                Text(sizeBytes>8192 ?
                                    "内容过长，请精简后保存" :
                                    "内容接近保存上限")
                                    .font(.system(size:12))
                                    .foregroundStyle(sizeBytes>8192 ? Color.red : Color.secondary)
                            }
                        }
                    }
                    .padding(18)
                } else {
                    ScrollView {
                        VStack(alignment:.leading,spacing:14) {
                            HStack {
                                Text("阅读预览")
                                    .font(.system(size:14,weight:.semibold))
                                Spacer()
                                Text("原V1阅读标题按内容识别，不修改正式人设")
                                    .font(.system(size:12))
                                    .foregroundStyle(.secondary)
                            }
                            ReadableMarkdownView(source:PersonaReadingLayout.preview(draft))
                                .frame(maxWidth:.infinity,alignment:.leading)
                        }
                        .padding(20)
                        .frame(maxWidth:.infinity,alignment:.leading)
                    }
                    .background(Color(nsColor:.textBackgroundColor),
                                in:RoundedRectangle(cornerRadius:10))
                    .padding(18)
                }
            }
            .frame(maxWidth:.infinity,maxHeight:.infinity)
            Divider()
            DisclosureGroup("保存格式和使用方式",isExpanded:$showFileDetails) {
                VStack(alignment:.leading,spacing:8) {
                    Text("预览会渲染 Markdown 标题、列表、加粗；编辑时可直接输入这些格式符号。")
                    Text("真实保存文件仍是 app/companion_persona.txt（支持 Markdown 文字语法）。DSH 目前读取这个路径，保存不会转成 .md 文件。")
                    Text(model.dshStatus)
                    Text(model.voiceStatus)
                    Text("人格成长审核：\(model.growthVersion)，已批准 \(model.approvedCount) 条、待审 \(model.pendingCount) 条。个人事实记忆在「我的记忆」单独管理。")
                    Text("保存后，下一次系统提示词组装会读取更新；已有会话的实际回答效果仍须真人验证。")
                }
                .font(.system(size:12))
                .foregroundStyle(.secondary)
                .padding(.top,10)
            }
            .font(.system(size:13))
            .padding(.horizontal,24).padding(.vertical,12)
            if !localNotice.isEmpty || !model.notice.isEmpty {
                Label(localNotice.isEmpty ? model.notice : localNotice,
                      systemImage:"info.circle")
                    .font(.system(size:12))
                    .foregroundStyle(.secondary)
                    .padding(.horizontal,24)
                    .padding(.vertical,7)
            }
            if confirmationVisible {
                HStack(alignment:.center,spacing:12) {
                    VStack(alignment:.leading,spacing:4) {
                        Text("确认修改大肥鱼的人设？")
                            .font(.system(size:14,weight:.semibold))
                        Text("保存后新版本可用于后续回答，当前版本会自动备份。")
                            .font(.system(size:12))
                            .foregroundStyle(.secondary)
                    }
                    Spacer(minLength:8)
                    Button("返回编辑"){confirmationVisible=false}
                        .buttonStyle(.bordered)
                    Button("确认保存这版人设"){
                        if model.save(draft,basedOn:revision) {
                            draft=model.text
                            revision=model.sha256
                            confirmationVisible=false
                            localNotice=model.notice
                            selectedView="预览"
                        } else {
                            localNotice=model.notice
                            confirmationVisible=false
                        }
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(!validDraft)
                }
                .padding(14)
                .background(Color.accentColor.opacity(0.07),
                            in:RoundedRectangle(cornerRadius:11))
                .padding(.horizontal,24)
                .padding(.bottom,12)
            }
            if discardVisible {
                HStack(spacing:12) {
                    Text("修改尚未保存，确定放弃并关闭？")
                        .font(.system(size:13))
                    Spacer()
                    Button("继续编辑"){discardVisible=false}
                    Button("不保存并关闭",role:.destructive){isPresented=false}
                }
                .padding(.horizontal,24)
                .padding(.bottom,12)
            }
            Divider()
            HStack {
                Text(changed ? "只有确认保存才会更改正式人设" :
                     "人设保存在这台 Mac 上")
                    .font(.system(size:12))
                    .foregroundStyle(.secondary)
                Spacer()
                Button("保存修改",systemImage:"checkmark"){
                    confirmationVisible=true
                    selectedView="编辑"
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .disabled(!changed || !validDraft || model.saving)
                .accessibilityIdentifier("r310-persona-confirm-save")
            }
            .padding(.horizontal,24).padding(.vertical,16)
        }
        .frame(minWidth:780,idealWidth:900,minHeight:650,idealHeight:790)
        .onAppear {
            model.refresh()
            draft=model.text
            revision=model.sha256
        }
    }
}
