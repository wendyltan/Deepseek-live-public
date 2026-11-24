// SPDX-License-Identifier: MIT
// Native catalog is extensible; published baseline motions are preserved.
// All device writes remain blocked pending per-file physical verification.
import AppKit
import SwiftUI
import UniformTypeIdentifiers

private struct MotionEntry: Codable, Identifiable {
    let id: String
    let name: String
    let category: String
    let inCurrentPackage: Bool
    let previewName: String
    let framesName: String
}
private struct MotionLibraryCatalog: Decodable {
    let schema: Int
    let count: Int
    let selectedCount: Int
    let motions: [MotionEntry]
}
private struct MotionScaleResult: Decodable {
    let id: String
    let risk: String
    let relativeScaleToIdle: Double
    let sourceScaleTo240: Double
    let framesMeasured: Int
}
private struct MotionScaleCatalog: Decodable {
    let schema: Int
    let count: Int
    let kind: String
    let motions: [MotionScaleResult]
}

struct MotionLibrarySheet: View {
    @ObservedObject var store: CompanionStore
    var embedded:Bool = false
    var openRules:(() -> Void)? = nil
    var sharedSelection:Binding<String>? = nil
    @Environment(\.dismiss) private var dismiss
    @State private var search=""
    @State private var group="全部"
    @State private var selectedID="m000"
    @State private var staged=Set<String>()
    @State private var customLabels=[String:String]()
    @State private var feedback=""
    @State private var isEncoding=false
    @State private var isCheckingInstall=false
    @State private var isInstalling=false
    @State private var entries=[MotionEntry]()
    @State private var loaded=false
    @State private var showTriggers=false
    @State private var scaleChecks=[String:MotionScaleResult]()
    @State private var physicallyInstalledNew=Set<String>()

    private let groups=["全部","设备素材","待新增","待机","工作","互动","彩蛋"]
    private let roles=["待机","工作","互动","彩蛋"]
    private static let selectedKey="dafeiyu.motionLibrary.pending.v1"
    private static let labelKey="dafeiyu.motionLibrary.classifications.v1"
    private static let importRoot=FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("Library/Application Support/Deepseek-live/motion-library",isDirectory:true)
    private static let importManifest=importRoot.appendingPathComponent("imported-motion-metadata.json")
    // 106 tiny approved JPG references are embedded in the signed .app.
    // Do not require removable-disk TCC access just to browse animation art.
    private var previewRoot:URL {
        (Bundle.main.resourceURL ??
         FileManager.default.homeDirectoryForCurrentUser)
            .appendingPathComponent("motion-previews",isDirectory:true)
    }
    private let sourceRoot=CompanionProjectPaths.motionSourceURL

    private func isOnSD(_ item:MotionEntry)->Bool {
        item.inCurrentPackage || physicallyInstalledNew.contains(item.id)
    }
    private var installedLabel:String {
        physicallyInstalledNew.isEmpty
            ? "SD安装状态待核对"
            : "实体SD回执 \(35+physicallyInstalledNew.count)/106"
    }
    private func loadSDReceipts() {
        let url=Self.importRoot.appendingPathComponent("physical-sd-106.json")
        guard let raw=try? Data(contentsOf:url),raw.count<32000,
              let doc=try? JSONSerialization.jsonObject(with:raw) as? [String:Any],
              doc["schema"] as? Int == 1,
              doc["status"] as? String == "hardware_sha_readback_verified",
              doc["factory35_preserved"] as? Bool == true,
              let count=doc["verified_additional_count"] as? Int,
              count>=0 && count<=71,
              let rows=doc["verified_additional"] as? [[String:Any]],
              rows.count==count else {return}
        let ids=rows.compactMap{row -> String? in
            guard let id=row["id"] as? String,
                  id.range(of:#"^m[0-9]{3}$"#,options:.regularExpression) != nil,
                  let hash=row["sha256"] as? String,hash.count==64,
                  let size=row["bytes"] as? Int,size>500 && size<8_000_000,
                  entries.contains(where:{$0.id==id && !$0.inCurrentPackage})
            else {return nil}
            return id
        }
        guard ids.count==count,Set(ids).count==count else{return}
        physicallyInstalledNew=Set(ids)
    }
    private var filtered:[MotionEntry] {
        entries.filter { item in
            let role=classification(item)
            let inGroup:Bool = switch group {
            case "设备素材": isOnSD(item)
            case "待新增": !isOnSD(item)
            case "待机","工作","互动","彩蛋": role==group
            default: true
            }
            return inGroup && (search.isEmpty
                || item.id.localizedCaseInsensitiveContains(search)
                || item.name.localizedCaseInsensitiveContains(search))
        }
    }
    private var focused:MotionEntry? { entries.first(where:{$0.id==selectedID}) }
    private func scaleAdvisory(_ item:MotionEntry)->MotionScaleResult? {
        scaleChecks[item.id]
    }
    private func scaleAdvisoryLabel(_ item:MotionEntry)->String? {
        guard let info=scaleAdvisory(item) else{return nil}
        switch info.risk {
        case "high":return "角色可能偏小 · 建议检查"
        case "review":return "画幅比例需留意"
        default:return nil
        }
    }
    private func stageCandidate(_ item:MotionEntry) {
        if staged.contains(item.id) {
            staged.remove(item.id)
            writePending()
            return
        }
        if let check=scaleAdvisory(item),check.risk=="high" || check.risk=="review" {
            let alert=NSAlert()
            alert.alertStyle = .informational
            alert.messageText="这段素材可能出现人物偏小"
            alert.informativeText="源动画整幅缩放相对待机为\(Int((check.relativeScaleToIdle*100).rounded()))%。道具、气泡或远距离动作可能拉大裁剪范围。请先看预览，再决定是否入选。\n\n这不是故障判定，继续仅加入Mac待审核清单，不会烧录ESP32。"
            alert.addButton(withTitle:"返回预览")
            alert.addButton(withTitle:"了解，仍加入待审核")
            if alert.runModal() != .alertSecondButtonReturn {return}
        } else if scaleAdvisory(item)==nil {
            let alert=NSAlert()
            alert.messageText="这段素材尚无可靠比例数据"
            alert.informativeText="请先预览人物及场景大小，不能自动判断是否适合ESP32。继续只加入本地待审核清单。"
            alert.addButton(withTitle:"返回预览")
            alert.addButton(withTitle:"了解，仍加入待审核")
            if alert.runModal() != .alertSecondButtonReturn {return}
        }
        staged.insert(item.id)
        writePending()
    }
    private var boardInstallCapable:Bool {
        // Never equate a valid USB session or the historical SD animation
        // package with permission/capability to WRITE new user assets.
        store.bothVerified && store.snapshot?.sd_install_capability_verified == true
    }
    private func classification(_ item:MotionEntry)->String {
        if let value=customLabels[item.id],roles.contains(value){return value}
        switch item.category {
        case "idle": return "待机"
        case "work": return "工作"
        case "reaction":return "互动"
        case "bonus":return "彩蛋"
        default:return "待新增"
        }
    }
    private func trustedFile(_ url:URL,max:Int)->Bool {
        guard let r=try? url.resourceValues(forKeys:[.isRegularFileKey,.isSymbolicLinkKey,.fileSizeKey]),
              r.isRegularFile == true,r.isSymbolicLink != true,let n=r.fileSize else{return false}
        return n>500 && n<max
    }
    private func preview(_ item:MotionEntry)->NSImage? {
        guard item.id.range(of:#"^m[0-9]{3}$"#,options:.regularExpression) != nil,
              item.previewName==item.id+".jpg" else {return nil}
        let file=previewRoot.appendingPathComponent(item.previewName)
        guard trustedFile(file,max:4_000_000) else{return nil}
        return NSImage(contentsOf:file)
    }
    private func loadLibrary(){
        defer{loaded=true}
        guard let uri=Bundle.main.url(forResource:"motion-catalog",withExtension:"json"),
              let info=try? uri.resourceValues(forKeys:[.isRegularFileKey,.isSymbolicLinkKey]),
              info.isRegularFile == true,info.isSymbolicLink != true,
              let raw=try? Data(contentsOf:uri),raw.count<100_000,
              let catalog=try? JSONDecoder().decode(MotionLibraryCatalog.self,from:raw),
              catalog.schema==1,catalog.count>0,
              catalog.count==catalog.motions.count,
              catalog.selectedCount>0,
              catalog.selectedCount==catalog.motions.filter({ $0.inCurrentPackage }).count,
              Set(catalog.motions.map(\.id)).count==catalog.count
        else { feedback="本机动画清单不可用，请重新构建 Mac App";return }
        entries=catalog.motions
        loadSDReceipts()
        // Static advisory metadata comes from verified local WebM alpha;
        // it is never a claim that the ESP32 is displaying these pixels.
        if let uri=Bundle.main.url(forResource:"motion-scale-advisory",withExtension:"json"),
           let raw=try? Data(contentsOf:uri),raw.count<75_000,
           let check=try? JSONDecoder().decode(MotionScaleCatalog.self,from:raw),
           check.schema==1,check.kind=="advisory_not_firmware_validation",
           check.count==catalog.count,check.motions.count==catalog.count,
           Set(check.motions.map(\.id))==Set(catalog.motions.map(\.id)),
           check.motions.allSatisfy({["normal","review","high"].contains($0.risk)
                 && $0.relativeScaleToIdle>0.1 && $0.relativeScaleToIdle<4.5
                 && $0.framesMeasured>0 && $0.framesMeasured<=100}) {
            scaleChecks=Dictionary(uniqueKeysWithValues:check.motions.map{($0.id,$0)})
        }
        if let data=try? Data(contentsOf:Self.importManifest),data.count<200_000,
           let imported=try? JSONDecoder().decode([MotionEntry].self,from:data) {
            entries.append(contentsOf:imported.filter { candidate in
                candidate.id.hasPrefix("u") && candidate.id.count==13
                && !candidate.inCurrentPackage && candidate.previewName.isEmpty
            })
        }
        let permitted=Set(entries.filter{ !$0.inCurrentPackage }.map(\.id))
        staged=Set((UserDefaults.standard.stringArray(forKey:Self.selectedKey) ?? []).filter{permitted.contains($0)})
        customLabels=(UserDefaults.standard.dictionary(forKey:Self.labelKey) as? [String:String]) ?? [:]
        if !entries.contains(where:{$0.id==selectedID}){selectedID=entries[0].id}
    }
    private func writePending(){
        UserDefaults.standard.set(staged.sorted(),forKey:Self.selectedKey)
    }
    private func changeRole(_ label:String){
        guard let item=focused,roles.contains(label) else{return}
        customLabels[item.id]=label
        UserDefaults.standard.set(customLabels,forKey:Self.labelKey)
    }
    private func importLocalMotion(){
        let picker=NSOpenPanel()
        picker.title="导入候选动画（保留在Mac，暂不写入ESP32）"
        picker.allowedContentTypes=[.movie,.gif]
        picker.allowsMultipleSelection=false
        picker.canChooseDirectories=false
        guard picker.runModal() == .OK, let source=picker.url else{return}
        let ext=source.pathExtension.lowercased()
        guard ["gif","mp4","mov","webm"].contains(ext),
              trustedFile(source,max:30_000_000) else {
            feedback="仅支持不超过30MB的 GIF、MP4、MOV、WebM 常规文件。"
            return
        }
        let id="u"+String(UUID().uuidString.replacingOccurrences(of:"-",with:"").prefix(12)).lowercased()
        let dir=Self.importRoot.appendingPathComponent("imports",isDirectory:true)
        let file=dir.appendingPathComponent(id+"."+ext)
        let entry=MotionEntry(id:id,name:String(source.deletingPathExtension().lastPathComponent.prefix(64)),
                              category:"custom",inCurrentPackage:false,
                              previewName:"",framesName:"")
        do {
            try FileManager.default.createDirectory(at:dir,withIntermediateDirectories:true)
            try FileManager.default.copyItem(at:source,to:file)
            try FileManager.default.setAttributes([.posixPermissions:0o600],ofItemAtPath:file.path)
            let all=entries.filter{$0.id.hasPrefix("u")}+[entry]
            let data=try JSONEncoder().encode(all)
            try data.write(to:Self.importManifest,options:.atomic)
            try FileManager.default.setAttributes([.posixPermissions:0o600],ofItemAtPath:Self.importManifest.path)
            entries.append(entry)
            staged.insert(id)
            writePending()
            selectedID=id
            feedback="已导入本地候选并加入待审核清单。尚需转换为设备DFS格式。"
        } catch { feedback="本地素材导入失败。"}
    }
    private func localCandidateURL(_ id:String)->URL? {
        guard id.range(of:#"^u[a-f0-9]{12}$"#,options:.regularExpression) != nil else {return nil}
        let file=Self.importRoot.appendingPathComponent("candidates").appendingPathComponent(id+".DFS")
        return trustedFile(file,max:8_000_000) ? file : nil
    }
    private func compileCandidate(_ item:MotionEntry) {
        guard item.id.range(of:#"^u[a-f0-9]{12}$"#,options:.regularExpression) != nil,
              !isEncoding,localCandidateURL(item.id)==nil else{return}
        let ident=item.id
        let runner=CompanionProjectPaths.script("companion_cli.py")
        let executable=CompanionProjectPaths.idfPython
        guard FileManager.default.isExecutableFile(atPath:executable),
              FileManager.default.fileExists(atPath:runner) else {
            feedback="转换器尚未安装到本机；请检查项目工作目录。"
            return
        }
        isEncoding=true
        feedback="正在离线压缩 240×240 / 8fps 动画，设备保持未连接…"
        DispatchQueue.global(qos:.userInitiated).async {
            let worker=Process()
            worker.executableURL=URL(fileURLWithPath:executable)
            worker.currentDirectoryURL=CompanionProjectPaths.rootURL
            worker.arguments=["-m","scripts.companion_cli","motion-prepare","--id",ident,"--level","6","--mode","contain"]
            let pipe=Pipe()
            worker.standardOutput=pipe
            worker.standardError=Pipe()
            var detail="压缩失败，请检查素材格式或64KB帧上限。"
            do {
                try worker.run()
                // Output is small, bounded JSON; wait for the exact process
                // and never launch a shell or USB transfer.
                worker.waitUntilExit()
                let data=pipe.fileHandleForReading.readDataToEndOfFile()
                if worker.terminationStatus==0,
                   let raw=try? JSONSerialization.jsonObject(with:data) as? [String:Any],
                   let bytes=raw["bytes"] as? Int,
                   let verified=raw["verified"] as? Bool,verified {
                    detail="已生成经SHA校验的设备候选（\(bytes)字节）。尚未烧录。"
                }
            }catch {
                detail="离线转换进程启动失败。"
            }
            DispatchQueue.main.async {
                self.isEncoding=false
                self.feedback=detail
            }
        }
    }
    private func physicalInstall(_ item:MotionEntry){
        guard !isInstalling && !isCheckingInstall && !isEncoding &&
              boardInstallCapable && staged.contains(item.id) && item.id.hasPrefix("u") &&
              localCandidateURL(item.id) != nil else { return }
        let prompt=NSAlert()
        prompt.messageText="烧录设备用户动画（需本人现场确认）"
        prompt.informativeText="只有通过实体验收、支持DFSD3的固件才可执行。将暂停Mac语音串口，在30秒内要求你点按ESP32上大肥鱼确认，最终写后读取SD原始文件SHA-256。不覆盖任何已安装的原版素材；若设备未返回当前 DFSD3 实体授权与读回回执则立即拒绝。"
        prompt.alertStyle = .warning
        prompt.addButton(withTitle:"取消")
        prompt.addButton(withTitle:"我在设备旁，确认开始")
        if prompt.runModal() != .alertSecondButtonReturn {return}
        exportPlan(showInFinder:false)
        let runner=CompanionProjectPaths.script("companion_cli.py")
        let executable=CompanionProjectPaths.idfPython
        guard FileManager.default.isExecutableFile(atPath:executable),
              FileManager.default.fileExists(atPath:runner) else {
            feedback="设备烧录工具未安装，未执行。"
            return
        }
        let devices=(try? FileManager.default.contentsOfDirectory(atPath:"/dev")
            .filter{$0.hasPrefix("cu.usbmodem")}.sorted()) ?? []
        guard devices.count==1 else {
            feedback="USB设备不唯一或不在线，已拒绝烧录。"
            return
        }
        let port="/dev/"+devices[0]
        let ident=item.id
        isInstalling=true
        feedback="等待真实设备的本地确认和写卡回执；已安装的原版动画均保持不变…"
        DispatchQueue.global(qos:.userInitiated).async {
            let proc=Process()
            proc.executableURL=URL(fileURLWithPath:executable)
            proc.currentDirectoryURL=CompanionProjectPaths.rootURL
            proc.arguments=["-m","scripts.companion_cli","motion-install","--id",ident,"--port",port,
                "--confirm-physical-tap","--approve-user-slot-write",
                "--manage-voice-agent"]
            let standard=Pipe()
            proc.standardOutput=standard
            proc.standardError=Pipe()
            var info="真实安装失败或已拒绝；请在设备现场核查，新动画不能视为已安装。"
            do{
                try proc.run()
                proc.waitUntilExit()
                let raw=standard.fileHandleForReading.readDataToEndOfFile()
                if let result=try? JSONSerialization.jsonObject(with:raw) as? [String:Any] {
                    if proc.terminationStatus==0,
                       result["sd_readback_verified"] as? Bool == true,
                       result["device_playback_first_frame_verified"] as? Bool == true,
                       let slot=result["slot"] as? String {
                        info="设备\(slot) 的 SD SHA256 读回及实际播放首帧均通过。"
                    }else if proc.terminationStatus==0,
                              result["sd_readback_verified"] as? Bool == true,
                              let slot=result["slot"] as? String {
                        info="设备\(slot) SD 写入/读回已核实，但播放首帧未验收，请勿标记为可用。"
                    }else if let error=result["error"] as? String {
                        info="烧录未完成（\(String(error.prefix(95)))）。"
                    }
                }
            }catch{info="串口安装程序无法启动；本机候选保留。"}
            DispatchQueue.main.async{
                self.isInstalling=false
                self.feedback=info
            }
        }
    }
    private func dryRunInstall() {
        // This checks the entire staged USB protocol against a volatile RAM
        // simulator. It neither opens a serial port nor writes the TF card.
        guard !isCheckingInstall && !isEncoding && !staged.isEmpty else { return }
        exportPlan(showInFinder:false)
        let executable=CompanionProjectPaths.idfPython
        let script=CompanionProjectPaths.script("companion_cli.py")
        guard FileManager.default.isExecutableFile(atPath:executable),
              FileManager.default.fileExists(atPath:script) else {
            feedback="本机烧录通道工具未安装。"
            return
        }
        isCheckingInstall=true
        feedback="正在模拟分块传输、SHA-256提交与SD读回；USB不会打开…"
        DispatchQueue.global(qos:.userInitiated).async {
            let proc=Process()
            proc.executableURL=URL(fileURLWithPath:executable)
            proc.currentDirectoryURL=CompanionProjectPaths.rootURL
            proc.arguments=["-m","scripts.companion_cli","motion-check"]
            let pipe=Pipe()
            proc.standardOutput=pipe
            proc.standardError=Pipe()
            var outcome="离线校验失败。请确认所选素材已压缩、用途已分类，且不超过8项。"
            do {
                try proc.run()
                proc.waitUntilExit()
                let data=pipe.fileHandleForReading.readDataToEndOfFile()
                if proc.terminationStatus==0,
                   let result=try? JSONSerialization.jsonObject(with:data) as? [String:Any],
                   result["physical_esp32_written"] as? Bool == false,
                   result["simulator_verified"] as? Bool == true,
                   let n=result["tested"] as? Int {
                    outcome="离线模拟通过：\(n)项，逐包ACK与回读SHA全部一致。真实设备写入仍须支持DFSD3的固件及本人点按。"
                }
            }catch {
                outcome="烧录通道模拟程序未能启动，现有素材保持不变。"
            }
            DispatchQueue.main.async {
                self.isCheckingInstall=false
                self.feedback=outcome
            }
        }
    }
    private func exportInstallPlan(){
        // Stage current UserDefaults classifications before the Python-only
        // integrity planner reads them. No device is touched.
        exportPlan(showInFinder:false)
        let executable=CompanionProjectPaths.idfPython
        guard !isEncoding,FileManager.default.isExecutableFile(atPath:executable) else{return}
        let proc=Process()
        proc.executableURL=URL(fileURLWithPath:executable)
        proc.currentDirectoryURL=CompanionProjectPaths.rootURL
        proc.arguments=["-m","scripts.companion_cli","motion-plan","--save"]
        proc.standardOutput=Pipe()
        proc.standardError=Pipe()
        do{
            try proc.run();proc.waitUntilExit()
            if proc.terminationStatus==0 {
                feedback="已生成本地同步提案；设备允许列表和写后读取仍需新固件，未接入USB。"
                let folder=Self.importRoot
                NSWorkspace.shared.open(folder)
            }else {
                feedback="同步计划未生成，可能已经存在同名提案或候选校验失败。"
            }
        }catch {feedback="同步计划工具暂不可用。"}
    }
    private func exportPlan(showInFinder:Bool=true){
        // Export only names/categories, never private 3rd-party media,
        // firmware, device tokens, Wi-Fi passwords, or serial instructions.
        let planned=entries.filter{staged.contains($0.id)}.map{
            ["id":$0.id,"name":$0.name,"category":classification($0)]
        }
        let risk=entries.filter{staged.contains($0.id)}.compactMap{item -> [String:Any]? in
            guard let info=scaleAdvisory(item),
                  info.risk=="high" || info.risk=="review" else {return nil}
            return ["id":item.id,"risk":info.risk,
                    "relativeScaleToIdle":info.relativeScaleToIdle]
        }
        let unmeasured=entries.filter{staged.contains($0.id) && scaleAdvisory($0)==nil}.map(\.id)
        let payload:[String:Any]=["schema":1,"status":"pending_review_not_on_device",
                                  "count":planned.count,"motions":planned,
                                  "scaleAdvisory":[
                                      "warningCount":risk.count,
                                      "warnings":risk,
                                      "unmeasuredIDs":unmeasured,
                                      "advisoryOnly":true]]
        let folder=FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/Deepseek-live/motion-library",isDirectory:true)
        let file=folder.appendingPathComponent("pending-motion-plan.json")
        do {
            try FileManager.default.createDirectory(at:folder,withIntermediateDirectories:true)
            let data=try JSONSerialization.data(withJSONObject:payload,options:[.prettyPrinted,.sortedKeys])
            try data.write(to:file,options:.atomic)
            try FileManager.default.setAttributes([.posixPermissions:0o600],ofItemAtPath:file.path)
            feedback="已保存待审核清单（\(planned.count) 项）。尚未写入 ESP32。"
            if showInFinder { NSWorkspace.shared.activateFileViewerSelecting([file]) }
        } catch { feedback="写入清单失败，请检查本机目录权限。" }
    }

    var body:some View {
        VStack(alignment:.leading,spacing:12){
            if !embedded {
                HStack(spacing:9){
                    Image(systemName:"square.stack.3d.up").foregroundStyle(.blue)
                    Text("大肥鱼 · 动画素材库").font(.system(size:19,weight:.semibold))
                    Spacer()
                    Button("关闭"){dismiss()}
                }
            }
            HStack(spacing:14) {
                Label("总计 \(entries.count)",systemImage:"square.grid.2x2")
                Label(installedLabel,systemImage:"checkmark.circle")
                Label("待同步 \(staged.count)",systemImage:"tray.and.arrow.down")
                Spacer()
                Text(store.espVerified ? "USB已验证" : "USB暂未核验")
                    .foregroundStyle(store.espVerified ? .green : .secondary)
            }
            .font(.system(size:12,weight:.medium))
            .padding(.horizontal,14).padding(.vertical,11)
            .background(Color.accentColor.opacity(0.06),in:RoundedRectangle(cornerRadius:10))
            if !embedded {
                Text("本地预览与安装到SD是两回事；新素材写入需要设备现场确认。")
                    .font(.system(size:11)).foregroundStyle(.secondary)
            }
            HStack {
                TextField("搜索动画名称或编号",text:$search).textFieldStyle(.roundedBorder)
                Picker("分类",selection:$group){
                    ForEach(groups,id:\.self){Text($0).tag($0)}
                }.frame(width:165)
            }
            HStack(spacing:14) {
                List(selection:$selectedID){
                    ForEach(filtered){item in
                        HStack(spacing:12){
                            if let image=preview(item){
                                Image(nsImage:image).resizable().scaledToFit()
                                    .frame(width:56,height:56).clipShape(RoundedRectangle(cornerRadius:8))
                            } else {
                                Image(systemName:"photo").frame(width:56,height:56)
                            }
                            VStack(alignment:.leading,spacing:3) {
                                Text(item.name).font(.system(size:13,weight:.medium)).lineLimit(2)
                                Text(item.id+" · "+classification(item))
                                    .foregroundStyle(.secondary).font(.system(size:11))
                                Text(item.inCurrentPackage ? "设备包保底 · 非实时读回" :
                                     physicallyInstalledNew.contains(item.id) ? "SD安装有历史校验回执" :
                                     staged.contains(item.id) ? "本机待审核" : "尚未安装")
                                    .font(.system(size:11)).foregroundStyle(.secondary)
                                if let advisory=scaleAdvisoryLabel(item) {
                                    Label(advisory,systemImage:"exclamationmark.triangle")
                                        .font(.system(size:11))
                                        .foregroundStyle(.orange)
                                }
                            }
                            Spacer(minLength:0)
                        }.padding(.vertical,4).tag(item.id)
                    }
                }
                .scrollContentBackground(.hidden)
                .background(Color.primary.opacity(0.035),in:RoundedRectangle(cornerRadius:12))
                .clipShape(RoundedRectangle(cornerRadius:12))
                .frame(minWidth:embedded ? 290 : 285,
                         maxWidth:embedded ? .infinity : nil,
                         minHeight:360,maxHeight:embedded ? .infinity : nil)
                ScrollView {
                VStack(alignment:.leading,spacing:11){
                    if let item=focused {
                        Text(item.name).font(.system(size:18,weight:.semibold))
                        Text(item.id).font(.system(.caption,design:.monospaced)).foregroundStyle(.secondary)
                        if let gif=store.motionFile(for:item.id) {
                            PrivateMotionPlayer(url:gif)
                                .frame(width:embedded ? 250 : 220,
                                       height:embedded ? 250 : 208)
                                .clipShape(RoundedRectangle(cornerRadius:12))
                                .frame(maxWidth:.infinity)
                        } else if let image=preview(item) {
                            Image(nsImage:image).resizable().scaledToFit()
                                .frame(width:220,height:208).background(.quaternary.opacity(0.3),
                                    in:RoundedRectangle(cornerRadius:12))
                        } else if item.id.hasPrefix("u") {
                            VStack(spacing:7){
                                Label(localCandidateURL(item.id) == nil ?
                                      "自定义素材 · 待压缩" : "候选素材 · 压缩及校验完成",
                                      systemImage:"film")
                                Text("240×240 · 8fps · DFSP").font(.system(size:11))
                            }.frame(width:220,height:208)
                        } else {
                            ContentUnavailableView("预览文件尚未就绪",systemImage:"photo")
                                .frame(width:220,height:208)
                        }
                        if let measure=scaleAdvisory(item) {
                            VStack(alignment:.leading,spacing:4) {
                                if let advisory=scaleAdvisoryLabel(item) {
                                    Label(advisory,systemImage:"exclamationmark.triangle.fill")
                                        .font(.system(size:11,weight:.semibold))
                                        .foregroundStyle(.orange)
                                } else {
                                    Label("未发现明显整体缩小风险",systemImage:"checkmark.circle")
                                        .font(.system(size:11))
                                        .foregroundStyle(.secondary)
                                }
                                Text("整幅源素材相对待机缩放约\(Int((measure.relativeScaleToIdle*100).rounded()))% · 约\(measure.framesMeasured)帧抽检")
                                    .font(.system(size:11,weight:.medium))
                                Text("道具、气泡、特效可能使人物显小；这是裁剪比例建议，不是人物实际身高，也不代表实体屏幕已验收。")
                                    .font(.system(size:11)).foregroundStyle(.secondary)
                                    .fixedSize(horizontal:false,vertical:true)
                            }
                            .padding(9)
                            .frame(maxWidth:.infinity,alignment:.leading)
                            .background(Color.orange.opacity(measure.risk=="normal" ? 0.04 : 0.09),
                                        in:RoundedRectangle(cornerRadius:9))
                        } else {
                            Label("未检查比例 · 建议先预览画面",systemImage:"info.circle")
                                .font(.system(size:10)).foregroundStyle(.secondary)
                        }
                        Text("用途分类仅改变Mac目录标签，不会修改ESP32触发条件。")
                            .font(.system(size:11)).foregroundStyle(.secondary)
                        Picker("用途分类",selection:Binding(
                            get:{classification(item)},
                            set:{changeRole($0)})){
                            ForEach(roles,id:\.self){Text($0).tag($0)}
                        }.frame(width:240)
                        if item.inCurrentPackage {
                            Label("当前设备包的受保护动画 · 并非逐文件实时读卡证明",
                                  systemImage:"checkmark.seal")
                                .font(.system(size:11)).foregroundStyle(.secondary)
                                .fixedSize(horizontal:false,vertical:true)
                            Button("查看本机已选DFS"){
                                let f=sourceRoot.appendingPathComponent(item.framesName)
                                if trustedFile(f,max:7_000_000) {
                                    NSWorkspace.shared.activateFileViewerSelecting([f])
                                }else{feedback="此项本地DFS文件未找到或未验证。"}
                            }
                        } else if physicallyInstalledNew.contains(item.id) {
                            Label("实体SD已验证 · 可编辑触发规则",
                                  systemImage:"checkmark.seal")
                                .font(.system(size:11))
                                .foregroundStyle(.secondary)
                        } else {
                            if item.id.hasPrefix("u") {
                                if let file=localCandidateURL(item.id) {
                                    Button("查看压缩后的 DFS 文件"){
                                        NSWorkspace.shared.activateFileViewerSelecting([file])
                                    }
                                }else{
                                    Button(isEncoding ? "正在压缩…" : "压缩转换为设备格式"){
                                        compileCandidate(item)
                                    }.disabled(isEncoding)
                                }
                            }
                            Button(staged.contains(item.id) ? "从待同步清单移除" : "加入待同步清单"){
                                stageCandidate(item)
                            }.buttonStyle(.borderedProminent)
                            if item.id.hasPrefix("u") {
                                Button(isInstalling ? "正在安装…" :
                                        (boardInstallCapable ? "安装到ESP32（需板上确认）" : "设备安装未开放")){
                                    physicalInstall(item)
                                }
                                .disabled(isInstalling || isEncoding || isCheckingInstall ||
                                    !boardInstallCapable || !staged.contains(item.id) || localCandidateURL(item.id)==nil)
                                .help("新增本机素材要先经过板上协议/SD校验，不修改已安装动作")
                            }
                        }
                        Spacer()
                    } else { Text("请选择动画") ;Spacer() }
                }
                .padding(16)
                .frame(minWidth:260,maxWidth:embedded ? .infinity : 260,
                       maxHeight:embedded ? .infinity : nil,alignment:.leading)
                }
                .frame(minWidth:260,maxWidth:embedded ? .infinity : 260,
                       maxHeight:embedded ? .infinity : nil,alignment:.topLeading)
                .background(Color.primary.opacity(0.035),in:RoundedRectangle(cornerRadius:12))
            }
            .frame(maxHeight:embedded ? .infinity : nil)
            if embedded {
                HStack(spacing:10) {
                    Button("导入动画…"){importLocalMotion()}
                    Button("编辑触发规则"){openRules?()}
                        .buttonStyle(.borderedProminent)
                    Spacer()
                    Menu("更多操作") {
                        Button("打开素材目录") {
                            if FileManager.default.fileExists(atPath:previewRoot.path) {
                                NSWorkspace.shared.open(previewRoot)
                            } else { feedback="素材目录不存在" }
                        }
                        Button("导出待安装清单"){exportPlan()}
                            .disabled(staged.isEmpty)
                        Button("模拟安装校验"){dryRunInstall()}
                            .disabled(isCheckingInstall || isEncoding || staged.isEmpty)
                        Button("生成离线安装方案"){exportInstallPlan()}
                            .disabled(isEncoding || staged.isEmpty)
                    }
                }
            } else {
            VStack(alignment:.leading,spacing:8) {
                HStack(spacing:9) {
                    Button("设备动画触发规则 / 解除绑定…"){showTriggers=true}
                        .help("审阅已保存提案、修改触发分组、申请本人实体点击授权；不会修改SD文件")
                    Button("导入动画…"){importLocalMotion()}
                    Button("打开素材目录"){
                        if FileManager.default.fileExists(atPath:previewRoot.path){
                            NSWorkspace.shared.open(previewRoot)
                        } else { feedback="本地原始素材目录暂不存在" }
                    }
                    Spacer()
                    Button("导出待安装清单"){exportPlan()}
                        .disabled(staged.isEmpty)
                }
                HStack(spacing:9) {
                    Button(isCheckingInstall ? "正在模拟…" : "模拟安装校验"){
                        dryRunInstall()
                    }
                    .disabled(isCheckingInstall || isEncoding || staged.isEmpty)
                    .help("只模拟USB分块和SHA读回，不接触ESP32")
                    Button("生成离线安装方案"){exportInstallPlan()}
                        .help("本地生成候选设备编号、校验信息和未来安装条件；不会写入SD卡")
                        .disabled(isEncoding || staged.isEmpty)
                    Spacer()
                    Text("目录浏览和待审核清单不会修改设备")
                        .font(.system(size:11)).foregroundStyle(.secondary)
                }
            }
            }
            if !embedded {
                Text(boardInstallCapable
                     ? "安装需本人在设备旁确认并校验SHA。"
                     : "设备写卡能力未验证，浏览预览不会修改SD。")
                    .font(.system(size:10)).foregroundStyle(.secondary)
            }
            if !feedback.isEmpty {
                Text(feedback).font(.system(size:11)).foregroundStyle(.secondary)
            }
        }
        .padding(embedded ? 16 : 20)
        .frame(width:embedded ? nil : 760,
               height:embedded ? nil : 740)
        .frame(maxWidth:embedded ? .infinity : nil,
               maxHeight:embedded ? .infinity : nil,alignment:.topLeading)
        .background(Color(nsColor: .windowBackgroundColor))
        .sheet(isPresented:$showTriggers){MotionTriggers106Sheet(store:store,onClose:{showTriggers=false})}
        .onAppear {
            if !loaded {loadLibrary()}
            if let id=sharedSelection?.wrappedValue,
               id.range(of:#"^m[0-9]{3}$"#,options:.regularExpression) != nil {
                selectedID=id
            }
        }
        .onChange(of:selectedID){_,id in
            sharedSelection?.wrappedValue=id
        }
    }
}
