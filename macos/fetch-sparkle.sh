#!/bin/bash
set -euo pipefail
destination=${1:?Usage: fetch-sparkle.sh DIRECTORY}
version=2.10.1
sha256=1a856d2a9edb8e628de88121d7be04cf0e2167f8641650b78fca00b14244cf27
mkdir -p "$destination"
cd "$destination"
archive="Sparkle-$version.tar.xz"
curl --fail --location --silent --show-error --retry 3 \
  "https://github.com/sparkle-project/Sparkle/releases/download/$version/$archive" -o "$archive"
echo "$sha256  $archive" | shasum -a 256 --check
tar -xJf "$archive" ./Sparkle.framework ./bin ./LICENSE
