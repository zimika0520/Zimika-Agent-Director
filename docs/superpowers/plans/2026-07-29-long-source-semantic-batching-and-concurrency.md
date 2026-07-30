# Long-Source Semantic Batching and Bounded Concurrency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Process novels of any length through chapter/event-aware source partitions with configurable capacity budgets and safe bounded concurrency, without hard-coded total word-count thresholds or concurrent writes to shared project state.

**Architecture:** Add a pure-Python partition/merge module that works on existing `source_corpus` units and temporary analysis shards. The orchestration layer may run independent shards concurrently, but all workers write isolated files and a single deterministic merge step produces the canonical payload before serial registration through `project_tool.py`.

**Tech Stack:** Python 3 standard library, `unittest`, JSON artifacts, existing `project_tool.py` state and artifact contracts.

## Global Constraints

- Never branch on total novel length such as `word_count > 100000`.
- Prefer chapter and event boundaries; use estimated token/complexity budgets only as capacity limits.
- Merge short adjacent semantic units; reject an oversized unit until upstream splits it at a scene/event boundary.
- Keep source order and exact source-unit coverage; no overlap, omission, or duplicate event IDs.
- Never allow concurrent workers to modify `project_state.json` or the same canonical artifact file.
- Worker concurrency is configurable and bounded; do not hard-code a fixed worker count.
- Preserve all current uncommitted source changes. Do not reset, stage, commit, push, install cache, or bump the plugin version while executing this plan unless the user separately authorizes release actions.
- Do not add model self-review loops. Validation in this plan is deterministic schema, coverage, ordering, and conflict validation only.

---

## File Structure

- Create `skills/novel-to-script-director/scripts/source_partition.py`: pure partition planning, shard validation, and deterministic merge functions.
- Create `skills/novel-to-script-director/scripts/test_source_partition.py`: focused unit and black-box tests for partitioning and merging.
- Modify `skills/novel-to-script-director/scripts/project_tool.py`: CLI wrappers for planning/validating/merging partitions; shared-state registration remains serial.
- Modify `skills/novel-to-script-director/scripts/test_project_tool.py`: command-level integration tests and project-state non-mutation checks.
- Modify `skills/novel-to-script-director/references/production-data-schemas.md`: source partition plan and analysis shard JSON contracts.
- Modify `skills/novel-to-script-director/references/artifact-contracts.md`: temporary shard lifecycle and canonical merge authority.
- Modify `skills/novel-to-script-director/references/workflow.md`: chapter/event-first batching and pipeline concurrency rules.
- Modify `skills/novel-to-script-director/SKILL.md`: public long-source behavior and safe concurrency policy.
- Modify `README.md`: command examples and user-visible behavior.

---

### Task 1: Define Dynamic Source Partition Contracts

**Files:**
- Modify: `skills/novel-to-script-director/references/production-data-schemas.md:5-58`
- Modify: `skills/novel-to-script-director/references/artifact-contracts.md:90-180`

**Interfaces:**
- Consumes: existing `source_corpus.source_units[]` fields `source_unit_id`, `source_locator`, `ordinal`, `content_path`, and `content_sha256`.
- Produces: optional source-unit metric fields plus `SourcePartitionPolicy`, `SourcePartitionPlan`, and `SourceAnalysisShard` JSON shapes consumed by `source_partition.py` in Task 2.

- [ ] **Step 1: Add source-unit metrics used by the partitioner**

Extend each `source_corpus.source_units[]` record with:

```json
{
  "character_count": 5400,
  "estimated_tokens": 3000,
  "complexity_points": 10
}
```

`character_count` is measured from the normalized source-unit text. `estimated_tokens` is calculated with the policy-provided `chars_per_token_estimate`, not a code-level constant. `complexity_points` is optional; absence means `0`, while projects that already extracted scene/event hints may supply a positive integer. Older corpora may be upgraded by creating a new source-corpus version with these metrics; do not overwrite the confirmed old version.

- [ ] **Step 2: Add the source partition policy schema**

Add this contract to `production-data-schemas.md`:

```json
{
  "schema_version": 1,
  "policy": {
    "max_input_tokens": 64000,
    "reserved_output_tokens": 12000,
    "chars_per_token_estimate": 1.8,
    "max_complexity_points": 100,
    "concurrency_mode": "bounded",
    "max_parallel_tasks": "auto",
    "single_state_writer": true
  }
}
```

Document that the numbers above are examples only. Runtime values are supplied by the active orchestration context or explicit project configuration; the validator must not inject these example values as defaults. `max_parallel_tasks` accepts `"auto"` or a positive integer.

- [ ] **Step 3: Add the source partition plan schema**

Add this exact shape:

```json
{
  "schema_version": 1,
  "source_corpus_ref": {"artifact_key": "source_corpus", "version": 1},
  "policy": {
    "max_input_tokens": 64000,
    "reserved_output_tokens": 12000,
    "chars_per_token_estimate": 1.8,
    "max_complexity_points": 100,
    "concurrency_mode": "bounded",
    "max_parallel_tasks": "auto",
    "single_state_writer": true
  },
  "partitions": [
    {
      "partition_id": "SP001",
      "ordinal": 1,
      "source_unit_ids": ["SRC-CH001", "SRC-CH002"],
      "estimated_input_tokens": 12000,
      "complexity_points": 24,
      "previous_partition_id": null,
      "next_partition_id": "SP002"
    }
  ]
}
```

State that a partition contains complete source units only. If one source unit exceeds the available budget, upstream normalization must split it by scene/event boundary and create new stable source-unit IDs.

- [ ] **Step 4: Add the analysis shard schema**

Add this exact shape:

```json
{
  "schema_version": 1,
  "partition_id": "SP001",
  "source_unit_ids": ["SRC-CH001", "SRC-CH002"],
  "units": [
    {
      "source_unit_id": "SRC-CH001",
      "status": "ready",
      "events": []
    }
  ]
}
```

Require one shard per partition, exact `source_unit_ids` equality with the plan, unique event IDs across all shards, and no shared-state writes from workers.

- [ ] **Step 5: Document temporary and canonical authority**

Add to `artifact-contracts.md`:

```text
Temporary source-analysis shards are worker outputs, not approved project artifacts.
Workers write only under tmp/source-analysis/<run-id>/<partition-id>.json.
A single merge process validates all shards and writes one canonical payload.
Only the canonical payload may be registered through project_tool.py.
```

- [ ] **Step 6: Review the documentation diff**

Run:

```bash
git diff --check -- ai-director/skills/novel-to-script-director/references/production-data-schemas.md ai-director/skills/novel-to-script-director/references/artifact-contracts.md
```

Expected: exit code `0` and no output.

---

### Task 2: Implement Pure Partition Planning and Merge Logic

**Files:**
- Create: `skills/novel-to-script-director/scripts/source_partition.py`
- Create: `skills/novel-to-script-director/scripts/test_source_partition.py`

**Interfaces:**
- Consumes: source-corpus payload, policy payload, and isolated shard payloads from Task 1.
- Produces:
  - `build_partition_plan(source_corpus: dict, policy: dict) -> dict`
  - `validate_partition_plan(plan: dict, source_corpus: dict) -> list[dict]`
  - `validate_analysis_shards(plan: dict, shards: list[dict]) -> list[dict]`
  - `merge_analysis_shards(plan: dict, shards: list[dict]) -> dict`

- [ ] **Step 1: Write failing unit tests for semantic-unit coverage**

Create `test_source_partition.py` with:

```python
import unittest

import source_partition


class SourcePartitionTests(unittest.TestCase):
    def source_corpus(self):
        return {
            "schema_version": 1,
            "source_units": [
                {"source_unit_id": "SU001", "ordinal": 1, "estimated_tokens": 3000, "complexity_points": 10},
                {"source_unit_id": "SU002", "ordinal": 2, "estimated_tokens": 2000, "complexity_points": 8},
                {"source_unit_id": "SU003", "ordinal": 3, "estimated_tokens": 4000, "complexity_points": 12},
            ],
        }

    def policy(self):
        return {
            "max_input_tokens": 8000,
            "reserved_output_tokens": 2000,
            "chars_per_token_estimate": 1.8,
            "max_complexity_points": 30,
            "concurrency_mode": "bounded",
            "max_parallel_tasks": "auto",
            "single_state_writer": True,
        }

    def test_build_partition_plan_merges_adjacent_units_without_splitting(self):
        plan = source_partition.build_partition_plan(self.source_corpus(), self.policy())
        self.assertEqual(
            [item["source_unit_ids"] for item in plan["partitions"]],
            [["SU001", "SU002"], ["SU003"]],
        )

    def test_validate_partition_plan_rejects_overlap_and_omission(self):
        plan = source_partition.build_partition_plan(self.source_corpus(), self.policy())
        plan["partitions"][1]["source_unit_ids"] = ["SU002"]
        codes = {item["code"] for item in source_partition.validate_partition_plan(plan, self.source_corpus())}
        self.assertIn("partition_source_unit_duplicate", codes)
        self.assertIn("partition_source_unit_missing", codes)

    def test_oversized_semantic_unit_is_rejected_not_arbitrarily_split(self):
        corpus = self.source_corpus()
        corpus["source_units"][0]["estimated_tokens"] = 7000
        with self.assertRaisesRegex(source_partition.PartitionError, "partition_unit_over_budget"):
            source_partition.build_partition_plan(corpus, self.policy())
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
cd skills/novel-to-script-director/scripts
PYTHONDONTWRITEBYTECODE=1 python3 test_source_partition.py
```

Expected: failure because `source_partition.py` does not exist.

- [ ] **Step 3: Implement policy validation and contiguous packing**

Create `source_partition.py` with these public definitions:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class PartitionError(ValueError):
    """Raised when partition planning or shard merging violates the contract."""


@dataclass(frozen=True)
class PartitionBudget:
    max_input_tokens: int
    reserved_output_tokens: int
    max_complexity_points: int

    @property
    def available_input_tokens(self) -> int:
        return self.max_input_tokens - self.reserved_output_tokens


def issue(code: str, message: str, **location: Any) -> dict[str, Any]:
    return {"code": code, "message": message, **location}


def parse_budget(policy: dict[str, Any]) -> PartitionBudget:
    max_input = policy.get("max_input_tokens")
    reserve = policy.get("reserved_output_tokens")
    complexity = policy.get("max_complexity_points")
    if not isinstance(max_input, int) or max_input <= 0:
        raise PartitionError("partition_policy_max_input_invalid")
    if not isinstance(reserve, int) or reserve < 0 or reserve >= max_input:
        raise PartitionError("partition_policy_output_reserve_invalid")
    if not isinstance(complexity, int) or complexity <= 0:
        raise PartitionError("partition_policy_complexity_invalid")
    if policy.get("single_state_writer") is not True:
        raise PartitionError("partition_policy_single_writer_required")
    workers = policy.get("max_parallel_tasks")
    if workers != "auto" and (not isinstance(workers, int) or workers <= 0):
        raise PartitionError("partition_policy_workers_invalid")
    return PartitionBudget(max_input, reserve, complexity)
```

Implement `build_partition_plan()` by sorting units by `ordinal`. For each unit, require positive integer `estimated_tokens`; treat missing `complexity_points` as `0` and reject non-integer or negative values. Append complete adjacent units while both token and complexity budgets remain within limits, and link `previous_partition_id`/`next_partition_id`. Never split a source unit inside this function. Report `partition_unit_metrics_missing` when the source corpus was not upgraded with token metrics.

- [ ] **Step 4: Implement exact coverage validation**

Implement `validate_partition_plan()` so it reports these codes:

```text
partition_source_unit_unknown
partition_source_unit_duplicate
partition_source_unit_missing
partition_order_invalid
partition_link_invalid
partition_budget_exceeded
partition_complexity_exceeded
```

The function must compare the flattened partition unit sequence with source-corpus units sorted by `ordinal`.

- [ ] **Step 5: Write failing tests for shard merge authority**

Add:

```python
    def test_merge_rejects_missing_partition_and_duplicate_event_id(self):
        plan = source_partition.build_partition_plan(self.source_corpus(), self.policy())
        shards = [
            {
                "schema_version": 1,
                "partition_id": "SP001",
                "source_unit_ids": ["SU001", "SU002"],
                "units": [
                    {"source_unit_id": "SU001", "status": "ready", "events": [{"event_id": "EV001"}]},
                    {"source_unit_id": "SU002", "status": "ready", "events": [{"event_id": "EV001"}]},
                ],
            }
        ]
        codes = {item["code"] for item in source_partition.validate_analysis_shards(plan, shards)}
        self.assertIn("analysis_shard_partition_missing", codes)
        self.assertIn("analysis_shard_event_duplicate", codes)

    def test_merge_orders_units_by_partition_and_source_order(self):
        plan = source_partition.build_partition_plan(self.source_corpus(), self.policy())
        shards = [
            {"schema_version": 1, "partition_id": "SP002", "source_unit_ids": ["SU003"], "units": [{"source_unit_id": "SU003", "status": "ready", "events": []}]},
            {"schema_version": 1, "partition_id": "SP001", "source_unit_ids": ["SU001", "SU002"], "units": [{"source_unit_id": "SU001", "status": "ready", "events": []}, {"source_unit_id": "SU002", "status": "ready", "events": []}]},
        ]
        merged = source_partition.merge_analysis_shards(plan, shards)
        self.assertEqual([unit["source_unit_id"] for unit in merged["units"]], ["SU001", "SU002", "SU003"])
```

- [ ] **Step 6: Implement shard validation and deterministic merge**

Implement `validate_analysis_shards()` and `merge_analysis_shards()` with exact partition equality, exact unit equality, unique `event_id`, and canonical ordering. `merge_analysis_shards()` must raise `PartitionError("analysis_shard_validation_failed")` if validation returns any issue.

- [ ] **Step 7: Run focused tests**

Run:

```bash
cd skills/novel-to-script-director/scripts
PYTHONDONTWRITEBYTECODE=1 python3 test_source_partition.py
```

Expected: all tests pass.

---

### Task 3: Add Read-Only Planning and Single-Writer Merge Commands

**Files:**
- Modify: `skills/novel-to-script-director/scripts/project_tool.py:10-25, 2565-2575, 9935-10130`
- Modify: `skills/novel-to-script-director/scripts/test_project_tool.py:39-end`

**Interfaces:**
- Consumes: Task 2 functions.
- Produces CLI commands:
  - `plan-source-partitions <project> --source-corpus <path> --policy <path> --output <path>`
  - `merge-source-analysis-shards <project> --plan <path> --shard-dir <path> --output <path>`

- [ ] **Step 1: Write failing command tests**

Add tests that call `project_tool.main()` and assert:

```python
    def test_plan_source_partitions_does_not_modify_project_state(self):
        before = (self.project / "project_state.json").read_bytes()
        exit_code = project_tool.main([
            "plan-source-partitions",
            str(self.project),
            "--source-corpus", str(self.project / "01_原著解析/source_corpus.json"),
            "--policy", str(self.project / "01_原著解析/partition_policy.json"),
            "--output", str(self.project / "tmp/source-analysis/run-001/partition-plan.json"),
        ])
        self.assertEqual(exit_code, 0)
        self.assertEqual((self.project / "project_state.json").read_bytes(), before)

    def test_merge_source_analysis_shards_writes_only_requested_output(self):
        exit_code = project_tool.main([
            "merge-source-analysis-shards",
            str(self.project),
            "--plan", str(self.project / "tmp/source-analysis/run-001/partition-plan.json"),
            "--shard-dir", str(self.project / "tmp/source-analysis/run-001/shards"),
            "--output", str(self.project / "01_原著解析/source_event_index_candidate.json"),
        ])
        self.assertEqual(exit_code, 0)
        self.assertTrue((self.project / "01_原著解析/source_event_index_candidate.json").is_file())
```

- [ ] **Step 2: Run focused command tests and verify failure**

Run:

```bash
cd skills/novel-to-script-director/scripts
PYTHONDONTWRITEBYTECODE=1 python3 test_project_tool.py ProjectToolTests.test_plan_source_partitions_does_not_modify_project_state ProjectToolTests.test_merge_source_analysis_shards_writes_only_requested_output
```

Expected: failure because the commands are not registered.

- [ ] **Step 3: Add command handlers**

Add `import source_partition` beside the existing standard-library/local imports. Add these path-safe helpers next to `atomic_write_json()`:

```python
def read_json_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ToolError(f"无法读取 JSON：{path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ToolError(f"JSON 顶层必须是对象：{path}")
    return payload


def resolve_project_input(project_path: Path, raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    path = path if path.is_absolute() else project_path / path
    path = path.resolve()
    if project_path != path and project_path not in path.parents:
        raise ToolError("输入路径必须位于项目目录内")
    if not path.is_file() and not path.is_dir():
        raise ToolError(f"输入路径不存在：{path}")
    return path


def resolve_project_output(project_path: Path, raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    path = path if path.is_absolute() else project_path / path
    path = path.resolve()
    if project_path != path and project_path not in path.parents:
        raise ToolError("输出路径必须位于项目目录内")
    return path
```

Add the handlers:

```python
def command_plan_source_partitions(args: argparse.Namespace) -> int:
    project_path, _state = load_state(args.project)
    source_corpus = read_json_file(resolve_project_input(project_path, args.source_corpus))
    policy = read_json_file(resolve_project_input(project_path, args.policy))
    plan = source_partition.build_partition_plan(source_corpus, policy["policy"])
    output = resolve_project_output(project_path, args.output)
    atomic_write_json(output, plan)
    print_json({"ok": True, "output": str(output), "partition_count": len(plan["partitions"])})
    return 0


def command_merge_source_analysis_shards(args: argparse.Namespace) -> int:
    project_path, _state = load_state(args.project)
    plan = read_json_file(resolve_project_input(project_path, args.plan))
    shard_dir = resolve_project_input(project_path, args.shard_dir)
    shards = [read_json_file(path) for path in sorted(shard_dir.glob("*.json"))]
    payload = source_partition.merge_analysis_shards(plan, shards)
    output = resolve_project_output(project_path, args.output)
    atomic_write_json(output, payload)
    print_json({"ok": True, "output": str(output), "unit_count": len(payload["units"])})
    return 0
```


- [ ] **Step 4: Register parser subcommands**

Add parser definitions in `build_parser()` with all paths required. Do not add implicit token-budget defaults.

- [ ] **Step 5: Run focused tests**

Run the command from Step 2 again.

Expected: both tests pass and `project_state.json` remains byte-identical.

---

### Task 4: Document Safe Bounded Concurrency and Pipeline Scheduling

**Files:**
- Modify: `skills/novel-to-script-director/SKILL.md:60-110`
- Modify: `skills/novel-to-script-director/references/workflow.md:1-130`
- Modify: `README.md:50-175`

**Interfaces:**
- Consumes: Task 1 contracts and Task 3 commands.
- Produces: orchestration rules used by Codex/Claude workers without requiring a new model-review stage.

- [ ] **Step 1: Replace length-threshold language with universal dynamic batching**

Document this rule verbatim:

```text
All source lengths use the same path: semantic source units first, capacity budgeting second.
Total novel word count never selects a separate workflow.
```

- [ ] **Step 2: Document safe parallel work**

Mark these operations as parallel-safe after source IDs and input versions are frozen:

```text
- independent source-analysis shards
- character/scene/prop/dialogue extraction into disjoint files
- DOCX and HTML rendering into separate output files
```

Mark these operations as serial-authority operations:

```text
- canonical character/location/event ID merge
- project_state.json mutation
- global timeline merge
- continuity ledger merge
- adjacent-episode final confirmation
- shared character-anchor version update
```

- [ ] **Step 3: Document pipeline concurrency**

Add the supported pipeline:

```text
E001 script confirmed -> E001 extraction may run in parallel while E002 source context is prepared.
E001 shot plan confirmed -> E001 DOCX and HTML render in parallel while E002 script drafting begins.
E002 cannot be finally confirmed until E001 end state is current.
```

- [ ] **Step 4: Add exact command examples**

Add examples for `plan-source-partitions` and `merge-source-analysis-shards`, with worker outputs under `tmp/source-analysis/<run-id>/shards/`.

- [ ] **Step 5: Run documentation checks**

Run:

```bash
git diff --check -- ai-director/skills/novel-to-script-director/SKILL.md ai-director/skills/novel-to-script-director/references/workflow.md ai-director/README.md
```

Expected: exit code `0` and no output.

---

### Task 5: Run One Long-Source Black-Box Fixture

**Files:**
- Modify: `skills/novel-to-script-director/scripts/test_source_partition.py`
- Modify: `skills/novel-to-script-director/scripts/test_project_tool.py`

**Interfaces:**
- Consumes: all previous tasks.
- Produces: one evidence-producing fixture proving dynamic batching and isolated concurrent-worker outputs.

- [ ] **Step 1: Add a fixture with short, normal, and oversized semantic units**

Build a corpus containing:

```text
SU001 and SU002: short adjacent chapters that should merge.
SU003: a normal chapter that forms the next partition.
SU004: an oversized chapter that must fail until split into SU004-A and SU004-B.
```

- [ ] **Step 2: Verify oversized-unit failure**

Run the partition command and assert code `partition_unit_over_budget`.

- [ ] **Step 3: Split the oversized unit at a declared scene boundary**

Replace `SU004` with `SU004-A` and `SU004-B`, each with unique ordinal and locator, then rerun planning.

Expected: all source units appear exactly once and in order.

- [ ] **Step 4: Produce isolated shard files and merge once**

Write one JSON file per partition under a temporary shard directory, merge them, and assert:

```python
self.assertEqual(merged_unit_ids, expected_unit_ids)
self.assertEqual(len(merged_event_ids), len(set(merged_event_ids)))
self.assertEqual(state_before, state_after)
```

- [ ] **Step 5: Run focused and full verification once**

Run:

```bash
cd skills/novel-to-script-director/scripts
PYTHONDONTWRITEBYTECODE=1 python3 test_source_partition.py
PYTHONDONTWRITEBYTECODE=1 python3 test_project_tool.py
python3 -m py_compile project_tool.py source_partition.py
cd ../../../..
git diff --check
```

Expected: all tests pass, compilation succeeds, and `git diff --check` has no output.

- [ ] **Step 6: Record status without release actions**

Report changed files, test counts, and fixture result. Do not commit, push, install cache, or change version metadata until the user explicitly authorizes those actions.
