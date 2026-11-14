import importlib.util
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import socket
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
        artifacts = os.environ.get("RUN_TEST_ARTIFACT_DIR")
        if artifacts:
            output = Path(artifacts)
            output.mkdir(parents=True, exist_ok=True)
            self.root = Path(tempfile.mkdtemp(prefix=self._testMethodName + "-", dir=output))
        else:
            self.temporary = tempfile.TemporaryDirectory()
            self.addCleanup(self.temporary.cleanup)
            self.root = Path(self.temporary.name)
        self.project = self.root / "project"
        self.project.mkdir()
        (self.project / "requirements.md").write_text("Goal: check the two input cases.\n", encoding="utf-8")
        (self.project / "config.json").write_text('{"seed": 7}\n', encoding="utf-8")
        (self.project / "input.txt").write_text("case one\n", encoding="utf-8")

    def invoke(self, *arguments, expected=0, env=None):
        command = [sys.executable, str(TOOL), *map(str, arguments)]
        result = subprocess.run(command,
                                capture_output=True, text=True, env=env)
        with (self.root / "cli-calls.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"argv": command, "returncode": result.returncode,
                                     "stdout": result.stdout, "stderr": result.stderr}) + "\n")
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

    def test_command_record_preserves_exact_argv_and_log_hashes(self):
        """C05, C14: saved commands and binary logs reproduce the actual invocation."""
        run = self.initialize(tasks=("a",))
        code = ("import json, sys; "
                "sys.stdout.buffer.write((json.dumps(sys.argv[1:], ensure_ascii=False) + '\\n').encode()); "
                "sys.stderr.buffer.write(b'warning\\x00\\xff\\n')")
        values = ["", "value with spaces", "双引号\"与单引号'", "line one\nline two",
                  "$(touch must-not-run)", "`touch must-not-run`", "; touch must-not-run", "--flag=value"]
        argv = [sys.executable, "-c", code, *values]
        result = self.invoke("exec", "--run", run, "--task", "a", "--", *argv)
        attempt = run / result["attempt"]
        command = json.loads((attempt / "command.json").read_text())
        self.assertEqual(command["argv"], argv)
        self.assertEqual(shlex.split(command["display_command"]), argv)
        commands = [json.loads(line) for line in (run / "commands.jsonl").read_text().splitlines()]
        self.assertEqual(commands, [command])
        expected = {"stdout": (json.dumps(values, ensure_ascii=False) + "\n").encode(),
                    "stderr": b"warning\x00\xff\n"}
        for name, content in expected.items():
            log = result["logs"][name]
            self.assertEqual((run / log["path"]).read_bytes(), content)
            self.assertEqual(log["sha256"], hashlib.sha256(content).hexdigest())
        self.assertEqual(json.loads((attempt / "result.json").read_text()), result)
        self.assertFalse((self.project / "must-not-run").exists())

    def test_explicit_cwd_and_output_environment_match_saved_paths(self):
        """C07, C14: the child observes the recorded directory and output locations."""
        run = self.initialize(tasks=("a",))
        cwd = self.project / "working directory"
        cwd.mkdir()
        code = (
            "import json, os; from pathlib import Path; "
            "context = {'cwd': str(Path.cwd()), 'run': os.environ['AGENT_RUN_DIR'], "
            "'attempt': os.environ['AGENT_ATTEMPT_DIR']}; "
            "Path(context['attempt'], 'child-context.json').write_text(json.dumps(context)); "
            "Path(context['run'], 'declared-output.txt').write_text('saved at the declared output')"
        )
        result = self.execute(run, code=code, options=("--cwd", "working directory"))
        attempt = run / result["attempt"]
        context = json.loads((attempt / "child-context.json").read_text())
        self.assertEqual(context, {"cwd": str(cwd), "run": str(run), "attempt": str(attempt)})
        command = json.loads((attempt / "command.json").read_text())
        self.assertEqual(command["cwd"], str(cwd))
        self.assertEqual(command["resolved_executable"], str(Path(sys.executable).resolve()))
        self.assertEqual(command["injected_environment"],
                         {"AGENT_RUN_DIR": str(run), "AGENT_ATTEMPT_DIR": str(attempt)})
        for location in (run, attempt):
            environment = json.loads((location / "environment.json").read_text())
            self.assertEqual(environment["project"], str(self.project))
            self.assertEqual(environment["python"], sys.executable)
            self.assertEqual(environment["hostname"], socket.gethostname())
            self.assertEqual(environment["tool_cwd"], str(Path.cwd().resolve()))
        self.assertEqual((run / "declared-output.txt").read_text(), "saved at the declared output")
        self.assertFalse((cwd / "child-context.json").exists())
        self.assertFalse((self.project / "declared-output.txt").exists())

    def test_requirement_change_after_first_task_requires_linked_new_run(self):
        """C03, C06, C14: recheck requirements before each task and preserve the old run."""
        first = self.initialize()
        self.execute(first)
        first_data_bytes = (first / "run.json").read_bytes()
        first_data = json.loads(first_data_bytes)
        frozen = next(item for item in first_data["snapshots"] if item["kind"] == "requirements")
        frozen_bytes = (first / frozen["snapshot"]).read_bytes()
        events_before = (first / "events.jsonl").read_bytes()
        commands_before = (first / "commands.jsonl").read_bytes()
        new_requirements = "Goal: verify the revised cases and retain the earlier evidence.\n"
        (self.project / "requirements.md").write_text(new_requirements)
        rejected = self.execute(first, task="b", code="from pathlib import Path; Path('rejected-output').touch()", expected=2)
        self.assertIn("new run", rejected["error"])
        self.assertFalse((self.project / "rejected-output").exists())
        self.assertFalse((first / "attempts/b").exists())
        self.assertEqual((first / "events.jsonl").read_bytes(), events_before)
        self.assertEqual((first / "commands.jsonl").read_bytes(), commands_before)
        second = self.initialize(parent=first)
        self.execute(second, task="a")
        self.execute(second, task="b")
        second_data = json.loads((second / "run.json").read_text())
        second_frozen = next(item for item in second_data["snapshots"] if item["kind"] == "requirements")
        self.assertEqual((second / second_frozen["snapshot"]).read_text(), new_requirements)
        self.assertNotEqual(second_frozen["sha256"], frozen["sha256"])
        self.assertEqual(second_data["parent"]["run_id"], first.name)
        self.assertEqual((first / "run.json").read_bytes(), first_data_bytes)
        self.assertEqual((first / frozen["snapshot"]).read_bytes(), frozen_bytes)
        self.assertEqual(self.status(first)["counts"],
                         {"completed": 1, "running": 0, "error": 0, "pending": 1, "total": 2})
        self.assertEqual(self.status(second)["counts"]["completed"], 2)

    def test_progress_reports_every_state_and_eta_after_failure_repair(self):
        """C08, C10: count all task states and estimate remaining work after repair."""
        run = self.initialize(tasks=("a", "b", "c", "d", "e"))
        self.execute(run, task="a")
        self.execute(run, task="b")
        self.execute(run, task="c", code="raise SystemExit(9)", expected=9)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            listener.settimeout(10)
            port = listener.getsockname()[1]
            code = (f"import socket; gate = socket.create_connection(('127.0.0.1', {port})); "
                    "gate.sendall(b'r'); gate.recv(1); gate.close(); print('released')")
            process = subprocess.Popen([sys.executable, str(TOOL), "exec", "--run", str(run), "--task", "d",
                                        "--", sys.executable, "-c", code],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            connection = None
            try:
                connection, _ = listener.accept()
                connection.settimeout(10)
                self.assertEqual(connection.recv(1), b"r")
                mixed = self.status(run)
                self.assertEqual(mixed["counts"],
                                 {"completed": 2, "running": 1, "error": 1, "pending": 1, "total": 5})
                self.assertEqual({task: details["state"] for task, details in mixed["tasks"].items()},
                                 {"a": "completed", "b": "completed", "c": "error", "d": "running", "e": "pending"})
                self.assertEqual(mixed["historical_failed_attempts"], 1)
                self.assertEqual(mixed["unknown_tasks"], 0)
                self.assertAlmostEqual(mixed["throughput_tasks_per_second"], 2 / mixed["elapsed_seconds"])
                self.assertIsNone(mixed["eta_seconds"])
                self.execute(run, task="c", options=("--note", "Corrected the disposable failing fixture"))
                repaired = self.status(run)
                self.assertEqual(repaired["counts"],
                                 {"completed": 3, "running": 1, "error": 0, "pending": 1, "total": 5})
                self.assertEqual(repaired["historical_failed_attempts"], 1)
                self.assertGreater(repaired["eta_seconds"], 0)
                self.assertAlmostEqual(repaired["eta_seconds"], 2 / repaired["throughput_tasks_per_second"])
                connection.sendall(b"x")
                stdout, stderr = process.communicate(timeout=10)
                self.assertEqual(process.returncode, 0, stdout + stderr)
            finally:
                if connection is not None:
                    connection.close()
                if process.poll() is None:
                    try:
                        process.communicate(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.communicate()
        self.execute(run, task="e")
        finished = self.status(run)
        self.assertEqual(finished["counts"],
                         {"completed": 5, "running": 0, "error": 0, "pending": 0, "total": 5})
        self.assertEqual(finished["eta_seconds"], 0)
        self.assertEqual(finished["historical_failed_attempts"], 1)

    def test_repeated_intermediate_and_result_attachments_keep_prior_bytes(self):
        """C05, C06: repeated names retain distinct intermediate and result snapshots."""
        run = self.initialize(tasks=("a",))
        source = self.project / "measurements.bin"
        artifacts = []
        for index, kind in enumerate(("intermediate", "intermediate", "result", "result")):
            content = f"variant {index}\n".encode() + b"\x00\xff"
            source.write_bytes(content)
            artifact = self.invoke("attach", "--run", run, "--task", "a", "--kind", kind,
                                   "--file", source.name, "--note", f"measurement {index}")
            self.assertEqual(Path(artifact["path"]).parts[0], "intermediate" if kind == "intermediate" else "results")
            self.assertEqual(artifact["original_path"], str(source))
            self.assertEqual(artifact["sha256"], hashlib.sha256(content).hexdigest())
            artifacts.append((artifact, content))
        source.unlink()
        self.assertEqual(len({artifact["path"] for artifact, _ in artifacts}), 4)
        for artifact, content in artifacts:
            self.assertEqual((run / artifact["path"]).read_bytes(), content)
        self.assertEqual(self.status(run)["artifacts"], [artifact for artifact, _ in artifacts])

    def test_missing_declared_input_prevents_partial_initialization(self):
        """C03, C05: missing declared files are rejected before a run is created."""
        for filename in ("requirements.md", "config.json", "input.txt"):
            with self.subTest(filename=filename):
                source = self.project / filename
                original = source.read_bytes()
                source.unlink()
                try:
                    rejected = self.invoke("init", "--project", self.project, "--name", "missing-input",
                                           "--requirements", "requirements.md", "--config", "config.json",
                                           "--input", "input.txt", "--task", "a", expected=2)
                    self.assertIn(filename, rejected["error"])
                    self.assertFalse((self.project / "runs").exists())
                finally:
                    source.write_bytes(original)

    def test_missing_saved_snapshot_prevents_command_evidence_and_effects(self):
        """C03, C05, C14: lost frozen evidence prevents a command from starting."""
        for kind in ("requirements", "config", "input"):
            with self.subTest(kind=kind):
                run = self.initialize(tasks=("a",))
                data = json.loads((run / "run.json").read_text())
                frozen = next(item for item in data["snapshots"] if item["kind"] == kind)
                (run / frozen["snapshot"]).unlink()
                events_before = (run / "events.jsonl").read_bytes()
                rejected = self.execute(run, code="from pathlib import Path; Path('must-not-execute').touch()", expected=2)
                self.assertIn("snapshot", rejected["error"].lower())
                self.assertFalse((self.project / "must-not-execute").exists())
                self.assertFalse((run / "attempts").exists())
                self.assertFalse((run / "commands.jsonl").exists())
                self.assertEqual((run / "events.jsonl").read_bytes(), events_before)

    def test_incomplete_lesson_never_appends_a_partial_record(self):
        """C13: all four lesson fields are validated before persistent append."""
        run = self.initialize(tasks=("a",))
        fields = {"condition": "Malformed pilot input", "cause": "The delimiter was wrong",
                  "fix": "Used the declared delimiter", "prevent": "Inspect raw pilot rows"}
        path = self.project / ".agent-experience/lessons.jsonl"
        for invalid in fields:
            with self.subTest(field=invalid, existing=False):
                arguments = [argument for name, content in fields.items()
                             for argument in ("--" + name, " \t\n" if name == invalid else content)]
                self.invoke("lesson", "--run", run, "--task", "a", *arguments, expected=2)
                self.assertFalse(path.exists())
        valid_arguments = [argument for name, content in fields.items() for argument in ("--" + name, content)]
        created = self.invoke("lesson", "--run", run, "--task", "a", *valid_arguments)
        before = path.read_bytes()
        for invalid in fields:
            with self.subTest(field=invalid, existing=True):
                arguments = [argument for name, content in fields.items()
                             for argument in ("--" + name, "" if name == invalid else content)]
                self.invoke("lesson", "--run", run, "--task", "a", *arguments, expected=2)
                self.assertEqual(path.read_bytes(), before)
        self.assertEqual([json.loads(line) for line in path.read_text().splitlines()], [created["lesson"]])

    @unittest.skipUnless(shutil.which("git"), "Git unavailable")
    def test_attempt_source_patches_distinguish_failure_and_repair(self):
        """C06, C08, C14: each retry keeps the source state that produced its result."""
        def git(*arguments):
            subprocess.run(["git", "-C", str(self.project), *arguments], check=True, capture_output=True)
        git("init")
        source = self.project / "experiment.py"
        source.write_text("print('original')\n")
        git("add", ".")
        git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-m", "fixture")
        run = self.initialize(tasks=("a",))
        source.write_text("print('observed failure')\nraise SystemExit(6)\n")
        failed = self.invoke("exec", "--run", run, "--task", "a", "--", sys.executable, source, expected=6)
        failed_patch = run / failed["attempt"] / "source/worktree.patch"
        failed_patch_bytes = failed_patch.read_bytes()
        self.assertIn(b"+raise SystemExit(6)", failed_patch_bytes)
        source.write_text("print('repaired')\n")
        git("add", "experiment.py")
        repaired = self.invoke("exec", "--run", run, "--task", "a", "--note", "Fixed the observed fixture failure",
                               "--", sys.executable, source)
        repaired_source = run / repaired["attempt"] / "source"
        self.assertEqual((repaired_source / "worktree.patch").read_bytes(), b"")
        self.assertIn("+print('repaired')", (repaired_source / "staged.patch").read_text())
        self.assertEqual(failed_patch.read_bytes(), failed_patch_bytes)
        self.assertEqual((run / "source/worktree.patch").read_bytes(), b"")
        self.assertEqual(self.status(run)["historical_failed_attempts"], 1)
        self.assertEqual(self.status(run)["counts"]["completed"], 1)

    def test_recorded_command_can_reproduce_result_from_saved_input(self):
        """C05, C14: replay saved argv against frozen inputs after the originals change."""
        run = self.initialize(tasks=("a",))
        data = json.loads((run / "run.json").read_text())
        input_snapshot = next(item for item in data["snapshots"] if item["kind"] == "input")
        config_snapshot = next(item for item in data["snapshots"] if item["kind"] == "config")
        code = ("import json, sys; from pathlib import Path; "
                "source = Path(sys.argv[1]).read_bytes(); config = json.loads(Path(sys.argv[2]).read_text()); "
                "Path('reproduced.bin').write_bytes(source + str(config['seed']).encode())")
        result = self.invoke("exec", "--run", run, "--task", "a", "--", sys.executable, "-c", code,
                             run / input_snapshot["snapshot"], run / config_snapshot["snapshot"])
        original_result = (self.project / "reproduced.bin").read_bytes()
        self.assertEqual(original_result, b"case one\n7")
        (self.project / "input.txt").write_text("later input\n")
        (self.project / "config.json").write_text('{"seed": 999}\n')
        command = json.loads((run / result["attempt"] / "command.json").read_text())
        replay = self.root / "replay"
        replay.mkdir()
        completed = subprocess.run(command["argv"], cwd=replay, capture_output=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual((replay / "reproduced.bin").read_bytes(), original_result)
        self.assertEqual((self.project / "reproduced.bin").read_bytes(), original_result)

    def test_invalid_task_is_rejected_before_execution_or_attachment(self):
        """C03, C05: an undeclared task cannot create execution or artifact evidence."""
        run = self.initialize(tasks=("a",))
        before = {path.relative_to(run): path.read_bytes() for path in run.rglob("*") if path.is_file()}
        rejected = self.execute(run, task="undeclared", code="from pathlib import Path; Path('unexpected-task').touch()", expected=2)
        self.assertIn("Unknown task", rejected["error"])
        self.invoke("attach", "--run", run, "--task", "undeclared", "--kind", "result",
                    "--file", "input.txt", expected=2)
        self.assertFalse((self.project / "unexpected-task").exists())
        after = {path.relative_to(run): path.read_bytes() for path in run.rglob("*") if path.is_file()}
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
