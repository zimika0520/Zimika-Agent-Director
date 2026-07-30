#!/usr/bin/env python3
from __future__ import annotations

import unittest

import shot_contracts


class ShotContractTests(unittest.TestCase):
    def test_missing_shot_size_and_camera_movement_are_both_reported(self) -> None:
        unit = {"shot_language": {}}
        codes = {
            item["code"]
            for item in shot_contracts.validate_shot_framing_contract(unit, 1, strict=True)
        }
        self.assertIn("shotplan_shot_size_missing", codes)
        self.assertIn("shotplan_camera_movement_missing", codes)

    def test_non_static_movement_requires_subject_and_description(self) -> None:
        unit = {
            "shot_language": {
                "shot_size": {"start": "medium_shot", "end": "close_up"},
                "camera_movement": {"type": "push_in", "subject": "", "description": ""},
            }
        }
        codes = {
            item["code"]
            for item in shot_contracts.validate_shot_framing_contract(unit, 1, strict=True)
        }
        self.assertIn("shotplan_camera_subject_missing", codes)
        self.assertIn("shotplan_camera_description_missing", codes)

    def test_static_movement_allows_empty_subject_but_requires_description(self) -> None:
        unit = {
            "shot_language": {
                "shot_size": {"start": "medium_shot", "end": "medium_shot"},
                "camera_movement": {
                    "type": "static",
                    "subject": "",
                    "description": "固定中景，人物位于画面中央。",
                },
            }
        }
        self.assertEqual(
            shot_contracts.validate_shot_framing_contract(unit, 1, strict=True), []
        )
        self.assertEqual(shot_contracts.shot_size_text(unit), "中景")

    def test_compiler_uses_validated_size_and_movement(self) -> None:
        unit = {
            "shot_language": {
                "shot_size": {"start": "medium_shot", "end": "close_up"},
                "camera_movement": {
                    "type": "push_in",
                    "subject": "C001",
                    "description": "从温喻腰部缓慢推近至面部。",
                },
            }
        }
        self.assertEqual(shot_contracts.shot_size_text(unit), "中景 → 近景")
        self.assertEqual(
            shot_contracts.compile_shot_instruction(unit),
            "景别：中景到近景。镜头运动：从温喻腰部缓慢推近至面部。",
        )

    def test_legacy_string_fields_remain_readable_outside_strict_delivery(self) -> None:
        unit = {
            "shot_language": {
                "shot_size": "中景",
                "camera_movement": "固定镜头",
            }
        }
        self.assertEqual(
            shot_contracts.validate_shot_framing_contract(unit, 1, strict=False), []
        )
        self.assertEqual(shot_contracts.shot_size_text(unit), "中景")
        self.assertEqual(shot_contracts.camera_movement_text(unit), "固定镜头")


if __name__ == "__main__":
    unittest.main()
