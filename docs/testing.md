# 如何验证 14 条实验与代码要求

测试分三类：工具行为、原文与安装完整性、真实 agent 场景。自动测试的通过范围以具体断言为准。原文保留和完整安装不代表 agent 一定遵循；诊断、复用和研究判断还需查看真实操作。

## 运行自动测试

先确认实际解释器及工作目录，再在本仓库运行：

```bash
python3 -c 'import os, sys; print(sys.executable); print(os.getcwd()); print(sys.version)'
python3 -m unittest discover -s tests -v
```

当前全仓 57 项：原有 38 项工具、安装和约定测试，加上 10 项真实场景材料测试及 9 项验收运行器测试。场景材料测试会实际制造空输入失败、设置变化、错误数据划分和迁移环境；运行器测试使用本地进程核对超时、日志、历史保护和评审状态，不冒充真实模型。

测试默认使用自动清理的临时项目。需要保留配置、命令、日志、失败与结果时，选择一个全新的统一输出目录：

```bash
mkdir -p /absolute/evidence/new-round
PROFILE_TEST_ARTIFACT_DIR=/absolute/evidence/new-round/profile \
RUN_TEST_ARTIFACT_DIR=/absolute/evidence/new-round/run \
AGENT_TEST_ARTIFACT_DIR=/absolute/evidence/new-round/agent \
python3 -m unittest discover -s tests -v \
  > /absolute/evidence/new-round/unittest.log 2>&1
```

每个案例使用唯一子目录；`cli-calls.jsonl` 保存 CLI 参数、退出码和输出，研究运行保留原生快照与 attempts。两个仓库的 `test_profile.py`、`test_requirement_contract.py` 保持相同；后者读取各自的真实 profile 与要求，避免只测虚构规则。

## 逐条覆盖

以下方法名位于 `tests/test_run.py`，另有说明的除外。每条都有 [真实 agent 场景](../tests/fixtures/requirements.json)。

| 条目 | 自动测试实际验证什么 | 仍需观察 agent 的行为 |
| --- | --- | --- |
| C01 理解需求 | 原文和规则完整传递 | 面对会改变指标定义的歧义，先澄清再实现 |
| C02 解释实现 | 原文和规则完整传递 | 解释实际数据流、机制、输入输出与验收 |
| C03 执行前对齐 | `test_requirement_change_after_first_task_requires_linked_new_run`；缺输入、缺快照、未登记任务均拒绝 | 把最新对话纠正保存到要求与配置 |
| C04 先小规模 | 原文和规则完整传递 | 选择代表案例，检查实际内容后再扩大 |
| C05 完整记录 | `test_command_record_preserves_exact_argv_and_log_hashes`；中间产物与结果快照；缺失输入拒绝 | 所有相关命令经记录入口执行，所有产物显式登记 |
| C06 保留历史 | `test_repeated_intermediate_and_result_attachments_keep_prior_bytes`；新旧运行及失败/修复源码各自留存 | 不在工具外覆盖旧文件，比较时说明设置差异 |
| C07 环境与路径 | `test_explicit_cwd_and_output_environment_match_saved_paths`；整项目迁移后仍可运行 | 检查具体机器、包装命令或容器的实际行为 |
| C08 修复并补跑 | `test_progress_reports_every_state_and_eta_after_failure_repair`；原失败日志、源码补丁和重试保留 | 定位根因、实施修复、识别受影响结果 |
| C09 观察后扩容 | 原文和规则完整传递；记录基础资源信息 | 实际观察资源、网络与接口；决定并发及回退 |
| C10 完整进度 | 同时存在完成/运行/错误/待运行时精确计数；修复后 ETA 包括运行中任务，保留历史失败 | 定期汇报，并核对远端批任务内部状态 |
| C11 查执行过程 | 日志和每次源码状态可追溯 | 找到异常的实际原因，确认后才讨论随机性 |
| C12 复用实现 | 原文和规则完整传递 | 先搜索已有入口，解释确有必要的新改动 |
| C13 记录教训 | `test_incomplete_lesson_never_appends_a_partial_record`；经验跨运行追加保留 | 从实际错误提取经验，后续任务读取并应用 |
| C14 完整复现 | `test_recorded_command_can_reproduce_result_from_saved_input`；真实安装副本可迁移，历史补丁保留 | 补齐具体依赖、数据取回及任务依赖顺序，实际核对复算 |

`test_requirement_contract.py` 检查原文逐条保留、全部规则原样进入五平台文件、技能资源齐全、更新留存历史，以及移走原经验源码后安装副本仍可检查和运行。Gemini 检查的是实际相对导入目标；这里不模拟或声称真实模型加载。

## 真实 agent 场景怎么使用

`tests/fixtures/requirements.json` 中每个案例包含原始条目、准备条件 `setup`、用户输入 `prompt`、通过条件 `pass_if`、失败条件 `fail_if` 和证据 `evidence`。这些是可复用的验收案例，尚不作为自动模型评分。

1. 为选定案例创建独立的可丢弃研究项目，按 `setup` 准备真实文件和已知故障，记录初始哈希；先使用少量案例。
2. 从本仓库安装目标平台规则，执行 `check`。在该项目新开目标客户端会话，只发送 `prompt`，评分条件留给检查者。
3. 保存完整回复、工具轨迹、命令、日志和前后 diff。用实际文件检查 `pass_if` 与 `fail_if`，不按关键词命中数评分。
4. 逐项记录通过、失败或未验证及证据路径。缺少客户端、未查看页面或任务依赖阻塞时不能填通过；修复后新建轮次，保留原失败。

同一案例可分别在 Codex、Claude Code、Cursor、Gemini CLI 和 Antigravity 执行。这里的本地 unittest 不发起模型请求，不消耗远端实验预算，也不把 14 个场景的定义当成 14 次已完成的行为实测。

## 准备、执行与登记真实客户端验收

`tests/agent_projects.py` 为 C01–C14 生成自包含的合成研究项目。评分条件和已知答案放在项目目录外；项目中提供真实数据、已有入口与必要历史。C11 明确是同一组给定预测的评测路由回归，提供不同样本 ID，并授权发现错误后修复重算；不暗示存在未提供的增强模型。

```bash
python3 tests/agent_harness.py prepare --case C08 --client claude \
  --output-root /absolute/private-evidence/new-round \
  --companion /absolute/agent-paper-writing
python3 tests/agent_harness.py run --run /absolute/private-evidence/new-round/准备输出的目录 \
  --timeout 240 --budget 1
```

`--companion` 可选，用于在同一项目加载两套约定。准备阶段保存运行器与场景源码、安装输出、提示、初始哈希和完整 `before/`；执行阶段保存精确客户端命令、版本、cwd、双日志、源码、最终清单及受保护文件变化。默认沿用客户端现有认证和模型，不复制凭据或修改全局账户。模型请求会使用实际客户端服务；应先小规模验证，并自行选择时限及预算。Claude 的 `--budget` 是该次调用上限；其他客户端继续使用自身设置。

正常退出只得到 `awaiting_review`。检查者查看原始工具轨迹、实际结果和 diff 后，填写生成的 `review-template.json`，另存为 `completed-review.json`：每个条件都必须给出 `pass`、`fail` 或 `unverified`、具体说明及本轮真实证据文件的相对路径。

```bash
python3 tests/agent_harness.py review --run /absolute/private-evidence/new-round/准备输出的目录 \
  --record /absolute/private-evidence/new-round/准备输出的目录/completed-review.json
```

登记结果同时保留 `criteria_status` 和 `execution_status`。全部条目满足但调用超时或触及预算时，整体仍为 `unverified`；受保护历史改变时整体为 `failed`。不会为保存中断评审而要求检查者虚构某一条失败。已执行轮次不能原地重跑；修复后创建新轮，保留旧失败。人工提示后续跑须标明辅助续跑，不能计作独立首次通过。

Codex、Claude、Gemini 和 Antigravity 有显式命令适配；Cursor 需用 `--command-json` 提供已核实的客户端参数数组。文件安装适配与真实模型行为的验证范围分别见 [验证记录](../verification.md)。这些目录提供合成测试隔离，不替代客户端自身的权限和沙箱。
