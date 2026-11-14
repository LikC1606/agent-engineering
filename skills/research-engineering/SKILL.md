---
name: research-engineering
description: 在论文相关项目中实现研究代码、运行和排查实验、整理结果或交付复现流程时，落实需求对齐、小规模验证、完整运行记录、失败补齐及资源观察。普通非研究开发不主动启用。
---

# 论文实验与研究代码

使用本技能时先读 [执行规则](references/rules.md)。理解项目当前任务与最新纠正，再读对应的已有实现、任务说明和运行记录。

首次进入任务时说明研究目标、具体实现机制、输入输出及验收方式。对会改变目标、实验有效性、成本或授权的未决歧义先讨论；范围内的常规步骤持续完成。

按 [工作流程](references/workflow.md) 组织实际任务，优先复用项目的执行入口和调度器。需要记录命令及失败重跑时，读 [记录工具](references/run-tool.md)，使用随项目安装的 `.agent-experience/agent-engineering/tools/run.py`。工具的 `init` 输出是后续步骤使用的真实运行目录。

按任务需要复制模板，填写真实内容：

- [任务说明](assets/templates/task.md)：启动或接手研究代码与实验。
- [小规模验证](assets/templates/pilot.md)：扩大案例数量、预算或并发之前。
- [异常排查](assets/templates/incident.md)：错误、异常指标、未知写入结果与补跑。
- [进度汇报](assets/templates/progress.md)：长期或多任务运行。
- [复现交付](assets/templates/reproduce.md)：交付命令、输入、环境与结果。
- [经验记录](assets/templates/lesson.md)：实际错误的根因、修复与识别条件。

规则指导判断；已保存的命令、退出码、日志和产物说明真实执行结果。任务完成需要实现、相应验证、失败补齐及可定位的交付记录；依赖阻塞时明确剩余任务和缺失证据。
