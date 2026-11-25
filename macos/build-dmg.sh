#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
output=${1:-"$PWD/dist/Reachy Mini Speech.dmg"}
work=$(mktemp -d "${TMPDIR:-/tmp}/reachy-dmg.XXXXXX")
trap 'rm -rf "$work"' EXIT

BUILD_DIR="$work/build" ./macos/build.sh
mkdir "$work/volume"
mv "$work/build/Reachy Mini Speech.app" "$work/volume/"
ln -s /Applications "$work/volume/Applications"
image="$work/Reachy Mini Speech.dmg"
hdiutil create -fs APFS -format ULFO -volname "Reachy Mini Speech" \
  -srcfolder "$work/volume" "$image"
if [[ -n ${CODE_SIGN_IDENTITY:-} ]]; then
  codesign --sign "$CODE_SIGN_IDENTITY" --timestamp --identifier local.reachy.speech.dmg "$image"
  codesign --verify --strict "$image"
fi
mkdir -p "$(dirname "$output")"
mv "$image" "$output"
echo "$output"
