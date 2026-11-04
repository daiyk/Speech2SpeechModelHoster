from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from reachy_local.probe import DEFAULT_URL, probe, validate_url
from reachy_local.runtime import DEFAULT_PROFILE, doctor, require_server, runtime_environment, serve


def port_number(value: str) -> int:
    port = int(value)
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("Port must be between 1 and 65535.")
    return port


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local Hugging Face speech server for Reachy Mini")
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("serve", "doctor"):
        child = commands.add_parser(command)
        child.add_argument("--config", type=Path, default=DEFAULT_PROFILE)
        host = child.add_mutually_exclusive_group()
        host.add_argument("--lan", action="store_true", help="Bind on all network interfaces")
        host.add_argument("--host", default="127.0.0.1")
        child.add_argument("--port", type=port_number, default=8765)
        if command == "serve":
            child.add_argument("--offline", action="store_true", help="Use cached HF weights")
    check = commands.add_parser(
        "check", help="Check a running server using Reachy's session format"
    )
    check.add_argument("--url", default=DEFAULT_URL)
    check.add_argument("--speak", help="Also test a text-triggered spoken reply; no microphone")
    check.add_argument("--wav", type=Path, help="Save test audio as a new 16 kHz PCM16 WAV")
    check.add_argument("--timeout", type=float, default=120)
    talk = commands.add_parser("talk", help="Use the Mac microphone/speakers with a running server")
    talk.add_argument("--url", default=DEFAULT_URL)
    talk.add_argument("--echo-cancellation", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "serve":
            serve(args.config, "0.0.0.0" if args.lan else args.host, args.port, args.offline)
        elif args.command == "doctor":
            print(
                json.dumps(
                    doctor(args.config, "0.0.0.0" if args.lan else args.host, args.port), indent=2
                )
            )
        elif args.command == "check":
            print(
                json.dumps(
                    asyncio.run(
                        probe(args.url, speak=args.speak, wav_path=args.wav, timeout=args.timeout)
                    ),
                    indent=2,
                )
            )
        elif args.command == "talk":
            require_server()
            validate_url(args.url)
            command = [sys.executable, "-m", "speech_to_speech.cli", "talk", "--url", args.url]
            if args.echo_cancellation:
                command.append("--echo-cancellation")
            os.execve(sys.executable, command, runtime_environment("127.0.0.1", 8765))
    except KeyboardInterrupt:
        return 130
    except TimeoutError:
        print(
            "Check timed out. Verify model loading is complete and no other client is connected.",
            file=sys.stderr,
        )
        return 1
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
