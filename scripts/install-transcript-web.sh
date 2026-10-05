#!/usr/bin/env bash
set -euo pipefail
[[ "$(id -u)" != 0 ]] || { echo 'sudo olmadan çalıştırın.' >&2; exit 1; }
transcript_repo="$(cd -- "$(dirname -- "$0")/.." && pwd)"
transcript_app="$transcript_repo/src/agora-transcript"
[[ -x "$transcript_app/.venv/bin/python" ]] || { echo 'Önce transkript motorunu kurun.' >&2; exit 1; }
[[ "$transcript_app" =~ ^/[a-zA-Z0-9_./-]+$ ]] || { echo 'Kurulum yolunda özel karakter desteklenmiyor.' >&2; exit 1; }
transcript_unit="$HOME/.config/systemd/user/agora-transcript-web.service"
mkdir -p -- "$(dirname -- "$transcript_unit")"
if [[ -e "$transcript_unit" ]] && ! grep -q '^# Managed by Agora Transcript web installer$' "$transcript_unit"; then
  echo 'Aynı adda başka servis var; değiştirilmedi.' >&2; exit 1
fi
if systemctl --user is-active --quiet agora-transcript-web.service; then
  echo 'Web servisi çalışıyor. Aktif döküm bitince servisi durdurup tekrar deneyin.' >&2; exit 1
fi
cat > "$transcript_unit" <<EOF
# Managed by Agora Transcript web installer
[Unit]
Description=Agora Transcript local web interface
After=network.target
[Service]
Type=simple
ExecStart=$transcript_app/.venv/bin/python $transcript_app/web.py
WorkingDirectory=$transcript_app
Restart=on-failure
RestartSec=5
UMask=0077
[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now agora-transcript-web.service
systemctl --user --no-pager status agora-transcript-web.service
echo 'Arayüz: http://127.0.0.1:8766 — Mac üzerinden aynı portla SSH tüneli açın.'
echo 'Kullanıcı oturumu kapanınca servis durabilir. Kalıcılık gerekiyorsa: loginctl enable-linger "$USER"'
