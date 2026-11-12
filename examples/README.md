# Demo source

`demo_story.md` 是仓库内原创的短示例，只用于验证 CLI 初始化、来源登记和项目状态读取。

```bash
python3 skills/novel-to-script-director/scripts/project_tool.py init \
  /tmp/zimika-agent-demo \
  --name "最后一班地铁" \
  --source examples/demo_story.md \
  --source-kind storyline \
  --expected-episodes 3

python3 skills/novel-to-script-director/scripts/project_tool.py show \
  /tmp/zimika-agent-demo --summary
```

运行示例前先退出仓库根目录的其他生产任务。示例只验证工程链路，不代表完整模型生成结果。
