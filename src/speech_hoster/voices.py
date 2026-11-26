"""Portable voice references and the local, persistent voice library."""

from __future__ import annotations

import base64
import io
import math
import os
import sqlite3
import wave
from contextlib import closing
from pathlib import Path
from typing import Annotated, Literal
from uuid import uuid4

import numpy as np
import soundfile as sf
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

BASE_MODEL = "mlx-community/Qwen3-TTS-12Hz-1.7B-Base-6bit"
BASE_REVISION = "34ff5318365b59cba9c03ff729f2eee0814caf72"
DESIGN_MODEL = "mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-6bit"
DESIGN_REVISION = "ffc6545dc9cb086950aa46c6cd3db490e6ece3e1"
PREVIEW_TEXT = "Hello! It is nice to meet you."
REFERENCE_RATE = 24000
MAX_SECONDS = 30
MAX_AUDIO_BYTES = 16 * 1024 * 1024
VoiceKind = Literal["cloned", "designed"]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Transcript = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
EncodedAudio = Annotated[str, Field(min_length=1, max_length=4 * ((MAX_AUDIO_BYTES + 2) // 3))]


class VoiceInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Reference(VoiceInput):
    audio: EncodedAudio
    transcript: Transcript


VoiceID = Annotated[str, Field(pattern=r"^voice_[a-f0-9]{32}$")]


class NewVoice(Reference):
    id: VoiceID = Field(default_factory=lambda: "voice_" + uuid4().hex)
    name: Name
    type: VoiceKind
    prompt: Transcript | None = None


class VoicePackage(NewVoice):
    version: Literal[1]
    id: VoiceID = Field(...)
    synthesis_model: str = Field(max_length=200)
    design_model: str | None = Field(default=None, max_length=200)

    def summary(self):
        return self.model_dump(include={"id", "name", "type"})


class InvalidRecording(ValueError):
    pass


class VoiceConflict(ValueError):
    pass


def decode_audio(encoded: str, rate: int = REFERENCE_RATE) -> np.ndarray:
    from scipy.signal import resample_poly

    try:
        try:
            raw = base64.b64decode(encoded, validate=True)
        except ValueError as exc:
            raise InvalidRecording("The recording contains invalid base64 data.") from exc
        if len(raw) > MAX_AUDIO_BYTES:
            raise InvalidRecording("Choose a recording of 16 MB or less.")
        with sf.SoundFile(io.BytesIO(raw)) as sound:
            if not (1 <= sound.channels <= 8 and 8000 <= sound.samplerate <= 192000):
                raise InvalidRecording("Use audio with 1–8 channels and an 8–192 kHz sample rate.")
            if not 0 < sound.frames <= MAX_SECONDS * sound.samplerate:
                raise InvalidRecording(f"Choose a recording up to {MAX_SECONDS} seconds long.")
            samples = sound.read(dtype="float32", always_2d=True).mean(axis=1)
            if samples.size != sound.frames or not np.isfinite(samples).all():
                raise InvalidRecording("The recording is incomplete or contains invalid samples.")
            if sound.samplerate != rate:
                divisor = math.gcd(sound.samplerate, rate)
                samples = resample_poly(samples, rate // divisor, sound.samplerate // divisor)
    except sf.LibsndfileError as exc:
        raise InvalidRecording("Choose a readable WAV, AIFF, FLAC, or MP3 recording.") from exc
    if not samples.size or np.max(np.abs(samples)) < 1e-5:
        raise InvalidRecording("The recording contains no audible speech.")
    return samples


def wav_bytes(samples: np.ndarray, rate: int) -> bytes:
    data = io.BytesIO()
    with wave.open(data, "wb") as wav:
        wav.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        wav.writeframes(np.clip(np.rint(samples * 32768), -32768, 32767).astype("<i2").tobytes())
    return data.getvalue()


class VoiceLibrary:
    def __init__(self, directory: Path | None = None):
        if directory is None:
            home = (
                os.environ.get("SPEECH_HOSTER_HOME")
                or os.environ.get("REACHY_APP_HOME")
                or (Path.home() / "Library/Application Support/Speech2SpeechModelHoster")
            )
            directory = Path(home) / "voices"
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path = directory / "library.sqlite3"
        with closing(sqlite3.connect(self.path)) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS voices (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL,
                    type TEXT NOT NULL, package TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)

    def list(self):
        with closing(sqlite3.connect(self.path)) as db:
            db.row_factory = sqlite3.Row
            return [
                dict(row)
                for row in db.execute(
                    "SELECT id, name, type FROM voices ORDER BY name COLLATE NOCASE, id"
                )
            ]

    def get(self, voice_id: str) -> VoicePackage | None:
        with closing(sqlite3.connect(self.path)) as db:
            row = db.execute("SELECT package FROM voices WHERE id=?", (voice_id,)).fetchone()
        return VoicePackage.model_validate_json(row[0]) if row else None

    def save(self, voice: NewVoice) -> VoicePackage:
        values = voice.model_dump()
        samples = decode_audio(voice.audio)
        values["audio"] = base64.b64encode(wav_bytes(samples, REFERENCE_RATE)).decode("ascii")
        package = VoicePackage(
            **values,
            version=1,
            synthesis_model=f"{BASE_MODEL}@{BASE_REVISION}",
            design_model=f"{DESIGN_MODEL}@{DESIGN_REVISION}" if voice.type == "designed" else None,
        )
        return self.store(package)

    def store(self, package: VoicePackage) -> VoicePackage:
        payload = package.model_dump_json()
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute(
                "INSERT OR IGNORE INTO voices VALUES (?, ?, ?, ?)",
                (package.id, package.name, package.type, payload),
            )
            row = db.execute("SELECT package FROM voices WHERE id=?", (package.id,)).fetchone()
            if row[0] != payload:
                raise VoiceConflict("A different voice already uses that ID.")
        return package

    def default(self, fallback: str) -> str:
        with closing(sqlite3.connect(self.path)) as db:
            row = db.execute("SELECT value FROM settings WHERE key='default_voice'").fetchone()
        return row[0] if row else fallback

    def set_default(self, voice_id: str):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("INSERT OR REPLACE INTO settings VALUES ('default_voice', ?)", (voice_id,))
