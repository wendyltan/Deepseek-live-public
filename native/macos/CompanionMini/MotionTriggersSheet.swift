// SPDX-License-Identifier: MIT
// R127: audited R121 bindings plus OFFLINE editable next-generation proposal.
// Never calls USB, writes SD/NVS, or represents Mac preferences as firmware.
import AppKit
import SwiftUI
import CryptoKit

private struct MotionTriggerBinding: Decodable, Identifiable {
    let id:String
    let device_package_selected:Bool
    let real_trigger:String
    let trigger_configurable_on_device:Bool
}
private struct MotionTriggerManifest: Decodable {
    let schema:Int
    let origin:String
    let firmware_source_sha256:String
    let live_binding_can_be_edited_on_R121:Bool
    let historical_count:Int
    let auto_triggered_count:Int
    let manual_only_count:Int
    let bindings:[MotionTriggerBinding]
}
private struct MotionTriggerOverride: Encodable {
    let id:String
    let target_trigger:String
}
private struct MotionTriggerProposal: Encodable {
    let schema:Int
    let status:String
    let on_device:Bool
    let preserve_all_original_motions:Bool
    let firmware_source_sha256:String
    let overrides:[MotionTriggerOverride]
}
struct MotionTriggersSheet: View {
    @ObservedObject var store: CompanionStore
    let onClose: () -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var approveInstall = false
    @State private var receiptNotice = ""
    @State private var manifest: MotionTriggerManifest?
    @State private var names=[String:String]()
    @State private var selectedID="m018"
    @State private var pending=[String:String]()
    @State private var notice=""
    @State private var group="全部"
    @State private var showDiscardConfirm=false
    @State private var savedProposalSummary=""
    private let choices=[
        ("inherit","保持目前触发"),
        ("tap","点击互动（提案）"),
        ("idle","空闲轮换（提案）"),
        ("bonus","低频彩蛋（提案）"),
        ("work","任务状态（提案）"),
        ("drag","手指拖拽（提案 · 待板端支持）"),
        ("manual","仅手动展示（提案）")]
    private let display=[
        "boot":"默认待机（开机及动作返回）",
        "tap":"点击：m013–m016循环",
        "idle":"空闲约90秒循环",
        "bonus":"约15分钟低频彩蛋",
        "work":"工作阶段约9秒轮换",
        "drag":"真实手指位移达到阈值的拖拽手势（候选固件）",
        "manual":"未绑定自动触发；可手动预览"]

    private var proposalURL:URL {
        FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(
            "Library/Application Support/Deepseek-live/motion-library/trigger-proposal-r121.json")
    }
    private var applyRequestURL:URL {
        FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(
            "Library/Application Support/Deepseek-live/companion-native/trigger-apply-request.json")
    }
    private var applyResultURL:URL {
        FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(
            "Library/Application Support/Deepseek-live/companion-native/trigger-apply-result.json")
    }
    private func requestPhysicalRuleApplication() {
        save()
        guard store.bothVerified,store.snapshot?.phase=="idle",
              let session=store.snapshot?.session_id, !session.isEmpty,
              pending.count>0, pending.count<=35,
              let bytes=try? Data(contentsOf:proposalURL),bytes.count<15000
        else {receiptNotice="官方会话未就绪，或没有可下发的已保存规则。";return}
        guard !FileManager.default.fileExists(atPath:applyRequestURL.path) else {
            receiptNotice="已有规则安装请求等待处理，请勿重复提交。";return
        }
        let digest=SHA256.hash(data:bytes).map{String(format:"%02x",$0)}.joined()
        let payload:[String:Any]=["schema":1,"action":"apply_saved_rules",
                                   "session_id":session,"at":Date().timeIntervalSince1970,
                                   "proposal_sha256":digest]
        guard let raw=try? JSONSerialization.data(withJSONObject:payload),
              raw.count<=512 else {receiptNotice="安装请求编码失败。";return}
        do {
            try raw.write(to:applyRequestURL,options:.atomic)
            try FileManager.default.setAttributes(
                [.posixPermissions:0o600],ofItemAtPath:applyRequestURL.path)
            receiptNotice="请求已提交，正在等待Mac与实体设备握手。这是Mac窗口状态，只有出现“等待实体点击授权”才可以点鱼。"
        } catch {
            receiptNotice="无法发送给唯一USB语音后台，板端规则未改变。"
        }
    }
    private func refreshApplyReceipt() {
        guard let raw=try? Data(contentsOf:applyResultURL),raw.count<5000,
              let result=try? JSONSerialization.jsonObject(with:raw) as? [String:Any],
              let state=result["status"] as? String else{return}
        switch state {
        case "starting":receiptNotice="正在核验R136实体固件及原始规则…"
        case "waiting_for_local_tap":receiptNotice="等待实体点击授权：请在30秒内轻点屏幕上的大肥鱼一次。"
        case "touch_confirmed":receiptNotice="已收到现场授权，正在暂存本次规则…"
        case "commit_verifying":receiptNotice="板端正在写入NVS并逐条回读校验…"
        case "verified":
            if result["verified"] as? Bool == true {
                let crc=result["crc32"] as? String ?? "未知"
                let applied=result["proposal_sha256"] as? String ?? ""
                let current=(try? Data(contentsOf:proposalURL)).map {
                    SHA256.hash(data:$0).map{String(format:"%02x",$0)}.joined()
                } ?? ""
                if !applied.isEmpty && applied==current {
                    receiptNotice="本次规则已由板端逐条读回验证，CRC "+crc+"。断线也保留。"
                } else {
                    receiptNotice="设备上一次已验证CRC "+crc+"；你新编辑的规则仍是Mac本地提案，尚未下发。请审阅后重新申请并在设备点按授权。"
                }
            }
        case "failed":
            receiptNotice = "未确认应用成功：" +
                (result["reason"] as? String ?? "未知错误") +
                "。当前不应假定规则已经改变。"
        default:break
        }
    }
    private var hasUnsavedChanges:Bool {
        guard let raw=try? Data(contentsOf:proposalURL),
              let obj=try? JSONSerialization.jsonObject(with:raw) as? [String:Any],
              let overrides=obj["overrides"] as? [[String:Any]] else {
            return !pending.isEmpty
        }
        let saved=Dictionary(uniqueKeysWithValues:overrides.compactMap { item -> (String,String)? in
            guard let key=item["id"] as? String,
                  let value=item["target_trigger"] as? String else{return nil}
            return (key,value)
        })
        return saved != pending
    }
    private func closeWindow(){
        // Explicitly close the owning sheet; environment dismiss is fallback.
        onClose()
        dismiss()
    }
    private var selected:MotionTriggerBinding? {
        manifest?.bindings.first(where:{$0.id==selectedID})
    }
    private var list:[MotionTriggerBinding] {
        (manifest?.bindings ?? []).filter {
            if group=="已自动绑定" { return $0.real_trigger != "manual" }
            if group=="尚未绑定" { return $0.real_trigger == "manual" }
            if group=="有待调整" { return pending[$0.id] != nil && pending[$0.id] != "inherit" }
            return true
        }
    }
    private var menuValue:String {
        pending[selectedID] ?? "inherit"
    }
    private func load() {
        guard let url=Bundle.main.url(forResource:"motion-trigger-r121",withExtension:"json"),
              let raw=try? Data(contentsOf:url),raw.count<40000,
              let info=try? JSONDecoder().decode(MotionTriggerManifest.self,from:raw),
              info.schema==1 && info.origin=="verified_R121_source_only" &&
              info.historical_count==35 &&
              info.bindings.count==35 &&
              info.auto_triggered_count+info.manual_only_count==35 &&
              Set(info.bindings.map(\.id)).count==35 &&
              info.live_binding_can_be_edited_on_R121 == false
        else { notice="触发规则审计清单缺失或无效；禁止生成同步方案";return }
        manifest=info
        if let catalogue=Bundle.main.url(forResource:"motion-catalog",withExtension:"json"),
           let raw=try? Data(contentsOf:catalogue),raw.count<100000,
           let obj=try? JSONSerialization.jsonObject(with:raw) as? [String:Any],
           let motions=obj["motions"] as? [[String:Any]] {
            names=Dictionary(uniqueKeysWithValues:motions.compactMap { entry in
                guard let id=entry["id"] as? String,let name=entry["name"] as? String else{return nil}
                return (id,name)
            })
        }
        if let data=try? Data(contentsOf:proposalURL),data.count<15000,
           let obj=try? JSONSerialization.jsonObject(with:data) as? [String:Any],
           obj["schema"] as? Int == 1,
           obj["status"] as? String == "offline_review_not_applied",
           obj["on_device"] as? Bool == false,
           obj["firmware_source_sha256"] as? String == info.firmware_source_sha256,
           let overrides=obj["overrides"] as? [[String:Any]] {
            let valid=Set(info.bindings.map(\.id))
            var restored=[String:String]()
            for item in overrides {
                if let id=item["id"] as? String,valid.contains(id),
                   let value=item["target_trigger"] as? String,
                   choices.contains(where:{$0.0==value}),value != "inherit" {
                    restored[id]=value
                }
            }
            pending=restored
            savedProposalSummary="Mac上已恢复保存的\(restored.count)条规则修改；未再次下发。"
        }
    }
    private func restoreSavedProposal(){
        // The persisted proposal is authoritative; discard only transient state.
        pending=[:]
        load()
        notice="已从本机文件恢复上次保存的规则。未操作ESP32。"
        showDiscardConfirm=false
    }
    private func change(_ value:String) {
        // m000 is the immutable recovery/boot idle. Never allow an offline
        // proposal that would strand the board without a safe idle sprite.
        guard selectedID != "m000" else {
            notice="m000是恢复基线，不能更改它的默认待机触发。"
            return
        }
        guard let manifest,manifest.bindings.contains(where:{$0.id==selectedID}),
              choices.contains(where:{$0.0==value}) else {return}
        if value == "inherit" {pending.removeValue(forKey:selectedID)}
        else {pending[selectedID]=value}
        notice="仅修改了本窗口的草稿。需要保存和本人实体授权后才会改变设备。"
    }
    private func save() {
        guard let manifest else {notice="未验证触发目录，不能保存";return}
        let valid=Set(manifest.bindings.map(\.id))
        guard pending.count<=35,
              pending.allSatisfy({entry in
                  valid.contains(entry.key) &&
                  choices.contains(where:{ choice in choice.0 == entry.value })
              }) else {
            notice="规则包含无效设备ID或不支持的触发方式";return
        }
        let data=MotionTriggerProposal(
            schema:1,status:"offline_review_not_applied",on_device:false,
            preserve_all_original_motions:true,
            firmware_source_sha256:manifest.firmware_source_sha256,
            overrides:pending.sorted(by:{$0.key<$1.key}).map {
                MotionTriggerOverride(id:$0.key,target_trigger:$0.value)})
        do {
            let root=proposalURL.deletingLastPathComponent()
            try FileManager.default.createDirectory(at:root,withIntermediateDirectories:true)
            let bytes=try JSONEncoder().encode(data)
            // Preserve last on-disk state before any deliberate save.
            let backup=root.appendingPathComponent("trigger-proposal-previous-save.json")
            if let previous=try? Data(contentsOf:proposalURL),previous.count<15000 {
                try previous.write(to:backup,options:.atomic)
                try FileManager.default.setAttributes(
                    [.posixPermissions:0o600],ofItemAtPath:backup.path)
            }
            try bytes.write(to:proposalURL,options:.atomic)
            try FileManager.default.setAttributes([.posixPermissions:0o600],ofItemAtPath:proposalURL.path)
            notice="已保存\(pending.count)条本机规则草稿（自动备份上次版本）；设备暂未改变。"
        }catch {notice="无法写入本机触发提案；未改变板端。"}
    }
    var body:some View {
        VStack(alignment:.leading,spacing:12) {
            HStack {
                Label("动画触发规则",systemImage:"arrow.triangle.branch")
                    .font(.system(size:19,weight:.semibold))
                Spacer()
                Button("关闭窗口"){closeWindow()}
                    .keyboardShortcut(.cancelAction)
            }
            Text("这里可以修改已安装的35条动画触发方式。左侧灰字是出厂历史基线，并非最新设备实时配置；橙字是Mac待下发修改。")
                .font(.system(size:12))
                .foregroundStyle(.secondary)
                .fixedSize(horizontal:false,vertical:true)
            HStack(alignment:.top,spacing:8) {
                Image(systemName:receiptNotice.contains("已由板端") ? "checkmark.seal.fill" : "info.circle")
                    .foregroundStyle(receiptNotice.contains("已由板端") ? .green : .orange)
                VStack(alignment:.leading,spacing:4) {
                    Text(receiptNotice.isEmpty
                        ? "状态显示在此 Mac 窗口，不会出现在设备屏幕。设备只负责接受你的真实点击授权。"
                        : receiptNotice)
                        .font(.system(size:13,weight:.semibold))
                        .fixedSize(horizontal:false,vertical:true)
                    Text("曾验证通过的设备规则保存在NVS，断线不丢。当前Mac草稿不会自动改变设备；依赖Mac对话阶段的触发不支持离线。")
                        .font(.system(size:11))
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal:false,vertical:true)
                }
                Spacer(minLength:0)
            }
            .padding(11)
            .frame(maxWidth:.infinity,alignment:.leading)
            .background(Color(nsColor: .controlBackgroundColor),
                        in:RoundedRectangle(cornerRadius:10))
            HStack {
                Label("历史自动绑定 \(manifest?.auto_triggered_count ?? 0)",systemImage:"checkmark.circle")
                Label("历史仅手动 \(manifest?.manual_only_count ?? 0)",systemImage:"hand.raised")
                Spacer()
                Picker("筛选",selection:$group) {
                    ForEach(["全部","已自动绑定","尚未绑定","有待调整"],id:\.self){Text($0).tag($0)}
                }.frame(width:190)
            }
            .font(.system(size:11))
            HStack(alignment:.top,spacing:14) {
                List(selection:$selectedID) {
                    ForEach(list) { item in
                        VStack(alignment:.leading,spacing:4){
                            HStack {
                                Text(item.id).font(.system(.caption,design:.monospaced))
                                Text(names[item.id] ?? "动画").font(.system(size:12,weight:.medium)).lineLimit(1)
                            }
                            Text("历史基线："+(display[item.real_trigger] ?? "未知"))
                                .font(.system(size:10)).foregroundStyle(.secondary)
                            if let proposed=pending[item.id],proposed != "inherit" {
                                Text("待下发提案："+(display[proposed] ?? proposed))
                                    .font(.system(size:10)).foregroundStyle(.orange)
                            }
                        }.tag(item.id)
                    }
                }.frame(width:325).frame(minHeight:390)
                VStack(alignment:.leading,spacing:14) {
                    if let item=selected {
                        Text(names[item.id] ?? item.id).font(.system(size:16,weight:.semibold))
                        Text(item.id).font(.system(.caption,design:.monospaced))
                            .foregroundStyle(.secondary)
                        GroupBox("历史默认规则（非实时回读）") {
                            Text(display[item.real_trigger] ?? "未映射")
                                .font(.system(size:12))
                                .frame(maxWidth:.infinity,alignment:.leading)
                        }
                        Picker("准备修改为",selection:Binding(
                            get:{menuValue},set:{change($0)})) {
                            ForEach(choices,id:\.0){choice in
                                Text(choice.1).tag(choice.0)
                            }
                        }.frame(maxWidth:.infinity)
                         .disabled(item.id=="m000")
                        Text("如需停止自动播放，请选择“仅手动展示”并申请下发；选择“保持目前触发”只是不修改本条。")
                            .font(.system(size:11)).foregroundStyle(.secondary)
                        if item.id=="m018" {
                            Text("特别说明：拖拽反馈需实体触摸/拖拽事件绑定，R121未实现该手势。")
                                .font(.system(size:11)).foregroundStyle(.orange)
                        }
                    }
                    Spacer()
                    Text("R136 已支持 DFTRIGGER1：需要你点击申请，并在设备上点按大肥鱼确认；仅触发规则写入NVS，绝不刷固件或新增SD素材。")
                        .font(.system(size:11)).foregroundStyle(.orange)
                        .fixedSize(horizontal:false,vertical:true)
                }.frame(width:300)
            }
            HStack(spacing:10) {
                Button("恢复上次保存的规则"){restoreSavedProposal()}
                    .disabled(manifest == nil)
                Button("放弃本窗口未保存的编辑"){showDiscardConfirm=true}
                    .disabled(!hasUnsavedChanges)
                    .confirmationDialog("放弃本窗口还没保存的修改？",
                        isPresented:$showDiscardConfirm,titleVisibility:.visible) {
                        Button("放弃本次编辑"){restoreSavedProposal()}
                        Button("取消",role:.cancel){}
                    } message:{
                        Text("不会删除已经保存的规则，更不会影响ESP32。可随时点击“恢复上次保存的规则”。")
                    }
                Spacer()
                Button("保存规则草稿"){save()}
                    .disabled(manifest == nil || !hasUnsavedChanges)
                Button("申请应用到当前ESP32（需现场确认）") {
                    approveInstall=true
                }
                .disabled(pending.isEmpty || !store.bothVerified ||
                           store.snapshot?.phase != "idle")
                .confirmationDialog("确认准备应用这些触发规则？",
                                    isPresented:$approveInstall,titleVisibility:.visible) {
                    Button("申请下发，随后在设备点击授权") {
                        requestPhysicalRuleApplication()
                    }
                    Button("取消",role:.cancel){}
                } message:{
                    Text("这将使用现有R136设备的DFTRIGGER1协议写入规则到NVS，不会刷板、不写SD素材。必须手动轻点设备一次，之后系统逐条回读核验。")
                }
            }
            if !savedProposalSummary.isEmpty {
                Text(savedProposalSummary).font(.system(size:11)).foregroundStyle(.secondary)
            }
            if !notice.isEmpty {
                Text(notice).font(.system(size:11)).foregroundStyle(.secondary)
            }
            HStack {
                Spacer()
                Button("关闭规则窗口"){closeWindow()}
                    .keyboardShortcut(.escape,modifiers:[])
            }
        }
        .padding(18).frame(minWidth:760,idealWidth:780,minHeight:680,idealHeight:700)
        .background(Color(nsColor: .windowBackgroundColor))
        .onAppear{load();refreshApplyReceipt()}
        .onReceive(Timer.publish(every:1.2,on:.main,in:.common).autoconnect()) { _ in
            refreshApplyReceipt()
        }
    }
}
