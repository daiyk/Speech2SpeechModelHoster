#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
output=${1:-"$PWD/dist/Speech2SpeechModelHoster.dmg"}
work=$(mktemp -d "${TMPDIR:-/tmp}/speech-dmg.XXXXXX")
trap 'rm -rf "$work"' EXIT

BUILD_DIR="$work/build" ./macos/build.sh
mkdir "$work/volume"
mv "$work/build/Speech2SpeechModelHoster.app" "$work/volume/"
ln -s /Applications "$work/volume/Applications"
image="$work/Speech2SpeechModelHoster.dmg"
hdiutil create -fs APFS -format ULFO -volname "Speech2SpeechModelHoster" \
  -srcfolder "$work/volume" "$image"
if [[ -n ${CODE_SIGN_IDENTITY:-} ]]; then
  codesign --sign "$CODE_SIGN_IDENTITY" --timestamp --identifier io.github.daiyk.Speech2SpeechModelHoster.dmg "$image"
  codesign --verify --strict "$image"
fi
mkdir -p "$(dirname "$output")"
mv "$image" "$output"
echo "$output"
