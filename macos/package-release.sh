#!/bin/bash
# Build the downloadable app and its matching, signed Sparkle feed.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${RELEASE_TAG:?Missing release tag}" "${GITHUB_REPOSITORY:?Missing GitHub owner/repository}"
: "${SPARKLE_DIR:?Run fetch-sparkle.sh first}" "${SPARKLE_PRIVATE_KEY:?Set the SPARKLE_PRIVATE_KEY Actions secret}"
notes=$(python3 macos/release_notes.py --tag "$RELEASE_TAG")
work=$(mktemp -d "${TMPDIR:-/tmp}/reachy-release.XXXXXX")
trap 'rm -rf "$work"' EXIT
assets="$work/assets"
mkdir -p "$assets"
public_key=$(printf '%s\n' "$SPARKLE_PRIVATE_KEY" | xcrun swift \
  -module-cache-path "${TMPDIR:-/tmp}/reachy-swift-cache" macos/sparkle-public-key.swift)
BUILD_DIR="$work/build" SPARKLE_PUBLIC_KEY="$public_key" ./macos/build.sh
app="$work/build/Reachy Mini Speech.app"
name="Reachy-Mini-Speech-$RELEASE_TAG-macOS-arm64"
if [[ -n ${CODE_SIGN_IDENTITY:-} ]]; then
  : "${APPLE_ID:?Missing notarization Apple ID}" "${APPLE_TEAM_ID:?Missing Apple team ID}"
  : "${APPLE_APP_PASSWORD:?Missing app-specific password}"
  ditto -c -k --keepParent "$app" "$work/notarize.zip"
  xcrun notarytool submit "$work/notarize.zip" --apple-id "$APPLE_ID" --team-id "$APPLE_TEAM_ID" \
    --password "$APPLE_APP_PASSWORD" --wait --timeout 30m --output-format json > "$work/notarization.json"
  if ! jq -e '.status == "Accepted"' "$work/notarization.json" >/dev/null; then
    cat "$work/notarization.json" >&2
    exit 1
  fi
  xcrun stapler staple "$app"
  xcrun stapler validate "$app"
  spctl --assess --type execute "$app"
fi
ditto -c -k --sequesterRsrc --keepParent "$app" "$assets/$name.zip"
printf '%s\n' "$notes" > "$assets/$name.md"
printf '%s\n' "$SPARKLE_PRIVATE_KEY" | "$SPARKLE_DIR/bin/generate_appcast" \
  --ed-key-file - --embed-release-notes --maximum-deltas 0 \
  --download-url-prefix "https://github.com/$GITHUB_REPOSITORY/releases/download/$RELEASE_TAG/" \
  "$assets"
printf '%s\n' "$SPARKLE_PRIVATE_KEY" | "$SPARKLE_DIR/bin/sign_update" \
  --ed-key-file - --verify "$assets/appcast.xml"
signature=$(xmllint --xpath 'string(/rss/channel/item/enclosure/@*[local-name()="edSignature"])' "$assets/appcast.xml")
test -n "$signature"
printf '%s\n' "$SPARKLE_PRIVATE_KEY" | "$SPARKLE_DIR/bin/sign_update" \
  --ed-key-file - --verify "$assets/$name.zip" "$signature"
out="${RELEASE_OUTPUT_DIR:-$PWD/dist/releases/$RELEASE_TAG}"
mkdir -p "$out"
cp "$assets/$name.zip" "$assets/appcast.xml" "$out/"
cp "$assets/$name.md" "$out/release-notes.md"
echo "$out"
