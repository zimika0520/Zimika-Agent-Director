---
name: novel-to-script-director
description: Guide a stateful, checkpointed adaptation of a novel, story outline, or other long-form narrative into a production-ready episodic manhua-drama script package and, when the delivery target includes AI video, per-episode text-only AI video execution packages (anchors, shot units, structured prompts) for models such as Seedance 2.0. Use when a user asks to start, continue, revise, inspect, validate, or export a 小说改剧本、漫剧剧本、短剧文学剧本、分集分场台本、制作就绪剧本、AI视频执行包 project, or asks to turn an already confirmed script into AI-video-ready textual shot units. Covers source parsing, adaptation decisions, asset budgeting, episodic writing, extraction, fidelity, continuity, shot-unit pacing, prompt contracts, handoff validation, and resumable state. The AI video layer produces structured text and prompt plans only; it never generates images, submits video jobs, or performs audiovisual production.
---

# AI导演：小说改制作就绪漫剧剧本与AI视频文字执行层

把长篇故事分阶段转换成可直接进入生产的分集剧本包。先建立全局事实与改编方案，再写局部成稿；保存每阶段制品、确认状态和原著依据，禁止用后续制作环节替编剧补戏。

## 交付目标与流程模式

项目规格必须锁定 `delivery_target`，它决定交付范围与默认纪律：

- `ai_video`（默认）：最终消费者是 AI 视频模型。AI 视频执行包是一等交付物，按集解锁；资产预算、节奏纪律和表演词汇纪律从圣经与大纲阶段就生效，见 [ai-video-production.md](references/ai-video-production.md)。
- `human_team`：交付制作就绪文学剧本包给人类团队，执行层仅在用户要求时生成。
- `both`：两者并行，文学剧本仍不混入镜头语言。

流程模式：

- `standard`：完整四道门禁，适合长剧集与多人协作。
- `express`（单人快速通道）：门禁合并为两道——①项目规格＋改编定位＋改编圣经＋全剧地图一次性确认；②首集试写＋首集执行包一次性确认，此后按批次滚动交付。express 下首集剧本即试写稿：同一文件先登记为 `pilot_scripts` 并完成试写审核，通过后复登记为 `episode_script:E001`，不必另写一份试写。三层内容边界报告照常生成并保持前置；`blocked` 与 `suspected_overreach` 的拦截规则不变，express 只减少确认次数，不放松内容边界。

## 交付边界

- `ai_video` 目标的最终交付是“分集AI视频执行包”及其上游依据：全剧规划、改编决策台账、分集分场剧本、四类提取表、连续性台账、四类锚点、分集执行计划与质检报告。`human_team` 目标交付“制作就绪剧本包”，至少包括：全剧规划、改编决策台账、分集分场剧本、角色提取表、场景提取表、道具服装台账、台词声音表、连续性台账、质检报告和交付清单。
- 分集剧本必须写清集标题、场次、地点、日夜、内外景、现场人物、必要的非现场人物、有效道具、连续可见动作、走位、反应、对白、必要的 VO/OS/电话/屏幕声音信息、场尾变化和集尾钩子。现场人物写入`人物：`；只发声但不在现场空间出镜的角色写入独立`非现场人物：`，并可用`角色名 电话声音：`、`角色名 VO：`、`角色名 OS：`标记交付方式，禁止为了通过校验把非现场角色重复塞进现场人物。
- 制作团队拿到后可以拆角色、场景、道具、台词并进入导演拆镜，不需要重新补剧情、人物动机或动作因果。
- 制作就绪文学剧本不混入镜号、景别、机位、运镜、焦段、单镜时长或生成提示词。镜头语言只存在于独立的 AI 视频执行层制品中；`delivery_target` 含 `ai_video` 时执行层默认生成，`human_team` 时仅在用户要求时生成。`validate-script` 对“景别：特写”这类填表式混入报 `director_field_forbidden` 错误并阻断；对“镜头推近”“俯拍全景”“切黑后淡入”这类散文式镜头语言报 `shot_language_suspected` 警告，须人工确认改写为可见动作，台词原文与场次标题不参与该判断。
- AI 视频执行层可以输出锚点、文字导演分镜、短生成单元和结构化视频提示词，但固定 `generate_images: false`、`submit_video_requests: false`；不调用生图、视频、配音或剪辑接口，不嵌入 Base64/data URI，也不把参考素材需求当作已生成资产。
- 执行层按集解锁：某集剧本通过对应 `episode_boundary_review` 且该集依赖的提取数据与锚点就绪后，即可交付该集执行包，不必等全剧完稿。
- 图片、故事板图片、角色/场景生图和影音成品不属于本技能。用户提供的既有参考素材只能登记路径、URL或资产 ID，不能由本技能生成。
- 不把“3场/集”“前3集”“每批3—5集”冒充行业标准；它们只能作为项目可调参数。
- 不声称忠于未读到的原著。来源缺失、损坏或无法核验时明确写“不清楚”，不得补造。
- 原著来源只来自用户提供。上传文件默认直接建档，不自动检查缺章、乱码、截断或完整度。来源类型使用 `self_owned`、`storyline` 或 `published_novel`；只有用户明确选择已发表小说、主动开启官网审核并提供官网或正版页面时，才读取该指定页面生成非阻塞 `source_review`，不自行全网搜索、不下载官网正文、不覆盖上传文件。
- 项目规格的 `rights_mode`（owned/licensed/unclear，缺省按 owned 处理）只登记用户声明的权利状态：`owned` 与 `licensed` 不讨论版权照常推进（licensed 可用 `rights_note` 记录授权范围）；`unclear` 时仅提示用户确认权利状态一次（提示不是错误），不阻塞任何流程。

## 内容边界总则

核心原则：**可以增加表达，不得擅自增加故事事实。** 内容边界不是最终交付前的一次文字匹配，而是以原著事件索引、故事事实库、改编决策台账和用户授权为证据，在以下三层分别运行的前置门禁：

1. 全剧分集地图先登记 `awaiting_approval`，再生成精确绑定当前版本的 `series_boundary_review`。
2. 每份批次详细大纲先登记 `awaiting_approval`，再生成精确绑定当前版本的 `batch_boundary_review`。
3. 每集分场剧本先登记 `awaiting_approval`，再生成精确绑定当前版本的 `episode_boundary_review`。

目标制品不能先确认、后补报告。报告中的每条发现只能使用四种结果：

- `passed`：有明确、可定位的原著依据。
- `approved_addition`：绑定 `AdaptationDecisionLedger` 中的已批准决策，以及可回查用户原话的 `ChangeAuthorization`。
- `suspected_overreach`：证据不足，必须人工判断；未得到人工处理前阻止目标稿确认。
- `blocked`：与原著事实冲突，或出现未经批准的主要新增；阻止目标稿确认并退回返修。

硬性阻断：目标稿未经事先授权就新增或改变主要人物、身份、能力或核心关系，改变人物动机、关键事件、因果、世界规则或结局性质，或提前泄露人物尚不知道的信息；以及找不到原著依据且没有获批新增记录的内容。只有取得适用的具体授权，并生成绑定该授权的新决策、目标稿版本和边界报告，才能按 `approved_addition` 重新进入门禁；不能让旧报告直接放行。

自动允许但必须追溯：心理描写转为可见动作；场景衔接、时间压缩和动作补全；不承担新剧情功能的群众或环境反应；原著已有事件的戏剧化展开。它们必须标记为 `expression_only`、`source_fact_change: false`，并绑定原著单元与改编决策，不能借“戏剧化”改变选择、原因或结果。对白、VO、OS 不属于自动表达变化：必须逐字引用原著，只允许拆到连续镜头和清理排版空白，禁止润色、换词、补写或把叙述伪装成对白。

必须取得用户确认：新命名角色或合并角色；新支线、新关系、新能力、新重大事件；调换关键事件顺序；改变人物选择、事件原因或结果；为增强钩子新增的重要危机。授权必须记录具体改动、适用范围、约束、确认原话和确认人，不能把笼统的“继续”解释成新增许可。

自动检查只负责证据核对、冲突预警和门禁执行，不声称百分之百判断正确。语义不确定项必须输出 `suspected_overreach` 并进入人工判断，不能自动放行。

## 每次开始或恢复

1. 在当前工作区查找用户指定项目；未指定时查找 `project_state.json`。只有一个候选时恢复，多个候选时列出项目名让用户选择。
2. 新项目没有原始内容时，要求用户上传文件或粘贴内容；已经提供时不要重复索要。用户只上传部分章节时照常建项目：剧本只写到已上传内容截断点，后续用 `add-source` 增量补传，工具自动标脏来源依赖链。
3. 完整读取 [workflow.md](references/workflow.md)，按阶段和人工门禁继续。
4. 运行 `scripts/project_tool.py show <项目目录> --summary`，以本地状态为准。
5. 优先处理失效或阻断制品；只加载当前阶段需要的原著片段和制品。
6. 展示进度卡：`当前阶段 / 已完成 / 待确认或阻塞 / 下一步`。
7. `delivery_target` 含 `ai_video`，或用户要求执行层时，完整读取 [ai-video-production.md](references/ai-video-production.md)；涉及 Seedance 具体接口时再读 [seedance-compatibility.md](references/seedance-compatibility.md)，先核对模型能力快照，再处理文字执行层。

## 任意长度小说与受控并发

不按小说总字数写死短/长流程。优先按章节、场景和事件建立稳定来源单元，再用当前运行时容量策略合并相邻单元。原著粗分析分片、四类制作提取和DOCX/HTML渲染可以在输入版本锁定后受控并发；全局ID归一、连续性、相邻集定稿和项目状态写入必须串行。主任务是唯一监督者，直接创建、等待和关闭不继承历史的一次性工作智能体；工作智能体只写独立候选文件，由主任务调用CLI验收和登记。生产任务开始前运行 `startup-preflight`；实际规划、验收和恢复统一使用 `plan-agent-slice`、`accept-agent-result`、`show-agent-runtime`。`coordinator_slice`只表示逻辑业务片段，不创建第二级协调智能体。主任务必须回传当前活动宿主任务ID；缺少宿主、结果和检查点的活动任务进入`abandoned/recovery_required`，以相同幂等键最多受控重试一次，旧attempt不得形成第二个有效结果。同一顶层校验命令必须复用运行级依赖DAG与JSON payload缓存；该缓存不得跨命令持久化，文件版本或散列变化必须重新校验。

生产来源分析必须维护`chapter_analysis_registry`和`rolling_source_progress`。相同`source_unit_id + content_sha256 + analysis_contract_version`不得重复分析；下一批先复用carryover，再从`next_read_start`规划新章节。使用`register-source-analysis`登记新的registry文件，使用`plan-rolling-source-window`生成增量窗口。所有输入输出必须位于显式项目根目录内。

## 建立本地项目

默认在工作区创建 `AI导演项目/<安全项目名>/`，不得覆盖已有项目：

```bash
python3 <技能目录>/scripts/project_tool.py init \
  <项目目录> --name <项目名> --source <原始文件> \
  [--source-kind self_owned|storyline|published_novel] \
  [--official-review --official-url <指定页面>] \
  [--expected-episodes <目标集数>]
```

必须至少提供一份 `--source`，可重复提供。脚本复制原文件并记录散列，不修改原文件。用户粘贴内容时先保存为来源文件再注册。

`--expected-episodes`记入状态的`expected_episodes_hint`，只用于固定全剧规格确认前的规划提示。运行时只读取有效确认的`project_spec`；更高版本仍为draft或awaiting_approval时不能覆盖上一份有效确认规格。`rolling_batch` schema v2允许`final_expected_episodes: null`，批次范围以显式用户确认的`project_state.batches`为权威。

完整小说、部分章节、TXT、Markdown、Word 或其他可读取文档都直接登记。`self_owned` 与 `storyline` 不询问官网审核；`published_novel` 再询问用户是否审核，默认关闭。用户主动开启时必须提供 HTTP/HTTPS 页面，审核结论只展示，不阻塞原著解析。`--garble-threshold` 仅为旧命令兼容保留，当前版本不触发正文检查。

直接读取 TXT/Markdown。PDF、DOCX 或扫描件使用对应文档读取能力，标准化文本写入 `01_原著解析/`，保留页码、章节或段落定位；无法可靠提取时停止并说明。

## 核心流程

### 1. 项目规格、原著解析与事件索引

- 锁定用途、受众平台、`delivery_target`、流程模式、总集数、单集目标时长、改编尺度、`rights_mode`（用户声明即可，不外部核实）、必须保留、允许调整和禁止改变项。用户未明确指定时，按单集约 60 秒、上下浮动 10%、约 15 个分镜单元规划；项目规格可用 `target_duration_seconds`（正整数秒）和 `duration_policy` 显式覆盖。
- 将“可直接进入导演拆镜”写入交付要求，不把“可商用”当成没有验收条件的形容词。
- 建立稳定来源 ID、人物、关系、地点、时间线、事件、因果和异常；事实、推断、未知和改编新增分栏。
- 逐个可定位原著单元生成全局 `SourceEventIndex`：允许整本使用 `chapter_summary`，仍须逐单元覆盖 `SourceCorpus` 并维护 `upgrade_pending`。当前批次不反复改写全局索引，而是用 `batch_source_scope:B01` 确定所需原著单元，再用 `batch_source_detail:B01` 对这些单元建立完整 `unit_detail`；缺单元、仍为粗粒度或绑定旧版本时不能确认批次大纲。
- canonical entity按类型使用`character: C001/CHAR-*`、`location: L001/LOC-*`、`prop: P001/PROP-*`，全局唯一且类型与前缀必须一致。
- 生成项目规格、原著语料、事件索引与事实库；项目规格和事件索引以规范 JSON 为权威，其他阅读版只作副本。

### 2. 改编定位与题材打标

- 读取 [adaptation-playbook.md](references/adaptation-playbook.md) 与 [genre-tags.md](references/genre-tags.md)。
- 先按三层标签体系（受众×主题材×流行元素）生成 `genre_profile`：每个标签给原著证据和置信度，判定不了的写入 uncertainties，不硬贴；标签不得虚构原著没有的元素。
- 把标签卡作为独立确认点展示给用户（“这是一部什么小说”），用户确认或纠正后，`adaptation_directives`（钩子偏好、节奏、资产倾向、雷区检查）注入改编圣经与全剧地图。
- 再生成改编定位卡：受众方向、主副题材、卖点、情绪回报、关系模式和基调；展示依据与不确定项。
- 完成第一道门禁：项目规格、题材标签与改编定位确认。

### 3. 改编圣经、决策台账与全剧地图

- 读取 [artifact-contracts.md](references/artifact-contracts.md)。
- 圣经锁定世界规则、人物弧、关系、主支线、关键地点、道具服装、伏笔、不可变事实与改编新增。
- `delivery_target` 含 `ai_video` 时，圣经同时登记 `asset_budget`（主场景数、核心角色数、单集出场上限、群演策略、高成本要素与降级替代），全剧地图逐集标注复用与新增资产；规则见 [ai-video-production.md](references/ai-video-production.md)。
- 建立规范 `AdaptationDecisionLedger`，逐项登记保留、压缩、合并、调序、删除和桥接新增；绑定原著单元、目标集、理由、受保护事实与连续性影响。
- 全剧地图使用 `granularity: full | backbone`。v0.8 的轻量 `backbone` 使用 `contract_version: 2`，每集只强制合法 `episode_id` 与非空 `summary`，仍须完整覆盖 `E001...EN`；`goal`、`core_conflict`、`source_hint`、`end_hook` 仅为推荐字段，缺少时警告但不阻塞。详细原著映射、冲突、钩子和场景节拍下沉到当前批次。
- 全剧地图登记 `awaiting_approval` 后，先生成精确绑定当前地图版本的 `series_boundary_review`；存在 `blocked` 或 `suspected_overreach` 时不能确认地图。
- 内容边界通过后，使用与起草分开的审核轮次生成全剧规划审核报告；审核只提出带证据的问题，不直接改稿。阻断问题关闭后，完成第二道门禁。用户确认前不写整集成稿；内容事实越界不能用普通质检豁免绕过，必须绑定用户变更授权。

### 4. 批次大纲与试写

- 细化前先定义不可重叠且不超出项目规格的批次范围：

```bash
python3 <技能目录>/scripts/project_tool.py define-batch \
  <项目目录> B01 E001 E002 E003 --confirmed-by-user
```

`--confirmed-by-user`只在rolling_batch schema v2新增批次时强制；不得由模型自行假定用户已确认。

- 按已确认地图细化当前批次；试写数量由项目决定，默认参数不是标准。
- 先登记并确认 `batch_source_scope:B01` 与 `batch_source_detail:B01`。范围制品绑定批次集号和当前原著语料；细化制品必须逐项覆盖范围中的所有原著单元，并全部达到 `unit_detail`。
- 批次大纲先登记 `awaiting_approval`，再生成精确绑定当前版本的 `batch_boundary_review`；边界报告通过后才能确认大纲并进入试写。
- 将叙述、心理和作者评价转成可见动作、选择、阻力、反应、对白、VO或OS。
- 每场必须形成“进入状态 → 当场任务 → 可见阻力 → 行动链 → 转折 → 离开状态”，不能只是对白之间插动作。
- 按 [script-format-and-quality.md](references/script-format-and-quality.md) 写作并运行 `validate-script`。
- 使用独立审核轮次核对试写的原著保真、动作因果、空间调度、对白、连续性与格式；返修后登记试写审核报告。
- 完成第三道门禁：确认动作密度、场景调度、对白尺度、节奏与格式。

### 5. 分批写作与滚动连续性

- 每批按 [workflow.md](references/workflow.md) 的“写第 N 集上下文配方”加载：全局滚动摘要（`rolling_summary`，硬上限）＋近程定向摘要＋上集结尾原文接缝，外加已确认圣经、批次大纲、对应原著片段、连续性台账和下一集地图条目；不整本回喂已写剧本。每批完成后更新滚动摘要新版本。
- 生产任务开始前运行`build-production-context-manifest`生成当前阶段最小加载清单；不得读取`test_*.py`或`docs/superpowers/plans/`。
- 顺序生成少量剧集，不并行破坏前后集状态。
- 每集剧本先登记 `awaiting_approval`，再生成精确绑定当前版本的 `episode_boundary_review`；`blocked` 或 `suspected_overreach` 必须先返修或人工确认，不能把越界内容带入后续剧集。
- 每集更新人物位置、身体/身份状态、关系、知情范围、服装、道具、伏笔、未解决冲突和故事线进度。
- 每批完成后生成 `batch_continuity_snapshot:B01`，提取批次开场与收尾的人物、物品、关系、知情、伏笔、故事线和相对时间状态，供全剧汇总时做跨批衔接检查。
- 结构校验通过后仍需做原著保真、戏剧有效性、可制作性和连续性语义复核。

### 6. 制作提取与质量复核

- 只从已确认且已通过对应 `episode_boundary_review` 的全部当前剧本和圣经提取角色、场景、道具服装、台词声音数据，不在提取阶段新增剧情。
- 每集提取前读取全剧现有规范实体；优先复用稳定 ID。别名、同名不同人、同地点不同空间版本或资料冲突进入归一冲突清单，禁止静默覆盖。
- 读取 [production-ready-delivery.md](references/production-ready-delivery.md) 和 [production-data-schemas.md](references/production-data-schemas.md)，生成角色提取表、场景提取表、道具服装台账和台词声音表。规范 JSON 是校验权威，Markdown/CSV 只作阅读与流转副本。核心角色提取语言指纹 `voice_fingerprint`（口头禅/说话风格/行为模式，逐项带原著佐证），供对白写作与审核注入；连续性台账的伏笔按生命周期管理（open→progressing→resolved＋预期回收点），质检核对健康度。
- 核对每条记录能回到集号、场号和剧本原句；信息缺失时退回剧本修改，禁止由提取表暗补。
- 四类制作提取表和连续性台账的状态依赖与 JSON `generated_from` 必须同时精确绑定全部当前 `episode_script` 及各自匹配的已确认 `episode_boundary_review`；少绑一集或沿用旧边界报告均不能确认。
- 更新连续性台账与质检报告。质检只能生成报告或返修版本，不静默覆盖已确认稿。

### 7. 定稿与制作交付包

- 运行项目校验、每集剧本校验和制作交付校验：

```bash
python3 <技能目录>/scripts/project_tool.py validate-project <项目目录>
python3 <技能目录>/scripts/project_tool.py validate-script <单集剧本>
python3 <技能目录>/scripts/project_tool.py validate-breakdowns <项目目录> --expected-episodes <集数>
python3 <技能目录>/scripts/project_tool.py validate-handoff <项目目录> --expected-episodes <集数>
python3 <技能目录>/scripts/project_tool.py build-handoff <项目目录> --expected-episodes <集数>
```

- 需要按批次交付时运行：

```bash
python3 <技能目录>/scripts/project_tool.py validate-breakdowns <项目目录> --batch B01
python3 <技能目录>/scripts/project_tool.py build-handoff <项目目录> --batch B01
python3 <技能目录>/scripts/project_tool.py validate-handoff <项目目录> --series --expected-episodes <集数>
python3 <技能目录>/scripts/project_tool.py build-handoff <项目目录> --series --expected-episodes <集数>
```

- 批次制品使用 `:<batch_id>` 作用域，包括原著范围、原著细化、批次大纲、制作提取、连续性快照、质检和交付审核；打包后生成独立 `batch_delivery_manifest:B01` 与 `batch_package:B01`。
- 全剧汇总要求全部批次无重叠、无缺集地覆盖 `E001...EN`，并具有当前已确认批次包、清单和快照；`cross_batch_continuity_review` 必须精确绑定全部快照且结论为 `passed`。汇总生成 `series_delivery_manifest` 与新的 `final_package`，复用批次 ZIP，不重新展开复制每集制品。
- 全剧或批次剧本与制作提取表通过对应第四道门禁后，使用 `build-handoff` 生成带散列和版本信息的交付包。批次交付只缩小剧集范围，不降低单批质检、制作就绪复核、三层内容边界和版本绑定标准。
- 旧 `build-handoff --expected-episodes` 全剧直接打包仅作兼容并返回弃用提示；v0.8 新项目使用 `--batch` 与 `--series` 两级交付。全剧汇总必须明确 `--expected-episodes`。
- 对外交付稿隐藏内部来源 ID、审批元数据和工作备注；内部制品继续保留。

### 8. AI 视频文字执行层（`ai_video`/`both` 默认，`human_team` 可选）

- 按 [ai-video-production.md](references/ai-video-production.md) 执行：①建立或更新风格/角色/场景/道具四类锚点（带版本号的规范制品）；②生成模型无关的 `ai_shot_plan:E001`（含每单元通用中文提示词），登记 `awaiting_approval` 后先过 `ai_video_boundary_review:E001` 前置门禁。**通用分镜计划就是默认最终交付**，不区分 Seedance/可灵/Veo 等平台。
- 仅当用户点名需要某平台的参数化任务包时，才建立该模型的 `model_capability_profile` 并编译 `ai_video_execution_plan:E001:<模型>`；语义审查绑定在分镜计划层，编译不重审。
- 分镜计划确认后运行 `project_tool.py render-storyboard <项目目录> <集号>` 生成 HTML 故事板供用户可视化检查（节奏时间轴、单元卡片、提示词复制、锚点资产表）；只读渲染，规范数据以 JSON 为准。相同输入版本与散列只实际渲染一次，AI执行包与逐集定稿位置通过项目内输入指纹缓存原子复制；输入变化必须重新渲染。
- 只从当前已确认 `episode_script`、对应 `episode_boundary_review`、覆盖该集的制作提取数据和连续性台账生成，不覆盖文学剧本。`ai_video` 目标下提取表与锚点可按已确认批次滚动更新，绑定当前批次全部剧本版本即可交付该批次执行包。
- 每个分镜单元必须绑定锚点版本；锚点更新后，引用它的计划自动标记失效，须换版重编。approve 时工具自动校验外形锁注入、台词逐条覆盖、单人对嘴、结构化状态链连续、切点时长理由、资产预算与提示词字段完整。
- 兼容旧项目：`seedance_execution_plan:E001` 键仍受支持，按原 Seedance 专属流程校验。
- 执行计划保存经核验日期和官方来源，不把旧模型 ID、时长或接口字段当成永久事实。实际接口不清楚时写“不清楚”，不得猜测。
- 每个短单元记录场号、总时长、原著依据、进入/离开状态、连续链、镜头文字、台词 cue ID、声音和编译后的中文视频提示词。镜头内部不写 `0-3秒` 一类硬秒点。
- 全部对白、VO、OS 必须按台词表逐条且仅一次覆盖；台词表使用 `contract_version: 2`，每条口述 cue 只保存原著文本、`source_unit_id` 与 `source_locator`，不得生成 `source_text`、改写理由、语义分数、人物语气判断或新增事实字段。参考素材模式只能绑定用户或项目已有素材，纯文本模式不得偷偷带素材。
- 执行计划还要经过 `seedance_boundary_review:E001` 前置门禁。报告不是 `passed` 时计划不能确认；镜头表达不得改变人物选择、事件原因、结果、知情范围或结局性质。
- 全剧完成后运行：

```bash
python3 <技能目录>/scripts/project_tool.py validate-seedance \
  <项目目录> --expected-episodes <集数>
```

- 校验通过只表示文字结构、台词覆盖、版本和内容边界适配完成，不代表真实视频已生成或模型效果已验证。

## 制品与状态操作

生成或修改制品后立即登记：

```bash
python3 <技能目录>/scripts/project_tool.py register-artifact \
  <项目目录> <制品键> <文件> --status awaiting_approval

python3 <技能目录>/scripts/project_tool.py approve \
  <项目目录> <制品键> --version <版本> --note <确认说明>

python3 <技能目录>/scripts/project_tool.py set-stage \
  <项目目录> <阶段> <阶段状态> --note <说明>
```

更新上游制品必须使用新版本；新版本必须使用新的文件路径（工具拒绝复用旧版本路径，命名如 `xxx_v2.json`）。每个制品登记精确的当前上游版本与剧集范围，工具会按实际依赖标记受影响下游制品。修改前先用依赖关系确认影响范围，优先局部返修；不得删除旧版本、伪造用户确认、反向依赖或绕过门禁。

## 对话规则

- 每次只询问会改变全局结果或阻塞当前门禁的事项；其余先从原著推断再让用户确认。
- 门禁提供：`确认继续 / 提出修改 / 查看依据 / 退回上一步`。
- 用户说“继续”时从本地状态恢复，不重复已确认工作。
- 用户纠正原著事实时，先修事实库，再标记全部受影响制品。
- 用户要求一次生成大量剧集时，先完成全剧地图和试写门禁，再分批写作。
- 每项关键事件、人物变化和新增桥段绑定原著来源；桥接内容标记“改编新增”及用途。
- 基于事实回答；样本经验与行业标准分开。没有调研到或不知道的事项直接说明不清楚。
- 用户提及 Toonflow、Huobao 或要求解释本插件参考依据时，读取 [reference-project-findings.md](references/reference-project-findings.md)；不得从参考项目引入分镜、图片、视频或固定经验参数。
- 用户要求 Seedance 兼容时只生成独立文字执行层；任何 API Key、Base64 图片/视频数据或实际生成请求都不得写入项目制品、工具输出或会话历史。


## 通用来源忠实与分镜门禁

生成和审核不得针对某一本小说硬编码人物、事件或台词。每个项目必须从自己的原著生成事件 beat、来源边界、受保护事实和台词锁；分镜必须引用这些项目内 ID。工具按来源顺序、事实覆盖、人物出现方式、对白时长、动作状态链和屏幕文字后期方案实际校验，不接受 `true` 或 `passed` 作为事实依据。

## 每集最终交付

当某集文学剧本、边界报告、制作提取、人物锚点v2和AI分镜均为当前确认版本后，运行 `render-episode-delivery`。每集交付一个可编辑DOCX文学剧本和一个从同版本剧本推演的HTML故事板。DOCX中的人物首次可见出镜位置展示完整三视图文字，后续场次引用；HTML每个分镜明确展示景别和镜头运动。本技能仍不生成图片或视频。
