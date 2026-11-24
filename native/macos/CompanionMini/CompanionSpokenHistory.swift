// SPDX-License-Identifier: MIT
import AppKit
import Combine
import SwiftUI

struct R499SpeechSegment: Decodable {
    let text:String
    let audio_ms:Int
}

struct R499ReplyComparison: Decodable {
    let speech_id:String?
    let schema:Int
    let session_id:String
    let generated_at_unix:Double
    let origin:String
    let original_text:String
    let spoken_text:String
    let final_spoken_text:String?
    let voice_profile_id:String?
    let original_chars:Int
    let spoken_chars:Int
    let segments:[R499SpeechSegment]?
    let tts_generated:Bool
    let device_playback_verified:Bool
}

enum R499ComparisonReader {
    static func read(for sessionID:String) -> R499ReplyComparison? {
        let url=FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/Deepseek-live/companion-native/reply-speech-comparison-v1.json")
        guard let props=try? url.resourceValues(forKeys:[.isRegularFileKey,.isSymbolicLinkKey]),
              props.isRegularFile==true,props.isSymbolicLink != true,
              let attrs=try? FileManager.default.attributesOfItem(atPath:url.path),
              ((attrs[.posixPermissions] as? NSNumber)?.intValue ?? 511) & 0o077 == 0,
              (attrs[.ownerAccountID] as? NSNumber)?.intValue == Int(getuid()),
              let size=(attrs[.size] as? NSNumber)?.intValue,
              size>20,size<=48_000,
              let raw=try? Data(contentsOf:url),
              let record=try? JSONDecoder().decode(R499ReplyComparison.self,from:raw)
        else {return nil}
        let now=Date().timeIntervalSince1970
        guard record.schema==1,record.session_id==sessionID,
              record.generated_at_unix.isFinite,
              now-record.generated_at_unix >= -5,
              now-record.generated_at_unix <= 7*86400,
              ["official_dsh_verified","verified_mac_local_datetime",
               "verified_open_meteo_weather","local_weather_source_unavailable"].contains(record.origin),
              record.original_chars==record.original_text.unicodeScalars.count,
              record.spoken_chars==record.spoken_text.unicodeScalars.count,
              record.original_chars>0,record.original_chars<=12_000,
              record.spoken_chars>0,record.spoken_chars<=8_000 else {return nil}
        if let final=record.final_spoken_text {
            guard !final.isEmpty && record.spoken_text.hasSuffix(final) else{return nil}
        }
        if let profile=record.voice_profile_id {
            guard ["dafeiyu-qwen3-d10","dafeiyu-r503-qwen06-long-trial"].contains(profile) else {
                return nil
            }
        }
        if let parts=record.segments, !parts.isEmpty {
            guard parts.count<=64,
                  parts.allSatisfy({$0.audio_ms>=100 && $0.audio_ms<=180_000}),
                  parts.map(\.text).joined()==record.spoken_text else {return nil}
        }
        return record
    }
}

// R520: private, same-session history of fully synthesized speech. This is
// display data, not proof of physical ESP32 speaker playback.
struct R520SpokenRecord: Decodable {
    let speech_id:String?
    let original_text:String
    let spoken_text:String
    let final_spoken_text:String?
    let generated_at_unix:Double
}
private struct R520SpokenArchive: Decodable {
    let schema:Int
    let session_id:String
    let records:[R520SpokenRecord]
}
enum R520SpokenHistoryReader {
    static func read(for sessionID:String) -> [R520SpokenRecord]? {
        let url=FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/Deepseek-live/companion-native/reply-speech-history-v1.json")
        guard let props=try? url.resourceValues(forKeys:[.isRegularFileKey,.isSymbolicLinkKey]),
              props.isRegularFile==true,props.isSymbolicLink != true,
              let attrs=try? FileManager.default.attributesOfItem(atPath:url.path),
              ((attrs[.posixPermissions] as? NSNumber)?.intValue ?? 511) & 0o077 == 0,
              (attrs[.ownerAccountID] as? NSNumber)?.intValue == Int(getuid()),
              let size=(attrs[.size] as? NSNumber)?.intValue,
              size>20,size<=800_000,
              let raw=try? Data(contentsOf:url),
              let archive=try? JSONDecoder().decode(R520SpokenArchive.self,from:raw),
              archive.schema==1,archive.session_id==sessionID,
              archive.records.count<=120 else {return nil}
        let now=Date().timeIntervalSince1970
        guard archive.records.allSatisfy({item in
            item.generated_at_unix.isFinite &&
            item.generated_at_unix <= now+5 &&
            item.original_text.count>0 && item.original_text.count<=12_000 &&
            item.spoken_text.count>0 && item.spoken_text.count<=8_000 &&
            (item.final_spoken_text == nil || (
                !(item.final_spoken_text ?? "").isEmpty &&
                item.spoken_text.hasSuffix(item.final_spoken_text ?? "")))
        }) else {return nil}
        return archive.records
    }
}

// R683: the default chat remains the verified spoken script. For a trusted
// read-only phone search the exact DSH tool-backed answer stays reachable
// without replacing speech with raw text or adding permanent UI controls.
struct R683PhoneSearchOriginalView: View {
    let turn:ConversationPreview
    @State private var expanded=false
    private var eligible:Bool {
        turn.origin == "model" &&
        (turn.user.contains("手机") || turn.user.lowercased().contains("pinky")) &&
        (turn.user.contains("搜索") || turn.user.contains("搜一下") ||
         turn.user.contains("搜一搜")) &&
        (turn.user.contains("只看") || turn.user.contains("只查看") ||
         turn.user.contains("仅查看")) &&
        turn.assistant.count>=12 && turn.assistant.count<=900 &&
        (turn.assistant.contains("商品") || turn.assistant.contains("搜索结果"))
    }
    var body:some View {
        if eligible {
            DisclosureGroup(isExpanded:$expanded) {
                ReadableMarkdownView(source:turn.assistant)
                    .padding(.vertical,7)
                    .frame(maxWidth:.infinity,alignment:.leading)
            } label: {
                Label("查看原始手机搜索结果",systemImage:"list.bullet.rectangle")
                    .font(.system(size:12,weight:.medium))
            }
            .foregroundStyle(.secondary)
            .padding(.horizontal,13)
            .padding(.vertical,9)
            .background(Color(nsColor:.controlBackgroundColor).opacity(0.65),
                        in:RoundedRectangle(cornerRadius:10))
            .frame(maxWidth:650,alignment:.leading)
            .accessibilityIdentifier("r683-original-phone-search-result")
        }
    }
}

// R531: one trusted per-turn spoken-script resolver for both Mac views.
// The original answer remains in the DSH history; this changes display only.
// The projector intentionally truncates preview answers to 900 characters,
// while the verified speech record retains the complete original answer.
enum R531VerifiedSpokenDisplay {
    static func matches(_ full:String, preview:String) -> Bool {
        full == preview || (preview.count == 900 && full.hasPrefix(preview))
    }
    static func resolve(turn:ConversationPreview, sessionID:String?) -> (String,String)? {
        guard let sid=sessionID,!sid.isEmpty,
              let id=turn.speech_id,
              id.range(of:#"^[0-9a-f]{32}$"#,options:.regularExpression) != nil
        else {return nil}
        let current=R499ComparisonReader.read(for:sid)
        if let current,
           current.speech_id==id,
           matches(current.original_text,preview:turn.assistant) {
            // R535: R511 already publishes the exact verified TTS plan before
            // synthesis. A pending plan is not playable audio, but it IS the
            // text that the board will hear if synthesis completes. Render it
            // immediately rather than waiting for a playback completion ACK.
            if !current.tts_generated {
                return (current.final_spoken_text ?? current.spoken_text,
                        "结果朗读稿 · 合成中")
            }
            return (current.final_spoken_text ?? current.spoken_text,
                    current.device_playback_verified ? "结果朗读稿 · 设备已完成播放" : "结果朗读稿 · 已合成")
        }
        let records=R520SpokenHistoryReader.read(for:sid) ?? []
        if let matched=records.last(where:{$0.speech_id==id &&
                         matches($0.original_text,preview:turn.assistant)}) {
            return (matched.final_spoken_text ?? matched.spoken_text,
                    "已合成结果朗读稿")
        }
        return nil
    }
}

// R317: explicit, non-destructive local service recovery buttons.
// A started PID and an authenticated ESP32 speech session are different facts.
