## v0.9.2 — 2026-08-06

- AI 视频执行层改为默认两段式交付（`ai_video_phase`，默认 `after_script_storyboard_confirm`）：先交付“剧本＋故事板”（分集文学剧本 DOCX ＋ 同版本 HTML 故事板，含渲染故事板所需的通用分镜计划与人物锚点），交付完成后询问用户是否继续 AI 视频执行层；取得确认后才生成能力档案、模型参数化执行计划、Seedance 执行计划等生成侧制品。
- 新增 `ai_video_continuation_authorization` 授权记录制品：默认两段式下，执行层生成侧制品必须先登记并确认该授权（或项目规格 `ai_video_phase: auto`），否则工具拒绝登记/确认（错误码 `ai_video_phase_not_confirmed`）。
- `project_spec` 新增 `ai_video_phase` 字段（`after_script_storyboard_confirm`/`auto`，缺省为前者），确认规格时校验枚举。
- 文档同步：SKILL.md、workflow.md、artifact-contracts.md、ai-video-production.md、README 明确“剧本＋故事板先行 → 用户确认 → AI 视频执行层”默认纪律。
- 新增7项回归测试，覆盖两段式默认、auto 跳过、授权放行、剧本＋故事板制品不受门禁；完整自动化测试230项通过。

# 更新记录

## v0.9.1 — 2026-08-06

- 集数判定机制改为“按原著事件量”：禁止仅凭上传章节数量推断集数；一章可拆多集、多章可合一集，章节数只界定来源范围。
- 新增`estimate-episodes`命令：读取已登记的`source_event_index`（优先统计beats，缺失时退回events），按每集戏剧单元容量（默认4—8，可由项目规格`episode_count_policy.units_per_episode`或CLI参数覆盖）输出建议集数区间与推荐值，可`--register`登记为`episode_count_estimate`制品。
- 新增项目规格集数依据门禁：项目已有确认的`source_corpus`/`source_event_index`时，确认`project_spec`必须携带`episode_count_basis`（或已确认`episode_count_estimate`制品），集数须落在事件量估算区间内，用户明确指定可登记`user_override`+`user_confirmation`；无内容索引的旧项目不阻塞。
- 文档同步：SKILL.md、workflow.md、artifact-contracts.md、adaptation-playbook.md 明确“事件量定集数、章节数不参与”规则与`episode_count_basis`契约。
- 统一插件版本号与代码常量（修复plugin.json与agent_runtime版本不一致导致的预检失败），版本升至`0.9.1`。

# 更新记录

## v0.9.0 — 2026-08-05

- 修复`series_delivery_manifest`依赖作用域：全剧汇总清单只绑定合法上游（项目规格、全剧地图/审核、批次清单/包/快照和跨批连续性审核），不再把`adaptation_profile`等非必需制品写入依赖，`build-handoff --series`产物可正常 approve。
- `final_delivery`阶段完成校验兼容新旧两条交付链：有`final_package`且已确认`delivery_manifest`或`series_delivery_manifest`其一即可标记完成。
- 新增`validate-ai-shot-plans`通用执行层校验：遍历`ai_shot_plan:E###`，要求已确认且绑定当前通过的`ai_video_boundary_review:E###`，复用结构制品校验，不再误报缺少Seedance执行计划。
- 新增`approve-artifacts`批量确认入口，支持`KEY@VERSION`，单条失败继续执行并汇总结果。
- 新增`render-episode-deliveries`批量渲染入口，逐集仍调用唯一标准生成入口并登记来源清单。
- 新增`references/ai-shot-plan-generation.md`通用分镜生成脚手架，只提供可复用逻辑，不硬编码具体项目人物或台词。
- 新增6项回归测试，覆盖汇总清单确认、阶段兼容、通用分镜校验和批量命令。

## v0.8.92 — 2026-08-04

- 生产故事板和逐集交付统一要求当前`execution_ready`；直接renderer调用、手工复制或缺少来源清单的文件不能被认定为正式交付。
- 新增`episode_delivery_manifest:<集号>`和`validate-episode-delivery`，按输入制品版本/散列、渲染契约、DOCX/HTML输出散列和标准renderer标记重新验收，只有全部一致才返回`official_delivery: true`。
- 相同逐集输入直接复用已验收产物；输出被覆盖或输入版本/散列变化后旧清单失效并重新生成，两个HTML位置继续复用同一次实际渲染。
- 新增`write-agent-result`，由CLI复用统一结果信封构造器、限制候选目录并标准化运行耗时字段。
- 未绑定宿主但租约仍有效的计划任务继续复用attempt 1；租约过期后沿用原幂等键受控恢复，第二次过期后阻断且不创建attempt 3。
- `ai_video`和`both`项目在制作提取、台词提取、故事板和逐集交付前要求schema v2事件索引、有效`beats`及目标集`episode_scopes`；`human_team`保持兼容。
- 新增15项正式交付与来源契约回归测试；编排相关定向测试46项通过，完整自动化测试221项通过。

## v0.8.91 — 2026-08-03

- 在现有`agent_runtime`和`project_state.agent_runtime.execution_control`中增加生产/开发模式锁；生产模式禁止临时运行开发测试、设计审核、Skill修改和源码修改，开发模式必须绑定明确开发任务ID。
- `startup-preflight`记录插件、Skill、运行入口、Python/平台和显式环境版本的指纹；环境不变且无新执行失败时直接复用，版本/环境变化或实际执行失败后才允许重跑。
- 统一决策身份与幂等键为项目、阶段、操作、输入散列、目标范围、规则/运行时/插件版本和输出契约/schema版本；活动任务禁止重复规划，已完成结果须通过文件存在、散列和基础校验后才能复用。
- 明确的“继续执行/按方案完成”按项目、执行链、阶段、输入和目标记录委托授权；作用域变化后自动失效，且不能绕过输入缺失、重大歧义、内容新增授权或候选验收失败。
- 普通警告按规则和授权作用域去重记录并继续；重大歧义、候选验收失败和连续失败创建全局阻断，立即暂停无关任务并写任务级检查点，解除阻断后恢复原任务租约或受控重试。
- v0.8.8/v0.8.9任务包在预检时迁移执行控制字段，首次新规划时按真实阶段重绑定统一决策键；旧工作智能体结果仍可验收并规范化，已完成有效结果不重复生成。
- 四个运行时入口统一复用同一执行控制；`show-agent-runtime`展示当前模式、预检、授权、警告、阻断和检查点状态。
- 新增20项生产执行控制回归测试；编排相关定向测试33项通过，实际耗时2.278秒。

## v0.8.9 — 2026-08-03

- 新增单次顶层校验命令共享的`ValidationContext`，按制品键、版本、当前文件散列及依赖闭包签名缓存已完成的依赖DAG结论；任一绑定上游变化都会使父节点缓存失效，循环检测、审批、版本绑定和边界门禁保持不变。
- JSON制品payload在同一校验运行中按文件散列复用，避免边界报告校验后再次读取同一分镜计划或人物锚点。
- `validate-handoff`与内部`validate-breakdowns`共享同一次`validate_state`结果、已加载状态和校验上下文，不再嵌套执行第二次完整项目扫描。
- `render-episode-delivery`把已校验的分镜计划和人物锚点直接传给故事板renderer，不再重新加载同一输入。
- HTML故事板按分镜计划、台词表、项目规格和四类锚点的版本/散列生成输入指纹；相同输入只实际渲染一次，再原子复制到AI执行包和逐集定稿交付位置。
- 故事板缓存位于项目根目录派生的`.ai-director/runtime/render-cache/storyboards/`，不进入最终交付；输入版本或散列变化时自动使用新缓存键重新渲染。
- 新增5项通用回归测试；受影响定向测试38项通过，完整自动化测试186项通过。

## v0.8.8 — 2026-08-03

- 全局长任务改为单层宿主编排：主任务直接创建、等待和关闭不继承历史的一次性工作智能体，不依赖宿主不支持的嵌套智能体。
- 新增`startup-preflight`、`plan-agent-slice`、`accept-agent-result`和`show-agent-runtime`四个运行时入口。
- 任务包冻结输入版本、散列、读取范围和候选写入目录；工作智能体只返回短结果信封，完整内容保留在项目文件中。
- 相同任务类型、业务范围、输入版本/散列和契约版本共享幂等键；完成结果直接复用，中断任务从检查点或受控新attempt恢复。
- `planned/running`任务缺少活动宿主、有效结果和有效检查点时进入`abandoned/recovery_required`；第二次失联或失败后阻断，旧attempt结果不得登记。
- `project_state.json`写入增加可重入项目锁、进程锁和原子替换，工作智能体不能直接修改项目状态。
- 默认并发为2并支持配置；只并行不同调度键的独立任务，串行任务、相邻集、连续性和项目状态写入保持互斥。
- 429、流式断开和上下文超限分别进入限流退避、全新智能体重连和缩小上下文恢复策略。
- 新增13项全局编排定向测试，覆盖初始化、候选验收、幂等复用、检查点恢复、串并行调度、状态锁和最小闭环。

## v0.8.7 — 2026-07-30

- 修复来源分析窗口`SA01/SA02`被误当成生产批次并连续扫描后续章节的问题。
- `rolling_source_progress`新增schema v2：强制绑定已确认`B01/B02`，记录完成窗口数、批次就绪状态和具体来源缺口。
- `plan-rolling-source-window`现在要求已确认的`rolling_batch`项目规格和当前B批次；没有B01时禁止开始滚动分析。
- 当前批次标记`ready_for_batch`后，工具拒绝继续扩窗并明确要求转入该批次的大纲、剧本和交付流程。
- 只有`needs_more_source`且记录非空`source_gap_reasons`时，才允许读取相邻新章节。
- 新增10项滚动闭环回归测试；测试套件由168项增加到178项，本轮源码收尾未重新执行。

## v0.8.6 — 2026-07-30

- 修复`非现场人物：`被误识别成对白并触发`dialogue_speaker_undeclared`的问题。
- 文学剧本对白注释新增`电话声音`、`电话音`、`电话声`、`屏幕声音`和`视频声音`解析；电话对白计入对白数量、时长预算和台词声音表覆盖。
- 现场人物与非现场说话人分开建模：二者共同参与合法说话人校验，但只有现场人物进入场景`characters`；同一人物同时声明为现场与非现场时阻断。
- 剧本索引与台词声音表覆盖校验新增`delivery_mode`一致性，区分`on_screen`、`off_screen`、`voice_over`、`phone_audio`和`screen_video`。
- 新增3项真实格式回归测试；完整测试由165项增加到168项。

## v0.8.5 — 2026-07-30

- 修复未确认`project_spec`覆盖已确认规格的运行权威缺陷。
- 将分集剧本时长warnings传播到项目和交付校验结果。
- canonical entity按类型支持`C/L/P`短ID与`CHAR/LOC/PROP-`长ID。
- 移除没有可靠消费者的`duration_policy.inflation_redline_ratio`字段。
- 新增章节分析幂等登记、carryover优先滚动窗口和重复分析阻断。
- 新增`register-source-analysis`、`plan-rolling-source-window`和`build-production-context-manifest`命令。
- rolling_batch schema v2支持未知最终集数，扩批必须显式用户确认。
- 显式故事板输出增加项目根路径保护；完整测试由155项增加到165项。


## v0.8.4 — 2026-07-30

### 长篇解析与并发

- 新增任意长度小说的章节/事件优先动态分片，不按小说总字数或固定字数范围硬切。
- 新增独立来源分析分片与单一写入者合并命令，支持多个分析代理并行读取，同时避免并发覆盖项目状态。

### 逐集交付

- 新增每集 `DOCX 文学剧本 + HTML 故事板` 的确定性双文件交付命令。
- 新增人物三视图文字锚点 v2：包含完整正面头肩肖像，以及全身正面、侧面、背面三视图；分开原著外貌与自动补齐视觉设计。
- 升级现有 `shot_language`，逐集交付要求结构化景别与镜头运动描述。

### 提示词与渲染修复

- 新增通用提示词可执行性门禁，检查动作起点、人物外形锁、声音、镜头运动、空间环境、说话人与原著台词、负面约束及屏幕文字后期方案。
- HTML 故事板优先渲染分镜单元的真实 `prompt_text`，并修复提示词双句号问题。
- DOCX 交付声明中文字体 `Songti SC`，且不再把内部来源注释渲染进最终剧本。

### 验证

- 完整测试：155 项通过。
- 插件结构、JSON、Python 编译与 Git 差异格式校验通过。

## v0.8.3 — 2026-07-29

### 修复

- 将《温夜有染》实际产物暴露的问题收敛为通用生成机制：通过结构化来源 beat 与分集边界阻断事件调序、越界和受保护事实遗漏，不在生产代码中硬编码具体小说人物或情节。
- 区分现场人物、画外音、电话音频与屏幕视频人物，阻断“视频中的人物被当成现场人物生成”和人物尚未到场却进入出镜列表的冲突。
- 新增结构化动作流、动作前置状态、最短承载时长、对白容量、时间跨度模式与必要屏幕文字后期叠加检查，避免动作跳步、镜头超载和依赖视频模型直接生成准确中文。
- 修复 schema v2 严格门禁误伤 schema v1 既有项目的问题：旧项目继续兼容，新契约仅在事件索引或分镜计划声明 v2 时强制。

### 默认策略

- 用户未明确指定时，默认按单集约 60 秒、上下浮动 10%、建议约 15 个分镜单元规划；项目规格中的显式时长与策略仍优先。
- 分镜数只作为生成规划建议，不作为机械阻断条件；时长、对白和动作承载继续按结构化数据校验。

### 输出

- HTML 故事板分别统计现场人物与屏幕视频人物，并展示必要屏幕文字及后期叠加方案。
- 边界结论由实际校验结果机器计算，不再依赖模型自报“已保真/可执行”。

### 验证

- 聚焦回归测试：11 项通过。
- 完整测试：105 项通过，0 失败，0 `ResourceWarning`。
- 《温夜有染》完整故事板包：7 集校验通过。

## v0.8.2 — 2026-07-28

### 修复

- AI分镜计划的时长校验可被绕过：`target_duration_seconds` 是计划自报的可选字段，省略它即可整段跳过 ±20% 偏差校验；该字段与项目规格之间也没有任何绑定，错误信息里“来自项目规格”一句从未被核对，导致 90 秒项目可以通过一份自报 30 秒的计划。现项目规格声明 `target_duration_seconds` 后，计划缺该字段报 `shotplan_target_duration_missing`，数值不符报 `shotplan_target_duration_mismatch`，均阻断确认。

### 新增

- 项目规格支持机器可读的时长契约：`target_duration_seconds`（正整数秒）与可选 `duration_policy`（`tolerance_ratio`、`dialogue_chars_per_second`、`inflation_redline_ratio`）。字段非法时拒绝确认，`validate-handoff` 报 `project_spec_duration_invalid`。原 `target_runtime` 是自由字符串、代码零引用，现降级为人工备注，不参与校验。
- `validate-script` 在获得单集目标时长后按“中文配音约3.5—4.5字/秒”推算净对白秒数：整集超载报 `episode_dialogue_budget_over`，单场超出“目标时长 ÷ 场数”比例区间报 `scene_duration_unbalanced`。两者都是警告不阻断，输出标注“非配音实测”。`approve` 与 `validate-handoff` 自动带入项目规格时长，独立使用可加 `--target-duration-seconds`。
- 分镜计划偏差容差改读 `duration_policy.tolerance_ratio`，缺省 0.2 与既有行为一致。

### 边界

- 工具不预设任何默认单集时长。项目规格未声明 `target_duration_seconds` 时，上述全部时长校验静默跳过，不报错也不猜测。
- 只预警超时，不预警偏短：判断偏短需要动作与转场余量，该余量不是项目已声明的参数，工具不凭空设定。

### 验证

- 新增测试：9 项（3 项规格时长契约、4 项分镜计划绑定与容差、2 项剧本秒数预算与向后兼容）。
- 完整测试：99 项通过。
- 变异验证：临时移除 `shotplan_target_duration_missing` 后对应测试如期失败，确认该测试真实覆盖所修缺陷。

## v0.8.1 — 2026-07-28

### 修复

- `init --expected-episodes` 此前只做取值校验后被丢弃，导致按 README 流程建档后 `define-batch` 直接报“无法从项目规格读取 expected_episodes”。现记入状态的 `expected_episodes_hint`，`project_spec` 确认前可据此定义批次并返回 `episode_scope_source: init_hint` 警告；`project_spec` 一经确认即覆盖提示，交付门禁权威不变。
- `validate-script` 此前只拦截“景别：特写”这类填表式镜头语言，散文式写法（`镜头缓缓推近`、`俯拍全景`、`手持跟拍长焦压缩背景`、`切黑后淡入`、`画面停留约3秒`、`35mm`）可整集通过且零提示，与“文学剧本不混入镜头语言”的门禁相矛盾。现新增 `shot_language_suspected` 警告覆盖运镜、景别、机位、焦段、剪辑与硬秒点五类；语义不确定项只预警不阻断，台词原文与场次标题不参与判断。

### 验证

- 新增测试：7 项（3 项集数提示语义、1 项状态字段校验、3 项镜头语言检测）。
- 完整测试：90 项通过。

## v0.8.0 — 2026-07-28

### 新增

- 来源默认直通，并支持已发表小说的可选指定官网审核。
- v0.8 轻量全剧骨架：每集只强制集号和摘要，详细内容下沉到当前批次。
- `batch_source_scope:Bxx` 与 `batch_source_detail:Bxx` 批次原著细化门禁。
- `batch_continuity_snapshot:Bxx` 批次连续性快照。
- `cross_batch_continuity_review` 跨批连续性终检。
- `--series` 全剧汇总模式，复用已确认批次包生成最终交付。

### 改进

- 修改单个批次时，不再让其他已确认批次包失效。
- 旧全剧直接打包方式保留兼容提示，引导新项目使用批次加全剧汇总流程。
- 插件描述、能力列表、默认提示词和工作流文档同步至 v0.8。

### 验证

- 聚焦测试：14 项通过。
- 完整测试：82 项通过。
- Skill、插件、JSON 和 Git 差异校验通过。
