"""Exercise the same GA Realtime session contract used by Reachy's HF client."""

from __future__ import annotations

import asyncio
import base64
import json
import math
import time
import wave
from pathlib import Path
from urllib.parse import urlsplit

from websockets.asyncio.client import connect

DEFAULT_URL = "ws://127.0.0.1:8765/v1/realtime"
SAMPLE_RATE = 16000


def validate_url(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in {"ws", "wss"} or not parsed.hostname:
        raise ValueError("Use a ws:// or wss:// URL with a hostname.")
    if parsed.path != "/v1/realtime" or parsed.fragment or parsed.username or parsed.password:
        raise ValueError("Use the full /v1/realtime endpoint without credentials or a fragment.")
    # Accessing port also validates malformed/out-of-range values.
    _ = parsed.port
    return url


def reachy_session() -> dict:
    return {
        "type": "realtime",
        "instructions": "You are Reachy Mini. Give a short spoken answer in one sentence.",
        "audio": {
            "input": {
                "format": {"type": "audio/pcm", "rate": None},
                "transcription": {"model": "gpt-4o-transcribe", "language": "auto"},
                "turn_detection": {"type": "server_vad", "interrupt_response": True},
            },
            "output": {"format": {"type": "audio/pcm", "rate": None}, "voice": "Aiden"},
        },
        "tools": [],
        "tool_choice": "auto",
    }


class ProbeError(RuntimeError):
    """The endpoint failed a required part of the Reachy contract."""


async def _receive(ws) -> dict:
    event = json.loads(await ws.recv())
    if not isinstance(event, dict):
        raise ProbeError("Endpoint returned a non-object event.")
    if event.get("type") == "error":
        error = event.get("error", {})
        code = error.get("code") or error.get("type") or "unknown"
        raise ProbeError(f"Endpoint error: {code}. Check server logs; disconnect other clients.")
    return event


async def _until(ws, event_type: str) -> dict:
    while True:
        event = await _receive(ws)
        if event.get("type") == event_type:
            return event


async def probe(
    url: str = DEFAULT_URL,
    *,
    speak: str | None = None,
    wav_path: Path | None = None,
    timeout: float = 120,
) -> dict:
    validate_url(url)
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Timeout must be finite and positive.")
    if speak is not None and not speak.strip():
        raise ValueError("Speech test text must not be empty.")
    if wav_path is not None and speak is None:
        raise ValueError("--wav requires --speak.")
    if wav_path is not None and wav_path.exists():
        raise FileExistsError(f"Recording already exists: {wav_path}")

    # One total deadline: a live stream of unrelated events cannot hang the check.
    async with asyncio.timeout(timeout):
        async with connect(url, proxy=None, open_timeout=min(timeout, 15), max_size=8 << 20) as ws:
            await _until(ws, "session.created")
            await ws.send(json.dumps({"type": "session.update", "session": reachy_session()}))
            updated = await _until(ws, "session.updated")
            audio = updated.get("session", {}).get("audio", {})
            for direction in ("input", "output"):
                audio_format = audio.get(direction, {}).get("format", {})
                if (
                    audio_format.get("type") != "audio/pcm"
                    or "rate" not in audio_format
                    or audio_format["rate"] not in (None, SAMPLE_RATE)
                ):
                    raise ProbeError(f"Endpoint did not negotiate native 16 kHz PCM {direction}.")

            result = {"session_configured": True, "speech_tested": False}
            if speak is None:
                return result
            await ws.send(
                json.dumps(
                    {
                        "type": "conversation.item.create",
                        "item": {
                            "type": "message",
                            "role": "user",
                            "content": [{"type": "input_text", "text": speak}],
                        },
                    }
                )
            )
            started = time.monotonic()
            await ws.send(json.dumps({"type": "response.create"}))
            audio_chunks: list[bytes] = []
            first_audio = None
            audio_bytes = 0
            while True:
                event = await _receive(ws)
                event_type = event.get("type")
                if event_type == "response.output_audio.delta":
                    chunk = base64.b64decode(event.get("delta", ""), validate=True)
                    if not chunk or len(chunk) % 2:
                        raise ProbeError("Endpoint returned empty or invalid PCM16 audio.")
                    if first_audio is None:
                        first_audio = time.monotonic() - started
                    audio_bytes += len(chunk)
                    if audio_bytes > SAMPLE_RATE * 2 * 300:
                        raise ProbeError("Speech test exceeded five minutes of audio.")
                    if wav_path is not None:
                        audio_chunks.append(chunk)
                elif event_type == "response.done":
                    if event.get("response", {}).get("status") != "completed":
                        raise ProbeError("Response did not complete successfully.")
                    if first_audio is None:
                        raise ProbeError("Response completed without GA output audio events.")
                    break
            if wav_path is not None:
                wav_path.parent.mkdir(parents=True, exist_ok=True)
                # Avoid overwriting an earlier experiment recording by accident.
                with wav_path.open("xb") as target, wave.open(target, "wb") as recording:
                    recording.setnchannels(1)
                    recording.setsampwidth(2)
                    recording.setframerate(SAMPLE_RATE)
                    recording.writeframes(b"".join(audio_chunks))
            result.update(
                speech_tested=True,
                first_received_audio_seconds=round(first_audio, 3),
                response_seconds=round(time.monotonic() - started, 3),
                audio_seconds=round(audio_bytes / (SAMPLE_RATE * 2), 3),
                sample_rate=SAMPLE_RATE,
            )
            return result
