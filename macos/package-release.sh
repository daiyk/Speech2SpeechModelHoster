#!/bin/bash
# Build the downloadable app and its matching, signed Sparkle feed.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${RELEASE_TAG:?Missing release tag}" "${GITHUB_REPOSITORY:?Missing GitHub owner/repository}"
: "${SPARKLE_DIR:?Run fetch-sparkle.sh first}" "${SPARKLE_PRIVATE_KEY:?Set the SPARKLE_PRIVATE_KEY Actions secret}"
notes=$(python3 macos/release_notes.py --tag "$RELEASE_TAG")
work=$(mktemp -d "${TMPDIR:-/tmp}/speech-release.XXXXXX")
trap 'rm -rf "$work"' EXIT
assets="$work/assets"
mkdir -p "$assets"
public_key=$(printf '%s\n' "$SPARKLE_PRIVATE_KEY" | xcrun swift \
  -module-cache-path "${TMPDIR:-/tmp}/speech-swift-cache" macos/sparkle-public-key.swift)
name="Speech2SpeechModelHoster-$RELEASE_TAG-macOS-arm64"
dmg="$assets/$name.dmg"
SPARKLE_PUBLIC_KEY="$public_key" ./macos/build-dmg.sh "$dmg"
if [[ -n ${CODE_SIGN_IDENTITY:-} ]]; then
  : "${APPLE_ID:?Missing notarization Apple ID}" "${APPLE_TEAM_ID:?Missing Apple team ID}"
  : "${APPLE_APP_PASSWORD:?Missing app-specific password}"
  xcrun notarytool submit "$dmg" --apple-id "$APPLE_ID" --team-id "$APPLE_TEAM_ID" \
    --password "$APPLE_APP_PASSWORD" --wait --timeout 30m --output-format json > "$work/notarization.json"
  if ! jq -e '.status == "Accepted"' "$work/notarization.json" >/dev/null; then
    cat "$work/notarization.json" >&2
    exit 1
  fi
  xcrun stapler staple "$dmg"
  xcrun stapler validate "$dmg"
  spctl --assess --type open --context context:primary-signature "$dmg"
fi
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
  --ed-key-file - --verify "$dmg" "$signature"
out="${RELEASE_OUTPUT_DIR:-$PWD/dist/releases/$RELEASE_TAG}"
mkdir -p "$out"
cp "$dmg" "$assets/appcast.xml" "$out/"
cp "$assets/$name.md" "$out/release-notes.md"
echo "$out"
