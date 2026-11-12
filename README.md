# Zimika Agent Director

把小说或故事线，转换为**可追溯、可分批推进、可直接进入导演拆镜的制作就绪剧本包**。

当前版本：`0.10.0-zimika.1`

GitHub: https://github.com/zimika0520/Zimika-Agent-Director

> Zimika 二次开发作品。核心思路来自 [ai-director](https://github.com/Shinchan-crayon/ai-director)，在原项目基础上完成品牌整理、工程说明、学习路径和可复现验证。原作者与许可证信息见 [UPSTREAM.md](UPSTREAM.md)。

## 它能做什么

Zimika Agent Director 是一个运行在 Codex 中的长篇小说改编工作流，负责把长篇小说或故事线逐步改写成制作就绪的分集剧本，并输出可直接使用的交付物：

- **按事件量判定集数**：先解析原著建立事件索引，再按每集可承载的戏剧单元容量估算集数。一章可以拆成多集，多章可以合成一集，绝不单纯按上传的章节数量推断集数。
- **默认两段式交付**：先交付“剧本＋故事板”（分集文学剧本 DOCX ＋ 同版本 HTML 故事板），交付完成后询问你是否继续 AI 视频执行层；取得你的确认后，才生成能力档案、模型参数化执行计划、Seedance 执行计划等视频侧制品。
- **全局骨架先行**：先生成覆盖全剧的轻量骨架，再按批次细化原著范围和事件，避免一次性硬切全书。
- **逐批次推进**：按批次生成大纲、分集剧本、角色/场景/道具/台词制作提取表；每个批次独立打包，修改一个批次不影响其他已确认批次。
- **内容边界与连续性门禁**：对原著追溯、内容边界、人物状态、伏笔和制作就绪程度执行校验；全剧完成后做跨批连续性终检。
- **制作就绪输出**：文学剧本区分现场人物与非现场说话人（电话声音、VO、OS、屏幕声音），可直接用于导演拆镜，不需要再补剧情、动机或动作因果。
- **生产模式保护**：正式制作任务锁定生产模式，禁止中途改源码、改 Skill 或重跑设计审核；长任务自动编排、断点恢复，已完成结果不会重复生成。

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

## 安装到 Codex

### 1. 克隆仓库

```bash
git clone https://github.com/zimika0520/Zimika-Agent-Director.git
cd Zimika-Agent-Director
```

### 2. 建立本地 Marketplace

```bash
MARKET="$HOME/.codex/local-marketplaces/zimika-agent-director-local"
mkdir -p "$MARKET/.agents/plugins" "$MARKET/plugins"
ln -sfn "$PWD" "$MARKET/plugins/zimika-agent-director"

cat > "$MARKET/.agents/plugins/marketplace.json" <<'JSON'
{
  "name": "zimika-agent-director-local",
  "interface": {
    "displayName": "Zimika Agent Director Local"
  },
  "plugins": [
    {
      "name": "zimika-agent-director",
      "source": {
        "source": "local",
        "path": "./plugins/zimika-agent-director"
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
codex plugin add zimika-agent-director@zimika-agent-director-local
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

### 按事件量估算集数

```bash
python3 skills/novel-to-script-director/scripts/project_tool.py estimate-episodes \
  /path/to/project
```

工具读取已登记的 `source_event_index`（优先统计 beats，缺失时退回 events），按每集戏剧单元容量输出建议集数区间与推荐值，可 `--register` 登记为 `episode_count_estimate` 制品。

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

### 定义批次

```bash
python3 skills/novel-to-script-director/scripts/project_tool.py define-batch \
  /path/to/project B01 E001 E002 E003 --confirmed-by-user
```

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

### 渲染并验收逐集交付

```bash
python3 skills/novel-to-script-director/scripts/project_tool.py render-episode-delivery \
  /path/to/project E001

python3 skills/novel-to-script-director/scripts/project_tool.py validate-episode-delivery \
  /path/to/project E001
```

逐集命令输出 `E001_剧本.docx`、`E001_故事板.html` 和项目运行时内的来源清单，不生成图片。文件存在不等于正式完成，必须以验收命令返回的 `official_delivery` 为准。

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

## 验证

```bash
python3 skills/novel-to-script-director/scripts/test_project_tool.py
python3 -m json.tool .codex-plugin/plugin.json >/dev/null
```

完整自动化测试 230 项通过（Zimika 基线版本）。

## 更新记录

见 [CHANGELOG.md](CHANGELOG.md)。

## Zimika 的工程整理

- 统一项目名称、插件展示名和学习入口。
- 增加 `LEARNING_GUIDE.md`，按架构、状态机、检查点、测试和面试表达拆分学习路径。
- 保留上游代码身份与许可证，明确区分原项目和 Zimika 的二次开发部分。
- 保留完整自动化测试，当前基线为 230 项通过。

## License

[MIT](LICENSE)。原始版权归 Shinchan-crayon 所有；Zimika 的二次开发说明见 [UPSTREAM.md](UPSTREAM.md)。
