# AI Director 正式交付来源证明与生产门禁设计

日期：2026-08-03

## 目标

修复生产执行中可以绕过标准入口、用临时脚本覆盖最终文件、再把“文件存在”误报为“正式交付完成”的全局问题。

本设计不试图阻止操作系统层面的任意文件写入。它通过可验证的来源证明，确保只有符合标准入口、标准输入、标准模板和当前版本的产物能够获得 `official_delivery: true`。

## 已确认根因

1. `render-storyboard` 和 `render-episode-delivery` 未统一调用现有 `require_execution_ready`。
2. `render_storyboard.render()` 可接收调用方构造的 `state` 和 `preloaded`，直接调用官方函数不等于走过官方工作流。
3. 当前逐集交付没有登记输入版本、输入哈希、生成入口、模板契约和输出哈希。
4. 最终目录中的 DOCX/HTML 可以被任意脚本覆盖，现有流程无法区分标准产物和旁路产物。
5. `agent_runtime.build_result_envelope()` 没有对应 CLI，工作智能体容易手写错误结果信封。
6. 未绑定宿主任务的活动租约缺少完整回归证据，可能被过早判定失联并消耗 attempt。
7. AI 视频下游要求的事件索引 schema v2、`beats` 和 `episode_scopes` 检查发生过晚。

## 方案选择

采用“统一生产门禁 + 正式交付来源证明”。

不采用目录权限隔离，因为同一用户进程仍可绕过，且无法证明输入和模板正确。不采用纯工作流文字约束，因为本次故障已经证明行为要求不能替代代码级保证。

## 架构

### 1. 统一生产命令门禁

复用现有 `agent_runtime`、执行控制、环境指纹和状态锁，不新增第二套运行时。

所有生产渲染和正式交付验收入口在读取或写入交付文件前统一执行：

- 项目执行模式必须为 `production`。
- `startup-preflight` 必须已经得到 `execution_ready`。
- 当前插件、Skill、`agent_runtime.py`、`project_tool.py` 和环境指纹必须与预检记录一致。
- 存在活动阻断时不得继续渲染或验收。

`render-storyboard` 继续作为只读可视化入口，但其产物默认是可视化候选；只有 `render-episode-delivery` 生成并登记完整来源证明后才成为正式交付。

### 2. 已验证只读输入

`episode_delivery_inputs()` 继续作为逐集交付的唯一输入装载和校验入口，并返回内部只读输入对象。该对象包含：

- 当前确认的文学剧本及边界报告；
- 制作提取数据；
- 人物、场景、道具和风格锚点；
- 当前确认的 AI 分镜计划；
- 所有输入制品的 artifact key、version、文件 SHA-256；
- 规则、运行时、插件、输出契约和 schema 版本。

渲染器不再把调用方任意构造的 `state/preloaded` 视为正式交付依据。内部测试或直接调用仍可生成候选 HTML，但不能生成或登记正式交付清单。

### 3. 逐集正式交付清单

`render-episode-delivery` 在项目状态锁内完成以下操作：

1. 获取并冻结已验证输入。
2. 根据输入指纹判断是否可以安全复用现有渲染缓存。
3. 在临时位置生成 DOCX 和 HTML。
4. 校验 DOCX ZIP 完整性和 HTML 标准模板来源标记。
5. 原子替换最终两个文件。
6. 写入并登记 `episode_delivery_manifest:E001`。
7. 立即运行正式交付验收。

清单至少记录：

- `schema_version`；
- `episode_id`；
- 固定入口 `project_tool render-episode-delivery`；
- 插件版本、运行时版本、规则版本；
- DOCX 渲染契约和 HTML 模板契约版本；
- 精确输入制品、版本、路径和 SHA-256；
- 统一输入指纹；
- DOCX/HTML 最终相对路径和 SHA-256；
- 故事板缓存输入指纹；
- 生成时间和复用状态。

清单使用项目相对路径，不允许写死任何小说名称或项目绝对路径。

### 4. 正式交付验收

新增 `validate-episode-delivery <project> <episode>`。

验收重新读取当前项目状态和文件，检查：

- 当前生产预检仍有效；
- 清单是项目状态中当前版本的 `episode_delivery_manifest:E001`；
- 清单声明的标准入口和契约版本正确；
- 所有输入制品仍是当前确认版本且文件哈希一致；
- 当前输入指纹与清单一致；
- DOCX 是可打开的 ZIP，必需 Word XML 存在；
- HTML 包含标准渲染器和模板契约标记；
- 两个输出文件存在且哈希与清单一致；
- 输出路径位于当前 `project_root` 的正式逐集交付目录。

全部通过才输出：

```json
{
  "official_delivery": true,
  "manifest": "...",
  "input_fingerprint": "...",
  "outputs": {
    "docx": {"path": "...", "sha256": "..."},
    "html": {"path": "...", "sha256": "..."}
  }
}
```

任一项失败时返回 `official_delivery: false` 和明确错误码。文件仍可保留，但不能被报告为正式完成。

### 5. 智能体结果信封

新增 `write-agent-result` CLI，直接复用 `agent_runtime.build_result_envelope()`。

工作智能体只提交：

- task id；
- attempt；
- 候选文件路径；
- 状态和错误分类；
- 检查点；
- 运行时间字段。

CLI 负责读取任务包、校验写入范围、补齐统一 telemetry 并原子写入结果目录。`accept-agent-result` 继续作为唯一验收和登记入口。

### 6. 租约和受控恢复

保留现有幂等键和 attempt 模型：

- 活动宿主任务存在时复用；
- 没有宿主绑定但 `activity_lease_expires_at` 未过期时仍复用，不增加 attempt；
- 租约过期且无有效结果或检查点时标记 `abandoned/recovery_required`；
- 使用原幂等键增加一次 attempt；
- 连续两次无效尝试后阻断；
- 已接受结果永远优先，不允许旧 attempt 形成第二个有效结果。

### 7. AI 视频契约提前门禁

当 `delivery_target` 为 `ai_video` 或 `both` 时，在进入制作提取或 AI 分镜规划前检查：

- `source_event_index.schema_version == 2`；
- 存在并可校验 `beats`；
- 存在并覆盖目标集的 `episode_scopes`。

不满足时立即返回 `ai_video_source_contract_not_ready`，不得继续生成下游产物或临时兜底交付。

## 错误处理

- 预检缺失：`execution_preflight_required`。
- 环境或版本变化：`execution_preflight_stale`。
- 正式产物被覆盖：`episode_delivery_output_hash_mismatch`。
- 输入版本或哈希变化：`episode_delivery_input_stale`。
- 非标准 HTML：`episode_delivery_template_marker_missing`。
- 清单缺失：`episode_delivery_manifest_missing`。
- AI 视频来源契约过旧：`ai_video_source_contract_not_ready`。

所有失败只更新现有运行时的失败和阻断状态，不创建第二套状态文件。

## 测试

先写失败测试并确认其因缺少目标行为而失败，再实现代码。

定向测试至少覆盖：

1. 未预检时两个渲染入口都被拒绝。
2. 插件或环境指纹变化后渲染被拒绝。
3. 直接调用 renderer 并注入伪造状态不能形成正式交付。
4. 合法入口生成 DOCX、HTML 和登记清单，验收返回 `official_delivery: true`。
5. 同一输入重复执行复用结果，不重复实际渲染。
6. 输入版本或哈希变化后旧清单失效并重新渲染。
7. 输出文件被覆盖后正式验收失败。
8. 两个交付位置的 HTML 内容一致，且同一输入只实际渲染一次。
9. `write-agent-result` 生成可由 `accept-agent-result` 接受的 telemetry。
10. 未绑定宿主任务的租约未过期时不增加 attempt。
11. 租约过期后受控恢复，两次失联后阻断。
12. AI 视频 schema v1 事件索引在制作提取前被拒绝。
13. 既有边界审核、审批、幂等、检查点、串并行调度和错误分类不回归。

验证顺序：

1. 新增定向测试；
2. 受影响测试模块；
3. 全部现有自动化测试；
4. 全新隔离虚构项目的一集最小闭环。

闭环不生成图片、视频、音频或付费任务，不读取或修改任何真实小说项目。

## 修改边界

允许修改：

- `agent_runtime.py`；
- `project_tool.py`；
- `render_storyboard.py`；
- 必要的 DOCX 渲染模块；
- `test_project_tool.py` 及必要的通用测试 fixture；
- 本次设计、工作流和数据契约文档。

禁止：

- 针对小说名称或固定项目路径写特例；
- 修改真实小说项目；
- 开发简介模式；
- 覆盖或回退现有滚动来源改动；
- 修改安装缓存；
- 提交、推送或发布。

## 完成标准

只有同时满足以下条件才可报告修复完成：

- 定向测试实际通过；
- 全部现有自动化测试实际通过，或明确列出与本次无关的既有失败；
- 隔离项目完成一集 DOCX、HTML 和正式交付清单；
- `validate-episode-delivery` 返回 `official_delivery: true`；
- 覆盖任一输出文件后验证立即转为失败；
- 当前主源码工作区和所有真实小说项目保持未修改。
