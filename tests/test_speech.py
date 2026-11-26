import io
import wave
from threading import Event
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi.testclient import TestClient

from speech_hoster.desktop import Monitor
from speech_hoster.server import Qwen3TTSHandler, create_app


@pytest.fixture
def speech(tmp_path):
    # Exercise the pinned handler's real audio conversion with only inference replaced.
    calls = []

    def generate(**kwargs):
        calls.append(kwargs)
        yield SimpleNamespace(audio=np.full(512, 0.25, dtype=np.float32), sample_rate=16000)

    handler = Qwen3TTSHandler.__new__(Qwen3TTSHandler)
    handler.backend = "mlx"
    handler.model = SimpleNamespace(
        config=SimpleNamespace(tts_model_type="custom_voice"),
        get_supported_speakers=lambda: ["Aiden", "Vivian"],
        generate_custom_voice=generate,
    )
    handler.language = "auto"
    handler.speaker = "Aiden"
    handler.instruct = None
    handler.gen_kwargs = {}
    handler.blocksize = 512
    handler.streaming_chunk_size = 4
    handler.cancel_scope = object()  # A direct request must never consult the Realtime session.
    app = create_app(
        pool=[SimpleNamespace(handlers=[handler])],
        stop_event=Event(),
        monitor=Monitor,
        voice_directory=tmp_path,
    )
    return TestClient(app), handler, calls


def test_direct_speech_uses_exact_text_and_isolates_session_voice(speech):
    client, handler, calls = speech
    handler.speaker = "Vivian"  # A connected Realtime client has changed its voice.
    text = "  Is it 3:30? Say exactly that.  "
    for extra, expected in [({}, "Aiden"), ({"voice": "vIvIaN"}, "Vivian"), ({}, "Aiden")]:
        response = client.post("/v1/audio/speech", json={"input": text, **extra})
        assert response.status_code == 200
        assert response.headers["content-type"] == "audio/wav"
        with wave.open(io.BytesIO(response.content)) as wav:
            assert (wav.getnchannels(), wav.getframerate(), wav.getsampwidth()) == (1, 16000, 2)
            assert wav.readframes(512) == np.full(512, 8192, dtype="<i2").tobytes()
        assert calls[-1]["text"] == text
        assert calls[-1]["speaker"] == expected
        assert handler.speaker == "Vivian"
    assert len(calls) == 3


@pytest.mark.parametrize("stream", [False, True])
def test_unmodified_upstream_tts_payload_returns_24khz_pcm(speech, monkeypatch, stream):
    from queue import Queue

    from speech_to_speech.TTS.openai_compatible_handler import OpenAICompatibleTTSHandler

    client, _, calls = speech
    monkeypatch.setattr(OpenAICompatibleTTSHandler, "warmup", lambda self: None)
    upstream = OpenAICompatibleTTSHandler(
        Event(), Queue(), Queue(), setup_kwargs={"should_listen": Event(), "stream": stream}
    )
    request = upstream._request_payload(text="Checking native audio.", voice=upstream.voice)
    response = client.post("/v1/audio/speech", json=request)
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/pcm"
    # The fake source is 512 samples at 16 kHz. The wire is 24 kHz signed PCM16.
    pcm = np.frombuffer(response.content, dtype="<i2")
    assert len(pcm) == 768 and np.mean(pcm) == pytest.approx(8192, rel=0.001)
    assert calls[-1]["speaker"] == "Aiden"


def test_upstream_style_language_and_voice_options(speech):
    client, handler, calls = speech
    request = {
        "model": "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
        "input": "Bonjour.",
        "voice": {"id": "vivian"},
        "response_format": "wav",
        "instructions": "Speak softly.",
        "language": "fr",
        "task_type": "CustomVoice",
    }
    response = client.post("/v1/audio/speech", json=request)
    assert response.status_code == 200
    assert calls[-1]["language"] == "french" and calls[-1]["instruct"] == "Speak softly."
    assert handler.instruct is None and handler.speaker == "Aiden"


def test_unknown_upstream_preset_preserves_session_voice(speech):
    _, handler, _ = speech
    handler.speaker = "Vivian"
    handler.ref_audio = "existing-reference.wav"
    config = SimpleNamespace(
        session=SimpleNamespace(audio=SimpleNamespace(output=SimpleNamespace(voice="unknown")))
    )
    handler._apply_session_voice_override("custom_voice", config)
    assert handler.speaker == "Vivian" and handler.ref_audio == "existing-reference.wav"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"input": " \n"},
        {"input": "x" * 501},
        {"input": "Hi", "voice": "unknown"},
        {"input": "Hi", "response_format": "mp3"},
        {"input": "Hi", "model": "other"},
    ],
)
def test_invalid_requests_do_not_run_inference(speech, payload):
    client, _, calls = speech
    assert client.post("/v1/audio/speech", json=payload).status_code == 422
    assert not calls


def test_direct_speech_model_failures_return_http_errors(speech):
    client, handler, _ = speech
    handler.model.generate_custom_voice = lambda **kwargs: []
    assert client.post("/v1/audio/speech", json={"input": "Hi"}).status_code == 500

    def busy(**kwargs):
        raise TimeoutError()

    handler.model.generate_custom_voice = busy
    assert client.post("/v1/audio/speech", json={"input": "Hi"}).status_code == 503


def test_other_profiles_keep_realtime_route():
    app = create_app(pool=[SimpleNamespace(handlers=[])], stop_event=Event())
    assert "/v1/realtime" in {route.path for route in app.routes}
    assert TestClient(app).post("/v1/audio/speech", json={"input": "Hi"}).status_code == 501


def test_voice_portability_selection_and_session_isolation(tmp_path, monkeypatch):
    import base64
    from concurrent.futures import ThreadPoolExecutor

    from speech_hoster.voice_engine import VoiceEngine
    from speech_hoster.voices import PREVIEW_TEXT, wav_bytes

    calls = []
    samples = np.full(12000, 0.2, dtype=np.float32)
    source = wav_bytes(samples, 24000)

    def design(self, handler, prompt, text):
        calls.append(("design", prompt, text))
        return source

    def clone(self, handler, reference, text, language=None):
        calls.append((reference.audio, reference.transcript, text, language, handler.cancel_scope))
        yield b"\x01\x00" * 512

    monkeypatch.setattr(VoiceEngine, "design", design)
    monkeypatch.setattr(VoiceEngine, "clone", clone)

    def server(folder):
        handler = Qwen3TTSHandler.__new__(Qwen3TTSHandler)
        handler.backend = "mlx"
        handler.speaker = "Aiden"
        handler.cancel_scope = object()
        handler.model = SimpleNamespace(
            config=SimpleNamespace(tts_model_type="custom_voice"),
            get_supported_speakers=lambda: ["aiden", "vivian"],
        )
        app = create_app(
            pool=[SimpleNamespace(handlers=[handler])], stop_event=Event(), voice_directory=folder
        )
        return TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 5000)), handler

    def voice_config(value):
        return SimpleNamespace(audio=SimpleNamespace(output=SimpleNamespace(voice=value)))

    first, _ = server(tmp_path / "first")
    catalog = first.get("/v1/audio/voices").json()
    assert catalog["default_voice"] in {v["id"] for v in catalog["voices"]}
    assert catalog["types"] == ["preset", "cloned", "designed"]
    request = {"prompt": "A gentle alto"}
    sample = first.post("/local/voices/design", json=request)
    assert sample.content == source and calls == [("design", request["prompt"], PREVIEW_TEXT)]
    reference = {"audio": base64.b64encode(source).decode(), "transcript": PREVIEW_TEXT}
    preview = first.post("/local/voices/preview", json=reference)
    assert preview.headers["content-type"] == "audio/wav"
    assert calls[-1] == (reference["audio"], PREVIEW_TEXT, PREVIEW_TEXT, None, None)
    packs = []
    for kind in ["cloned", "designed"]:
        body = {**reference, "name": "The reader", "type": kind}
        if kind == "designed":
            body.update(request)
        saved = first.post("/local/voices", json=body).json()
        retry = first.post("/local/voices", json={**body, "id": saved["id"]})
        assert retry.json() == saved
        pack = first.get(f"/local/voices/{saved['id']}/export").json()
        assert pack["audio"] == reference["audio"] and pack["name"] == body["name"]
        assert pack["type"] == kind and pack["transcript"] == PREVIEW_TEXT
        packs.append(pack)

    other_dir = tmp_path / "second"
    second, _ = server(other_dir)
    with ThreadPoolExecutor(4) as executor:
        codes = list(
            executor.map(
                lambda item: second.post("/local/voices/import", json=item).status_code, packs * 2
            )
        )
    assert codes == [200] * 4
    assert (
        second.post("/local/voices/import", json={**packs[0], "name": "Other"}).status_code == 409
    )
    one, two = (p["id"] for p in packs)
    assert second.put("/local/voices/default", json={"voice": one}).status_code == 200
    restarted, handler = server(other_dir)
    catalog = restarted.get("/v1/audio/voices").json()
    assert {v["id"] for v in catalog["voices"]} == {"aiden", "vivian", one, two}
    assert catalog["default_voice"] == one
    assert restarted.get(f"/local/voices/{one}/export").json() == packs[0]
    session = SimpleNamespace(session=voice_config(one))
    for response, expected in [(voice_config(SimpleNamespace(id=two)), two), (None, one)]:
        handler._apply_session_voice_override("custom_voice", session, response)
        assert handler.speaker == expected
        assert list(handler._process_custom_voice("Bonjour", "french"))
        assert calls[-1][-2:] == ("french", handler.cancel_scope)
    for body in [{"input": "Hi"}, {"input": "Hi", "voice": two}]:
        assert restarted.post("/v1/audio/speech", json=body).status_code == 200
        assert calls[-1][-3:] == ("Hi", None, None)
        assert handler.speaker == one
    assert (
        restarted.post("/local/voices/import", json={**packs[0], "version": 2}).status_code == 422
    )
    assert (
        restarted.post("/local/voices/import", json={**packs[0], "audio": "!"}).status_code == 422
    )
    remote = TestClient(restarted.app, base_url="http://192.0.2.1", client=("192.0.2.2", 5100))
    assert remote.get("/v1/audio/voices").status_code == 200
    assert remote.get(f"/local/voices/{one}/export").status_code == 403
