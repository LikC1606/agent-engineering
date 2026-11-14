# Agent Engineering

用于论文相关项目的个人 agent 经验：先理解研究需求，解释具体实现，先做小规模验证，保留运行过程，排查并补齐失败任务，最后交付可复现流程。支持 Codex、Claude Code、Cursor、Google Gemini CLI 和 Google Antigravity。

与 [Agent Paper Writing](https://github.com/LikC1606/agent-paper-writing) 配合使用时，本仓库负责实验代码、运行与分析，写作仓库负责论文故事、实验论证、图表与修订。两者可在同一个研究项目中安装，也可独立使用。

## 新环境使用

需要 Git 和 Python 3.10 或更新版本；运行工具只用 Python 标准库，进程锁支持 Linux、macOS 和 WSL，原生 Windows 不在当前支持范围。先确认解释器的实际路径与工作目录，特别是机器上存在容器包装命令时：

```bash
python3 -c 'import os, sys; print(sys.executable); print(os.getcwd()); print(sys.version)'
git clone https://github.com/LikC1606/agent-engineering.git
python3 agent-engineering/tools/profile.py install --project /path/to/research-project --dry-run
python3 agent-engineering/tools/profile.py install --project /path/to/research-project
python3 agent-engineering/tools/profile.py check --project /path/to/research-project
```

将 `/path/to/research-project` 替换为实际研究项目目录。`--agents` 接受 `codex claude cursor gemini antigravity`，省略时操作全部五平台；例如 `--agents gemini antigravity` 只选择两个 Google 平台。安装范围是指定项目；下载配置仓库后，需要执行安装使其在研究项目中生效。配置不修改全局 `context.fileName`、权限、账户认证或模型设置。

安装器将核心规则直接写入共享的 `AGENTS.md`（Codex/Antigravity）、`CLAUDE.md` 命名区域及 `.cursor/rules/agent-engineering.mdc`；Gemini 的 `GEMINI.md` 使用原生相对导入引用同一规则正文。Codex、Gemini 与 Antigravity 共用 `.agents/skills`。已有规则区外的内容予以保留，备份、内容清单和安装历史位于 `.agent-experience/installations/agent-engineering/`。执行前检查项目已有规则及更具体入口；文件检查不替代客户端加载验证。

`check` 核对文件、内容和安装状态；要确认 agent 实际加载，在该研究项目中新开会话，让它说明本次任务会使用哪些规则与运行记录位置，再用小任务观察行为。Cursor 的规则入口为项目 `.mdc` 文件，技能副本仅供读取详细流程。安装副本用相对路径互相引用，便于项目整体迁移。

五平台入口、旧三平台升级、Google 客户端核对，以及两个仓库同项目使用的完整步骤见 [平台兼容说明](docs/platforms.md)。

## 经验如何组织

- [requirements.md](requirements.md) 保留 C01–C14 原始要求及已确认解释。
- [执行规则](skills/research-engineering/references/rules.md) 是各平台入口的唯一正文来源。
- [SKILL.md](skills/research-engineering/SKILL.md) 引导按场景读取工作流程与模板。
- [运行记录工具](skills/research-engineering/references/run-tool.md) 说明实际命令、快照、任务状态、产物与错误教训的保存方式。
- [lessons](lessons/) 保存有适用条件和事实依据的长期经验。

[逐条测试说明](docs/testing.md) 将 C01–C14 对应到自动行为测试和真实 agent 验收场景，并给出保留测试现场的命令。

执行前由 agent 主动核对最新要求、配置、环境和路径；会改变目标、实验有效性、成本或授权的实质歧义需要讨论。常规可逆步骤在当前授权内持续完成。

## 记录实验

已有训练、评测或批处理入口可以继续使用。记录工具包裹明确调用的命令，保存每次尝试和结果；任务调度与批量并发继续由研究项目已有实现承担。任务统计覆盖预先登记的命令任务；若命令只是提交远端作业，作业内部进度和最终结果还需从原调度器与评测产物核对。

安装后的工具位于：

```text
<研究项目>/.agent-experience/agent-engineering/tools/run.py
```

先准备任务要求文件、配置和任务清单，再按 [完整命令示例](skills/research-engineering/references/run-tool.md) 创建运行。运行记录集中在项目的 `runs/` 下。配置改变建立关联的新运行；失败补跑保留旧尝试。状态报告覆盖总数、完成、运行、错误、待运行、吞吐和预计剩余时间，并区分历史失败。

工具保存明确注册的配置和输入，记录 Git 提交、状态和补丁。复现所需的未跟踪文件、外部数据和其他依赖需要按任务登记。凭据通过认证工具或环境变量提供，在记录中说明变量名及获取方式。

## 更新、卸载与迁移

```bash
git -C agent-engineering pull --ff-only
python3 agent-engineering/tools/profile.py install --project /path/to/research-project --dry-run
python3 agent-engineering/tools/profile.py install --project /path/to/research-project
python3 agent-engineering/tools/profile.py check --project /path/to/research-project
python3 agent-engineering/tools/profile.py uninstall --project /path/to/research-project --dry-run
python3 agent-engineering/tools/profile.py uninstall --project /path/to/research-project
```

重复安装相同内容保持不变；更新与卸载前检查手动修改，发现冲突时保留现场并报告。旧三平台用户在 `git pull` 后执行默认 `install`、`check` 即加入五平台；只保留原三平台则在命令中显式加 `--agents codex claude cursor`。共享入口或技能等到最后一个使用它的平台卸载后才移除，其他 profile 的区域和历史各自保留。每次修改要求，在提交中写明条目编号、原行为、新行为和原因。

Git 仓库迁移长期规则、模板、工具及已整理经验。跨机器续跑时，还需要同步研究项目代码、运行目录、输入与外部存储索引，并重新配置账户认证。运行目录的备份位置和恢复方式写入项目复现说明；忽略入库不等于已备份。

## 验证与维护

```bash
python3 -m unittest discover -s agent-engineering/tests -v
```

测试使用临时研究项目，覆盖安装共存与历史保护，以及运行记录中的失败、补跑和配置变更。安装器 `tools/profile.py` 与写作仓库使用同一份实现，修改后同步两个副本。

规则引导判断，文件检查说明安装状态，日志与产物说明真实执行。具体验证范围见 [verification.md](verification.md)。
