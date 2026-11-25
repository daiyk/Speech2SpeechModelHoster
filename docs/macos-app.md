# Speech2SpeechModelHoster on macOS

The desktop app appears in Finder as **Reachy Mini Speech.app**. It hosts the speech models on your Mac and displays the address to enter in the Reachy Mini Conversation App.

## Implementation plan and result

1. Native SwiftUI app: Start/Stop, local/LAN selection, endpoint copy, current
   activity, bounded live log, accepted WebSocket clients with peer addresses.
2. Private first-launch bootstrap: pinned uv 0.13.7 installer, managed Python
   3.12, locked Python packages. No Homebrew or preinstalled Python required.
3. Pinned default pipeline: download immutable Hugging Face snapshots and use
   revision-specific local aliases. Pin Silero's Torch Hub source commit too.
4. Passive ASGI observer: forward frames unchanged; track accept/disconnect,
   show text/transcript and request events, omit encoded audio payloads.
5. Validate configuration, lifecycle observation, native compilation, installer,
   and a real audio/tool round trip. Distribute an ad-hoc-signed local build.

## Build and use

For an install that receives updates, download the DMG, drag the app onto
Applications, and launch it from Applications. Choose **Reachy Mini Speech →
Check for Updates…** for later releases. [Download from Speech2SpeechModelHoster](https://github.com/daiyk/Speech2SpeechModelHoster/releases)

On an Apple Silicon developer Mac with Xcode command-line tools:

```sh
./macos/build.sh
open "dist/Reachy Mini Speech.app"
```

Copy the built app to Applications on another Apple Silicon Mac. The recipient
needs neither Xcode, Python, uv, nor this repository. macOS 14 or newer is the
app's deployment target; specific MLX kernels and hardware still need validation
on the target Mac. Plan for at least 16 GB RAM and 15 GB free disk space.

The first launch prepares the environment and default model snapshots. Press
**Start server** to load the models and listen on port 8765. Watch for **Running**
before connecting Reachy. Further VAD/NLTK resources may download at first Start.
Setup/download failures appear in the log; Start retries the operation. Stop
cancels setup or inference. Closing the last window or quitting stops the worker
and its process group; Stop allows five seconds before forced termination.

Local mode binds 127.0.0.1. LAN mode binds 0.0.0.0; enter the Mac's LAN address in
Reachy's connection settings. LAN service has no authentication. The client list
shows accepted sockets, not device identities; the upstream pipeline supports one
conversation at a time. Rejected connections are not counted.

Runtime files live in `~/Library/Application Support/Reachy Mini Speech/`:
private uv, Python, virtual environment, bundled source copy, model aliases and
caches. Nothing is installed into Homebrew or shell profiles. Moving the app
preserves this data. `REACHY_APP_HOME` overrides this directory for testing.

Logs include conversation text and requests in a bounded in-memory UI buffer;
the app does not persist them. Clear removes the displayed log and current
activity. Audio payloads are omitted. Upstream operational diagnostics are shown
alongside protocol events. This app has no microphone client; Reachy supplies
audio through the existing Realtime endpoint.

## Model lock

The desktop model lock is in `src/reachy_local/desktop.py`:

| Component | Revision |
| --- | --- |
| Parakeet TDT v3 | ed2b7e8c15f9aaa0b5772e2efb986255eaef7e15 |
| Qwen3.5 4B 4-bit | 0e7ffd5c629ef7719d4cbc04069232580bfa9d9c |
| Qwen3-TTS CustomVoice 6-bit | 1c6c0ff58c43afa8df571facde2efa077efd85e2 |
| Smart Turn v3.2 | f766f81d3cfdf7737ac64aad813d91bbfd56bf93 |
| Silero VAD source and bundled weights | 066409f3d9db45a30d21dfcbf9147826ffdd7052 |

The original CLI/custom YAML workflow is unchanged and its model IDs remain
unpinned. The desktop app intentionally ships the validated default Parakeet
pipeline only. NLTK auxiliary data and the Python 3.12 patch release are not
model weights and are not revision-pinned. Internet tools are not enabled.

## Validation (2026-11-11)

- 58 Python tests passed, including model revision propagation and ASGI frame
  preservation, rejected connections and cleanup on exceptions.
- Ruff and shell syntax checks passed.
- Swift app compiled; bundle plist and ad-hoc signature validated.
- Private uv installer ran successfully in a temporary application directory.
  Managed Python provisioning and locked dependency installation were exercised.
  Existing model caches were reused; this is not a fresh physical Mac test.
- Real pinned pipeline started and completed text-to-audio, audio-to-response,
  and mock function-call/result cycles. First audio on the measured warmed
  request arrived in 0.759 seconds; this is not a hardware benchmark.
- Accepted/disconnected sessions and transcript events observed in the monitor.
- Native UI verified: Start reached Running, a connected client and its message
  appeared, and Stop returned to Stopped with zero clients (worker exit 0).
- Managed Python 3.12.16 downloaded automatically in the isolated app directory;
  the installed app environment loaded the full pipeline successfully.

The app uses an in-process hook around upstream 1.1.0's ASGI app factory and
Silero loader. Keep integration tests when updating upstream. A new physical Mac,
physical Reachy, LAN/firewall behavior, and sustained sessions remain to be tested.

## Icon and interface update

The generated robot-and-waveform icon is stored in `macos/Assets/AppIcon.png`.
Its prompt and provenance are in `macos/Assets/README.md`. The build produces
all macOS icon sizes and embeds both the ICNS Finder/Dock icon and the PNG used
in the sidebar.

The sidebar contains server controls, local/LAN access, actual selectable LAN
addresses, Copy URL, and connected clients. Conversation displays completed
user/assistant messages with timestamps; protocol and startup logs are in a
separate searchable Diagnostics view. Follow latest can be disabled to inspect
history. Each view has its own Clear action. Startup and errors have a dedicated
banner. Closing the app still stops its worker.

Validation: native compilation/signature checks, 58 Python tests, and focused
Swift checks for chunked message parsing, transcripts, client cleanup, and LAN
URLs passed. Visual review verified the icon, final layout, setup cancellation,
and actual LAN addresses. The Swift checks can be run with:

```sh
xcrun swiftc -parse-as-library -D MODEL_TEST macos/ReachySpeech.swift \
  tests/macos_model.swift -o /tmp/reachy-model-checks \
  -target arm64-apple-macos14.0 -framework SwiftUI -framework AppKit
/tmp/reachy-model-checks
```

## Installer

Build the native macOS installer with `./macos/build-installer.sh`. This rebuilds
the app and creates `dist/Reachy Mini Speech Installer.pkg` (about 3.6 MB).
Double-click the package and follow Installer. It requires administrator
authorization to install into `/Applications`, targets Apple Silicon and macOS
14+, and never relocates installation to a development copy elsewhere.
Quit the running app before installing an update.

The package has no install-time scripts or downloads. Open the installed app to
perform first-launch runtime/model setup as the logged-in user. Existing user
model caches and settings are preserved. This local package is unsigned and the
app is ad-hoc signed. For the public DMG and first-launch instructions, see the
[installation guide](../README.md#macos-app).

Validation: expanded the product package, checked its Applications payload and
non-relocatable upgrade metadata, verified the extracted app's signature, and
successfully queried Installer's choices. No system installation was performed.
