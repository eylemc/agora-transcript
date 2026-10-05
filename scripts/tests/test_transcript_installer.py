"""Offline integration tests: real local Git, no remote downloads or model calls."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/install-agora-transcript.sh"
URL = "git@github.com:eylemc/agora-transcript.git"
GIT = shutil.which("git")


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.seed = self.base / "seed"
        self.remote = self.base / "remote.git"
        self.target = self.base / "checkout with spaces"
        self.git("init", "--bare", str(self.remote))
        self.git("init", "-b", "main", str(self.seed))
        self.git("-C", str(self.seed), "remote", "add", "origin", str(self.remote))
        self.commit_seed("first")
        fake = self.base / "bin"
        fake.mkdir()
        wrapper = fake / "git"
        wrapper.write_text('''#!/usr/bin/env bash
set -euo pipefail
if [[ "$1" == clone ]]; then
  target="${@: -1}"
  "$TEST_REAL_GIT" clone --branch main --single-branch "$TEST_REMOTE" "$target"
  "$TEST_REAL_GIT" -C "$target" remote set-url origin 'git@github.com:eylemc/agora-transcript.git'
elif [[ "$1" == -C && "$3" == fetch ]]; then
  exec "$TEST_REAL_GIT" -C "$2" fetch "$TEST_REMOTE" main
else
  exec "$TEST_REAL_GIT" "$@"
fi
''')
        wrapper.chmod(0o755)
        self.env = dict(os.environ, PATH=str(fake) + os.pathsep + os.environ["PATH"],
                        TEST_REAL_GIT=GIT, TEST_REMOTE=str(self.remote))

    def git(self, *args):
        return subprocess.run([GIT, *args], text=True, capture_output=True, check=True).stdout.strip()

    def commit_seed(self, text):
        (self.seed / "tracked.txt").write_text(text)
        self.git("-C", str(self.seed), "add", ".")
        self.git("-C", str(self.seed), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                 "commit", "-m", text)
        self.git("-C", str(self.seed), "push", "origin", "main")

    def sync(self):
        return subprocess.run(["bash", "-c", 'source "$1"; sync_transcript_repo "$2" "$3"',
                               "test", str(SCRIPT), str(self.target), URL],
                              env=self.env, text=True, capture_output=True)

    def test_clone_repeat_and_fast_forward_update(self):
        self.assertEqual(self.sync().returncode, 0)
        self.assertEqual(self.sync().returncode, 0)
        self.commit_seed("second")
        result = self.sync()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.target/"tracked.txt").read_text(), "second")

    def test_dirty_checkout_is_preserved(self):
        self.assertEqual(self.sync().returncode, 0)
        (self.target/"tracked.txt").write_text("user edit")
        self.commit_seed("upstream")
        self.assertNotEqual(self.sync().returncode, 0)
        self.assertEqual((self.target/"tracked.txt").read_text(), "user edit")

    def test_wrong_repository_is_not_changed(self):
        self.assertEqual(self.sync().returncode, 0)
        self.git("-C", str(self.target), "remote", "set-url", "origin", "https://github.com/example/other.git")
        self.assertNotEqual(self.sync().returncode, 0)
        self.assertEqual((self.target/"tracked.txt").read_text(), "first")

    def test_diverged_history_is_not_reset(self):
        self.assertEqual(self.sync().returncode, 0)
        (self.target/"local.txt").write_text("local work")
        self.git("-C", str(self.target), "add", ".")
        self.git("-C", str(self.target), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                 "commit", "-m", "local")
        before = self.git("-C", str(self.target), "rev-parse", "HEAD")
        self.commit_seed("remote work")
        self.assertNotEqual(self.sync().returncode, 0)
        self.assertEqual(self.git("-C", str(self.target), "rev-parse", "HEAD"), before)
        self.assertEqual((self.target/"local.txt").read_text(), "local work")

    def test_install_reuses_existing_venv(self):
        app = self.base / "app"
        app.mkdir()
        for name in ("install.sh", "requirements.txt"):
            shutil.copy(ROOT / "src/agora-transcript" / name, app / name)
        tools = app / ".tools/uv"
        tools.mkdir(parents=True)
        fake = tools / "uv"
        fake.write_text('''#!/usr/bin/env bash
set -euo pipefail
if [[ "$1" == venv ]]; then
  echo created >> creations.txt
  mkdir -p .venv/bin
  ln -s "$TEST_PYTHON" .venv/bin/python
elif [[ "$1" == pip && "$2" == freeze ]]; then
  echo 'fixture==1.0'
fi
''')
        fake.chmod(0o755)
        env = dict(os.environ, TEST_PYTHON=sys.executable)
        for _ in range(2):
            result = subprocess.run(["bash", str(app/"install.sh"), "--cpu"], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((app/"creations.txt").read_text().splitlines(), ["created"])
        self.assertEqual((app/"installed-versions.txt").read_text().strip(), "fixture==1.0")


if __name__ == "__main__":
    unittest.main()
