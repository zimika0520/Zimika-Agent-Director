# Seedance 2.0 纯文字兼容层

本文件只覆盖 Seedance 2.0 的接口事实与计划结构。视觉单元节奏、锚点制品、表演词汇、提示词契约和执行层质检等模型无关纪律以 [ai-video-production.md](ai-video-production.md) 为准；两者冲突时，接口能力以本文件的能力快照为准，编排纪律以 ai-video-production.md 为准。

## 目的与边界

本层把已确认的制作就绪文学剧本转换成可供 Seedance 2.0 类视频模型继续执行的文字导演分镜和短生成单元。它是下游适配，不是第二次改编：不得改变人物、事件、因果、关系、知情范围、世界规则或结局。

插件只写结构化 JSON 与阅读版 Markdown：

- 不生成、编辑或读取故事板图片。
- 不调用图片或视频接口。
- 不提交视频任务，不轮询生成结果。
- 不在制品、命令输出或会话中保存 API Key、Base64、`b64_json` 或 `data:` 媒体 URI。
- 可以登记用户已有的本地路径、HTTPS URL 或平台资产 ID；不能把“需要参考图”写成“参考图已生成”。

## 能力事实与可变参数

旧试验在 2026-07-24 核验过字节 Seed 官方模型页和发布说明，并据当时可见接口制作过 4–15 秒整数任务、16:9、1080p、24fps、原生声音的样例。这些是一次能力快照，不是永久行业标准；模型 ID、时长、画幅、分辨率、声音和输入模式可能变化。

每次新项目或距离上次核验较久时，重新核对官方资料，并在 `model_profile.capability_snapshot` 记录：

- `status`：`verified` 或用户明确确认时的 `user_confirmed`。
- `checked_at`：核验日期。
- `source_urls`：至少一条字节 Seed 或火山引擎官方 HTTPS 来源。
- 当次适用的 `provider_model_id`、时长区间、画幅、分辨率、声音与输入模式。

无法核验的参数写“不清楚”，不能猜。校验器故意不把 4–15 秒或某个模型 ID硬编码为永久值，而是校验计划是否遵守当前已记录的能力快照。

实操提示：模型宣传页通常查不到时长/画幅/分辨率等参数级事实，应优先核对火山引擎 API 文档或模型服务开通页；仍核不到时，快照按 `user_confirmed` 登记用户指定值，并在 `notes` 逐项列出未核实项，不得把指定值写成 `verified`。

## 生成顺序

1. 确认当前集文学剧本和对应 `episode_boundary_review` 都是当前已确认版本。
2. 读取当前角色、场景、道具服装、台词声音和连续性规范数据。
3. 核验 Seedance 能力快照，选择纯文本或使用既有参考素材的输入模式。
4. 按场景、状态变化、主要说话人和模型单元时长拆分短单元。
5. 逐条绑定原著 `source_refs`、改编 `decision_ids` 和台词 `cue_id`。
6. 生成 `seedance_execution_plan:E001`，先保持 `awaiting_approval`。
7. 独立生成精确绑定当前计划版本的 `seedance_boundary_review:E001`。
8. 边界报告确认且结论为 `passed` 后，再确认执行计划。
9. 全集完成后运行 `validate-seedance --expected-episodes N`。

## 拆分原则

- 单元总时长必须是能力快照允许区间内的整数；模型内部镜头不硬写 `0-3秒、3-6秒`。
- 生成任务时长（能力快照约束）与视觉单元/切点节奏（编排纪律）是两个层级：一个任务内的切点数、每切点信息变化和超长单元的持续变化要求按 ai-video-production.md 执行。
- 一个短单元只有一个清楚的叙事任务，尽量减少同时清晰说话的人数。
- 长对白按语义、说话人和动作反馈拆分，不能删词、改词或重复。
- 单元必须写清 `start_state`、`end_state` 和 `continuity`；同一连续链上一单元的 `output_state` 必须等于下一单元的 `input_state`。
- 每个镜头写一种主要机位/运镜、可见动作、对白 cue 和声音；镜头表达不能新增故事事实。
- 传闻、判断、误解和未知不能用客观画面认证；需要在提示词中明确禁止闪回认证或越权揭示。
- 字幕由后期独立处理；模型提示词默认不要求生成文字、Logo或水印。

## 参考素材模式

`reference_assets` 只登记既有素材：

- `origin` 只能为 `user_provided`、`existing_project` 或 `generated_elsewhere`。
- `status` 为 `provided` 时才可以被执行单元绑定；`unbound` 只是需求占位，不能声称任务可直接提交。
- `text_to_video` 单元不得绑定参考素材。
- 非纯文本模式必须绑定已提供素材，并遵守当次能力快照支持的互斥输入规则。
- 本插件永远不使用 `generated_by_plugin` 一类来源。

## 规范 JSON 示例

```json
{
  "schema_version": 1,
  "project_id": "项目UUID",
  "episode_id": "E001",
  "generated_from": [
    {"artifact_key": "source_event_index", "version": 1},
    {"artifact_key": "story_facts", "version": 1},
    {"artifact_key": "adaptation_decision_ledger", "version": 1},
    {"artifact_key": "episode_script:E001", "version": 1},
    {"artifact_key": "episode_boundary_review:E001", "version": 1},
    {"artifact_key": "character_roster", "version": 1},
    {"artifact_key": "scene_catalog", "version": 1},
    {"artifact_key": "prop_costume_ledger", "version": 1},
    {"artifact_key": "dialogue_cue_sheet", "version": 1},
    {"artifact_key": "continuity_ledger", "version": 1}
  ],
  "model_profile": {
    "family": "Seedance 2.0",
    "provider_model_id": "当次官方或用户确认的模型ID",
    "capability_snapshot": {
      "status": "verified",
      "checked_at": "2026-07-25",
      "source_urls": ["https://seed.bytedance.com/zh/seedance2_0"]
    }
  },
  "execution_policy": {
    "generate_images": false,
    "submit_video_requests": false,
    "asset_handling": "text_only",
    "prompt_language": "zh-CN",
    "subtitle_policy": "post_production",
    "timing_policy": "unit_duration_only"
  },
  "model_constraints": {
    "unit_duration_seconds": {"min": 4, "max": 15},
    "ratio": "16:9",
    "resolution": "1080p",
    "generate_audio": true
  },
  "reference_assets": [],
  "global_constraints": ["人物、道具、知情范围和空间轴线连续"],
  "total_duration_seconds": 8,
  "units": [
    {
      "unit_id": "SD2-E001-U001",
      "sequence": 1,
      "scene_id": "1-1",
      "duration_seconds": 8,
      "source_refs": ["EV-0001"],
      "decision_ids": ["AD-0001"],
      "start_state": "人物进入当前场景",
      "end_state": "当场状态发生可见变化",
      "generation_mode": "text_to_video",
      "reference_asset_ids": [],
      "continuity": {
        "chain_id": "CHAIN-E001-S01",
        "input_state": "STATE-E001-S01-START",
        "output_state": "STATE-E001-S01-END"
      },
      "shots": [
        {
          "shot": 1,
          "camera": "固定中景",
          "visual_action": "角色完成剧本已有动作",
          "dialogue_cue_ids": ["Q-E001-S01-001"],
          "sound": ["剧本已有环境声"]
        }
      ],
      "prompt_text": "把全局约束、本单元镜头顺序、动作、原台词和声音编译成中文提示词。"
    }
  ]
}
```

## 边界报告

`seedance_boundary_review:E001` 使用与三层内容边界报告相同的四种结果：`passed`、`approved_addition`、`suspected_overreach`、`blocked`。它除绑定事件索引、事实库、决策台账、文学剧本和分集边界报告外，还必须精确绑定当前 `seedance_execution_plan:E001`。

重点检查：

- 拆镜是否把角色观点变成客观事实。
- 镜头衔接是否新增人物选择、危机、原因或结果。
- 台词是否完整、未串说话人、未改含义。
- 是否提前展示人物尚未知晓的信息。
- 参考素材是否暗含未获批准的新外形或空间事实。
- 提示词是否越过原著范围或剧本截断边界。

校验通过只代表文字兼容层达到结构、追溯和边界要求。真实 Seedance 输出效果、口型、声音、画面一致性和接口可用性均未实测，不能写成“已验证成片”。
