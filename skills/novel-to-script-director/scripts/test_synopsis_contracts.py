#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("synopsis_contracts.py")
SPEC = importlib.util.spec_from_file_location("synopsis_contracts", MODULE_PATH)
assert SPEC and SPEC.loader
synopsis_contracts = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(synopsis_contracts)


def base_profile() -> dict:
    return {
        "facts": [
            {
                "fact_id": "F-CHAR-001",
                "fact_type": "character",
                "fact_text": "女主为弟弟女扮男装进入寄宿高中",
                "source_refs": ["SYNOPSIS"],
                "protection": "must_preserve",
            },
            {
                "fact_id": "F-REL-001",
                "fact_type": "relationship",
                "fact_text": "女主与校霸从针锋相对转向双向心动",
                "source_refs": ["SYNOPSIS"],
                "protection": "must_preserve",
            },
            {
                "fact_id": "F-SET-001",
                "fact_type": "setting",
                "fact_text": "故事主要发生在寄宿高中",
                "source_refs": ["SYNOPSIS"],
                "protection": "flexible",
            },
            {
                "fact_id": "F-EV-001",
                "fact_type": "event",
                "fact_text": "女主觉醒读心异能，听见校霸内心独白",
                "source_refs": ["SYNOPSIS"],
                "protection": "must_preserve",
            },
        ],
        "unknowns": [],
        "analysis": {
            "conflict_nodes": [
                {"id": "CON-001", "label": "女扮男装身份危机"},
                {"id": "CON-002", "label": "校霸校园冲突升级"},
                {"id": "CON-003", "label": "读心异能暴露风险"},
                {"id": "CON-004", "label": "弟弟病情与学业压力"},
            ],
            "relationship_turns": [
                {"id": "REL-001", "label": "女主识破校霸伪装"},
                {"id": "REL-002", "label": "校霸对男主身份产生好感"},
                {"id": "REL-003", "label": "校霸发现性别秘密"},
                {"id": "REL-004", "label": "双向心动确定"},
            ],
            "hook_candidates": [
                {"id": "HOOK-001", "label": "异能意外读取到关键秘密"},
                {"id": "HOOK-002", "label": "身份证据出现在教室"},
                {"id": "HOOK-003", "label": "校霸听见女主心里称呼他"},
            ],
            "supporting_expansion_axes": [
                {"id": "EXP-001", "label": "校园生活事件"},
                {"id": "EXP-002", "label": "配角和对手"},
                {"id": "EXP-003", "label": "中间冲突与误会"},
                {"id": "EXP-004", "label": "关系升级过渡"},
            ],
        },
    }


def slots_for(episode_count: int) -> list[dict]:
    ids = [
        "CON-001",
        "CON-002",
        "CON-003",
        "CON-004",
        "REL-001",
        "REL-002",
        "REL-003",
        "REL-004",
        "HOOK-001",
        "HOOK-002",
        "HOOK-003",
        "EXP-001",
        "EXP-002",
        "EXP-003",
        "EXP-004",
    ]
    return [
        {
            "episode_id": f"E{number:03d}",
            "change_id": ids[(number - 1) % len(ids)],
            "story_function": "推进" if number % 3 else "收束",
            "state_change": f"state-{number}",
            "hook": f"钩子-{number}",
        }
        for number in range(1, episode_count + 1)
    ]


def base_event_index(episode_count: int, verdict: str = "sufficient") -> dict:
    return {
        "source_mode": "synopsis",
        "synopsis_profile": base_profile(),
        "synopsis_feasibility": {
            "requested_episodes": episode_count,
            "verdict": verdict,
            "blocking_reasons": [] if verdict == "sufficient" else ["简介冲突节点不足，请补充简介或减少集数"],
            "warnings": [],
            "episode_slots": slots_for(episode_count) if verdict == "sufficient" else [],
        },
    }


class SynopsisContractsTests(unittest.TestCase):
    def test_default_policy_is_synopsis_range_and_21_units(self) -> None:
        policy = synopsis_contracts.default_synopsis_policy()
        self.assertEqual(policy["duration_seconds"], {"min": 60, "max": 90})
        self.assertEqual(policy["minimum_shot_units"], 21)
        self.assertEqual(policy["composition_policy"], "unrestricted")
        self.assertEqual(synopsis_contracts.validate_synopsis_policy(policy), [])

    def test_invalid_policy_is_rejected(self) -> None:
        errors = synopsis_contracts.validate_synopsis_policy(
            {
                "duration_seconds": {"min": 90, "max": 60},
                "minimum_shot_units": 0,
                "composition_policy": "restricted",
            }
        )
        codes = {item["code"] for item in errors}
        self.assertIn("synopsis_duration_invalid", codes)
        self.assertIn("synopsis_minimum_shot_units_invalid", codes)
        self.assertIn("synopsis_composition_policy_invalid", codes)

    def test_valid_event_index_accepts_20_30_and_40_episodes(self) -> None:
        for count in (20, 30, 40):
            with self.subTest(count=count):
                errors = synopsis_contracts.validate_synopsis_event_index(
                    base_event_index(count),
                    count,
                )
                self.assertEqual(errors, [])
                result = synopsis_contracts.evaluate_synopsis_feasibility(
                    base_event_index(count),
                    count,
                )
                self.assertEqual(result["verdict"], "sufficient")
                self.assertEqual(result["errors"], [])

    def test_insufficient_feasibility_blocks_before_map(self) -> None:
        payload = base_event_index(40, verdict="insufficient")
        result = synopsis_contracts.evaluate_synopsis_feasibility(payload, 40)
        self.assertEqual(result["verdict"], "insufficient")
        self.assertTrue(
            any("简介冲突节点不足" in reason for reason in result["blocking_reasons"]),
            result["blocking_reasons"],
        )

    def test_passed_verdict_is_not_accepted_as_feasibility(self) -> None:
        payload = base_event_index(20)
        payload["synopsis_feasibility"]["verdict"] = "passed"
        result = synopsis_contracts.evaluate_synopsis_feasibility(payload, 20)
        self.assertEqual(result["verdict"], "insufficient")
        self.assertIn(
            "synopsis_verdict_invalid",
            {item["code"] for item in result["errors"]},
        )

    def test_duplicate_slot_change_without_new_state_is_rejected(self) -> None:
        payload = base_event_index(20)
        slots = payload["synopsis_feasibility"]["episode_slots"]
        slots[1]["change_id"] = slots[0]["change_id"]
        slots[1]["state_change"] = slots[0]["state_change"]
        errors = synopsis_contracts.validate_synopsis_feasibility(
            payload["synopsis_feasibility"],
            payload["synopsis_profile"],
            20,
        )
        self.assertIn(
            "synopsis_slot_duplicate_change",
            {item["code"] for item in errors},
        )

    def test_missing_episode_slots_cannot_pass_sufficient(self) -> None:
        payload = base_event_index(30)
        del payload["synopsis_feasibility"]["episode_slots"]
        errors = synopsis_contracts.validate_synopsis_event_index(payload, 30)
        self.assertIn(
            "synopsis_episode_slots_missing",
            {item["code"] for item in errors},
        )

    def test_controlled_bridge_expansion_must_preserve_facts(self) -> None:
        ledger = {
            "decisions": [
                {
                    "decision_id": "AD-BRIDGE-001",
                    "expansion_id": "EXP-X001",
                    "operation": "bridge_addition",
                    "purpose": "intermediate_conflict",
                    "addition_basis": "校霸误会女主偏向同学",
                    "state_change": "校霸把女主视为更特别的人",
                    "continuity_impact": "女主与校霸关系升温但未公开",
                    "source_unit_ids": ["SYNOPSIS"],
                    "source_fact_ids": ["F-REL-001"],
                    "source_facts_unchanged": True,
                    "change_level": "expression_only",
                    "source_fact_change": False,
                    "target_episode_ids": ["E006"],
                    "status": "accepted",
                }
            ]
        }
        self.assertEqual(
            synopsis_contracts.validate_synopsis_expansion(
                ledger,
                base_profile(),
            ),
            [],
        )

    def test_unauthorized_mainline_expansion_is_rejected(self) -> None:
        ledger = {
            "decisions": [
                {
                    "decision_id": "AD-BAD-001",
                    "expansion_id": "EXP-BAD",
                    "operation": "bridge_addition",
                    "purpose": "intermediate_conflict",
                    "addition_basis": "新增第二段完全无关的主要故事线",
                    "state_change": "女主开始调查另一个神秘组织",
                    "continuity_impact": "新增主线",
                    "source_unit_ids": ["SYNOPSIS"],
                    "source_fact_ids": ["F-CHAR-001"],
                    "source_facts_unchanged": True,
                    "change_level": "story_fact_change",
                    "source_fact_change": True,
                    "target_episode_ids": ["E010"],
                    "status": "approved_addition",
                    "authorization_ref": "AUTH-001",
                }
            ]
        }
        errors = synopsis_contracts.validate_synopsis_expansion(
            ledger,
            base_profile(),
        )
        self.assertIn(
            "synopsis_bridge_not_expression",
            {item["code"] for item in errors},
        )
        self.assertIn(
            "synopsis_bridge_alters_fact",
            {item["code"] for item in errors},
        )

    def test_expression_quality_flags_generic_ai_prose_and_repeated_action(self) -> None:
        text = (
            "△她眼底闪过一丝情绪，忍不住勾唇一笑。\n"
            "△她眼底闪过一丝情绪，忍不住勾唇一笑。\n"
            "阿宁：我们继续。\n"
        )
        issues = synopsis_contracts.synopsis_expression_issues(text)
        codes = {item["code"] for item in issues}
        self.assertIn("synopsis_ai_expression_suspected", codes)
        self.assertIn("synopsis_repeated_action", codes)


if __name__ == "__main__":
    unittest.main()
