#!/usr/bin/env python3
"""Single-user loopback UI. Reach remotely through an SSH tunnel."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
from agora_transcript import youtube_url

APP = Path(__file__).resolve().parent
FILES = {'transcript.txt', 'transcript.srt', 'transcript.json', 'review.json', 'manifest.json'}
JOB = re.compile(r'\d{8}T\d{6}Z-[a-f0-9]{8}')

class Jobs:
    def __init__(self, root):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.active = False
        self.log = ''
        self.exit_code = None

    def start(self, body):
        url = youtube_url(body.get('url', ''))
        mode = body.get('mode', 'audio')
        device = body.get('device', 'cuda')
        language = body.get('language', 'tr')
        if mode not in ('audio', 'auto', 'captions') or device not in ('cuda', 'cpu', 'auto') or language not in ('tr', 'en'):
            raise ValueError('Geçersiz çözümleme ayarı.')
        with self.lock:
            if self.active:
                return False
            self.active, self.log, self.exit_code = True, 'İş başlatılıyor…\n', None
        threading.Thread(target=self.run, args=(url, mode, device, language), daemon=True).start()
        return True

    def run(self, url, mode, device, language):
        try:
            command = ['bash', str(APP / 'run.sh'), url, '--output', str(self.root), '--mode', mode,
                       '--device', device, '--language', language]
            env = dict(os.environ, PYTHONUNBUFFERED='1')
            with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  text=True, encoding='utf-8', errors='replace', env=env) as process:
                for line in process.stdout:
                    with self.lock:
                        self.log = (self.log + line)[-18000:]
                code = process.wait()
            with self.lock:
                self.exit_code = code
        except Exception as error:
            with self.lock:
                self.log += '\nİş başlatılamadı: ' + str(error)
                self.exit_code = 1
        finally:
            with self.lock:
                self.active = False

    def file(self, job, name):
        if not JOB.fullmatch(job) or name not in FILES:
            raise ValueError('Dosya bulunamadı.')
        path = self.root / job / name
        if path.is_symlink() or path.parent.is_symlink() or not path.is_file():
            raise ValueError('Dosya bulunamadı.')
        return path

    def state(self):
        jobs = []
        for directory in sorted(self.root.iterdir(), reverse=True):
            if not JOB.fullmatch(directory.name) or directory.is_symlink() or not directory.is_dir():
                continue
            try:
                manifest = json.loads(self.file(directory.name, 'manifest.json').read_text())
            except (ValueError, OSError):
                continue
            jobs.append({'id': directory.name, 'status': manifest.get('status'),
                         'title': (manifest.get('video') or {}).get('title') or manifest.get('source', directory.name),
                         'started_at': manifest.get('started_at'), 'segments': manifest.get('segment_count'),
                         'files': [name for name in sorted(FILES) if (directory / name).is_file()]})
        with self.lock:
            return {'active': self.active, 'log': self.log, 'exit_code': self.exit_code, 'jobs': jobs}

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, status, content, content_type='application/json; charset=utf-8', attachment=None):
        data = content if isinstance(content, bytes) else json.dumps(content, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        if attachment:
            self.send_header('Content-Disposition', 'attachment; filename="' + attachment + '"')
        self.end_headers()
        self.wfile.write(data)

    def allowed(self):
        port = self.server.server_port
        hosts = {f'127.0.0.1:{port}', f'localhost:{port}'}
        if self.headers.get('Host') not in hosts:
            self.reply(403, {'error': 'Yalnız localhost erişimi desteklenir.'})
            return False
        origin = self.headers.get('Origin')
        if origin and origin not in {'http://' + host for host in hosts}:
            self.reply(403, {'error': 'İstek kaynağı reddedildi.'})
            return False
        return True

    def do_GET(self):
        if not self.allowed():
            return
        path = urlsplit(self.path).path
        if path in ('/', '/app.js', '/style.css'):
            filename, kind = {'/': ('index.html', 'text/html'), '/app.js': ('app.js', 'text/javascript'),
                              '/style.css': ('style.css', 'text/css')}[path]
            return self.reply(200, (APP / 'web' / filename).read_bytes(), kind + '; charset=utf-8')
        if path == '/api/state':
            return self.reply(200, self.server.jobs.state())
        parts = path.strip('/').split('/')
        if len(parts) == 3 and parts[0] in ('download', 'preview'):
            try:
                file = self.server.jobs.file(parts[1], parts[2])
                return self.reply(200, file.read_bytes(), 'text/plain; charset=utf-8',
                                  parts[2] if parts[0] == 'download' else None)
            except (ValueError, OSError):
                pass
        self.reply(404, {'error': 'Bulunamadı.'})

    def do_POST(self):
        if not self.allowed():
            return
        if self.path != '/api/jobs':
            return self.reply(404, {'error': 'Bulunamadı.'})
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            return self.reply(415, {'error': 'JSON gerekli.'})
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 4096:
                raise ValueError('İstek boyutu geçersiz.')
            body = json.loads(self.rfile.read(size))
            if not isinstance(body, dict) or not isinstance(body.get('url'), str):
                raise ValueError('YouTube bağlantısı gerekli.')
            if not self.server.jobs.start(body):
                return self.reply(409, {'error': 'Bir işlem çalışıyor. Bitmesini bekleyin.'})
            self.reply(202, {'ok': True})
        except (ValueError, TypeError) as error:
            self.reply(400, {'error': str(error)})


def main():
    parser = argparse.ArgumentParser(description='Agora Transcript yerel web arayüzü')
    parser.add_argument('--port', type=int, default=8766)
    parser.add_argument('--output', default=str(Path.home() / 'agora-transcripts'))
    args = parser.parse_args()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    server.jobs = Jobs(Path(args.output).expanduser())
    print(f'Agora Transcript: http://127.0.0.1:{server.server_port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

if __name__ == '__main__':
    main()
