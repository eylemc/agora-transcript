#!/usr/bin/env bash
# Public GitHub repo; HTTPS cloning requires no account or SSH key.
set -euo pipefail

sync_transcript_repo() {
  local target="$1" remote="$2" origin
  if [[ ! -e "$target" ]]; then
    mkdir -p -- "$(dirname -- "$target")"
    git clone --branch main --single-branch "$remote" "$target" || {
      echo 'Repo indirilemedi. İnternet bağlantısını ve GitHub erişimini kontrol edin.' >&2
      return 1
    }
    return
  fi
  [[ -d "$target/.git" ]] || { echo 'Hedef var fakat Git reposu değil; değiştirilmedi.' >&2; return 1; }
  origin="$(git -C "$target" remote get-url origin)"
  case "$origin" in
    git@github.com:eylemc/agora-transcript.git|https://github.com/eylemc/agora-transcript.git) ;;
    *) echo 'Hedef başka bir repoya ait; değiştirilmedi.' >&2; return 1 ;;
  esac
  [[ "$(git -C "$target" branch --show-current)" == main ]] || {
    echo 'Hedef main dalında değil; dal değiştirilmedi.' >&2; return 1;
  }
  [[ -z "$(git -C "$target" status --porcelain)" ]] || {
    echo 'Yerel değişiklikler var. Önce kaydedin veya başka kurulum hedefi seçin; dosyalar silinmedi.' >&2
    return 1
  }
  git -C "$target" fetch origin main
  git -C "$target" merge --ff-only FETCH_HEAD
}

install_transcript_main() {
  local transcript_repo_url="${AGORA_TRANSCRIPT_REPO_URL:-https://github.com/eylemc/agora-transcript.git}"
  local transcript_repo_dir="${AGORA_TRANSCRIPT_REPO_DIR:-$HOME/agora-transcript-public}"
  local transcript_device=cuda transcript_check=1 transcript_arg
  for transcript_arg in "$@"; do
    case "$transcript_arg" in
      --cpu) transcript_device=cpu ;;
      --skip-model-check) transcript_check=0 ;;
      --help|-h)
        echo 'Kullanım: bash install-agora-transcript.sh [--cpu] [--skip-model-check]'
        echo 'Varsayılan: ~/agora-transcript-public, Python 3.12, GPU ve large-v3 çalışma testi.'
        echo 'AGORA_TRANSCRIPT_REPO_DIR: hedef; AGORA_TRANSCRIPT_REPO_URL: GitHub SSH/HTTPS adresi.'
        return 0 ;;
      *) echo "Bilinmeyen seçenek: $transcript_arg" >&2; return 2 ;;
    esac
  done
  [[ "$(uname -s)" == Linux ]] || { echo 'Bu kurucu Agora/Linux içindir.' >&2; return 1; }
  if [[ "${EUID:-$(id -u)}" == 0 ]]; then
    echo 'Root olarak çalıştırmayın. Kendi kullanıcınızla çalıştırın; yalnız apt gerekirse sudo istenir.' >&2
    return 1
  fi
  case "$transcript_repo_url" in
    git@github.com:eylemc/agora-transcript.git|https://github.com/eylemc/agora-transcript.git) ;;
    *) echo 'Repo adresi eylemc/agora-transcript için SSH/HTTPS olmalı; URL içinde token kullanmayın.' >&2; return 1 ;;
  esac
  local transcript_missing=() transcript_package
  for transcript_package in git curl unzip; do
    command -v "$transcript_package" >/dev/null 2>&1 || transcript_missing+=("$transcript_package")
  done
  if (( ${#transcript_missing[@]} )); then
    command -v apt-get >/dev/null && command -v sudo >/dev/null || {
      echo "Eksik sistem araçları: ${transcript_missing[*]}" >&2; return 1;
    }
    sudo apt-get update
    sudo apt-get install -y ca-certificates "${transcript_missing[@]}"
  fi
  if [[ "$transcript_device" == cuda ]]; then
    command -v nvidia-smi >/dev/null && nvidia-smi --query-gpu=name,memory.free --format=csv,noheader || {
      echo 'NVIDIA aygıt/sürücü kontrolü başarısız. CPU kurulumu için --cpu kullanın.' >&2; return 1;
    }
  fi
  sync_transcript_repo "$transcript_repo_dir" "$transcript_repo_url"
  transcript_repo_dir="$(cd -- "$transcript_repo_dir" && pwd)"
  local transcript_app="$transcript_repo_dir/src/agora-transcript"
  [[ -f "$transcript_app/install.sh" ]] || { echo 'Repoda transkript uygulaması bulunamadı.' >&2; return 1; }
  export PATH="$transcript_app/.tools/uv:$transcript_app/.tools/deno/bin:$PATH"
  local transcript_deno_ok=0 transcript_deno_version transcript_deno_major
  if command -v deno >/dev/null 2>&1; then
    transcript_deno_version="$(deno --version | head -n 1)"
    transcript_deno_major="${transcript_deno_version#deno }"
    transcript_deno_major="${transcript_deno_major%%.*}"
    if [[ "$transcript_deno_major" =~ ^[0-9]+$ ]] && (( transcript_deno_major >= 2 )); then
      transcript_deno_ok=1
    fi
  fi
  if [[ "$transcript_deno_ok" == 0 ]]; then
    local transcript_deno_installer
    transcript_deno_installer="$(mktemp)"
    curl --fail --show-error --location --proto '=https' --tlsv1.2 --retry 2 \
      https://deno.land/install.sh -o "$transcript_deno_installer"
    DENO_INSTALL="$transcript_app/.tools/deno" sh "$transcript_deno_installer" --no-modify-path
    rm -f -- "$transcript_deno_installer"
  fi
  deno --version
  if [[ "$transcript_device" == cuda ]]; then
    bash "$transcript_app/install.sh" --gpu
  else
    bash "$transcript_app/install.sh" --cpu
  fi
  bash "$transcript_app/run.sh" --doctor
  if [[ "$transcript_check" == 1 ]]; then
    bash "$transcript_app/run.sh" --runtime-check --device "$transcript_device"
  fi
  local transcript_launcher="$HOME/.local/bin/agora-transcript" transcript_launcher_tmp
  mkdir -p -- "$(dirname -- "$transcript_launcher")"
  if [[ -e "$transcript_launcher" ]] && ! grep -q '^# Managed by Agora Transcript installer$' "$transcript_launcher"; then
    echo 'Aynı adda başka bir komut var; değiştirilmedi.' >&2
    return 1
  fi
  transcript_launcher_tmp="$(mktemp "$(dirname -- "$transcript_launcher")/.agora-transcript.XXXXXX")"
  {
    printf '%s\n' '#!/usr/bin/env bash' '# Managed by Agora Transcript installer' 'set -euo pipefail'
    printf 'exec bash %q --output %q "$@"\n' "$transcript_app/run.sh" "$HOME/agora-transcripts"
  } > "$transcript_launcher_tmp"
  chmod 755 "$transcript_launcher_tmp"
  mv -- "$transcript_launcher_tmp" "$transcript_launcher"
  echo "Kurulum tamamlandı: $(git -C "$transcript_repo_dir" rev-parse --short HEAD)"
  if [[ "$transcript_check" == 0 ]]; then
    echo 'Model çalışma testi atlandı. İlk ses çalıştırmasında model indirilebilir.'
  fi
  printf 'Çalıştır: %q %q --mode audio --device %s\n' \
    "$transcript_launcher" 'https://www.youtube.com/watch?v=cgBmqZE8XCg' "$transcript_device"
  echo "Dökümler: $HOME/agora-transcripts"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  install_transcript_main "$@"
fi
