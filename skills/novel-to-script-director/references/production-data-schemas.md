# 制作提取表 JSON 契约

四类提取表以 UTF-8 JSON 为校验权威。Markdown 或 CSV 可以导出给人阅读，但不能替代 JSON。

## 原著语料库

```json
{
  "schema_version": 1,
  "project_id": "项目UUID",
  "source_units": [
    {
      "source_unit_id": "SRC-CH001",
      "source_id": "project_state.sources 中的 UUID",
      "source_locator": "第1章 / PDF第3-8页",
      "ordinal": 1,
      "content_path": "01_原著解析/标准化正文_第001章.txt",
      "content_sha256": "64位十六进制散列"
    }
  ]
}
```

`source_unit_id` 与 `ordinal` 各自唯一。`source_id` 必须存在于项目来源记录，`content_path` 必须位于项目目录内且散列匹配；同一标准化文件可以被多个不同定位单元引用，但不能省略 `source_locator`。

## 长文本动态分片计划

小说总字数不选择工作流。所有来源先按章节、场景或事件建立完整 `source_unit_id`，再按运行时提供的容量策略组合相邻单元。`source_corpus.source_units[]` 可增加 `character_count`、`estimated_tokens` 与 `complexity_points`；估算参数来自当前运行策略，不在代码中写死小说字数阈值。

分片计划使用：

```json
{
  "schema_version": 1,
  "policy": {
    "max_input_tokens": 64000,
    "reserved_output_tokens": 12000,
    "chars_per_token_estimate": 1.8,
    "max_complexity_points": 100,
    "concurrency_mode": "bounded",
    "max_parallel_tasks": "auto",
    "single_state_writer": true
  },
  "partitions": [
    {
      "partition_id": "SP001",
      "ordinal": 1,
      "source_unit_ids": ["SRC-CH001"],
      "estimated_input_tokens": 12000,
      "complexity_points": 20,
      "previous_partition_id": null,
      "next_partition_id": null
    }
  ]
}
```

示例数值不是默认值。单个来源单元超预算时，必须先按场景/事件建立新稳定ID，不得在模型调用中任意截断。并发分析分片写入 `tmp/source-analysis/<run-id>/shards/`，统一合并后才登记规范事件索引。

## 原著事件索引

```json
{
  "schema_version": 1,
  "project_id": "项目UUID",
  "generated_from": [
    {"artifact_key": "source_corpus", "version": 1}
  ],
  "units": [
    {
      "source_unit_id": "SRC-CH001",
      "source_locator": "第1章",
      "status": "ready",
      "events": [
        {
          "event_id": "EV-0001",
          "summary": "人物以行动改变了局势",
          "participants": ["C001"],
          "cause": "可核验起因",
          "action": "可核验行动",
          "outcome": "可核验结果",
          "state_change": "关系、信息、位置或风险变化",
          "source_refs": ["SRC-CH001:P003-P005"]
        }
      ]
    }
  ]
}
```

`status` 只能为 `ready`、`excluded` 或 `failed`。`excluded` 必须提供 `exclusion_reason`，`failed` 必须提供 `error_reason`；存在 `failed` 时不能确认。`source_unit_id` 与 `event_id` 各自唯一。

## 改编变更授权记录

只有需要用户确认的主要新增或故事事实改动才创建：

```json
{
  "schema_version": 1,
  "project_id": "项目UUID",
  "generated_from": [
    {"artifact_key": "project_spec", "version": 1},
    {"artifact_key": "story_facts", "version": 1},
    {"artifact_key": "adaptation_profile", "version": 1}
  ],
  "authorizations": [
    {
      "authorization_id": "AUTH-0001",
      "category": "new_relationship",
      "approved_change": "用户明确批准的具体改动",
      "rationale": "为什么需要该改动",
      "scope": "E010-E018",
      "constraints": "不得改变原著结局和人物核心动机",
      "user_confirmation_quote": "可回查的用户确认原话",
      "approved_by": "用户"
    }
  ]
}
```

`category` 只能为 `named_character`、`merge_character`、`new_subplot`、`new_relationship`、`new_ability`、`new_major_event`、`reorder_key_event`、`change_motivation`、`change_choice`、`change_cause`、`change_outcome`、`change_world_rule`、`change_ending_nature` 或 `hook_crisis`。授权内容、范围、约束、确认原话和确认人均不能为空。普通流程确认不能替代这份授权。

## 改编决策台账

```json
{
  "schema_version": 1,
  "project_id": "项目UUID",
  "generated_from": [
    {"artifact_key": "source_event_index", "version": 1},
    {"artifact_key": "story_facts", "version": 1},
    {"artifact_key": "adaptation_profile", "version": 1},
    {"artifact_key": "adaptation_bible", "version": 1}
  ],
  "decisions": [
    {
      "decision_id": "AD-0001",
      "operation": "compress",
      "source_unit_ids": ["SRC-CH001"],
      "target_episode_ids": ["E001"],
      "boundary_class": "auto_allowed",
      "change_level": "expression_only",
      "source_fact_change": false,
      "rationale": "合并重复说明但保留因果与人物选择",
      "protected_facts": ["FACT-001"],
      "character_arc_impact": "不改变人物动机",
      "continuity_impact": "时间线不变",
      "alternative": "保留为两场会造成同功能重复",
      "status": "accepted"
    }
  ]
}
```

`operation` 只能为 `preserve`、`compress`、`merge`、`reorder`、`omit`、`bridge_addition`、`psychology_externalization`、`scene_transition`、`time_compression`、`action_completion`、`crowd_environment_reaction`、`dramatic_expansion`、`named_character`、`merge_character`、`new_subplot`、`new_relationship`、`new_ability`、`new_major_event`、`change_motivation`、`change_choice`、`change_cause`、`change_outcome`、`change_world_rule`、`change_ending_nature` 或 `hook_crisis`。`source_based` 使用 `no_change`；`auto_allowed` 使用 `expression_only`，且两者都必须绑定至少一个 `source_unit_id`。无原著单元依据时只能走 `user_confirmation_required` 与有效授权。桥接新增还必须提供 `addition_basis`、`purpose` 和 `source_facts_unchanged: true`。

自动允许项必须是 `boundary_class: auto_allowed`、`change_level: expression_only`、`source_fact_change: false`、`status: accepted`，并绑定原著依据。需要确认或改变故事事实的决策必须是 `boundary_class: user_confirmation_required`、`status: approved_addition`，并以 `authorization_ref` 绑定当前有效授权。

核心原则是“可以增加表达，不得擅自增加故事事实”。找不到原著依据且没有授权的内容不能登记为自动允许；也不能用桥接、戏剧化或钩子名义改变人物选择、事件原因或结果。

## 三层内容边界报告

全剧地图、批次大纲和每集剧本先以 `awaiting_approval` 登记，再分别生成 `series_boundary_review`、`batch_boundary_review` 和 `episode_boundary_review`。三类报告使用相同结构：

```json
{
  "schema_version": 1,
  "project_id": "项目UUID",
  "review_target": {
    "artifact_key": "episode_script:E001",
    "version": 2
  },
  "automation_limitations": "自动核对只能发现证据缺失和明显冲突，不能保证百分之百判断正确。",
  "generated_from": [
    {"artifact_key": "source_event_index", "version": 1},
    {"artifact_key": "story_facts", "version": 1},
    {"artifact_key": "adaptation_decision_ledger", "version": 2},
    {"artifact_key": "episode_script:E001", "version": 2}
  ],
  "findings": [
    {
      "finding_id": "BR-E001-001",
      "category": "psychology_externalization",
      "location": "E001 / 1-1",
      "description": "心理描写外化为人物藏起钥匙的可见动作",
      "evidence": "动作不改变人物选择、原因或结果",
      "result": "passed",
      "source_refs": ["SRC-CH001:P003-P005"],
      "decision_ids": ["AD-0001"]
    }
  ],
  "conclusion": "passed"
}
```

`review_target` 必须与报告制品状态中绑定的唯一目标制品键和版本完全一致；报告还必须绑定当前原著事件索引、故事事实库和改编决策台账。每条发现必须使用校验器支持的 `category`，且 `result` 只能是：

- `passed`：必须有非空 `source_refs`。
- `approved_addition`：必须有 `decision_ids` 与精确 `authorization_refs`，且对应决策为 `approved_addition` 并带同一有效 `authorization_ref`。
- `suspected_overreach`：必须写 `human_judgment_required: true`。
- `blocked`：原著冲突或未经批准的主要新增。

有任一 `blocked` 时结论为 `blocked`；否则有任一 `suspected_overreach` 时为 `needs_human_review`；其余为 `passed`。前两种结论都阻止目标稿确认。报告必须明确自动判断局限，不能声称百分之百正确。

`category` 分为三组：原著直接保留使用 `source_fidelity`；自动表达变化使用 `psychology_externalization`、`scene_transition`、`time_compression`、`action_completion`、`crowd_environment_reaction` 或 `dramatic_expansion`，此时 `passed` 还必须以 `decision_ids` 绑定同类型 `auto_allowed` 决策；需授权的故事事实变化使用变更授权支持的类别。硬冲突使用 `major_character_change`、`identity_change`、`ability_change`、`core_relationship_change`、`motivation_change`、`key_event_change`、`causality_change`、`world_rule_change`、`ending_nature_change`、`premature_knowledge_disclosure` 或 `missing_source_or_authorization`，只能输出 `suspected_overreach` 或 `blocked`。

## 开发阶段审核报告

全剧规划审核和试写审核都使用相同问题结构，但 `review_target` 与依赖不同：

```json
{
  "schema_version": 1,
  "project_id": "项目UUID",
  "review_target": "series_plan",
  "generated_from": [
    {"artifact_key": "series_map", "version": 1}
  ],
  "issues": [
    {
      "issue_id": "DEV-001",
      "severity": "blocking",
      "location": "E003",
      "evidence": "可核验的制品内容",
      "suggestion": "返修建议",
      "status": "resolved"
    }
  ],
  "conclusion": "passed"
}
```

`severity` 只能为 `blocking`、`major` 或 `minor`，`status` 只能为 `open`、`resolved` 或 `waived`。`waived` 必须提供 `waiver_id`、`reason` 和 `approved_by`。有 `blocking/open` 时结论不能为 `passed`。

## 项目规格

最终交付使用的项目规格必须是规范 JSON，至少包含：

```json
{
  "schema_version": 1,
  "project_id": "项目UUID",
  "expected_episodes": 60,
  "target_duration_seconds": 90,
  "duration_policy": {
    "tolerance_ratio": 0.2,
    "dialogue_chars_per_second": [3.5, 4.5],
    "inflation_redline_ratio": 0.3
  },
  "target_runtime": "每集目标时长或内容量（人工备注，不参与校验）",
  "handoff_target": "可直接进入导演拆镜"
}
```

`expected_episodes` 必须是大于 0 的整数。`validate-handoff` 和 `build-handoff` 的同名参数只能与已确认项目规格核对，不得用较小参数绕过全剧集数。

`target_duration_seconds` 是可选的单集目标时长覆盖值，必须是大于 0 的整数秒。未声明时使用默认 60 秒；声明后以项目值为权威。AI 分镜计划必须写出当前生效值，剧本校验也据此给出对白秒数预警。默认建议约 15 个分镜单元，该数量仅用于规划提示，不作为机械阻断门禁。

`duration_policy` 可选，用于覆盖推算参数，缺省值见下；非法值会被拒绝确认。

- `tolerance_ratio`：分镜计划单元合计时长的允许偏差，0 到 1 之间，缺省 `0.1`（±10%）。
- `dialogue_chars_per_second`：中文配音字/秒推算区间 `[下限, 上限]`，必须递增且为正数，缺省 `[3.5, 4.5]`。该区间是样本推算值，不是行业标准，仅作预警。
- `inflation_redline_ratio`：防扩写红线，0 到 1 之间，缺省 `0.3`。

`target_runtime` 是人工备注自由文本，不参与任何机器校验，保留仅为兼容旧项目。

## 全剧分集地图

全剧分集地图也以规范 JSON 为最终交付权威，至少包含：

```json
{
  "schema_version": 1,
  "project_id": "项目UUID",
  "expected_episodes": 60,
  "episodes": [
    {"episode_id": "E001", "title": "集标题"}
  ]
}
```

`expected_episodes` 必须与项目规格和交付命令一致，`episodes` 必须从 `E001` 到 `EN` 逐集覆盖且无重复。每集记录仍按 `SeriesMap` 契约补齐目标、状态、冲突、行动、变化、来源和钩子。

全剧地图登记后保持 `awaiting_approval`，直到精确绑定当前版本的 `series_boundary_review` 结论为 `passed`。批次大纲和每集剧本分别遵守同样的 `batch_boundary_review`、`episode_boundary_review` 前置门禁。

## 通用顶层

```json
{
  "schema_version": 1,
  "project_id": "项目UUID",
  "generated_from": [
    {"artifact_key": "episode_script:E001", "version": 1},
    {"artifact_key": "episode_boundary_review:E001", "version": 1}
  ],
  "entity_resolution": {
    "decisions": [],
    "conflicts": []
  },
  "records": []
}
```

四类制作提取表的 `generated_from` 必须精确绑定全部当前已确认剧本版本及各自一一对应的已确认 `episode_boundary_review`；制品状态 `depends_on` 必须使用完全相同的版本集合。`records` 中的集号、场号、人物和文本必须能回查这些剧本。缺一集、缺一份边界报告或绑定旧版本都不能确认。

`entity_resolution.decisions` 记录别名归一、复用或拆分稳定 ID 的人工决定；`conflicts` 记录尚未解决的同名不同人、别名冲突、地点定义冲突或物品归属冲突。存在未解决冲突时不能通过交付校验。

## 角色提取表

```json
{
  "character_id": "C001",
  "name": "角色名",
  "aliases": [],
  "identity": "身份",
  "dramatic_function": "剧情功能",
  "voice_and_performance": "语言与表演约束",
  "appearance_facts": [],
  "states": [],
  "appearances": [
    {"episode_id": "E001", "scene_id": "1-1", "entry_state": "", "exit_state": ""}
  ],
  "knowledge_state": [],
  "source_refs": []
}
```

必填：`character_id`、`name`、`appearances`。角色 ID 和姓名唯一。

## 场景提取表

```json
{
  "scene_id": "1-1",
  "episode_id": "E001",
  "location_id": "L001",
  "location_name": "地点",
  "time": "日",
  "space": "外",
  "zones": [],
  "fixed_elements": [],
  "character_ids": ["C001"],
  "item_ids": ["P001"],
  "entry_state": "入场状态",
  "exit_state": "离场状态",
  "reuse_notes": ""
}
```

必填：`scene_id`、`episode_id`、`location_id`、`location_name`、`time`、`space`、`character_ids`、`item_ids`、`entry_state`、`exit_state`。每个剧本场次必须且只能对应一条记录。

## 道具服装台账

```json
{
  "item_id": "P001",
  "name": "道具或服装名",
  "aliases": [],
  "category": "prop",
  "appearance_facts": [],
  "dramatic_function": "",
  "appearances": [
    {"episode_id": "E001", "scene_id": "1-1", "holder": "C001", "state": "完好"}
  ],
  "changes": [],
  "final_state": "",
  "source_refs": []
}
```

`category` 只能为 `prop` 或 `costume`。必填：`item_id`、`name`、`category`、`appearances`。ID、名称和别名必须唯一；剧本道具名称必须精确命中名称或别名。

## 台词声音表

```json
{
  "schema_version": 1,
  "contract_version": 2,
  "generated_from": [
    {"artifact_key": "source_corpus", "version": 1},
    {"artifact_key": "source_event_index", "version": 1},
    {"artifact_key": "episode_script:E001", "version": 1},
    {"artifact_key": "episode_boundary_review:E001", "version": 1}
  ],
  "records": [{
    "cue_id": "Q-E001-S01-001",
    "episode_id": "E001",
    "scene_id": "1-1",
    "speaker_id": "C001",
    "speaker_name": "角色名",
    "type": "dialogue",
    "delivery_mode": "on_screen",
    "text": "原著中的逐字对白",
    "source_unit_id": "SRC-CH001",
    "source_locator": "CH001-P023",
    "source_beat_refs": ["B-E001-023"],
    "context": "当场目的或声音语境",
    "performance_note": ""
  }]
}
```

`type` 只能为 `dialogue`、`vo`、`os`、`environment` 或 `sfx`。台词声音表必须直接依赖当前 `source_corpus`、`source_event_index`、分集剧本和对应边界报告。必填：`cue_id`、`episode_id`、`scene_id`、`type`、`text`。对白、VO、OS 还必须提供 `speaker_id`、`speaker_name`、`delivery_mode`、`source_unit_id`、`source_locator` 和 `source_beat_refs`。

## 双向追溯

- 场景表必须覆盖全部剧本场次，不能缺场或多场。
- 台词声音表必须覆盖剧本中全部对白、VO 和 OS，并使用 `contract_version: 2`。口述 cue 必须提供 `text`、`source_unit_id`、`source_locator`、`source_beat_refs`，其中 `text` 必须逐字存在于绑定原著单元，beat 必须属于当前集明确允许范围，定位必须命中 beat 来源，台词顺序不得倒退；不得包含 `source_text`、`delivered_text`、`preservation_mode`、`adaptation_note`、语义分数、改写审批或对白新增事实字段。
- 场景表引用的角色 ID 必须存在于角色表，物品 ID 必须存在于道具服装台账。
- 角色和物品的每条 `appearances` 必须指向存在的剧本场次。
- 提取表出现剧本没有的集号、场号、台词或角色时判为阻断。
- 场景表的 `location_name`、`time`、`space` 必须与对应剧本场头一致；同一 `location_id` 不能绑定互相冲突的地点名称或空间定义。

## 连续性台账

```json
{
  "schema_version": 1,
  "project_id": "项目UUID",
  "generated_from": [
    {"artifact_key": "episode_script:E001", "version": 1},
    {"artifact_key": "episode_boundary_review:E001", "version": 1}
  ],
  "records": [
    {
      "episode_id": "E001",
      "scene_id": "1-1",
      "character_states": {"C001": "院门外；未受伤；身份未暴露"},
      "item_states": {"P001": "由C001持有且完好；服装无变化"},
      "relationship_state": {"C001-C002": "公开对立"},
      "knowledge_state": {"C001": ["知道钥匙来源"]},
      "unresolved_threads": ["管家仍堵门", "官差敲门尚未揭示来意"],
      "storyline_progress": {"main": "守钥匙冲突升级"},
      "relative_time": "同日白天",
      "end_state": "C001守住钥匙，但官差到场使风险升级"
    }
  ]
}
```

台账的 `generated_from` 和制品 `depends_on` 必须精确绑定全部当前分集剧本，以及与每集当前版本匹配、已经确认的 `episode_boundary_review`。顶层必须使用 `records`，逐场覆盖，不能缺场、多场或出现空对象占位。每条必须包含且不得留空：`episode_id`、`scene_id`、`character_states`、`item_states`、`relationship_state`、`knowledge_state`、`unresolved_threads`、`storyline_progress`、`relative_time`、`end_state`。不得用 `scenes`、`knowledge_states`、`relationship_changes` 等旧字段替代。

## 质检报告

质检报告同样使用规范 JSON：

```json
{
  "schema_version": 1,
  "project_id": "项目UUID",
  "generated_from": [
    {"artifact_key": "episode_script:E001", "version": 1},
    {"artifact_key": "character_roster", "version": 1}
  ],
  "issues": [
    {
      "issue_id": "QA-001",
      "episode_id": "E001",
      "scene_id": "1-1",
      "category": "continuity",
      "severity": "blocking",
      "evidence": "可核验的剧本原句或状态冲突",
      "suggestion": "返修建议",
      "blocking": true,
      "status": "resolved"
    }
  ],
  "conclusion": "passed"
}
```

`generated_from` 必须精确绑定全部当前分集剧本、四类提取表和连续性台账。每集剧本必须已通过对应边界报告，四类提取表和连续性台账也已把这些报告纳入自身来源依赖，因此质检可以沿依赖链追溯。`status` 只能为 `open`、`resolved` 或 `waived`；`waived` 必须提供 `waiver_id`，并在制作就绪复核报告中登记同一豁免。只要仍有 `blocking: true` 且状态不是 `resolved` 或 `waived`，结论不能为 `passed`。质检豁免不能替代改变故事事实所需的用户授权。

## 制作就绪复核报告

```json
{
  "schema_version": 1,
  "project_id": "项目UUID",
  "generated_from": [
    {"artifact_key": "episode_script:E001", "version": 1},
    {"artifact_key": "character_roster", "version": 1},
    {"artifact_key": "scene_catalog", "version": 1},
    {"artifact_key": "prop_costume_ledger", "version": 1},
    {"artifact_key": "dialogue_cue_sheet", "version": 1},
    {"artifact_key": "continuity_ledger", "version": 1},
    {"artifact_key": "quality_report", "version": 1}
  ],
  "checks": {
    "script_structure": "passed",
    "semantic_quality": "passed",
    "episode_coverage": "passed",
    "breakdown_traceability": "passed",
    "continuity": "passed"
  },
  "runtime_verification": {
    "status": "not_measured",
    "note": "尚未完成配音实读，不声称时长已达标"
  },
  "unresolved_blockers": [],
  "waivers": [],
  "conclusion": "ready"
}
```

`generated_from` 必须绑定全部分集剧本、四类提取表、连续性台账和质检报告的当前确认版本。复核时还要沿这些制品的依赖检查三层边界报告均为当前版本、无疑似或阻断项，且所有已批准新增都可追溯至用户授权。`runtime_verification.status` 只能是 `measured` 或 `not_measured`。如有豁免，每条至少包含 `waiver_id`、`reason` 和 `approved_by`，且不得用豁免掩盖未授权的版权或事实问题。

## Seedance 2.0 纯文字执行层

用户明确要求模型兼容时，按 [seedance-compatibility.md](seedance-compatibility.md) 生成 `seedance_execution_plan:E001` 和对应 `seedance_boundary_review:E001`。该制品独立于文学剧本和四类制作提取表，固定禁止图片生成、视频提交、API Key、Base64 和 data URI；实际模型参数使用带日期与官方来源的能力快照，不硬编码成永久标准。

## v0.6 扩展字段（可选，出现即校对）

**角色语言指纹**（角色提取表 records 内，服务“对白像不像这个人”）：

```json
"voice_fingerprint": {
  "catchphrases": [{"text": "口头禅原文", "source_ref": "SRC-CH001"}],
  "speech_style": "短句、反问多、从不用敬语",
  "behavior_patterns": ["紧张时摸袖口"],
  "taboo_words": ["不会说网络流行语"]
}
```

每项特征必须带可定位原著佐证；写剧本与对白审核时注入。无原文依据的特征不得填写。

**事件约束分级**（原著事件索引 events 内，供边界审查与决策台账直接消费）：

```json
"adaptation_constraint": {
  "level": "immutable | adjustable | expendable",
  "note": "为何是该级别（如：结局性质依赖此事件因果）"
}
```

- `immutable`：核心因果/结局性质依赖，任何改动都需用户授权。
- `adjustable`：可压缩、可调序、可合并，表达层自由。
- `expendable`：可删除，删除时在决策台账记录影响。

**伏笔生命周期**（连续性台账内）：

```json
"foreshadowings": [{
  "hook_id": "FS-001",
  "origin": {"episode_id": "E001", "scene_id": "1-2"},
  "content": "钥匙柄内侧的刻字",
  "status": "open | progressing | resolved",
  "expected_payoff": {"episode_id": "E012"},
  "source_ref": "EV-0007"
}]
```

质检阶段核对健康度：临近 `expected_payoff` 仍为 `open` 的伏笔、已 `resolved` 又被重复揭示的伏笔，均列入质检报告；全剧交付前不允许存在计划内未回收且无处理说明的伏笔。

**全局滚动摘要** `rolling_summary`：按批次登记新版本的 Markdown/文本制品，建议 ≤2000 字；是有损压缩的工作记忆，事实以事件索引与连续性台账为准，冲突时以后者纠正摘要。


## 通用语义追踪与制作可执行性（schema v2）

- `source_event_index` 的 schema v2 必须为事件和 beat 提供唯一顺序，并通过 `episode_scopes` 声明每集按原著顺序声明无重复的 `allowed_beat_ids`，并使首尾 beat 与该列表一致。
- AI 分镜单元必须使用 `source_beat_refs`，顺序不得倒退或越过当前集来源边界；引用 beat 的 `protected_fact_ids` 必须进入 `preserved_fact_ids`。
- 新增事实必须写入 `new_fact_claims` 并绑定有效改编决策，不能用布尔值自报“忠实”。
- 台词声音表用 `delivery_mode` 区分 `on_screen`、`off_screen`、`voice_over`、`phone_audio`、`screen_video`；非现场人物不得进入 `characters_on_screen`。
- 每个分镜单元必须提供 `action_flow`、`time_span_mode` 和完整 `shot_language`。动作前置状态、最短时长、对白字数和屏幕文字后期方案由工具实际校验。
- 边界报告的最终结论由目标制品的机器校验结果计算；报告自填 `passed` 不能覆盖阻断错误。

### 人物三视图锚点v2与分镜镜头语言v2

`character_anchor:<角色ID>` 的新交付格式使用 `contract_version: 2`，分开保存 `source_appearance`、`visual_design` 与 `turnaround_prompt`。自动补齐的五官、发型、体型和服装属于视觉设计，不得伪装成原著事实，也不得暗示未公开身份、关系、能力或经历。

角色提取表 `appearances[]` 增加 `presence_mode: on_screen | voice_only | crowd_group`。

新逐集交付要求 `ai_shot_plan.shot_language_contract_version: 2`。每个 `units[]` 继续使用现有 `shot_language`，但其中两个字段升级为：

```json
{
  "shot_language": {
    "shot_size": {"start": "medium_shot", "end": "close_up"},
    "camera_movement": {
      "type": "push_in",
      "subject": "C001",
      "description": "从人物腰部中景缓慢推近至面部近景，最终停在她握紧的手机上"
    },
    "camera_angle": "平视",
    "composition": "人物位于画面左侧",
    "visual_focus": "手机",
    "transition": "动作衔接"
  }
}
```

旧字符串格式继续可读；只有新 `render-episode-delivery` 交付要求v2结构。

### 分镜空间、声音与跨集续接硬契约

- `source_event_index` schema v2 顶层必须包含 canonical `entities`；事件 `participants` 只能引用已登记的 character ID。台词 `speaker_id`、现场人物、屏幕人物和状态链人物必须沿用同一 ID。
- 严格分镜单元必须使用 `space_zones`；每名现场人物必须绑定当前单元的 `space_id`，两辆车、现场与设备屏幕不得合并成同一空间。
- 严格分镜单元使用结构化 `sound_events`，每条声音必须绑定 `space_id` 且 `scope: unit`。电话或屏幕视频台词必须绑定当前单元的 device sound event，禁止无生命周期的整场广播。
- 同集 `tail_frame_chain` 必须绑定紧邻上一单元；跨集首镜必须绑定上一集已确认分镜计划的最后一个单元。第一集首镜不得使用上一集尾帧。
- 正式配音 cue 禁止 `20XX`、`TBD`、`TODO`、`FIXME` 和待定类占位符。

### 剧情内容原子、必要事实与故事时间轴

`source_event_index` schema v2 必须使用 `content_contract_version: 1`。每个 beat 必须提供：

- `content_atoms`：逐字来自原著的剧情内容原子；`text` 必须等于 `source_excerpt`，且摘录必须存在于绑定 `source_corpus` 单元。
- `required_fact_ids`：当前 beat 出现时必须由可见或可听载体表达的身份、年龄、关系、因果或知情变化事实。
- 可选 `story_time`：涉及明确时间关系时记录整数 `day_index` 与规范 `day_part`。

顶层 `fact_definitions` 负责定义必要事实及其 `source_beat_ids`；顶层 `temporal_constraints` 用原著逐字时间表达绑定 anchor/target beat。工具从“同日、次日、后天、N天后”等表达确定性计算天数，不接受模型自报偏移量。

严格分镜和Seedance执行单元必须使用 `content_atoms` 与 `content_bindings`：

- 剧情字段只能逐字编译自来源 beat 的 source atom，或逐字来自已接受改编决策的 `authorized_content`。
- `narrative_task`、`action_start`、`action_end`、动作步骤、屏显、Seedance `start_state/end_state/visual_action/prompt_text` 不得继续作为无来源自由文本。
- `new_fact_claims: []` 不能证明没有新增事实；没有合法 atom 和 binding 的剧情字段直接阻断。

每集必要事实由 `episode_scope.allowed_beat_ids` 中全部 beat 的 `required_fact_ids` 自动合并。分镜通过 `fact_realizations` 将事实绑定到真实 `dialogue_cue`、`action_step`、`state_change` 或 `screen_text`；不存在的载体不计入覆盖。

AI视频执行计划必须用 `content_atom_refs` 无遗漏消费绑定分镜单元的 atoms。`prompt.action`由 atoms 编译，人物只能来自绑定分镜，环境没有环境atom时固定使用场景锚点，`prompt_text`必须等于 `prompt_compiler_version: 1` 的确定性编译结果。
