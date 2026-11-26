"""Extend the pinned Realtime server with direct access to its loaded voice model."""

from __future__ import annotations

import asyncio
import io
import sys
import wave
from concurrent.futures import ThreadPoolExecutor
from copy import copy
from functools import partial
from pathlib import Path
from typing import Literal

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from speech_to_speech.api.openai_realtime import websocket_router
from speech_to_speech.STT.parakeet_tdt_handler import ParakeetTDTSTTHandler
from speech_to_speech.TTS.qwen3_tts_handler import PIPELINE_SR, Qwen3TTSHandler
from speech_to_speech.utils.mlx_lock import MLXLockContext

from speech_hoster.voice_engine import VoiceEngine
from speech_hoster.voices import (
    PREVIEW_TEXT,
    EncodedAudio,
    InvalidRecording,
    NewVoice,
    Reference,
    Transcript,
    VoiceConflict,
    VoiceInput,
    VoiceLibrary,
    VoicePackage,
    decode_audio,
)


class VoiceReference(BaseModel):
    id: str


class SpeechRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input: str = Field(min_length=1, max_length=500, pattern=r"\S")
    model: Literal[
        "qwen3-tts",
        "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
        "mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-6bit",
    ] = "qwen3-tts"
    voice: str | VoiceReference | None = None
    response_format: Literal["wav", "pcm"] = "wav"
    stream_format: Literal["audio"] = "audio"
    stream: bool = False
    language: str | None = None
    instructions: str | None = None
    task_type: Literal["CustomVoice", "Base"] | None = None
    speed: float = Field(default=1.0, ge=0.25, le=4.0)

    @model_validator(mode="after")
    def validate_stream(self):
        if self.stream and (self.response_format != "pcm" or self.speed != 1):
            raise ValueError("Streaming requires raw PCM and speed 1.")
        return self


class WavResponse(Response):
    media_type = "audio/wav"


class DesignRequest(VoiceInput):
    prompt: Transcript
    text: str = Field(default=PREVIEW_TEXT, min_length=1, max_length=200, pattern=r"\S")


class PreviewRequest(Reference):
    text: str = Field(default=PREVIEW_TEXT, min_length=1, max_length=500, pattern=r"\S")


class TranscribeRequest(VoiceInput):
    audio: EncodedAudio


class DefaultRequest(VoiceInput):
    voice: str


def render_wav(chunks):
    audio = io.BytesIO()
    with wave.open(audio, "wb") as wav:
        wav.setparams((1, 2, PIPELINE_SR, 0, "NONE", "not compressed"))
        for chunk in chunks:
            wav.writeframesraw(chunk)
        if wav.getnframes() == 0:
            raise HTTPException(500, "Speech model produced no audio.")
    return WavResponse(audio.getvalue())


def raw_pcm(handler, generated, label):
    """Keep the native 24 kHz Qwen output for the upstream HTTP TTS adapter."""
    from math import gcd

    from scipy.signal import resample_poly

    for item in generated:
        audio, rate = handler._prepare_audio_chunk(item)
        if audio is None or not audio.size:
            continue
        if rate != 24000:
            divisor = gcd(rate, 24000)
            audio = resample_poly(audio, 24000 // divisor, rate // divisor)
        yield handler._to_int16(audio).astype("<i2", copy=False).tobytes()


async def stream_audio(chunks):
    # MLX acquires a thread-owned lock for the lifetime of its generator.
    # Starlette's default synchronous iterator may change threads between chunks.
    worker = ThreadPoolExecutor(max_workers=1)
    loop = asyncio.get_running_loop()
    try:
        while (chunk := await loop.run_in_executor(worker, next, chunks, None)) is not None:
            yield chunk
    finally:
        worker.submit(chunks.close)
        worker.shutdown(wait=False)


def change_speed(chunks, speed):
    from librosa.effects import time_stretch

    data = b"".join(chunks)
    if data:
        samples = np.frombuffer(data, dtype="<i2").astype(np.float32)
        result = time_stretch(samples, rate=speed)
        yield np.rint(result).clip(-32768, 32767).astype("<i2").tobytes()


def local_management(request: Request):
    if (
        request.client is None
        or request.client.host not in {"127.0.0.1", "::1"}
        or request.url.hostname not in {"localhost", "127.0.0.1", "::1"}
    ):
        raise HTTPException(403, "Manage voice recordings on the host Mac.")


class VoiceOutput:
    def __init__(self, handler, library, engine):
        self.handler = handler
        self.library = library
        self.engine = engine
        self.presets = {v.casefold(): v for v in handler._supported_speakers() or []}
        fallback = handler._resolve_speaker()
        self.fallback = self.presets.get(str(fallback).casefold(), fallback)

    def resolve(self, voice_id):
        if not isinstance(voice_id, str):
            return None
        preset = self.presets.get(voice_id.casefold())
        if preset:
            return preset
        if voice_id.startswith("voice_"):
            return self.library.get(voice_id)
        return None

    def default_id(self):
        return self.library.default(self.fallback)

    def stream(self, handler, choice, text, language=None):
        if isinstance(choice, VoicePackage):
            yield from self.engine.clone(handler, choice, text, language)
        else:
            synthesis = copy(handler)
            synthesis.speaker = choice
            yield from Qwen3TTSHandler._process_custom_voice(synthesis, text, language)

    def connect_realtime(self, stage):
        # The upstream process owns cancellation, language detection and sentence
        # coalescing. Only replace its two preset-selection/synthesis hooks.
        upstream_select = stage._apply_session_voice_override

        def select(model_type, runtime_config=None, response=None):
            voice = None
            for config in (response, runtime_config.session if runtime_config else None):
                audio = getattr(config, "audio", None)
                voice = getattr(getattr(audio, "output", None), "voice", None)
                if voice:
                    break
            # Preserve upstream preset validation, including leaving the current
            # speaker/reference alone when a client requests an unknown preset.
            if isinstance(voice, str) and not voice.startswith("voice_"):
                upstream_select(model_type, runtime_config, response)
                return
            selected = getattr(voice, "id", voice) or self.default_id()
            stage.speaker = selected
            if voice or selected != self.fallback:
                stage.ref_audio = None
                stage._clear_cached_voice_reference()

        def speak(text, language=None):
            choice = self.resolve(stage.speaker)
            if choice is None:
                # Some existing clients request a hosted-only preset, e.g. alloy.
                choice = self.resolve(self.default_id()) or self.fallback
            yield from self.stream(stage, choice, text, language)

        stage._apply_session_voice_override = select
        stage._process_custom_voice = speak


def create_app(*, pool, monitor=None, voice_directory=None, voice_engine=None, **kwargs):
    app = websocket_router.create_app(pool=pool, **kwargs)
    if monitor is not None:
        app.add_middleware(monitor)

    stages = [
        stage
        for unit in pool
        for stage in unit.handlers
        if isinstance(stage, Qwen3TTSHandler) and stage._model_type() == "custom_voice"
    ]
    output = None
    if stages:
        output = VoiceOutput(
            stages[0], VoiceLibrary(voice_directory), voice_engine or VoiceEngine()
        )
        for stage in stages:
            output.connect_realtime(stage)

    def voices():
        if output is None:
            raise HTTPException(501, "Voice selection requires a Qwen3-TTS CustomVoice profile.")
        return output

    recognizer = next(
        (
            stage
            for stage in pool[0].handlers
            if isinstance(stage, ParakeetTDTSTTHandler) and stage.backend == "mlx"
        ),
        None,
    )

    @app.get("/v1/audio/voices")
    def catalog():
        if output is None:
            return {"types": [], "voices": [], "default_voice": None, "can_transcribe": False}
        presets = [{"id": v, "name": v, "type": "preset"} for v in output.presets.values()]
        return {
            "types": ["preset", "cloned", "designed"],
            "voices": presets + output.library.list(),
            "default_voice": output.default_id(),
            "can_transcribe": recognizer is not None,
        }

    @app.post("/v1/audio/speech", response_class=WavResponse)
    def synthesize(request: SpeechRequest):
        service = voices()
        voice = request.voice.id if isinstance(request.voice, VoiceReference) else request.voice
        choice = service.resolve(voice if voice is not None else service.default_id())
        if choice is None:
            raise HTTPException(422, "Unknown voice. Choose an ID from GET /v1/audio/voices.")
        synthesis = copy(service.handler)
        synthesis.cancel_scope = None
        kind = "Base" if isinstance(choice, VoicePackage) else "CustomVoice"
        if request.task_type and request.task_type != kind:
            raise HTTPException(422, f"This voice uses the {kind} task.")
        if request.instructions is not None:
            if isinstance(choice, VoicePackage):
                raise HTTPException(422, "Saved voices take their style from the reference audio.")
            synthesis.instruct = request.instructions
        if request.response_format == "pcm":
            synthesis._stream = partial(raw_pcm, synthesis)
        language = synthesis._normalize_language(request.language) if request.language else None
        chunks = service.stream(synthesis, choice, request.input, language)
        if request.stream:
            return StreamingResponse(stream_audio(chunks), media_type="audio/pcm")
        if request.speed != 1:
            chunks = change_speed(chunks, request.speed)
        if request.response_format == "wav":
            return render_wav(chunks)
        pcm = b"".join(chunks)
        if not pcm:
            raise HTTPException(500, "Speech model produced no audio.")
        return Response(pcm, media_type="audio/pcm")

    manage = APIRouter(prefix="/local/voices", dependencies=[Depends(local_management)])

    @manage.post("/transcribe")
    def transcribe(request: TranscribeRequest):
        if recognizer is None:
            raise HTTPException(501, "Enter the transcript for this recording.")
        samples = decode_audio(request.audio, PIPELINE_SR)
        with MLXLockContext(handler_name="Voice transcription", timeout=10) as acquired:
            if not acquired:
                raise TimeoutError
            return {"transcript": recognizer._process_mlx(samples)}

    @manage.post("/design", response_class=WavResponse)
    def design(request: DesignRequest):
        service = voices()
        return WavResponse(service.engine.design(service.handler, request.prompt, request.text))

    @manage.post("/preview", response_class=WavResponse)
    def preview(request: PreviewRequest):
        service = voices()
        synthesis = copy(service.handler)
        synthesis.cancel_scope = None
        return render_wav(service.engine.clone(synthesis, request, request.text))

    @manage.post("")
    def save(request: NewVoice):
        return voices().library.save(request).summary()

    @manage.post("/import")
    def import_voice(package: VoicePackage):
        decode_audio(package.audio)
        return voices().library.store(package).summary()

    @manage.get("/{voice_id}/export")
    def export_voice(voice_id: str):
        entry = voices().library.get(voice_id)
        if entry is None:
            raise HTTPException(404, "Saved voice not found.")
        return entry

    @manage.put("/default")
    def set_default(request: DefaultRequest):
        service = voices()
        choice = service.resolve(request.voice)
        if choice is None:
            raise HTTPException(422, "Unknown voice.")
        voice_id = choice.id if isinstance(choice, VoicePackage) else choice
        service.library.set_default(voice_id)
        return {"default_voice": voice_id}

    @app.exception_handler(VoiceConflict)
    async def conflict(_, error):
        return JSONResponse({"detail": str(error)}, status_code=409)

    @app.exception_handler(InvalidRecording)
    async def invalid_audio(_, error):
        return JSONResponse({"detail": str(error)}, status_code=422)

    @app.exception_handler(TimeoutError)
    async def model_busy(_, error):
        return JSONResponse({"detail": "Speech model is busy. Retry shortly."}, status_code=503)

    if stages:
        app.include_router(manage)
    return app


def serve_profile(profile: Path, monitor=None) -> None:
    from speech_to_speech.api.openai_realtime import server
    from speech_to_speech.cli import main

    server.create_app = partial(create_app, monitor=monitor)
    sys.argv = ["speech-to-speech", "serve", "-f", str(profile)]
    main()


if __name__ == "__main__":
    serve_profile(Path(sys.argv[1]))
