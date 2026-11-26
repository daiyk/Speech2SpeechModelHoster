"""Use the pinned MLX voice models with the conversation pipeline's shared GPU lock."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
from speech_to_speech.utils.mlx_lock import MLXLockContext

from speech_hoster.voices import (
    BASE_MODEL,
    BASE_REVISION,
    DESIGN_MODEL,
    DESIGN_REVISION,
    REFERENCE_RATE,
    decode_audio,
    wav_bytes,
)


@lru_cache(maxsize=2)
def model_path(repo, revision):
    from huggingface_hub import snapshot_download

    # An immutable cached revision also works without a network connection.
    try:
        return Path(snapshot_download(repo, revision=revision, local_files_only=True))
    except FileNotFoundError:
        return Path(snapshot_download(repo, revision=revision))


class VoiceEngine:
    def __init__(self):
        self.loaded_path = None
        self.model = None

    def _load_locked(self, path):
        from mlx_audio.tts.utils import load_model

        if self.loaded_path != path:
            # Keep only one additional TTS model alongside the conversation pipeline.
            self.model = None
            self.loaded_path = None
            self.model = load_model(path)
            self.loaded_path = path
        return self.model

    def design(self, handler, prompt, text):
        path = model_path(DESIGN_MODEL, DESIGN_REVISION)
        with MLXLockContext(handler_name="Voice design", timeout=10) as acquired:
            if not acquired:
                raise TimeoutError
            model = self._load_locked(path)
            chunks = [
                np.asarray(part.audio).reshape(-1)
                for part in model.generate_voice_design(
                    text=text,
                    instruct=prompt,
                    language="auto",
                    verbose=False,
                    max_tokens=min(360, handler._estimate_max_new_tokens(text)),
                )
            ]
            if not chunks or not any(chunk.size for chunk in chunks):
                raise RuntimeError("Voice design produced no audio.")
            return wav_bytes(np.concatenate(chunks), model.sample_rate)

    def clone(self, handler, reference, text, language=None):
        import mlx.core as mx

        path = model_path(BASE_MODEL, BASE_REVISION)
        samples = decode_audio(reference.audio, REFERENCE_RATE)

        def generate(**kwargs):
            # The handler calls this iterator under its shared, reentrant MLX lock.
            model = self._load_locked(path)
            if not model.speech_tokenizer.has_encoder:
                raise RuntimeError("The Base model is missing its reference-audio encoder.")
            yield from model.generate(
                ref_audio=mx.array(samples),
                ref_text=reference.transcript,
                lang_code=language or handler.language,
                **kwargs,
            )

        yield from handler._stream_mlx_generation(
            generate,
            label="saved_voice",
            max_tokens=handler._estimate_max_new_tokens(text),
            text=text,
        )
