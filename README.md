# AI导演

把小说、故事线或部分章节，转换为**可追溯、可分批推进、可直接进入导演拆镜的制作就绪剧本包**。

当前版本：`0.8.0+claude.20260728`

## 它能做什么

- 上传来源默认直接建档，不自动检查缺章、乱码或完整度。
- 已发表小说可由用户主动开启指定官网页面审核；审核不阻塞工作流。
- 先生成覆盖全剧的轻量骨架，再按当前批次细化原著范围和事件。
- 按批次生成大纲、分集剧本、角色/场景/道具/台词制作提取表。
- 对原著追溯、内容边界、人物状态、伏笔和制作就绪程度执行门禁校验。
- 每个批次独立打包；修改一个批次时，其他已确认批次包保持有效。
- 全剧完成后执行跨批连续性终检，并复用批次包汇总最终交付。
- 可选输出模型无关或 Seedance 2.0 的纯文字导演执行计划。

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

### 定义批次

```bash
python3 skills/novel-to-script-director/scripts/project_tool.py define-batch \
  /path/to/project B01 E001 E002 E003
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

v0.8 完整测试：`82/82` 通过。

## 更新记录

见 [CHANGELOG.md](CHANGELOG.md)。

## License

[MIT](LICENSE)
