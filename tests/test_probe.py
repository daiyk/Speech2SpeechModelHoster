"""Protocol tests against a loopback WebSocket peer; no models are loaded."""

from __future__ import annotations

import asyncio
import base64
import json
import math
import struct
import wave
from contextlib import asynccontextmanager

import pytest
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

from reachy_local.probe import ProbeError, probe, validate_url


def session_audio(rate=None):
    return {
        "input": {"format": {"type": "audio/pcm", "rate": rate}},
        "output": {"format": {"type": "audio/pcm", "rate": rate}},
    }


@asynccontextmanager
async def endpoint(handler):
    async with serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        yield f"ws://127.0.0.1:{port}/v1/realtime"


async def configure(ws, received, *, audio=None):
    await ws.send(json.dumps({"type": "session.created", "session": {"id": "test"}}))
    received.append(json.loads(await ws.recv()))
    await ws.send(
        json.dumps(
            {
                "type": "session.updated",
                "session": {"audio": session_audio() if audio is None else audio},
            }
        )
    )


@pytest.mark.parametrize("rate", [None, 16000])
async def test_handshake_uses_reachy_native_audio_and_server_vad(rate):
    received = []

    async def handler(ws):
        await configure(ws, received, audio=session_audio(rate))
        await ws.wait_closed()

    async with endpoint(handler) as url:
        result = await probe(url, timeout=2)

    assert result == {"session_configured": True, "speech_tested": False}
    request = received[0]
    assert request["type"] == "session.update"
    session = request["session"]
    assert session["type"] == "realtime"
    assert session["audio"]["input"] == {
        "format": {"type": "audio/pcm", "rate": None},
        "transcription": {"model": "gpt-4o-transcribe", "language": "auto"},
        "turn_detection": {"type": "server_vad", "interrupt_response": True},
    }
    assert session["audio"]["output"] == {
        "format": {"type": "audio/pcm", "rate": None},
        "voice": "Aiden",
    }
    assert session["tools"] == []


@pytest.mark.parametrize("direction", ["input", "output"])
@pytest.mark.parametrize(
    "bad_format", [{}, {"type": "audio/pcm"}, {"type": "audio/pcm", "rate": 24000}]
)
async def test_rejects_audio_that_reachy_would_play_at_the_wrong_rate(direction, bad_format):
    audio = session_audio()
    audio[direction]["format"] = bad_format

    async def handler(ws):
        await configure(ws, [], audio=audio)
        await ws.wait_closed()

    async with endpoint(handler) as url:
        with pytest.raises(ProbeError, match="16 kHz PCM"):
            await probe(url, timeout=2)


async def speech_peer(ws, received, events):
    await configure(ws, received)
    received.append(json.loads(await ws.recv()))
    received.append(json.loads(await ws.recv()))
    for event in events:
        await ws.send(json.dumps(event))
    await ws.wait_closed()


async def test_text_triggered_speech_writes_exact_pcm16_wav(tmp_path):
    received = []
    pcm = struct.pack("<hhhh", 0, 32767, -32768, 100)
    events = [
        {"type": "response.created", "response": {"id": "r1"}},
        {"type": "response.output_audio.delta", "delta": base64.b64encode(pcm[:4]).decode()},
        {"type": "response.output_audio.delta", "delta": base64.b64encode(pcm[4:]).decode()},
        {"type": "response.output_audio.done"},
        {"type": "response.done", "response": {"status": "completed"}},
    ]

    async def handler(ws):
        await speech_peer(ws, received, events)

    target = tmp_path / "recordings" / "reply.wav"
    async with endpoint(handler) as url:
        result = await probe(url, speak="Say hello.", wav_path=target, timeout=2)

    assert received[1] == {
        "type": "conversation.item.create",
        "item": {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": "Say hello."}],
        },
    }
    assert received[2] == {"type": "response.create"}
    assert result["speech_tested"] is True
    assert result["sample_rate"] == 16000
    assert result["first_received_audio_seconds"] >= 0
    with wave.open(str(target), "rb") as recording:
        assert (recording.getnchannels(), recording.getsampwidth(), recording.getframerate()) == (
            1,
            2,
            16000,
        )
        assert recording.readframes(4) == pcm


async def test_existing_recording_is_preserved(tmp_path):
    target = tmp_path / "existing.wav"
    target.write_bytes(b"keep this recording")
    events = [
        {"type": "response.output_audio.delta", "delta": "AAAAAA=="},
        {"type": "response.done", "response": {"status": "completed"}},
    ]

    async def handler(ws):
        await speech_peer(ws, [], events)

    async with endpoint(handler) as url:
        with pytest.raises(FileExistsError):
            await probe(url, speak="Hello", wav_path=target, timeout=2)
    assert target.read_bytes() == b"keep this recording"


@pytest.mark.parametrize(
    "events, message",
    [
        ([{"type": "response.done", "response": {"status": "failed"}}], "successfully"),
        ([{"type": "response.done", "response": {"status": "completed"}}], "without GA"),
        (
            [
                {"type": "response.audio.delta", "delta": "AAAAAA=="},
                {"type": "response.done", "response": {"status": "completed"}},
            ],
            "without GA",
        ),
        ([{"type": "response.output_audio.delta", "delta": "AA=="}], "PCM16"),
        ([{"type": "response.output_audio.delta", "delta": ""}], "PCM16"),
    ],
)
async def test_failed_or_incompatible_speech_is_not_reported_as_success(events, message):
    async def handler(ws):
        await speech_peer(ws, [], events)

    async with endpoint(handler) as url:
        with pytest.raises(ProbeError, match=message):
            await probe(url, speak="Hello", timeout=2)


async def test_endpoint_error_is_surfaced_without_echoing_remote_message():
    async def handler(ws):
        await ws.send(
            json.dumps(
                {
                    "type": "error",
                    "error": {"code": "server_busy", "message": "private details"},
                }
            )
        )
        await ws.wait_closed()

    async with endpoint(handler) as url:
        with pytest.raises(ProbeError, match="server_busy") as exc:
            await probe(url, timeout=2)
    assert "private details" not in str(exc.value)


@pytest.mark.parametrize("raw", ["[]", '{"type":', '{"type":"error","error":null}'])
async def test_malformed_events_fail_closed(raw):
    async def handler(ws):
        await ws.send(raw)
        await ws.wait_closed()

    async with endpoint(handler) as url:
        with pytest.raises((ProbeError, ValueError, AttributeError)):
            await probe(url, timeout=2)


async def test_unrelated_event_stream_cannot_extend_total_deadline():
    async def handler(ws):
        try:
            while True:
                await ws.send('{"type":"irrelevant"}')
                await asyncio.sleep(0.005)
        except ConnectionClosed:
            pass

    async with endpoint(handler) as url:
        with pytest.raises(TimeoutError):
            await probe(url, timeout=0.1)


@pytest.mark.parametrize(
    "url",
    [
        "https://localhost:8765/v1/realtime",
        "ws:///v1/realtime",
        "ws://localhost/v1",
        "ws://user:secret@localhost/v1/realtime",
        "ws://localhost/v1/realtime#fragment",
        "ws://localhost:99999/v1/realtime",
        "ws://localhost:notaport/v1/realtime",
    ],
)
def test_invalid_urls_rejected(url):
    with pytest.raises(ValueError):
        validate_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "ws://127.0.0.1:8765/v1/realtime",
        "wss://example.com/v1/realtime",
        "ws://[::1]:8765/v1/realtime",
    ],
)
def test_valid_urls(url):
    assert validate_url(url) == url


@pytest.mark.parametrize("timeout", [0, -1, math.nan, math.inf])
async def test_timeout_must_be_finite_and_positive(timeout):
    with pytest.raises(ValueError, match="[Tt]imeout"):
        await probe(timeout=timeout)


async def test_invalid_speech_options_are_rejected_before_connection(tmp_path):
    with pytest.raises(ValueError, match="empty"):
        await probe(speak="   ")
    with pytest.raises(ValueError, match="requires"):
        await probe(wav_path=tmp_path / "out.wav")
