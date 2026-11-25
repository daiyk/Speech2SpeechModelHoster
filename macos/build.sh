#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
out=${BUILD_DIR:-"$PWD/dist"}
app="$out/Reachy Mini Speech.app"
version_args=(--version-only)
if [[ -n ${RELEASE_TAG:-} ]]; then version_args+=(--tag "$RELEASE_TAG"); fi
version=$(python3 macos/release_notes.py "${version_args[@]}")
sign=(codesign --force --sign "${CODE_SIGN_IDENTITY:--}")
if [[ -n ${CODE_SIGN_IDENTITY:-} ]]; then sign+=(--options runtime --timestamp); fi
mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources/project/src"
swift_flags=(-framework SwiftUI -framework AppKit)
if [[ -n ${SPARKLE_DIR:-} ]]; then
  : "${SPARKLE_PUBLIC_KEY:?Missing Sparkle public key}" "${GITHUB_REPOSITORY:?Missing GitHub owner/repository}"
  mkdir -p "$app/Contents/Frameworks"
  framework="$app/Contents/Frameworks/Sparkle.framework"
  ditto "$SPARKLE_DIR/Sparkle.framework" "$framework"
  cp "$SPARKLE_DIR/LICENSE" "$app/Contents/Resources/Sparkle-LICENSE"
  if [[ -n ${CODE_SIGN_IDENTITY:-} ]]; then
    helpers="$framework/Versions/Current"
    "${sign[@]}" "$helpers/XPCServices/Installer.xpc"
    "${sign[@]}" --preserve-metadata=entitlements "$helpers/XPCServices/Downloader.xpc"
    "${sign[@]}" "$helpers/Autoupdate"
    "${sign[@]}" "$helpers/Updater.app"
    "${sign[@]}" "$framework"
  fi
  swift_flags+=(-D SPARKLE_UPDATES -F "$SPARKLE_DIR" -framework Sparkle
    -Xlinker -rpath -Xlinker '@executable_path/../Frameworks')
fi
xcrun swiftc -parse-as-library macos/ReachySpeech.swift -o "$app/Contents/MacOS/ReachySpeech" \
  -target arm64-apple-macos14.0 -module-cache-path "${TMPDIR:-/tmp}/reachy-swift-cache" "${swift_flags[@]}"
iconset="$out/AppIcon.iconset"
mkdir -p "$iconset"
for size in 16 32 128 256 512; do
  sips -z "$size" "$size" macos/Assets/AppIcon.png --out "$iconset/icon_${size}x${size}.png" >/dev/null
  double=$((size * 2))
  sips -z "$double" "$double" macos/Assets/AppIcon.png --out "$iconset/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns "$iconset" -o "$app/Contents/Resources/AppIcon.icns"
cp macos/Assets/AppIcon.png "$app/Contents/Resources/AppIcon.png"
cp macos/bootstrap.sh "$app/Contents/Resources/bootstrap.sh"
cp pyproject.toml uv.lock .python-version "$app/Contents/Resources/project/"
rsync -a --delete --exclude '__pycache__' src/reachy_local "$app/Contents/Resources/project/src/"
plist="$app/Contents/Info.plist"
cat > "$plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleExecutable</key><string>ReachySpeech</string>
<key>CFBundleIdentifier</key><string>local.reachy.speech</string>
<key>CFBundleName</key><string>Reachy Mini Speech</string>
<key>CFBundleIconFile</key><string>AppIcon</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleVersion</key><string>$version</string>
<key>CFBundleShortVersionString</key><string>$version</string>
<key>LSMinimumSystemVersion</key><string>14.0</string>
<key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST
if [[ -n ${SPARKLE_DIR:-} ]]; then
  plutil -insert SUFeedURL -string "https://github.com/$GITHUB_REPOSITORY/releases/latest/download/appcast.xml" "$plist"
  plutil -insert SUPublicEDKey -string "$SPARKLE_PUBLIC_KEY" "$plist"
  plutil -insert SURequireSignedFeed -bool YES "$plist"
  plutil -insert SUVerifyUpdateBeforeExtraction -bool YES "$plist"
fi
"${sign[@]}" "$app"
codesign --verify --deep --strict "$app"
echo "$app"
