// SPDX-License-Identifier: MIT
// R151 R150 physical 106-ID rules: clear saved drafts vs real NVS map2.
// No SD firmware mutation; a physical avatar tap is mandatory for commit.
import AppKit
import SwiftUI
import CryptoKit

private struct R151Motion: Decodable,Identifiable {
    let id:String
    let name:String
    let inCurrentPackage:Bool
    let previewName:String
}
private struct R151Catalog:Decodable {
    let schema:Int
    let count:Int
    let motions:[R151Motion]
}
private struct R151Rule:Codable {
    let id:String
    let target_trigger:String
}
private struct R158DeviceClip:Decodable {
    let id:String
    let sha256:String
    let bytes:Int
}
private struct R158DeviceLibrary:Decodable {
    let schema:Int
    let status:String
    let device_firmware:String
    let factory35_preserved:Bool
    let verified_additional_count:Int
    let verified_additional:[R158DeviceClip]
}
private struct R172RulesReadback:Decodable {
    let schema:Int
    let source:String
    let session_id:String
    let updated_at_unix:Double
    let count:Int
    let v2_active:Bool
    let v2_crc32:String
    let legacy_crc32:String
    let legacy_count:Int
    let legacy_rules:[String:String]
    let rules:[String:String]
}
private struct R151Draft:Codable {
    let schema:Int
    let status:String
    let count:Int
    let protect_m000:Bool
    let overrides:[R151Rule]
}
struct MotionTriggers106Sheet:View {
    @ObservedObject var store:CompanionStore
    let onClose:()->Void
    var embedded:Bool = false
    var sharedSelection:Binding<String>? = nil
    var sessionChanges:Binding<[String:String]?>? = nil
    @Environment(\.dismiss) private var dismiss
    @State private var motions=[R151Motion]()
    @State private var selectedID="m080"
    @State private var pending=[String:String]()
    @State private var saved=[String:String]()
    @State private var filter="全部"
    @State private var message=""
    @State private var deviceNotice="设备端106条规则状态尚未读取；Mac草稿不能当成设备状态。"
    @State private var approvedDeviceIDs=Set<String>()
    @State private var approve=false
    @State private var discard=false
    @State private var liveRules:R172RulesReadback?
    @State private var readbackMessage="未读取设备规则"
    @State private var lastReadbackRequest=Date.distantPast
    // A successful NVS commit does not make the *cached* 106-rule list live.
    // Queue one read-only, same-session snapshot after each new verified
    // commit and show the result only after independent matching CRC.
    @State private var lastAutoReadbackFingerprint=""
    @State private var awaitingAppliedCRC:String? = nil
    @State private var awaitingAppliedAt:Double=0
    // A modal is shown ONLY after a fresh real board WAIT_LOCAL_TOUCH receipt.
    // It is not triggered just by clicking "apply" or by an old result file.
    @State private var authorizedRequestStarted=Date.distantPast
    @State private var lastNoticeFingerprint=""
    @State private var actionAlertOpen=false
    @State private var actionAlertTitle=""
    @State private var actionAlertMessage=""
    @State private var tapRemaining=0
    // Keep a single timer publisher across body re-evaluations so parent
    // store polling cannot reset the 0.8s countdown before it fires.
    private static let pollTimer = Timer.publish(every:0.8,on:.main,in:.common).autoconnect()
    private let choices=[
        ("inherit","不改动这条规则"),
        ("manual","仅手动，不参与自动轮换"),
        ("tap","点击互动"),
        ("idle","待机轮换"),
        ("bonus","低频彩蛋"),
        ("work","工作状态"),
        ("drag","拖拽触发（需实体支持）")]
    private var root:URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/Deepseek-live")
    }
    private var draftURL:URL {root.appendingPathComponent("motion-library/trigger-proposal-v2.json")}
    private var oldDraftURL:URL {root.appendingPathComponent("motion-library/trigger-proposal-r121.json")}
    private var physicalLibraryURL:URL {
        root.appendingPathComponent("motion-library/physical-sd-106.json")
    }
    private func refreshPhysicalLibrary(){
        guard let raw=try? Data(contentsOf:physicalLibraryURL),raw.count<32000,
              let proven=try? JSONDecoder().decode(R158DeviceLibrary.self,from:raw),
              proven.schema==1 && proven.status=="hardware_sha_readback_verified"
              && proven.device_firmware=="R170" && proven.factory35_preserved
              && proven.verified_additional.count==proven.verified_additional_count
              && proven.verified_additional.count<=71
              && Set(proven.verified_additional.map(\.id)).count==proven.verified_additional_count
              && proven.verified_additional.allSatisfy({x in
                x.id.hasPrefix("m") && (Int(x.id.dropFirst()) ?? -1)<106
                && x.sha256.count==64 && x.bytes>500 && x.bytes<8_000_000
                && motions.contains(where:{$0.id==x.id && !$0.inCurrentPackage})
              })
        else {return}
        approvedDeviceIDs=Set(proven.verified_additional.map(\.id))
    }
    private var requestURL:URL {root.appendingPathComponent("companion-native/trigger106-apply-request.json")}
    private var reportURL:URL {root.appendingPathComponent("companion-native/trigger106-apply-result.json")}
    private var readbackURL:URL {
        root.appendingPathComponent("companion-native/trigger-readback-result.json")
    }
    private var readbackRequestURL:URL {
        root.appendingPathComponent("companion-native/trigger-readback-request.json")
    }
    private var liveFresh:Bool {
        guard let info=liveRules, info.session_id==store.snapshot?.session_id else {return false}
        return abs(Date().timeIntervalSince1970-info.updated_at_unix)<180
    }
    private func current(_ id:String)->String? {
        guard liveFresh else {return nil}
        return liveRules?.rules[id]
    }
    private func name(_ group:String)->String {
        group=="boot" ? "开机保底" : (choices.first{$0.0==group}?.1 ?? group)
    }
    private var changedCount:Int? {
        guard liveFresh else{return nil}
        return pending.filter{current($0.key) != $0.value}.count
    }
    private func refreshReadback(){
        guard let raw=try? Data(contentsOf:readbackURL),raw.count<7000,
              let info=try? JSONDecoder().decode(R172RulesReadback.self,from:raw),
              info.schema==1 && info.source=="real_esp32_usb_readback"
              && info.count==106 && info.rules.count==106
              && info.legacy_count==35 && info.legacy_rules.count==35
              && info.session_id==store.snapshot?.session_id
              && abs(Date().timeIntervalSince1970-info.updated_at_unix)<180
              && Set(info.rules.keys)==Set((0..<106).map{String(format:"m%03d",$0)})
              && info.rules["m000"]=="boot" && info.v2_crc32.count==8
        else{return}
        liveRules=info
        readbackMessage="已实时读取106条规则 · 仅读取，未写入"
        if let expected=awaitingAppliedCRC,
           info.updated_at_unix>=awaitingAppliedAt-1 {
            awaitingAppliedCRC=nil
            if info.v2_active && info.v2_crc32==expected {
                deviceNotice="已生效：设备重新读回106条规则，CRC \(expected)。差异列表已刷新。"
                if authorizedRequestStarted != .distantPast {
                    showActionNotice("success-\(authorizedRequestStarted.timeIntervalSince1970)",
                        title:"触发规则已成功下发",
                        details:"已核实实体NVS写入，重新读回106条规则与提交CRC \(expected)一致。差异列表已刷新。")
                }
            } else {
                deviceNotice="下发回执已取得，但最新设备规则与提交CRC不一致；请重新读取，暂不认定规则一致。"
            }
        }
    }
    private func requestReadback(){
        guard store.bothVerified,store.snapshot?.phase=="idle",
              let session=store.snapshot?.session_id,!session.isEmpty else {
            readbackMessage="设备暂未空闲在线，无法读取。不会修改现有绑定。"
            return
        }
        guard Date().timeIntervalSince(lastReadbackRequest)>3 else{return}
        if FileManager.default.fileExists(atPath:readbackRequestURL.path){
            readbackMessage="设备规则读取中…";return
        }
        let packet:[String:Any]=["schema":1,"action":"read_current_rules",
            "session_id":session,"at":Date().timeIntervalSince1970]
        do {
            let raw=try JSONSerialization.data(withJSONObject:packet)
            try raw.write(to:readbackRequestURL,options:.atomic)
            try FileManager.default.setAttributes(
                [.posixPermissions:0o600],ofItemAtPath:readbackRequestURL.path)
            lastReadbackRequest=Date()
            readbackMessage="正在从设备读取，不修改NVS…"
        }catch{readbackMessage="无法发出只读查询，设备未改变。"}
    }
    private var canApply:Bool {
        store.bothVerified && store.snapshot?.phase=="idle" && !pending.isEmpty && pending==saved
    }
    private var shown:[R151Motion] {
        motions.filter{ item in
            switch filter {
            case "已入选35条":return item.inCurrentPackage
            case "新增71条":return !item.inCurrentPackage
            case "待下发差异":return pending[item.id] != nil &&
                (!liveFresh || current(item.id) != pending[item.id])
            case "已一致":return pending[item.id] != nil && liveFresh &&
                current(item.id)==pending[item.id]
            default:return true
            }
        }
    }
    private var focused:R151Motion? {motions.first{$0.id==selectedID}}
    private func close(){onClose();dismiss()}
    private func load(){
        if let url=Bundle.main.url(forResource:"motion-catalog",withExtension:"json"),
           let data=try? Data(contentsOf:url),data.count<110000,
           let catalog=try? JSONDecoder().decode(R151Catalog.self,from:data),
           catalog.count==106,catalog.motions.count==106,
           Set(catalog.motions.map(\.id))==Set((0..<106).map{String(format:"m%03d",$0)}){
            motions=catalog.motions
        }else{message="106素材目录未核验；禁止保存或下发规则。";return}
        refreshPhysicalLibrary()
        if let bytes=try? Data(contentsOf:draftURL),bytes.count<20000,
           let prior=try? JSONDecoder().decode(R151Draft.self,from:bytes),
           prior.schema==2 && prior.count==106 && prior.protect_m000 &&
           prior.status=="local_pending_not_on_device" {
            saved=Dictionary(uniqueKeysWithValues:prior.overrides.map{($0.id,$0.target_trigger)})
            pending=saved
            message="已读取本机保存的 \(saved.count) 条修改计划；是否生效，请看设备对比。"
        }else if let bytes=try? Data(contentsOf:oldDraftURL),bytes.count<15000,
                 let object=try? JSONSerialization.jsonObject(with:bytes) as? [String:Any],
                 let items=object["overrides"] as? [[String:Any]] {
            let old=items.compactMap{ value -> (String,String)? in
                guard let id=value["id"] as? String, let val=value["target_trigger"] as? String,
                      id != "m000",id.hasPrefix("m"),Int(id.dropFirst()) != nil,
                      ["manual","tap","idle","bonus","work","drag"].contains(val) else{return nil}
                return (id,val)
            }
            saved=Dictionary(uniqueKeysWithValues:old)
            pending=saved
            message="已找到此前保存的 \(saved.count) 条本地计划。设备相同的条目无需再次下发。"
        }
        refresh()
        refreshReadback()
        requestReadback()
    }
    private func reportFreshForThisRequest()->Bool {
        guard authorizedRequestStarted != .distantPast,
              let attrs=try? FileManager.default.attributesOfItem(atPath:reportURL.path),
              let modified=attrs[.modificationDate] as? Date else {return false}
        return modified>=authorizedRequestStarted.addingTimeInterval(-0.8)
               && Date().timeIntervalSince(modified)<42
    }
    private func showActionNotice(_ key:String,title:String,details:String) {
        guard key != lastNoticeFingerprint else {return}
        lastNoticeFingerprint=key
        actionAlertTitle=title
        actionAlertMessage=details
        NSApp.activate(ignoringOtherApps:true)
        if actionAlertOpen {
            actionAlertOpen=false
            DispatchQueue.main.async { actionAlertOpen=true }
        } else {
            actionAlertOpen=true
        }
    }
    private func refresh(){
        guard let raw=try? Data(contentsOf:reportURL),raw.count<5000,
              let obj=try? JSONSerialization.jsonObject(with:raw) as? [String:Any],
              let status=obj["status"] as? String else{return}
        let activeReport=reportFreshForThisRequest()
        switch status {
        case "waiting_for_local_tap":
            guard activeReport else {return}
            let attrs=try? FileManager.default.attributesOfItem(atPath:reportURL.path)
            let modified=attrs?[.modificationDate] as? Date ?? Date()
            tapRemaining=max(0,Int(ceil(30-Date().timeIntervalSince(modified))))
            deviceNotice="现在请点击实体大肥鱼！剩余约\(tapRemaining)秒；仅点击设备屏幕，不是在Mac上点击。"
            if tapRemaining>0 {
                showActionNotice("tap-\(authorizedRequestStarted.timeIntervalSince1970)",
                    title:"现在请点击实体大肥鱼",
                    details:"设备已真正进入30秒授权窗口。请在\(tapRemaining)秒内轻点ESP32屏幕上的大肥鱼一次；不是点击Mac。随后我会显示成功或失败，并重新读取规则。")
            }
        case "touch_confirmed":
            tapRemaining=0
            deviceNotice="实体点击已确认，正在向设备提交规则…"
        case "commit_verifying":
            tapRemaining=0
            deviceNotice="设备已收到点击，正在核对NVS规则校验值…"
        case "verified":
            tapRemaining=0
            let crc=obj["crc32"] as? String ?? ""
            let sha=obj["proposal_sha256"] as? String ?? ""
            let data=try? Data(contentsOf:draftURL)
            let current=data.map{SHA256.hash(data:$0).map{String(format:"%02x",$0)}.joined()} ?? ""
            guard obj["verified"] as? Bool == true,
                  crc.range(of:"^[0-9a-f]{8}$",options:.regularExpression) != nil else {
                deviceNotice="收到不完整的设备提交回执，请重新读取，不认定规则已经生效。"
                return
            }
            if sha==current && !sha.isEmpty {
                // If the current snapshot already has the confirmed CRC,
                // leave it visible. Otherwise queue a *read-only* refresh.
                if liveFresh && liveRules?.v2_active==true &&
                   liveRules?.v2_crc32==crc && awaitingAppliedCRC==nil {
                    deviceNotice="已生效：设备106条规则读回CRC \(crc)，差异列表已刷新。"
                } else {
                    deviceNotice="板端提交已通过逐条校验，CRC \(crc)；正在重新读取设备规则并刷新差异…"
                    let fingerprint=sha+":"+crc
                    if fingerprint != lastAutoReadbackFingerprint &&
                       Date().timeIntervalSince(lastReadbackRequest)>3 &&
                       store.bothVerified && store.snapshot?.phase=="idle" &&
                       !FileManager.default.fileExists(atPath:readbackRequestURL.path) {
                        lastAutoReadbackFingerprint=fingerprint
                        awaitingAppliedCRC=crc
                        awaitingAppliedAt=Date().timeIntervalSince1970
                        requestReadback()
                    }
                }
            } else {
                deviceNotice="以前成功下发过规则，CRC \(crc)；当前本机计划与该版本不同，不会假称已生效。"
            }
        case "failed":
            tapRemaining=0
            let reason=obj["reason"] as? String ?? "未知错误"
            deviceNotice="此次下发未确认成功："+reason
            if activeReport {
                showActionNotice("fail-\(authorizedRequestStarted.timeIntervalSince1970)",
                    title:"触发规则未能下发",
                    details:"设备未确认成功：\(reason)。原有设备规则不视为已改变；可稍后重试。")
            }
        case "starting":
            tapRemaining=0
            deviceNotice="正在申请实体授权，已送达设备；等待进入30秒点击窗口…"
        default:deviceNotice="规则操作中，正在校验设备状态…"
        }
    }
    private func set(_ value:String){
        guard selectedID != "m000" else {message="m000是开机恢复保底，不允许修改。";return}
        if value=="inherit"{pending.removeValue(forKey:selectedID)}
        else{pending[selectedID]=value}
        message="只改了当前窗口草稿。保存并现场授权后才会影响设备。"
    }
    private func restore(){
        pending=saved
        message="已恢复上次保存的 \(saved.count) 条修改，未影响实体设备。"
    }
    private func save(){
        guard motions.count==106 && !pending.keys.contains("m000")
           && pending.count<=105 &&
           pending.allSatisfy({k,v in Set(motions.map(\.id)).contains(k)
                                 && choices.contains(where:{$0.0==v}) && v != "inherit"})
        else{message="包含无效编号或触发方式，未保存。";return}
        let draft=R151Draft(schema:2,status:"local_pending_not_on_device",
                           count:106,protect_m000:true,
                           overrides:pending.sorted{$0.key<$1.key}.map{R151Rule(id:$0.key,target_trigger:$0.value)})
        do {
            let bytes=try JSONEncoder().encode(draft)
            let dir=draftURL.deletingLastPathComponent()
            try FileManager.default.createDirectory(at:dir,withIntermediateDirectories:true)
            if let prior=try? Data(contentsOf:draftURL),prior.count<20000 {
                let backup=dir.appendingPathComponent("trigger-proposal-v2-previous.json")
                try prior.write(to:backup,options:.atomic)
                try FileManager.default.setAttributes([.posixPermissions:0o600],ofItemAtPath:backup.path)
            }
            try bytes.write(to:draftURL,options:.atomic)
            try FileManager.default.setAttributes([.posixPermissions:0o600],ofItemAtPath:draftURL.path)
            saved=pending
            message="已保存 \(saved.count) 条本地草稿，设备尚未改变；旧草稿可恢复。"
        }catch{message="保存失败。设备没有变化。"}
    }
    private func request(){
        guard canApply,let sid=store.snapshot?.session_id,!sid.isEmpty else{
            message="请先保存草稿并等待设备/DSH处于空闲在线状态。";return
        }
        guard !FileManager.default.fileExists(atPath:requestURL.path),
              let data=try? Data(contentsOf:draftURL),data.count<20000 else{
            message="当前有另一项申请，或者未找到已保存的草稿。";return
        }
        let digest=SHA256.hash(data:data).map{String(format:"%02x",$0)}.joined()
        let object:[String:Any]=["schema":2,"action":"apply106_saved_rules",
                                  "session_id":sid,"at":Date().timeIntervalSince1970,
                                  "proposal_sha256":digest]
        do {
            let raw=try JSONSerialization.data(withJSONObject:object)
            try raw.write(to:requestURL,options:.atomic)
            try FileManager.default.setAttributes([.posixPermissions:0o600],ofItemAtPath:requestURL.path)
            lastAutoReadbackFingerprint=""
            awaitingAppliedCRC=nil
            authorizedRequestStarted=Date()
            lastNoticeFingerprint=""
            tapRemaining=0
            deviceNotice="正在申请实体授权，尚未开始30秒倒计时；请等弹窗再点设备。"
        }catch{message="申请发送失败，设备未改变。"}
    }
    var body:some View {
        VStack(alignment:.leading,spacing:11){
            if !embedded {
                HStack {
                    Label("106条设备动画 · 触发规则",systemImage:"square.stack.3d.up")
                        .font(.system(size:17,weight:.semibold))
                    Spacer()
                    Button("关闭窗口"){close()}.keyboardShortcut(.cancelAction)
                }
            }
            HStack(alignment:.center,spacing:12){
                VStack(alignment:.leading,spacing:4) {
                    Text(liveFresh
                         ? (liveRules?.v2_active == true
                            ? "设备当前：新版106条触发规则"
                            : "设备当前：原35条规则仍生效")
                         : "设备规则尚未实时读取")
                        .font(.system(size:14,weight:.semibold))
                    Text(liveFresh
                         ? "旧规则CRC：\(liveRules?.legacy_crc32 ?? "未知") · 查询不会修改绑定"
                         : "之前的规则已在设备NVS保存；读回后可看清哪些需要修改。")
                        .font(.system(size:11)).foregroundStyle(.secondary)
                }
                Spacer()
                Button("重新读取设备"){requestReadback()}
                    .disabled(!store.bothVerified || store.snapshot?.phase != "idle")
            }
            .padding(15)
            .background(Color.accentColor.opacity(0.07),in:RoundedRectangle(cornerRadius:12))
            HStack(spacing:14){
                Label("设备素材 \(35+approvedDeviceIDs.count)/106",systemImage:"square.stack")
                Label("本机草稿 \(saved.count) 条",systemImage:"doc.text")
                Label(liveFresh ? "待应用差异 \(changedCount ?? 0) 条" :
                    "差异待核对 \(pending.count) 条",systemImage:"arrow.left.arrow.right")
                Spacer()
                Picker("查看",selection:$filter){
                    ForEach(["全部","待下发差异","已一致","新增71条"],id:\.self){
                        Text($0).tag($0)
                    }
                }.frame(width:172)
            }.font(.system(size:12))
            HStack(spacing:8) {
                Text("设备当前").foregroundStyle(.secondary)
                Image(systemName:"arrow.right").foregroundStyle(.tertiary)
                Text("本机计划").foregroundStyle(.orange)
                Spacer()
                Text("保存后仍需实体确认").foregroundStyle(.secondary)
            }
            .font(.caption)
            .accessibilityElement(children:.combine)
            Text(readbackMessage).font(.caption).foregroundStyle(.secondary)
            if !deviceNotice.isEmpty {
                Label(deviceNotice,systemImage:
                    deviceNotice.hasPrefix("已生效") ? "checkmark.seal" :
                    deviceNotice.contains("失败") || deviceNotice.contains("超时") ||
                    deviceNotice.contains("未确认") ? "exclamationmark.circle" :
                    "info.circle")
                    .font(.system(size:tapRemaining>0 ? 15 : 12,
                                  weight:tapRemaining>0 ? .bold : .medium))
                    .foregroundStyle(tapRemaining>0 ? Color.orange :
                                     deviceNotice.hasPrefix("已生效") ? Color.green : Color.primary)
                    .padding(10)
                    .frame(maxWidth:.infinity,alignment:.leading)
                    .background(tapRemaining>0 ?
                        Color.orange.opacity(0.15) : Color(nsColor:.controlBackgroundColor),
                        in:RoundedRectangle(cornerRadius:10))
                    .fixedSize(horizontal:false,vertical:true)
            }
            HStack(alignment:.top,spacing:12){
                ScrollViewReader { proxy in
                List(selection:$selectedID){
                    ForEach(shown){ item in
                        VStack(alignment:.leading,spacing:3){
                            HStack(spacing:7){
                                Text(item.id).font(.system(.caption,design:.monospaced))
                                Text(item.name).font(.system(size:13,weight:.medium)).lineLimit(1)
                            }
                            Text(item.inCurrentPackage ? "原有35条 · 设备保底" :
                                 approvedDeviceIDs.contains(item.id)
                                 ? "新增素材 · 实体SD SHA已验证"
                                 : "尚未安装 · 编号仅可预设")
                                .font(.system(size:11))
                                .foregroundStyle(approvedDeviceIDs.contains(item.id) ? .green : .secondary)
                            if let proposed=pending[item.id] {
                                if let effective=current(item.id) {
                                    let same=proposed==effective
                                    let description=same
                                        ? "已一致："+name(effective)
                                        : "设备："+name(effective)+" → 计划："+name(proposed)
                                    Text(description)
                                        .font(.system(size:11))
                                        .foregroundStyle(same ? Color.secondary : Color.orange)
                                }else{
                                    Text("本机计划："+name(proposed)+" · 待读取设备")
                                        .font(.system(size:11)).foregroundStyle(.secondary)
                                }
                            }else if let effective=current(item.id) {
                                Text("设备："+name(effective))
                                    .font(.system(size:11)).foregroundStyle(.secondary)
                            }
                        }.padding(.vertical,4).tag(item.id).id(item.id)
                    }
                }
                .scrollContentBackground(.hidden)
                .background(Color.primary.opacity(0.035),in:RoundedRectangle(cornerRadius:12))
                .clipShape(RoundedRectangle(cornerRadius:12))
                .frame(minWidth:embedded ? 295 : 382,
                        maxWidth:embedded ? .infinity : 382,
                        minHeight:380,
                        maxHeight:embedded ? .infinity : nil)
                .onChange(of:selectedID) { _,id in
                    proxy.scrollTo(id,anchor:.center)
                }
                .onChange(of:shown.map(\.id)) { _,ids in
                    if ids.contains(selectedID) {
                        proxy.scrollTo(selectedID,anchor:.center)
                    }
                }
                }
                ScrollView {
                VStack(alignment:.leading,spacing:10){
                    if let item=focused {
                        Text(item.name).font(.system(size:17,weight:.semibold))
                        Text(item.id).font(.system(.caption,design:.monospaced)).foregroundStyle(.secondary)
                        if !shown.contains(where:{$0.id==item.id}) {
                            Label("当前筛选中未显示此动画",systemImage:"line.3.horizontal.decrease.circle")
                                .font(.system(size:11)).foregroundStyle(.secondary)
                        }
                        // Reuse the exact player and light 8fps motion files
                        // from the main motion-library page, not the black
                        // JPG cover that never animates.
                        if let animation=store.motionFile(for:item.id) {
                            PrivateMotionPlayer(url:animation)
                                .id(item.id)
                                .frame(width:embedded ? 250 : 220,
                                       height:embedded ? 250 : 208)
                                .background(Color(nsColor: .controlBackgroundColor),
                                            in:RoundedRectangle(cornerRadius:12))
                                .clipShape(RoundedRectangle(cornerRadius:12))
                                .frame(maxWidth:.infinity)
                        } else {
                            Label("当前动画预览尚未生成",systemImage:"film")
                                .font(.system(size:11)).foregroundStyle(.secondary)
                                .frame(width:embedded ? 250 : 220,
                                       height:embedded ? 250 : 208)
                                .background(Color(nsColor: .controlBackgroundColor),
                                            in:RoundedRectangle(cornerRadius:12))
                                .frame(maxWidth:.infinity)
                        }
                        Text(item.inCurrentPackage
                             ? "原版35条：保留原素材与旧NVS规则；新绑定仍须实体授权。"
                             : approvedDeviceIDs.contains(item.id)
                               ? "新增素材：实体SD已成功上传并通过文件SHA读回；仍需本人触摸授权才能绑定触发。"
                               : "新增素材：当前仅可预设规则；完成实体SD上传和SHA读回前不会自动播放。")
                            .font(.system(size:11)).foregroundStyle(.secondary)
                            .fixedSize(horizontal:false,vertical:true)
                        if let effective=current(item.id) {
                            Label("设备当前："+name(effective),systemImage:"checkmark.shield")
                                .font(.system(size:12,weight:.medium))
                        }else{
                            Label("设备当前规则尚未读回",systemImage:"info.circle")
                                .font(.system(size:11)).foregroundStyle(.secondary)
                        }
                        if let proposed=pending[item.id] {
                            Text(proposed==current(item.id)
                                 ? "本机计划与设备一致 · 无需再次下发"
                                 : "本机计划："+name(proposed)+(liveFresh ? " · 未下发" : " · 待核对"))
                                .font(.system(size:11))
                                .foregroundStyle(proposed==current(item.id) ? Color.secondary : Color.orange)
                        }
                        Picker("准备设为",selection:Binding(
                            get:{pending[selectedID] ?? "inherit"},set:{set($0)})){
                            ForEach(choices,id:\.0){Text($0.1).tag($0.0)}
                        }.disabled(selectedID=="m000")
                        Text("保留当前规则无需操作；解除自动绑定选“仅手动”。保存只留在Mac，应用前需实体确认。")
                            .font(.system(size:11)).foregroundStyle(.secondary)
                    }
                    Spacer(minLength:0)
                }
                .padding(16)
                .frame(maxWidth:.infinity,maxHeight:.infinity,alignment:.topLeading)
                }
                .frame(maxWidth:.infinity,maxHeight:.infinity,alignment:.topLeading)
                .background(Color.primary.opacity(0.035),in:RoundedRectangle(cornerRadius:12))
            }
            .frame(minHeight:365,maxHeight:.infinity)
            HStack(spacing:10){
                Button("恢复本机保存"){restore()}
                Button("放弃未保存编辑"){discard=true}
                    .disabled(pending==saved)
                    .confirmationDialog("确认放弃当前窗口未保存的修改？",
                        isPresented:$discard,titleVisibility:.visible){
                        Button("放弃当前编辑"){restore()}
                        Button("取消",role:.cancel){}
                    }message:{Text("不会删除本机已保存的草稿，也不会影响ESP32。")}
                Spacer()
                Button("保存本地计划"){save()}.disabled(pending==saved && FileManager.default.fileExists(atPath:draftURL.path))
                Button("应用已保存计划"){approve=true}
                    .disabled(!canApply || !liveFresh || (changedCount ?? 0)==0
                              || !FileManager.default.fileExists(atPath:draftURL.path))
                    .confirmationDialog("确认将本机已保存的完整计划提交给实体设备？",
                       isPresented:$approve,titleVisibility:.visible){
                       Button("申请，随后本人点击设备"){request()}
                       Button("取消",role:.cancel){}
                    }message:{
                       Text("本次方案共有 \(saved.count) 条，其中与设备不同的有 \(changedCount ?? 0) 条。全部计划将提交至新版规则表；仍需你在30秒内亲自轻点实体设备确认，不会写SD或刷固件。")
                    }
            }
            if !message.isEmpty {Text(message).font(.system(size:11)).foregroundStyle(.secondary)}
            if !embedded {
                HStack {
                    Spacer()
                    Button("关闭规则窗口"){close()}
                }
            }
        }
        .padding(embedded ? 16 : 18)
        .frame(width:embedded ? nil : 815,
               height:embedded ? nil : 750)
        .frame(maxWidth:embedded ? .infinity : nil,
               maxHeight:embedded ? .infinity : nil,alignment:.topLeading)
        .background(Color(nsColor:.windowBackgroundColor))
        .onAppear{
            load()
            if let selected=sharedSelection?.wrappedValue,
               selected.range(of:#"^m[0-9]{3}$"#,options:.regularExpression) != nil {
                selectedID=selected
            }
            if let draft=sessionChanges?.wrappedValue {
                pending=draft
            }
        }
        .onChange(of:selectedID){_,id in
            sharedSelection?.wrappedValue=id
        }
        .onChange(of:pending){_,draft in
            sessionChanges?.wrappedValue=draft
        }
        .safeAreaInset(edge:.top,spacing:0) {
            if authorizedRequestStarted != .distantPast &&
               Date().timeIntervalSince(authorizedRequestStarted)<43 &&
               (tapRemaining>0 || deviceNotice.contains("正在申请实体授权")) {
                HStack(spacing:12) {
                    Image(systemName:tapRemaining>0 ? "hand.tap.fill":"clock")
                        .font(.system(size:20))
                    VStack(alignment:.leading,spacing:3) {
                        Text(tapRemaining>0 ? "现在点击实体大肥鱼" : "授权申请已送出")
                            .font(.system(size:16,weight:.bold))
                        Text(tapRemaining>0
                             ? "实体设备已进入授权窗口，剩余约\(tapRemaining)秒"
                             : "等待设备回执；还没有开始30秒倒计时，不要提前点击")
                            .font(.system(size:12))
                    }
                    Spacer(minLength:0)
                }
                .padding(14)
                .frame(maxWidth:.infinity)
                .background(tapRemaining>0 ? Color.orange.opacity(0.20) :
                             Color.accentColor.opacity(0.11))
                .accessibilityIdentifier("r223-physical-approval-banner")
            }
        }
        .onReceive(Self.pollTimer){_ in
            refresh()
            refreshReadback()
            refreshPhysicalLibrary()
        }
        .alert(actionAlertTitle,isPresented:$actionAlertOpen) {
            Button("知道了，去点击实体设备",role:.cancel){}
        } message: {
            Text(actionAlertMessage)
        }
    }
}
