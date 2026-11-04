"""Check launch/configuration behavior without importing inference models."""

from __future__ import annotations

import importlib.metadata
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from reachy_local import cli, runtime


def test_runtime_environment_preserves_explicit_cache_paths_and_parent_environment(
    monkeypatch,
    tmp_path,
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HF_HOME", "/existing/model/cache")
    monkeypatch.delenv("TORCH_HOME", raising=False)
    monkeypatch.delenv("NLTK_DATA", raising=False)
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    monkeypatch.delenv("TRANSFORMERS_OFFLINE", raising=False)
    monkeypatch.delenv("REACHY_SPEECH_CACHE", raising=False)
    environment = runtime.runtime_environment("0.0.0.0", 9876, offline=True)
    assert environment["HF_HOME"] == "/existing/model/cache"
    assert environment["TORCH_HOME"] == str(tmp_path / ".cache" / "torch")
    assert environment["NLTK_DATA"] == str(tmp_path / ".cache" / "nltk")
    assert environment["REACHY_SPEECH_HOST"] == "0.0.0.0"
    assert environment["REACHY_SPEECH_PORT"] == "9876"
    assert environment["HF_HUB_OFFLINE"] == environment["TRANSFORMERS_OFFLINE"] == "1"
    assert "HF_HUB_OFFLINE" not in runtime.os.environ


def test_require_server_rejects_missing_and_drifted_installation(monkeypatch):
    def missing(_name):
        raise importlib.metadata.PackageNotFoundError("speech-to-speech")

    monkeypatch.setattr(runtime.importlib.metadata, "version", missing)
    with pytest.raises(RuntimeError, match="setup.sh"):
        runtime.require_server()
    monkeypatch.setattr(runtime.importlib.metadata, "version", lambda _name: "99.0.0")
    with pytest.raises(RuntimeError, match="Expected speech-to-speech"):
        runtime.require_server()


@pytest.mark.parametrize("system,machine", [("Linux", "aarch64"), ("Darwin", "x86_64")])
def test_require_server_rejects_unsupported_platform(monkeypatch, system, machine):
    monkeypatch.setattr(runtime.importlib.metadata, "version", lambda _: runtime.UPSTREAM_VERSION)
    monkeypatch.setattr(runtime.platform, "system", lambda: system)
    monkeypatch.setattr(runtime.platform, "machine", lambda: machine)
    with pytest.raises(RuntimeError, match="Apple Silicon"):
        runtime.require_server()


def test_serve_executes_fixed_python_module_with_literal_config_path(monkeypatch, tmp_path):
    config = tmp_path / "profile with spaces; $(false).yaml"
    config.write_text("not read: configuration resolver is replaced in this unit test\n")
    monkeypatch.setattr(runtime, "require_server", lambda: None)
    monkeypatch.setattr(
        runtime,
        "resolve_profile",
        lambda *args: SimpleNamespace(
            runtime={"server": {"host": "127.0.0.1", "port": 8765}},
            pipelines={"mac": {}},
        ),
    )
    monkeypatch.setenv("REACHY_SPEECH_CACHE", str(tmp_path / "cache"))
    for name in ("HF_HOME", "TORCH_HOME", "NLTK_DATA"):
        monkeypatch.delenv(name, raising=False)
    calls = []
    monkeypatch.setattr(runtime.os, "execve", lambda *args: calls.append(args))

    runtime.serve(config, "127.0.0.1", 8765, offline=True)

    executable, argv, environment = calls[0]
    assert executable == sys.executable
    assert argv == [
        sys.executable,
        "-m",
        "speech_to_speech.cli",
        "serve",
        "-f",
        str(config.resolve()),
    ]
    assert environment["HF_HUB_OFFLINE"] == "1"
    assert all(Path(environment[key]).is_dir() for key in ("HF_HOME", "TORCH_HOME", "NLTK_DATA"))


def test_serve_rejects_multiple_pipelines_before_launch(monkeypatch):
    monkeypatch.setattr(runtime, "require_server", lambda: None)
    monkeypatch.setattr(
        runtime,
        "resolve_profile",
        lambda *args: SimpleNamespace(
            runtime={"server": {}},
            pipelines={"one": {}, "two": {}},
        ),
    )
    with pytest.raises(ValueError, match="exactly one"):
        runtime.serve(Path("config.yaml"), "127.0.0.1", 8765)


def test_doctor_reports_configuration_only(monkeypatch):
    monkeypatch.setattr(runtime, "require_server", lambda: None)
    monkeypatch.setattr(runtime.importlib.metadata, "version", lambda _: runtime.UPSTREAM_VERSION)
    monkeypatch.setattr(
        runtime,
        "resolve_profile",
        lambda *args: SimpleNamespace(
            pipelines={"mac": {}},
        ),
    )
    result = runtime.doctor(Path("config.yaml"), "127.0.0.1", 8765)
    assert result["config_valid"] is True
    assert result["models_loaded"] is False
    assert result["pipelines"] == ["mac"]


@pytest.mark.parametrize("host,port", [("127.0.0.1", 8765), ("0.0.0.0", 9876)])
def test_real_profile_resolves_requested_listener_without_loading_models(host, port):
    pytest.importorskip("speech_to_speech.config", reason="Requires the server extra")
    resolved = runtime.resolve_profile(runtime.DEFAULT_PROFILE, host, port)
    assert resolved.runtime["server"]["host"] == host
    assert resolved.runtime["server"]["port"] == port


@pytest.mark.parametrize(
    "field,literal,host,port",
    [
        ("host", "127.0.0.1", "0.0.0.0", 8765),
        ("host", "0.0.0.0", "127.0.0.1", 8765),
        ("port", "8765", "127.0.0.1", 9876),
    ],
)
def test_literal_profile_cannot_silently_override_requested_listener(
    tmp_path,
    field,
    literal,
    host,
    port,
):
    pytest.importorskip("speech_to_speech.config", reason="Requires the server extra")
    profile = tmp_path / "custom.yaml"
    original = runtime.DEFAULT_PROFILE.read_text()
    profile.write_text(original.replace(f"{{env: REACHY_SPEECH_{field.upper()}}}", literal))
    with pytest.raises(ValueError, match="REACHY_SPEECH_"):
        runtime.resolve_profile(profile, host, port)


def test_cli_lan_selection_and_custom_port(monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "serve", lambda *args: calls.append(args))
    assert cli.main(["serve", "--lan", "--port", "9876", "--offline"]) == 0
    assert calls[0][1:] == ("0.0.0.0", 9876, True)


@pytest.mark.parametrize(
    "arguments",
    [
        ["serve", "--port", "0"],
        ["doctor", "--port", "65536"],
        ["serve", "--port", "abc"],
        ["serve", "--lan", "--host", "127.0.0.1"],
    ],
)
def test_cli_rejects_invalid_launch_options(arguments):
    with pytest.raises(SystemExit) as exc:
        cli.main(arguments)
    assert exc.value.code == 2


def test_cli_check_prints_json_and_reports_timeout(monkeypatch, capsys):
    async def okay(*args, **kwargs):
        return {"session_configured": True, "speech_tested": False}

    monkeypatch.setattr(cli, "probe", okay)
    assert cli.main(["check"]) == 0
    assert json.loads(capsys.readouterr().out)["speech_tested"] is False

    async def timeout(*args, **kwargs):
        raise TimeoutError

    monkeypatch.setattr(cli, "probe", timeout)
    assert cli.main(["check"]) == 1
    assert "timed out" in capsys.readouterr().err


def test_talk_executes_upstream_client_with_literal_url(monkeypatch):
    monkeypatch.setattr(cli, "require_server", lambda: None)
    calls = []
    monkeypatch.setattr(cli.os, "execve", lambda *args: calls.append(args))
    url = "ws://localhost:8765/v1/realtime?tag=$(false)"
    assert cli.main(["talk", "--url", url, "--echo-cancellation"]) == 0
    assert calls[0][1] == [
        sys.executable,
        "-m",
        "speech_to_speech.cli",
        "talk",
        "--url",
        url,
        "--echo-cancellation",
    ]
