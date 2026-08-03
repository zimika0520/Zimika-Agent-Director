# 工作流与恢复规则

## 阶段表

| 阶段键 | 主要动作 | 核心产物 | 继续条件 |
|---|---|---|---|
| `project_setup` | 接收原著、建档、规格草案 | 原始文件、项目规格 | 来源可读取 |
| `source_analysis` | 建立索引与事实库 | 原著语料、两层粒度原著事件索引、故事事实 | 每个原著单元已处理或有明确排除理由 |
| `adaptation_positioning` | 判断受众、题材与边界 | 改编定位卡 | 第一门禁确认 |
| `adaptation_bible` | 锁定全局规则与改编操作 | 改编圣经、改编决策台账 | 制品完成 |
| `series_planning` | 规划剧情弧和全部分集 | `full` 或 `backbone` 全剧分集地图、全剧地图内容边界报告、全剧规划审核报告 | 完整覆盖全部集号，边界报告通过且第二门禁确认 |
| `batch_outline` | 细化当前批次 | 批次详细大纲、批次大纲内容边界报告 | 边界报告通过且当前批次确认 |
| `pilot_writing` | 验证制作就绪写法 | 试写剧本、试写审核报告 | 第三门禁确认 |
| `batch_writing` | 顺序生成后续剧集 | 全部分集剧本、逐集内容边界报告 | 每集边界报告通过且当前批次完成 |
| `quality_review` | 制作提取、结构、保真与连续性复核 | 四类提取表、台账、质检报告 | 无阻断问题或用户豁免 |
| `final_delivery` | 全剧复核与打包 | 制作就绪剧本包 | 第四门禁确认 |

AI 视频执行层不是新的编剧阶段，而是逐集解锁的纯文字适配层：某集通过 `episode_boundary_review` 且覆盖该集的提取数据与锚点就绪后，即可生成该集 `seedance_execution_plan` 与对应 `seedance_boundary_review`，不必等 `final_delivery`。`delivery_target` 含 `ai_video` 时默认生成，`human_team` 时仅在用户要求时生成；它不改变既有阶段完成状态，也不把图片或视频成品纳入项目。节奏、锚点与提示词纪律见 [ai-video-production.md](ai-video-production.md)。

`express` 模式下四道门禁合并为两道（规格＋定位＋圣经＋地图；首集试写＋首集执行包），此后按批次滚动确认。三层内容边界报告仍然前置生成，`blocked` 与 `suspected_overreach` 拦截规则不变。

阻塞、待修改和可恢复失败写入当前阶段 `status` 与 `note`，不得伪装成完成。

## 四道强制门禁

1. 项目规格与改编定位。
2. 改编圣经、改编决策台账、全剧分集地图、全剧地图内容边界报告与独立规划审核。
3. 批次大纲内容边界、试写稿的场景动作、改编尺度、节奏、对白、格式与独立试写审核。
4. 每集剧本内容边界、全剧剧本、角色/场景/道具服装/台词声音提取表、连续性与质检、交付清单。

确认必须绑定制品版本。用户说“整体可以”“按这个继续”等明确表达可以视为当前门禁的流程确认；沉默、上传文件或询问不能视为确认。流程确认不等于批准新增故事事实；需要用户确认的主要新增或改动仍须形成具体 `change_authorization`。

## 新项目

1. 确认至少有一份可读取来源。来源只来自用户提供；上传完整小说或部分章节都直接建档，不自动检查缺章、乱码、截断或完整度。
2. 询问来源类型：`self_owned`、`storyline` 或 `published_novel`。前两种直接运行；已发表小说再询问是否审核，默认关闭。用户主动开启时必须提供指定官网或正版页面，Skill 只读取该页面并登记非阻塞 `source_review`，不自行搜索或下载正文。
3. 初始化项目并展示保存位置；`init` 只复制、计算散列和记录 `source_policy`。`--expected-episodes` 只记录项目意图，不检查上传文件是否足够。
4. 只询问会改变全局结果的缺失项：用途、集数/时长、改编范围、硬性保留、禁改和交付对象。
5. 未指定参数给出带依据的建议，在第一道门禁确认。

## 恢复项目

1. 运行 `show` 读取 `current_stage`、`stages`、`artifacts` 和 `approvals`。
2. 检查登记文件是否存在且散列一致。
3. 优先处理阻塞和失效制品，不跳到后续生成。
4. 只读取当前阶段所需原著片段和制品。

## 全局智能体编排运行时

长任务采用单层宿主编排：主任务是唯一监督者，直接创建、等待和关闭不继承历史的一次性工作智能体。`project_tool.py`只规划、校验、验收和更新运行状态，不创建智能体、不调用模型。运行目录固定派生自当前项目根目录的 `.ai-director/runtime/`，不进入最终交付包。

`--coordinator-slice`为兼容既有任务包保留，只表示来源窗口、单集剧本、制作提取或批次收尾等逻辑业务片段，不表示第二级协调智能体。

```bash
python3 <技能目录>/scripts/project_tool.py startup-preflight <项目目录>

# 第一次规划生成不可变任务包
python3 <技能目录>/scripts/project_tool.py plan-agent-slice \
  <项目目录> --task-type source_analysis \
  --scope-json '{"source_unit_id":"SU001"}' \
  --input-ref source_corpus@1=01_原著解析/原著语料V1.json \
  --contract-version 1 --acceptance-command schema-only \
  --coordinator-slice source_window --run-id RUN-001

# 主任务用 fork_context:false 创建工作智能体，获得宿主ID后绑定当前attempt
python3 <技能目录>/scripts/project_tool.py plan-agent-slice \
  <项目目录> <与第一次完全相同的任务参数> \
  --host-task-id <宿主工作智能体ID> \
  --active-host-task-id <宿主工作智能体ID>

# 等待并关闭工作智能体后验收结果
python3 <技能目录>/scripts/project_tool.py accept-agent-result \
  <项目目录> --task-id <任务ID> --result <项目内结果信封.json>
python3 <技能目录>/scripts/project_tool.py show-agent-runtime <项目目录>
```

- 任务包不继承会话历史，只读取冻结的 `input_refs` 和允许路径；相同任务类型、范围、输入版本/散列与契约版本只生成一个有效结果。
- 主任务每次调用`plan-agent-slice`时必须通过可重复的`--active-host-task-id`传入全部仍存活的工作智能体ID。只有宿主ID仍活动、存在有效结果或存在有效检查点时，活动任务才可复用。
- `planned/running`任务失去宿主、结果和检查点时，工具将其标记为`abandoned/recovery_required`并写检查点，再以相同幂等键创建attempt 2；第二次仍失联时标记`blocked`。旧attempt晚到结果不能登记。
- 默认并发为 2；`--max-parallel-tasks`、`--service-capacity` 可配置，调度器只并行不同调度键的独立任务。相邻集剧本、连续性、全局归一和状态写入保持串行。
- 候选结果先由 CLI 校验，再登记 `awaiting_approval`；智能体不得直接写 `project_state.json`。所有状态读改写都经过项目状态锁和原子落盘。
- `429_too_many_requests`、`stream_disconnect_without_completion`、`context_window_exceeded` 分别进入限流退避、全新智能体重连、缩小上下文恢复策略；同一任务连续失败两次后写入检查点并阻断。
- 用户说“继续”时先读取 `show-agent-runtime` 和最近检查点，复用已完成结果，不重新读取相同上下文或重复生成。

### 编排接口冻结

自2026-08-03起，四个运行时入口、任务包、结果信封、幂等键、宿主任务绑定、检查点状态、项目状态锁、串行/独立调度和两次失败阻断为冻结兼容面。新增流程只能复用这些接口；不得让工作智能体直接写状态、绕过候选验收、改变幂等键组成或把失联任务无限标记为活动。

### 校验与故事板复用

- `validate_state`、`confirmed_record_is_usable`和`matching_boundary_review`在一次顶层命令内共享`ValidationContext`。缓存键包含制品键、版本、当前文件散列和依赖闭包签名；任一绑定上游变化都会使父节点失效。只缓存已完成结果，循环检测中的临时状态不写入缓存。
- `validate-handoff`把同一次项目校验结果、已加载状态和上下文传给`validate-breakdowns`，不能为了提速跳过制作提取、连续性、审批、版本或追溯检查。
- `episode_delivery_inputs`读取并校验分镜计划、人物锚点和交付依赖后，将只读payload传给renderer；renderer不得再次读取这些输入。
- 故事板缓存位于当前项目`.ai-director/runtime/render-cache/storyboards/`，输入指纹覆盖分镜计划、台词表、项目规格和四类锚点的版本与散列。两个HTML交付位置必须从同一缓存文件原子复制；指纹变化时重新渲染，旧缓存不得冒充新版本。

## 分层索引与全剧骨架

- `SourceEventIndex.units[].granularity` 使用 `unit_detail` 或 `chapter_summary`。前者记录完整事件因果、行动、结果和状态变化；后者用于先建立章节级摘要，只强制事件摘要与原著引用。
- 顶层 `upgrade_pending` 必须无重复地精确列出全部 `chapter_summary` 单元。无论粒度如何，事件索引都必须与 `SourceCorpus` 逐单元一一对应；旧索引缺少粒度字段时按 `unit_detail` 兼容读取。
- `SeriesMap.granularity` 使用 `full` 或 `backbone`。v0.8 `backbone` 使用 `contract_version: 2`，每集只强制 `episode_id` 与 `summary`；推荐的目标、冲突、原著提示和钩子缺失时只警告。两种地图都必须覆盖项目规格中的 `E001...EN`。
- 全局 `SourceEventIndex` 可以保持全书 `chapter_summary`。当前批次通过 `batch_source_scope:B01` 选择原著单元，再以 `batch_source_detail:B01` 完成 `unit_detail` 覆盖；不要为了 B01 修改整个全局索引并让无关批次失效。

## 批次定义、校验与交付

先把批次范围写入项目状态；批次 ID 使用 `B01` 格式，集号使用 `E001` 格式，同一集不能落入多个批次：

```bash
python3 <技能目录>/scripts/project_tool.py define-batch <项目目录> B01 E001 E002
```

批次原著范围、原著细化、大纲、边界报告、四类制作提取、连续性台账、连续性快照、质检、制作就绪复核和批次交付审核统一使用 `:<batch_id>` 作用域。`batch_outline:B01` 必须绑定当前已确认的 `batch_source_scope:B01` 和 `batch_source_detail:B01`。单批完成后运行：

```bash
python3 <技能目录>/scripts/project_tool.py validate-breakdowns <项目目录> --batch B01
python3 <技能目录>/scripts/project_tool.py build-handoff <项目目录> --batch B01
```

批次打包生成 `batch_delivery_manifest:B01` 和 `batch_package:B01`。每批还必须有 `batch_continuity_snapshot:B01`。全剧完成后生成精确绑定全部当前快照且结论为 `passed` 的 `cross_batch_continuity_review`，再运行：

```bash
python3 <技能目录>/scripts/project_tool.py validate-handoff <项目目录> --series --expected-episodes N
python3 <技能目录>/scripts/project_tool.py build-handoff <项目目录> --series --expected-episodes N
```

汇总模式要求批次无重叠、无缺集地覆盖 `E001...EN`，复用已确认批次 ZIP 与清单生成 `series_delivery_manifest` 和 `final_package`。修改一批只标脏该批、跨批审核和全剧汇总，不影响其他批次包。

## 增量补传来源（追更场景）

用户先传部分章节、后续补传时，运行：

```bash
python3 <技能目录>/scripts/project_tool.py add-source <项目目录> <新章节文件> --reason <说明>
```

工具登记新来源（按 sha256 去重）并自动把原著语料库及其下游标脏，不自动执行入料体检。随后增量更新语料库、全局粗索引与受影响批次的原著范围/细化制品，再复核受影响稿件；已出剧本不得静默重写。基于部分章节的项目照常推进，所有事实和钩子只能来自当前已上传内容。

## 耗时登记（两口径）

阶段耗时分两口径登记，用于评估流程改进：`machine_time`（机器计算耗时）与 `human_wait`（人工等待耗时，如等用户确认门禁）。`set-stage` 支持可选参数 `--machine-time-seconds` 与 `--human-wait-seconds`，写入 stage 历史记录；`show --summary` 在有数据时按两列汇总（`time_tracking`），旧项目无字段不报错也不显示。混在一起的“总耗时”会把人工等待算进机器改进空间，无法向业务证明优化效果。

## 写第 N 集的上下文配方（长剧上下文压缩）

分批写作阶段，每集加载的上下文按三层硬上限组织，总量可预算化（参考自公开项目验证过的 200+ 章规模实践，上限数值为项目可调参数）：

1. **全局滚动摘要** `rolling_summary`（建议 ≤2000 字）：每集确认后增量合并，覆盖全剧已发生事实与主线状态；有损压缩，事实争议以事件索引和连续性台账为准。
2. **近程定向摘要**（建议 ≤800 字）：最近 2—3 集的摘要，生成时同时参考本集与下一集的地图条目，面向“接下来要写什么”取材，而非中性复述。
3. **接缝原文**：上一集结尾一场的原文（数百字级），保证行文与状态衔接质感。

外加：已确认圣经、当前批次大纲、本集对应原著片段、连续性台账相关条目、下一集地图条目（让本集结尾主动为下集铺垫）。不整本回喂已写剧本。

## 任意长度来源的动态分批与逐集交付

1. 不检查“是否超过10万字”来选择流程。所有来源先按章节、场景、事件形成稳定原著单元。
2. 短小相邻单元在容量预算内合并；超长单元必须先沿场景/事件边界拆出新ID。原著解析批次与剧本生产批次相互独立。
3. 独立来源分片可受控并发；人物/地点/事件归一、全局时间线、连续性和 `project_state.json` 由单一写入者串行合并。
4. 某集剧本确认后，人物、场景、道具、台词提取可写入不同文件并发执行；同一角色锚点和相邻集最终状态不得并发覆盖。
5. 某集分镜确认后，DOCX与HTML可并发确定性渲染。E001交付完成不必等待全剧全部剧本完成。

逐集命令：

```bash
python3 scripts/project_tool.py render-episode-delivery <项目目录> E001
```

输出固定为 `09_定稿交付/分集交付/E001/E001_剧本.docx` 和 `E001_故事板.html`。

## 修改传播

| 修改对象 | 默认需要复核的下游 |
|---|---|
| 原著来源或项目规格 | 定位、圣经、地图、全部剧本与提取表 |
| 原著事件索引 | 事实库、定位、决策台账、地图、相关剧本与质检 |
| 改编定位 | 圣经、地图、大纲、剧本与提取表 |
| 改编圣经 | 决策台账、地图、相关批次、剧本、提取表和连续性 |
| 改编决策台账 | 全剧地图、规划审核、相关大纲、剧本与质检 |
| 全剧地图 | 全剧地图边界报告、规划审核、受影响大纲、剧本、提取表和台账 |
| 批次大纲 | 批次大纲边界报告、当前批次剧本及后续承接 |
| 某集剧本 | 对应分集边界报告、四类提取表、质检、台账和受承接影响的后集 |
| 四类提取表 | 交付包与交付清单 |
| 某集剧本、对应边界报告或任一制作提取表 | 对应 AI 分镜计划、执行计划与执行层边界报告 |
| 风格/角色/场景/道具锚点 | 引用该锚点的全部分镜计划、执行计划与重试台账 |
| AI 分镜计划 `ai_shot_plan` | 对应 `ai_video_boundary_review` 与全部模型的 `ai_video_execution_plan` |
| 模型能力档案 | 该模型的全部 `ai_video_execution_plan` |
| 纯排版 | 仅重新导出 |

优先局部返修。旧版本保留，已确认版本不得静默覆盖。

## 制作提取纪律

- 角色、场景、道具服装和台词声音表只能提取已确认且通过对应内容边界报告的剧本与圣经中的内容。
- 提取时发现信息不足，回到剧本补齐并生成新版本；不得在表格中暗补。
- 每条提取记录保留集号、场号或角色 ID，可双向追溯。
- 四类制作提取表与连续性台账的 `depends_on` 和 JSON `generated_from` 必须同时精确绑定全部当前 `episode_script` 版本与一一对应的已确认 `episode_boundary_review` 版本；不能少绑某集、混用旧报告，或只在正文写版本。
- 每集提取前先读取项目级规范实体。名称相同不等于同一角色，地点文字相似不等于同一空间；自动归一只能提出建议，未确认冲突不得静默覆盖稳定 ID。
- 核心文学剧本流程不生成视觉造型、导演分镜或配音成品。用户明确要求 Seedance 兼容时，只在独立下游制品中生成文字导演分镜和视频提示词；仍不生成或读取图片，不提交视频任务。

## AI 视频文字执行层（三层）

1. 确认文学剧本、对应分集内容边界报告、覆盖该集的制作提取表和连续性台账均为当前版本；建立或更新风格/角色/场景/道具锚点（带版本的规范制品）。
2. 读取 `ai-video-production.md`（三层结构、节奏、锚点、状态链、提示词纪律）；为目标模型建立或复核 `model_capability_profile`，涉及 Seedance 接口时再读 `seedance-compatibility.md`；未知参数不得猜测。
3. 生成模型无关的 `ai_shot_plan:E001` 并登记 `awaiting_approval`；独立生成精确绑定当前版本的 `ai_video_boundary_review:E001`，报告 `passed` 后确认分镜计划。工具在 approve 时自动校验外形锁、台词覆盖、单人对嘴、状态链、锚点版本与资产预算。
4. 按能力档案把已确认分镜单元编译成 `ai_video_execution_plan:E001:<模型>`（每个单元恰好消费一次）；换模型只需换档案重编,不重审语义。
3. 每集生成 `seedance_execution_plan:E001` 并登记 `awaiting_approval`。执行策略必须写 `generate_images: false` 与 `submit_video_requests: false`。
4. 独立生成 `seedance_boundary_review:E001`，精确绑定计划当前版本。报告不是 `passed` 时不确认计划。
5. 台词、VO、OS 按 `dialogue_cue_sheet` 逐条且仅一次覆盖；单元时长遵守能力快照，镜头内部不硬写精确秒点。
6. 全剧运行 `validate-seedance --expected-episodes N`。通过只代表文字适配完成，不代表实际生成已测试。

## 独立审核与返修

1. 起草者先提交制品并登记 `awaiting_approval`，审核轮次重新读取当前文件、原著依据和上游版本，不依赖起草摘要。
2. 审核报告逐项记录位置、证据、严重度、建议和状态；只报告问题，不直接覆盖被审稿件。
3. `blocking` 问题必须 `resolved` 或持有用户明确批准的 `waived` 记录。存在未关闭阻断项时，审核结论不能为 `passed`。
4. 返修生成新版本，旧稿与旧审核保留。审核报告必须绑定返修后的当前版本，不能继续使用旧报告过门。
5. 数值与审美判断以项目规格和原著为准；无法核验的商业经验标记为建议，不能伪装成行业硬规则。

## 三层内容边界门禁

核心原则是“可以增加表达，不得擅自增加故事事实”。全剧地图、批次大纲、每集剧本都必须先登记 `awaiting_approval`，再由对应 `series_boundary_review`、`batch_boundary_review`、`episode_boundary_review` 精确绑定当前版本审核；禁止先确认目标稿再补报告。

每条边界发现使用四种结果：

- `passed`：有明确原著依据，并提供可定位 `source_refs`。
- `approved_addition`：绑定改编决策；该决策再绑定有效 `change_authorization` 与用户确认记录。
- `suspected_overreach`：证据不足，标记 `human_judgment_required: true`；报告结论为 `needs_human_review`，目标稿不能确认。
- `blocked`：与原著事实冲突或有未经批准的主要新增；报告结论为 `blocked`，目标稿不能确认。

没有疑似或阻断项时，报告结论才是 `passed`。自动判断必须填写 `automation_limitations`，明确它不能保证百分之百正确。普通审核中的 `waived` 不能替代内容新增授权。

硬阻断包括：目标稿未经事先授权就新增或改变主要人物、身份、能力、核心关系，改变动机、关键事件、因果、世界规则或结局性质，或提前泄露人物尚未知晓的信息；以及没有原著依据且没有已批准新增记录的内容。用户随后批准时，必须生成绑定授权的新决策、目标稿版本和边界报告，旧报告不能直接改结论放行。

自动允许但必须追溯的表达层操作包括：心理外化、场景衔接、时间压缩、动作补全、无新剧情功能的群众/环境反应，以及原著事件的戏剧化展开。它们必须登记为 `auto_allowed`、`expression_only`、`source_fact_change: false`，并绑定原著依据与改编决策。对白、VO、OS 直接引用原著语料，不再进入改写、润色、语义复核或审批链路。

新命名角色、合并角色、新支线、新关系、新能力、新重大事件、关键事件调序、改变人物选择/事件原因/结果、为钩子新增重要危机，必须先取得用户明确确认并形成 `change_authorization`；未授权时直接阻断。

## 每轮进度卡

```text
项目：<名称>
当前阶段：<阶段>
已完成：<已确认制品>
待确认/阻塞：<一项或少量事项>
下一步：<用户确认后会发生什么>
```
