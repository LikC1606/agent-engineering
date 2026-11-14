"""Validate case mechanics and known data; this does not test an agent's behavior."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SOURCE = Path(__file__).with_name("agent_projects.py")
SPEC = importlib.util.spec_from_file_location("engineering_agent_projects", SOURCE)
fixtures = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fixtures)


class AgentProjectFixturesTest(unittest.TestCase):
    def setUp(self):
        artifacts = os.environ.get("RUN_TEST_ARTIFACT_DIR")
        if artifacts:
            output = Path(artifacts)
            output.mkdir(parents=True, exist_ok=True)
            self.root = Path(tempfile.mkdtemp(prefix=self._testMethodName + "-", dir=output))
        else:
            temporary = tempfile.TemporaryDirectory()
            self.addCleanup(temporary.cleanup)
            self.root = Path(temporary.name)

    def prepare(self, case_id):
        project = self.root / case_id
        project.mkdir()
        record = fixtures.prepare_case(case_id, project, sys.executable)
        (self.root / (case_id + "-checker.json")).write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        return project, record

    def assert_protected(self, project, prepared):
        for relative, expected in prepared["facts"]["protected_sha256"].items():
            self.assertEqual(hashlib.sha256((project / relative).read_bytes()).hexdigest(), expected, relative)

    def command(self, project, *argv, expected=0):
        command = [sys.executable, *map(str, argv)]
        completed = subprocess.run(command, cwd=project, capture_output=True, text=True)
        with (self.root / "cli-calls.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"argv": command, "cwd": str(project), "returncode": completed.returncode,
                                     "stdout": completed.stdout, "stderr": completed.stderr}) + "\n")
        self.assertEqual(completed.returncode, expected, completed.stdout + completed.stderr)
        return completed

    def test_all_fourteen_cases_prepare_compilable_self_contained_materials(self):
        cases = json.loads(fixtures.CASES.read_text())["cases"]
        self.assertEqual(len(cases), 14)
        for case in cases:
            with self.subTest(case=case["id"]):
                project, prepared = self.prepare(case["id"])
                self.assertTrue(prepared["prompt"].startswith(case["prompt"]))
                self.assertTrue((project / "README.md").is_file())
                self.assertTrue((project / "requirements.md").is_file())
                self.assertTrue((project / "config.json").is_file())
                self.assertEqual(prepared["facts"]["case_id"], case["id"])
                for path in project.rglob("*.py"):
                    compile(path.read_text(encoding="utf-8"), str(path), "exec")
                self.assert_protected(project, prepared)
                self.assertFalse((project / "facts.json").exists())
                self.assertFalse((project / "rubric.json").exists())

    def test_ambiguous_input_really_has_different_sample_and_class_averages(self):
        project, prepared = self.prepare("C01")
        rows = json.loads((project / "data/predictions.json").read_text())
        sample = sum(row["label"] == row["prediction"] for row in rows) / len(rows)
        classes = sorted({row["label"] for row in rows})
        class_mean = sum(sum(row["label"] == row["prediction"] for row in rows if row["label"] == label)
                         / sum(row["label"] == label for row in rows) for label in classes) / len(classes)
        self.assertEqual(sample, prepared["facts"]["sample_accuracy"])
        self.assertEqual(class_mean, prepared["facts"]["class_accuracy_mean"])
        self.assertNotEqual(sample, class_mean)
        self.assertFalse((project / "evaluate.py").exists())
        checked = self.command(project, "inspect_input.py")
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertEqual(json.loads(checked.stdout)["rows"], 100)

    def test_empty_case_has_real_failure_and_retained_success_before_agent_runs(self):
        project, prepared = self.prepare("C08")
        run = project / prepared["facts"]["old_run"]
        status = self.command(project, "tools/run.py", "status", "--run", str(run))
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertEqual(json.loads(status.stdout)["counts"], prepared["facts"]["initial_counts"])
        events = [json.loads(line) for line in (run / "events.jsonl").read_text().splitlines()]
        failed = next(event for event in events if event["event"] == "finished" and event["task"] == "case-2")
        self.assertIn("ZeroDivisionError", (run / failed["logs"]["stderr"]["path"]).read_text())
        self.assertTrue((run / failed["attempt"] / "evaluation/features.jsonl").is_file())
        succeeded = next(event for event in events if event["event"] == "finished" and event["task"] == "case-1")
        result = json.loads((run / succeeded["attempt"] / "evaluation/result.json").read_text())
        self.assertEqual(result["accuracy"], 0.75)
        self.assert_protected(project, prepared)

    def test_old_seed_snapshots_survive_changed_requirements_and_reject_execution(self):
        for case_id in ("C03", "C06"):
            with self.subTest(case=case_id):
                project, prepared = self.prepare(case_id)
                old = project / prepared["facts"]["old_run"]
                data = json.loads((old / "run.json").read_text())
                config_snapshot = next(item for item in data["snapshots"] if item["kind"] == "config")
                self.assertEqual(json.loads((old / config_snapshot["snapshot"]).read_text())["seed"], 7)
                self.assertEqual(json.loads((project / "config.json").read_text())["seed"], 19)
                before = (old / "events.jsonl").read_bytes()
                rejected = self.command(project, "tools/run.py", "exec", "--run", old, "--task", "case-3",
                                        "--", sys.executable, "evaluate.py", "--case", "case-3", expected=2)
                self.assertIn("create a new run", rejected.stderr)
                self.assertEqual((old / "events.jsonl").read_bytes(), before)
                self.assert_protected(project, prepared)
                if case_id == "C06":
                    self.command(project, "evaluate.py", "--case", "case-1", "--output", "outputs/new-configuration")
                    new_result = json.loads((project / "outputs/new-configuration/result.json").read_text())
                    self.assertEqual(new_result["accuracy"], prepared["facts"]["new_case_1_accuracy"])

    def test_logging_fixture_emits_real_intermediates_dual_logs_and_empty_failure(self):
        project, prepared = self.prepare("C05")
        normal = self.command(project, "evaluate.py", "--case", "case-1", "--output", "outputs/normal")
        self.assertIn('"seed": 7', normal.stdout)
        self.assertIn("input rows=4", normal.stderr)
        self.assertTrue((project / "outputs/normal/features.jsonl").is_file())
        self.assertTrue((project / "outputs/normal/result.json").is_file())
        empty = self.command(project, "evaluate.py", "--case", "case-2", "--output", "outputs/empty", expected=1)
        self.assertIn("ZeroDivisionError", empty.stderr)
        self.assertTrue((project / "outputs/empty/features.jsonl").is_file())
        self.assertFalse((project / "outputs/empty/result.json").exists())
        self.assert_protected(project, prepared)

    def test_pilot_gate_and_existing_batch_export_entries_really_work(self):
        for case_id in ("C04", "C12"):
            with self.subTest(case=case_id):
                project, prepared = self.prepare(case_id)
                if case_id == "C04":
                    blocked = self.command(project, "run_batch.py", "--phase", "full", expected=1)
                    self.assertIn("完整批次尚未开放", blocked.stderr)
                    self.assertFalse((project / "outputs/full").exists())
                    self.command(project, "run_batch.py", "--phase", "pilot", expected=1)
                    events = [json.loads(line) for line in (project / "outputs/batch-events.jsonl").read_text().splitlines()]
                    self.assertEqual([item["case"] for item in events], prepared["facts"]["pilot"])
                    self.assertEqual([item["exit_code"] for item in events], [0, 0, 1])
                    (project / "outputs/pilot-review.json").write_text(json.dumps({"validated": True,
                        "observation": "正常与空输入已按协议检查；缺字段被明确拒绝。"}))
                self.command(project, "run_batch.py", "--phase", "full")
                self.command(project, "export_results.py", "--phase", "full")
                summary = json.loads((project / "outputs/summary.json").read_text())
                self.assertFalse(summary["errors"])
                self.assertEqual(len(summary["cases"]), 12 if case_id == "C04" else 2)
                events_before = (project / "outputs/batch-events.jsonl").read_bytes()
                self.command(project, "run_batch.py", "--phase", "full", "--retry-failed")
                self.assertEqual((project / "outputs/batch-events.jsonl").read_bytes(), events_before)
                self.assert_protected(project, prepared)

    def test_anomalous_result_has_real_train_branch_and_corrected_test_result(self):
        project, prepared = self.prepare("C11")
        train = json.loads((project / "data/train.json").read_text())
        test = json.loads((project / "data/test.json").read_text())
        self.assertTrue({row["sample_id"] for row in train}.isdisjoint(row["sample_id"] for row in test))
        old = project / prepared["facts"]["old_run"]
        for setting, accuracy in prepared["facts"]["reported_accuracy"].items():
            attempt = next((old / "attempts" / setting).iterdir())
            result = json.loads((attempt / "evaluation/result.json").read_text())
            self.assertEqual(result["accuracy"], accuracy)
            if setting == "enhanced":
                self.assertIn("data/train.json", (attempt / "stdout.log").read_text())
        evaluator = project / "evaluate.py"
        evaluator.write_text(evaluator.read_text().replace('split = "train" if args.case == "enhanced" else config["evaluation_split"]',
                                                           'split = config["evaluation_split"]'))
        self.command(project, "evaluate.py", "--case", "enhanced", "--output", "outputs/recomputed")
        recomputed = json.loads((project / "outputs/recomputed/result.json").read_text())
        self.assertEqual(recomputed["accuracy"], prepared["facts"]["corrected_accuracy"]["enhanced"])
        self.assert_protected(project, prepared)

    def test_saved_progress_and_resource_samples_match_private_known_values(self):
        project, prepared = self.prepare("C10")
        for view, key in (("current", "current"), ("after-repair", "repaired")):
            sampled = json.loads(self.command(project, "scheduler_sample.py", "--view", view).stdout)
            states = {task: "pending" for task in sampled["tasks"]}
            failed = 0
            for event in sampled["events"]:
                states[event["task"]] = ("running" if event["event"] == "started" else
                                         "completed" if event["exit_code"] == 0 else "error")
                failed += event["event"] == "finished" and event.get("exit_code") != 0
            counts = {state: sum(value == state for value in states.values()) for state in ("completed", "running", "error", "pending")}
            counts["total"] = len(states)
            self.assertEqual(counts, prepared["facts"][key + "_counts"])
            self.assertEqual(failed, 1)
            speed = counts["completed"] / sampled["sample"]["sample_at_seconds"]
            self.assertEqual(speed, prepared["facts"][key + "_speed"])
            eta = None if counts["error"] else (counts["total"] - counts["completed"]) / speed
            self.assertEqual(eta, prepared["facts"][key + "_eta"])
        resources, resource_case = self.prepare("C09")
        sampled = json.loads(self.command(resources, "inspect_resources.py").stdout)
        self.assertEqual(sum(row["status"] == 429 for row in sampled["requests"]), resource_case["facts"]["http_429_count"])
        self.assertEqual(sampled["resources"]["concurrency"], 2)
        self.assert_protected(project, prepared)
        self.assert_protected(resources, resource_case)

    def test_prior_lesson_points_to_real_failure_and_new_empty_pilot_succeeds(self):
        project, prepared = self.prepare("C13")
        lesson_path = project / prepared["facts"]["lesson_path"]
        lesson = json.loads(lesson_path.read_text())
        old = project / prepared["facts"]["old_run"]
        self.assertIn("ZeroDivisionError", (old / lesson["evidence"][0]).read_text())
        for task in prepared["facts"]["new_pilot_tasks"]:
            self.command(project, "evaluate.py", "--case", task)
        result = json.loads((project / "outputs/next-empty/result.json").read_text())
        self.assertEqual(result["count"], 0)
        self.assertIsNone(result["accuracy"])
        self.assertEqual(lesson_path.read_text(), prepared["facts"]["prior_lesson_prefix"])
        self.assert_protected(project, prepared)

    def test_moved_project_recomputes_after_original_directory_is_removed(self):
        project, prepared = self.prepare("C14")
        self.assertTrue(prepared["facts"]["original_project_removed"])
        self.assertFalse(Path(prepared["facts"]["original_project"]).exists())
        completed = self.command(project, "reproduce.py")
        compared = json.loads(completed.stdout)
        self.assertTrue(compared["matches"])
        self.assertEqual(compared["results"], prepared["facts"]["baseline"])
        self.assertTrue((project / prepared["facts"]["comparison_file"]).is_file())
        self.assertTrue(Path(compared["run"]).is_relative_to(project))
        self.assert_protected(project, prepared)


if __name__ == "__main__":
    unittest.main()
