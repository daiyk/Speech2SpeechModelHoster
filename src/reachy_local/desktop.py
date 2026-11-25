"""Pinned desktop pipeline and passive ASGI session observation."""

from __future__ import annotations

import json
import os
import runpy
import sys
import threading
import uuid
from pathlib import Path

PINS = {
    "parakeet_tdt_model_name": (
        "mlx-community/parakeet-tdt-0.6b-v3",
        "ed2b7e8c15f9aaa0b5772e2efb986255eaef7e15",
    ),
    "model_name": ("mlx-community/Qwen3.5-4B-4bit", "0e7ffd5c629ef7719d4cbc04069232580bfa9d9c"),
    "qwen3_tts_model_name": (
        "mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-6bit",
        "1c6c0ff58c43afa8df571facde2efa077efd85e2",
    ),
}
SMART_REVISION = "f766f81d3cfdf7737ac64aad813d91bbfd56bf93"
SILERO_REVISION = "066409f3d9db45a30d21dfcbf9147826ffdd7052"
_event_lock = threading.Lock()


def emit(kind, **values):
    with _event_lock:
        print("REACHY_EVENT " + json.dumps({"kind": kind, **values}), flush=True)


def describe(raw):
    """Summarize protocol events without ever emitting encoded audio."""
    try:
        event = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(event, dict):
        return None
    kind = str(event.get("type", "unknown"))
    if kind in {"input_audio_buffer.append", "response.audio.delta", "response.output_audio.delta"}:
        return None
    text = event.get("transcript") or event.get("text")
    if not text and kind.endswith(".delta"):
        text = event.get("delta")
    if kind == "conversation.item.create":
        item = event.get("item", {})
        if not isinstance(item, dict) or not isinstance(item.get("content", []), list):
            return kind
        text = " ".join(
            str(part.get("text", "")) for part in item.get("content", []) if isinstance(part, dict)
        )
    if kind == "error":
        text = str(event.get("error", ""))
    return kind + (": " + str(text)[:4000] if text else "")


class Monitor:
    """Observe actual accepted sessions; preserve all ASGI messages unchanged."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "websocket":
            return await self.app(scope, receive, send)
        client_id = uuid.uuid4().hex[:12]
        peer = scope.get("client") or ("unknown", 0)
        accepted = False

        def observe(message, direction):
            summary = describe(message.get("text"))
            if summary:
                emit("message", id=client_id, direction=direction, text=summary)

        async def incoming():
            message = await receive()
            observe(message, "Client")
            return message

        async def outgoing(message):
            nonlocal accepted
            await send(message)
            if message["type"] == "websocket.accept":
                accepted = True
                emit("connected", id=client_id, peer=f"{peer[0]}:{peer[1]}")
            observe(message, "Server")

        try:
            await self.app(scope, incoming, outgoing)
        finally:
            if accepted:
                emit("disconnected", id=client_id)


def prepare_profile(destination):
    import yaml
    from huggingface_hub import hf_hub_download, snapshot_download

    from reachy_local.runtime import DEFAULT_PROFILE

    profile = yaml.safe_load(DEFAULT_PROFILE.read_text())
    for stage, key in (
        ("stt", "parakeet_tdt_model_name"),
        ("llm", "model_name"),
        ("tts", "qwen3_tts_model_name"),
    ):
        repo, revision = PINS[key]
        emit("status", text=f"Preparing {repo}")
        path = snapshot_download(repo, revision=revision)
        # mlx-audio infers architecture from the path basename for Parakeet.
        # Preserve the model name while keeping each alias revision-specific.
        alias = destination.parent / "models" / revision / repo.split("/")[-1]
        alias.parent.mkdir(parents=True, exist_ok=True)
        if not alias.is_symlink():
            alias.symlink_to(path, target_is_directory=True)
        elif alias.resolve() != Path(path).resolve():
            raise RuntimeError(f"Pinned model alias points to an unexpected snapshot: {alias}")
        profile["blocks"][stage]["settings"][key] = str(alias.absolute())
    smart = hf_hub_download(
        "pipecat-ai/smart-turn-v3", "smart-turn-v3.2-cpu.onnx", revision=SMART_REVISION
    )
    profile["blocks"]["vad"]["settings"] = {"smart_turn_model_path": smart}
    destination.write_text(yaml.safe_dump(profile))


def pin_silero():
    import torch

    original = torch.hub.load

    def pinned(repo, *args, **kwargs):
        if repo == "snakers4/silero-vad:master":
            repo = "snakers4/silero-vad:" + SILERO_REVISION
        return original(repo, *args, **kwargs)

    torch.hub.load = pinned


def main():
    from reachy_local.runtime import require_server, runtime_environment

    require_server()
    os.environ.update(runtime_environment("0.0.0.0" if "--lan" in sys.argv else "127.0.0.1", 8765))
    for name in ("HF_HOME", "TORCH_HOME", "NLTK_DATA"):
        Path(os.environ[name]).mkdir(parents=True, exist_ok=True)
    profile = Path("desktop-profile.yaml").resolve()
    prepare_profile(profile)
    pin_silero()
    from speech_to_speech.api.openai_realtime import server

    original = server.create_app
    server.create_app = lambda **kwargs: Monitor(original(**kwargs))
    emit("status", text="Loading models")
    sys.argv = ["speech-to-speech", "serve", "-f", str(profile)]
    runpy.run_module("speech_to_speech.cli", run_name="__main__")


if __name__ == "__main__":
    main()
