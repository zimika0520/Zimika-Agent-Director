# AI导演

把小说、故事线或部分章节，转换为**可追溯、可分批推进、可直接进入导演拆镜的制作就绪剧本包**。

当前版本：`0.8.8`

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

生产任务开始前运行最小预演，再由主任务直接创建、等待和关闭工作智能体：

```bash
python3 skills/novel-to-script-director/scripts/project_tool.py startup-preflight <项目目录>
python3 skills/novel-to-script-director/scripts/project_tool.py plan-agent-slice <项目目录> \
  --task-type source_analysis --scope-json '{"source_unit_id":"SU001"}' \
  --input-ref source_corpus@1=01_原著解析/原著语料V1.json \
  --contract-version 1 --acceptance-command schema-only \
  --coordinator-slice source_window --run-id RUN-001
python3 skills/novel-to-script-director/scripts/project_tool.py accept-agent-result \
  <项目目录> --task-id <任务ID> --result <项目内结果信封.json>
python3 skills/novel-to-script-director/scripts/project_tool.py show-agent-runtime <项目目录>
```

工作智能体只能读取任务包允许路径，只能写入`.ai-director/runtime/candidates/`下的任务目录。CLI负责候选校验、制品登记、检查点和项目状态写入，不直接调用模型。

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
```

流程不按小说总字数切换；章节/事件优先，容量预算兜底。逐集命令输出 `E001_剧本.docx` 与 `E001_故事板.html`，不生成图片。

## 验证

```bash
python3 skills/novel-to-script-director/scripts/test_project_tool.py
python3 -m json.tool .codex-plugin/plugin.json >/dev/null
```

v0.8.8 候选新增13项全局编排定向测试；候选完整测试集合共181项。

## 更新记录

见 [CHANGELOG.md](CHANGELOG.md)。

## License

[MIT](LICENSE)
