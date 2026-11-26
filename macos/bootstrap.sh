#!/bin/bash
set -euo pipefail
resources="$1"
shift
support="${SPEECH_HOSTER_HOME:-${REACHY_APP_HOME:-$HOME/Library/Application Support/Speech2SpeechModelHoster}}"
mkdir -p "$support"
cd "$support"
export UV_CACHE_DIR="$support/cache/uv"
export UV_PYTHON_INSTALL_DIR="$support/python"
export UV_PROJECT_ENVIRONMENT="$support/venv"
export SPEECH_HOSTER_CACHE="$support/cache"
export PYTHONUNBUFFERED=1
export HF_HOME="$support/cache/huggingface"
export TORCH_HOME="$support/cache/torch"
export NLTK_DATA="$support/cache/nltk"
# Install privately: no Homebrew, sudo, or shell-profile changes.
if [[ ! -x "$support/bin/uv" ]]; then
  echo 'Installing uv…'
  /usr/bin/curl --fail --location --retry 3 https://astral.sh/uv/0.13.7/install.sh -o "$support/uv-install.sh"
  UV_UNMANAGED_INSTALL="$support/bin" /bin/sh "$support/uv-install.sh"
fi
# Copy the shipped source; keep the environment and model cache across launches.
mkdir -p "$support/project"
/usr/bin/rsync -a --delete "$resources/project/" "$support/project/"
echo 'Preparing Python and locked dependencies…'
"$support/bin/uv" sync --project "$support/project" --locked --extra server --no-dev --managed-python
if [[ "${1:-}" == "--prepare-only" ]]; then
  "$support/venv/bin/python" -c 'from pathlib import Path; from speech_hoster.desktop import prepare_profile; prepare_profile(Path("desktop-profile.yaml"))'
  echo 'Setup ready. Press Start server.'
  exit 0
fi
exec "$support/venv/bin/python" -m speech_hoster.desktop "$@"
