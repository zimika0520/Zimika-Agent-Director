# 非现场声音解析 v0.8.6 热修复实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复文学剧本中“非现场人物、电话声音、VO/OS/画外音”声明与对白解析不一致，确保全部口述 cue 被统计并通过合法说话人校验。

**Architecture:** 保留现场人物 `characters` 作为空间/出镜语义；新增独立非现场说话人声明解析，并将两者合并为合法 `declared_speakers`。对白解析返回 canonical speaker、注释和文本，声明行在进入对白解析前显式排除；电话声音映射为 `phone_audio`，OS/画外音映射为 `off_screen`。

**Tech Stack:** Python 3、`unittest`、Codex 本地 Marketplace 插件缓存。

## Global Constraints

- 不修改 `/Users/shinchan/Desktop/小说/温夜有染_AI导演项目` 的任何生产制品或状态。
- 保持现场人物与非现场人物语义分离，非现场人物不得进入 `characters_on_screen`。
- 保持已有 `scene_end_state_unmarked` 审批阻断规则。
- 发布为 `0.8.6`，创建新缓存目录，禁止覆盖 `0.8.5`。

---

### Task 1: 文学剧本解析回归测试

**Files:**
- Modify: `skills/novel-to-script-director/scripts/test_project_tool.py`

- [ ] 增加真实格式夹具：现场温喻、王警官电话声音、祈星染 OS。
- [ ] 断言声明行不计入对白、三句电话对白全部计入、总 cue 数为9。
- [ ] 断言非现场说话人合法但不进入现场人物列表。
- [ ] 运行新增测试并确认在旧实现上失败。

### Task 2: 声明与对白解析修复

**Files:**
- Modify: `skills/novel-to-script-director/scripts/project_tool.py`

- [ ] 新增非现场人物声明正则与声明行排除规则。
- [ ] 扩展对白注释支持电话声音并提取 annotation。
- [ ] 合并现场与非现场合法说话人，仅将现场人物写入场景索引。
- [ ] 增加 delivery mode 解析并保持原 cue type 兼容。
- [ ] 运行新增测试确认转绿。

### Task 3: 版本、文档和发布

**Files:**
- Modify: `.codex-plugin/plugin.json`
- Modify: `CHANGELOG.md`
- Modify: `README.md`
- Modify: `skills/novel-to-script-director/SKILL.md`
- Modify: `skills/novel-to-script-director/references/script-format-and-quality.md`

- [ ] 将版本升级到 `0.8.6`。
- [ ] 明确文学剧本的现场/非现场声明与电话声音格式。
- [ ] 更新完整测试数量和变更记录。

### Task 4: 验证、同步和缓存隔离

- [ ] 运行165项原测试和新增测试。
- [ ] 用真实 E001 v2 运行 `validate-script`，确认只剩 `scene_end_state_unmarked`。
- [ ] 验证源码、Git提交、远端 main 与 v0.8.6 缓存文件哈希一致。
- [ ] 卸载/重装本地插件，确认 `codex plugin list` 显示0.8.6。
- [ ] 给生产会话一段只从 `episode_script:E001@2` 继续的明确话术。
