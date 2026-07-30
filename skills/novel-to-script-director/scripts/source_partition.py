#!/usr/bin/env python3
"""Deterministic semantic-unit partition planning and analysis-shard merging."""
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
    if not isinstance(policy, dict):
        raise PartitionError("partition_policy_invalid")
    max_input = policy.get("max_input_tokens")
    reserve = policy.get("reserved_output_tokens")
    complexity = policy.get("max_complexity_points")
    if not isinstance(max_input, int) or isinstance(max_input, bool) or max_input <= 0:
        raise PartitionError("partition_policy_max_input_invalid")
    if (
        not isinstance(reserve, int)
        or isinstance(reserve, bool)
        or reserve < 0
        or reserve >= max_input
    ):
        raise PartitionError("partition_policy_output_reserve_invalid")
    if (
        not isinstance(complexity, int)
        or isinstance(complexity, bool)
        or complexity <= 0
    ):
        raise PartitionError("partition_policy_complexity_invalid")
    chars_per_token = policy.get("chars_per_token_estimate")
    if not isinstance(chars_per_token, (int, float)) or isinstance(chars_per_token, bool) or chars_per_token <= 0:
        raise PartitionError("partition_policy_chars_per_token_invalid")
    if policy.get("concurrency_mode") not in {"serial", "bounded"}:
        raise PartitionError("partition_policy_concurrency_mode_invalid")
    if policy.get("single_state_writer") is not True:
        raise PartitionError("partition_policy_single_writer_required")
    workers = policy.get("max_parallel_tasks")
    if workers != "auto" and (
        not isinstance(workers, int) or isinstance(workers, bool) or workers <= 0
    ):
        raise PartitionError("partition_policy_workers_invalid")
    return PartitionBudget(max_input, reserve, complexity)


def _ordered_units(source_corpus: dict[str, Any]) -> list[dict[str, Any]]:
    units = source_corpus.get("source_units") if isinstance(source_corpus, dict) else None
    if not isinstance(units, list) or not units:
        raise PartitionError("partition_source_units_missing")
    if not all(isinstance(unit, dict) for unit in units):
        raise PartitionError("partition_source_unit_invalid")
    ordered = sorted(units, key=lambda unit: unit.get("ordinal", 0))
    ids: set[str] = set()
    ordinals: set[int] = set()
    for unit in ordered:
        unit_id = unit.get("source_unit_id")
        ordinal = unit.get("ordinal")
        if not isinstance(unit_id, str) or not unit_id.strip():
            raise PartitionError("partition_source_unit_id_invalid")
        if unit_id in ids:
            raise PartitionError("partition_source_unit_id_duplicate")
        if not isinstance(ordinal, int) or isinstance(ordinal, bool) or ordinal <= 0:
            raise PartitionError("partition_source_unit_ordinal_invalid")
        if ordinal in ordinals:
            raise PartitionError("partition_source_unit_ordinal_duplicate")
        ids.add(unit_id)
        ordinals.add(ordinal)
    return ordered


def _unit_cost(unit: dict[str, Any]) -> tuple[int, int]:
    tokens = unit.get("estimated_tokens")
    complexity = unit.get("complexity_points", 0)
    if not isinstance(tokens, int) or isinstance(tokens, bool) or tokens <= 0:
        raise PartitionError("partition_unit_metrics_missing")
    if (
        not isinstance(complexity, int)
        or isinstance(complexity, bool)
        or complexity < 0
    ):
        raise PartitionError("partition_unit_complexity_invalid")
    return tokens, complexity


def build_partition_plan(
    source_corpus: dict[str, Any], policy: dict[str, Any]
) -> dict[str, Any]:
    budget = parse_budget(policy)
    ordered = _ordered_units(source_corpus)
    groups: list[dict[str, Any]] = []
    current_ids: list[str] = []
    current_tokens = 0
    current_complexity = 0

    def flush() -> None:
        nonlocal current_ids, current_tokens, current_complexity
        if current_ids:
            groups.append(
                {
                    "source_unit_ids": current_ids,
                    "estimated_input_tokens": current_tokens,
                    "complexity_points": current_complexity,
                }
            )
        current_ids = []
        current_tokens = 0
        current_complexity = 0

    for unit in ordered:
        unit_id = unit["source_unit_id"]
        tokens, complexity = _unit_cost(unit)
        if (
            tokens > budget.available_input_tokens
            or complexity > budget.max_complexity_points
        ):
            raise PartitionError(f"partition_unit_over_budget:{unit_id}")
        would_exceed = current_ids and (
            current_tokens + tokens > budget.available_input_tokens
            or current_complexity + complexity > budget.max_complexity_points
        )
        if would_exceed:
            flush()
        current_ids.append(unit_id)
        current_tokens += tokens
        current_complexity += complexity
    flush()

    partitions: list[dict[str, Any]] = []
    for index, group in enumerate(groups, 1):
        partition_id = f"SP{index:03d}"
        partitions.append(
            {
                "partition_id": partition_id,
                "ordinal": index,
                **group,
                "previous_partition_id": f"SP{index - 1:03d}" if index > 1 else None,
                "next_partition_id": f"SP{index + 1:03d}" if index < len(groups) else None,
            }
        )
    return {
        "schema_version": 1,
        "source_corpus_ref": source_corpus.get("artifact_ref"),
        "policy": dict(policy),
        "partitions": partitions,
    }


def validate_partition_plan(
    plan: dict[str, Any], source_corpus: dict[str, Any]
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    try:
        budget = parse_budget(plan.get("policy", {}))
        expected_units = _ordered_units(source_corpus)
    except PartitionError as exc:
        return [issue(str(exc).split(":", 1)[0], str(exc))]
    expected_ids = [unit["source_unit_id"] for unit in expected_units]
    known_ids = set(expected_ids)
    partitions = plan.get("partitions")
    if not isinstance(partitions, list) or not partitions:
        return [issue("partition_plan_empty", "分片计划必须包含 partitions")]
    flattened: list[str] = []
    seen: set[str] = set()
    for index, partition in enumerate(partitions, 1):
        if not isinstance(partition, dict):
            errors.append(issue("partition_record_invalid", "分片记录必须是对象", partition=index))
            continue
        expected_partition_id = f"SP{index:03d}"
        if partition.get("partition_id") != expected_partition_id or partition.get("ordinal") != index:
            errors.append(issue("partition_order_invalid", "分片编号或顺序不连续", partition=index))
        previous_expected = f"SP{index - 1:03d}" if index > 1 else None
        next_expected = f"SP{index + 1:03d}" if index < len(partitions) else None
        if partition.get("previous_partition_id") != previous_expected or partition.get("next_partition_id") != next_expected:
            errors.append(issue("partition_link_invalid", "分片前后链接不正确", partition=index))
        unit_ids = partition.get("source_unit_ids")
        if not isinstance(unit_ids, list) or not unit_ids:
            errors.append(issue("partition_source_units_empty", "分片不得为空", partition=index))
            continue
        tokens = 0
        complexity = 0
        for unit_id in unit_ids:
            if unit_id not in known_ids:
                errors.append(issue("partition_source_unit_unknown", "分片引用未知原著单元", source_unit_id=unit_id))
                continue
            if unit_id in seen:
                errors.append(issue("partition_source_unit_duplicate", "原著单元被多个分片重复覆盖", source_unit_id=unit_id))
            seen.add(unit_id)
            flattened.append(unit_id)
            source_unit = expected_units[expected_ids.index(unit_id)]
            try:
                unit_tokens, unit_complexity = _unit_cost(source_unit)
            except PartitionError as exc:
                errors.append(issue(str(exc), str(exc), source_unit_id=unit_id))
                continue
            tokens += unit_tokens
            complexity += unit_complexity
        if tokens > budget.available_input_tokens:
            errors.append(issue("partition_budget_exceeded", "分片超过输入容量预算", partition=index))
        if complexity > budget.max_complexity_points:
            errors.append(issue("partition_complexity_exceeded", "分片超过复杂度预算", partition=index))
    for unit_id in expected_ids:
        if unit_id not in seen:
            errors.append(issue("partition_source_unit_missing", "原著单元未被任何分片覆盖", source_unit_id=unit_id))
    if [unit_id for unit_id in flattened if unit_id in known_ids] != [unit_id for unit_id in expected_ids if unit_id in seen]:
        errors.append(issue("partition_order_invalid", "分片必须保持原著单元顺序"))
    return errors


def validate_analysis_shards(
    plan: dict[str, Any], shards: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    partitions = plan.get("partitions")
    if not isinstance(partitions, list):
        return [issue("analysis_partition_plan_invalid", "分片计划缺少 partitions")]
    expected = {
        partition.get("partition_id"): partition.get("source_unit_ids")
        for partition in partitions
        if isinstance(partition, dict)
    }
    shard_by_partition: dict[str, dict[str, Any]] = {}
    event_ids: set[str] = set()
    for shard_index, shard in enumerate(shards, 1):
        if not isinstance(shard, dict):
            errors.append(issue("analysis_shard_invalid", "分析分片必须是对象", shard=shard_index))
            continue
        partition_id = shard.get("partition_id")
        if not isinstance(partition_id, str) or partition_id not in expected:
            errors.append(issue("analysis_shard_partition_unknown", "分析分片引用未知 partition_id", shard=shard_index))
            continue
        if partition_id in shard_by_partition:
            errors.append(issue("analysis_shard_partition_duplicate", "同一 partition_id 存在多个分析分片", partition_id=partition_id))
            continue
        shard_by_partition[partition_id] = shard
        if shard.get("source_unit_ids") != expected[partition_id]:
            errors.append(issue("analysis_shard_scope_mismatch", "分析分片 source_unit_ids 与计划不一致", partition_id=partition_id))
        units = shard.get("units")
        if not isinstance(units, list):
            errors.append(issue("analysis_shard_units_invalid", "分析分片缺少 units", partition_id=partition_id))
            continue
        unit_ids = [unit.get("source_unit_id") for unit in units if isinstance(unit, dict)]
        if unit_ids != expected[partition_id]:
            errors.append(issue("analysis_shard_unit_coverage_invalid", "分析分片 units 未精确覆盖计划范围", partition_id=partition_id))
        for unit in units:
            if not isinstance(unit, dict):
                continue
            events = unit.get("events", [])
            if not isinstance(events, list):
                errors.append(issue("analysis_shard_events_invalid", "events 必须是数组", source_unit_id=unit.get("source_unit_id")))
                continue
            for event in events:
                event_id = event.get("event_id") if isinstance(event, dict) else None
                if not isinstance(event_id, str) or not event_id.strip():
                    errors.append(issue("analysis_shard_event_id_invalid", "事件缺少 event_id", source_unit_id=unit.get("source_unit_id")))
                elif event_id in event_ids:
                    errors.append(issue("analysis_shard_event_duplicate", "事件 ID 在多个分析结果中重复", event_id=event_id))
                else:
                    event_ids.add(event_id)
    for partition_id in expected:
        if partition_id not in shard_by_partition:
            errors.append(issue("analysis_shard_partition_missing", "缺少分析分片", partition_id=partition_id))
    return errors


def merge_analysis_shards(
    plan: dict[str, Any], shards: list[dict[str, Any]]
) -> dict[str, Any]:
    errors = validate_analysis_shards(plan, shards)
    if errors:
        raise PartitionError("analysis_shard_validation_failed")
    by_partition = {shard["partition_id"]: shard for shard in shards}
    units: list[dict[str, Any]] = []
    for partition in sorted(plan["partitions"], key=lambda item: item["ordinal"]):
        units.extend(by_partition[partition["partition_id"]]["units"])
    return {
        "schema_version": 1,
        "generated_from_partition_plan": {
            "schema_version": plan.get("schema_version"),
            "partition_ids": [item["partition_id"] for item in plan["partitions"]],
        },
        "units": units,
    }
