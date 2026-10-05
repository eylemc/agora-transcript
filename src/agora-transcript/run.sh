#!/usr/bin/env bash
set -euo pipefail
transcript_root="$(cd -- "$(dirname -- "$0")" && pwd)"
export PATH="$transcript_root/.tools/uv:$transcript_root/.tools/deno/bin:$PATH"
transcript_python="$transcript_root/.venv/bin/python"
if [[ ! -x "$transcript_python" ]]; then
  echo 'Önce bash install.sh --gpu çalıştırın.' >&2
  exit 1
fi
transcript_cuda_libs="$("$transcript_python" - <<'PY'
from pathlib import Path
import site
paths=[]
for base in site.getsitepackages():
    for package in ('cublas','cudnn'):
        path=Path(base)/'nvidia'/package/'lib'
        if path.is_dir(): paths.append(str(path))
print(':'.join(paths))
PY
)"
if [[ -n "$transcript_cuda_libs" ]]; then
  export LD_LIBRARY_PATH="$transcript_cuda_libs${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi
exec "$transcript_python" "$transcript_root/agora_transcript.py" "$@"
