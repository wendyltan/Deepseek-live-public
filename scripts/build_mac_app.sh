#!/bin/zsh
# Build the native Dafeiyu macOS app from the checked-in Swift sources.
# Usage: zsh scripts/build_mac_app.sh check
#        zsh scripts/build_mac_app.sh build /path/to/Dafeiyu.app
#        zsh scripts/build_mac_app.sh build /path/to/Dafeiyu.app --motion-previews /path/to/106-jpegs
set -euo pipefail

project="$(cd "$(dirname "$0")/.." && pwd -P)"
source_dir="$project/native/macos/CompanionMini"
mode="${1:-}"

if [[ "$mode" != "check" && "$mode" != "build" ]]; then
  print -u2 "Usage: zsh scripts/build_mac_app.sh check | build /path/to/Dafeiyu.app [--motion-previews DIR]"
  exit 2
fi

sources=(
  CompanionProjectPaths.swift CompanionModels.swift CompanionStore.swift main.swift CompanionManagementCenter.swift
  CompanionPreferencesView.swift CompanionServiceControlsView.swift CompanionSpokenHistory.swift CompanionManagementConversation.swift
  CompanionComputerApproval.swift
  MemoryOverviewSheet.swift PersonaOverviewSheet.swift WiFiGatewayStatusView.swift
  BridgeGrowthReviewSheet.swift ConversationContextSheet.swift
  ReadableMarkdownView.swift VoicePreprocessorSettingsView.swift
  MotionLibrarySheet.swift MotionTriggers106Sheet.swift RemoteDisplaySheet.swift
  CompanionDiagnosticsHubSheet.swift
)
[[ -f "$source_dir/CompanionPluginsView.swift" ]] && sources+=(CompanionPluginsView.swift)
files=()
for f in "${sources[@]}"; do
  [[ -f "$source_dir/$f" ]] || { print -u2 "Missing Swift source: $f"; exit 3; }
  files+=("$source_dir/$f")
done

if [[ "$mode" == "check" ]]; then
  /usr/bin/swiftc -typecheck -parse-as-library -framework AppKit -framework SwiftUI "${files[@]}"
  echo "MAC_APP_SOURCE_CHECK_PASS (${#files[@]} Swift files)"
  exit 0
fi

dest="${2:-}"
[[ -n "$dest" && "$dest" == *.app && ! -e "$dest" && ! -L "$dest" ]] || {
  print -u2 "Provide a new .app destination that does not already exist."
  exit 4
}
parent="$(cd "$(dirname "$dest")" && pwd -P)" || {
  print -u2 "Create the destination parent directory first."
  exit 4
}
dest="$parent/$(basename "$dest")"
preview_source=""
if [[ $# -gt 2 ]]; then
  [[ $# -eq 4 && "$3" == "--motion-previews" && -d "$4" && ! -L "$4" ]] || {
    print -u2 "Usage: build output.app [--motion-previews DIR]"
    exit 5
  }
  preview_source="$(cd "$4" && pwd -P)"
  # An explicitly provided asset directory is the sole input for previews.
  for n in {000..105}; do
    f="$preview_source/m$n.jpg"
    [[ -f "$f" && ! -L "$f" && -s "$f" ]] || {
      print -u2 "Missing animation preview: $f"
      exit 5
    }
  done
  preview_count="$(find "$preview_source" -maxdepth 1 -type f -name 'm[0-9][0-9][0-9].jpg' | wc -l | tr -d ' ')"
  [[ "$preview_count" == "106" ]] || {
    print -u2 "Expected 106 animation previews, got $preview_count"
    exit 5
  }
fi
icon="$project/docs/assets/deepseek-live-icon.png"
catalog="$source_dir/motion-catalog.json"
scale="$source_dir/motion-scale-advisory.json"
trigger="$source_dir/motion-trigger-r121.json"
[[ -s "$icon" && -s "$catalog" && -s "$scale" && -s "$trigger" ]] || {
  print -u2 "Required icon or motion configuration JSON is missing."
  exit 5
}

# Build into a temporary directory and move into place only after signing.
work="$(mktemp -d "$parent/.dafeiyu-build.XXXXXXXX")"
cleanup() { [[ -n "${work:-}" && -d "$work" ]] && /bin/rm -rf -- "$work"; }
trap cleanup EXIT
bundle="$work/大肥鱼.app"
/bin/mkdir -p "$bundle/Contents/MacOS" "$bundle/Contents/Resources"
/usr/bin/swiftc -parse-as-library -O -framework AppKit -framework SwiftUI \
  "${files[@]}" -o "$bundle/Contents/MacOS/DeepseekMini"
/bin/cp "$icon" "$bundle/Contents/Resources/deepseek-live-icon.png"
/bin/cp "$catalog" "$bundle/Contents/Resources/motion-catalog.json"
/bin/cp "$scale" "$bundle/Contents/Resources/motion-scale-advisory.json"
/bin/cp "$trigger" "$bundle/Contents/Resources/motion-trigger-r121.json"

# Generate an App icon directly from this repo's own PNG.
iconset="$work/Dafeiyu.iconset"
/bin/mkdir -p "$iconset"
for size in 16 32 128 256 512; do
  /usr/bin/sips -s format png -z "$size" "$size" "$icon"     --out "$iconset/icon_"$size"x"$size".png" >/dev/null
  doubled="$((size*2))"
  /usr/bin/sips -s format png -z "$doubled" "$doubled" "$icon"     --out "$iconset/icon_"$size"x"$size"@2x.png" >/dev/null
done
/usr/bin/iconutil -c icns "$iconset" -o "$bundle/Contents/Resources/deepseek-live.icns"

if [[ -n "$preview_source" ]]; then
  /bin/mkdir -p "$bundle/Contents/Resources/motion-previews"
  for n in {000..105}; do
    /bin/cp "$preview_source/m$n.jpg" "$bundle/Contents/Resources/motion-previews/m$n.jpg"
  done
fi

cat > "$bundle/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleExecutable</key><string>DeepseekMini</string>
<key>CFBundleIdentifier</key><string>org.deepseeklive.dafeiyu.mac</string>
<key>CFBundleName</key><string>大肥鱼</string>
<key>CFBundleDisplayName</key><string>大肥鱼</string>
<key>CFBundleIconFile</key><string>deepseek-live.icns</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleShortVersionString</key><string>0.1.0</string>
<key>CFBundleVersion</key><string>1</string>
<key>LSMinimumSystemVersion</key><string>14.0</string>
<key>LSUIElement</key><false/>
<key>NSAppTransportSecurity</key><dict>
  <key>NSAllowsLocalNetworking</key><true/>
</dict>
</dict></plist>
PLIST
/usr/bin/plutil -lint "$bundle/Contents/Info.plist"
/usr/bin/codesign --force --sign - "$bundle"
/usr/bin/codesign --verify --deep --strict "$bundle"
[[ ! -e "$dest" && ! -L "$dest" ]] || { print -u2 "Destination now exists: $dest"; exit 6; }
/bin/mv "$bundle" "$dest"
if [[ -n "$preview_source" ]]; then
  echo "MAC_APP_RESOURCES_COMPLETE motion_previews=106"
else
  echo "MAC_APP_MOTION_PREVIEWS_ABSENT: add --motion-previews DIR for full motion library"
fi
echo "MAC_APP_BUILD_PASS $dest"
