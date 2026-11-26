# Validation record

## Hugging Face client compatibility · 2026-11-26

The server embedded in the locally built Mac app ran with cached weights. Both client checks used the installed upstream `speech-to-speech==1.1.0` package over loopback.

- **Realtime.** The stock session request omitted the voice and audio format. Generated speech passed through VAD and transcription, and the SDK received a spoken reply. A function call, its client result, and the spoken continuation completed on the same connection. A separate stock session explicitly selected Vivian and 24 kHz PCM and received audio.
- **HTTP speech.** The upstream `OpenAICompatibleTTSHandler` completed its warmup and decoded a subsequent utterance using its default Qwen model name and raw 24 kHz PCM. Separate runs exercised streaming PCM, WAV with language and style instructions, and 1.25× speed.
- **Build.** The Mac app and installer built locally. The native model checks and 73 Python tests passed.

These checks exercised the WebSocket and HTTP transports on one Mac.

## Initial pipeline validation · 2026-11-04

Environment: Apple M5 Max MacBook Pro, 64 GB unified memory, CPython 3.12.13,
`speech-to-speech==1.1.0`, `openai==2.28.0`. The default Mac profile was used.

## Completed checks

- Locked dependency installation and upstream configuration validation for both profiles.
- 54 automated tests: a real loopback WebSocket transport with simulated server events,
  malformed/error responses, bounded deadlines, PCM negotiation, WAV handling,
  upstream YAML resolution, and launcher argument/environment behavior.
- Ruff lint and formatting checks; shell script syntax checks.
- Real model startup and Realtime session negotiation.
- Offline-mode restart from the final repository location with cached models, followed
  by a successful `scripts/validate_pipeline.py` audio and tool round trip. The Mac
  remained network-connected; this tested offline flags and cached resources, not
  an OS-level network isolation test.
- Text-triggered speech generation, returning mono 16 kHz PCM16 audio.
- Generated speech streamed back as microphone-format audio through VAD and Parakeet;
  a nonempty transcript and a new spoken reply were received.
- A `get_test_value` function call, client-side simulated result, and spoken continuation.

One warmed text-to-speech request received its first audio after 0.784 seconds.
The final-location smoke test received its first source audio after 0.629 seconds.
These are individual smoke-test measurements on this Mac. It excludes input speech
recognition and client playback, and is not an M5 Pro or experiment latency benchmark.

## Model snapshots observed

| Model | Hugging Face revision |
|---|---|
| `mlx-community/parakeet-tdt-0.6b-v3` | `ed2b7e8c15f9aaa0b5772e2efb986255eaef7e15` |
| `mlx-community/Qwen3.5-4B-4bit` | `0e7ffd5c629ef7719d4cbc04069232580bfa9d9c` |
| `mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-6bit` | `1c6c0ff58c43afa8df571facde2efa077efd85e2` |
| `pipecat-ai/smart-turn-v3` | `f766f81d3cfdf7737ac64aad813d91bbfd56bf93` |

Upstream also caches Silero VAD through Torch Hub. Python dependencies are frozen
in `uv.lock`; model IDs in the profiles are not revision pins. Preserve the model
cache or use fixed local snapshot paths when a study requires identical weights.

## Remaining physical validation

LAN connectivity, microphone echo, interruptions, and sustained sessions on a physical client were outside these checks. The Qwen3-ASR
alternative passed configuration validation but was not loaded for inference.
Use the [experiment checklist](experiment-checklist.md) before participant sessions.

## Run the automated checks

```bash
./scripts/setup.sh
.venv/bin/pytest -q
.venv/bin/ruff check src tests scripts
.venv/bin/ruff format --check src tests scripts
```

Use `.venv/bin/…` after setup, or include `--extra server` in any `uv run`/`uv sync`
command. A plain `uv sync` omits the optional inference backend.
