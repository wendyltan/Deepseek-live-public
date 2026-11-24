// SPDX-License-Identifier: MIT
import AppKit
import Combine
import SwiftUI

private struct R459ServiceState: Decodable {
    let enabled:Bool
    let loaded:Bool
    let running:Bool
}
private struct R459SwitchReceipt: Decodable {
    let schema:Int
    let ok:Bool
    let reason:String?
    let services:[String:R459ServiceState]?
}

// R459 service switches represent actual persisted launchctl decisions.
// Never fabricate a DSH/tts power toggle: those are shared backends.
struct CompanionServiceControlsView: View {
    @ObservedObject var store:CompanionStore
    var compact:Bool = false
    @State private var wirelessBusy=false
    @State private var services:[String:R459ServiceState]=[:]
    @State private var applying:String?=nil
    @State private var pendingOff:String?=nil
    @State private var showTurnOff=false
    @State private var notice=""

    private func refreshWirelessBusy() {
        let status=VerifiedWiFiGateway.read()
        wirelessBusy=status?.active_devices == 1 || status?.pending_dsh_jobs == 1
    }

    private nonisolated static func manager(_ args:[String]) -> R459SwitchReceipt? {
        let command=Process()
        command.executableURL=URL(fileURLWithPath:CompanionProjectPaths.python)
        command.arguments=[
            CompanionProjectPaths.script("companion_cli.py"),"service"
        ]+args
        command.standardError=Pipe()
        let output=Pipe()
        command.standardOutput=output
        do {
            try command.run()
            command.waitUntilExit()
            guard command.terminationStatus==0 else{return nil}
            let bytes=output.fileHandleForReading.readDataToEndOfFile()
            guard bytes.count<8192 else{return nil}
            return try JSONDecoder().decode(R459SwitchReceipt.self,from:bytes)
        } catch {return nil}
    }

    private func refreshServices() {
        guard applying==nil else{return}
        Task.detached(priority:.utility) {
            let receipt=Self.manager(["status"])
            await MainActor.run {
                guard applying==nil else{return}
                if let receipt,receipt.schema==1,receipt.ok,
                   let result=receipt.services {
                    services=result
                } else {
                    services=[:]
                    notice="无法读取 Mac 服务开关的真实状态。"
                }
            }
        }
    }

    private func localReason(_ code:String?) -> String {
        switch code {
        case "wireless_conversation_active","wireless_owner_unverified",
             "wifi_gateway_running","wireless_status_stale":
            return "无线设备或网关仍在工作，请先结束当前无线会话"
        case "voice_not_idle","voice_not_verified","usb_state_unavailable":
            return "USB语音尚未确认空闲，暂不允许停止"
        case "status_read_failed","launchctl_read_failed":
            return "macOS服务状态读取失败"
        case "missing_or_untrusted_launchagent","launchagent_owner_mismatch":
            return "启动配置未经核验，请检查本机服务安装"
        case "bootout_failed","bootstrap_failed":
            return "系统没有完成启停，请查看本机日志"
        case "readback_mismatch","service_still_loaded":
            return "系统回读与请求不一致，开关已恢复真实状态"
        default:
            return "系统未确认本次操作"
        }
    }

    private func change(_ service:String,_ enabled:Bool) {
        guard applying==nil,services[service] != nil else{return}
        if !enabled {
            pendingOff=service
            showTurnOff=true
            return
        }
        apply(service,true)
    }

    private func apply(_ service:String,_ enabled:Bool) {
        guard applying==nil else{return}
        applying=service
        notice="正在通过 macOS 系统服务管理器核实变更…"
        Task.detached(priority:.userInitiated) {
            let reply=Self.manager([service,enabled ? "on":"off"])
            await MainActor.run {
                applying=nil
                if let reply,reply.schema==1,
                   let actual=reply.services {
                    services=actual
                    if reply.ok &&
                       actual[service]?.enabled==enabled {
                        notice=enabled ? "已开启服务托管；实际连接状态以运行回执为准。"
                                       : "已关闭服务托管，Mac 已确认服务退出。"
                    } else {
                        notice=localReason(reply.reason)+"；已按系统实际状态显示。"
                    }
                } else {
                    services=[:]
                    notice="服务操作没有可信回执，开关状态暂不确认。"
                }
            }
        }
    }

    private func serviceSwitch(_ key:String,_ title:String,
                               _ detail:String) -> some View {
        HStack(alignment:.center,spacing:14) {
            VStack(alignment:.leading,spacing:4) {
                Text(title).font(.system(size:13,weight:.medium))
                Text(detail)
                    .font(.system(size:11)).foregroundStyle(.secondary)
                    .fixedSize(horizontal:false,vertical:true)
                if let live=services[key] {
                    Text(live.running ? "系统确认正在运行" :
                         live.enabled ? "已允许启动 · 等待条件满足":"已停用")
                        .font(.system(size:11))
                        .foregroundStyle(.secondary)
                }
            }
            Spacer(minLength:8)
            Toggle(title,isOn:Binding(
                get:{services[key]?.enabled == true},
                set:{change(key,$0)}))
                .labelsHidden()
                .toggleStyle(.switch)
                .disabled(services[key]==nil || applying != nil ||
                          store.connecting || wirelessBusy ||
                          (key=="usb" && !canSafelyChangeVoice))
                .accessibilityLabel(title)
                .accessibilityHint("切换的是 macOS LaunchAgent 托管许可；只在有实际读回时更新。")
                .accessibilityIdentifier("r459-switch-"+key)
        }
    }

    private var canSafelyChangeVoice:Bool {
        guard let info=store.snapshot,
              info.session_verified == true,
              Date().timeIntervalSince1970-info.updated_at_unix<12 else {
            // A currently unloaded service cannot have a fresh USB snapshot.
            return services["usb"]?.loaded == false
        }
        return info.phase=="idle" && !store.connecting
    }

    private func recover() {
        if store.dshServiceState != "已就绪" {
            store.startDshService()
        } else if services["transport"]?.enabled == true &&
                  services["transport"]?.running == false {
            store.startWiFiGateway()
        } else if services["usb"]?.enabled == true &&
                  services["usb"]?.running == false && !wirelessBusy {
            store.startVoiceService()
        } else {
            refreshServices()
            notice="服务托管状态已刷新；连接状态仍以设备与会话回执为准。"
        }
    }

    var body:some View {
        VStack(alignment:.leading,spacing:13) {
            if !compact {
                Text("Mac 后台服务").font(.system(size:16,weight:.semibold))
            }
            serviceSwitch("usb","USB 语音服务",
                          "只管理USB通道，使用无线通话时不可切换。")
            Divider()
            serviceSwitch("transport","自动管理 USB / Wi-Fi 通道",
                          "随设备连接方式自动切换唯一语音通道。")
            Divider()
            HStack(alignment:.center,spacing:12) {
                VStack(alignment:.leading,spacing:5) {
                    LabeledContent("官方 DSH",value:store.dshServiceState)
                    LabeledContent("Qwen 声音",value:store.localTTSReady ? "就绪":"尚未就绪")
                }
                Spacer(minLength:10)
                Button("检查并修复"){recover()}
                    .disabled(applying != nil || store.connecting || wirelessBusy)
                    .help("仅在服务异常时恢复所需服务，不关闭共享DSH或Qwen")
            }
            if wirelessBusy {
                Label("无线设备正在使用，服务切换已锁定",systemImage:"lock.shield")
                    .font(.caption).foregroundStyle(.secondary)
            }
            if applying != nil || store.connecting {
                ProgressView("正在核验后台服务…").controlSize(.small)
            }
            if !notice.isEmpty {
                Text(notice)
                    .font(.system(size:11)).foregroundStyle(.secondary)
                    .fixedSize(horizontal:false,vertical:true)
            }
            if !store.launchStatus.isEmpty {
                Text(store.launchStatus)
                    .font(.system(size:11)).foregroundStyle(.secondary)
                    .fixedSize(horizontal:false,vertical:true)
            }
        }
        .font(.system(size:13))
        .accessibilityIdentifier("r317-service-controls")
        .confirmationDialog("确认关闭这项服务？",
                            isPresented:$showTurnOff,titleVisibility:.visible) {
            Button("关闭服务",role:.destructive) {
                if let service=pendingOff {apply(service,false)}
                pendingOff=nil
            }
            Button("取消",role:.cancel){pendingOff=nil}
        } message: {
            Text(pendingOff=="transport" ?
                 "关闭后Mac不会自动在USB与Wi-Fi之间切换；不会中断正在进行的对话，繁忙时操作会被拒绝。" :
                 "关闭USB语音后台后无法使用USB录音与播报，重新打开开关可恢复。Wi-Fi通话中不能关闭。")
        }
        .onAppear {refreshWirelessBusy();refreshServices()}
        .onReceive(Timer.publish(every:5,on:.main,in:.common).autoconnect()) { _ in
            refreshWirelessBusy()
            refreshServices()
        }
    }
}
