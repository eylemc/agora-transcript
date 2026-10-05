#!/usr/bin/env python3
"""Local, timestamped transcription. No LLM rewriting or price correction."""
from __future__ import annotations

import argparse
import hashlib
import html
import importlib.metadata
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

VERSION = "0.2.1"
TERMS = "KoinVizyon, Hamsi Gücü, Bitcoin, DXY, USDT, XRP, Brent, TOBO, Matrix, MA20, likidasyon."
NUMBER_WORDS = re.compile(r"\d|\b(?:sıfır|bir|iki|üç|dört|beş|altı|yedi|sekiz|dokuz|on|yirmi|otuz|kırk|elli|altmış|yetmiş|seksen|doksan|yüz|bin|milyon|milyar|dolar|yüzde)\b", re.I)


def dump(path, value):
    path = Path(path)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temp.replace(path)


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def youtube_url(value):
    parsed = urlparse(value)
    if parsed.scheme not in ("https", "http") or parsed.username or parsed.password:
        raise ValueError("Geçerli bir YouTube video bağlantısı gerekli.")
    host = (parsed.hostname or "").lower()
    parts = parsed.path.strip("/").split("/")
    if host in ("youtu.be", "www.youtu.be"):
        vid = parts[0]
    elif host in ("youtube.com", "www.youtube.com", "m.youtube.com"):
        if parsed.path == "/watch":
            vid = parse_qs(parsed.query).get("v", [""])[0]
        elif len(parts) == 2 and parts[0] in ("live", "shorts", "embed"):
            vid = parts[1]
        else:
            vid = ""
    else:
        vid = ""
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", vid):
        raise ValueError("Tek bir YouTube videosu seçin; başka siteler ve oynatma listeleri desteklenmez.")
    return f"https://www.youtube.com/watch?v={vid}"


def timestamp(seconds, srt=False):
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError("Geçersiz zaman damgası.")
    ms = int(seconds * 1000 + 0.5)
    sec, milli = divmod(ms, 1000)
    minute, sec = divmod(sec, 60)
    hour, minute = divmod(minute, 60)
    sep = "," if srt else "."
    return f"{hour:02}:{minute:02}:{sec:02}{sep}{milli:03}"


def validate_segments(segments):
    previous_start = -1.0
    for segment in segments:
        start, end = float(segment["start"]), float(segment["end"])
        if not (math.isfinite(start) and math.isfinite(end) and 0 <= start < end):
            raise ValueError("Bozuk segment zamanlaması; ham kaynak korundu.")
        if start < previous_start:
            raise ValueError("Zaman sırası bozuk; kaynak otomatik olarak yeniden sıralanmadı.")
        previous_start = start


def caption_segments(raw):
    result = []
    for event in raw.get("events", []):
        text = "".join(s.get("utf8", "") for s in event.get("segs", []))
        text = html.unescape(text).strip()
        if not text:
            continue
        if "tStartMs" not in event or "dDurationMs" not in event:
            raise ValueError("Altyazı zamanlaması eksik; ses üzerinden çözümleme gerekli.")
        result.append({"start": event["tStartMs"] / 1000,
                       "end": (event["tStartMs"] + event["dDurationMs"]) / 1000,
                       "text": text, "words": []})
    validate_segments(result)
    if not result:
        raise ValueError("Altyazıda konuşma metni bulunamadı.")
    # Rolling captions may repeat text. Preserve it rather than delete real words.
    return result


def choose_caption(info, language):
    for key, kind in (("subtitles", "manual"), ("automatic_captions", "automatic")):
        tracks = info.get(key) or {}
        for code in (language, language + "-orig"):
            formats = tracks.get(code) or []
            usable = [f for f in formats if f.get("ext") == "json3"
                      and not parse_qs(urlparse(f.get("url", "")).query).get("tlang")]
            if usable:
                return kind, code
    return None


def quality_flags(segment, caption_kind=None):
    flags = []
    if NUMBER_WORDS.search(segment["text"]):
        flags.append("number_or_price_check")
    if segment.get("avg_logprob", 0) < -1.0:
        flags.append("low_model_score")
    if segment.get("no_speech_prob", 0) > 0.6:
        flags.append("possible_non_speech")
    if segment.get("compression_ratio", 0) > 2.4:
        flags.append("possible_repetition")
    if any(w.get("probability", 1) < 0.5 for w in segment.get("words", [])):
        flags.append("low_word_score")
    if caption_kind == "automatic":
        flags.append("automatic_caption_unverified")
    return flags


def export(job, segments, manifest):
    validate_segments(segments)
    reviews, text_lines, subtitles = [], [], []
    prior_end = 0.0
    for index, segment in enumerate(segments, 1):
        flags = quality_flags(segment, manifest.get("caption_kind"))
        if segment["start"] < prior_end:
            flags.append("overlapping_segment_check")
        prior_end = max(prior_end, segment["end"])
        segment["review_flags"] = flags
        start, end, text = segment["start"], segment["end"], segment["text"]
        text_lines.append(f"[{timestamp(start)} – {timestamp(end)}] {text}")
        subtitles.append(f"{index}\n{timestamp(start, True)} --> {timestamp(end, True)}\n{text}\n")
        if flags:
            reviews.append({"segment": index, "start": start, "end": end, "text": text, "flags": flags})
    (job / "transcript.txt").write_text("\n\n".join(text_lines) + "\n", encoding="utf-8")
    (job / "transcript.srt").write_text("\n".join(subtitles), encoding="utf-8")
    dump(job / "transcript.json", {"metadata": manifest, "segments": segments})
    dump(job / "review.json", {"note": "Otomatik kontrol işaretleri hata kanıtı veya kalibre edilmiş güven oranı değildir.", "segments": reviews})


def run_ydl(arguments, cookie_file=None, timeout=300):
    command = [sys.executable, "-m", "yt_dlp", "--ignore-config", "--no-playlist",
               "--no-progress", "--quiet", "--socket-timeout", "30", "--retries", "2"]
    if shutil.which("deno"):
        command += ["--js-runtimes", "deno"]
    elif shutil.which("node"):
        command += ["--js-runtimes", "node"]
    if cookie_file:
        command += ["--cookies", str(Path(cookie_file).resolve())]
    result = subprocess.run(command + arguments, text=True, encoding="utf-8",
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    if result.returncode:
        # Do not expose signed media URLs or cookie contents in persisted logs.
        message = re.sub(r"https?://\S+", "[URL]", result.stderr[-2500:])
        raise RuntimeError(f"YouTube erişimi başarısız. Yerel kayıt dosyası da kullanılabilir.\n{message}")
    return result.stdout


def obtain_youtube(args, job, manifest):
    url = youtube_url(args.input)
    info = json.loads(run_ydl(["--dump-single-json", "--skip-download", "--", url], args.cookies))
    if info.get("is_live") or info.get("live_status") in ("is_live", "is_upcoming", "post_live"):
        raise ValueError("Yayın hâlâ canlı veya arşivi işleniyor; tam kayıt hazır olunca tekrar deneyin.")
    manifest.update({"source": url, "video": {k: info.get(k) for k in
                     ("id", "title", "channel", "duration", "upload_date")}})
    track = choose_caption(info, args.language)
    if args.mode != "audio" and track:
        kind, code = track
        flag = "--write-subs" if kind == "manual" else "--write-auto-subs"
        try:
            run_ydl(["--skip-download", flag, "--sub-langs", code, "--sub-format", "json3",
                     "-o", str(job / "source.%(ext)s"), "--", url], args.cookies)
            candidates = sorted(job.glob("source.*.json3"))
            if len(candidates) != 1:
                raise ValueError("Tek bir JSON3 altyazı dosyası bekleniyordu.")
            segments = caption_segments(json.loads(candidates[0].read_text(encoding="utf-8")))
            manifest.update({"method": "youtube_captions", "caption_kind": kind,
                             "caption_language": code, "source_sha256": sha256(candidates[0])})
            return segments, None
        except (RuntimeError, ValueError, subprocess.TimeoutExpired) as error:
            if args.mode == "captions":
                raise
            manifest["caption_fallback_reason"] = type(error).__name__
            print("Altyazı kullanılamadı; ses üzerinden çözümlemeye geçiliyor.", file=sys.stderr)
    elif args.mode == "captions":
        raise ValueError("Bu dilde özgün altyazı bulunamadı. --mode audio kullanın.")
    print("Yayın sesi indiriliyor…", file=sys.stderr)
    output = run_ydl(["-f", "bestaudio/best", "-o", str(job / "source.%(ext)s"),
                      "--print", "after_move:filepath", "--no-simulate", "--", url],
                     args.cookies, timeout=7200)
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("İndirilen ses dosyası bulunamadı.")
    audio = Path(lines[-1]).resolve()
    if audio.parent != job.resolve() or not audio.is_file():
        raise RuntimeError("İndirilen ses dosyasının konumu doğrulanamadı.")
    return None, audio


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def transcribe_audio(args, audio, job, manifest):
    try:
        import ctranslate2
        from faster_whisper import WhisperModel
    except ImportError as error:
        raise RuntimeError("Önce bash install.sh çalıştırın.") from error
    device = args.device
    if device == "auto":
        device = "cuda" if ctranslate2.get_cuda_device_count() else "cpu"
    compute = "int8_float16" if device == "cuda" else "int8"
    manifest.update({"method": "faster_whisper", "model": args.model, "language": args.language,
                     "device": device, "compute_type": compute, "source_sha256": sha256(audio),
                     "initial_prompt": TERMS, "vad_filter": not args.no_vad,
                     "condition_on_previous_text": False})
    dump(job / "manifest.json", manifest)
    print(f"Model: {args.model}; aygıt: {device}. İlk kullanımda model indirilebilir.", file=sys.stderr)
    model = WhisperModel(args.model, device=device, compute_type=compute, cpu_threads=8)
    stream, info = model.transcribe(str(audio), language=args.language, task="transcribe",
                                    beam_size=5, word_timestamps=True, initial_prompt=TERMS,
                                    condition_on_previous_text=False, vad_filter=not args.no_vad,
                                    vad_parameters={"min_silence_duration_ms": 500})
    manifest["audio_duration_seconds"] = info.duration
    manifest["duration_after_vad_seconds"] = info.duration_after_vad
    segments = []
    with (job / "segments.partial.jsonl").open("w", encoding="utf-8") as checkpoint:
        for segment in stream:
            item = {"start": segment.start, "end": segment.end, "text": segment.text.strip(),
                    "avg_logprob": segment.avg_logprob, "no_speech_prob": segment.no_speech_prob,
                    "compression_ratio": segment.compression_ratio,
                    "words": [{"start": w.start, "end": w.end, "word": w.word, "probability": w.probability}
                              for w in (segment.words or [])]}
            if not item["text"]:
                continue
            checkpoint.write(json.dumps(item, ensure_ascii=False, allow_nan=False) + "\n")
            checkpoint.flush()
            os.fsync(checkpoint.fileno())
            segments.append(item)
            print(f"\rÇözümlenen konum: {timestamp(item['end'])}", end="", file=sys.stderr, flush=True)
    print(file=sys.stderr)
    if not segments:
        raise ValueError("Konuşma bulunamadı. Ses içeriğini ve VAD ayarını kontrol edin.")
    return segments


def versions():
    result = {"agora_transcript": VERSION, "python": sys.version.split()[0]}
    for name in ("yt-dlp", "faster-whisper", "ctranslate2", "av", "onnxruntime"):
        try:
            result[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            result[name] = None
    return result


def doctor():
    status = {"versions": versions(), "executables": {n: shutil.which(n) for n in ("deno", "node", "ffmpeg", "nvidia-smi")}}
    try:
        import ctranslate2
        status["cuda_devices"] = ctranslate2.get_cuda_device_count()
        if status["cuda_devices"]:
            status["cuda_compute_types"] = sorted(ctranslate2.get_supported_compute_types("cuda"))
    except Exception as error:
        status["cuda_check_error"] = str(error)
    status["note"] = "Aygıt görünürlüğü tam ses çözümleme testi değildir. Node kullanılıyorsa 22+ gerekir."
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return 0 if status["versions"]["faster-whisper"] and status["versions"]["yt-dlp"] else 1


def runtime_check(args):
    """Exercise model loading and inference, not just GPU enumeration."""
    import tempfile
    import wave
    import ctranslate2
    from faster_whisper import WhisperModel
    device = args.device
    if device == "auto":
        device = "cuda" if ctranslate2.get_cuda_device_count() else "cpu"
    compute = "int8_float16" if device == "cuda" else "int8"
    print(f"Model yükleme/çözümleme testi: {args.model}, {device}. İlk indirme birkaç GB olabilir.", flush=True)
    model = WhisperModel(args.model, device=device, compute_type=compute, cpu_threads=8)
    with tempfile.TemporaryDirectory(prefix="agora-asr-check-") as temporary:
        sample = Path(temporary) / "silence.wav"
        with wave.open(str(sample), "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(16000)
            stream.writeframes(b"\x00\x00" * 16000)
        segments, _ = model.transcribe(str(sample), language="tr", beam_size=1, vad_filter=False)
        list(segments)
    print("Model çalıştırma testi geçti. Bu, Türkçe döküm doğruluğu testi değildir.")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Agora: YouTube veya yerel kayıttan zaman damgalı tam döküm.")
    parser.add_argument("input", nargs="?", help="YouTube video URL veya yerel ses/video yolu")
    parser.add_argument("--doctor", action="store_true")
    parser.add_argument("--runtime-check", action="store_true", help="Modeli indir/yükle ve kısa çözümleme testi yap")
    parser.add_argument("--output", default="transcripts", help="Her çalışmada yeni iş klasörü oluşturulur")
    parser.add_argument("--mode", choices=("auto", "captions", "audio"), default="auto")
    parser.add_argument("--language", default="tr")
    parser.add_argument("--model", default="large-v3")
    parser.add_argument("--device", choices=("auto", "cuda", "cpu"), default="auto")
    parser.add_argument("--no-vad", action="store_true", help="Sessiz bölüm filtresini kapat; süre/yanlış metin artabilir")
    parser.add_argument("--cookies", help="İsteğe bağlı, kullanıcının sağladığı Netscape cookies.txt yolu")
    args = parser.parse_args(argv)
    if args.doctor:
        return doctor()
    if args.runtime_check:
        try:
            return runtime_check(args)
        except Exception as error:
            print(f"Model testi başarısız: {error}", file=sys.stderr)
            return 1
    if not args.input:
        parser.error("Bir bağlantı veya kayıt dosyası verin.")
    if not re.fullmatch(r"[a-z]{2,3}", args.language):
        parser.error("Dil kodu tr veya en gibi iki/üç küçük harf olmalı.")
    if args.cookies and not Path(args.cookies).is_file():
        parser.error("Belirtilen çerez dosyası bulunamadı.")
    is_url = args.input.startswith(("http://", "https://"))
    try:
        source = youtube_url(args.input) if is_url else str(Path(args.input).expanduser().resolve(strict=True))
        if not is_url and not Path(source).is_file():
            raise ValueError("Yerel kaynak normal bir dosya olmalı.")
        if not is_url and args.mode == "captions":
            raise ValueError("Altyazı modu YouTube içindir; yerel kayıt için --mode audio kullanın.")
    except (ValueError, OSError) as error:
        parser.error(str(error))
    job = Path(args.output).expanduser().resolve() / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8])
    job.mkdir(parents=True, exist_ok=False)
    manifest = {"status": "processing", "source": source, "started_at": utcnow(),
                "human_verified": False, "versions": versions(),
                "note": "Otomatik döküm; tamamlanma durumunun anlamı işlem tamamlandı, tüm sözcükler doğrulandı değildir."}
    dump(job / "manifest.json", manifest)
    print(f"Çıktı klasörü: {job}", file=sys.stderr)
    try:
        segments, audio = obtain_youtube(args, job, manifest) if is_url else (None, Path(source))
        if audio:
            segments = transcribe_audio(args, audio, job, manifest)
        manifest.update({"status": "completed", "completed_at": utcnow(), "segment_count": len(segments)})
        export(job, segments, manifest)
        dump(job / "manifest.json", manifest)
        partial = job / "segments.partial.jsonl"
        if partial.exists():
            partial.rename(job / "segments.raw.jsonl")
        print(str(job / "transcript.txt"))
        return 0
    except (Exception, KeyboardInterrupt) as error:
        manifest.update({"status": "interrupted" if isinstance(error, KeyboardInterrupt) else "failed",
                         "finished_at": utcnow(), "error_type": type(error).__name__})
        dump(job / "manifest.json", manifest)
        print(f"Döküm tamamlanmadı: {error}\nHam/yarım sonuçlar: {job}", file=sys.stderr)
        return 130 if isinstance(error, KeyboardInterrupt) else 1


if __name__ == "__main__":
    raise SystemExit(main())
