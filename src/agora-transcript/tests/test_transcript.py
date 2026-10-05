import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import agora_transcript as app


class TranscriptTests(unittest.TestCase):
    def test_timestamp_carry_and_multihour(self):
        self.assertEqual(app.timestamp(59.9996, True), "00:01:00,000")
        self.assertEqual(app.timestamp(3600.001, True), "01:00:00,001")
        self.assertEqual(app.timestamp(86400), "24:00:00.000")
        for value in (-1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                app.timestamp(value)

    def test_url_scope_and_canonicalization(self):
        expected = "https://www.youtube.com/watch?v=cgBmqZE8XCg"
        for url in ("https://youtu.be/cgBmqZE8XCg?t=12", expected + "&list=abcdef",
                    "https://www.youtube.com/live/cgBmqZE8XCg"):
            self.assertEqual(app.youtube_url(url), expected)
        for url in ("https://youtube.com.attacker.example/watch?v=cgBmqZE8XCg",
                    "https://user:pass@youtube.com/watch?v=cgBmqZE8XCg",
                    "https://youtube.com/playlist?list=abcdef"):
            with self.assertRaises(ValueError):
                app.youtube_url(url)

    def test_caption_text_and_overlapping_repetitions_are_preserved(self):
        raw = {"events": [
            {"tStartMs": 1000, "dDurationMs": 3000, "segs": [{"utf8": "86.628 olabilir."}]},
            {"tStartMs": 2000, "dDurationMs": 3000, "segs": [{"utf8": "86.628 olabilir."}]},
            {"tStartMs": 8000, "dDurationMs": 2000, "segs": [{"utf8": "Kesin değil &amp; koşullu."}]},
        ]}
        segments = app.caption_segments(raw)
        self.assertEqual(len(segments), 3)
        self.assertEqual(segments[0]["text"], "86.628 olabilir.")
        with tempfile.TemporaryDirectory() as temp:
            app.export(Path(temp), segments, {"caption_kind": "automatic"})
            text = (Path(temp)/"transcript.txt").read_text()
            self.assertEqual(text.count("86.628 olabilir."), 2)
            self.assertIn("Kesin değil & koşullu.", text)
            self.assertIn("00:00:08,000 --> 00:00:10,000", (Path(temp)/"transcript.srt").read_text())
            flags = json.loads((Path(temp)/"review.json").read_text())["segments"]
            self.assertIn("overlapping_segment_check", flags[1]["flags"])

    def test_missing_and_invalid_caption_times_fail(self):
        for event in ({"segs": [{"utf8": "metin"}]},
                      {"tStartMs": 0, "dDurationMs": 0, "segs": [{"utf8": "metin"}]}):
            with self.assertRaises(ValueError):
                app.caption_segments({"events": [event]})

    def test_original_manual_caption_preferred_and_translation_rejected(self):
        original = [{"ext": "json3", "url": "https://example.com/?lang=tr"}]
        translated = [{"ext": "json3", "url": "https://example.com/?lang=en&tlang=tr"}]
        self.assertEqual(app.choose_caption({"subtitles": {"tr": original},
                                             "automatic_captions": {"tr-orig": original}}, "tr"), ("manual", "tr"))
        self.assertEqual(app.choose_caption({"automatic_captions": {"tr": translated, "tr-orig": original}}, "tr"), ("automatic", "tr-orig"))
        self.assertIsNone(app.choose_caption({"automatic_captions": {"tr": translated}}, "tr"))

    def test_error_never_reported_as_completed(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(app, "obtain_youtube", side_effect=RuntimeError("network failed")):
                with contextlib.redirect_stderr(io.StringIO()):
                    code = app.main(["https://youtu.be/cgBmqZE8XCg", "--output", temp])
            self.assertEqual(code, 1)
            manifest = json.loads(next(Path(temp).glob("*/manifest.json")).read_text())
            self.assertEqual(manifest["status"], "failed")
            self.assertFalse(list(Path(temp).glob("*/transcript.txt")))

    def test_completed_job_formats_agree_and_new_runs_do_not_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            segments = [{"start": 10, "end": 13, "text": "Yüz bin olabilir; kesin değil.", "words": []}]
            with patch.object(app, "obtain_youtube", return_value=(segments, None)):
                with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
                    for _ in range(2):
                        self.assertEqual(app.main(["https://youtu.be/cgBmqZE8XCg", "--output", temp]), 0)
            jobs = list(Path(temp).iterdir())
            self.assertEqual(len(jobs), 2)
            for job in jobs:
                self.assertEqual(json.loads((job/"manifest.json").read_text())["status"], "completed")
                structured = json.loads((job/"transcript.json").read_text())
                self.assertFalse(structured["metadata"]["human_verified"])
                self.assertEqual(structured["segments"][0]["text"], segments[0]["text"])
                self.assertIn(segments[0]["text"], (job/"transcript.srt").read_text())

    def test_local_audio_flow_uses_original_path_and_preserves_source(self):
        with tempfile.TemporaryDirectory() as temp:
            media = Path(temp)/"original audio.wav"
            media.write_bytes(b"fixture")
            output = Path(temp)/"jobs"
            segments = [{"start": 0, "end": 2, "text": "KoinVizyon", "words": []}]
            with patch.object(app, "transcribe_audio", return_value=segments) as transcribe:
                with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(app.main([str(media), "--mode", "audio", "--output", str(output)]), 0)
            self.assertEqual(transcribe.call_args.args[1], media)
            self.assertEqual(media.read_bytes(), b"fixture")


if __name__ == "__main__":
    unittest.main()
