#!/usr/bin/env python3
"""Synopsis-mode contracts for AI Director.

The synopsis mode is a controlled-expansion source policy, not a second
state machine. This module owns pure validation for synopsis facts,
feasibility, expansion decisions, and expression quality so the CLI keeps
reusing the existing project state and artifact gates.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any


SOURCE_MODE_SYNOPSIS = "synopsis"
SYNOPSIS_FACT_TYPES = {
    "character",
    "relationship",
    "setting",
    "ability",
    "event",
    "motivation",
    "ending",
    "constraint",
}
SYNOPSIS_PROTECTIONS = {"must_preserve", "flexible", "unknown"}
SYNOPSIS_VERDICTS = {"sufficient", "needs_user_input", "insufficient"}
SYNOPSIS_ANALYSIS_TYPES = {
    "conflict_nodes",
    "relationship_turns",
    "hook_candidates",
    "supporting_expansion_axes",
}
SYNOPSIS_ALLOWED_PURPOSES = {
    "school_life_event",
    "supporting_character",
    "supporting_opponent",
    "intermediate_conflict",
    "misunderstanding",
    "transition",
    "dialogue",
    "action",
    "reaction",
    "scene_transition",
    "environment_reaction",
}

SYNOPSIS_DEFAULT_POLICY = {
    "duration_seconds": {"min": 60, "max": 90},
    "minimum_shot_units": 21,
    "composition_policy": "unrestricted",
}

# Deterministic "AI smell" signals. These are warnings, not fake scores.
SYNOPSIS_GENERIC_PATTERNS = (
    ("眼底闪过", "generic_eye_emotion"),
    ("眼底划过", "generic_eye_emotion"),
    ("勾唇一笑", "generic_smile"),
    ("嘴角微扬", "generic_smile"),
    ("空气突然安静", "generic_air_silence"),
    ("气氛瞬间", "generic_atmosphere"),
    ("两人关系更进一步", "templated_relationship_progress"),
    ("突然传来一个声音", "templated_sudden_sound"),
    ("他不自觉", "generic_involuntary_gesture"),
    ("她忍不住", "generic_involuntary_gesture"),
)


def issue(code: str, message: str, **location: Any) -> dict[str, Any]:
    return {"code": code, "message": message, **location}


def default_synopsis_policy() -> dict[str, Any]:
    return {
        "duration_seconds": {"min": 60, "max": 90},
        "minimum_shot_units": 21,
        "composition_policy": "unrestricted",
    }


def validate_synopsis_policy(policy: Any) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    if not isinstance(policy, dict):
        return [issue("synopsis_policy_invalid", "synopsis_policy 必须是对象")]
    duration = policy.get("duration_seconds")
    if not isinstance(duration, dict):
        errors.append(issue("synopsis_duration_missing", "synopsis_policy.duration_seconds 必须包含 min 与 max"))
        duration = {}
    minimum = duration.get("min")
    maximum = duration.get("max")
    if type(minimum) is not int or type(maximum) is not int or minimum < 1 or maximum < minimum:
        errors.append(
            issue(
                "synopsis_duration_invalid",
                "synopsis_policy.duration_seconds 必须是 min <= max 的正整数区间",
            )
        )
    minimum_units = policy.get("minimum_shot_units")
    if type(minimum_units) is not int or minimum_units < 1:
        errors.append(
            issue(
                "synopsis_minimum_shot_units_invalid",
                "synopsis_policy.minimum_shot_units 必须是正整数",
            )
        )
    if policy.get("composition_policy") != "unrestricted":
        errors.append(
            issue(
                "synopsis_composition_policy_invalid",
                "synopsis_policy.composition_policy 当前只能为 unrestricted",
            )
        )
    return errors


def resolve_synopsis_policy(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict) and isinstance(payload.get("synopsis_policy"), dict):
        return payload["synopsis_policy"]
    return default_synopsis_policy()


def validate_synopsis_profile(profile: Any) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    if not isinstance(profile, dict):
        return [issue("synopsis_profile_invalid", "source_event_index 必须提供 synopsis_profile 对象")]
    facts = profile.get("facts")
    if not isinstance(facts, list) or not facts:
        errors.append(issue("synopsis_facts_missing", "synopsis_profile.facts 必须是非空数组"))
        facts = []
    fact_ids: set[str] = set()
    for index, fact in enumerate(facts, 1):
        if not isinstance(fact, dict):
            errors.append(issue("synopsis_fact_invalid", "简介事实必须是对象", fact_index=index))
            continue
        fact_id = fact.get("fact_id")
        if not isinstance(fact_id, str) or not fact_id.strip():
            errors.append(issue("synopsis_fact_id_invalid", "简介事实缺少 fact_id", fact_index=index))
        elif fact_id in fact_ids:
            errors.append(issue("synopsis_fact_id_duplicate", f"简介事实 ID 重复：{fact_id}", fact_index=index))
        else:
            fact_ids.add(fact_id)
        if fact.get("fact_type") not in SYNOPSIS_FACT_TYPES:
            errors.append(
                issue(
                    "synopsis_fact_type_invalid",
                    "fact_type 必须为 character/relationship/setting/ability/event/motivation/ending/constraint",
                    fact_index=index,
                )
            )
        if not isinstance(fact.get("fact_text"), str) or not fact["fact_text"].strip():
            errors.append(issue("synopsis_fact_text_missing", "简介事实缺少非空 fact_text", fact_index=index))
        source_refs = fact.get("source_refs")
        if not isinstance(source_refs, list) or not source_refs or not all(
            isinstance(value, str) and value.strip() for value in source_refs
        ):
            errors.append(issue("synopsis_fact_source_missing", "简介事实必须提供非空 source_refs", fact_index=index))
        if fact.get("protection") not in SYNOPSIS_PROTECTIONS:
            errors.append(
                issue(
                    "synopsis_fact_protection_invalid",
                    "protection 必须为 must_preserve/flexible/unknown",
                    fact_index=index,
                )
            )
    unknowns = profile.get("unknowns")
    if unknowns is not None and (
        not isinstance(unknowns, list)
        or not all(isinstance(value, dict) and isinstance(value.get("description"), str) and value["description"].strip() for value in unknowns)
    ):
        errors.append(
            issue(
                "synopsis_unknowns_invalid",
                "synopsis_profile.unknowns 必须是包含非空 description 的对象数组",
            )
        )
    analysis = profile.get("analysis")
    if analysis is not None:
        if not isinstance(analysis, dict):
            errors.append(issue("synopsis_analysis_invalid", "synopsis_profile.analysis 必须是对象"))
        else:
            for field in SYNOPSIS_ANALYSIS_TYPES:
                values = analysis.get(field)
                if not isinstance(values, list) or not values or not all(
                    isinstance(value, dict)
                    and isinstance(value.get("id"), str)
                    and value["id"].strip()
                    and isinstance(value.get("label"), str)
                    and value["label"].strip()
                    for value in values
                ):
                    errors.append(
                        issue(
                            "synopsis_analysis_invalid",
                            f"synopsis_profile.analysis.{field} 必须是非空 {field} 对象数组，每项包含 id 与 label",
                        )
                    )
    return errors


def _analysis_ids(profile: Any) -> dict[str, set[str]]:
    result = {field: set() for field in SYNOPSIS_ANALYSIS_TYPES}
    analysis = profile.get("analysis") if isinstance(profile, dict) else None
    if not isinstance(analysis, dict):
        return result
    for field in SYNOPSIS_ANALYSIS_TYPES:
        values = analysis.get(field)
        if isinstance(values, list):
            result[field] = {
                item.get("id")
                for item in values
                if isinstance(item, dict) and isinstance(item.get("id"), str)
            }
    return result


def validate_synopsis_feasibility(
    feasibility: Any,
    profile: Any,
    expected_episodes: int | None = None,
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    if not isinstance(feasibility, dict):
        return [issue("synopsis_feasibility_missing", "source_event_index 必须提供 synopsis_feasibility 对象")]
    requested = feasibility.get("requested_episodes")
    if type(requested) is not int or requested < 1:
        errors.append(issue("synopsis_requested_episodes_invalid", "synopsis_feasibility.requested_episodes 必须是正整数"))
        requested = None
    if expected_episodes is not None and requested != expected_episodes:
        errors.append(
            issue(
                "synopsis_requested_episodes_mismatch",
                "synopsis_feasibility.requested_episodes 必须与已确认项目规格 expected_episodes 一致",
                feasibility=requested,
                project_spec=expected_episodes,
            )
        )
    verdict = feasibility.get("verdict")
    if verdict not in SYNOPSIS_VERDICTS:
        errors.append(
            issue(
                "synopsis_verdict_invalid",
                "synopsis_feasibility.verdict 必须为 sufficient/needs_user_input/insufficient，不接受 passed 放行",
            )
        )
    if verdict == "sufficient":
        blocking_reasons = feasibility.get("blocking_reasons")
        if not isinstance(blocking_reasons, list) or blocking_reasons:
            errors.append(
                issue(
                    "synopsis_sufficient_with_blocker",
                    "verdict=sufficient 时 blocking_reasons 必须为空数组",
                )
            )
        slots = feasibility.get("episode_slots")
        if not isinstance(slots, list) or not slots:
            errors.append(issue("synopsis_episode_slots_missing", "verdict=sufficient 必须提供覆盖全部集的 episode_slots"))
            slots = []
        count = requested if type(requested) is int else expected_episodes
        if type(count) is not int or count < 1:
            count = len(slots)
        if isinstance(slots, list):
            expected_ids = {f"E{number:03d}" for number in range(1, count + 1)}
            actual_ids = {
                item.get("episode_id")
                for item in slots
                if isinstance(item, dict) and isinstance(item.get("episode_id"), str)
            }
            if len(slots) != len(expected_ids) or actual_ids != expected_ids:
                errors.append(
                    issue(
                        "synopsis_episode_slots_coverage_invalid",
                        "episode_slots 必须逐一覆盖 E001...EN，不能缺集、重集或多集",
                    )
                )
            analysis_ids = _analysis_ids(profile)
            valid_change_ids = set().union(*analysis_ids.values())
            seen_changes: set[tuple[str, str]] = set()
            for index, slot in enumerate(slots, 1):
                if not isinstance(slot, dict):
                    errors.append(issue("synopsis_episode_slot_invalid", "episode_slots 条目必须是对象", slot_index=index))
                    continue
                episode_id = slot.get("episode_id")
                if not isinstance(episode_id, str) or not re.fullmatch(r"E\d{3,6}", episode_id):
                    errors.append(issue("synopsis_episode_slot_id_invalid", "episode_slots 条目缺少规范 episode_id", slot_index=index))
                change_id = slot.get("change_id")
                if not isinstance(change_id, str) or not change_id.strip():
                    errors.append(issue("synopsis_slot_change_missing", "episode_slots 条目缺少 change_id", slot_index=index))
                elif change_id not in valid_change_ids:
                    errors.append(issue("synopsis_slot_change_unknown", "episode_slots 引用了未知变化节点", slot_index=index, change_id=change_id))
                for field in ("story_function", "state_change", "hook"):
                    if not isinstance(slot.get(field), str) or not slot[field].strip():
                        errors.append(issue("synopsis_slot_field_missing", f"episode_slots 条目缺少 {field}", slot_index=index, field=field))
                if isinstance(change_id, str) and isinstance(slot.get("state_change"), str):
                    key = (change_id, slot["state_change"].strip())
                    if key in seen_changes:
                        errors.append(
                            issue(
                                "synopsis_slot_duplicate_change",
                                "同一变化节点不能在没有新状态变化时重复用于不同集",
                                slot_index=index,
                                change_id=change_id,
                            )
                        )
                    seen_changes.add(key)
    elif verdict is not None:
        blocking_reasons = feasibility.get("blocking_reasons")
        if not isinstance(blocking_reasons, list) or not blocking_reasons or not all(
            isinstance(value, str) and value.strip() for value in blocking_reasons
        ):
            errors.append(
                issue(
                    "synopsis_blocking_reasons_missing",
                    f"verdict={verdict} 时必须提供非空 blocking_reasons 并说明补简介或减集数",
                )
            )
    return errors


def validate_synopsis_event_index(
    payload: Any,
    expected_episodes: int | None = None,
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    if not isinstance(payload, dict):
        return [issue("synopsis_event_index_invalid", "source_event_index 必须是对象")]
    if payload.get("source_mode") != SOURCE_MODE_SYNOPSIS:
        errors.append(
            issue(
                "synopsis_source_mode_missing",
                "synopsis 项目的 source_event_index 必须声明 source_mode=synopsis",
            )
        )
    profile = payload.get("synopsis_profile")
    errors.extend(validate_synopsis_profile(profile))
    feasibility = payload.get("synopsis_feasibility")
    errors.extend(validate_synopsis_feasibility(feasibility, profile, expected_episodes))
    return errors


def evaluate_synopsis_feasibility(
    payload: Any,
    requested_episodes: int | None = None,
) -> dict[str, Any]:
    errors = validate_synopsis_event_index(payload, requested_episodes)
    feasibility = payload.get("synopsis_feasibility") if isinstance(payload, dict) else None
    verdict = (
        feasibility.get("verdict")
        if isinstance(feasibility, dict)
        and feasibility.get("verdict") in SYNOPSIS_VERDICTS
        and not any(
            item.get("code") in {
                "synopsis_feasibility_missing",
                "synopsis_verdict_invalid",
                "synopsis_requested_episodes_invalid",
                "synopsis_requested_episodes_mismatch",
                "synopsis_sufficient_with_blocker",
                "synopsis_episode_slots_missing",
                "synopsis_episode_slots_coverage_invalid",
                "synopsis_slot_change_missing",
                "synopsis_slot_change_unknown",
                "synopsis_slot_field_missing",
                "synopsis_slot_duplicate_change",
            }
            for item in errors
        )
        else "insufficient"
    )
    return {
        "requested_episodes": requested_episodes,
        "verdict": verdict,
        "blocking_reasons": (
            feasibility.get("blocking_reasons")
            if isinstance(feasibility, dict)
            and isinstance(feasibility.get("blocking_reasons"), list)
            else []
        ),
        "warnings": (
            feasibility.get("warnings")
            if isinstance(feasibility, dict)
            and isinstance(feasibility.get("warnings"), list)
            else []
        ),
        "errors": errors,
    }


def validate_synopsis_expansion(
    ledger: Any,
    profile: Any,
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    if not isinstance(ledger, dict):
        return [issue("synopsis_ledger_invalid", "改编决策台账必须是对象")]
    facts = profile.get("facts") if isinstance(profile, dict) else None
    fact_ids = {
        item.get("fact_id")
        for item in facts
        if isinstance(item, dict) and isinstance(item.get("fact_id"), str)
    } if isinstance(facts, list) else set()
    decisions = ledger.get("decisions")
    if not isinstance(decisions, list):
        return [issue("synopsis_ledger_decisions_invalid", "改编决策台账 decisions 必须是非空数组")]
    seen_bridges: set[tuple[str, str, str]] = set()
    for index, decision in enumerate(decisions, 1):
        if not isinstance(decision, dict):
            errors.append(issue("synopsis_decision_invalid", "改编决策必须是对象", decision_index=index))
            continue
        if decision.get("operation") != "bridge_addition":
            continue
        if decision.get("purpose") not in SYNOPSIS_ALLOWED_PURPOSES:
            errors.append(
                issue(
                    "synopsis_bridge_purpose_invalid",
                    "简介桥接新增 purpose 必须属于受控扩写允许类别",
                    decision_index=index,
                    purpose=decision.get("purpose"),
                )
            )
        if not isinstance(decision.get("expansion_id"), str) or not decision["expansion_id"].strip():
            errors.append(issue("synopsis_expansion_id_missing", "简介桥接新增必须提供 expansion_id", decision_index=index))
        for field in ("addition_basis", "state_change", "continuity_impact"):
            if not isinstance(decision.get(field), str) or not decision[field].strip():
                errors.append(issue("synopsis_bridge_field_missing", f"简介桥接新增缺少 {field}", decision_index=index, field=field))
        if decision.get("source_facts_unchanged") is not True:
            errors.append(issue("synopsis_bridge_fact_guard_missing", "简介桥接新增必须声明 source_facts_unchanged: true", decision_index=index))
        target_ids = decision.get("target_episode_ids")
        if not isinstance(target_ids, list) or not target_ids or not all(
            isinstance(value, str) and re.fullmatch(r"E\d{3,6}", value) for value in target_ids
        ):
            errors.append(issue("synopsis_bridge_scope_invalid", "简介桥接新增必须绑定非空规范 target_episode_ids", decision_index=index))
        source_refs = decision.get("source_unit_ids", [])
        source_fact_refs = decision.get("source_fact_ids", [])
        if not isinstance(source_refs, list) or not isinstance(source_fact_refs, list):
            errors.append(issue("synopsis_bridge_source_invalid", "简介桥接新增 source_unit_ids 与 source_fact_ids 必须是数组", decision_index=index))
        unknown_facts = set(source_fact_refs) - fact_ids if isinstance(source_fact_refs, list) else set()
        if unknown_facts:
            errors.append(
                issue(
                    "synopsis_bridge_fact_unknown",
                    "简介桥接新增引用了未知简介事实",
                    decision_index=index,
                    unknown=sorted(unknown_facts),
                )
            )
        if decision.get("change_level") != "expression_only":
            errors.append(
                issue(
                    "synopsis_bridge_not_expression",
                    "简介桥接新增只能增加表达，change_level 必须为 expression_only",
                    decision_index=index,
                )
            )
        if decision.get("source_fact_change") is not False:
            errors.append(
                issue(
                    "synopsis_bridge_alters_fact",
                    "简介桥接新增不能改变故事事实，source_fact_change 必须为 false",
                    decision_index=index,
                )
            )
        if decision.get("status") != "accepted":
            errors.append(
                issue(
                    "synopsis_bridge_unaccepted",
                    "简介桥接新增必须标记 accepted",
                    decision_index=index,
                )
            )
        basis = decision.get("addition_basis") if isinstance(decision.get("addition_basis"), str) else ""
        state_change = decision.get("state_change") if isinstance(decision.get("state_change"), str) else ""
        purpose = decision.get("purpose") if isinstance(decision.get("purpose"), str) else ""
        key = (basis.strip(), state_change.strip(), purpose.strip())
        if key in seen_bridges:
            errors.append(
                issue(
                    "synopsis_bridge_duplicate",
                    "同一依据、用途和状态变化的桥接新增重复出现，不能用重复内容凑集数",
                    decision_index=index,
                )
            )
        seen_bridges.add(key)
    return errors


def synopsis_expression_issues(
    text: str,
    ledger: Any = None,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if not isinstance(text, str) or not text.strip():
        return issues
    for pattern, pattern_code in SYNOPSIS_GENERIC_PATTERNS:
        if pattern in text:
            issues.append(
                issue(
                    "synopsis_ai_expression_suspected",
                    f"检测到通用 AI 表达“{pattern}”；请改写为具体人物、动作、对象和可见反应",
                    pattern=pattern,
                    pattern_code=pattern_code,
                )
            )
    action_lines = [
        line.strip()
        for line in text.splitlines()
        if line.startswith("△")
    ]
    repeated = [
        line
        for line, count in Counter(action_lines).items()
        if count > 1 and len(line) >= 4
    ]
    if repeated:
        issues.append(
            issue(
                "synopsis_repeated_action",
                "同一动作行在本集重复出现，请检查是否用重复反应或空动作填充",
                repeated=repeated[:10],
            )
        )
    if ledger is not None and isinstance(ledger, dict):
        decisions = ledger.get("decisions")
        if isinstance(decisions, list):
            seen_bases: Counter[str] = Counter()
            for decision in decisions:
                if not isinstance(decision, dict):
                    continue
                basis = decision.get("addition_basis")
                if isinstance(basis, str) and basis.strip():
                    seen_bases[basis.strip()] += 1
            repeated_bases = [basis for basis, count in seen_bases.items() if count > 1]
            if repeated_bases:
                issues.append(
                    issue(
                        "synopsis_repeated_expansion_basis",
                        "多个桥接新增使用相同依据；必须为每个新增提供不同的故事功能和状态变化",
                        repeated_bases=repeated_bases[:10],
                    )
                )
    return issues
