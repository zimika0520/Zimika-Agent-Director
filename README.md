# AI导演

把小说、故事线或部分章节，转换为**可追溯、可分批推进、可直接进入导演拆镜的制作就绪剧本包**。

当前版本：`0.8.92`

## 它能做什么

- 上传来源默认直接建档，不自动检查缺章、乱码或完整度。
- 已发表小说可由用户主动开启指定官网页面审核；审核不阻塞工作流。
- 先生成覆盖全剧的轻量骨架，再按当前批次细化原著范围和事件。
- 按批次生成大纲、分集剧本、角色/场景/道具/台词制作提取表。
- 对原著追溯、内容边界、人物状态、伏笔和制作就绪程度执行门禁校验。
- 每个批次独立打包；修改一个批次时，其他已确认批次包保持有效。
- 全剧完成后执行跨批连续性终检，并复用批次包汇总最终交付。
- 可选输出模型无关或 Seedance 2.0 的纯文字导演执行计划。
- 只有有效确认的项目规格能改变运行权威；未确认新版本不会覆盖旧确认版本。
- 章节分析按章节哈希和契约版本幂等登记，后续批次优先复用carryover。
- `rolling_batch`允许最终总集数未知，并要求显式用户确认后才能扩展批次。
- 文学剧本区分现场人物与非现场说话人，并识别电话声音、VO、OS和屏幕声音，防止口述cue被漏计。
- 长任务由主任务直接调度不继承历史的一次性工作智能体；完整内容写入项目候选文件，不回流主上下文。
- 任务规划具备幂等键、检查点和受控恢复；已完成结果不会重复生成，失联或失败最多尝试两次。
- 独立任务可按可配置容量并发，串行任务和`project_state.json`写入保持互斥。
- 生产任务与开发任务在启动时锁定模式；生产模式禁止修改源码、Skill、运行开发测试或重新做设计审核。
- 生产预检按插件、运行时、Skill、入口和环境指纹只执行一次；版本/环境变化或实际执行失败后才重跑。
- 用户的明确继续指令按项目、执行链、阶段、输入和目标复用；输入、目标、规则或阶段变化后自动失效。
- 普通警告去重记录后继续；重大歧义、候选验收失败和连续失败立即阻断无关任务并从检查点恢复。
- v0.8.8/v0.8.9运行时任务在首次预检时迁移，并在首次新规划时按真实阶段重绑定统一决策键；已完成且校验有效的结果不重新生成。
- 单次校验命令共享依赖DAG结果、已加载状态和JSON payload；文件版本或散列变化会在新运行中重新校验。
- 相同分镜输入只生成一次HTML，两个交付位置通过输入指纹缓存和原子复制保持一致。
- 逐集DOCX/HTML只有经`render-episode-delivery`生成、登记来源清单并通过`validate-episode-delivery`后才是正式交付；直接renderer输出或手工复制文件只算候选。
- `ai_video`和`both`项目在制作提取、台词提取、故事板或逐集交付前必须使用带`beats`和`episode_scopes`的schema v2事件索引；`human_team`不受该门禁影响。

## 工作流

```mermaid
flowchart LR
    A[上传小说或故事线] --> B[来源直接建档]
    B --> C[项目规格与原著解析]
    C --> D[轻量全剧骨架]
    D --> E[批次原著范围与细化]
    E --> F[批次大纲与分集剧本]
    F --> G[制作提取与质量门禁]
    G --> H[独立批次包]
    H --> I[跨批连续性终检]
    I --> J[全剧最终交付包]
```

## 全局编排运行时

正式处理小说时先锁定生产模式并运行一次预检，再由主任务直接创建、等待和关闭工作智能体：

```bash
python3 skills/novel-to-script-director/scripts/project_tool.py startup-preflight \
  <项目目录> --mode production --run-id RUN-001
python3 skills/novel-to-script-director/scripts/project_tool.py plan-agent-slice <项目目录> \
  --task-type source_analysis --scope-json '{"source_unit_id":"SU001"}' \
  --input-ref source_corpus@1=01_原著解析/原著语料V1.json \
  --stage source_analysis --operation source_analysis \
  --contract-version 1 --acceptance-command schema-only \
  --output-schema-version 1 --coordinator-slice source_window \
  --run-id RUN-001 --delegation-directive "继续执行"
python3 skills/novel-to-script-director/scripts/project_tool.py accept-agent-result \
  <项目目录> --task-id <任务ID> --result <项目内结果信封.json>
python3 skills/novel-to-script-director/scripts/project_tool.py show-agent-runtime <项目目录>
```

工作智能体只能读取任务包允许路径，只能写入`.ai-director/runtime/candidates/`下的任务目录。CLI负责候选校验、制品登记、检查点和项目状态写入，不直接调用模型。

`production`是小说生产默认模式。模式一经锁定不能在同一项目执行链中切换；只有明确的插件开发任务才能使用`--mode development --development-task-id <开发任务ID>`。生产任务包会拒绝`development_test`、`design_review`、`skill_edit`和`source_edit`操作。

预检结果记录在现有`project_state.json -> agent_runtime.execution_control`中，不建立第二套状态文件。环境未变化且没有新的执行失败时复用`execution_ready`；插件、Skill、入口、Python/平台或显式环境版本变化后，下一次规划先报预检失效，重跑后再继续。

统一决策幂等键包含项目身份、阶段、操作、输入散列、目标范围、规则版本、运行时/插件版本及输出契约/schema版本。已接受结果只有在文件存在、散列一致且基础校验通过时才复用；否则沿用原幂等键进入受控恢复。

普通警告只记录一次并继续。重大歧义或候选验收失败会创建活动阻断、暂停无关任务并写检查点；修复后用`startup-preflight --resolve-blocker-id <阻断ID> --resolution-note <说明>`解除，原任务从检查点恢复。笼统的“继续执行”只授权当前执行动作，不能替代新增故事事实所需的具体`change_authorization`。

校验缓存只存在于单次命令的内存中，不跨命令持久化；它按制品键、版本、文件散列和依赖闭包签名复用已完成的依赖结论。故事板缓存位于项目自己的`.ai-director/runtime/render-cache/storyboards/`，按分镜计划及相关锚点、台词表、项目规格的版本和散列生成指纹。输入变化后使用新指纹重新渲染，缓存目录不进入最终交付包。

生产渲染必须使用当前`execution_ready`。`render-episode-delivery`会冻结当前确认制品的路径、版本和SHA-256，生成DOCX/HTML后登记`episode_delivery_manifest:<集号>`；只有`validate-episode-delivery`重新核对输入指纹、输出散列、DOCX结构和HTML标准renderer标记后，结果才返回`official_delivery: true`。

## 安装到 Codex

### 1. 克隆仓库

```bash
git clone https://github.com/Shinchan-crayon/ai-director.git
cd ai-director
```

### 2. 建立本地 Marketplace

```bash
MARKET="$HOME/.codex/local-marketplaces/ai-director-local"
mkdir -p "$MARKET/.agents/plugins" "$MARKET/plugins"
ln -sfn "$PWD" "$MARKET/plugins/ai-director"

cat > "$MARKET/.agents/plugins/marketplace.json" <<'JSON'
{
  "name": "ai-director-local",
  "interface": {
    "displayName": "AI Director Local"
  },
  "plugins": [
    {
      "name": "ai-director",
      "source": {
        "source": "local",
        "path": "./plugins/ai-director"
      },
      "policy": {
        "installation": "AVAILABLE",
        "authentication": "ON_INSTALL"
      },
      "category": "Productivity"
    }
  ]
}
JSON
```

### 3. 安装插件

```bash
codex plugin marketplace add "$MARKET"
codex plugin add ai-director@ai-director-local
```

安装后请新建一个 Codex 任务，让新任务加载最新版 Skill。

## 使用示例

### 创建项目

```bash
python3 skills/novel-to-script-director/scripts/project_tool.py init \
  /path/to/project \
  --name "项目名" \
  --source /path/to/novel.txt \
  --source-kind self_owned \
  --expected-episodes 60
```

`--expected-episodes` 记入 `expected_episodes_hint`，只用于在 `project_spec` 确认前先定义批次；交付校验仍以已确认 `project_spec` 的 `expected_episodes` 为权威。

### 声明单集目标时长（可选）

默认生成策略为单集约 60 秒、允许上下浮动 10%、建议约 15 个分镜单元。若项目需要其他时长，可在 `project_spec` JSON 中显式写入 `target_duration_seconds` 覆盖默认值：

```json
{
  "schema_version": 1,
  "project_id": "项目UUID",
  "expected_episodes": 60,
  "target_duration_seconds": 90
}
```

AI 分镜计划必须写出当前生效的目标时长（未显式声明时为默认 60 秒，显式声明时为项目值）；缺失或不符都会阻断确认。剧本校验也会按“中文配音约3.5—4.5字/秒”给出净对白秒数预警。可选 `duration_policy` 覆盖容差与推算参数，默认偏差容差为 ±10%，详见 `references/production-data-schemas.md`。

单独校验某集剧本的时长预算：

```bash
python3 skills/novel-to-script-director/scripts/project_tool.py validate-script \
  /path/to/E001.md --target-duration-seconds 90
```

### 定义批次

```bash
python3 skills/novel-to-script-director/scripts/project_tool.py define-batch \
  /path/to/project B01 E001 E002 E003 --confirmed-by-user
```

`--confirmed-by-user`只对`scope_mode: rolling_batch`、`schema_version: 2`的新批次强制；固定全剧旧项目仍按`expected_episodes`校验。

### 滚动来源复用

```bash
python3 skills/novel-to-script-director/scripts/project_tool.py register-source-analysis \
  /path/to/project --source-corpus 01_原著解析/source_corpus.json \
  --registry 01_原著解析/chapter_registry_v1.json \
  --source-unit-id SRC-CH001 --analysis tmp/CH001_analysis.json \
  --contract-version 1 --output 01_原著解析/chapter_registry_v2.json

python3 skills/novel-to-script-director/scripts/project_tool.py plan-rolling-source-window \
  /path/to/project --source-corpus 01_原著解析/source_corpus.json \
  --registry 01_原著解析/chapter_registry_v2.json \
  --progress 01_原著解析/rolling_progress.json \
  --window-size 3 --output tmp/rolling_plan.json
```

### 构建批次交付包

```bash
python3 skills/novel-to-script-director/scripts/project_tool.py build-handoff \
  /path/to/project --batch B01
```

### 汇总全剧交付

```bash
python3 skills/novel-to-script-director/scripts/project_tool.py validate-handoff \
  /path/to/project --series --expected-episodes 60

python3 skills/novel-to-script-director/scripts/project_tool.py build-handoff \
  /path/to/project --series --expected-episodes 60
```

## 项目结构

```text
.codex-plugin/plugin.json
skills/novel-to-script-director/
├── SKILL.md
├── references/
└── scripts/
    ├── project_tool.py
    ├── agent_runtime.py
    └── test_project_tool.py
```

## 边界

本插件负责文字工作流、项目状态、制品契约、校验和交付打包。它不会：

- 自动下载小说正文；
- 生成或嵌入图片；
- 提交视频生成任务；
- 调用配音或剪辑接口；
- 把未读取到的内容冒充原著事实。

## 动态分批与逐集交付

```bash
python3 skills/novel-to-script-director/scripts/project_tool.py plan-source-partitions   <项目目录> --source-corpus <source_corpus.json> --policy <partition_policy.json>   --output <tmp/source-analysis/run-001/partition-plan.json>

python3 skills/novel-to-script-director/scripts/project_tool.py merge-source-analysis-shards   <项目目录> --plan <partition-plan.json> --shard-dir <shards目录>   --output <source_event_index_candidate.json>

python3 skills/novel-to-script-director/scripts/project_tool.py render-episode-delivery   <项目目录> E001

python3 skills/novel-to-script-director/scripts/project_tool.py validate-episode-delivery   <项目目录> E001
```

流程不按小说总字数切换；章节/事件优先，容量预算兜底。逐集命令输出 `E001_剧本.docx`、`E001_故事板.html`和项目运行时内的来源清单，不生成图片。文件存在不等于正式完成，必须以验收命令返回的`official_delivery`为准。

## 验证

```bash
python3 skills/novel-to-script-director/scripts/test_project_tool.py
python3 -m json.tool .codex-plugin/plugin.json >/dev/null
```

v0.8.92 新增15项正式交付与来源契约回归测试；编排、幂等、检查点、恢复、串并行和门禁相关定向测试46项通过；完整自动化测试221项通过。

## 更新记录

见 [CHANGELOG.md](CHANGELOG.md)。

## License

[MIT](LICENSE)
