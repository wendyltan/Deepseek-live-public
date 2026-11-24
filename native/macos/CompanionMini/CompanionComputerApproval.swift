// SPDX-License-Identifier: MIT
import AppKit
import Combine
import SwiftUI

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
        let helper=project.appendingPathComponent("scripts/companion_cli.py")
        guard ["status","decide"].contains(action),
              FileManager.default.fileExists(atPath:helper.path),
              let body=try? JSONSerialization.data(withJSONObject:payload) else{return nil}
        let task=Process()
        task.executableURL=URL(fileURLWithPath:CompanionProjectPaths.python)
        task.arguments=[helper.path,"computer-question",action]
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
struct R675ComputerQuestionPanel:View {
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
struct R676ComputerPreconsentSettings:View {
    @State private var enabled=false
    @State private var checked=false
    @State private var busy=false
    @State private var requested:Bool?=nil
    @State private var confirm=false
    @State private var notice="当前未读取到已验证的本机授权"
    private nonisolated static func call(_ action:String)->R676ComputerConsentReply? {
        let root=CompanionProjectPaths.rootURL
        let script=root.appendingPathComponent("scripts/companion_cli.py")
        guard ["status","allow","revoke"].contains(action),
              FileManager.default.fileExists(atPath:script.path) else {return nil}
        let p=Process()
        p.executableURL=URL(fileURLWithPath:CompanionProjectPaths.python)
        p.currentDirectoryURL=root
        var args=[script.path,"computer-preconsent",action]
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
