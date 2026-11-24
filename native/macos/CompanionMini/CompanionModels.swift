// SPDX-License-Identifier: MIT
// Shared companion state models, palette, and USB serial hint for CompanionMini.
import AppKit
import SwiftUI

struct CompanionStep: Decodable {
    let phase: String
    let label: String
}

struct ConversationPreview: Decodable {
    var speech_id: String? = nil
    let user: String
    let assistant: String
    let origin: String
    let progress: [String]?
}

struct VerifiedConversationArchive: Decodable {
    let schema: Int
    let session_id: String
    let session_verified: Bool
    let turns: [ConversationPreview]
}

struct CompanionSnapshot: Decodable {
    let schema: Int
    let updated_at_unix: Double
    let phase: String
    let session_id: String?
    let session_verified: Bool?
    let model_id: String?
    let model_confirmed: Bool?
    let answer_origin: String?
    let answer_verified: Bool?
    let user_text: String?
    let answer_text: String?
    let answer_speech_id: String?
    let spoken_progress_text: String?
    let turn_progress: [String]?
    let current_task_id: String?
    let reasoning_observed: Bool?
    let steps: [CompanionStep]?
    let model_selection_source: String?
    let search_enabled: Bool?
    let search_supported: Bool?
    let board_battery_valid: Bool?
    let board_battery_percent: Int?
    let board_telemetry_at_unix: Double?
    let board_clock_hhmm: String?
    let wake_capability_verified: Bool?
    let voice_streaming_enabled: Bool?
    let voice_audio_diagnostics: String?
    // Only true after an actual DFSD3 user-write protocol handshake.
    // Current R121 has not provided this capability receipt.
    let screen_capture_status: String?
    let screen_capture_crc32: String?
    let sd_install_capability_verified: Bool?
    let tool_execution_verified: Bool?
    let last_outcome: String?
    let animation_id: String?
    let animation: String?
    let esp32_frame_motion_id: String?
    let esp32_frame_verified: Bool?
    let conversation_preview: [ConversationPreview]?
    let voice_preprocessor_last: String?
    let voice_preprocessor_original_chars: Int?
    let voice_preprocessor_spoken_chars: Int?
}

// Always derive counts from the bundled, SHA-tested catalog. A preserved
// 35-motion baseline is never a ceiling on future additions.
enum MotionCatalogSummary {
    static let text: String = {
        guard let url = Bundle.main.url(forResource: "motion-catalog", withExtension: "json"),
              let data = try? Data(contentsOf: url), data.count < 100_000,
              let raw = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              raw["schema"] as? Int == 1,
              let total = raw["count"] as? Int, total > 0, total < 10000,
              let selected = raw["selectedCount"] as? Int, selected > 0, selected <= total,
              let entries = raw["motions"] as? [[String: Any]], entries.count == total,
              entries.filter({ $0["inCurrentPackage"] as? Bool == true }).count == selected
        else { return "素材清单不可用 · 请重新构建" }
        return "\(total) 个素材 · 已选 \(selected) 个（可继续增加）"
    }()
}

// Authenticated by the existing real ESP USB probes and the official DSH
// bind receipt from the *same* process. Never treat mere port presence as DSH.
struct PhysicalDeviceLink: Decodable {
    let schema: Int
    let started_at_unix: Double
    let session_id: String
    let esp32_verified: Bool
    let selected35_verified: Bool
    let usb_port: String
    let voice_source: String
}

// R317: observed service status comes from the private read-only manager.
struct CompanionServiceStatus: Decodable {
    let dsh_ready: Bool
    let dsh_running: Bool
    let voice_running: Bool
    let voice_verified: Bool
    let tts_ready: Bool
    let usb_present: Bool
    let lan_occupied: Bool
}

struct CompanionServiceReceipt: Decodable {
    let ok: Bool
    let detail: String
    let status: CompanionServiceStatus?
}

enum DeepSeekPalette {
    static let background = Color(nsColor: .windowBackgroundColor)
    static let panel = Color(nsColor: .controlBackgroundColor)
    static let panelAlt = Color(nsColor: .underPageBackgroundColor)
    static let accent = Color(nsColor: .controlAccentColor)
    static let foreground = Color(nsColor: .labelColor)
    static let secondary = Color(nsColor: .secondaryLabelColor)
    static let border = Color(nsColor: .separatorColor)
}

// Device detection is a *hint*, never a proof of authenticated USB handshake.
// Reject ambiguous modems; the Python serial owner verifies ESP VID/PID.
enum ESPUSBSerialPresence {
    static func currentPort() -> String? {
        guard let names = try? FileManager.default.contentsOfDirectory(atPath: "/dev") else {
            return nil
        }
        let matches = names.filter { $0.hasPrefix("cu.usbmodem") }
                           .sorted()
        return matches.count == 1 ? "/dev/" + matches[0] : nil
    }
    static var detected: Bool { currentPort() != nil }
}
