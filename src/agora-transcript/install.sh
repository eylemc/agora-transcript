#!/usr/bin/env bash
# Install only this application's user-owned environment. Safe to rerun.
set -euo pipefail
cd -- "$(dirname -- "$0")"
transcript_root="$PWD"
case "${1:---gpu}" in
  --gpu) transcript_gpu=1 ;;
  --cpu) transcript_gpu=0 ;;
  *) echo 'Kullanım: bash install.sh [--gpu|--cpu]' >&2; exit 2 ;;
esac
export PATH="$transcript_root/.tools/uv:$transcript_root/.tools/deno/bin:$PATH"
if ! command -v uv >/dev/null 2>&1; then
  command -v curl >/dev/null || { echo 'curl gerekli.' >&2; exit 1; }
  transcript_installer="$(mktemp)"
  trap 'rm -f -- "$transcript_installer"' EXIT
  curl --fail --show-error --location --proto '=https' --tlsv1.2 --retry 2 \
    https://astral.sh/uv/install.sh -o "$transcript_installer"
  UV_UNMANAGED_INSTALL="$transcript_root/.tools/uv" sh "$transcript_installer"
fi
if [[ -e .venv ]]; then
  [[ -x .venv/bin/python ]] || { echo 'Mevcut .venv bozuk; değiştirilmedi.' >&2; exit 1; }
  .venv/bin/python -c 'import sys; assert sys.version_info[:2] == (3,12), "Mevcut .venv Python 3.12 değil; değiştirilmedi."'
else
  uv venv --python 3.12 .venv
fi
uv pip install --python .venv/bin/python -r requirements.txt
if [[ "$transcript_gpu" == 1 ]]; then
  uv pip install --python .venv/bin/python 'nvidia-cublas-cu12>=12,<13' 'nvidia-cudnn-cu12>=9,<10'
fi
uv pip freeze --python .venv/bin/python > installed-versions.txt
echo 'Python ortamı hazır.'
