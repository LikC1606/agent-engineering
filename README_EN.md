<!-- README_SYNC: source=7fd318b85e92326ec475163eeda6ade99fb77dad; updated=2026-11-18 -->

[简体中文](./README.md) · English

# Agent Engineering

Install research rules and an experiment recorder into a paper project. Start with a small trial, then keep configurations, tasks, artifacts, and failed attempts with the project so you can inspect or resume a run later.

[Star the repository](https://github.com/LikC1606/agent-engineering/stargazers) to find the workflow again.

[![Stars](https://img.shields.io/github/stars/LikC1606/agent-engineering)](https://github.com/LikC1606/agent-engineering/stargazers)
[![Checks](https://github.com/LikC1606/agent-engineering/actions/workflows/check.yml/badge.svg)](https://github.com/LikC1606/agent-engineering/actions/workflows/check.yml)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB)](./tools/profile.py)
[![Issues](https://img.shields.io/github/issues/LikC1606/agent-engineering)](https://github.com/LikC1606/agent-engineering/issues)

## Install into a research project

You need Git and Python 3.10 or later. The tools use the standard library; process locking supports Linux, macOS, and WSL. Check the interpreter and its working directory if your environment wraps `python3` in a container launcher.

```bash
git clone https://github.com/LikC1606/agent-engineering.git
python3 agent-engineering/tools/profile.py install --project /path/to/research-project --dry-run
python3 agent-engineering/tools/profile.py install --project /path/to/research-project
python3 agent-engineering/tools/profile.py check --project /path/to/research-project
```

Point these commands at your project. The default targets Codex, Claude Code, Cursor, Gemini CLI, and Antigravity; `--agents gemini antigravity` selects only the two Google clients. Open a fresh client session in the project, confirm that it reads the rules, and observe a small task. The installer's `check` verifies files and installation state only.

## Capture an experiment you can inspect later

Use the [run recorder guide](./skills/research-engineering/references/run-tool.md) to prepare requirements, configuration, and a task manifest. Wrap an existing training or evaluation command with the project's `.agent-experience/agent-engineering/tools/run.py`. Attempts stay under `runs/`. A configuration change starts a linked run, and retries preserve previous attempts. Progress and throughput describe registered tasks. When a command submits work to a remote scheduler, inspect that scheduler and its artifacts for execution progress and results.

The recorder keeps the Git commit, status, patch, and registered inputs. Track uncommitted files, external data, and dependencies explicitly. Leave credential values to the environment or authentication tooling and record only the variable names and how to obtain them. Move the research project, run directory, and external storage index together.

## Rules and client adapters

| What you need | Where to look |
| --- | --- |
| The original C01–C14 agreements | [Requirements](./requirements.md) |
| How the agent should run an experiment | [Canonical rules](./skills/research-engineering/references/rules.md) · [Research Engineering Skill](./skills/research-engineering/SKILL.md) |
| Where clients load their rules | [Platform adapters](./docs/platforms.md) |
| Reusable lessons from previous runs | [Experiment lessons](./lessons/) |

Codex and Antigravity share a region in the project's `AGENTS.md`. Gemini reads the same rules through a relative import in `GEMINI.md`, and the three share a project skill directory. Claude Code and Cursor receive their own entry points from the same rule source. Installation records stay in `.agent-experience/installations/agent-engineering/`; existing project text outside managed regions and other profiles are preserved.

Install [Agent Paper Writing](https://github.com/LikC1606/agent-paper-writing) alongside this profile for manuscript arguments, figures, and revision records.

## Update and verify

After updating the source, rerun the preview, install, and check. You can also preview uninstallation:

```bash
git -C agent-engineering pull --ff-only
python3 agent-engineering/tools/profile.py uninstall --project /path/to/research-project --dry-run
python3 -m unittest discover -s agent-engineering/tests -v
```

Updates and removals flag local edits without overwriting a conflicting installation. A shared entry point stays until its last consumer is removed. Reinstalling with the defaults adds both Google clients to an older three-client setup; use `--agents codex claude cursor` to keep just the original three.

The [verification scope](./verification.md), [test instructions](./docs/testing.md), and [client behavior results](./docs/behavior-results.md) distinguish installed files, recorder behavior, and rules applied by clients. Please [open an issue](https://github.com/LikC1606/agent-engineering/issues) for reproducible problems.
