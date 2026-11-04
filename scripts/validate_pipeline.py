"""Optional synthetic audio and tool smoke test against a running local server."""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import math
import sys
import tempfile
import time
import wave
from pathlib import Path
from urllib.parse import urlsplit

from openai import AsyncOpenAI

from reachy_local.probe import DEFAULT_URL, probe, reachy_session, validate_url


class EndpointError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(f"Endpoint error: {code}")


async def receive(conn):
    event = await conn.recv()  # A closed connection raises instead of ending a loop silently.
    if event.type == "error":
        raise EndpointError(event.error.code or event.error.type or "unknown")
    return event


async def wait_event(conn, kind: str):
    while True:
        event = await receive(conn)
        if event.type == kind:
            return event


async def finish_response(conn, *, require_transcript=False, require_tool=False):
    transcript_chars, audio_bytes, call = 0, 0, None
    while True:
        event = await receive(conn)
        if event.type == "conversation.item.input_audio_transcription.completed":
            transcript_chars = len(event.transcript.strip())
        elif event.type == "response.output_audio.delta":
            chunk = base64.b64decode(event.delta, validate=True)
            if not chunk or len(chunk) % 2:
                raise RuntimeError("Invalid PCM16 response audio")
            audio_bytes += len(chunk)
        elif event.type == "response.function_call_arguments.done":
            if not require_tool or call is not None or event.name != "get_test_value":
                raise RuntimeError("Unexpected or duplicate tool call")
            if json.loads(event.arguments) != {} or not event.call_id:
                raise RuntimeError("Invalid test tool arguments or call ID")
            call = event
        elif event.type == "response.done":
            if event.response.status != "completed":
                raise RuntimeError("Response did not complete successfully")
            if require_transcript and not transcript_chars:
                raise RuntimeError("No speech recognition transcript received")
            if require_tool and call is None:
                raise RuntimeError("No test tool call received")
            if not require_tool and not audio_bytes:
                raise RuntimeError("No response audio received")
            return transcript_chars, audio_bytes, call


async def exercise(conn, audio: bytes) -> dict:
    await conn.session.update(session=reachy_session())
    await wait_event(conn, "session.updated")
    # Append two seconds of silence to let server VAD end the synthetic utterance.
    audio += bytes(16000 * 2 * 2)
    for offset in range(0, len(audio), 1024):
        await conn.input_audio_buffer.append(
            audio=base64.b64encode(audio[offset : offset + 1024]).decode()
        )
        await asyncio.sleep(0.032)
    chars, audio_bytes, _ = await finish_response(conn, require_transcript=True)
    result = {"audio_roundtrip": {"transcript_chars": chars, "response_audio_bytes": audio_bytes}}
    config = reachy_session()
    config["instructions"] = (
        "Call get_test_value exactly once when asked for the test value. "
        "After receiving its result, say the returned value in one short sentence."
    )
    config["tools"] = [
        {
            "type": "function",
            "name": "get_test_value",
            "description": "Get the test value from the local client.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        }
    ]
    await conn.session.update(session=config)
    await wait_event(conn, "session.updated")
    await conn.conversation.item.create(
        item={
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": "Get the test value using get_test_value."}],
        }
    )
    await conn.response.create()
    _, _, call = await finish_response(conn, require_tool=True)
    # This mock tool returns a constant; it performs no robot action.
    await conn.conversation.item.create(
        item={
            "type": "function_call_output",
            "call_id": call.call_id,
            "output": json.dumps({"value": 42}),
        }
    )
    await conn.response.create()
    _, audio_bytes, _ = await finish_response(conn)
    result["tool_roundtrip"] = {"name": call.name, "response_audio_bytes": audio_bytes}
    return result


async def validate(url: str, timeout: float) -> dict:
    validate_url(url)
    parts = urlsplit(url)
    ws_base = parts._replace(path="/v1").geturl()
    http_base = parts._replace(scheme="https" if parts.scheme == "wss" else "http", path="/v1")
    async with asyncio.timeout(timeout):
        with tempfile.TemporaryDirectory(prefix="reachy-pipeline-check-") as directory:
            source = Path(directory) / "source.wav"
            generated = await probe(
                url,
                speak="Say exactly: Hello Reachy, please tell me a short fun fact.",
                wav_path=source,
                timeout=timeout,
            )
            with wave.open(str(source), "rb") as recording:
                shape = (
                    recording.getnchannels(),
                    recording.getsampwidth(),
                    recording.getframerate(),
                )
                if shape != (1, 2, 16000):
                    raise RuntimeError("Expected mono 16 kHz PCM16 source WAV")
                audio = recording.readframes(recording.getnframes())
            async with AsyncOpenAI(
                api_key="DUMMY",
                base_url=http_base.geturl(),
                websocket_base_url=ws_base,
                max_retries=0,
            ) as client:
                drain_deadline = time.monotonic() + 10
                while True:
                    async with client.realtime.connect() as conn:
                        try:
                            remaining = max(0.01, drain_deadline - time.monotonic())
                            async with asyncio.timeout(remaining):
                                await wait_event(conn, "session.created")
                        except EndpointError as exc:
                            can_retry = time.monotonic() < drain_deadline
                            if exc.code != "session_limit_reached" or not can_retry:
                                raise
                        else:
                            return {"source_generation": generated, **await exercise(conn, audio)}
                    await asyncio.sleep(0.25)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--timeout", type=float, default=180, help="Total deadline in seconds")
    args = parser.parse_args()
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("--timeout must be finite and positive")
    try:
        report = asyncio.run(validate(args.url, args.timeout))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"Pipeline check failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
