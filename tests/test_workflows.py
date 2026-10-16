"""Every GitHub workflow must be valid YAML (GitHub rejects the whole file otherwise).

Needs PyYAML (pip install pyyaml); skipped if it is not installed.
"""
import unittest
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

WORKFLOWS = sorted((Path(__file__).resolve().parent.parent / ".github" / "workflows").glob("*.yml"))


@unittest.skipUnless(yaml, "PyYAML is not installed")
class WorkflowTests(unittest.TestCase):
    def test_workflows_exist(self):
        self.assertEqual({p.stem for p in WORKFLOWS}, {"market", "send", "sync"})

    def test_each_workflow_parses_and_has_jobs(self):
        for path in WORKFLOWS:
            with self.subTest(workflow=path.name):
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
                self.assertIn("jobs", data)
                for job in data["jobs"].values():
                    self.assertTrue(job["steps"])

    def test_commit_steps_keep_their_message(self):
        for path in WORKFLOWS:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            runs = [s["run"] for j in data["jobs"].values() for s in j["steps"] if "run" in s]
            pushes = [r for r in runs if "git_push.sh" in r]
            self.assertTrue(all('"data: ' in r for r in pushes), path.name)


if __name__ == "__main__":
    unittest.main()
