#!/bin/bash
# Build a native Installer package. No install-time scripts or network downloads.
set -euo pipefail
cd "$(dirname "$0")/.."
./macos/build.sh
app="$PWD/dist/Speech2SpeechModelHoster.app"
version=$(/usr/libexec/PlistBuddy -c 'Print CFBundleShortVersionString' "$app/Contents/Info.plist")
work=$(mktemp -d "${TMPDIR:-/tmp}/reachy-installer.XXXXXX")
trap 'rm -rf "$work"' EXIT
mkdir -p "$work/root/Applications" "$work/resources"
ditto "$app" "$work/root/Applications/Speech2SpeechModelHoster.app"
pkgbuild --analyze --root "$work/root" "$work/components.plist"
# Always install in Applications, even if a development copy exists elsewhere.
/usr/libexec/PlistBuddy -c 'Add :0:BundleIsRelocatable bool false' "$work/components.plist"
pkgbuild --root "$work/root" --component-plist "$work/components.plist" \
  --identifier io.github.daiyk.Speech2SpeechModelHoster.installer --version "$version" \
  --install-location / --ownership recommended "$work/application.pkg"
cat > "$work/resources/welcome.html" <<'HTML'
<html><body style="font-family:-apple-system;font-size:14px;color:#222">
<h1>Speech2SpeechModelHoster</h1>
<p>Speech2SpeechModelHoster runs the speech models on this Mac for the Reachy Mini Conversation App.</p>
<p>This installer places Speech2SpeechModelHoster in your Applications folder.</p>
<ul><li>Apple Silicon Mac, macOS 14 or later</li>
<li>At least 16 GB memory recommended</li>
<li>Allow at least 15 GB free space for the runtime and models</li></ul>
<p>On first launch, the app downloads Python, its dependencies, and pinned
speech models. Keep your Mac online while setup completes.</p>
<p>Quit any running copy of Speech2SpeechModelHoster before continuing.</p>
</body></html>
HTML
cat > "$work/resources/conclusion.html" <<'HTML'
<html><body style="font-family:-apple-system;font-size:14px;color:#222">
<h1>Ready for first launch</h1>
<p>Open <b>Applications → Speech2SpeechModelHoster</b>.</p>
<p>Wait for automatic setup, then select <b>Start server</b>. When the server
is online, copy the connection URL into the Reachy conversation app.</p>
<p>Your runtime and model cache are kept in your user Library's Application
Support folder. Updating the app preserves these files.</p>
</body></html>
HTML
cat > "$work/distribution.xml" <<XML
<?xml version="1.0" encoding="utf-8"?>
<installer-gui-script minSpecVersion="2">
  <title>Speech2SpeechModelHoster</title>
  <welcome file="welcome.html"/>
  <conclusion file="conclusion.html"/>
  <options customize="never" require-scripts="false" hostArchitectures="arm64"/>
  <domains enable_localSystem="true" enable_currentUserHome="false" enable_anywhere="false"/>
  <volume-check><allowed-os-versions><os-version min="14.0"/></allowed-os-versions></volume-check>
  <choices-outline><line choice="app"/></choices-outline>
  <choice id="app" visible="false" title="Speech2SpeechModelHoster">
    <pkg-ref id="io.github.daiyk.Speech2SpeechModelHoster.installer"/>
  </choice>
  <pkg-ref id="io.github.daiyk.Speech2SpeechModelHoster.installer" version="$version" onConclusion="none">application.pkg</pkg-ref>
</installer-gui-script>
XML
output="$PWD/dist/Speech2SpeechModelHoster Installer.pkg"
productbuild --distribution "$work/distribution.xml" --resources "$work/resources" \
  --package-path "$work" "$output"
echo "$output"
