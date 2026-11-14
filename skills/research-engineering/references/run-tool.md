# 实验记录工具

`tools/run.py` 使用 Python 3.10+ 标准库，支持 Linux、macOS 和 WSL。进程锁依赖 `fcntl`，原生 Windows 不在当前支持范围。解释器由调用者明确选择；在新环境先确认它实际使用的机器、目录和依赖。

安装到论文相关项目后，入口为 `.agent-experience/agent-engineering/tools/run.py`。以下 `python3` 指已检查过的解释器。工具保存明确指定的命令，不安排任务、调整并发或自动重试。

## 冻结任务和设置

先填写任务要求及配置。相对输入路径相对于 `--project`，配置和输入均可重复指定。任务 ID 必须预先完整登记，并且不能重复。

```bash
python3 .agent-experience/agent-engineering/tools/run.py init \
  --project . --name pilot --goal '验证两个输入案例的实际行为' \
  --requirements research/task.md --config research/config.json \
  --input research/cases.json --task case-1 --task case-2 \
  --env-name MODEL_API_KEY
```

命令以 JSON 返回绝对 `run` 路径。每次调用建立新的 `runs/<UTC时间>-<名称>-<唯一标识>/`，同名运行也保留历史。`run.json` 保存目标、任务、来源及哈希；`snapshots/` 保存要求、配置和输入文件。大型数据集可提供带版本与哈希的数据清单作为输入文件，并在复现说明中记录取回办法。

`source/` 保存 Git commit、状态、未暂存补丁和已暂存补丁，不递归归档 `runs/` 或 `.agent-experience/`。未跟踪代码只列在 Git 状态里；复现必需的未跟踪文件应先纳入版本管理，或通过 `--input` 明确快照。没有 Git 时保存失败命令及原因，不能声称源码已归档。

## 执行一个任务

```bash
python3 .agent-experience/agent-engineering/tools/run.py exec \
  --run /absolute/project/runs/<run-id> --task case-1 \
  --note '读取案例，按声明的参数执行并验证输出' \
  -- python3 experiments/evaluate.py --case case-1
```

每次执行前检查要求、配置、输入源文件及其保存快照。内容变化或缺失会拒绝执行旧运行；使用新的 `init`，可加 `--parent /absolute/old-run` 关联旧设置。实现错误修复后的明确补跑也保存各次 Git 状态与补丁，便于区分修复前后的代码。

命令直接作为参数数组执行，不经过额外 shell。默认工作目录为研究项目；`--cwd` 可以指定其他明确目录。子进程获得 `AGENT_RUN_DIR`、`AGENT_ATTEMPT_DIR` 两个输出位置变量。若需要 shell 语法，应明确以 `bash -lc '...'` 等命令执行，具体参数照实保存。

每次尝试保存在独立 `attempts/<task>/<UTC时间>-<唯一标识>/`：

- `command.json`：完整参数数组、便于阅读的命令、工作目录、解析后的命令路径、说明和时间。
- `environment.json`、`source/`：本次机器、工具解释器、目录、资源概况及 Git 状态。
- `process.json`：该次直接子进程和控制进程信息，用于定位，不把历史 PID 当成恢复依据。
- `stdout.log`、`stderr.log`、`result.json`：原始输出、退出码、时长、错误与日志哈希。

所有开始记录追加到 `commands.jsonl`，任务状态追加到 `events.jsonl`。不同任务可以由已有调度器并行调用；同一任务持有进程锁，重复启动会拒绝。已完成任务也会拒绝重复执行，新实验应新建运行。

非零退出不会自动重试。定位原因、修复后，对同一失败任务再次调用 `exec`，新 attempt 保留旧失败证据。可用 `--timeout 秒数` 明确限制运行；超时停止该命令的进程组、留下证据并返回 124。

控制进程意外退出时，直接子进程继续持有任务锁，避免它尚在执行时重复启动。缺少完成记录且锁已释放的任务报告为“结果未知”，不会冒充成功。检查日志和具体外部效果之后，确认适合重跑才使用 `--retry-uncertain --note '检查依据及重跑理由'`。工具不能判断远端写操作是否完成。

## 记录中间产物、结果与经验

```bash
python3 .agent-experience/agent-engineering/tools/run.py attach \
  --run /absolute/project/runs/<run-id> --task case-1 \
  --kind result --file outputs/scores.csv --note '两案例正式结果'

python3 .agent-experience/agent-engineering/tools/run.py lesson \
  --run /absolute/project/runs/<run-id> --task case-1 \
  --condition '某类输入缺少标签时' --cause '读取逻辑默认标签存在' \
  --fix '按输入协议处理缺失标签并补跑' --prevent 'pilot 包含缺标签案例' \
  --evidence attempts/case-1/<attempt-id>/stderr.log
```

`attach` 将文件复制到 `intermediate/` 或 `results/`，使用独立名称，保存原路径、哈希和说明；原文件之后变化不影响旧快照。脚本产生的文件须显式登记，工具不假定任意命令的所有输出位置。

`lesson` 仅追加到项目 `.agent-experience/lessons.jsonl`，关联运行和可选任务、证据位置。经验注明适用条件，不能因一次错误把新限制扩大到所有任务。通用经验经整理后再回填经验仓库；运行数据和项目经验需要随研究项目备份。

## 进度与恢复

```bash
python3 .agent-experience/agent-engineering/tools/run.py status \
  --run /absolute/project/runs/<run-id>
```

输出覆盖所有登记任务，分别给出总数、完成、运行、当前错误和待运行数量；历史失败 attempt 另计，修复成功后不再占当前错误数。吞吐按“完成任务 / 首次尝试以来的实际墙钟时间”计算，包含失败和等待时间。预计剩余时间包含运行中任务；完成样本不足两项或有未解决错误时返回 `null` 并说明原因，不编造估计。

`reproduce.md` 指向来源快照、Git 状态、各次命令、日志和结果。补齐任务特有的数据取回、依赖安装与验证步骤；命令开始顺序不等于完整任务依赖。整个项目迁移后，项目内输入按相对路径核对；项目外来源位置发生变化时建立关联新运行。

配置和命令参数不得包含密钥；使用环境变量注入凭据，`--env-name` 只保存变量名。工具不转储环境，但子命令主动输出的内容会照实进入日志，因此须避免在子命令中打印凭据。Git 补丁和显式输入也会照实保存，仅登记适合保留的项目文件。
