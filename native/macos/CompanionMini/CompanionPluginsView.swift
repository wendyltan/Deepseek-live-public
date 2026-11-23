// SPDX-License-Identifier: MIT
// R689 production plugin lifecycle: read-only companion inventory, optional
// bundles separated from runtime components, and links into the exact official
// DSH manager for activation/removal. Actual package operations and prompts
// Package lifecycle is handled by the official manager for this profile.
import AppKit
import SwiftUI
import WebKit

// R674: official DSH's real plugin installer, not a recreated npm frontend.
// The one-use local login URL is obtained from an owner-private helper and
// consumed only inside this window. Never place it in logs or regular URLs.
private struct LocalDSHMarketWeb: NSViewRepresentable {
    let localURL:URL
    func makeCoordinator() -> Coordinator { Coordinator() }
    func makeNSView(context:Context) -> WKWebView {
        let view=WKWebView(frame:.zero)
        view.navigationDelegate=context.coordinator
        view.load(URLRequest(url:localURL))
        return view
    }
    func updateNSView(_ view:WKWebView,context:Context) {}
    final class Coordinator:NSObject,WKNavigationDelegate {
        func webView(_ webView:WKWebView,
                     decidePolicyFor action:WKNavigationAction,
                     decisionHandler:@escaping (WKNavigationActionPolicy)->Void) {
            guard let url=action.request.url else {
                decisionHandler(.cancel);return
            }
            // Only the local, user-owned DSH Host can be an embedded page.
            if url.scheme=="http" && url.host=="127.0.0.1" && url.port==3080 {
                decisionHandler(.allow)
            } else {
                if action.navigationType == .linkActivated && url.scheme=="https" {
                    NSWorkspace.shared.open(url)
                }
                decisionHandler(.cancel)
            }
        }
    }
}

private struct R674MarketAccess:Decodable {
    let ok:Bool
    let url:String
}
private struct PluginPackage: Codable, Identifiable {
    let name:String
    let requested_spec:String
    let version:String?
    let installed:Bool
    let is_bundle:Bool
    let enabled_bundle:Bool
    let protected:Bool
    var id:String { name }
}
private struct PluginTool: Codable, Identifiable {
    let name:String
    let declared:Bool
    let protected:Bool
    var id:String { name }
}
private struct PluginInventory: Codable {
    let schema:Int
    let scope:String
    let host_port:Int
    let bundle_count:Int
    let declared_package_count:Int
    let packages:[PluginPackage]
    let essential_tools:[PluginTool]
}
private struct PluginMarketEntry: Codable, Identifiable {
    let id:String
    let title:String
    let version:String
    let source:String
    let scope:String
    let description:String
    let compatibility:String
    let declared_locally:Bool
    let published_version_verified_online:Bool
    let homepage:String?
}
private struct PluginCatalog: Codable {
    let schema:Int
    let scope:String
    let catalog_type:String
    let count:Int
    let items:[PluginMarketEntry]
    let online_checked:Bool
    let total_matches:Int?
    let index_url:String?
}
private enum PluginBrowserTab:String,CaseIterable {
    case installed="已安装"
    case market="插件市场"
}
struct CompanionPluginsView:View {
    @AppStorage("r659CompanionProjectRoot") private var projectRoot:String=""
    @AppStorage("r659CompanionDSHHome") private var dshHome:String=""
    @AppStorage("r659CompanionPython") private var pythonExecutable:String=""
    @State private var showInactivePackages=false
    @State private var showSystemDetails=false
    @State private var inventory:PluginInventory?=nil
    @State private var catalog:PluginCatalog?=nil
    @State private var selected:PluginBrowserTab = .installed
    @State private var search:String=""
    @State private var busy=false
    @State private var notice:String=""
    @State private var showConfiguration=false
    @State private var showOfficialMarket=false
    @State private var authorizedOfficialURL:URL?=nil
    // R672: the shipped official manager owns actual package installation.
    // The third-party index displayed below stays discovery-only.
    private let officialMarketBundle="@deepseek-ai/dsh-experimental-plugin-market-bundle"
    private var officialMarketEnabled:Bool {
        inventory?.packages.first(where:{$0.name==officialMarketBundle})?.enabled_bundle == true
    }
    // Only real optional Bundles are user-manageable. Computer Use and CUA
    // are dependencies of the protected runtime, not optional plugin cards.
    private func optionalBundle(_ pkg:PluginPackage)->Bool {
        !pkg.protected && pkg.name != officialMarketBundle
            && pkg.name != "@deepseek-ai/dsh-computer-use"
            && pkg.name != "@deepseek-ai/dsh-experimental-cua-macos"
            && pkg.installed && pkg.is_bundle
    }
    private var activeOptionalBundles:[PluginPackage] {
        (inventory?.packages ?? []).filter {
            optionalBundle($0) && $0.enabled_bundle
        }
    }
    private var inactiveOptionalBundles:[PluginPackage] {
        (inventory?.packages ?? []).filter {
            optionalBundle($0) && !$0.enabled_bundle
        }
    }
    private func pluginRow(_ pkg:PluginPackage)->some View {
        HStack(spacing:10) {
            Image(systemName:pkg.enabled_bundle ? "checkmark.circle.fill":"circle")
                .foregroundStyle(pkg.enabled_bundle ? .green : .secondary)
            VStack(alignment:.leading,spacing:2) {
                Text(pkg.name).font(.subheadline)
                Text("\(pkg.version ?? "未知版本") · \(pkg.enabled_bundle ? "已启用" : "已停用")")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }.padding(.vertical,5)
    }

    private var effectiveRoot:String {
        // Uses the same installation/user-selected source directory as every
        // other Mac App section; no author-specific ExtSSD path.
        return CompanionProjectPaths.rootURL.path
    }
    private var effectiveHome:String {
        if !dshHome.isEmpty{return (dshHome as NSString).expandingTildeInPath}
        if let envHome=ProcessInfo.processInfo.environment["DAFEIYU_HOME"], !envHome.isEmpty {
            return (envHome as NSString).expandingTildeInPath
        }
        let library=FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/Deepseek-live")
        for folder in ["dsh-home-production-r645", "my-companion", "companion-public"] {
            let candidate=library.appendingPathComponent(folder)
            if FileManager.default.fileExists(
                atPath:candidate.appendingPathComponent("profiles/web/package.json").path) {
                return candidate.path
            }
        }
        return library.appendingPathComponent("my-companion").path
    }
    private var effectivePython:String {
        if !pythonExecutable.isEmpty{return pythonExecutable}
        if let fromEnv=ProcessInfo.processInfo.environment["DAFEIYU_PYTHON"] {
            return fromEnv
        }
        return "/opt/homebrew/bin/python3.12"
    }

    // This never runs on the UI thread. The Python backend can only read the
    // specific user's Deepseek-live companion HOME and curated local catalog.
    private nonisolated static func invoke(
        python:String,root:String,home:String,extra:[String],
        source:String="r659_plugin_manager.py") throws -> Data {
        guard ["r659_plugin_manager.py",
               "r674_local_market_access.py"].contains(source) else {
            throw NSError(domain:"companion-plugin-script",code:2,
                          userInfo:[NSLocalizedDescriptionKey:"未认可的插件管理脚本"])
        }
        let file=URL(fileURLWithPath:root)
            .appendingPathComponent("scripts").appendingPathComponent(source)
        guard FileManager.default.fileExists(atPath:file.path),
              FileManager.default.fileExists(atPath:python)
        else { throw NSError(domain:"companion-plugin-config",code:2,
                             userInfo:[NSLocalizedDescriptionKey:"请先配置项目目录与 Python 3.12"]) }
        let proc=Process()
        proc.executableURL=URL(fileURLWithPath:python)
        // Python invoked with an absolute script path does not reliably put
        // the repository root on sys.path. All three backends are modules.
        let module="scripts."+source.replacingOccurrences(of:".py",with:"")
        proc.arguments=["-m",module]+extra+["--dsh-home",home]
        proc.currentDirectoryURL=URL(fileURLWithPath:root)

        // A child may produce >64KB of pnpm errors. Waiting before draining
        // both Pipes can deadlock. Use private temporary output files instead.
        let fm=FileManager.default
        let dir=fm.temporaryDirectory.appendingPathComponent(
            "dafeiyu-plugins-"+UUID().uuidString,isDirectory:true)
        try fm.createDirectory(at:dir,withIntermediateDirectories:false,
                               attributes:[.posixPermissions:0o700])
        defer {try? fm.removeItem(at:dir)}
        let stdout=dir.appendingPathComponent("stdout")
        let stderr=dir.appendingPathComponent("stderr")
        guard fm.createFile(atPath:stdout.path,contents:nil,
                            attributes:[.posixPermissions:0o600]),
              fm.createFile(atPath:stderr.path,contents:nil,
                            attributes:[.posixPermissions:0o600])
        else {throw NSError(domain:"companion-plugin-tempfile",code:3)}
        let outHandle=try FileHandle(forWritingTo:stdout)
        let errHandle=try FileHandle(forWritingTo:stderr)
        proc.standardOutput=outHandle
        proc.standardError=errHandle
        defer {try? outHandle.close();try? errHandle.close()}
        try proc.run()
        proc.waitUntilExit()
        try outHandle.synchronize()
        try errHandle.synchronize()
        let outSize=(try fm.attributesOfItem(atPath:stdout.path)[.size] as? NSNumber)?
            .intValue ?? 0
        guard proc.terminationStatus==0,outSize>0,outSize<=131072 else {
            let data=(try? Data(contentsOf:stderr)) ?? Data()
            let message=String(data:data.prefix(512),encoding:.utf8)
                ?? "后端返回错误或输出超过限制"
            throw NSError(domain:"companion-plugin-command",code:Int(proc.terminationStatus),
                          userInfo:[NSLocalizedDescriptionKey:message])
        }
        return try Data(contentsOf:stdout)
    }
    private func load(preserveNotice:Bool=false) {
        guard !busy else {return}
        busy=true
        if !preserveNotice {notice=""}
        let python=effectivePython,root=effectiveRoot,home=effectiveHome
        let tab=selected,query=search
        if tab == .market {catalog=nil}
        Task {
            let response=await Task.detached(priority:.utility) {
                Result {
                    try Self.invoke(python:python,root:root,home:home,
                                    extra:tab == .installed
                                        ? ["status"]
                                        : ["discover","--query",query])
                }
            }.value
            switch response {
            case .success(let data):
                do {
                    if tab == .installed {
                        inventory=try JSONDecoder().decode(PluginInventory.self,from:data)
                    } else {
                        catalog=try JSONDecoder().decode(PluginCatalog.self,from:data)
                    }
                } catch {notice="插件数据解析失败：\(error.localizedDescription)"}
            case .failure(let error):notice=error.localizedDescription
            }
            busy=false
        }
    }
    private func lookupOnline() {
        guard !busy else {return}
        busy=true
        let python=effectivePython,root=effectiveRoot,home=effectiveHome,query=search
        catalog=nil // Offline must not masquerade as live remote data.
        Task {
            let response=await Task.detached(priority:.utility) {
                Result {
                    try Self.invoke(python:python,root:root,home:home,
                                    extra:["discover","--query",query])
                }
            }.value
            if case .success(let data)=response {
                do {catalog=try JSONDecoder().decode(PluginCatalog.self,from:data)}
                catch {notice="市场版本数据无法解析"}
            } else if case .failure(let error)=response {
                notice=error.localizedDescription
            }
            busy=false
        }
    }
    private func openOfficialMarket() {
        guard !busy,officialMarketEnabled else {return}
        busy=true
        notice="正在核对 DSH 当前会话的本机授权入口…"
        let python=effectivePython,root=effectiveRoot,home=effectiveHome
        Task {
            let result=await Task.detached(priority:.utility) {
                Result {
                    try Self.invoke(python:python,root:root,home:home,
                        extra:["url"],source:"r674_local_market_access.py")
                }
            }.value
            switch result {
            case .success(let data):
                do {
                    let info=try JSONDecoder().decode(R674MarketAccess.self,from:data)
                    guard info.ok,let url=URL(string:info.url),
                          let components=URLComponents(url:url,resolvingAgainstBaseURL:false),
                          url.scheme=="http",url.host=="127.0.0.1",url.port==3080,
                          url.path=="/",components.queryItems?.count==1,
                          components.queryItems?.first?.name=="token",
                          let token=components.queryItems?.first?.value,
                          token.range(of:#"^[A-Za-z0-9_-]{32,128}$"#,
                                      options:.regularExpression) != nil else {
                        throw NSError(domain:"r674-market-auth",code:3)
                    }
                    authorizedOfficialURL=url
                    showOfficialMarket=true
                    notice="已打开 DSH 插件管理。安装、启用、停用及卸载均在官方页面操作。"
                } catch {
                    notice="本机 DSH 授权地址核验失败；没有打开不可信网页或执行安装。"
                }
            case .failure:
                notice="DSH 官方页面尚未准备好，未修改插件或原会话；请刷新后再试。"
            }
            busy=false
        }
    }

    private func chooseProject() {
        let panel=NSOpenPanel()
        panel.canChooseDirectories=true
        panel.canChooseFiles=false
        panel.allowsMultipleSelection=false
        panel.prompt="选择项目"
        if panel.runModal() == .OK,let url=panel.url {
            guard FileManager.default.fileExists(
                atPath:url.appendingPathComponent("scripts/r659_plugin_manager.py").path)
            else {notice="所选目录不是 Deepseek-live 源码";return}
            projectRoot=url.path
            load()
        }
    }
    var body:some View {
        VStack(alignment:.leading,spacing:14) {
            HStack {
                VStack(alignment:.leading,spacing:4) {
                    Text("大肥鱼专用 DSH")
                        .font(.headline)
                    Text("仅管理当前配置的 DSH 实例")
                        .font(.subheadline).foregroundStyle(.secondary)
                }
                Spacer()
                Button {
                    showConfiguration.toggle()
                } label:{
                    Label("环境",systemImage:"gearshape")
                }
                .accessibilityIdentifier("r659-plugin-environment")
                Button {
                    openOfficialMarket()
                } label:{
                    Label("管理插件",systemImage:"slider.horizontal.3")
                }
                .buttonStyle(.borderedProminent)
                .disabled(busy || !officialMarketEnabled)
                .accessibilityIdentifier("r690-open-official-plugin-manager")
                Button {
                    load()
                } label:{
                    Label("刷新",systemImage:"arrow.clockwise")
                }
                .disabled(busy)
                .accessibilityIdentifier("r659-plugin-refresh")
            }
            if showConfiguration {
                VStack(alignment:.leading,spacing:8) {
                    HStack {
                        Text("项目目录").font(.caption)
                        TextField("Deepseek-live 源码目录",text:$projectRoot)
                        Button("选择") {chooseProject()}
                    }
                    HStack {
                        Text("DSH_HOME").font(.caption)
                        TextField("私有 DSH 主目录",text:$dshHome)
                    }
                    HStack {
                        Text("Python").font(.caption)
                        TextField("Python 3.12 执行路径",text:$pythonExecutable)
                    }
                    Text("仅管理当前配置的实例，不读取或更改其他 DSH 环境。")
                        .font(.caption).foregroundStyle(.secondary)
                }
                .padding(12)
                .background(Color(nsColor:.controlBackgroundColor),
                            in:RoundedRectangle(cornerRadius:10))
            }
            Picker("视图",selection:$selected) {
                ForEach(PluginBrowserTab.allCases,id:\.self) { tab in
                    Text(tab.rawValue).tag(tab)
                }
            }
            .pickerStyle(.segmented)
            .onChange(of:selected) {_,_ in load()}
            if selected == .market {
                HStack {
                    TextField("搜索已审查的插件候选",text:$search)
                        .textFieldStyle(.roundedBorder)
                        .onSubmit {load()}
                    Button("搜索") {load()}.disabled(busy)
                    Button("刷新网络目录") {lookupOnline()}.disabled(busy)
                }
            }
            if !notice.isEmpty {
                Text(notice).font(.caption)
                    .textSelection(.enabled)
                    .foregroundStyle(.secondary)
                    .accessibilityIdentifier("r659-plugin-notice")
            }
            if busy {ProgressView("正在读取插件状态…")}
            if !officialMarketEnabled && inventory != nil {
                Text("官方插件管理器未启用，无法执行插件变更。")
                    .font(.caption).foregroundStyle(.secondary)
            }
            ScrollView {
                VStack(alignment:.leading,spacing:12) {
                    if selected == .installed {
                        if let v=inventory {
                            HStack {
                                Text("已启用插件").font(.subheadline.weight(.semibold))
                                Spacer()
                                Text("\(activeOptionalBundles.count) 个")
                                    .foregroundStyle(.secondary)
                            }
                            if activeOptionalBundles.isEmpty {
                                Text("暂无额外启用的插件")
                                    .font(.subheadline).foregroundStyle(.secondary)
                            }
                            ForEach(activeOptionalBundles) { pkg in pluginRow(pkg) }
                            Divider()
                            DisclosureGroup(
                                "其他已安装插件（\(inactiveOptionalBundles.count) 个，未启用）",
                                isExpanded:$showInactivePackages) {
                                VStack(alignment:.leading,spacing:6) {
                                    Text("这些插件当前未启用，操作请点击顶部「管理插件」。")
                                        .font(.caption).foregroundStyle(.secondary)
                                    ForEach(inactiveOptionalBundles) { pkg in
                                        pluginRow(pkg)
                                    }
                                }.padding(.top,8)
                            }
                            Divider()
                            DisclosureGroup("系统组件 · 按运行配置保护",
                                            isExpanded:$showSystemDetails) {
                                VStack(alignment:.leading,spacing:6) {
                                    Text("基础 Bundle、手机与电脑工具、插件管理器由系统维护，不在这里卸载。")
                                        .font(.caption).foregroundStyle(.secondary)
                                    ForEach(v.essential_tools) { tool in
                                        HStack {
                                            Image(systemName:"lock.fill")
                                                .foregroundStyle(.secondary)
                                            Text(tool.name)
                                            Spacer()
                                            Text(tool.declared ? "已配置":"待配置")
                                                .foregroundStyle(.secondary)
                                        }.font(.caption).padding(.vertical,3)
                                    }
                                }.padding(.top,8)
                            }
                        } else if !busy {
                            Text("尚未读取状态。请检查项目目录和 DSH_HOME。")
                                .foregroundStyle(.secondary)
                        }
                    } else {
                        Text("DSH 联网插件市场 · 第三方索引")
                            .font(.subheadline.weight(.semibold))
                        Text("这里仅供浏览插件索引。安装、启停或卸载请使用顶部「管理插件」。")
                            .font(.caption).foregroundStyle(.secondary)
                        if let list=catalog {
                            Text("联网匹配 \(list.total_matches ?? list.count) 项，每次显示前 \(list.count) 项")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                        ForEach(catalog?.items ?? []) { item in
                            VStack(alignment:.leading,spacing:6) {
                                HStack {
                                    Text(item.title).font(.subheadline.weight(.medium))
                                    Spacer()
                                    Text(item.version).font(.caption)
                                        .foregroundStyle(.secondary)
                                }
                                Text(item.id).font(.caption).foregroundStyle(.secondary)
                                Text(item.description).font(.caption)
                                HStack {
                                    Text(item.compatibility)
                                        .font(.caption).foregroundStyle(.secondary)
                                    Spacer()
                                    if item.declared_locally {
                                        Text("已安装")
                                            .font(.caption).foregroundStyle(.secondary)
                                    }
                                    if let raw=item.homepage,
                                       let link=URL(string:raw),
                                       link.scheme=="https" {
                                        Button("查看来源") {
                                            NSWorkspace.shared.open(link)
                                        }.buttonStyle(.borderless)
                                    }
                                }
                            }
                            .padding(10)
                            .frame(maxWidth:.infinity,alignment:.leading)
                            .background(Color(nsColor:.controlBackgroundColor),
                                        in:RoundedRectangle(cornerRadius:10))
                        }
                    }
                }
                .frame(maxWidth:.infinity,alignment:.topLeading)
            }
        }
        .padding(24)
        .onAppear {load()}
        .sheet(isPresented:$showOfficialMarket,onDismiss:{
            authorizedOfficialURL=nil
            load()
        }) {
            VStack(alignment:.leading,spacing:10) {
                HStack {
                    Text("DSH 官方插件管理")
                        .font(.title3.weight(.semibold))
                    Spacer()
                    Button("关闭") {showOfficialMarket=false}
                }
                Text("在下方官方页面完成安装、启用、停用或卸载，关闭后返回本页查看最新状态。")
                    .font(.caption).foregroundStyle(.secondary)
                if let url=authorizedOfficialURL {
                    HStack {
                        Button("在系统浏览器打开") {
                            NSWorkspace.shared.open(url)
                        }
                        .buttonStyle(.borderedProminent)
                        .accessibilityIdentifier("r675-open-official-market-system-browser")
                        Text("本机官方 DSH 授权页面，外部浏览器自行完成一次性登录")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                }
                if let source=catalog?.index_url,
                   let link=URL(string:source),link.scheme=="https" {
                    HStack {
                        Text("当前索引：\(source)").font(.caption)
                            .textSelection(.enabled)
                        Button("复制索引地址") {
                            NSPasteboard.general.clearContents()
                            NSPasteboard.general.setString(source,forType:.string)
                        }
                    }
                }
                Divider()
                if let url=authorizedOfficialURL {
                    LocalDSHMarketWeb(localURL:url)
                        .frame(minWidth:960,minHeight:640)
                } else {
                    Text("官方授权地址不可用，本次未进入插件安装中心。")
                }
            }
            .padding(18)
        }
    }
}
