# 滚动来源窗口停止与B01转入门禁设计

## 问题

v0.8.6允许`rolling_source_progress.current_batch_id`使用任意非空字符串。生产任务因此把`SA01/SA02/SA03`当作批次ID，连续规划来源窗口，而项目状态中没有已定义的`B01`。`plan-rolling-source-window`也未检查项目规格、批次定义或上一窗口是否已足够支撑当前批次。

结果是：滚动机制只实现了断点续读，没有强制执行“当前批次够用即停止扩窗并转入交付”。

## 目标行为

1. 滚动来源窗口只能绑定已确认的生产批次`B01/B02...`，`SA01`不得作为`current_batch_id`。
2. 规划首个窗口前，必须存在已确认的`rolling_batch` schema v2项目规格和已确认的当前批次。
3. `rolling_source_progress` schema v2必须记录：
   - `completed_window_count`；
   - `batch_readiness`：`initial_window | needs_more_source | ready_for_batch`；
   - `source_gap_reasons`。
4. 首窗完成后：
   - `ready_for_batch`：工具拒绝继续规划来源窗口，要求转入当前B01；
   - `needs_more_source`：只有存在非空具体缺口理由时，允许读取相邻新单元；
   - 不能继续沿用`initial_window`。
5. 旧schema v1可以继续被项目校验读取，但不得用于规划新的来源窗口；必须升级成schema v2。
6. 工具输出明确声明窗口完成后必须重新评估批次就绪状态，不能自动串行生成下一窗口。

## 数据流

```text
确认 rolling_batch 项目规格
→ define-batch B01
→ 建立 progress v2(initial_window, completed_window_count=0)
→ plan 首窗
→ 分析并登记
→ 写 progress v2：
   ├─ ready_for_batch → 禁止SA02，转入B01
   └─ needs_more_source + gap reasons → 允许下一相邻窗口
```

## 兼容与恢复

现有错误项目中的章节分析文件和registry继续有效。恢复时不删除、不重跑；只需确认项目规格、定义B01，并把当前进度迁移到绑定B01的schema v2。已多读的章节作为carryover保留。

## 验收

- `SA02`作为`current_batch_id`被机器拒绝。
- 没有已确认B01时不能规划来源窗口。
- 首窗可以规划。
- 首窗完成且`ready_for_batch`时，第二窗口被阻断。
- 只有`needs_more_source`和具体缺口理由同时存在时，第二窗口才允许。
- 完整测试和真实副本只读黑盒验证通过。
