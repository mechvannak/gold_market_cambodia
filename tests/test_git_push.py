"""scripts/git_push.sh against a throw-away local remote.

The first hourly sync runs before the owner has sent /start, so data/private.enc does not exist yet.
That must not fail the workflow.
"""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "git_push.sh"


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


@unittest.skipUnless(shutil.which("git") and shutil.which("bash"), "git/bash not available")
class GitPushTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.remote = self.tmp / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.remote)], check=True)
        self.work = self.tmp / "work"
        subprocess.run(["git", "clone", "-q", str(self.remote), str(self.work)], check=True, capture_output=True)
        git(self.work, "checkout", "-q", "-B", "main")
        git(self.work, "config", "user.email", "t@example.com")
        git(self.work, "config", "user.name", "t")
        (self.work / "README.md").write_text("x\n")
        git(self.work, "add", "-A")
        git(self.work, "commit", "-q", "-m", "init")
        git(self.work, "push", "-q", "-u", "origin", "main")
        (self.work / "scripts").mkdir()
        shutil.copy(SCRIPT, self.work / "scripts" / "git_push.sh")

    def run_push(self, msg, *paths):
        return subprocess.run(["bash", "scripts/git_push.sh", msg, *paths], cwd=self.work, capture_output=True, text=True, timeout=60)

    def test_missing_vault_is_skipped_not_an_error(self):
        p = self.run_push("vault", "data/private.enc")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("nothing to commit", p.stdout)

    def test_new_file_is_committed_and_pushed(self):
        (self.work / "data").mkdir()
        (self.work / "data" / "private.enc").write_text("{}")
        p = self.run_push("data: vault update", "data/private.enc")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(git(self.remote, "log", "-1", "--format=%s", "main"), "data: vault update")

    def test_only_listed_paths_are_committed(self):
        (self.work / "data").mkdir()
        (self.work / "data" / "market.json").write_text("{}")
        (self.work / "notes.txt").write_text("not for the commit")
        self.assertEqual(self.run_push("data: market update", "data/market.json", "data/history.csv").returncode, 0)
        files = git(self.remote, "ls-tree", "-r", "--name-only", "main").splitlines()
        self.assertIn("data/market.json", files)
        self.assertNotIn("notes.txt", files)

    def test_unchanged_file_makes_no_commit(self):
        (self.work / "data").mkdir()
        (self.work / "data" / "market.json").write_text("{}")
        self.run_push("first", "data/market.json")
        p = self.run_push("second", "data/market.json")
        self.assertEqual(p.returncode, 0)
        self.assertIn("nothing to commit", p.stdout)
        self.assertEqual(git(self.remote, "log", "-1", "--format=%s", "main"), "first")

    def test_rebases_over_a_commit_pushed_by_someone_else(self):
        other = self.tmp / "other"
        subprocess.run(["git", "clone", "-q", str(self.remote), str(other)], check=True, capture_output=True)
        git(other, "config", "user.email", "o@example.com")
        git(other, "config", "user.name", "o")
        (other / "analysis.json").write_text("{}")
        git(other, "add", "-A")
        git(other, "commit", "-q", "-m", "analysis")
        git(other, "push", "-q", "origin", "HEAD:main")
        (self.work / "data").mkdir()
        (self.work / "data" / "market.json").write_text("{}")
        self.assertEqual(self.run_push("data: market update", "data/market.json").returncode, 0)
        files = git(self.remote, "ls-tree", "-r", "--name-only", "main").splitlines()
        self.assertIn("analysis.json", files)
        self.assertIn("data/market.json", files)


if __name__ == "__main__":
    unittest.main()
