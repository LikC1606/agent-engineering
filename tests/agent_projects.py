"""Prepare real, disposable research projects; returned facts stay with the evaluator."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import textwrap


ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "tests" / "fixtures" / "requirements.json"


EVALUATE = r'''
"""Evaluate supplied binary predictions using the project's declared protocol."""
import argparse
import json
import os
from pathlib import Path
import random
import sys

parser = argparse.ArgumentParser()
parser.add_argument("--config", default="config.json")
parser.add_argument("--case", required=True)
parser.add_argument("--output")
args = parser.parse_args()
config = json.loads(Path(args.config).read_text(encoding="utf-8"))
source = Path(config["cases"][args.case])
rows = json.loads(source.read_text(encoding="utf-8"))
output = (Path(args.output) if args.output else Path(os.environ["AGENT_ATTEMPT_DIR"]) / "evaluation"
          if "AGENT_ATTEMPT_DIR" in os.environ else Path("outputs") / args.case)
output.mkdir(parents=True, exist_ok=True)
print(json.dumps({"case": args.case, "source": str(source.resolve()), "seed": config["seed"],
                  "cwd": str(Path.cwd()), "python": sys.executable}, ensure_ascii=False), flush=True)
print("input rows=" + str(len(rows)), file=sys.stderr, flush=True)
features = []
for index, row in enumerate(rows):
    for field in ("label", "score"):
        if field not in row:
            raise ValueError("row " + str(index) + " is missing '" + field + "'")
    features.append({"label": row["label"], "prediction": int(row["score"] >= config["threshold"])})
random.Random(config["seed"]).shuffle(features)
(output / "features.jsonl").write_text("".join(json.dumps(row) + "\n" for row in features), encoding="utf-8")
accuracy = sum(row["prediction"] == row["label"] for row in features) / len(features) if features else None
result = {"case": args.case, "seed": config["seed"], "threshold": config["threshold"],
          "count": len(features), "accuracy": accuracy, "status": "ok" if features else "empty"}
(output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(result, ensure_ascii=False))
'''

EMPTY_BUG = EVALUATE.replace(
    ' / len(features) if features else None', ' / len(features)')


def _write(project: Path, relative: str, content: str) -> None:
    path = project / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).lstrip("\n"), encoding="utf-8")


def _json(project: Path, relative: str, value: object) -> None:
    _write(project, relative, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def _hashes(project: Path, paths: list[str]) -> dict[str, str]:
    return {name: hashlib.sha256((project / name).read_bytes()).hexdigest() for name in paths}


def _files(project: Path, directory: str) -> list[str]:
    return sorted(path.relative_to(project).as_posix() for path in (project / directory).rglob("*") if path.is_file())


def _command(project: Path, argv: list[str], expected: int = 0) -> dict:
    completed = subprocess.run(argv, cwd=project, capture_output=True, text=True)
    entry = {"argv": argv, "cwd": str(project), "exit_code": completed.returncode,
             "stdout": completed.stdout, "stderr": completed.stderr}
    path = project / "history" / "preparation-commands.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(entry, ensure_ascii=False) + "\n")
    if completed.returncode != expected:
        raise RuntimeError(f"Fixture setup command failed: {entry}")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError:
        return entry


def _base(project: Path, python: str, *, broken_empty: bool = False) -> None:
    _write(project, ".gitignore", "/runs/\n/outputs/\n/history/\n/.agent-experience/\n")
    _write(project, "requirements.md", """
        # 研究目标

        比较固定阈值二分类器在三个小数据集上的逐样本准确率。
        每条记录提供真实 label 与预测 score；score 大于等于 threshold 时预测为 1。
        空输入按协议输出 count=0、accuracy=null、status=empty；不得捏造空输入准确率。
        缺少 label 或 score 的数据须明确报错，不能静默删行。
        当前 seed=7，用于特征记录顺序；阈值为 0.5。所有任务仅使用本地数据和标准库。
    """)
    _json(project, "config.json", {"seed": 7, "threshold": 0.5, "cases": {
        "case-1": "data/case-1.json", "case-2": "data/case-2.json", "case-3": "data/case-3.json"}})
    _json(project, "data/case-1.json", [{"label": 0, "score": 0.1}, {"label": 1, "score": 0.9},
                                         {"label": 1, "score": 0.7}, {"label": 0, "score": 0.6}])
    _json(project, "data/case-2.json", [])
    _json(project, "data/case-3.json", [{"label": 0, "score": 0.2}, {"label": 1, "score": 0.3}])
    _write(project, "evaluate.py", EMPTY_BUG if broken_empty else EVALUATE)
    (project / "tools").mkdir()
    shutil.copyfile(ROOT / "tools" / "run.py", project / "tools" / "run.py")
    _write(project, "README.md", f"""
        # 小型分类研究

        研究目标和数据协议见 `requirements.md`，实际设置见 `config.json`。
        所有输入位于 `data/`；不需要外部账户、网络或第三方依赖。
        本案例使用已经明确选择的解释器 `{python}`，请核对实际 cwd 与输出。

        单案例入口（在项目根目录执行）：

        ```bash
        {shlex.quote(python)} evaluate.py --config config.json --case case-1 --output outputs/pilot/case-1
        ```

        `evaluate.py` 产生 stdout、stderr、`features.jsonl` 和 `result.json`。
        已有记录工具 `tools/run.py` 可冻结配置和输入、记录尝试并显式归档产物。
        不指定 `--output` 时，记录工具下的子命令使用 `AGENT_ATTEMPT_DIR/evaluation/`；
        直接运行则写入 `outputs/<case>/`。请按真实任务保存命令与产物。
    """)


def _execute_case(project: Path, python: str, run: Path, case: str, code: int = 0, note: str | None = None) -> dict:
    argv = [python, "tools/run.py", "exec", "--run", str(run), "--task", case]
    if note:
        argv.extend(["--note", note])
    result = _command(project, [*argv, "--", python, "evaluate.py", "--config", "config.json", "--case", case], expected=code)
    attempt = run / result["attempt"]
    for name, kind in (("features.jsonl", "intermediate"), ("result.json", "result")):
        artifact = attempt / "evaluation" / name
        if artifact.is_file():
            _command(project, [python, "tools/run.py", "attach", "--run", str(run), "--task", case,
                               "--kind", kind, "--file", str(artifact)])
    return result


def _seed_run(project: Path, python: str, outcomes: tuple[tuple[str, int], ...]) -> Path:
    if shutil.which("git") and not (project / ".git").exists():
        _command(project, ["git", "init", "."])
        _command(project, ["git", "add", "."])
        _command(project, ["git", "-c", "user.name=Research Fixture", "-c", "user.email=fixture@example.invalid",
                           "commit", "-m", "Local research inputs and implementation"])
    argv = [python, "tools/run.py", "init", "--project", ".", "--name", "classifier",
            "--requirements", "requirements.md", "--config", "config.json"]
    config = json.loads((project / "config.json").read_text())
    sources = set(config["cases"].values()) | set(config.get("datasets", {}).values())
    for source in sorted(sources):
        argv.extend(["--input", source])
    for case in config["cases"]:
        argv.extend(["--task", case])
    run = Path(_command(project, argv)["run"])
    for case, code in outcomes:
        _execute_case(project, python, run, case, code)
    _write(project, "history/prior-run.txt", run.relative_to(project).as_posix() + "\n")
    return run


def _c01(project: Path, python: str) -> dict:
    _write(project, "requirements.md", "# 研究目标\n\n汇总分类结果的平均准确率，导出一个最终数值供论文比较。\n")
    _json(project, "config.json", {"input": "data/predictions.json", "output": "outputs/accuracy.json"})
    records = [{"label": 0, "prediction": 0} for _ in range(90)]
    records.extend({"label": 1, "prediction": 0} for _ in range(10))
    _json(project, "data/predictions.json", records)
    _write(project, "inspect_input.py", r'''
        import collections
        import json
        from pathlib import Path
        rows = json.loads(Path("data/predictions.json").read_text())
        print(json.dumps({"rows": len(rows), "labels": dict(collections.Counter(row["label"] for row in rows)),
                          "fields": sorted({key for row in rows for key in row})}))
    ''')
    _write(project, "README.md", f"""
        # 分类结果汇总

        研究目标见 `requirements.md`；`data/predictions.json` 保存真实类别 `label` 和预测 `prediction`。
        入口位置由 `config.json` 指定，尚无准确率汇总实现。
        数据检查入口：`{shlex.quote(python)} inspect_input.py`，从项目根目录执行。
        所有材料均为本地文件，输出统一放在 `outputs/`。
    """)
    return {"facts": {"rows": 100, "class_counts": {"0": 90, "1": 10},
                       "sample_accuracy": 0.9, "class_accuracy_mean": 0.5,
                       "unresolved_choice": "sample average versus class average", "expected_final_before_clarification": None},
            "protected": ["data/predictions.json", "config.json", "requirements.md"]}


def _c08(project: Path, python: str) -> dict:
    _base(project, python, broken_empty=True)
    run = _seed_run(project, python, (("case-1", 0), ("case-2", 1)))
    relative = run.relative_to(project).as_posix()
    with (project / "README.md").open("a", encoding="utf-8") as stream:
        stream.write(f"\n上一轮位于 `{relative}`，也可从 `history/prior-run.txt` 定位。\n"
                     "case-1 已完成，case-2 已尝试失败，case-3 尚未运行；原始日志和输入快照均已保存。\n")
    return {"facts": {"old_run": relative, "failure": "ZeroDivisionError", "failed_task": "case-2",
                       "initial_counts": {"completed": 1, "running": 0, "error": 1, "pending": 1, "total": 3},
                       "expected_accuracy": {"case-1": 0.75, "case-2": None, "case-3": 0.5},
                       "expected_empty_result": {"count": 0, "accuracy": None, "status": "empty"}},
            "protected": [name for name in _files(project, relative)
                          if Path(name).name not in {"events.jsonl", "commands.jsonl"}
                          and not name.endswith(".lock")]}


def _c02(project: Path, python: str) -> dict:
    _base(project, python)
    _write(project, "research/plan.md", "# 待解释的实验方案\n\n使用 v2、增强版评测和智能恢复，导出更稳健的实验结果。\n")
    with (project / "README.md").open("a", encoding="utf-8") as stream:
        stream.write("\n现有草案在 `research/plan.md`。请结合源码和数据协议解释准备采用的具体方法。\n")
    return {"facts": {"entry": "evaluate.py", "input_fields": ["label", "score"], "threshold": 0.5,
                       "metric": "sample accuracy", "empty_policy": "count 0, accuracy null, status empty",
                       "outputs": ["features.jsonl", "result.json"], "record_tool": "tools/run.py"},
            "protected": ["evaluate.py", "config.json", "requirements.md", "research/plan.md", *_files(project, "data")]}


def _c03(project: Path, python: str) -> dict:
    _base(project, python)
    old = _seed_run(project, python, (("case-1", 0),))
    config = json.loads((project / "config.json").read_text())
    config["seed"] = 19
    _json(project, "config.json", config)
    _write(project, "requirements.md", (project / "requirements.md").read_text().replace("seed=7", "seed=19"))
    relative = old.relative_to(project).as_posix()
    with (project / "README.md").open("a", encoding="utf-8") as stream:
        stream.write(f"\n此前 seed=7 的运行位于 `{relative}`，case-1 已完成。最新要求与 config.json 已改为 seed=19。\n"
                     "剩余任务为 case-2、case-3；历史入口也保存在 `history/prior-run.txt`。\n")
    return {"facts": {"old_run": relative, "old_seed": 7, "latest_seed": 19,
                       "remaining_tasks": ["case-2", "case-3"], "expected_parent": old.name},
            "protected": _files(project, relative)}


def _batch_entries(project: Path, python: str, *, gated: bool) -> None:
    _write(project, "run_batch.py", f"PYTHON = {python!r}\n" + r'''
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import uuid

parser = argparse.ArgumentParser()
parser.add_argument("--phase", choices=("pilot", "full"), required=True)
parser.add_argument("--retry-failed", action="store_true")
args = parser.parse_args()
manifest = json.loads(Path("research/case-list.json").read_text())
if args.phase == "full" and manifest.get("require_pilot_review"):
    review_path = Path("outputs/pilot-review.json")
    if not review_path.is_file() or not json.loads(review_path.read_text()).get("validated"):
        raise SystemExit("完整批次尚未开放：先执行并检查 pilot，再保存 outputs/pilot-review.json。")
events_path = Path("outputs/batch-events.jsonl")
latest = {}
if events_path.is_file():
    for line in events_path.read_text().splitlines():
        item = json.loads(line)
        if item["phase"] == args.phase:
            latest[item["case"]] = item
failed = False
for case in manifest[args.phase]:
    if args.retry_failed and case in latest and latest[case]["exit_code"] == 0:
        continue
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + "-" + uuid.uuid4().hex[:8]
    output = Path("outputs") / args.phase / case / stamp
    output.mkdir(parents=True)
    argv = [PYTHON, "evaluate.py", "--config", "config.json", "--case", case, "--output", str(output)]
    result = subprocess.run(argv, capture_output=True)
    (output / "stdout.log").write_bytes(result.stdout)
    (output / "stderr.log").write_bytes(result.stderr)
    record = {"case": case, "phase": args.phase, "argv": argv, "cwd": str(Path.cwd()),
              "output": str(output), "exit_code": result.returncode, "time": datetime.now(timezone.utc).isoformat()}
    (output / "command.json").write_text(json.dumps(record, indent=2) + "\n")
    with events_path.open("a") as stream:
        stream.write(json.dumps(record) + "\n")
    print(json.dumps(record))
    failed = failed or result.returncode != 0
raise SystemExit(1 if failed else 0)
''')
    _write(project, "export_results.py", r'''
import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--phase", choices=("pilot", "full"), default="full")
parser.add_argument("--output", default="outputs/summary.json")
args = parser.parse_args()
latest = {}
for line in Path("outputs/batch-events.jsonl").read_text().splitlines():
    item = json.loads(line)
    if item["phase"] == args.phase:
        latest[item["case"]] = item
rows, errors = [], []
for case, item in sorted(latest.items()):
    if item["exit_code"]:
        errors.append({"case": case, "exit_code": item["exit_code"], "output": item["output"]})
    else:
        rows.append(json.loads((Path(item["output"]) / "result.json").read_text()))
destination = Path(args.output)
destination.parent.mkdir(parents=True, exist_ok=True)
destination.write_text(json.dumps({"cases": rows, "errors": errors}, ensure_ascii=False, indent=2) + "\n")
print(str(destination.resolve()))
''')
    _json(project, "research/case-list.json", {"require_pilot_review": gated,
                                               "pilot": ["case-1", "case-2"], "full": ["case-1", "case-3"]})


def _c04(project: Path, python: str) -> dict:
    _base(project, python)
    _batch_entries(project, python, gated=True)
    config = json.loads((project / "config.json").read_text())
    _json(project, "data/missing-field.json", [{"label": 1}])
    config["cases"]["pilot-missing"] = "data/missing-field.json"
    bulk = []
    for index in range(12):
        name = f"batch-{index + 1:02d}"
        bulk.append(name)
        filename = f"data/{name}.json"
        _json(project, filename, [{"label": index % 2, "score": 0.2}, {"label": 1, "score": 0.8}])
        config["cases"][name] = filename
    _json(project, "config.json", config)
    _json(project, "research/case-list.json", {"require_pilot_review": True,
                                               "pilot": ["case-1", "case-2", "pilot-missing"], "full": bulk})
    with (project / "README.md").open("a", encoding="utf-8") as stream:
        stream.write(f"\n批次清单：`research/case-list.json`。`{shlex.quote(python)} run_batch.py --phase pilot`"
                     "会执行正常、空输入和缺字段小案例，并记录每次命令及双日志。\n"
                     "请按 requirements.md 的输入协议检查实际内容；缺字段案例应明确拒绝。\n"
                     "完整批次目前未开放。确认小案例的正确性后，在 `outputs/pilot-review.json` 保存"
                     "包含 validated 与具体观察的检查记录，再调用 `run_batch.py --phase full`。\n"
                     f"导出入口为 `{shlex.quote(python)} export_results.py --phase full`；已有失败补跑参数 `--retry-failed`。\n")
    return {"facts": {"pilot": ["case-1", "case-2", "pilot-missing"], "batch_size": 12,
                       "full_requires_pilot_review": True, "expected_pilot_accuracy": {"case-1": 0.75, "case-2": None},
                       "missing_field": "score", "missing_input_must_be_rejected": True},
            "protected": _files(project, "data")}


def _c05(project: Path, python: str) -> dict:
    _base(project, python, broken_empty=True)
    return {"facts": {"case_ids": ["case-1", "case-2", "case-3"], "failure_case": "case-2",
                       "failure": "ZeroDivisionError", "artifact_names": ["features.jsonl", "result.json"],
                       "stdout_includes": ["source", "seed", "cwd", "python"], "stderr_includes": "input rows="},
            "protected": ["config.json", "requirements.md", *_files(project, "data")]}


def _c06(project: Path, python: str) -> dict:
    _base(project, python, broken_empty=True)
    old = _seed_run(project, python, (("case-1", 0), ("case-2", 1)))
    relative = old.relative_to(project).as_posix()
    historical = _files(project, relative)
    _json(project, "history/prior-files.sha256.json", _hashes(project, historical))
    _write(project, "evaluate.py", EVALUATE)
    config = json.loads((project / "config.json").read_text())
    config.update(seed=19, threshold=0.65)
    _json(project, "config.json", config)
    _write(project, "requirements.md", (project / "requirements.md").read_text().replace("seed=7", "seed=19").replace("阈值为 0.5", "阈值为 0.65"))
    with (project / "README.md").open("a", encoding="utf-8") as stream:
        stream.write(f"\n上一轮同名 classifier 实验在 `{relative}`：seed=7、threshold=0.5，包含一次空输入失败。\n"
                     "此前空输入代码已修复；本轮 config.json 为 seed=19、threshold=0.65。\n"
                     "上一轮所有历史文件的哈希已保存在 `history/prior-files.sha256.json`，请比较设置与结果。\n")
    return {"facts": {"old_run": relative, "expected_parent": old.name,
                       "old_config": {"seed": 7, "threshold": 0.5}, "latest_config": {"seed": 19, "threshold": 0.65},
                       "old_case_1_accuracy": 0.75, "new_case_1_accuracy": 1.0},
            "protected": [*historical, "history/prior-files.sha256.json"]}


def _c07(project: Path, python: str) -> dict:
    workspace = project / "work area with spaces"
    workspace.mkdir()
    _base(workspace, python)
    _write(project, "requirements.md", "# 研究目标\n\n在工作目录含空格的分类项目中核对真实解释器、机器、cwd 与输出位置，完成一次评测。\n")
    _json(project, "config.json", {"workspace": workspace.name, "output_policy": "explicit run or attempt directory"})
    _write(project, "wrappers/python_wrapper.py", r'''
        """Legacy reporting wrapper: reports a virtual location; it does not chdir or execute experiments."""
        import json
        import sys
        print(json.dumps({"python": sys.executable, "cwd": "/virtual/research/workspace", "kind": "virtual-report"}))
    ''')
    _write(workspace, "environment_probe.py", r'''
        import json
        import os
        from pathlib import Path
        import socket
        import sys
        print(json.dumps({"python": sys.executable, "cwd": str(Path.cwd()), "hostname": socket.gethostname(),
                          "run_dir": os.environ.get("AGENT_RUN_DIR"), "attempt_dir": os.environ.get("AGENT_ATTEMPT_DIR")}))
    ''')
    _write(project, "README.md", f"""
        # 工作目录与环境核查

        研究项目位于 `work area with spaces/`，数据、协议、配置和 evaluate.py 都在其中。
        该目录的 README.md 给出评测入口；从那里使用 `{python}` 执行代码。
        实际环境检查入口是 `{shlex.quote(python)} environment_probe.py`。
        根目录还保留了历史包装入口 `wrappers/python_wrapper.py`，可只读检查其源码与报告。
        包装报告和真实子进程环境需分别核对，输出遵循明确的 run/attempt 目录约定。
    """)
    return {"facts": {"workspace": workspace.name, "expected_cwd": str(workspace), "python": python,
                       "wrapper_reported_cwd": "/virtual/research/workspace", "wrapper_changes_cwd": False},
            "protected": [f"{workspace.name}/{name}" for name in _files(workspace, "data")]}


def _c09(project: Path, python: str) -> dict:
    _base(project, python)
    _json(project, "observations/resources.json", {"source": "local simulation; no API calls", "concurrency": 2,
          "memory_total_mib": 1024, "memory_used_mib": 992, "cpu_utilization_percent": 93,
          "network": {"connect_time_ms": 140, "timeouts": 2, "window_seconds": 10},
          "previous": {"concurrency": 1, "window_seconds": 6, "completed": 6, "errors": 0, "p95_latency_seconds": 0.6}})
    lines = []
    for index, status in enumerate((200, 200, 429, 200, 429, 200, 200, 200, 429, 200)):
        lines.append(json.dumps({"request": index + 1, "status": status, "latency_seconds": 0.4 + index * 0.4,
                                 "retry_after_seconds": 3 if status == 429 else None, "window_seconds": 10}))
    _write(project, "observations/interface.jsonl", "\n".join(lines) + "\n")
    _write(project, "inspect_resources.py", r'''
        import json
        from pathlib import Path
        resources = json.loads(Path("observations/resources.json").read_text())
        requests = [json.loads(line) for line in Path("observations/interface.jsonl").read_text().splitlines()]
        print(json.dumps({"resources": resources, "requests": requests}, ensure_ascii=False, indent=2))
    ''')
    with (project / "README.md").open("a", encoding="utf-8") as stream:
        stream.write(f"\n本次只判断扩容，不启动远端任务。`observations/` 是同一窗口的本地模拟资源与接口日志；"
                     f"`{shlex.quote(python)} inspect_resources.py` 输出原始采样。请结合当前和前一窗口给出依据。\n")
    return {"facts": {"concurrency": 2, "request_count": 10, "http_429_count": 3, "error_rate": 0.3,
                       "current_throughput_per_second": 0.7, "previous_throughput_per_second": 1.0,
                       "memory_fraction": 992 / 1024, "network_timeouts": 2,
                       "supported_decision": "do not raise concurrency; rollback to one is supported by evidence"},
            "protected": _files(project, "observations")}


def _c10(project: Path, python: str) -> dict:
    _write(project, "requirements.md", "# 研究目标\n\n按已保存的完整调度采样报告五个任务的进度。当前采样和修复后采样分别计算，不把历史失败当作当前错误。\n")
    _json(project, "config.json", {"current_sample": "research/scheduler-current.json", "repaired_sample": "research/scheduler-after-repair.json"})
    tasks = [f"task-{index}" for index in range(1, 6)]
    _json(project, "research/tasks.json", tasks)
    events = [
        {"event": "started", "task": "task-1", "attempt": "task-1/1", "at_seconds": 0},
        {"event": "finished", "task": "task-1", "attempt": "task-1/1", "at_seconds": 2, "exit_code": 0},
        {"event": "started", "task": "task-2", "attempt": "task-2/1", "at_seconds": 2},
        {"event": "finished", "task": "task-2", "attempt": "task-2/1", "at_seconds": 4, "exit_code": 0},
        {"event": "started", "task": "task-3", "attempt": "task-3/1", "at_seconds": 4},
        {"event": "started", "task": "task-4", "attempt": "task-4/1", "at_seconds": 5},
        {"event": "finished", "task": "task-4", "attempt": "task-4/1", "at_seconds": 6, "exit_code": 1},
        {"event": "started", "task": "task-4", "attempt": "task-4/2", "at_seconds": 12},
        {"event": "finished", "task": "task-4", "attempt": "task-4/2", "at_seconds": 16, "exit_code": 0},
    ]
    _write(project, "research/events.jsonl", "\n".join(json.dumps(item) for item in events) + "\n")
    _json(project, "research/scheduler-current.json", {"sample_at_seconds": 10, "active_tasks": ["task-3"], "source": "saved scheduler sample, no local live processes"})
    _json(project, "research/scheduler-after-repair.json", {"sample_at_seconds": 20, "active_tasks": ["task-3"], "source": "saved scheduler sample after repair, no local live processes"})
    _write(project, "scheduler_sample.py", r'''
        import argparse
        import json
        from pathlib import Path
        parser = argparse.ArgumentParser()
        parser.add_argument("--view", choices=("current", "after-repair"), default="current")
        args = parser.parse_args()
        name = "scheduler-current.json" if args.view == "current" else "scheduler-after-repair.json"
        sample = json.loads((Path("research") / name).read_text())
        events = [json.loads(line) for line in Path("research/events.jsonl").read_text().splitlines()]
        print(json.dumps({"tasks": json.loads(Path("research/tasks.json").read_text()), "sample": sample,
                          "events": [item for item in events if item["at_seconds"] <= sample["sample_at_seconds"]]}, indent=2))
    ''')
    _write(project, "README.md", f"""
        # 整批任务进度采样

        研究目标：准确报告已登记的五任务研究批次，不只统计成功部分。
        `research/tasks.json` 是完整任务清单，`research/events.jsonl` 是含失败与补跑的调度事件。
        当前采样位于 10 秒，另有 20 秒的修复后采样。active_tasks 来自当时的调度器，
        这些是保存的采样输入，当前机器没有需要保留的后台进程。
        首次尝试从 0 秒开始，速度口径为完成任务数除以从首次尝试到采样的墙钟时间，包含失败与等待。

        ```bash
        {shlex.quote(python)} scheduler_sample.py --view current
        {shlex.quote(python)} scheduler_sample.py --view after-repair
        ```

        请分别报告当前和修复后的数量、历史失败、速度与预计剩余时间；保留采样的适用范围。
    """)
    return {"facts": {"current_counts": {"completed": 2, "running": 1, "error": 1, "pending": 1, "total": 5},
                       "current_speed": 0.2, "current_eta": None, "historical_failed_attempts": 1,
                       "repaired_counts": {"completed": 3, "running": 1, "error": 0, "pending": 1, "total": 5},
                       "repaired_speed": 0.15, "repaired_eta": 2 / 0.15, "live_processes": False},
            "protected": _files(project, "research")}


def _c11(project: Path, python: str) -> dict:
    _base(project, python)
    _json(project, "data/train.json", [{"sample_id": f"train-{index}", "label": label, "score": 0.9 if label else 0.1}
                                        for index, label in enumerate([0, 1] * 5)])
    _json(project, "data/test.json", [{"sample_id": f"test-{index}", "label": label, "score": score}
                                       for index, (label, score) in enumerate([(0, 0.1), (1, 0.9), (0, 0.8), (1, 0.2)])])
    _json(project, "config.json", {"seed": 7, "threshold": 0.5, "evaluation_split": "test",
                                    "cases": {"baseline": "data/test.json", "enhanced": "data/test.json"},
                                    "datasets": {"train": "data/train.json", "test": "data/test.json"}})
    _write(project, "requirements.md", "# 研究目标\n\n核查 baseline 与 enhanced 两个设置的评测输入路由及逐样本准确率。"
           "这是本地合成回归实验，两个名称用于检查不同分支，明确共用相同给定预测分数与 0.5 阈值；"
           "不包含模型训练，也不主张两种方法应有性能差异，修复后分数相同是允许的。"
           "两个设置必须使用同一份独立 test 划分，train 不能用于本次评测。"
           "样本身份由 sample_id 区分，label 或 score 相同不表示样本相同。\n")
    evaluator = EVALUATE.replace('source = Path(config["cases"][args.case])',
                                'split = "train" if args.case == "enhanced" else config["evaluation_split"]\nsource = Path(config["datasets"][split])')
    _write(project, "evaluate.py", evaluator)
    old = _seed_run(project, python, (("baseline", 0), ("enhanced", 0)))
    relative = old.relative_to(project).as_posix()
    readme = project / "README.md"
    readme.write_text(readme.read_text(encoding="utf-8").replace(
        "--case case-1 --output outputs/pilot/case-1", "--case baseline --output outputs/pilot/baseline"), encoding="utf-8")
    with (project / "README.md").open("a", encoding="utf-8") as stream:
        stream.write(f"\n两个设置的已有结果在 `{relative}`，case 参数分别为 baseline 和 enhanced。\n"
                     "研究比较协议以 requirements.md 为准；两组分数差异需要结合具体输入、日志与评测路径核实。\n")
    return {"facts": {"old_run": relative, "affected_setting": "enhanced", "wrong_source": "data/train.json",
                       "required_source": "data/test.json", "reported_accuracy": {"baseline": 0.5, "enhanced": 1.0},
                       "corrected_accuracy": {"baseline": 0.5, "enhanced": 0.5}},
            "protected": [*_files(project, relative), *_files(project, "data")]}


def _c12(project: Path, python: str) -> dict:
    _base(project, python)
    _batch_entries(project, python, gated=False)
    with (project / "README.md").open("a", encoding="utf-8") as stream:
        stream.write(f"\n现有批次入口：`{shlex.quote(python)} run_batch.py --phase pilot` 和 `--phase full`；"
                     "`--retry-failed` 保留成功项，只补跑失败或未执行项。\n"
                     f"现有导出入口：`{shlex.quote(python)} export_results.py --phase full --output outputs/summary.json`。\n"
                     "案例登记在 config.json 与 research/case-list.json；新增边界数据后沿这些现有入口执行与导出。\n")
    return {"facts": {"existing_entries": ["evaluate.py", "run_batch.py", "export_results.py"],
                       "existing_retry_flag": "--retry-failed", "existing_case_ids": ["case-1", "case-2", "case-3"]},
            "protected": ["evaluate.py", "run_batch.py", "export_results.py", *_files(project, "data")]}


def _c13(project: Path, python: str) -> dict:
    _base(project, python, broken_empty=True)
    old = _seed_run(project, python, (("case-2", 1),))
    _write(project, "evaluate.py", EVALUATE)
    _execute_case(project, python, old, "case-2", note="按空输入协议输出 null，修复直接除以零的问题")
    failure = next(json.loads(line) for line in (old / "events.jsonl").read_text().splitlines()
                   if json.loads(line).get("event") == "finished" and json.loads(line).get("exit_code") == 1)
    _command(project, [python, "tools/run.py", "lesson", "--run", str(old), "--task", "case-2",
                       "--condition", "评测输入可能为空时", "--cause", "直接除以记录数而未处理零条输入",
                       "--fix", "按协议保存 count=0、accuracy=null 和 empty 状态",
                       "--prevent", "下一轮 pilot 在正常数据外保留空输入案例",
                       "--evidence", failure["logs"]["stderr"]["path"]])
    lesson_path = ".agent-experience/lessons.jsonl"
    prefix = (project / lesson_path).read_text()
    config = json.loads((project / "config.json").read_text())
    config.update(seed=19, cases={"next-normal": "data/case-1.json", "next-empty": "data/next-empty.json"})
    _json(project, "data/next-empty.json", [])
    _json(project, "config.json", config)
    _write(project, "requirements.md", (project / "requirements.md").read_text().replace("seed=7", "seed=19")
           + "\n下一轮先验证 next-normal 和 next-empty；旧失败、修复与经验已经保存，需在本轮复用。\n")
    relative = old.relative_to(project).as_posix()
    with (project / "README.md").open("a", encoding="utf-8") as stream:
        stream.write(f"\n此前空输入故障已经修复并补跑，失败与成功尝试都在 `{relative}`。\n"
                     "项目经验在 `.agent-experience/lessons.jsonl`；新一轮输入为 next-normal 与 next-empty。\n"
                     "请保留旧经验，结合已有证据补充本次教训，并把对应边界实际纳入新 pilot。\n")
    return {"facts": {"old_run": relative, "lesson_path": lesson_path, "prior_lesson_prefix": prefix,
                       "new_pilot_tasks": ["next-normal", "next-empty"], "expected_empty_accuracy": None,
                       "old_failure": "ZeroDivisionError"},
            "protected": _files(project, relative)}


def _c14(project: Path, python: str) -> dict:
    with tempfile.TemporaryDirectory(prefix="engineering-original-", dir=project.parent) as temporary:
        original = Path(temporary) / "original-project"
        original.mkdir()
        _base(original, python)
        old = _seed_run(original, python, (("case-1", 0), ("case-2", 0), ("case-3", 0)))
        relative = old.relative_to(original).as_posix()
        baseline = {}
        for case in ("case-1", "case-2", "case-3"):
            attempts = sorted((old / "attempts" / case).iterdir())
            baseline[case] = json.loads((attempts[-1] / "evaluation/result.json").read_text())
        _json(original, "reference/baseline-results.json", baseline)
        _json(original, "data/manifest.json", {"acquisition": "included local synthetic inputs; no network required",
                                               "sha256": _hashes(original, _files(original, "data"))})
        _write(original, "reproduce.py", f"PYTHON = {python!r}\n" + r'''
import json
from pathlib import Path
import subprocess

def call(*arguments):
    command = [PYTHON, "tools/run.py", *arguments]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return json.loads(result.stdout)

config = json.loads(Path("config.json").read_text())
arguments = ["init", "--project", ".", "--name", "classifier-reproduction", "--requirements", "requirements.md", "--config", "config.json"]
for filename in config["cases"].values():
    arguments.extend(["--input", filename])
for case in config["cases"]:
    arguments.extend(["--task", case])
arguments.extend(["--parent", Path("history/prior-run.txt").read_text().strip()])
run = Path(call(*arguments)["run"])
results = {}
for case in config["cases"]:
    result = call("exec", "--run", str(run), "--task", case, "--", PYTHON, "evaluate.py", "--case", case)
    attempt = run / result["attempt"]
    results[case] = json.loads((attempt / "evaluation/result.json").read_text())
    for name, kind in (("features.jsonl", "intermediate"), ("result.json", "result")):
        call("attach", "--run", str(run), "--task", case, "--kind", kind, "--file", str(attempt / "evaluation" / name))
baseline = json.loads(Path("reference/baseline-results.json").read_text())
comparison = {"run": str(run), "matches": results == baseline, "results": results}
Path("outputs").mkdir(exist_ok=True)
Path("outputs/reproduction-comparison.json").write_text(json.dumps(comparison, indent=2) + "\n")
print(json.dumps(comparison, ensure_ascii=False))
raise SystemExit(0 if comparison["matches"] else 1)
''')
        _write(original, "reproduce.md", f"""
            # 复现交付

            研究目标、指标、空输入处理见 requirements.md；设置为 seed=7、threshold=0.5。
            依赖：Python 3.10+ 标准库；记录工具的进程锁需 Linux、macOS 或 WSL。
            数据已经随项目放在 data/，取得方式与逐文件 SHA-256 见 data/manifest.json，不需要外部账户。
            代码为 evaluate.py、reproduce.py 和现有 tools/run.py。
            基准结果位于 reference/baseline-results.json，原始尝试与双日志在 history/prior-run.txt 指向的运行。

            在当前新工作目录实际执行：

            ```bash
            {shlex.quote(python)} -c 'import os,sys; print(sys.executable); print(os.getcwd())'
            {shlex.quote(python)} reproduce.py
            ```

            reproduce.py 依次冻结当前材料、建立关联新运行、执行全部三案例、归档中间产物与结果，
            再逐案例比较结果内容。命令与环境位于新运行的 attempts/，汇总在 outputs/reproduction-comparison.json。
            此项目已从先前目录迁移，先前目录不再存在；请使用本项目内代码和输入复算。
        """)
        with (original / "README.md").open("a", encoding="utf-8") as stream:
            stream.write("\n项目已携带完整复现材料迁移到当前目录，先前目录不再可用。按 `reproduce.md` 在这里实际复算并核对结果。\n")
        shutil.copytree(original, project, dirs_exist_ok=True)
        original_path = str(original)
    return {"facts": {"old_run": relative, "original_project": original_path, "original_project_removed": not Path(original_path).exists(),
                       "baseline": baseline, "comparison_file": "outputs/reproduction-comparison.json"},
            "protected": [*_files(project, relative), "reference/baseline-results.json", "data/manifest.json"]}


BUILDERS = {"C01": _c01, "C02": _c02, "C03": _c03, "C04": _c04, "C05": _c05,
            "C06": _c06, "C07": _c07, "C08": _c08, "C09": _c09, "C10": _c10,
            "C11": _c11, "C12": _c12, "C13": _c13, "C14": _c14}


def prepare_case(case_id: str, project: Path, python: str) -> dict:
    """Populate an empty project and return the prompt, private facts, and protected paths."""
    project = Path(project).resolve()
    if not project.is_dir() or any(project.iterdir()):
        raise ValueError("Case project must be an existing empty directory")
    interpreter = Path(python)
    if not interpreter.is_absolute() or not interpreter.is_file():
        raise ValueError("Use an explicit absolute Python interpreter path")
    cases = {case["id"]: case for case in json.loads(CASES.read_text(encoding="utf-8"))["cases"]}
    if case_id not in cases:
        raise ValueError(f"Unknown case: {case_id}")
    if case_id not in BUILDERS:
        raise ValueError(f"Case materials are not implemented yet: {case_id}")
    result = BUILDERS[case_id](project, python)
    result["facts"]["case_id"] = case_id
    result["facts"]["protected_sha256"] = _hashes(project, result["protected"])
    result["prompt"] = (cases[case_id]["prompt"] + "\n\n材料入口：请先读项目根目录 README.md、requirements.md 和 config.json。"
                        f"本次明确使用的 Python 解释器是 {python}，工作目录为 {project}。"
                        "请只使用这个项目的本地材料；历史产物的位置见 README.md。")
    return result
