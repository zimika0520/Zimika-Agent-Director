# AI 分镜计划生成脚手架（通用）

本文件沉淀从已确认文学剧本到 `ai_shot_plan:E###` 的可复用生成流程，供不同项目复用；不包含任何具体小说的人物、台词或事件。

## 适用边界

- 生成模型无关的通用分镜计划，默认 `shot_language_contract_version: 2`。
- 不生成图片、不编译平台专属执行计划、不提交视频任务。
- 只从项目状态读取当前已确认制品，禁止针对项目硬编码人物、台词或事件 ID。

## 前置输入

以下制品必须全部为当前已确认版本：

- `project_spec`：包含 `expected_episodes`，并按需声明 `target_duration_seconds`/`duration_policy`。
- `source_event_index`：schema v2，带 `beats` 和覆盖目标集的 `episode_scopes`。
- `episode_script:E###` 与 `episode_boundary_review:E###`：目标集剧本和对应内容边界报告。
- `dialogue_cue_sheet`：`contract_version: 2`，每条口述 cue 绑定 `source_unit_id` 与 `source_locator`。
- `scene_catalog`、`character_roster`、`prop_costume_ledger`、`continuity_ledger`。
- `style_anchor`、`character_anchor:*`（v2）、`scene_anchor:*`、`prop_anchor:*`。
- `adaptation_decision_ledger`，以及目标集依赖的全剧地图、边界报告或批次大纲依据。

## 生成步骤

1. 从剧本解析场景、现场人物、动作、对白、VO/OS、道具和场尾状态。
2. 从事件索引和连续性台账建立逐场进入状态、动作链和离开状态；优先按状态变化切分单元。
3. 按台词声音表逐条且仅一次绑定 cue，保持原文，禁止改写或润色。
4. 每个单元填写 `unit_id`、`sequence`、`scene_id`、`narrative_task`、`shot_language`、`production_feasibility`、`duration_seconds`、`action_start/action_end`、`source_refs`、`source_beat_refs`、`decision_ids`、`content_atoms`、`content_bindings`、`fact_realizations`、`characters_on_screen`、`scene_anchor_ref`、`dialogue`、`space_zones`、`sound_events`、`action_flow`、`time_span_mode`、`negative_constraints`、`generation_strategy`，以及可选的状态链和跨单元续接引用。
5. 为每个单元生成通用中文提示词，注入现场人物外形锁、动作起点/终点、镜头运动、声音、对白和禁止项。
6. 分镜计划登记 `awaiting_approval` 后，先登记并确认精确绑定当前版本的 `ai_video_boundary_review:E###`，再确认分镜计划。
7. 全剧生成完成后运行 `validate-ai-shot-plans` 做覆盖和门禁复核。

## 校验与批量操作

```bash
python3 <技能目录>/scripts/project_tool.py validate-ai-shot-plans \
  <项目目录> --expected-episodes <集数>

python3 <技能目录>/scripts/project_tool.py approve-artifacts \
  <项目目录> ai_shot_plan:E001@1 ai_video_boundary_review:E001@1 ...

python3 <技能目录>/scripts/project_tool.py render-episode-deliveries \
  <项目目录> E001 E002 ...
```

`approve` 自动校验外形锁注入、台词逐条覆盖、单人对嘴、结构化状态链连续、切点时长理由、资产预算与提示词字段完整；`validate-ai-shot-plans` 只核验文字分镜、版本、内容边界和边界报告，不证明真实视频效果。

## 反模式

- 不硬编码项目人物、台词、场景或事件 ID。
- 不把边界报告结论当作事实依据；每条发现必须绑定可定位源 refs。
- 不跳过 approve 门禁直接把候选文件称为正式交付。
