# Changelog

## v0.3.0 — 2026-11-26

- Open **Voices** to clone a named voice from a recording or design one from a description. Preview a sample sentence and save the take you want to use again.
- Export a preview as WAV or share a reusable voice package. Imported voices keep their IDs, and you can select a server-wide default.
- Clients can list preset, cloned, and designed voices with `GET /v1/audio/voices` and select one for Realtime conversations or direct speech. The Hugging Face speech client can request WAV or 24 kHz PCM, including streaming PCM.
- The app and its guides now support general-purpose Realtime clients. The terminal launcher is `speech-hoster`. Earlier command names and voice packages still work.

## v0.2.3 — 2026-11-25

- Install **Speech2SpeechModelHoster.app** from the newly named DMG. The app now uses its own Application Support folder and downloads its runtime and models on first launch.

## v0.2.2 — 2026-11-25

- The app and installer now identify the project as Speech2SpeechModelHoster.
- The setup guide links to the project's GitHub releases and explains how to open the DMG on first launch.

## v0.2.1 — 2026-11-25

- Open the DMG and drag the app onto the Applications shortcut to install it. Existing release installations receive the same disk image through the in-app updater.

## v0.2.0 — 2026-11-25

- Run the speech server from a native Apple Silicon app. First launch sets up Python and the pinned speech models in your user Library.
- Switch between local and LAN access, copy the connection address, and see connected clients, conversation transcripts, and diagnostics.
- Install the macOS app from GitHub Releases. Enable automatic update checks or choose **Check for Updates…** in the app menu to install a signed update. Downloaded models carry over.

## 2026-11-04

- Added the terminal launchers for the local Hugging Face speech server, Mac model profiles, and Realtime connection diagnostics.
