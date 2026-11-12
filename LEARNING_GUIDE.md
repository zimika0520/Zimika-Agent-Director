# Zimika Agent Director 学习路线

这份指南的目标不是背代码，而是让你能打开项目、跑通验证、解释状态机，并能现场做一个小改动。

## 先建立一句话认识

这是一个“长任务 Agent 编排器”：主任务规划工作、把独立子任务交给无历史 Worker，用文件保存任务包和检查点，再通过幂等键、租约、校验和恢复机制避免重复执行和旧结果覆盖新结果。

## 第 1 天：跑通和定位

```bash
cd Zimika-Agent-Director
python3 -m json.tool .codex-plugin/plugin.json >/dev/null
python3 skills/novel-to-script-director/scripts/test_project_tool.py
```

你要能回答：

- 项目入口在哪里？
- 插件清单为什么必须能被 JSON 解析？
- 230 项测试主要覆盖什么？

## 第 2 天：读主流程

按顺序读：

1. `skills/novel-to-script-director/SKILL.md`
2. `skills/novel-to-script-director/references/workflow.md`
3. `skills/novel-to-script-director/scripts/project_tool.py`
4. `skills/novel-to-script-director/scripts/agent_runtime.py`

重点找四个词：`task`、`attempt`、`lease`、`checkpoint`。不要一开始逐行读 6000 多行，先用搜索定位函数，再顺着调用关系读。

## 第 3 天：理解可靠性设计

自己画一张流程图，至少画出：

```text
规划任务 -> 生成任务包 -> Worker 提交结果 -> 主任务校验 -> 登记状态
                                     失败 -> 检查点 -> 受控重试
```

然后解释：

- 为什么子 Agent 不继承主任务历史？
- 为什么任务需要幂等键？
- 为什么租约过期后不能无限重试？
- 为什么旧产物必须绑定输入版本和哈希？

## 第 4 天：照着测试改一个小功能

从测试里找一个你理解的校验规则，先改测试预期，再改实现，最后运行完整测试。第一次改动建议只改提示文字、错误信息或一个最小规则，不要碰状态迁移核心。

## 第 5 天：准备面试表达

用 90 秒按这个顺序讲：

1. 业务问题：长文本生成任务耗时长，模型或进程可能中断。
2. 架构方案：主任务负责规划与验收，Worker 独立执行，文件化交接。
3. 可靠性：幂等键、租约、检查点、有限重试、版本绑定。
4. 质量门禁：结构化产物、哈希、前置条件、人工确认。
5. 验证结果：230 项自动化测试通过。

必须明确说这是基于开源项目的二次开发，不要声称从零实现全部上游代码。你的优势应该落在“能读懂、能运行、能定位、能继续改”。
