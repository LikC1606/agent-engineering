#!/usr/bin/env python3
"""Record explicit research commands and their evidence; no scheduler or retries."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import time
import uuid

try:
    import fcntl
except ImportError:
    fcntl = None


def now():
    return datetime.now(timezone.utc).isoformat()


def identity():
    return uuid.uuid4().hex[:12]


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def write_json(path, data):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


@contextmanager
def lock(path, *, blocking=True):
    if fcntl is None:
        raise RuntimeError("Process locks require Linux, macOS, or WSL; native Windows is not supported.")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        flags = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
        try:
            fcntl.flock(stream.fileno(), flags)
        except BlockingIOError:
            raise ValueError(f"Task is already running: {path.stem}") from None
        try:
            yield stream
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def append_record(path, data, lock_path=None):
    path = Path(path)
    with lock(lock_path or path.with_suffix(".lock")):
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(data, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())


def records(run):
    with lock(run / "events.lock"):
        path = run / "events.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def event(run, event_type, **fields):
    data = {"id": identity(), "time": now(), "event": event_type, **fields}
    append_record(run / "events.jsonl", data, run / "events.lock")
    return data


def load_run(path):
    run = Path(path).expanduser().resolve()
    data = json.loads((run / "run.json").read_text(encoding="utf-8"))
    if data.get("run_id") != run.name or run.parent.name != "runs":
        raise ValueError("Keep a run inside its project's runs/ directory, with its original name.")
    return run, data, run.parent.parent


def check_task(data, task):
    if task not in data["tasks"]:
        raise ValueError(f"Unknown task {task!r}; registered tasks: {', '.join(data['tasks'])}")


def checked_file(raw, project):
    path = Path(raw).expanduser()
    path = (project / path).resolve() if not path.is_absolute() else path.resolve()
    if not path.is_file():
        raise ValueError(f"Expected a file: {path}")
    return path


def snapshot_file(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as src, target.open("xb") as dst:
        shutil.copyfileobj(src, dst)
    return {"sha256": digest(target), "bytes": target.stat().st_size}


def git_snapshot(project, destination):
    destination.mkdir()
    paths = [".", ":(exclude)runs", ":(exclude).agent-experience"]
    commands = {
        "root": ["rev-parse", "--show-toplevel"],
        "head": ["rev-parse", "HEAD"],
        "status": ["status", "--porcelain=v1", "--untracked-files=all", "--", *paths],
        "worktree.patch": ["diff", "--binary", "--", *paths],
        "staged.patch": ["diff", "--cached", "--binary", "--", *paths],
    }
    summary = {}
    for name, arguments in commands.items():
        argv = ["git", "-C", str(project), *arguments]
        try:
            result = subprocess.run(argv, capture_output=True, check=False)
            output, error, code = result.stdout, result.stderr, result.returncode
        except OSError as exc:
            output, error, code = b"", str(exc).encode(), 127
        (destination / name).write_bytes(output)
        (destination / (name + ".stderr")).write_bytes(error)
        summary[name] = {"argv": argv, "exit_code": code}
    write_json(destination / "commands.json", summary)


def environment(project):
    return {
        "recorded_at": now(), "hostname": socket.gethostname(),
        "platform": platform.platform(), "python": sys.executable,
        "python_version": sys.version, "project": str(project),
        "tool_cwd": str(Path.cwd().resolve()), "cpu_count": os.cpu_count(),
        "load_average": list(os.getloadavg()) if hasattr(os, "getloadavg") else None,
        "disk_free_bytes": shutil.disk_usage(project).free,
    }


def initialize(args):
    if fcntl is None:
        raise RuntimeError("Use Linux, macOS, or WSL; native Windows process locks are not supported.")
    project = Path(args.project).expanduser().resolve()
    if not project.is_dir():
        raise ValueError(f"Project directory does not exist: {project}")
    if not args.name.strip():
        raise ValueError("Run name must not be empty.")
    if len(args.task) != len(set(args.task)):
        raise ValueError("Task IDs must be unique.")
    for task in args.task:
        if not re.fullmatch(r"[\w][\w.-]{0,79}", task):
            raise ValueError(f"Invalid task ID: {task!r}")
    sources = [("requirements", checked_file(args.requirements, project))]
    if not sources[0][1].read_text(encoding="utf-8").strip():
        raise ValueError("Requirements must not be empty.")
    sources += [("config", checked_file(item, project)) for item in args.config]
    sources += [("input", checked_file(item, project)) for item in args.input]
    if len({path for _, path in sources}) != len(sources):
        raise ValueError("Snapshot source paths must be unique.")
    parent = None
    if args.parent:
        parent_run, parent_data, _ = load_run(args.parent)
        parent = {"run_id": parent_data["run_id"], "original_path": str(parent_run)}
    slug = re.sub(r"[^\w.-]+", "-", args.name).strip(".-")[:48] or "run"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    run = project / "runs" / f"{stamp}-{slug}-{identity()}"
    run.mkdir(parents=True, exist_ok=False)
    snapshots = []
    for index, (kind, source) in enumerate(sources):
        target = run / "snapshots" / f"{index:03d}-{source.name}"
        details = snapshot_file(source, target)
        relative = str(source.relative_to(project)) if source.is_relative_to(project) else None
        snapshots.append({"kind": kind, "source": str(source), "project_relative": relative,
                          "snapshot": str(target.relative_to(run)), **details})
    data = {"run_id": run.name, "name": args.name, "goal": args.goal or args.name,
            "created_at": now(), "original_project": str(project), "parent": parent,
            "tasks": args.task, "snapshots": snapshots,
            "credential_environment_names": args.env_name}
    write_json(run / "run.json", data)
    write_json(run / "environment.json", environment(project))
    git_snapshot(project, run / "source")
    (run / "reproduce.md").write_text(
        "# 复现记录\n\n"
        "run.json 保存目标、任务和输入快照；source/ 保存 Git commit、状态与两份补丁。\n"
        "未跟踪代码只列入 Git 状态；复现必需的文件应作为 --input 显式快照或先纳入版本管理。\n"
        "attempts/ 各次 command.json 的 argv 为实际命令，cwd 为工作目录；stdout/stderr 与 result.json 保留执行结果。\n"
        "commands.jsonl 按开始时间汇总命令。不得将并发开始顺序误当成完整任务依赖。\n"
        "凭据通过环境注入，记录仅保存变量名。迁移整个项目可保留项目内相对路径；外部路径变化需新建关联运行。\n",
        encoding="utf-8")
    event(run, "initialized", tasks=args.task)
    return {"run": str(run), "run_id": run.name, "tasks": args.task}


def validate_snapshots(run, data, project):
    for item in data["snapshots"]:
        source = project / item["project_relative"] if item["project_relative"] is not None else Path(item["source"])
        frozen = run / item["snapshot"]
        if not frozen.is_file() or digest(frozen) != item["sha256"]:
            raise ValueError(f"Saved snapshot changed or is missing: {frozen}")
        if not source.is_file() or digest(source) != item["sha256"]:
            raise ValueError(f"{item['kind']} changed or is missing: {source}; create a new run, optionally with --parent.")


def task_events(items, task):
    return [item for item in items if item.get("task") == task and item["event"] in {"started", "finished"}]


def stop_child(process):
    if process.poll() is not None:
        return
    os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()


def execute(args):
    run, data, project = load_run(args.run)
    check_task(data, args.task)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        raise ValueError("Provide a command after --.")
    if args.timeout is not None and args.timeout <= 0:
        raise ValueError("Timeout must be positive.")
    cwd = Path(args.cwd).expanduser() if args.cwd else project
    cwd = (project / cwd).resolve() if not cwd.is_absolute() else cwd.resolve()
    if not cwd.is_dir():
        raise ValueError(f"Working directory does not exist: {cwd}")
    with lock(run / "locks" / f"{args.task}.lock", blocking=False) as held:
        validate_snapshots(run, data, project)
        history = task_events(records(run), args.task)
        if history and history[-1]["event"] == "started":
            if not args.retry_uncertain or not args.note:
                raise ValueError("Previous attempt has an unknown outcome. Inspect its logs and effects, then use --retry-uncertain --note REASON if a retry is appropriate.")
        if history and history[-1].get("exit_code") == 0:
            raise ValueError("Task is already complete; use a new run for a new execution.")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        attempt = run / "attempts" / args.task / f"{stamp}-{identity()}"
        attempt.mkdir(parents=True, exist_ok=False)
        started = now()
        executable = shutil.which(command[0])
        if os.sep in command[0]:
            candidate = Path(command[0])
            executable = str((cwd / candidate).resolve() if not candidate.is_absolute() else candidate.resolve())
        description = {"task": args.task, "attempt": str(attempt.relative_to(run)),
                       "started_at": started, "argv": command, "display_command": shlex.join(command),
                       "cwd": str(cwd), "resolved_executable": executable,
                       "run": str(run), "note": args.note, "retry_uncertain": args.retry_uncertain,
                       "timeout_seconds": args.timeout,
                       "injected_environment": {"AGENT_RUN_DIR": str(run), "AGENT_ATTEMPT_DIR": str(attempt)}}
        write_json(attempt / "command.json", description)
        write_json(attempt / "environment.json", environment(project))
        git_snapshot(project, attempt / "source")
        append_record(run / "commands.jsonl", description)
        event(run, "started", task=args.task, attempt=description["attempt"])
        child_env = os.environ.copy()
        child_env.update(description["injected_environment"])
        failure = None
        process = None
        interrupted = False
        before = time.monotonic()
        with (attempt / "stdout.log").open("xb") as out, (attempt / "stderr.log").open("xb") as err:
            try:
                process = subprocess.Popen(command, cwd=cwd, env=child_env, stdout=out, stderr=err,
                                           start_new_session=True, pass_fds=(held.fileno(),))
                write_json(attempt / "process.json", {"pid": process.pid, "controller_pid": os.getpid(), "started_at": now()})
                code = process.wait(timeout=args.timeout)
            except subprocess.TimeoutExpired:
                stop_child(process)
                code, failure = 124, "Command exceeded its explicit timeout; its process group was stopped."
            except KeyboardInterrupt:
                if process is not None:
                    stop_child(process)
                code, failure, interrupted = 130, "Execution interrupted; inspect logs and external effects before retrying.", True
            except OSError as exc:
                if process is not None:
                    stop_child(process)
                code, failure = (127 if isinstance(exc, FileNotFoundError) else 126), str(exc)
            if failure:
                err.write((failure + "\n").encode("utf-8"))
        result = {"task": args.task, "attempt": description["attempt"], "started_at": started,
                  "finished_at": now(), "elapsed_seconds": time.monotonic() - before,
                  "exit_code": code, "state": "completed" if code == 0 else "error",
                  "failure": failure, "interrupted": interrupted,
                  "logs": {name: {"path": f"{description['attempt']}/{name}.log",
                                   "sha256": digest(attempt / f"{name}.log")}
                           for name in ("stdout", "stderr")}}
        write_json(attempt / "result.json", result)
        event(run, "finished", **result)
    return result, (128 - code if code < 0 else code)


def report(args):
    run, data, project = load_run(args.run)
    items = records(run)
    states = {}
    for task in data["tasks"]:
        history = task_events(items, task)
        state = {"state": "pending", "attempt": None}
        if history:
            latest = history[-1]
            state["attempt"] = latest["attempt"]
            if latest["event"] == "finished":
                state.update(state="completed" if latest["exit_code"] == 0 else "error",
                             exit_code=latest["exit_code"])
            else:
                try:
                    with lock(run / "locks" / f"{task}.lock", blocking=False):
                        state.update(state="error", reason="unknown outcome: no completion record and no active task lock")
                except ValueError:
                    state["state"] = "running"
        states[task] = state
    counts = {state: sum(value["state"] == state for value in states.values())
              for state in ("completed", "running", "error", "pending")}
    counts["total"] = len(states)
    starts = [datetime.fromisoformat(item["time"]) for item in items if item["event"] == "started"]
    terminal = [datetime.fromisoformat(item["time"]) for item in items if item["event"] == "finished"]
    end = max(terminal) if terminal and counts["completed"] == counts["total"] else datetime.now(timezone.utc)
    elapsed = max(0.0, (end - min(starts)).total_seconds()) if starts else 0.0
    speed = counts["completed"] / elapsed if elapsed > 0 else None
    remaining = counts["total"] - counts["completed"]
    eta = None
    note = "unknown: need at least two completed tasks and no unresolved errors"
    if remaining == 0:
        eta, note = 0.0, "all tasks complete"
    elif counts["completed"] >= 2 and counts["error"] == 0 and speed:
        eta, note = remaining / speed, "estimate from completed tasks / elapsed wall time; includes running tasks"
    return {"run": str(run), "project": str(project), "counts": counts, "tasks": states,
            "historical_failed_attempts": sum(item["event"] == "finished" and item["exit_code"] != 0 for item in items),
            "unknown_tasks": sum("reason" in state for state in states.values()),
            "elapsed_seconds": elapsed, "throughput_tasks_per_second": speed,
            "speed_basis": "completed tasks / wall time since the first attempt, including failed attempts and waiting",
            "eta_seconds": eta, "eta_note": note,
            "artifacts": [item for item in items if item["event"] == "artifact"]}


def attach(args):
    run, data, project = load_run(args.run)
    if args.task:
        check_task(data, args.task)
    source = checked_file(args.file, project)
    relative = Path("intermediate" if args.kind == "intermediate" else "results") / f"{identity()}-{source.name}"
    details = snapshot_file(source, run / relative)
    return event(run, "artifact", task=args.task, kind=args.kind, original_path=str(source),
                 path=str(relative), note=args.note, **details)


def lesson(args):
    run, data, project = load_run(args.run)
    if args.task:
        check_task(data, args.task)
    for name in ("condition", "cause", "fix", "prevent"):
        if not getattr(args, name).strip():
            raise ValueError(f"Lesson {name} must not be empty.")
    entry = {"id": identity(), "time": now(), "run_id": data["run_id"],
             "run_relative": str(run.relative_to(project)), "task": args.task,
             **{name: getattr(args, name) for name in ("condition", "cause", "fix", "prevent")},
             "evidence": args.evidence}
    path = project / ".agent-experience" / "lessons.jsonl"
    append_record(path, entry)
    return {"lesson": entry, "path": str(path)}


def parser():
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="action", required=True)
    init = commands.add_parser("init", help="Freeze requirements, configuration, inputs, and task IDs.")
    init.add_argument("--project", required=True)
    init.add_argument("--name", required=True)
    init.add_argument("--goal")
    init.add_argument("--requirements", required=True)
    init.add_argument("--config", action="append", required=True)
    init.add_argument("--input", action="append", default=[])
    init.add_argument("--task", action="append", required=True)
    init.add_argument("--parent")
    init.add_argument("--env-name", action="append", default=[], help="Record a credential variable NAME, never its value.")
    execute_parser = commands.add_parser("exec", help="Run one explicit task command and preserve its attempt.")
    execute_parser.add_argument("--run", required=True)
    execute_parser.add_argument("--task", required=True)
    execute_parser.add_argument("--cwd")
    execute_parser.add_argument("--note")
    execute_parser.add_argument("--timeout", type=float)
    execute_parser.add_argument("--retry-uncertain", action="store_true")
    execute_parser.add_argument("command", nargs=argparse.REMAINDER)
    status = commands.add_parser("status", help="Report every registered task and evidence-based throughput.")
    status.add_argument("--run", required=True)
    artifact = commands.add_parser("attach", help="Copy an intermediate/result file into the run and index its hash.")
    artifact.add_argument("--run", required=True)
    artifact.add_argument("--kind", choices=("intermediate", "result"), required=True)
    artifact.add_argument("--file", required=True)
    artifact.add_argument("--task")
    artifact.add_argument("--note")
    lessons = commands.add_parser("lesson", help="Append a scoped lesson to the project's persistent history.")
    lessons.add_argument("--run", required=True)
    lessons.add_argument("--task")
    for name in ("condition", "cause", "fix", "prevent"):
        lessons.add_argument("--" + name, required=True)
    lessons.add_argument("--evidence", action="append", default=[])
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.action == "exec":
            result, code = execute(args)
        else:
            handler = {"init": initialize, "status": report, "attach": attach, "lesson": lesson}[args.action]
            result, code = handler(args), 0
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return code
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
