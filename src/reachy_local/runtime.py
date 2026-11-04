"""Use upstream's server unchanged; only configure its process environment."""

from __future__ import annotations

import importlib.metadata
import os
import platform
import sys
from pathlib import Path

UPSTREAM_VERSION = "1.1.0"
DEFAULT_PROFILE = Path(__file__).parent / "profiles" / "mac.yaml"


def require_server() -> None:
    try:
        installed = importlib.metadata.version("speech-to-speech")
    except importlib.metadata.PackageNotFoundError as exc:
        raise RuntimeError("Server is not installed. Run ./scripts/setup.sh first.") from exc
    if installed != UPSTREAM_VERSION:
        raise RuntimeError(
            f"Expected speech-to-speech {UPSTREAM_VERSION}, found {installed}. "
            "Run ./scripts/setup.sh to restore the pinned environment."
        )
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise RuntimeError("This repository's tested target is an Apple Silicon Mac.")


def runtime_environment(host: str, port: int, offline: bool = False) -> dict[str, str]:
    environment = dict(os.environ)
    environment["REACHY_SPEECH_HOST"] = host
    environment["REACHY_SPEECH_PORT"] = str(port)
    # All generated caches stay inside the checkout unless explicitly configured.
    cache = Path(os.environ.get("REACHY_SPEECH_CACHE", ".cache")).resolve()
    for key, directory in {
        "HF_HOME": "huggingface",
        "TORCH_HOME": "torch",
        "NLTK_DATA": "nltk",
    }.items():
        environment.setdefault(key, str(cache / directory))
    if offline:
        environment["HF_HUB_OFFLINE"] = "1"
        environment["TRANSFORMERS_OFFLINE"] = "1"
    return environment


def resolve_profile(config: Path, host: str, port: int, offline: bool = False):
    from speech_to_speech.config import load_config, resolve_config

    resolved = resolve_config(load_config(config), environ=runtime_environment(host, port, offline))
    server = resolved.runtime["server"]
    if server["host"] != host or server["port"] != port:
        raise ValueError(
            "Profile listener conflicts with launch options. Set runtime.server.host to "
            "{env: REACHY_SPEECH_HOST} and runtime.server.port to {env: REACHY_SPEECH_PORT}."
        )
    return resolved


def serve(config: Path, host: str, port: int, offline: bool = False) -> None:
    require_server()
    resolved = resolve_profile(config, host, port, offline)
    server = resolved.runtime["server"]
    if len(resolved.pipelines) != 1:
        raise ValueError("Select exactly one pipeline in your configuration file.")
    advertised_host = server["host"]
    if advertised_host == "0.0.0.0":
        advertised_host = "<this-Mac-LAN-IP>"
        print("LAN mode: the upstream endpoint has no authentication; use a trusted LAN.")
    print(f"Reachy endpoint: ws://{advertised_host}:{server['port']}/v1/realtime")
    print("Loading models; the first start downloads weights. Stop with Ctrl+C.", flush=True)
    environment = runtime_environment(host, port, offline)
    for key in ("HF_HOME", "TORCH_HOME", "NLTK_DATA"):
        Path(environment[key]).mkdir(parents=True, exist_ok=True)
    os.execve(
        sys.executable,
        [sys.executable, "-m", "speech_to_speech.cli", "serve", "-f", str(config.resolve())],
        environment,
    )


def doctor(config: Path, host: str, port: int) -> dict:
    require_server()
    resolved = resolve_profile(config, host, port)
    return {
        "python": platform.python_version(),
        "platform": f"{platform.system()} {platform.machine()}",
        "speech_to_speech": importlib.metadata.version("speech-to-speech"),
        "config_valid": True,
        "pipelines": list(resolved.pipelines),
        "models_loaded": False,
        "note": "Configuration validation only. Run check against the running server.",
    }
