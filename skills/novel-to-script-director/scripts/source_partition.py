#!/usr/bin/env python3
"""Deterministic semantic-unit partition planning and analysis-shard merging."""
from __future__ import annotations

import copy
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


def analysis_idempotency_key(
    source_unit_id: str, content_sha256: str, analysis_contract_version: int
) -> str:
    return f"{source_unit_id}:{content_sha256}:v{analysis_contract_version}"


def validate_chapter_analysis_registry(
    registry: dict[str, Any]
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    if not isinstance(registry, dict) or registry.get("schema_version") != 1:
        return [issue("analysis_registry_schema_invalid", "章节分析登记表 schema_version 必须为1")]
    records = registry.get("records")
    if not isinstance(records, list):
        return [issue("analysis_registry_records_invalid", "章节分析登记表 records 必须是数组")]
    seen: set[str] = set()
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            errors.append(issue("analysis_registry_record_invalid", "章节分析登记必须是对象", record_index=index))
            continue
        unit_id = record.get("source_unit_id")
        content_hash = record.get("content_sha256")
        contract_version = record.get("analysis_contract_version")
        if not isinstance(unit_id, str) or not unit_id:
            errors.append(issue("analysis_registry_source_unit_invalid", "章节分析登记缺少 source_unit_id", record_index=index))
            continue
        if not isinstance(content_hash, str) or not content_hash:
            errors.append(issue("analysis_registry_content_hash_invalid", "章节分析登记缺少 content_sha256", source_unit_id=unit_id))
            continue
        if type(contract_version) is not int or contract_version < 1:
            errors.append(issue("analysis_registry_contract_version_invalid", "analysis_contract_version 必须是正整数", source_unit_id=unit_id))
            continue
        expected_key = analysis_idempotency_key(unit_id, content_hash, contract_version)
        actual_key = record.get("idempotency_key")
        if actual_key != expected_key:
            errors.append(issue("analysis_registry_hash_mismatch", "分析登记幂等键与章节哈希或契约版本不一致", source_unit_id=unit_id))
        if expected_key in seen:
            errors.append(issue("source_analysis_idempotency_conflict", "同一章节、哈希和分析契约存在多个登记", source_unit_id=unit_id))
        seen.add(expected_key)
        if record.get("analysis_status") not in {"pending", "analyzed", "invalidated"}:
            errors.append(issue("analysis_registry_status_invalid", "analysis_status 必须为 pending/analyzed/invalidated", source_unit_id=unit_id))
        for field in ("analysis_path", "analysis_sha256"):
            if record.get("analysis_status") == "analyzed" and (
                not isinstance(record.get(field), str) or not record[field]
            ):
                errors.append(issue("analysis_registry_artifact_invalid", f"已分析记录缺少 {field}", source_unit_id=unit_id))
    return errors


def record_chapter_analysis(
    registry: dict[str, Any],
    *,
    source_unit_id: str,
    content_sha256: str,
    analysis_contract_version: int,
    analysis_path: str,
    analysis_sha256: str,
) -> dict[str, Any]:
    errors = validate_chapter_analysis_registry(registry)
    if errors:
        raise PartitionError("analysis_registry_invalid")
    key = analysis_idempotency_key(
        source_unit_id, content_sha256, analysis_contract_version
    )
    records = registry["records"]
    if any(
        isinstance(record, dict)
        and record.get("idempotency_key") == key
        and record.get("analysis_status") != "invalidated"
        for record in records
    ):
        raise PartitionError("source_unit_reanalysis_forbidden")
    result = copy.deepcopy(registry)
    result["records"].append(
        {
            "source_unit_id": source_unit_id,
            "content_sha256": content_sha256,
            "analysis_contract_version": analysis_contract_version,
            "analysis_status": "analyzed",
            "analysis_path": analysis_path,
            "analysis_sha256": analysis_sha256,
            "idempotency_key": key,
        }
    )
    return result


def validate_rolling_source_progress(
    progress: dict[str, Any]
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    if not isinstance(progress, dict) or progress.get("schema_version") != 1:
        return [issue("rolling_progress_schema_invalid", "滚动来源进度 schema_version 必须为1")]
    batch_id = progress.get("current_batch_id")
    if not isinstance(batch_id, str) or not batch_id:
        errors.append(issue("rolling_progress_batch_invalid", "滚动来源进度缺少 current_batch_id"))
    carryover = progress.get("carryover_event_ids", [])
    if not isinstance(carryover, list) or not all(isinstance(value, str) and value for value in carryover):
        errors.append(issue("carryover_analysis_missing", "carryover_event_ids 必须是字符串数组"))
        carryover = []
    consumption = progress.get("event_consumption", {})
    if not isinstance(consumption, dict):
        errors.append(issue("rolling_progress_consumption_invalid", "event_consumption 必须是对象"))
        consumption = {}
    allowed = {"unconsumed", "partially_consumed", "consumed", "invalidated"}
    for event_id, status in consumption.items():
        if not isinstance(event_id, str) or status not in allowed:
            errors.append(
                issue(
                    "rolling_progress_consumption_status_invalid",
                    "事件消费状态必须为 unconsumed/partially_consumed/consumed/invalidated",
                    event_id=event_id,
                    status=status,
                )
            )
    missing = [event_id for event_id in carryover if event_id not in consumption]
    if missing:
        errors.append(issue("carryover_analysis_missing", "carryover事件缺少消费状态", event_ids=missing))
    next_read_start = progress.get("next_read_start")
    if next_read_start is not None and (
        not isinstance(next_read_start, str) or not next_read_start
    ):
        errors.append(issue("rolling_progress_next_read_invalid", "next_read_start 必须是字符串或null"))
    return errors


def build_rolling_source_plan(
    source_corpus: dict[str, Any],
    registry: dict[str, Any],
    progress: dict[str, Any],
    *,
    window_size: int = 3,
) -> dict[str, Any]:
    if type(window_size) is not int or window_size < 1:
        raise PartitionError("rolling_window_size_invalid")
    registry_errors = validate_chapter_analysis_registry(registry)
    if registry_errors:
        raise PartitionError("analysis_registry_invalid")
    progress_errors = validate_rolling_source_progress(progress)
    if progress_errors:
        raise PartitionError("rolling_source_progress_invalid")
    ordered = _ordered_units(source_corpus)
    corpus_hashes = {
        unit["source_unit_id"]: unit.get("content_sha256") for unit in ordered
    }
    analyzed = {
        record["source_unit_id"]
        for record in registry["records"]
        if isinstance(record, dict)
        and record.get("analysis_status") == "analyzed"
        and corpus_hashes.get(record.get("source_unit_id")) == record.get("content_sha256")
    }
    ordered_ids = [unit["source_unit_id"] for unit in ordered]
    start_id = progress.get("next_read_start") if isinstance(progress, dict) else None
    start_index = ordered_ids.index(start_id) if start_id in ordered_ids else 0
    new_units = [unit_id for unit_id in ordered_ids[start_index:] if unit_id not in analyzed][
        :window_size
    ]
    carryover = progress.get("carryover_event_ids", []) if isinstance(progress, dict) else []
    if not isinstance(carryover, list) or not all(isinstance(value, str) for value in carryover):
        raise PartitionError("carryover_analysis_missing")
    return {
        "schema_version": 1,
        "current_batch_id": progress.get("current_batch_id") if isinstance(progress, dict) else None,
        "carryover_event_ids": list(carryover),
        "reusable_analyzed_source_unit_ids": [unit_id for unit_id in ordered_ids if unit_id in analyzed],
        "new_analysis_source_unit_ids": new_units,
        "next_read_start": new_units[0] if new_units else None,
    }
