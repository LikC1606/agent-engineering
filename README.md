<!-- README_SYNC: source=7fd318b85e92326ec475163eeda6ade99fb77dad; updated=2026-11-23 -->
<p align="center">简体中文 · <a href="./README_EN.md" lang="en">English</a></p>

# Agent Engineering

给论文实验项目装上一套跨五种客户端共享的研究 Agent 规则和运行记录工具：先做小规模验证，再把配置、任务清单、产物与每次失败尝试留在项目内，换机器或补跑时全程有据可查。

[![Stars](https://img.shields.io/github/stars/LikC1606/agent-engineering)](https://github.com/LikC1606/agent-engineering/stargazers)
[![Checks](https://github.com/LikC1606/agent-engineering/actions/workflows/check.yml/badge.svg)](https://github.com/LikC1606/agent-engineering/actions/workflows/check.yml)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB)](./tools/profile.py)
[![Issues](https://img.shields.io/github/issues/LikC1606/agent-engineering)](https://github.com/LikC1606/agent-engineering/issues)

如果这套可复现实验工作流对你有用，欢迎 [Star 收藏](https://github.com/LikC1606/agent-engineering/stargazers)。

## 安装到实验项目

需要 Git 和 Python 3.10 或更新版本。工具使用 Python 标准库，进程锁支持 Linux、macOS 和 WSL。若环境用同名命令包装解释器，先确认实际解释器和工作目录。

```bash
git clone https://github.com/LikC1606/agent-engineering.git
python3 agent-engineering/tools/profile.py install --project /path/to/research-project --dry-run
python3 agent-engineering/tools/profile.py install --project /path/to/research-project
python3 agent-engineering/tools/profile.py check --project /path/to/research-project
```

把示例路径换成你的研究项目。默认安装 Codex、Claude Code、Cursor、Gemini CLI 和 Antigravity 五种入口；`--agents gemini antigravity` 只选择两种 Google 客户端。安装后从研究项目新开会话，确认 Agent 实际加载了规则，再用小任务观察其行为。安装器的 `check` 只核对项目文件与安装状态。

## 让实验有记录可查

按[运行记录指南](./skills/research-engineering/references/run-tool.md)准备要求、配置和任务清单，用项目中的 `.agent-experience/agent-engineering/tools/run.py` 包裹已有训练或评测命令。每次尝试保存在 `runs/`；配置变化会新建关联运行，失败补跑保留旧尝试。进度和吞吐基于已登记任务。若命令只是提交远端作业，作业进度和结果到原调度器和评测产物核对。

记录包含 Git 提交、状态、补丁和已登记输入。未跟踪的复现文件、外部数据和依赖要按任务登记；凭据由认证工具或环境提供，运行记录只说明变量名与取得方式。迁移时一并保存研究项目、运行目录和外部存储索引。

## 查规则和平台入口

| 想了解什么 | 从这里开始 |
| --- | --- |
| 原始 C01–C14 约定 | [要求与解释](./requirements.md) |
| Agent 应怎样执行 | [规则正文](./skills/research-engineering/references/rules.md) · [Research Engineering Skill](./skills/research-engineering/SKILL.md) |
| 各客户端怎样加载 | [五平台适配](./docs/platforms.md) |
| 可复用的研究教训 | [经验条目](./lessons/) |

项目内的 `AGENTS.md` 由 Codex 和 Antigravity 共用，Gemini 从 `GEMINI.md` 相对导入同一份规则；三者共用项目技能目录。Claude Code 和 Cursor 也由同一份正文生成入口。安装历史在 `.agent-experience/installations/agent-engineering/`，项目原有的规则区外正文与其他 Profile 保留。

[Agent Paper Writing](https://github.com/LikC1606/agent-paper-writing) 负责论文论证、图表和修订记录，可以和本工具装到同一项目。

## 更新与验证

拉取源仓库更新后，重跑安装预览、安装和检查。卸载前也可预览：

```bash
git -C agent-engineering pull --ff-only
python3 agent-engineering/tools/profile.py uninstall --project /path/to/research-project --dry-run
python3 -m unittest discover -s agent-engineering/tests -v
```

发现手改冲突时保留现场；共享入口等最后一个使用平台卸载后才移除。旧三平台可按默认流程升级到五平台；要保留原三种，传入 `--agents codex claude cursor`。

[验证范围](./verification.md)、[检查方法](./docs/testing.md)和[真实客户端记录](./docs/behavior-results.md)分别说明文件安装、运行记录及客户端行为已有的证据。遇到可复现的问题，欢迎[开 Issue](https://github.com/LikC1606/agent-engineering/issues)。
