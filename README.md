# Speech2SpeechModelHoster

Host Hugging Face’s speech-to-speech pipeline on an Apple Silicon Mac. Microphone clients can stream audio over a Realtime WebSocket and receive spoken replies. Applications can also send text over HTTP to synthesize speech in a selected voice.

The macOS app and terminal launcher use the same pinned `speech-to-speech==1.1.0` server for audio streaming, interruptions, conversation state, and tool calls. [Hugging Face speech-to-speech](https://github.com/huggingface/speech-to-speech)

```text
Realtime client (microphone, speaker, optional tools)
          │ ws://<mac-address>:8765/v1/realtime
          ▼
Mac: Silero VAD → Parakeet TDT → Qwen3.5-4B (MLX, 4-bit) → Qwen3-TTS
```

## macOS app

1. On an Apple Silicon Mac running macOS 14 or later, download the latest `Speech2SpeechModelHoster-vX.Y.Z-macOS-arm64.dmg` from [Speech2SpeechModelHoster releases](https://github.com/daiyk/Speech2SpeechModelHoster/releases).
2. Open the DMG, drag **Speech2SpeechModelHoster.app** onto **Applications**, eject the disk image, and open the app from Applications.
3. Allow at least 15 GB free for the first-launch Python and model downloads. Once setup finishes, choose **Start server**.

This project distributes an ad-hoc-signed app without Apple notarization. If macOS blocks the first launch because it cannot verify the developer, and you trust the download, choose **System Settings → Privacy & Security → Open Anyway** after the first launch attempt. [Apple’s first-launch instructions](https://support.apple.com/en-us/102445)

Choose **Speech2SpeechModelHoster → Check for Updates…** for an immediate check, or
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

Choose the launcher according to **where the client runs**:

| Client location | Double-click | Client endpoint |
|---|---|---|
| On the same Mac | `Start Local Server.command` | `ws://127.0.0.1:8765/v1/realtime` |
| On another device on the LAN | `Start LAN Server.command` | `ws://<mac-lan-ip>:8765/v1/realtime` |

Terminal equivalents:

```bash
./scripts/serve.sh
./scripts/serve.sh --lan
```

Wait for model loading and the server startup message before connecting. Keep the terminal open; press **Ctrl+C** to stop the server. One configured pipeline serves one connected conversation at a time, so disconnect diagnostic clients before connecting another client.

The LAN launcher listens on `0.0.0.0`; clients must use the Mac's actual LAN address, never `0.0.0.0`. Find it in **macOS System Settings → Wi-Fi → Details → TCP/IP**. Use the same network for the Mac and client, and allow the server through the macOS firewall if prompted. This local endpoint has no authentication, so keep it on a trusted network.

## Speak supplied text directly

With the server running, send a short message to `POST /v1/audio/speech`. Qwen3-TTS speaks the supplied text without a conversation or an LLM call. By default the caller receives a mono 16 kHz PCM16 WAV and controls playback.

```bash
curl --fail --silent --show-error http://127.0.0.1:8765/v1/audio/speech \
  -H 'Content-Type: application/json' \
  -d '{"input":"Welcome. The session is ready to begin."}' \
  -o speech.wav
afplay speech.wav
```

Only `input` is required (1–500 characters, including at least one non-whitespace character). The voice defaults to the server’s selected voice (initially Aiden). To select a preset or a saved voice, set `voice` to its catalogue ID. Existing preset names such as `Vivian` are case-insensitive.

Hugging Face’s HTTP TTS backend (`--tts openai`) can point its `--openai_tts_base_url` to `http://127.0.0.1:8765/v1` and use its standard Qwen settings. The endpoint accepts the original `Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice` model ID and the local `qwen3-tts` alias. With `response_format="pcm"`, it returns raw **24 kHz mono signed 16-bit little-endian PCM**. The adapter’s `stream_format="audio"` and optional `stream=true` work with PCM. WAV remains available for file playback.

The terminal server and builds of the macOS app from this checkout expose this route on the same host and port as Realtime. Both load the full pipeline at startup. Direct requests can be made while a Realtime client is connected. Each request chooses its own voice. In LAN mode, replace `127.0.0.1` with the Mac's LAN IP.

## Create and use voices

Start the server in the Mac app and open **Voices**.

- **Clone voice** accepts up to 30 seconds of M4A (including Voice Memos), WAV, AIFF, FLAC, or MP3 audio. Name the voice and check the words in the transcript. With the default Parakeet profile, the app transcribes the recording for you.
- **Design voice** takes a description and a reference sentence. Generate and replay takes until you find one you like. **Save voice** keeps that take and its transcript. When speaking new text, the Base model uses the saved reference. Delivery can vary slightly between utterances.
- **Play voice preview** speaks “Hello! It is nice to meet you.” You can also enter your own sentence. **Export audio** saves the selected library voice’s current preview as a WAV. **Export voice** saves a portable `.s2svoice` file containing the reference audio, transcript, name, type, and model details. **Import** restores the voice with the same ID on another Mac running this server. Importing the same package again is safe.
- **Use as server default** selects the voice for clients that omit a voice. Clients that specify a voice take precedence. Saved voices and the default persist across restarts in `~/Library/Application Support/Speech2SpeechModelHoster/voices` (or under `SPEECH_HOSTER_HOME`).

The first design downloads the pinned Qwen3-TTS 1.7B VoiceDesign model. Previewing or speaking a cloned or designed voice downloads the 1.7B Base model. Both are 6-bit MLX models, cached locally. Voice design and cloning share one additional model slot in memory.

**Client discovery and selection**

`GET /v1/audio/voices` returns `types`, `default_voice`, and a `voices` array. Each entry has an `id`, display `name`, and `type` of `preset`, `cloned`, or `designed`. Use the returned ID even when two voices share a name.

```bash
curl http://127.0.0.1:8765/v1/audio/voices
```

For direct speech, send the ID in the `voice` field of `POST /v1/audio/speech`. For Realtime, send a `session.update` before requesting speech, replacing `<voice-id>` with an ID from the catalogue.

```json
{"type":"session.update","session":{"type":"realtime","audio":{"output":{"voice":"<voice-id>"}}}}
```

The bundled CLI also accepts `speech-hoster talk --voice <voice-id>` and `speech-hoster check --voice <voice-id> --speak "Say hello"`. Clients on the LAN can list voices and speak with them. Creating, importing, and exporting voice references is available on the host Mac.

## Connect a Hugging Face client

The original microphone client can connect directly to the running server:

```sh
.venv/bin/speech-to-speech talk --url ws://127.0.0.1:8765/v1/realtime
```

For an SDK integration, point the HTTP base at `http://<host>:8765/v1` and the WebSocket base at `ws://<host>:8765/v1`, then connect with `model="local"`. The SDK accepts a placeholder API key for this local endpoint. See the [client environment example](client.env.example). A client may omit the voice and audio format just as the upstream client does. The upstream default is 16 kHz mono PCM for Realtime audio. [Hugging Face Realtime example](https://github.com/huggingface/speech-to-speech#realtime-api)

## Check the installation and connection

From this repository:

```bash
.venv/bin/speech-hoster doctor
.venv/bin/speech-hoster check --url ws://127.0.0.1:8765/v1/realtime
```

Run the connection check while the server is running with a free conversation slot. A successful handshake confirms that the server accepts the upstream session request.

To exercise language generation and speech synthesis without a microphone:

```bash
.venv/bin/speech-hoster check \
  --url ws://127.0.0.1:8765/v1/realtime \
  --speak "Say hello in one short sentence." \
  --wav /tmp/speech-hoster-test.wav \
  --timeout 120
```

The optional WAV contains the returned mono, 16 kHz PCM16 audio. Choose a new output filename for each run; existing recordings are not overwritten. This check reports time to first received audio after a text request. It does **not** include speech recognition, voice activity detection, or client playback delay.

You can also connect the upstream microphone/speaker client from the Mac:

```bash
.venv/bin/speech-hoster talk
```

Use headphones for this check. macOS may request microphone permission. Quit this client before connecting another client.

Optional full pipeline check, with the server running and a free conversation slot:

```bash
.venv/bin/python scripts/validate_pipeline.py --timeout 180
```

This generates a temporary spoken sample, streams it through recognition and response generation, and completes a function call with a simulated client result using the OpenAI SDK. It prints a JSON report without transcripts. Use `--url` to test another endpoint.

## Models and configuration

The default profile is [`src/speech_hoster/profiles/mac.yaml`](src/speech_hoster/profiles/mac.yaml). It uses the upstream Apple Silicon preset and an explicit `mlx-community/Qwen3.5-4B-4bit` language model. Copy the profile to customize it, then run `./scripts/serve.sh --config /path/to/profile.yaml`. Keep the `SPEECH_HOSTER_HOST` and `SPEECH_HOSTER_PORT` environment references in `runtime.server` so `--lan`, `--host`, and `--port` work. Conflicting literal listener settings are rejected. See the [upstream YAML guide](https://github.com/huggingface/speech-to-speech/blob/main/docs/configuration.md) for stage settings.

Language coverage depends on both recognition and synthesis. In particular, the default Parakeet recognizer covers European languages. The alternative [`mac-qwen-asr.yaml`](src/speech_hoster/profiles/mac-qwen-asr.yaml) profile uses Qwen3-ASR for broader language coverage, including CJK; validate recognition quality and latency for the selected language before use:

```bash
./scripts/serve.sh --config src/speech_hoster/profiles/mac-qwen-asr.yaml
```

The default profile is intended for speech conversation. Camera reasoning and additional tool integrations need their own validation and may require another model/backend.

After all resources have been downloaded and a complete conversation has succeeded, test an offline restart:

```bash
./scripts/serve.sh --offline
```

Keep Wi-Fi enabled if a client connects over the LAN. Offline mode disables Hugging Face Hub requests; any separately enabled internet tools still require their own connections.

## Verification

See the [validation record](docs/validation.md) for the completed automated and real-model checks, model snapshot revisions, and remaining hardware tests.

## Before an experiment

Use the [experiment checklist](docs/experiment-checklist.md) on the intended server and client devices. Measure end-of-speech to audible reply, including slow turns and interruptions. Protocol compatibility alone is not an experimental readiness result.

## Troubleshooting

| Symptom | Check |
|---|---|
| Connection refused | Start the server, wait for models to load, and check the address and port. |
| Works on the Mac but not from a LAN client | Use the LAN launcher and the Mac's LAN IP; check firewall access and Wi-Fi client isolation. |
| Connection closes or reports no available pipeline | Stop other clients; the default profile has one conversation slot. |
| First start appears slow | Read the terminal output for model download/loading progress. Later starts use cached models. |
| Offline startup fails | Complete an online startup and conversation first so all selected model resources are cached. |
| Recognition misses speech or playback triggers interruptions | Check the selected language, background noise, speaker volume, and the client’s turn-detection settings. |

The server runs in the foreground so its diagnostics remain visible. Do not change model versions or configuration during a study without recording and retesting the change.
