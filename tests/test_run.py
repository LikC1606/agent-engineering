import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest


TOOL = Path(__file__).resolve().parents[1] / "tools" / "run.py"
spec = importlib.util.spec_from_file_location("research_run_tool", TOOL)
run_tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run_tool)


@unittest.skipIf(run_tool.fcntl is None, "Process locks require Linux, macOS, or WSL")
class RunRecordsTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.project = Path(self.temporary.name) / "project"
        self.project.mkdir()
        (self.project / "requirements.md").write_text("Goal: check the two input cases.\n", encoding="utf-8")
        (self.project / "config.json").write_text('{"seed": 7}\n', encoding="utf-8")
        (self.project / "input.txt").write_text("case one\n", encoding="utf-8")

    def invoke(self, *arguments, expected=0, env=None):
        result = subprocess.run([sys.executable, str(TOOL), *map(str, arguments)],
                                capture_output=True, text=True, env=env)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout if expected == 0 or result.stdout else result.stderr)

    def initialize(self, tasks=("a", "b"), **kwargs):
        arguments = ["init", "--project", self.project, "--name", "pilot",
                     "--requirements", "requirements.md", "--config", "config.json", "--input", "input.txt"]
        for task in tasks:
            arguments.extend(["--task", task])
        for key, value in kwargs.items():
            arguments.extend(["--" + key.replace("_", "-"), value])
        return Path(self.invoke(*arguments)["run"])

    def execute(self, run, task="a", code="print('ok')", expected=0, options=()):
        return self.invoke("exec", "--run", run, "--task", task, *options,
                           "--", sys.executable, "-c", code, expected=expected)

    def status(self, run):
        return self.invoke("status", "--run", run)

    def test_independent_runs_keep_snapshots_and_parent(self):
        first = self.initialize()
        second = self.initialize(parent=first, goal="Compare two cases with fixed seed")
        self.assertNotEqual(first, second)
        first_data = json.loads((first / "run.json").read_text())
        second_data = json.loads((second / "run.json").read_text())
        self.assertEqual(second_data["parent"]["run_id"], first.name)
        self.assertEqual(second_data["goal"], "Compare two cases with fixed seed")
        for item in first_data["snapshots"]:
            self.assertEqual(run_tool.digest(first / item["snapshot"]), item["sha256"])
            self.assertIsNotNone(item["project_relative"])
        self.assertEqual(self.status(first)["counts"],
                         {"completed": 0, "running": 0, "error": 0, "pending": 2, "total": 2})

    def test_failed_attempt_is_retained_after_explicit_retry(self):
        run = self.initialize()
        failed = self.execute(run, code="import sys; print('first'); print('problem', file=sys.stderr); sys.exit(7)", expected=7)
        before = self.status(run)
        self.assertEqual(before["counts"]["error"], 1)
        self.assertEqual(before["historical_failed_attempts"], 1)
        self.assertIsNone(before["eta_seconds"])
        old_stdout = (run / failed["logs"]["stdout"]["path"]).read_bytes()
        succeeded = self.execute(run, code="print('repaired')", options=("--note", "Fixed the observed fixture input"))
        self.assertNotEqual(failed["attempt"], succeeded["attempt"])
        self.assertEqual((run / failed["logs"]["stdout"]["path"]).read_bytes(), old_stdout)
        status = self.status(run)
        self.assertEqual(status["counts"]["completed"], 1)
        self.assertEqual(status["counts"]["error"], 0)
        self.assertEqual(status["historical_failed_attempts"], 1)
        self.assertGreater(status["throughput_tasks_per_second"], 0)
        self.assertIsNone(status["eta_seconds"])
        self.execute(run, expected=2)

    def test_changed_or_corrupt_snapshots_do_not_execute(self):
        for filename in ("requirements.md", "config.json", "input.txt"):
            with self.subTest(filename=filename):
                run = self.initialize()
                source = self.project / filename
                original = source.read_bytes()
                source.write_bytes(original + b"changed\n")
                response = self.execute(run, code="from pathlib import Path; Path('should-not-exist').touch()", expected=2)
                self.assertIn("new run", response["error"])
                self.assertFalse((self.project / "should-not-exist").exists())
                source.write_bytes(original)
        run = self.initialize()
        data = json.loads((run / "run.json").read_text())
        (run / data["snapshots"][0]["snapshot"]).write_text("tampered")
        self.execute(run, expected=2)

    def test_concurrent_tasks_keep_valid_events_and_reject_duplicate(self):
        run = self.initialize()
        processes = []
        for task in ("a", "b"):
            processes.append(subprocess.Popen(
                [sys.executable, str(TOOL), "exec", "--run", str(run), "--task", task,
                 "--", sys.executable, "-c", "import time; time.sleep(0.8); print('done')"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
        try:
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                status = self.status(run)
                if status["counts"]["running"] == 2:
                    break
                time.sleep(0.02)
            self.assertEqual(status["counts"]["running"], 2)
            duplicate = self.execute(run, expected=2)
            self.assertIn("already running", duplicate["error"])
            for process in processes:
                out, err = process.communicate(timeout=5)
                self.assertEqual(process.returncode, 0, out + err)
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                    process.wait()
        status = self.status(run)
        self.assertEqual(status["counts"]["completed"], 2)
        self.assertEqual(status["eta_seconds"], 0)
        items = run_tool.records(run)
        self.assertEqual(sum(item["event"] == "started" for item in items), 2)
        self.assertEqual(sum(item["event"] == "finished" for item in items), 2)

    def test_unknown_outcome_requires_inspection_note(self):
        run = self.initialize(tasks=("a",))
        run_tool.event(run, "started", task="a", attempt="attempts/a/interrupted")
        status = self.status(run)
        self.assertEqual(status["counts"]["error"], 1)
        self.assertEqual(status["unknown_tasks"], 1)
        self.execute(run, expected=2)
        self.execute(run, expected=2, options=("--retry-uncertain",))
        self.execute(run, options=("--retry-uncertain", "--note", "Inspected the empty fixture directory; no effects occurred"))
        self.assertEqual(self.status(run)["counts"]["completed"], 1)

    def test_result_copies_and_lessons_survive_new_runs(self):
        run = self.initialize()
        result_file = self.project / "result.csv"
        result_file.write_text("value\n1\n", encoding="utf-8")
        artifact = self.invoke("attach", "--run", run, "--task", "a", "--kind", "result", "--file", "result.csv")
        result_file.write_text("value\n2\n", encoding="utf-8")
        self.assertEqual((run / artifact["path"]).read_text(), "value\n1\n")
        self.assertEqual(run_tool.digest(run / artifact["path"]), artifact["sha256"])
        first = self.invoke("lesson", "--run", run, "--task", "a", "--condition", "Fixture label absent",
                            "--cause", "Input omitted the header", "--fix", "Added the required header",
                            "--prevent", "Check the two-case pilot", "--evidence", artifact["path"])
        second_run = self.initialize(parent=run)
        self.invoke("lesson", "--run", second_run, "--condition", "Second fixture variant",
                    "--cause", "Different delimiter", "--fix", "Read the declared delimiter",
                    "--prevent", "Compare raw rows in the pilot")
        entries = [json.loads(line) for line in Path(first["path"]).read_text().splitlines()]
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["run_id"], run.name)
        self.assertEqual(len(self.status(run)["artifacts"]), 1)

    def test_whole_project_can_move_without_losing_relative_sources(self):
        run = self.initialize(tasks=("a",))
        moved = self.project.with_name("moved-project")
        shutil.move(str(self.project), moved)
        self.project = moved
        run = moved / "runs" / run.name
        result = self.execute(run, code="from pathlib import Path; Path('executed-here').write_text('yes')")
        self.assertEqual(result["exit_code"], 0)
        self.assertTrue((moved / "executed-here").exists())

    def test_timeout_and_missing_executable_leave_terminal_evidence(self):
        run = self.initialize()
        timed_out = self.execute(run, code="import time; time.sleep(5)", expected=124, options=("--timeout", "0.1"))
        self.assertIn("timeout", timed_out["failure"])
        missing = self.invoke("exec", "--run", run, "--task", "b", "--", "does-not-exist-research-run-fixture", expected=127)
        self.assertEqual(missing["state"], "error")
        self.assertEqual(self.status(run)["historical_failed_attempts"], 2)

    def test_invalid_initialization_and_credential_names(self):
        self.invoke("init", "--project", self.project, "--name", "pilot", "--requirements", "requirements.md",
                    "--config", "config.json", "--task", "same", "--task", "same", expected=2)
        self.assertFalse((self.project / "runs").exists())
        env = os.environ.copy()
        env["RESEARCH_FIXTURE_TOKEN"] = "a-secret-value-never-serialized"
        arguments = ["init", "--project", self.project, "--name", "pilot", "--requirements", "requirements.md",
                     "--config", "config.json", "--task", "a", "--env-name", "RESEARCH_FIXTURE_TOKEN"]
        run = Path(self.invoke(*arguments, env=env)["run"])
        self.execute(run)
        text_files = [p for p in run.rglob("*") if p.is_file() and p.suffix in {".json", ".jsonl"}]
        self.assertTrue(all(env["RESEARCH_FIXTURE_TOKEN"] not in p.read_text() for p in text_files))
        self.assertEqual(json.loads((run / "run.json").read_text())["credential_environment_names"], ["RESEARCH_FIXTURE_TOKEN"])

    @unittest.skipUnless(shutil.which("git"), "Git unavailable")
    def test_git_state_records_patch_without_recursively_listing_runs(self):
        def git(*args):
            subprocess.run(["git", "-C", str(self.project), *args], check=True, capture_output=True)
        git("init")
        source = self.project / "experiment.py"
        source.write_text("seed = 1\n")
        git("add", ".")
        git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-m", "fixture")
        source.write_text("seed = 2\n")
        run = self.initialize(tasks=("a",))
        self.assertIn("+seed = 2", (run / "source" / "worktree.patch").read_text())
        self.assertNotIn("runs/", (run / "source" / "status").read_text())
        self.assertTrue((run / "source" / "head").read_text().strip())


if __name__ == "__main__":
    unittest.main()
