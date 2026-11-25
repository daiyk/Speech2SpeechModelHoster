# Speech2SpeechModelHoster

Host speech recognition, language generation, and speech synthesis on an Apple Silicon Mac. The Reachy Mini Conversation App connects to the Mac over a Realtime WebSocket, sends microphone audio, and plays the spoken response.

Use **Reachy Mini Speech**, the macOS app included in Speech2SpeechModelHoster, or run the same backend from the terminal. Both use **`speech-to-speech==1.1.0`** for audio streaming, interruptions, conversation state, and tool calls.

```text
Reachy Mini Conversation App
  microphone / speaker / robot tools
          │ Realtime WebSocket
          ▼
Mac: Silero VAD → Parakeet TDT → Qwen3.5-4B (MLX, 4-bit) → Qwen3-TTS
          ws://<mac-address>:8765/v1/realtime
```

The pipeline comes from [Hugging Face speech-to-speech](https://github.com/huggingface/speech-to-speech). The [official Reachy app supports connecting directly to this server](https://github.com/pollen-robotics/reachy_mini_conversation_app#hugging-face-connection-modes).

The connection settings were checked against Reachy Conversation App 1.2.0, [commit `e901925`](https://github.com/pollen-robotics/reachy_mini_conversation_app/tree/e90192559149d6281d782c1c4aed39bb7d84bdef), on 2026-11-04. Physical robot validation is a separate step.

## macOS app

1. On an Apple Silicon Mac running macOS 14 or later, download the DMG ending in `macOS-arm64.dmg` from [Speech2SpeechModelHoster releases](https://github.com/daiyk/Speech2SpeechModelHoster/releases).
2. Open the DMG, drag **Reachy Mini Speech.app** onto **Applications**, eject the disk image, and open the app from Applications.
3. Allow at least 15 GB free for the first-launch Python and model downloads. Once setup finishes, choose **Start server**.

This project distributes an ad-hoc-signed app without Apple notarization. If macOS blocks the first launch because it cannot verify the developer, and you trust the download, choose **System Settings → Privacy & Security → Open Anyway** after the first launch attempt. [Apple’s first-launch instructions](https://support.apple.com/en-us/102445)

Choose **Reachy Mini Speech → Check for Updates…** for an immediate check, or
enable automatic checks when prompted. Updates preserve the downloaded models.
If you previously installed a local development copy, install the GitHub release
once to get the updater.

To build locally, use `./macos/build-dmg.sh` for the disk image,
`./macos/build.sh` for the app, or
`./macos/build-installer.sh` for the installer.
See the [app setup guide](docs/macos-app.md), [release instructions](docs/releases.md),
and [changelog](CHANGELOG.md).

## Set up once (terminal workflow)

Use an Apple Silicon Mac and install [uv](https://docs.astral.sh/uv/getting-started/installation/) first. This repository targets macOS; it does not provide a tested CUDA or Windows setup.

```bash
git clone https://github.com/daiyk/Speech2SpeechModelHoster.git
cd Speech2SpeechModelHoster
./scripts/setup.sh
```

Setup uses Python 3.12 and installs the Python environment and pinned packages; Python 3.11 is also supported. The **first server start downloads the models**, so do that while online before an experiment. Allow several GB of disk space for model files. Upstream's default Mac configuration targets approximately 16 GB unified memory; actual latency and available memory must be checked on the machine used for the study.

Launchers keep model/resource caches in this repository's ignored `.cache/` directory unless `HF_HOME`, `TORCH_HOME`, or `NLTK_DATA` is explicitly set. If you move to another Mac, run setup there and download or transfer the required model caches; copying a Python `.venv` between machines is not a reliable installation method.

## Start the server

Choose the launcher according to **where the Conversation App runs**:

| Conversation App location | Double-click | Endpoint entered in Reachy |
|---|---|---|
| On the same Mac, including a USB-connected robot | `Start Local Server.command` | `ws://127.0.0.1:8765/v1/realtime` |
| On a Reachy Mini Wireless or another computer | `Start LAN Server.command` | `ws://<mac-lan-ip>:8765/v1/realtime` |

Terminal equivalents:

```bash
./scripts/serve.sh
./scripts/serve.sh --lan
```

Wait for model loading and the server startup message before connecting. Keep the terminal open; press **Ctrl+C** to stop the server. One configured pipeline serves one connected conversation at a time, so disconnect diagnostic clients before connecting Reachy.

The LAN launcher listens on `0.0.0.0`; clients must use the Mac's actual LAN address, never `0.0.0.0`. Find it in **macOS System Settings → Wi-Fi → Details → TCP/IP**. Use the same network for the Mac and robot, and allow the server through the macOS firewall if prompted. This local endpoint has no authentication, so keep it on a trusted network.

## Point Reachy at the Mac

In the Conversation App, open **Settings → Connection**, choose the local server, and enter:

- `127.0.0.1:8765` if the Conversation App runs on this Mac.
- `<mac-lan-ip>:8765` if it runs on the robot or a different machine.

For a configuration-file installation, set these variables **in the Conversation App's environment**:

```dotenv
HF_REALTIME_CONNECTION_MODE=local
HF_REALTIME_WS_URL=ws://127.0.0.1:8765/v1/realtime
```

Replace `127.0.0.1` with the Mac's LAN IP when needed. No Hugging Face token or OpenAI key is required by this local backend.

**Reachy's saved UI settings take precedence over environment variables.** If it keeps using the hosted server, change the connection in the app's Settings view. Restart the conversation after switching endpoints.

## Check the installation and connection

From this repository:

```bash
.venv/bin/reachy-local doctor
.venv/bin/reachy-local check --url ws://127.0.0.1:8765/v1/realtime
```

Run the connection check while the server is running and Reachy is disconnected. A successful handshake confirms that the endpoint accepts a Reachy-style session; it does not measure recognition quality or prove that the robot's microphone and speaker work.

To exercise language generation and speech synthesis without a microphone:

```bash
.venv/bin/reachy-local check \
  --url ws://127.0.0.1:8765/v1/realtime \
  --speak "Say hello in one short sentence." \
  --wav /tmp/reachy-local-test.wav \
  --timeout 120
```

The optional WAV contains the returned mono, 16 kHz PCM16 audio. Choose a new output filename for each run; existing recordings are not overwritten. This check reports time to first received audio after a text request. It does **not** include speech recognition, voice activity detection, or the robot's playback delay.

You can also connect the upstream microphone/speaker client from the Mac:

```bash
.venv/bin/reachy-local talk
```

Use headphones for this check. macOS may request microphone permission. Quit this client before connecting Reachy.

Optional full pipeline check, with the server running and Reachy disconnected:

```bash
.venv/bin/python scripts/validate_pipeline.py --timeout 180
```

This generates a temporary spoken sample, streams it back through recognition and response generation, and completes a mock function-call/result cycle using Reachy's OpenAI SDK. It prints a JSON report without transcripts. It uses no microphone and controls no robot; physical audio, movements, and conversational latency still need validation on Reachy. Use `--url` to test another endpoint.

## Models and configuration

The default profile is [`src/reachy_local/profiles/mac.yaml`](src/reachy_local/profiles/mac.yaml). It uses the upstream Apple Silicon preset and an explicit `mlx-community/Qwen3.5-4B-4bit` language model. Copy the profile to customize it, then run `./scripts/serve.sh --config /path/to/profile.yaml`. Keep the `REACHY_SPEECH_HOST` and `REACHY_SPEECH_PORT` environment references in `runtime.server` so `--lan`, `--host`, and `--port` work. Conflicting literal listener settings are rejected. See the [upstream YAML guide](https://github.com/huggingface/speech-to-speech/blob/main/docs/configuration.md) for stage settings.

This uses the same backend project as Reachy's hosted service. The local default follows the official speech-to-speech Mac setup. [Reachy's configuration identifies Qwen3-ASR as its deployed recognizer](https://github.com/pollen-robotics/reachy_mini_conversation_app/blob/e90192559149d6281d782c1c4aed39bb7d84bdef/src/reachy_mini_conversation_app/config.py#L52), whereas this profile uses Parakeet. Hosted model choices and tuning can change independently; this local profile does not promise identical answers or voices.

Language coverage depends on both recognition and synthesis. In particular, the default Parakeet recognizer covers European languages. The alternative [`mac-qwen-asr.yaml`](src/reachy_local/profiles/mac-qwen-asr.yaml) profile uses Qwen3-ASR for broader language coverage, including CJK; validate recognition quality and latency for the selected language before use:

```bash
./scripts/serve.sh --config src/reachy_local/profiles/mac-qwen-asr.yaml
```

The default profile is intended for speech conversation. Camera reasoning and additional tool integrations need their own validation and may require another model/backend.

After all resources have been downloaded and a complete conversation has succeeded, test an offline restart:

```bash
./scripts/serve.sh --offline
```

Keep Wi-Fi enabled if the robot connects over the LAN. Offline mode disables Hugging Face Hub requests; any separately enabled internet tools still require their own connections.

## Verification

See the [validation record](docs/validation.md) for the completed automated and real-model checks, model snapshot revisions, and remaining hardware tests.

## Before an experiment

Use the [experiment checklist](docs/experiment-checklist.md) on the actual Mac and robot. Measure end-of-speech to audible reply, including slow turns and interruptions. Protocol compatibility alone is not an experimental readiness result.

## Troubleshooting

| Symptom | Check |
|---|---|
| Connection refused | Start the server, wait for models to load, and check the address and port. |
| Works on the Mac but not from Reachy Wireless | Use the LAN launcher and the Mac's LAN IP; check firewall access and Wi-Fi client isolation. |
| Reachy still uses the hosted service | Update its saved Connection setting; environment variables do not override saved UI choices. |
| Connection closes or reports no available pipeline | Stop other clients; the default profile has one conversation slot. |
| First start appears slow | Read the terminal output for model download/loading progress. Later starts use cached models. |
| Offline startup fails | Complete an online startup and conversation first so all selected model resources are cached. |
| Robot misunderstands speech or interrupts itself | Check the selected language, background noise, speaker volume, and Reachy's VAD/barge-in settings. |

The server runs in the foreground so its diagnostics remain visible. Do not change model versions or configuration during a study without recording and retesting the change.
