#

## 长文本分片与人物视觉锚点补充契约

- 小说总字数不得触发单独流程；章节/事件为主边界，Token和复杂度只作容量上限。
- 并发工作者只能写独立临时分片，不能同时修改 `project_state.json`、全局时间线、连续性台账或同一人物锚点。
- `plan-source-partitions` 与 `merge-source-analysis-shards` 均不修改项目状态；合并后的规范文件由单一写入者串行登记。
- 人物锚点v2是DOCX、HTML和视频提示词共同视觉权威；同一角色不得在不同文件中重新生成外形。
- 逐集交付绑定当前 `episode_script:E001`、对应边界报告、角色提取表、人物锚点v2、`ai_shot_plan:E001`及对应边界报告。纯排版重导出不改变剧情制品版本。 制作就绪剧本制品契约

## 原著语料库 `SourceCorpus`

规范 JSON 记录全部可定位原著单元。每个单元至少包含稳定 `source_unit_id`、来源文件 ID、章节/页码/段落定位、标准化文本文件或片段引用、文本散列和顺序号。扫描或提取失败必须保留异常记录，不能从单元列表中消失。

## 来源策略 `SourcePolicy`

项目状态顶层 `source_policy` 包含 `source_kind`、`official_review_enabled`、`official_url` 和固定的 `content_authority: uploaded_files`。旧项目缺字段时按 `self_owned`、关闭审核读取。

- `self_owned`：自营小说，上传文件直接作为依据。
- `storyline`：故事线、梗概或大纲，上传内容是唯一依据。
- `published_novel`：已发表小说，默认直接运行；只有用户主动开启时才能登记 HTTP/HTTPS `official_url`。

`init` 和 `add-source` 不检查缺章、乱码、截断或完整度，也不生成入料体检。上传文件始终保留原样并以散列登记。

## 来源官网审核 `SourceReview`

可选制品键 `source_review`，只允许用于已主动开启官网审核的 `published_novel` 项目。规范 JSON 必须包含当前全部 `uploaded_source_ids`、与来源策略一致的 `official_url`、`checked_at`、标题/作者/章节覆盖/样本内容四项检查、证据、自动化局限和 `matched|partial|mismatch|inconclusive` 结论。

审核只读取用户指定页面，不自行搜索、下载或替换正文。该制品不进入阶段完成或交付强制依赖，任何结论都不阻塞后续工作流。

## 原著事件索引 `SourceEventIndex`

顶层包含 `schema_version`、`project_id`、精确的 `generated_from`、`units` 和 `upgrade_pending`。每个 `SourceCorpus` 单元必须且只能出现一次：

- `source_unit_id` 与可回查定位。
- `status`：`ready`、`excluded` 或 `failed`。
- `granularity`：`unit_detail` 或 `chapter_summary`。旧索引缺少该字段和顶层 `upgrade_pending` 时按 `unit_detail` 兼容读取。
- `unit_detail` 的 `events`：稳定 `event_id`、事件摘要、参与者、起因、行动、结果、状态变化与原著引用。
- `chapter_summary` 的 `events`：稳定 `event_id`、事件摘要与原著引用；允许暂缺起因、行动、结果和状态变化。
- `excluded` 必须提供 `exclusion_reason`；`failed` 必须提供 `error_reason`。

`upgrade_pending` 必须无重复地精确列出全部 `chapter_summary` 单元，不能漏列或多列。事件索引只有在没有 `failed` 单元、没有缺失或重复单元，且所有 `excluded` 都有明确理由时才能确认。粗粒度只用于分阶段建索引，不能绕过 `SourceCorpus` 全覆盖；事件摘要不能替代后续读取原文。

## 故事事实库

每个原著单元使用稳定 `source_unit_id`，记录文件、章节/页码/段落、摘要和可定位引用。人物、事件、地点、关系和时间线使用稳定 ID。

事实库区分：`source_fact`、`inference`、`unknown`、`adaptation_addition`。新增内容不得写回原著事实。

## 项目规格 `ProjectSpec`

最终交付以规范 JSON 为权威，必须包含 `schema_version`、`project_id` 和大于 0 的 `expected_episodes`，用来锁定全剧完整性。

- 目标用途与交付对象
- 受众平台（如用户指定）
- 总集数、单集目标时长或内容量。用户未指定时按单集约 60 秒、上下浮动 10%、约 15 个分镜单元规划；项目规格可用 `target_duration_seconds`（正整数秒）和 `duration_policy` 显式覆盖。
- 改编尺度与来源说明
- 可选 `rights_mode`：`owned`（默认，自有版权）、`licensed`（第三方授权，可用可选字符串 `rights_note` 记录授权范围）或 `unclear`。缺省字段按 `owned` 语义处理，旧规格不需要补字段。非法枚举值会被校验器拒绝确认；`unclear` 不阻塞，只在 `show`/`approve` 时提示用户确认权利状态一次。权利状态只登记用户声明，插件不联网检索正文、不外部核实、不等待授权。
- 必须保留、允许调整、禁止改变
- 交付语言、格式和制作就绪验收条件
- 用户硬性要求与待确认项

## 改编定位卡 `AdaptationProfile`

- 受众方向及依据
- 主、副题材
- 核心情绪回报与故事卖点
- 主角、关系和基调模式
- 优先强化、需要压缩和谨慎改写内容
- 已确认改编边界

## 改编变更授权记录 `ChangeAuthorization`

只有确实需要改变故事事实或加入主要内容时才创建。规范 JSON 顶层包含 `schema_version`、`project_id`、精确的 `generated_from` 和非空 `authorizations`。每条授权至少记录：

- 唯一 `authorization_id`。
- `category`：新命名角色、合并角色、新支线、新关系、新能力、新重大事件、关键事件调序、改变动机/选择/原因/结果/世界规则/结局性质，或新增钩子危机中的一种。
- `approved_change`、`rationale`、适用 `scope` 和不得越过的 `constraints`。
- 可回查的 `user_confirmation_quote` 与 `approved_by`。

用户对当前流程说“继续”不等于批准改变故事事实。授权范围必须具体；后续决策超出授权范围时仍按未经批准处理。

## 改编圣经 `AdaptationBible`

- 世界观与不可变规则
- 人物欲望、恐惧、能力、语言风格、人物弧和关系节点
- 主线、支线、感情线和阶段目标
- 地点、道具、服装、伏笔及回收计划
- 不可变事实、获准调整项、改编新增项
- 全剧时间线

## 改编决策台账 `AdaptationDecisionLedger`

规范 JSON 顶层包含 `schema_version`、`project_id`、精确 `generated_from` 和 `decisions`。每条决策至少包含：

- 稳定 `decision_id`。
- `operation`：保留、压缩、合并、调序、删除、桥接，以及心理外化、场景衔接、时间压缩、动作补全、群众/环境反应、原著事件戏剧化展开或需要用户确认的主要改动类型。对白不属于改编操作，直接引用原著语料。
- 对应 `source_unit_ids` 与 `target_episode_ids`。
- `rationale`、`protected_facts`、人物弧影响、因果/连续性影响和替代方案。
- `boundary_class`：原著直接保留用 `source_based`，只增加表达用 `auto_allowed`，改变故事事实用 `user_confirmation_required`。
- `change_level`：对应使用 `no_change`、`expression_only` 或 `story_fact_change`；另以布尔值 `source_fact_change` 明确是否改变故事事实。
- 自动允许的表达操作使用 `status: accepted`。需要用户确认或改变故事事实的操作使用 `status: approved_addition`，并以 `authorization_ref` 绑定有效 `ChangeAuthorization`。

核心原则是“可以增加表达，不得擅自增加故事事实”。自动允许项必须同时满足 `change_level: expression_only` 与 `source_fact_change: false`，并绑定可定位原著依据。`bridge_addition` 必须填写 `addition_basis`、`purpose` 和 `source_facts_unchanged: true`；如果找不到原著依据、承担新剧情功能或改变选择/原因/结果，就不再是自动桥接，必须先获用户授权。引用未知原著单元、越过项目禁改项、落点超出计划集数或缺少所需授权时不能确认。

## 全剧分集地图 `SeriesMap`

最终交付以规范 JSON 为权威，顶层 `expected_episodes` 必须与项目规格一致，`episodes` 必须完整覆盖 `E001...EN`。顶层 `granularity` 使用 `full` 或 `backbone`；旧地图缺字段时按 `full` 读取。

v0.8 轻量 `backbone` 使用 `contract_version: 2`，每集只强制合法 `episode_id` 与非空 `summary`。`goal`、`core_conflict`、`source_hint`、`end_hook` 是推荐字段，缺少时输出警告但不阻塞。旧 backbone 可读取，但再次确认、批次细化或交付前必须升级。详细原著范围和节拍不在骨架层强制。

先列剧情弧，再逐集记录：

- `episode_id`、集号、标题
- 本集目标与开场状态
- 核心冲突、关键行动和局势变化
- 信息释放与人物变化
- 前集承接、后集推动
- 集尾钩子
- 原著 `source_unit_id`
- 改编 `decision_id`
- 改编新增及用途

全剧地图对改编决策的引用必须双向一致：台账写入某集的决策要出现在该集 `decision_ids`，地图不能引用不存在的决策。

地图生成后先登记 `awaiting_approval`，不得直接确认。只有精确绑定当前地图版本的 `SeriesBoundaryReview` 结论为 `passed`，且其他规划审核也通过时，地图才可确认。

## 三层内容边界报告 `SeriesBoundaryReview` / `BatchBoundaryReview` / `EpisodeBoundaryReview`

三种规范 JSON 使用同一发现结构，分别精确绑定一个当前 `series_map`、`batch_outline` 或 `episode_script`；同时绑定当前原著事件索引、故事事实库和改编决策台账。顶层至少包含：

- `schema_version`、`project_id`。
- 与状态依赖完全一致的 `review_target: {artifact_key, version}`。
- `automation_limitations`：说明自动判断不能保证百分之百正确。
- 非空 `findings` 与由发现项推导出的 `conclusion`。

每条发现至少包含唯一 `finding_id`、规则 `category`、目标稿 `location`、`description`、可核验 `evidence` 和 `result`：

- `passed`：必须提供非空 `source_refs`，证明有明确原著依据。
- `approved_addition`：必须提供 `decision_ids` 和精确的 `authorization_refs`；对应决策必须为 `approved_addition`，并绑定同一有效用户授权。
- `suspected_overreach`：证据不足且必须人工判断，写 `human_judgment_required: true`。
- `blocked`：与原著冲突，或出现未经批准的主要新增。

存在任何 `blocked` 时顶层 `conclusion` 为 `blocked`；没有阻断但存在 `suspected_overreach` 时为 `needs_human_review`；其余才为 `passed`。`blocked` 和 `needs_human_review` 都阻止目标制品确认。返修目标稿会产生新版本，旧边界报告不能沿用。

三层都检查同一组硬边界：主要人物/身份/能力/核心关系，动机、关键事件、因果、世界规则、结局性质，人物知情时序，以及缺少原著依据和授权的新增。心理外化、对白等表达层变化也必须追溯，不能因“自动允许”而省略证据。

自动表达变化判定 `passed` 时，还必须以 `decision_ids` 绑定同类型、`auto_allowed / expression_only / source_fact_change: false / accepted` 的改编决策；只写原著定位而不登记表达决策，仍视为追溯不完整。

## 全剧规划审核报告 `SeriesPlanReview`

规范 JSON 绑定当前事件索引、改编圣经、决策台账和全剧地图。逐项审核原著覆盖、因果、人物弧、集数覆盖、每集有效变化、信息释放、钩子来源和项目参数一致性。问题包含位置、证据、严重度、建议、状态与豁免；只有无未关闭阻断项时结论可为 `passed`。

## 批次原著范围 `BatchSourceScope`

制品键 `batch_source_scope:B01`。规范 JSON 精确绑定当前 `series_map` 与 `source_corpus`，并包含与项目批次定义完全一致的 `batch_id`、`episode_ids` 和非空 `required_source_unit_ids`。原著单元不能重复且必须存在于当前语料库。旧 backbone 不能作为新范围制品的上游。

## 批次原著细化 `BatchSourceDetail`

制品键 `batch_source_detail:B01`。规范 JSON 精确绑定当前批次原著范围、全局事件索引和原著语料库，`units` 必须无重复地精确覆盖范围中的全部原著单元。每个单元必须为 `unit_detail`，事件必须包含摘要、起因、行动、结果、状态变化和原著引用。

全局事件索引可以保持 `chapter_summary`；批次细化作为独立覆盖层存在。`batch_outline:B01` 缺少当前范围或细化依赖时不能确认。

## 批次详细大纲 `BatchOutline`

记录每集场景目标、剧情节拍、冲突升级、场景转换、原著依据、进入状态和离开状态。它是剧本直接上游，不展开完整对白。

批次必须先由 `define-batch <项目> B01 E001 E002` 登记不可重叠且不超出项目规格的明确集号范围。大纲使用 `batch_outline:B01`，对应边界报告使用 `batch_boundary_review:B01`；大纲还必须绑定当前 `batch_source_scope:B01` 和 `batch_source_detail:B01`。

每个批次大纲先登记 `awaiting_approval`，再由精确绑定当前版本的 `BatchBoundaryReview` 前置审核。报告结论不是 `passed` 时不能确认或进入试写。

## 分集剧本 `EpisodeScript`

内部稿保留 `episode_id`、版本、审批状态、来源和改编新增。每场保留稳定 `scene_id`、地点 ID、人物 ID、道具 ID、场景任务、阻力与状态变化。

对外交付正文显示：集标题、场次、地点、日夜、内外景、人物、道具、连续动作、走位、反应、对白、VO/OS、必要声音信息、场尾变化和集尾钩子。

每集剧本先登记 `awaiting_approval`，再由精确绑定当前版本的 `EpisodeBoundaryReview` 前置审核。报告结论不是 `passed` 时不能确认，也不能进入角色、场景、道具服装、台词声音或连续性提取。

## 试写审核报告 `PilotReview`

规范 JSON 绑定当前试写稿及其上游，核对原著保真、场景任务、动作—反馈—变化、空间关系、人物动机、对白功能、连续性、目标内容量和导演字段隔离。审核不修改试写；返修后必须生成绑定新版本的审核报告。

## 角色提取表 `CharacterRoster`

每个角色记录：

- 稳定角色 ID、姓名、别名和身份
- 剧情功能、欲望、关系与人物弧
- 语言、声音和表演特征
- 原著确认的外形事实与改编确认的造型约束
- 分阶段服装、伤势、身体和身份状态
- 每集/每场出场及进出场状态
- 知情范围和关键关系变化

角色表以规范 JSON 为权威数据，Markdown/CSV 可作为阅读副本。角色表是文字生产约束，不生成角色图片或视觉提示词。

规范 JSON 的 `generated_from` 与制品 `depends_on` 必须精确绑定全部当前已确认 `episode_script` 和一一对应的已确认 `episode_boundary_review`；其他三类提取表与连续性台账遵守同一依赖要求。

角色归一前先读取全剧已有稳定 ID。别名相同、同名不同人、身份冲突或阶段信息冲突写入顶层 `entity_resolution.conflicts`；只有冲突为空或已记录人工决定时才能确认，禁止用新提取值静默覆盖规范角色。

## 场景提取表 `SceneCatalog`

每个场景记录：

- 稳定地点 ID 与场景 ID
- 所属集、地点、日夜和内外景
- 空间分区、入口/出口、固定陈设和可互动元素
- 当场人物、道具、进入状态与离开状态
- 是否复用、跨集连续要求和剧情用途

场景表以规范 JSON 为权威数据。不得新增剧本没有的空间动作或剧情事件。

同一地点的名称变体通过别名归一；同地点但时间、空间分区或连续状态不同可以是不同场景版本。每个稳定 `location_id` 必须保持名称与空间定义一致，冲突进入人工确认清单。

## 道具服装台账 `PropCostumeLedger`

每件物品记录：稳定 ID、类别、文字外观事实、功能、持有人/穿戴者、首次出现、每次转移、损坏/变化、最后去向和连续性限制。规范 JSON 是校验权威。

## 台词声音表 `DialogueCueSheet`

规范 JSON 顶层使用 `contract_version: 2`。每条口述记录包含：`cue_id`、集号、场号、canonical `speaker_id`、类型、`delivery_mode`、原著文本 `text`、`source_unit_id`、`source_locator`、`source_beat_refs`、语境与表演目的。台词表必须直接依赖 `source_event_index`。`text` 必须逐字存在于绑定原著单元；模型不得生成 `source_text`、改写理由、语义分数、人物语气判断、改写审批或对白新增事实字段。环境声与关键音效不受原著逐字匹配约束。

## 连续性台账 `ContinuityLedger`

规范 JSON 顶层使用 `records` 逐场覆盖。每条记录必须包含 `episode_id`、`scene_id`、`character_states`、`item_states`、`relationship_state`、`knowledge_state`、`unresolved_threads`、`storyline_progress`、`relative_time` 和 `end_state`；这些字段分别承载人物位置/身体/身份、服装与道具持有/变化、关系、知情范围、未解决冲突与伏笔、故事线进度、时间和场尾状态。不得使用另一个 `scenes` 数组或旧字段名代替。

台账的 `generated_from` 与制品 `depends_on` 必须精确绑定全部当前分集剧本及一一对应的已确认分集内容边界报告，并与剧本逐场一一对应。

## 批次连续性快照 `BatchContinuitySnapshot`

制品键 `batch_continuity_snapshot:B01`。它精确绑定批内全部当前剧本、逐集内容边界报告和 `continuity_ledger:B01`，记录 `episode_ids` 以及 `opening_state`、`closing_state`。首尾状态都必须包含人物、物品、关系、知情、未解决伏笔、故事线进度和相对时间。

快照只压缩批次边界状态，不替代完整连续性台账。批次包缺少当前快照时不能生成。

## 跨批连续性审核 `CrossBatchContinuityReview`

制品键 `cross_batch_continuity_review`。规范 JSON 必须按剧集顺序列出全部当前批次，精确绑定每个 `batch_continuity_snapshot:Bxx`，记录相邻批次转换、发现项和结论。只有 `passed` 可以进入全剧汇总；`blocked` 或 `needs_human_review` 都阻止 `--series`。

## 质检报告 `QualityReport`

规范 JSON 必须精确绑定当前全部分集剧本、四类制作提取表和连续性台账；分集剧本还必须已有一一对应的当前已确认内容边界报告。每个问题包含稳定问题 ID、集/场、类型、严重程度、证据、建议、是否阻断、处理状态和人工豁免。至少覆盖原著保真、因果、人物、场景有效性、可制作性、连续性和目标时长；未解决阻断项存在时不能写 `passed`。普通质检豁免不能替代主要新增的用户授权。

## 制作就绪复核报告 `ProductionReadinessReport`

绑定全部分集剧本和四类提取表版本，明确记录：结构校验、语义复核、剧集覆盖、双向追溯、时长实读状态、未处理阻断项、版本绑定豁免和最终结论。只有 `ready` 结论且制品状态已确认时才能打包。

批次交付时，角色、场景、道具服装、台词声音、连续性、质检和制作就绪复核分别使用 `character_roster:B01`、`scene_catalog:B01`、`prop_costume_ledger:B01`、`dialogue_cue_sheet:B01`、`continuity_ledger:B01`、`quality_report:B01` 和 `production_readiness_report:B01`。这些制品只绑定批内集号，但字段完整性、逐集边界报告、双向追溯、阻断项关闭和结论标准与全剧交付相同。

## 全局滚动摘要 `RollingSummary`

- 制品键：`rolling_summary`；分批写作阶段按批次登记新版本，建议 ≤2000 字（项目可调）。
- 是写第 N 集上下文配方的第一层（见 workflow.md）；有损压缩的工作记忆，事实以事件索引与连续性台账为准。
- 上游：当前批次分集剧本与边界报告、连续性台账。

## 四类锚点 `StyleAnchor` / `CharacterAnchor` / `SceneAnchor` / `PropAnchor`

- 制品键：`style_anchor`、`character_anchor:C001`、`scene_anchor:L001`、`prop_anchor:P001`；带版本登记，存放于 `10_AI视频执行包/`。
- 上游：分别绑定改编圣经、角色提取表、场景提取表、道具服装台账。
- 只含文字描述与既有素材引用；外形细节属表达层，暗示新故事事实的设定需原著依据或获批新增。
- 锚点更新出新版本时，引用它的分镜计划与执行计划自动标记失效。

## 模型能力档案 `ModelCapabilityProfile`

- 制品键：`model_capability_profile:<模型>`；规范 JSON。
- 必含：`model_family`、`capability_snapshot`（status=verified/user_confirmed、checked_at、官方 source_urls）、`capabilities`（task_duration_seconds、input_modes 必填；lip_sync、max_reference_images、max_clear_speakers 等未核实写 null）。
- 校验器按档案约束执行计划，不硬编码任何模型参数。

## AI分镜单元计划 `AiShotPlan`

- 制品键：`ai_shot_plan:E001`；模型无关，规范 JSON；字段契约见 [ai-video-production.md](ai-video-production.md)。
- 必须先登记 `awaiting_approval`，经 `ai_video_boundary_review` 通过后才能确认。
- 上游：分集剧本、分集边界报告、台词声音表、风格/角色/场景锚点（必需），事件索引、事实库、决策台账、道具锚点、四类提取表（可选绑定）。

## AI分镜内容边界报告 `AiVideoBoundaryReview`

- 制品键：`ai_video_boundary_review:E001`；与三层内容边界报告同构（四种结果、精确绑定目标版本），目标是 `ai_shot_plan`。
- 语义审查绑定在分镜计划层：审一次，编译到任意模型不重审。

## AI视频执行计划 `AiVideoExecutionPlan`

- 制品键：`ai_video_execution_plan:E001:<模型>`；由已确认分镜计划＋模型能力档案编译，字段契约见 [ai-video-production.md](ai-video-production.md)。
- 每个分镜单元恰好被一个生成任务消费；时长、模式、对嘴人数全部以能力档案为准。
- 固定 `generate_images: false`、`submit_video_requests: false`。

## Seedance文字执行计划 `SeedanceExecutionPlan`

可选规范 JSON，使用 `seedance_execution_plan:E001` 逐集登记。它是已确认文学剧本的下游纯文字适配层，不覆盖 `EpisodeScript`，也不生成图片或视频。

计划必须精确绑定当前原著事件索引、故事事实、改编决策台账、当前集剧本及分集边界报告，以及当前角色、场景、道具服装、台词声音和连续性数据。顶层至少包含：

- `episode_id` 与制品 key 一致。
- `model_profile`：`Seedance 2.0`、可选供应商模型 ID、核验日期和官方来源。
- `execution_policy`：固定 `generate_images: false`、`submit_video_requests: false`，并声明纯文本或仅使用既有素材。
- `model_constraints`：当前能力快照允许的单元时长区间、画幅、分辨率和声音开关。
- `reference_assets`：只允许用户、现有项目或外部既有素材；不得嵌入 Base64/data URI。
- `global_constraints`、`total_duration_seconds` 和非空 `units`。

每个单元包含稳定 ID、顺序、场号、整数总时长、原著引用、改编决策、进入/离开状态、生成模式、参考素材 ID、连续链、非空镜头数组和编译后的 `prompt_text`。全部对白、VO、OS 必须以台词 cue ID 逐条且仅一次覆盖；提示词完整保留原台词，不在镜头内部写精确秒点。

## Seedance执行层内容边界报告 `SeedanceBoundaryReview`

使用 `seedance_boundary_review:E001` 逐集登记，并复用三层内容边界报告的发现结构和四种结论。报告精确绑定当前事件索引、事实库、决策台账、文学剧本、分集边界报告和 `seedance_execution_plan:E001` 当前版本。

报告重点检查镜头是否把人物观点拍成事实、是否新增人物选择/危机/因果/结果、是否提前泄密、是否改台词或串说话人，以及参考素材是否暗含新故事事实。报告确认且结论为 `passed` 之前，执行计划不能确认。

## 交付清单 `DeliveryManifest` / `SeriesDeliveryManifest`

由 `build-handoff` 自动生成并登记，记录包格式版本、项目 ID、生成时间、预期集数、每个交付文件的制品键、版本、相对路径、大小和 SHA-256。不得手工登记。

批次交付先运行 `validate-breakdowns <项目> --batch B01`，再运行 `build-handoff <项目> --batch B01`。工具要求已确认的 `batch_delivery_review:B01` 精确绑定当前地图与地图边界报告、批次原著范围/细化、批次大纲与边界报告、批内剧本与逐集边界报告、批次制作提取、连续性快照、质检和制作就绪复核，且审核结论为 `passed`。

批次打包自动生成 `batch_delivery_manifest:B01` 与 `batch_package:B01`，清单额外记录 `batch_id` 和 `episode_ids`。

全剧汇总使用 `build-handoff <项目> --series --expected-episodes N`。工具要求所有已定义批次无重叠、无缺集地覆盖 `E001...EN`，每批清单、包和连续性快照均为当前已确认版本，并存在结论为 `passed` 的当前 `cross_batch_continuity_review`。汇总生成 `series_delivery_manifest`，记录批次顺序、版本、文件和散列。

## 制作就绪交付包 `FinalPackage`

旧全剧兼容模式至少包含：

1. 项目规格、改编定位、改编圣经和全剧地图。
2. 改编决策台账、适用的改编变更授权记录、三层内容边界报告与已通过的全剧规划、试写审核记录。
3. 全部已确认分集剧本。
4. 角色提取表、场景提取表、道具服装台账和台词声音表。
5. 连续性台账与无阻断问题的质检报告。
6. 制作就绪复核报告。
7. 交付清单：制品键、版本、文件、散列值和生成时间。

缺任何一项都不能声称“制作就绪”。

`BatchPackage` 只把上述要求收窄到已定义批次的集号范围，不降低单批质检、制作就绪复核、内容边界、连续性或版本绑定标准，也不能据此声称全剧已经交付完成。

v0.8 默认 `FinalPackage` 由全局规划制品、全部当前批次 ZIP/清单/连续性快照、跨批连续性审核和 `series_delivery_manifest` 汇总而成，不重新展开复制每集制品。修改一个批次只让该批次、跨批审核、汇总清单和最终包失效，其他批次包保持有效。旧 `build-handoff --expected-episodes N` 仍可兼容调用，但会返回弃用提示。


## 通用语义追踪与制作可执行性（schema v2）

- `source_event_index` 的 schema v2 必须为事件和 beat 提供唯一顺序，并通过 `episode_scopes` 声明每集按原著顺序声明无重复的 `allowed_beat_ids`，并使首尾 beat 与该列表一致。
- AI 分镜单元必须使用 `source_beat_refs`，顺序不得倒退或越过当前集来源边界；引用 beat 的 `protected_fact_ids` 必须进入 `preserved_fact_ids`。
- 新增事实必须写入 `new_fact_claims` 并绑定有效改编决策，不能用布尔值自报“忠实”。
- 台词声音表用 `delivery_mode` 区分 `on_screen`、`off_screen`、`voice_over`、`phone_audio`、`screen_video`；非现场人物不得进入 `characters_on_screen`。
- 每个分镜单元必须提供 `action_flow`、`time_span_mode` 和完整 `shot_language`。动作前置状态、最短时长、对白字数和屏幕文字后期方案由工具实际校验。
- 边界报告的最终结论由目标制品的机器校验结果计算；报告自填 `passed` 不能覆盖阻断错误。

### Canonical 身份、空间、声音和尾帧绑定

- 事件索引 schema v2 必须登记 canonical entities，事件参与者、台词 speaker、分镜人物和状态链共用同一 ID。
- 分镜人物必须绑定 `space_zones` 中的 `space_id`；设备视频人物不得混入现场人物空间。
- 声音使用结构化 `sound_events`，设备声音限制为当前单元并与电话/视频 cue 显式绑定。
- `tail_frame_chain` 不得只是标签：同集绑定紧邻上一单元，跨集首镜绑定上一集已确认尾单元。

### 内容来源闭环

- 原著 beat 的 `content_atoms` 是剧情文字的机器权威来源；source atom 逐字匹配原著，决策 atom 逐字匹配已接受决策的 `authorized_content`。
- 分镜、Seedance执行层和AI视频执行层只消费已验证 atoms，不能重新独立创作剧情文字。
- `required_fact_ids` 从分集允许 beat 自动计算，`fact_realizations` 必须绑定实际存在的对白、动作、状态变化或屏显载体。
- `story_time` 和 `temporal_constraints` 是机器时间轴权威；连续镜头不能跨日期，非闪回不能倒退，明确相对时间不能脱离原著约束出现。
- HTML故事板只渲染由 `content_bindings` 编译出的剧情字段，不再直接信任旧自由文本。
