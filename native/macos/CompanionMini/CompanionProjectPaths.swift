// SPDX-License-Identifier: MIT
// R660 portable companion project path resolution for the native Mac manager.
// User-selected project location is authoritative. No network, scanning of
// private app data or filesystem mutations; historical ExtSSD discoverable
// as a normal external volume, not hardcoded to a particular username.
import Foundation

enum CompanionProjectPaths {
    private static let managerScript = "scripts/r659_plugin_manager.py"

    private static func projectExists(_ url: URL) -> Bool {
        let fm=FileManager.default
        let path=url.standardizedFileURL.resolvingSymlinksInPath()
        return fm.fileExists(atPath:path.appendingPathComponent(managerScript).path)
            && fm.fileExists(atPath:path.appendingPathComponent("scripts/install_host.py").path)
            && fm.fileExists(atPath:path.appendingPathComponent("plugins/dsh-live-bridge/package.json").path)
    }

    private static func validated(_ raw: String?) -> URL? {
        guard let raw, !raw.isEmpty else {return nil}
        let url=URL(fileURLWithPath:(raw as NSString).expandingTildeInPath)
            .standardizedFileURL.resolvingSymlinksInPath()
        return projectExists(url) ? url : nil
    }

    static var rootURL:URL {
        if let selected=validated(UserDefaults.standard.string(forKey:"r659CompanionProjectRoot")) {
            return selected
        }
        if let configured=validated(ProcessInfo.processInfo.environment["DAFEIYU_PROJECT_ROOT"]) {
            return configured
        }
        let home=FileManager.default.homeDirectoryForCurrentUser
        for candidate in [
            home.appendingPathComponent("Projects/Deepseek-live"),
            home.appendingPathComponent("Documents/Deepseek-live"),
            home.appendingPathComponent("Developer/Deepseek-live")
        ] where projectExists(candidate) {
            return candidate
        }
        // Discover a project on an attached user volume without assuming
        // that anyone else's disk is named ExtSSD.
        if let volumes=try? FileManager.default.contentsOfDirectory(
            at:URL(fileURLWithPath:"/Volumes",isDirectory:true),
            includingPropertiesForKeys:nil,options:[.skipsHiddenFiles]) {
            for volume in volumes {
                let candidate=volume.appendingPathComponent("Projects/Deepseek-live")
                if projectExists(candidate) {return candidate}
            }
        }
        // A missing project resolves to a harmless nonexistent user path.
        // Every actual script call checks its presence before execution.
        return home.appendingPathComponent("Projects/Deepseek-live")
    }
    static func script(_ relative:String)->String {
        rootURL.appendingPathComponent("scripts").appendingPathComponent(relative).path
    }
    static var toolsURL:URL {
        if let env=ProcessInfo.processInfo.environment["DAFEIYU_TOOLS_ROOT"],
           !env.isEmpty {
            return URL(fileURLWithPath:(env as NSString).expandingTildeInPath)
        }
        return rootURL.deletingLastPathComponent()
            .deletingLastPathComponent().appendingPathComponent("Tools")
    }
    static var python:String {
        if let v=ProcessInfo.processInfo.environment["DAFEIYU_PYTHON"],
           !v.isEmpty {return v}
        return "/opt/homebrew/bin/python3.12"
    }
    static var idfPython:String {
        if let v=ProcessInfo.processInfo.environment["DAFEIYU_ESP_IDF_PYTHON"],
           !v.isEmpty {return v}
        return toolsURL.appendingPathComponent(
            "espressif-idf54/python_env/idf5.5_py3.12_env/bin/python3").path
    }
    static var motionSourceURL:URL {
        toolsURL.appendingPathComponent("esp32-s3-lab/selected-motions240",
                                       isDirectory:true)
    }
}
