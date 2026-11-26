import json

import pytest

from speech_hoster.desktop import PINS, Monitor, describe, prepare_profile


def test_audio_payloads_are_never_logged():
    for kind in (
        "input_audio_buffer.append",
        "response.audio.delta",
        "response.output_audio.delta",
    ):
        assert describe(json.dumps({"type": kind, "delta": "secret audio"})) is None
    assert describe("not json") is None
    assert describe("[]") is None
    assert describe(
        json.dumps({"type": "response.audio_transcript.done", "transcript": "Hello"})
    ).endswith("Hello")


@pytest.mark.asyncio
async def test_monitor_preserves_frames_and_removes_disconnected_client(monkeypatch):
    events, sent = [], []
    monkeypatch.setattr("speech_hoster.desktop.emit", lambda kind, **kw: events.append((kind, kw)))
    incoming = {"type": "websocket.receive", "text": '{"type":"response.create"}'}

    async def receive():
        return incoming

    async def send(message):
        sent.append(message)

    async def app(scope, receive, send):
        await send({"type": "websocket.accept"})
        assert await receive() is incoming
        await send(
            {"type": "websocket.send", "text": '{"type":"response.audio.delta","delta":"abc"}'}
        )
        raise RuntimeError("connection lost")

    with pytest.raises(RuntimeError):
        await Monitor(app)({"type": "websocket", "client": ("127.0.0.1", 123)}, receive, send)
    assert [event[0] for event in events] == ["connected", "message", "disconnected"]
    assert len(sent) == 2
    assert events[0][1]["id"] == events[-1][1]["id"]


@pytest.mark.asyncio
async def test_rejected_connection_is_not_counted(monkeypatch):
    events = []
    monkeypatch.setattr("speech_hoster.desktop.emit", lambda *a, **kw: events.append(a))

    async def app(scope, receive, send):
        await send({"type": "websocket.close", "code": 1008})

    async def send(message):
        pass

    await Monitor(app)({"type": "websocket"}, None, send)
    assert events == []


def test_profile_downloads_exact_revisions_and_uses_local_paths(monkeypatch, tmp_path):
    import yaml

    calls = []

    def snapshot(repo, revision):
        calls.append((repo, revision))
        return str(tmp_path / revision)

    monkeypatch.setattr("huggingface_hub.snapshot_download", snapshot)
    monkeypatch.setattr("huggingface_hub.hf_hub_download", lambda *a, **kw: "/pinned/smart.onnx")
    profile = tmp_path / "profile.yaml"
    prepare_profile(profile)
    assert calls == list(PINS.values())
    data = yaml.safe_load(profile.read_text())
    assert data["blocks"]["llm"]["settings"]["model_name"].startswith(str(tmp_path))
    assert data["blocks"]["vad"]["settings"]["smart_turn_model_path"] == "/pinned/smart.onnx"
    from speech_to_speech.config import load_config, resolve_config

    resolve_config(
        load_config(profile),
        environ={"SPEECH_HOSTER_HOST": "127.0.0.1", "SPEECH_HOSTER_PORT": "8765"},
    )
