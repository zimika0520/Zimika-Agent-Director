#!/usr/bin/env python3
from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
import zipfile
from collections import Counter
from types import SimpleNamespace
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).with_name("project_tool.py")
SPEC = importlib.util.spec_from_file_location("project_tool", MODULE_PATH)
assert SPEC and SPEC.loader
project_tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(project_tool)


GOOD_SCRIPT = """# 第1集：钥匙之争

## 1-1 场景：院门 日 / 外
人物：阿宁、管家
道具：钥匙

△阿宁攥着钥匙退到门槛外。
管家：把钥匙交出来。
△管家伸手，阿宁把钥匙藏到袖后。
阿宁：这是母亲留给我的。
场尾状态：阿宁仍持有钥匙，管家堵住院门。

集尾钩子：院门外忽然响起官差叩门声，二人同时回头。
"""


OFF_SCENE_VOICE_SCRIPT = """# 第1集：她的儿子？

## 1-1 场景：梦中卧室 夜 / 内
人物：温喻、祈宥
道具：无

△温喻在梦中惊醒。
温喻：嘶，轻点..
祈宥：温喻……
温喻：嗯...
场尾状态：温喻从梦中惊醒。

## 1-2 场景：温喻卧室 晨 / 内
人物：温喻
非现场人物：王警官（电话声音）、祈星染（画外音）
道具：手机

△手机剧烈震动，温喻接通。
王警官 电话声音：请问是温喻女士吗？
△温喻挂断，手机再次震动。
温喻：喂...
王警官 电话声音：请迅速来分局一趟。
△温喻确认是公安局固定电话。
温喻：你们是不是搞错了？
王警官 电话声音：孩子在这儿，您先过来再说吧。
△温喻抵达警局大厅。
祈星染 OS：妈妈。
场尾状态：温喻在警局第一次见到祈星染。
集尾钩子：男孩依赖地看着温喻。
"""


class ProjectToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "原著.txt"
        self.source.write_text("阿宁守住母亲留下的钥匙。\n", encoding="utf-8")
        self.project = self.root / "项目"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_cli(self, *arguments: str) -> tuple[int, dict]:
        output = io.StringIO()
        error_output = io.StringIO()
        try:
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error_output):
                code = project_tool.main(arguments)
        except SystemExit as exc:
            return int(exc.code or 0), {
                "ok": False,
                "error": error_output.getvalue().strip() or "argument_parser_rejected",
            }
        payload = json.loads(output.getvalue())
        return code, payload

    def init_project(self) -> None:
        code, payload = self.run_cli(
            "init", str(self.project), "--name", "测试项目", "--source", str(self.source)
        )
        self.assertEqual(code, 0, payload)

    def write_project_file(self, relative: str, content: str) -> Path:
        path = self.project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def write_json(self, relative: str, payload: dict) -> Path:
        return self.write_project_file(
            relative, json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        )

    def register_and_approve(
        self,
        key: str,
        relative: str,
        content: str,
        dependencies: tuple[str, ...] = (),
    ) -> int:
        version = self.register_artifact(key, relative, content, dependencies)
        self.approve_artifact(key, version)
        return version

    def register_artifact(
        self,
        key: str,
        relative: str,
        content: str,
        dependencies: tuple[str, ...] = (),
    ) -> int:
        path = self.write_project_file(relative, content)
        arguments = [
            "register-artifact",
            str(self.project),
            key,
            str(path),
            "--status",
            "awaiting_approval",
        ]
        for dependency in dependencies:
            arguments.extend(["--depends-on", dependency])
        code, payload = self.run_cli(*arguments)
        self.assertEqual(code, 0, payload)
        return payload["version"]

    def approve_artifact(self, key: str, version: int) -> None:
        code, payload = self.run_cli(
            "approve", str(self.project), key, "--version", str(version), "--note", "测试确认"
        )
        self.assertEqual(code, 0, payload)

    def state(self) -> dict:
        return json.loads((self.project / project_tool.STATE_FILENAME).read_text(encoding="utf-8"))

    def update_artifact_json(self, key: str, update) -> dict:
        state = self.state()
        record = state["artifacts"][key][-1]
        path = self.project / record["path"]
        payload = json.loads(path.read_text(encoding="utf-8"))
        update(payload)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        record["sha256"] = project_tool.sha256_file(path)
        record["size_bytes"] = path.stat().st_size
        (self.project / project_tool.STATE_FILENAME).write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return payload

    def register_boundary_review(
        self,
        review_key: str,
        target_key: str,
        target_version: int,
        finding: dict,
        conclusion: str,
        *,
        ledger_version: int = 1,
        file_tag: str = "测试",
    ) -> int:
        project_id = self.state()["project_id"]
        payload = {
            "schema_version": 1,
            "project_id": project_id,
            "generated_from": [
                {"artifact_key": "source_event_index", "version": 1},
                {"artifact_key": "story_facts", "version": 1},
                {"artifact_key": "adaptation_decision_ledger", "version": ledger_version},
                {"artifact_key": target_key, "version": target_version},
            ],
            "review_target": {
                "artifact_key": target_key,
                "version": target_version,
            },
            "automation_limitations": "自动检查只能提供证据化风险提示，不能替代人工语义判断。",
            "findings": [finding],
            "conclusion": conclusion,
        }
        safe_key = review_key.replace(":", "_")
        return self.register_artifact(
            review_key,
            f"08_连续性与质检/{safe_key}_{file_tag}.json",
            json.dumps(payload, ensure_ascii=False),
            (
                "source_event_index@1",
                "story_facts@1",
                f"adaptation_decision_ledger@{ledger_version}",
                f"{target_key}@{target_version}",
            ),
        )

    def register_episode_candidate(
        self,
        *,
        ledger_version: int = 1,
        content: str = GOOD_SCRIPT,
        file_tag: str = "候选",
    ) -> int:
        return self.register_artifact(
            "episode_script:E001",
            f"07_分集剧本/第001集_{file_tag}.md",
            content,
            (
                f"adaptation_decision_ledger@{ledger_version}",
                "pilot_scripts@1",
                "pilot_review@1",
            ),
        )

    def test_init_requires_source(self) -> None:
        code, payload = self.run_cli("init", str(self.project), "--name", "空项目")
        self.assertEqual(code, 2)
        self.assertIn("至少一份原始内容", payload["error"])

    def test_approval_requires_unchanged_file_and_confirmed_dependencies(self) -> None:
        self.init_project()
        parent = self.write_project_file("01_原著解析/规格V1.md", "规格V1")
        code, _ = self.run_cli(
            "register-artifact", str(self.project), "project_spec", str(parent),
            "--status", "awaiting_approval",
        )
        self.assertEqual(code, 0)
        child = self.write_project_file("01_原著解析/语料V1.md", "语料V1")
        code, _ = self.run_cli(
            "register-artifact", str(self.project), "source_corpus", str(child),
            "--status", "awaiting_approval", "--depends-on", "project_spec@1",
        )
        self.assertEqual(code, 0)
        code, payload = self.run_cli("approve", str(self.project), "source_corpus")
        self.assertEqual(code, 2)
        self.assertIn("依赖必须是最新版且已获有效确认", payload["error"])

        parent.write_text("登记后被改过", encoding="utf-8")
        code, payload = self.run_cli("approve", str(self.project), "project_spec")
        self.assertEqual(code, 2)
        self.assertIn("登记后已变更", payload["error"])

    def test_new_version_cannot_reuse_old_path(self) -> None:
        self.init_project()
        path = self.write_project_file("01_原著解析/规格.md", "V1")
        code, _ = self.run_cli(
            "register-artifact", str(self.project), "project_spec", str(path)
        )
        self.assertEqual(code, 0)
        path.write_text("V2", encoding="utf-8")
        code, payload = self.run_cli(
            "register-artifact", str(self.project), "project_spec", str(path)
        )
        self.assertEqual(code, 2)
        self.assertIn("新的文件路径", payload["error"])

    def test_draft_cannot_be_approved(self) -> None:
        self.init_project()
        path = self.write_project_file("01_原著解析/规格草稿.md", "草稿")
        code, payload = self.run_cli(
            "register-artifact", str(self.project), "project_spec", str(path), "--status", "draft"
        )
        self.assertEqual(code, 0, payload)
        code, payload = self.run_cli("approve", str(self.project), "project_spec")
        self.assertEqual(code, 2)
        self.assertIn("只能确认 awaiting_approval", payload["error"])

    def test_handler_rejects_direct_confirmed(self) -> None:
        self.init_project()
        path = self.write_project_file("01_原著解析/规格V1.md", "规格")
        arguments = SimpleNamespace(
            project=str(self.project), artifact_key="project_spec", path=str(path),
            status="confirmed", depends_on=[], note=None,
        )
        with self.assertRaises(project_tool.ToolError):
            project_tool.command_register_artifact(arguments)
        self.assertNotIn("project_spec", self.state()["artifacts"])

    def test_cue_type_uses_speaker_annotation_not_dialogue_text(self) -> None:
        self.assertEqual(project_tool.cue_type_from_line("阿青：我内心并不害怕。"), "dialogue")
        self.assertEqual(project_tool.cue_type_from_line("阿青（VO）：门终于开了。"), "vo")
        self.assertEqual(project_tool.cue_type_from_line("阿青（OS）：谁在外面？"), "os")


    def test_dialogue_parser_supports_off_scene_and_phone_annotations(self) -> None:
        self.assertIsNone(
            project_tool.dialogue_match(
                "非现场人物：王警官（电话声音）、祈星染（画外音）"
            )
        )
        phone = project_tool.dialogue_match("王警官 电话声音：请迅速来分局一趟。")
        self.assertIsNotNone(phone)
        assert phone is not None
        self.assertEqual(phone.group("speaker"), "王警官")
        self.assertEqual(project_tool.cue_type_from_line("王警官 电话声音：请迅速来分局一趟。"), "dialogue")
        self.assertEqual(project_tool.delivery_mode_from_line("王警官 电话声音：请迅速来分局一趟。"), "phone_audio")
        self.assertEqual(project_tool.delivery_mode_from_line("王警官（电话声音）：请迅速来分局一趟。"), "phone_audio")
        self.assertEqual(project_tool.delivery_mode_from_line("祈星染 OS：妈妈。"), "off_screen")
        self.assertEqual(project_tool.delivery_mode_from_line("温喻：喂..."), "on_screen")

    def test_script_validation_accepts_declared_off_scene_speakers_and_counts_all_cues(self) -> None:
        script = self.root / "off-scene-voice.md"
        script.write_text(OFF_SCENE_VOICE_SCRIPT, encoding="utf-8")

        result = project_tool.validate_script_file(script)

        self.assertTrue(result["valid"], result)
        self.assertEqual(result["summary"]["dialogue_count"], 9, result)
        self.assertNotIn(
            "dialogue_speaker_undeclared",
            {item["code"] for item in result["errors"]},
        )

    def test_script_index_separates_on_scene_characters_and_voice_delivery_modes(self) -> None:
        script = self.root / "off-scene-index.md"
        script.write_text(OFF_SCENE_VOICE_SCRIPT, encoding="utf-8")

        scenes, cues = project_tool.extract_script_index(script, "episode_script:E001")

        self.assertEqual(scenes["1-2"]["characters"], ["温喻"])
        self.assertEqual(scenes["1-2"]["off_scene_speakers"], ["王警官", "祈星染"])
        self.assertEqual(len(cues), 9)
        self.assertIn(
            ("1-2", "王警官", "dialogue", "phone_audio", "请迅速来分局一趟"),
            cues,
        )
        self.assertIn(
            ("1-2", "祈星染", "os", "off_screen", "妈妈"),
            cues,
        )

    def test_tampered_confirmed_dependency_blocks_downstream_approval(self) -> None:
        self.init_project()
        self.register_and_approve("project_spec", "01_原著解析/规格V1.md", "规格V1")
        state = self.state()
        parent_path = self.project / state["artifacts"]["project_spec"][-1]["path"]
        parent_path.write_text("确认后被篡改", encoding="utf-8")
        child_path = self.write_project_file("01_原著解析/语料V1.md", "语料V1")
        code, payload = self.run_cli(
            "register-artifact", str(self.project), "source_corpus", str(child_path),
            "--status", "awaiting_approval", "--depends-on", "project_spec@1",
        )
        self.assertEqual(code, 0, payload)
        code, payload = self.run_cli("approve", str(self.project), "source_corpus")
        self.assertEqual(code, 2)
        self.assertIn("依赖必须是最新版且已获有效确认", payload["error"])

    def test_script_validation_boundaries(self) -> None:
        good = self.root / "good.md"
        good.write_text(GOOD_SCRIPT, encoding="utf-8")
        result = project_tool.validate_script_file(good)
        self.assertTrue(result["valid"], result)
        self.assertFalse(result["production_ready"])

        fragment = self.root / "fragment.md"
        fragment.write_text(GOOD_SCRIPT.split("集尾钩子：", 1)[0], encoding="utf-8")
        self.assertFalse(project_tool.validate_script_file(fragment)["valid"])
        self.assertTrue(project_tool.validate_script_file(fragment, fragment=True)["valid"])

        silent = self.root / "silent.md"
        silent.write_text(
            "# 第一集：静默试探\n\n## 1-1 场景：密室 夜 / 内\n"
            "人物：阿宁\n道具：无\n△阿宁贴墙停步。\n△门缝下掠过一道影子。\n"
            "场尾状态：阿宁藏进门后。\n集尾钩子：门锁从外面缓缓转动起来。\n",
            encoding="utf-8",
        )
        self.assertTrue(project_tool.validate_script_file(silent)["valid"])

        forbidden = self.root / "forbidden.md"
        for index, forbidden_line in enumerate(
            (
                "景别：特写",
                "**运镜：** 推进",
                "| 机位 | 低机位 |",
                "△ 镜号：1，景别：特写",
                "| 场次 | 镜号 | 景别 | 画面 |",
                "△ 阿宁进门后停下；镜号：1；景别：特写。",
                "△ 阿宁抬眼。景别：特写。",
                "△ 阿宁抬眼（镜号：1，景别：特写）。",
                "| 动作说明 | 建议景别：特写 |",
            )
        ):
            with self.subTest(forbidden_line=forbidden_line):
                forbidden = self.root / f"forbidden-{index}.md"
                forbidden.write_text(GOOD_SCRIPT + f"\n{forbidden_line}\n", encoding="utf-8")
                result = project_tool.validate_script_file(forbidden)
                self.assertFalse(result["valid"])
                self.assertIn("director_field_forbidden", {item["code"] for item in result["errors"]})

        wrong_episode = self.root / "wrong.md"
        wrong_episode.write_text(GOOD_SCRIPT.replace("第1集", "第一集").replace("1-1", "2-1"), encoding="utf-8")
        result = project_tool.validate_script_file(wrong_episode)
        self.assertFalse(result["valid"])
        self.assertIn("scene_episode_mismatch", {item["code"] for item in result["errors"]})

        placeholder = self.root / "placeholder.md"
        placeholder.write_text(GOOD_SCRIPT.replace("△阿宁攥着", "△【待补动作】阿宁攥着"), encoding="utf-8")
        result = project_tool.validate_script_file(placeholder)
        self.assertFalse(result["valid"])
        self.assertIn("placeholder_found", {item["code"] for item in result["errors"]})

        fullwidth_placeholder = self.root / "fullwidth-placeholder.md"
        fullwidth_placeholder.write_text(GOOD_SCRIPT + "\n△ ＴＯＤＯ：补动作。\n", encoding="utf-8")
        result = project_tool.validate_script_file(fullwidth_placeholder)
        self.assertFalse(result["valid"])
        self.assertIn("placeholder_found", {item["code"] for item in result["errors"]})

        zero = self.root / "zero.md"
        zero.write_text(GOOD_SCRIPT.replace("第1集", "第0集").replace("1-1", "0-1"), encoding="utf-8")
        result = project_tool.validate_script_file(zero)
        self.assertFalse(result["valid"])
        self.assertIn("episode_number_invalid", {item["code"] for item in result["errors"]})

        nonstandard = self.root / "nonstandard-heading.md"
        nonstandard.write_text(
            GOOD_SCRIPT.replace("# 第1集：钥匙之争", "# 第1集 钥匙之争").replace(
                "## 1-1 场景：院门 日 / 外", "## 1-1 院门 日 / 外"
            ),
            encoding="utf-8",
        )
        result = project_tool.validate_script_file(nonstandard)
        self.assertFalse(result["valid"])
        self.assertIn("episode_heading_format_invalid", {item["code"] for item in result["errors"]})
        self.assertIn("scene_heading_format_invalid", {item["code"] for item in result["errors"]})

    def create_ready_project(self, expected_episodes: int = 1) -> None:
        self.init_project()
        project_id = self.state()["project_id"]
        project_spec = {
            "schema_version": 1,
            "project_id": project_id,
            "expected_episodes": expected_episodes,
            "target_runtime": "按项目实读复核",
            "handoff_target": "可直接进入导演拆镜",
            # 该 helper 被 AI 视频执行层测试复用，显式允许执行层自动生成。
            "ai_video_phase": "auto",
        }
        self.register_and_approve(
            "project_spec",
            "01_原著解析/项目规格V1.json",
            json.dumps(project_spec, ensure_ascii=False),
        )
        normalized_source = self.write_project_file(
            "01_原著解析/标准化正文_第001章.txt",
            "阿宁守住母亲留下的钥匙。\n管家：把钥匙交出来。\n阿宁：这是母亲留给我的。\n",
        )
        source_corpus = {
            "schema_version": 1,
            "project_id": project_id,
            "generated_from": [{"artifact_key": "project_spec", "version": 1}],
            "source_units": [
                {
                    "source_unit_id": "SRC-CH001",
                    "source_id": self.state()["sources"][0]["source_id"],
                    "source_locator": "第1章",
                    "ordinal": 1,
                    "content_path": normalized_source.relative_to(self.project).as_posix(),
                    "content_sha256": project_tool.sha256_file(normalized_source),
                }
            ],
        }
        self.register_and_approve(
            "source_corpus",
            "01_原著解析/原著语料V1.json",
            json.dumps(source_corpus, ensure_ascii=False),
            ("project_spec@1",),
        )
        source_event_index = {
            "schema_version": 2,
            "content_contract_version": 1,
            "project_id": project_id,
            "generated_from": [{"artifact_key": "source_corpus", "version": 1}],
            "entities": [
                {"entity_id": "C001", "entity_type": "character", "canonical_name": "阿宁", "aliases": []},
                {"entity_id": "C002", "entity_type": "character", "canonical_name": "管家", "aliases": []},
            ],
            "fact_definitions": [],
            "temporal_constraints": [],
            "units": [
                {
                    "source_unit_id": "SRC-CH001",
                    "source_locator": "第1章",
                    "status": "ready",
                    "events": [
                        {
                            "event_id": "EV-0001",
                            "ordinal": 1,
                            "summary": "阿宁拒绝交出母亲留下的钥匙",
                            "participants": ["C001", "C002"],
                            "cause": "管家索要钥匙",
                            "action": "阿宁把钥匙藏到袖后并拒绝",
                            "outcome": "管家堵住院门",
                            "state_change": "钥匙仍由阿宁持有，冲突升级",
                            "source_refs": ["SRC-CH001"],
                            "beats": [
                                {
                                    "beat_id": "B001",
                                    "ordinal": 1,
                                    "source_refs": ["SRC-CH001", "第1章"],
                                    "protected_fact_ids": [],
                                    "required_fact_ids": [],
                                    "content_atoms": [
                                        {
                                            "atom_id": "SA-B001-001",
                                            "kind": "action",
                                            "text": "阿宁守住母亲留下的钥匙。",
                                            "source_unit_id": "SRC-CH001",
                                            "source_locator": "第1章",
                                            "source_excerpt": "阿宁守住母亲留下的钥匙。",
                                        },
                                        {
                                            "atom_id": "SA-B001-002",
                                            "kind": "dialogue_context",
                                            "text": "管家：把钥匙交出来。",
                                            "source_unit_id": "SRC-CH001",
                                            "source_locator": "第1章",
                                            "source_excerpt": "管家：把钥匙交出来。",
                                        },
                                        {
                                            "atom_id": "SA-B001-003",
                                            "kind": "dialogue_context",
                                            "text": "阿宁：这是母亲留给我的。",
                                            "source_unit_id": "SRC-CH001",
                                            "source_locator": "第1章",
                                            "source_excerpt": "阿宁：这是母亲留给我的。",
                                        },
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ],
            "episode_scopes": {
                f"E{number:03d}": {
                    "allowed_beat_ids": ["B001"],
                    "first_beat_id": "B001",
                    "last_beat_id": "B001",
                }
                for number in range(1, expected_episodes + 1)
            },
        }
        self.register_and_approve(
            "source_event_index",
            "01_原著解析/原著事件索引V1.json",
            json.dumps(source_event_index, ensure_ascii=False),
            ("source_corpus@1",),
        )
        self.register_and_approve(
            "story_facts", "01_原著解析/事实库V1.md", "# 事实库\n", ("source_event_index@1",)
        )
        self.register_and_approve(
            "adaptation_profile", "02_改编定位/定位V1.md", "# 改编定位\n",
            ("project_spec@1", "story_facts@1"),
        )
        self.register_and_approve(
            "adaptation_bible", "03_改编圣经/圣经V1.md", "# 改编圣经\n", ("adaptation_profile@1",)
        )
        adaptation_decisions = {
            "schema_version": 1,
            "project_id": project_id,
            "generated_from": [
                {"artifact_key": "source_event_index", "version": 1},
                {"artifact_key": "story_facts", "version": 1},
                {"artifact_key": "adaptation_profile", "version": 1},
                {"artifact_key": "adaptation_bible", "version": 1},
            ],
            "decisions": [
                {
                    "decision_id": "AD-0001",
                    "operation": "preserve",
                    "boundary_class": "source_based",
                    "change_level": "no_change",
                    "source_fact_change": False,
                    "source_unit_ids": ["SRC-CH001"],
                    "target_episode_ids": ["E001"],
                    "rationale": "保留钥匙争夺的核心人物选择与冲突结果",
                    "protected_facts": ["阿宁持有母亲留下的钥匙"],
                    "character_arc_impact": "保持阿宁主动守护遗物的行动动机",
                    "continuity_impact": "钥匙在场尾仍由阿宁持有",
                    "status": "accepted",
                },
                {
                    "decision_id": "AD-AUTO-001",
                    "operation": "psychology_externalization",
                    "boundary_class": "auto_allowed",
                    "change_level": "expression_only",
                    "source_fact_change": False,
                    "source_unit_ids": ["SRC-CH001"],
                    "target_episode_ids": ["E001"],
                    "rationale": "把守护钥匙的心理意图外化为攥紧和藏袖动作",
                    "protected_facts": ["阿宁拒绝交出钥匙", "钥匙仍由阿宁持有"],
                    "character_arc_impact": "不改变阿宁守护遗物的动机",
                    "continuity_impact": "不改变钥匙归属和事件结果",
                    "status": "accepted",
                }
            ],
        }
        self.register_and_approve(
            "adaptation_decision_ledger",
            "03_改编圣经/改编决策台账V1.json",
            json.dumps(adaptation_decisions, ensure_ascii=False),
            (
                "source_event_index@1",
                "story_facts@1",
                "adaptation_profile@1",
                "adaptation_bible@1",
            ),
        )
        series_episodes = [
            {
                "episode_id": f"E{number:03d}",
                "title": "钥匙之争" if number == 1 else f"第{number}集主干",
                "source_unit_ids": ["SRC-CH001"],
                "decision_ids": ["AD-0001", "AD-AUTO-001"],
            }
            for number in range(1, expected_episodes + 1)
        ]
        series_map_version = self.register_artifact(
            "series_map",
            "04_分集地图/地图V1.json",
            json.dumps(
                {
                    "schema_version": 1,
                    "project_id": project_id,
                    "expected_episodes": expected_episodes,
                    "episodes": series_episodes,
                },
                ensure_ascii=False,
            ),
            ("adaptation_bible@1", "adaptation_decision_ledger@1"),
        )
        series_boundary_version = self.register_and_approve(
            "series_boundary_review",
            "04_分集地图/全剧地图内容边界V1.json",
            json.dumps(
                {
                    "schema_version": 1,
                    "project_id": project_id,
                    "generated_from": [
                        {"artifact_key": "source_event_index", "version": 1},
                        {"artifact_key": "story_facts", "version": 1},
                        {"artifact_key": "adaptation_decision_ledger", "version": 1},
                        {"artifact_key": "series_map", "version": series_map_version},
                    ],
                    "review_target": {
                        "artifact_key": "series_map",
                        "version": series_map_version,
                    },
                    "automation_limitations": "自动检查只能发现有证据的冲突与缺口，语义边界仍需人工复核。",
                    "findings": [
                        {
                            "finding_id": "BR-S-001",
                            "category": "source_fidelity",
                            "result": "passed",
                            "location": "E001",
                            "description": "钥匙争夺事件、人物选择和结果均来自原著事件索引。",
                            "evidence": "EV-0001 保留阿宁拒交钥匙及仍持有钥匙的结果。",
                            "source_refs": ["EV-0001"],
                        }
                    ],
                    "conclusion": "passed",
                },
                ensure_ascii=False,
            ),
            (
                "source_event_index@1",
                "story_facts@1",
                "adaptation_decision_ledger@1",
                f"series_map@{series_map_version}",
            ),
        )
        self.approve_artifact("series_map", series_map_version)
        self.register_and_approve(
            "series_plan_review",
            "04_分集地图/全剧规划审核V1.json",
            json.dumps(
                {
                    "schema_version": 1,
                    "project_id": project_id,
                    "review_target": "series_plan",
                    "generated_from": [
                        {"artifact_key": "source_event_index", "version": 1},
                        {"artifact_key": "adaptation_bible", "version": 1},
                        {"artifact_key": "adaptation_decision_ledger", "version": 1},
                        {"artifact_key": "series_map", "version": 1},
                        {"artifact_key": "series_boundary_review", "version": series_boundary_version},
                    ],
                    "issues": [],
                    "conclusion": "passed",
                },
                ensure_ascii=False,
            ),
            (
                "source_event_index@1",
                "adaptation_bible@1",
                "adaptation_decision_ledger@1",
                "series_map@1",
                f"series_boundary_review@{series_boundary_version}",
            ),
        )
        batch_outline_version = self.register_artifact(
            "batch_outline",
            "05_批次大纲/大纲V1.md",
            "# 批次大纲\n",
            ("adaptation_decision_ledger@1", "series_map@1", "series_plan_review@1"),
        )
        batch_boundary_version = self.register_and_approve(
            "batch_boundary_review",
            "05_批次大纲/批次内容边界V1.json",
            json.dumps(
                {
                    "schema_version": 1,
                    "project_id": project_id,
                    "generated_from": [
                        {"artifact_key": "source_event_index", "version": 1},
                        {"artifact_key": "story_facts", "version": 1},
                        {"artifact_key": "adaptation_decision_ledger", "version": 1},
                        {"artifact_key": "batch_outline", "version": batch_outline_version},
                    ],
                    "review_target": {
                        "artifact_key": "batch_outline",
                        "version": batch_outline_version,
                    },
                    "automation_limitations": "自动检查不能替代编剧对人物动机和因果的人工判断。",
                    "findings": [
                        {
                            "finding_id": "BR-B-001",
                            "category": "source_fidelity",
                            "result": "passed",
                            "location": "E001",
                            "description": "批次大纲沿用全剧地图中的原著事件。",
                            "evidence": "大纲仅展开 EV-0001。",
                            "source_refs": ["EV-0001"],
                        }
                    ],
                    "conclusion": "passed",
                },
                ensure_ascii=False,
            ),
            (
                "source_event_index@1",
                "story_facts@1",
                "adaptation_decision_ledger@1",
                f"batch_outline@{batch_outline_version}",
            ),
        )
        self.approve_artifact("batch_outline", batch_outline_version)
        self.register_and_approve(
            "pilot_scripts",
            "06_试写剧本/试写V1.md",
            GOOD_SCRIPT,
            ("batch_outline@1", f"batch_boundary_review@{batch_boundary_version}"),
        )
        self.register_and_approve(
            "pilot_review",
            "06_试写剧本/试写审核V1.json",
            json.dumps(
                {
                    "schema_version": 1,
                    "project_id": project_id,
                    "review_target": "pilot",
                    "generated_from": [
                        {"artifact_key": "pilot_scripts", "version": 1}
                    ],
                    "issues": [],
                    "conclusion": "passed",
                },
                ensure_ascii=False,
            ),
            ("pilot_scripts@1",),
        )

        episode_version = self.register_artifact(
            "episode_script:E001",
            "07_分集剧本/第001集_V1.md",
            GOOD_SCRIPT,
            ("adaptation_decision_ledger@1", "pilot_scripts@1", "pilot_review@1"),
        )
        episode_boundary_version = self.register_and_approve(
            "episode_boundary_review:E001",
            "07_分集剧本/第001集内容边界V1.json",
            json.dumps(
                {
                    "schema_version": 1,
                    "project_id": project_id,
                    "generated_from": [
                        {"artifact_key": "source_event_index", "version": 1},
                        {"artifact_key": "story_facts", "version": 1},
                        {"artifact_key": "adaptation_decision_ledger", "version": 1},
                        {"artifact_key": "episode_script:E001", "version": episode_version},
                    ],
                    "review_target": {
                        "artifact_key": "episode_script:E001",
                        "version": episode_version,
                    },
                    "automation_limitations": "自动检查可能漏掉隐含人物知识差和语义改写，必须保留人工门禁。",
                    "findings": [
                        {
                            "finding_id": "BR-E-001",
                            "category": "source_fidelity",
                            "result": "passed",
                            "location": "E001/1-1",
                            "description": "人物选择、钥匙归属和冲突结果有明确原著事件依据。",
                            "evidence": "EV-0001 对应本场行动链和场尾状态。",
                            "source_refs": ["EV-0001"],
                        }
                    ],
                    "conclusion": "passed",
                },
                ensure_ascii=False,
            ),
            (
                "source_event_index@1",
                "story_facts@1",
                "adaptation_decision_ledger@1",
                f"episode_script:E001@{episode_version}",
            ),
        )
        self.approve_artifact("episode_script:E001", episode_version)
        generated_from = [
            {"artifact_key": "episode_script:E001", "version": episode_version},
            {"artifact_key": "episode_boundary_review:E001", "version": episode_boundary_version},
        ]

        character_payload = {
            "schema_version": 1,
            "project_id": project_id,
            "generated_from": generated_from,
            "records": [
                {"character_id": "C001", "name": "阿宁", "aliases": [], "appearances": [
                    {"episode_id": "E001", "scene_id": "1-1", "entry_state": "持钥匙", "exit_state": "仍持钥匙"}
                ]},
                {"character_id": "C002", "name": "管家", "aliases": [], "appearances": [
                    {"episode_id": "E001", "scene_id": "1-1", "entry_state": "索要钥匙", "exit_state": "堵门"}
                ]},
            ],
        }
        scene_payload = {
            "schema_version": 1,
            "project_id": project_id,
            "generated_from": generated_from,
            "records": [{
                "scene_id": "1-1", "episode_id": "E001", "location_id": "L001",
                "location_name": "院门", "time": "日", "space": "外", "zones": ["门槛"],
                "fixed_elements": ["院门"], "character_ids": ["C001", "C002"],
                "item_ids": ["P001"], "entry_state": "阿宁持钥匙退到门槛外",
                "exit_state": "阿宁仍持钥匙，管家堵门", "reuse_notes": "",
            }],
        }
        item_payload = {
            "schema_version": 1,
            "project_id": project_id,
            "generated_from": generated_from,
            "records": [{
                "item_id": "P001", "name": "钥匙", "aliases": [], "category": "prop",
                "appearances": [{"episode_id": "E001", "scene_id": "1-1", "holder": "C001", "state": "完好"}],
            }],
        }
        cue_generated_from = [
            {"artifact_key": "source_corpus", "version": 1},
            {"artifact_key": "source_event_index", "version": 1},
            *generated_from,
        ]
        cue_payload = {
            "schema_version": 1,
            "contract_version": 2,
            "project_id": project_id,
            "generated_from": cue_generated_from,
            "records": [
                {"cue_id": "Q001", "episode_id": "E001", "scene_id": "1-1", "speaker_id": "C002", "speaker_name": "管家", "type": "dialogue", "delivery_mode": "on_screen", "text": "把钥匙交出来。", "source_unit_id": "SRC-CH001", "source_locator": "第1章", "source_beat_refs": ["B001"]},
                {"cue_id": "Q002", "episode_id": "E001", "scene_id": "1-1", "speaker_id": "C001", "speaker_name": "阿宁", "type": "dialogue", "delivery_mode": "on_screen", "text": "这是母亲留给我的。", "source_unit_id": "SRC-CH001", "source_locator": "第1章", "source_beat_refs": ["B001"]},
            ],
        }
        versions: dict[str, int] = {}
        for key, relative, payload in (
            ("character_roster", "08_连续性与质检/角色提取表V1.json", character_payload),
            ("scene_catalog", "08_连续性与质检/场景提取表V1.json", scene_payload),
            ("prop_costume_ledger", "08_连续性与质检/道具服装台账V1.json", item_payload),
            ("dialogue_cue_sheet", "08_连续性与质检/台词声音表V1.json", cue_payload),
        ):
            dependencies = (
                "source_corpus@1",
                "source_event_index@1",
                "episode_script:E001@1",
                f"episode_boundary_review:E001@{episode_boundary_version}",
            ) if key == "dialogue_cue_sheet" else (
                "episode_script:E001@1",
                f"episode_boundary_review:E001@{episode_boundary_version}",
            )
            versions[key] = self.register_and_approve(
                key,
                relative,
                json.dumps(payload, ensure_ascii=False),
                dependencies,
            )

        versions["continuity_ledger"] = self.register_and_approve(
            "continuity_ledger",
            "08_连续性与质检/连续性台账V1.json",
            json.dumps(
                {
                    "schema_version": 1,
                    "project_id": project_id,
                    "generated_from": generated_from,
                    "records": [
                        {
                            "episode_id": "E001",
                            "scene_id": "1-1",
                            "character_states": {
                                "C001": "阿宁仍持钥匙",
                                "C002": "管家堵住院门",
                            },
                            "item_states": {"P001": "钥匙由阿宁持有，完好"},
                            "relationship_state": "阿宁与管家因钥匙对峙",
                            "knowledge_state": "二人均知道钥匙与阿宁母亲有关",
                            "unresolved_threads": ["官差突然叩门"],
                            "storyline_progress": "钥匙争夺陷入僵持",
                            "relative_time": "本集开场",
                            "end_state": "阿宁仍持钥匙，管家堵住院门",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            ("episode_script:E001@1", f"episode_boundary_review:E001@{episode_boundary_version}"),
        )
        quality_bindings = [
            {"artifact_key": "episode_script:E001", "version": 1},
            *[
                {"artifact_key": key, "version": version}
                for key, version in versions.items()
            ],
        ]
        quality_payload = {
            "schema_version": 1,
            "project_id": project_id,
            "generated_from": quality_bindings,
            "issues": [],
            "conclusion": "passed",
        }
        versions["quality_report"] = self.register_and_approve(
            "quality_report",
            "08_连续性与质检/质检报告V1.json",
            json.dumps(quality_payload, ensure_ascii=False),
            (
                "episode_script:E001@1",
                "character_roster@1",
                "scene_catalog@1",
                "prop_costume_ledger@1",
                "dialogue_cue_sheet@1",
                "continuity_ledger@1",
            ),
        )
        readiness_bindings = [
            {"artifact_key": "episode_script:E001", "version": 1},
            *[
                {"artifact_key": key, "version": version}
                for key, version in versions.items()
            ],
        ]
        readiness_payload = {
            "schema_version": 1,
            "project_id": project_id,
            "generated_from": readiness_bindings,
            "checks": {
                "script_structure": "passed",
                "semantic_quality": "passed",
                "episode_coverage": "passed",
                "breakdown_traceability": "passed",
                "continuity": "passed",
            },
            "runtime_verification": {"status": "not_measured", "note": "尚未配音实读"},
            "unresolved_blockers": [],
            "waivers": [],
            "conclusion": "ready",
        }
        readiness_dependencies = (
            "episode_script:E001@1",
            "character_roster@1",
            "scene_catalog@1",
            "prop_costume_ledger@1",
            "dialogue_cue_sheet@1",
            "continuity_ledger@1",
            "quality_report@1",
        )
        self.register_and_approve(
            "production_readiness_report",
            "08_连续性与质检/制作就绪复核V1.json",
            json.dumps(readiness_payload, ensure_ascii=False),
            readiness_dependencies,
        )

    def define_batch(
        self,
        batch_id: str = "B01",
        episode_ids: tuple[str, ...] = ("E001",),
    ) -> dict:
        code, payload = self.run_cli(
            "define-batch",
            str(self.project),
            batch_id,
            *episode_ids,
            "--note",
            "测试批次",
        )
        self.assertEqual(code, 0, payload)
        return payload

    def add_batch_delivery_inputs(self, batch_id: str = "B01") -> tuple[dict, ...]:
        self.define_batch(batch_id)
        project_id = self.state()["project_id"]
        source_scope_key = f"batch_source_scope:{batch_id}"
        source_scope_version = self.register_and_approve(
            source_scope_key,
            f"01_原著解析/{batch_id}_原著范围V1.json",
            json.dumps(
                {
                    "schema_version": 1,
                    "project_id": project_id,
                    "batch_id": batch_id,
                    "episode_ids": ["E001"],
                    "required_source_unit_ids": ["SRC-CH001"],
                    "generated_from": [
                        {"artifact_key": "series_map", "version": 1},
                        {"artifact_key": "source_corpus", "version": 1},
                    ],
                },
                ensure_ascii=False,
            ),
            ("series_map@1", "source_corpus@1"),
        )
        source_detail_key = f"batch_source_detail:{batch_id}"
        source_detail_version = self.register_and_approve(
            source_detail_key,
            f"01_原著解析/{batch_id}_原著细化V1.json",
            json.dumps(
                {
                    "schema_version": 1,
                    "project_id": project_id,
                    "batch_id": batch_id,
                    "generated_from": [
                        {"artifact_key": source_scope_key, "version": source_scope_version},
                        {"artifact_key": "source_event_index", "version": 1},
                        {"artifact_key": "source_corpus", "version": 1},
                    ],
                    "units": [
                        {
                            "source_unit_id": "SRC-CH001",
                            "granularity": "unit_detail",
                            "events": [
                                {
                                    "event_id": f"EV-{batch_id}-001",
                                    "summary": "阿宁拒绝交出钥匙。",
                                    "cause": "管家索要钥匙。",
                                    "action": "阿宁把钥匙藏到袖后。",
                                    "outcome": "双方在院门对峙。",
                                    "state_change": "钥匙争夺公开化。",
                                    "source_refs": ["SRC-CH001"],
                                }
                            ],
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            (f"{source_scope_key}@{source_scope_version}", "source_event_index@1", "source_corpus@1"),
        )
        batch_outline_key = f"batch_outline:{batch_id}"
        batch_outline_version = self.register_artifact(
            batch_outline_key,
            f"05_批次大纲/{batch_id}_大纲V1.md",
            f"# {batch_id} 批次大纲\n",
            (
                "adaptation_decision_ledger@1",
                "series_map@1",
                "series_plan_review@1",
                f"{source_scope_key}@{source_scope_version}",
                f"{source_detail_key}@{source_detail_version}",
            ),
        )
        batch_boundary_key = f"batch_boundary_review:{batch_id}"
        batch_boundary_version = self.register_boundary_review(
            batch_boundary_key,
            batch_outline_key,
            batch_outline_version,
            {
                "finding_id": f"BR-{batch_id}-001",
                "category": "source_fidelity",
                "result": "passed",
                "location": "E001",
                "description": "批次大纲只展开已确认的原著事件。",
                "evidence": "EV-0001 对应钥匙争夺。",
                "source_refs": ["EV-0001"],
            },
            "passed",
            file_tag=batch_id,
        )
        self.approve_artifact(batch_boundary_key, batch_boundary_version)
        self.approve_artifact(batch_outline_key, batch_outline_version)

        episode_dependencies = (
            "episode_script:E001@1",
            "episode_boundary_review:E001@1",
        )
        scoped_versions: dict[str, int] = {}
        for artifact_kind in (
            "character_roster",
            "scene_catalog",
            "prop_costume_ledger",
            "dialogue_cue_sheet",
            "continuity_ledger",
        ):
            source_record = self.state()["artifacts"][artifact_kind][-1]
            source_path = self.project / source_record["path"]
            payload = json.loads(source_path.read_text(encoding="utf-8"))
            scoped_key = f"{artifact_kind}:{batch_id}"
            scoped_dependencies = (
                "source_corpus@1",
                "source_event_index@1",
                *episode_dependencies,
            ) if artifact_kind == "dialogue_cue_sheet" else episode_dependencies
            scoped_versions[artifact_kind] = self.register_and_approve(
                scoped_key,
                f"08_连续性与质检/{batch_id}_{artifact_kind}_V1.json",
                json.dumps(payload, ensure_ascii=False),
                scoped_dependencies,
            )

        quality_bindings = [
            {"artifact_key": "episode_script:E001", "version": 1},
            *[
                {
                    "artifact_key": f"{artifact_kind}:{batch_id}",
                    "version": version,
                }
                for artifact_kind, version in scoped_versions.items()
            ],
        ]
        quality_key = f"quality_report:{batch_id}"
        quality_version = self.register_and_approve(
            quality_key,
            f"08_连续性与质检/{batch_id}_质检报告V1.json",
            json.dumps(
                {
                    "schema_version": 1,
                    "project_id": project_id,
                    "generated_from": quality_bindings,
                    "issues": [],
                    "conclusion": "passed",
                },
                ensure_ascii=False,
            ),
            (
                "episode_script:E001@1",
                f"character_roster:{batch_id}@1",
                f"scene_catalog:{batch_id}@1",
                f"prop_costume_ledger:{batch_id}@1",
                f"dialogue_cue_sheet:{batch_id}@1",
                f"continuity_ledger:{batch_id}@1",
            ),
        )
        readiness_bindings = [
            *quality_bindings,
            {"artifact_key": quality_key, "version": quality_version},
        ]
        readiness_key = f"production_readiness_report:{batch_id}"
        readiness_version = self.register_and_approve(
            readiness_key,
            f"08_连续性与质检/{batch_id}_制作就绪复核V1.json",
            json.dumps(
                {
                    "schema_version": 1,
                    "project_id": project_id,
                    "generated_from": readiness_bindings,
                    "checks": {
                        "script_structure": "passed",
                        "semantic_quality": "passed",
                        "episode_coverage": "passed",
                        "breakdown_traceability": "passed",
                        "continuity": "passed",
                    },
                    "runtime_verification": {
                        "status": "not_measured",
                        "note": "尚未配音实读",
                    },
                    "unresolved_blockers": [],
                    "waivers": [],
                    "conclusion": "ready",
                },
                ensure_ascii=False,
            ),
            (
                "episode_script:E001@1",
                f"character_roster:{batch_id}@1",
                f"scene_catalog:{batch_id}@1",
                f"prop_costume_ledger:{batch_id}@1",
                f"dialogue_cue_sheet:{batch_id}@1",
                f"continuity_ledger:{batch_id}@1",
                f"quality_report:{batch_id}@1",
            ),
        )
        snapshot_key = f"batch_continuity_snapshot:{batch_id}"
        snapshot_version = self.register_and_approve(
            snapshot_key,
            f"08_连续性与质检/{batch_id}_连续性快照V1.json",
            json.dumps(
                {
                    "schema_version": 1,
                    "project_id": project_id,
                    "batch_id": batch_id,
                    "episode_ids": ["E001"],
                    "generated_from": [
                        {"artifact_key": "episode_script:E001", "version": 1},
                        {"artifact_key": "episode_boundary_review:E001", "version": 1},
                        {"artifact_key": f"continuity_ledger:{batch_id}", "version": scoped_versions["continuity_ledger"]},
                    ],
                    "opening_state": {
                        "character_states": {"C001": "阿宁持有钥匙"},
                        "item_states": {"P001": "钥匙完好"},
                        "relationship_state": "阿宁与管家尚未公开冲突",
                        "knowledge_state": "阿宁知道钥匙来历",
                        "unresolved_threads": [],
                        "storyline_progress": "钥匙争夺开始前",
                        "relative_time": "本批开场",
                    },
                    "closing_state": {
                        "character_states": {"C001": "阿宁仍持钥匙"},
                        "item_states": {"P001": "钥匙仍由阿宁持有"},
                        "relationship_state": "阿宁与管家公开对峙",
                        "knowledge_state": "二人均知道钥匙与阿宁母亲有关",
                        "unresolved_threads": ["官差突然叩门"],
                        "storyline_progress": "钥匙争夺陷入僵持",
                        "relative_time": "本批收尾",
                    },
                },
                ensure_ascii=False,
            ),
            (
                "episode_script:E001@1",
                "episode_boundary_review:E001@1",
                f"continuity_ledger:{batch_id}@{scoped_versions['continuity_ledger']}",
            ),
        )
        return (
            {"artifact_key": "series_map", "version": 1},
            {"artifact_key": "series_boundary_review", "version": 1},
            {"artifact_key": source_scope_key, "version": source_scope_version},
            {"artifact_key": source_detail_key, "version": source_detail_version},
            {"artifact_key": batch_outline_key, "version": batch_outline_version},
            {"artifact_key": batch_boundary_key, "version": batch_boundary_version},
            {"artifact_key": "episode_script:E001", "version": 1},
            {"artifact_key": "episode_boundary_review:E001", "version": 1},
            *[
                {
                    "artifact_key": f"{artifact_kind}:{batch_id}",
                    "version": version,
                }
                for artifact_kind, version in scoped_versions.items()
            ],
            {"artifact_key": quality_key, "version": quality_version},
            {"artifact_key": readiness_key, "version": readiness_version},
            {"artifact_key": snapshot_key, "version": snapshot_version},
        )

    def register_batch_delivery_review(
        self,
        dependencies: tuple[dict, ...],
        *,
        batch_id: str = "B01",
        result: str = "passed",
        file_tag: str = "通过",
    ) -> int:
        conclusion = {
            "passed": "passed",
            "blocked": "blocked",
            "suspected_overreach": "needs_human_review",
        }[result]
        finding = {
            "finding_id": f"BDR-{batch_id}-{file_tag}",
            "category": "delivery_boundary",
            "result": result,
            "location": batch_id,
            "description": "批次交付内容与三层边界报告一致。",
            "evidence": "交付输入均绑定当前已确认版本。",
        }
        if result == "passed":
            finding["source_refs"] = ["EV-0001"]
        if result == "suspected_overreach":
            finding["human_judgment_required"] = True
        return self.register_artifact(
            f"batch_delivery_review:{batch_id}",
            f"09_定稿交付/{batch_id}_批次交付审核_{file_tag}.json",
            json.dumps(
                {
                    "schema_version": 1,
                    "project_id": self.state()["project_id"],
                    "batch_id": batch_id,
                    "generated_from": list(dependencies),
                    "findings": [finding],
                    "conclusion": conclusion,
                },
                ensure_ascii=False,
            ),
            tuple(
                f"{item['artifact_key']}@{item['version']}"
                for item in dependencies
            ),
        )

    def create_ready_batch(
        self,
        *,
        batch_id: str = "B01",
        expected_episodes: int = 2,
    ) -> tuple[dict, ...]:
        self.create_ready_project(expected_episodes=expected_episodes)
        dependencies = self.add_batch_delivery_inputs(batch_id)
        review_version = self.register_batch_delivery_review(
            dependencies, batch_id=batch_id
        )
        self.approve_artifact(f"batch_delivery_review:{batch_id}", review_version)
        return dependencies

    def register_cross_batch_continuity_review(
        self,
        *,
        batch_ids: tuple[str, ...] = ("B01",),
        conclusion: str = "passed",
    ) -> int:
        dependencies = []
        for batch_id in batch_ids:
            record = self.state()["artifacts"][f"batch_continuity_snapshot:{batch_id}"][-1]
            dependencies.append(
                {
                    "artifact_key": f"batch_continuity_snapshot:{batch_id}",
                    "version": record["version"],
                }
            )
        finding_result = "passed" if conclusion == "passed" else "blocked"
        return self.register_artifact(
            "cross_batch_continuity_review",
            "08_连续性与质检/跨批连续性审核.json",
            json.dumps(
                {
                    "schema_version": 1,
                    "project_id": self.state()["project_id"],
                    "generated_from": dependencies,
                    "batch_ids": list(batch_ids),
                    "transitions": [],
                    "findings": [
                        {
                            "finding_id": "CBR-001",
                            "result": finding_result,
                            "description": "相邻批次首尾状态可以衔接。",
                            "evidence": "连续性快照版本已核对。",
                        }
                    ],
                    "conclusion": conclusion,
                },
                ensure_ascii=False,
            ),
            tuple(
                f"{item['artifact_key']}@{item['version']}" for item in dependencies
            ),
        )

    def seedance_dependencies(self) -> tuple[str, ...]:
        return (
            "source_event_index@1",
            "story_facts@1",
            "adaptation_decision_ledger@1",
            "episode_script:E001@1",
            "episode_boundary_review:E001@1",
            "character_roster@1",
            "scene_catalog@1",
            "prop_costume_ledger@1",
            "dialogue_cue_sheet@1",
            "continuity_ledger@1",
        )

    def seedance_payload(self) -> dict:
        project_id = self.state()["project_id"]
        dependencies = self.seedance_dependencies()
        generated_from = []
        for value in dependencies:
            key, raw_version = value.rsplit("@", 1)
            generated_from.append(
                {"artifact_key": key, "version": int(raw_version)}
            )
        return {
            "schema_version": 1,
            "content_contract_version": 1,
            "project_id": project_id,
            "episode_id": "E001",
            "generated_from": generated_from,
            "model_profile": {
                "family": "Seedance 2.0",
                "provider_model_id": "doubao-seedance-2-0-test",
                "capability_snapshot": {
                    "status": "verified",
                    "checked_at": "2026-07-25",
                    "source_urls": [
                        "https://seed.bytedance.com/zh/seedance2_0"
                    ],
                },
            },
            "execution_policy": {
                "generate_images": False,
                "submit_video_requests": False,
                "asset_handling": "text_only",
                "prompt_language": "zh-CN",
                "subtitle_policy": "post_production",
                "timing_policy": "unit_duration_only",
            },
            "model_constraints": {
                "unit_duration_seconds": {"min": 4, "max": 15},
                "ratio": "16:9",
                "resolution": "1080p",
                "generate_audio": True,
            },
            "reference_assets": [],
            "global_constraints": [
                "保持阿宁、管家、钥匙和院门的状态连续",
                "不得改变人物选择、事件原因或结果",
                "不生成字幕、Logo或水印文字",
            ],
            "total_duration_seconds": 16,
            "units": [
                {
                    "unit_id": "SD2-E001-U001",
                    "sequence": 1,
                    "scene_id": "1-1",
                    "duration_seconds": 8,
                    "source_refs": ["EV-0001"],
                    "source_beat_refs": ["B001"],
                    "preserved_fact_ids": [],
                    "new_fact_claims": [],
                    "decision_ids": ["AD-0001"],
                    "start_state": "管家：把钥匙交出来。",
                    "end_state": "管家：把钥匙交出来。",
                    "content_atoms": [{"atom_id": "CA-SD-U001", "origin": "source", "source_atom_id": "SA-B001-002", "text": "管家：把钥匙交出来。"}],
                    "content_bindings": {"start_state": ["CA-SD-U001"], "end_state": ["CA-SD-U001"], "prompt_text": ["CA-SD-U001"]},
                    "generation_mode": "text_to_video",
                    "reference_asset_ids": [],
                    "continuity": {
                        "chain_id": "CHAIN-E001-S01",
                        "input_state": "STATE-E001-S01-START",
                        "output_state": "STATE-E001-S01-MID",
                    },
                    "shots": [
                        {
                            "shot": 1,
                            "camera": "固定中景",
                            "visual_action": "管家：把钥匙交出来。",
                            "content_atom_refs": ["CA-SD-U001"],
                            "dialogue_cue_ids": ["Q001"],
                            "sound": ["院门外环境声"],
                        }
                    ],
                    "prompt_text": "管家：把钥匙交出来。",
                },
                {
                    "unit_id": "SD2-E001-U002",
                    "sequence": 2,
                    "scene_id": "1-1",
                    "duration_seconds": 8,
                    "source_refs": ["EV-0001"],
                    "source_beat_refs": ["B001"],
                    "preserved_fact_ids": [],
                    "new_fact_claims": [],
                    "decision_ids": ["AD-0001", "AD-AUTO-001"],
                    "start_state": "阿宁：这是母亲留给我的。",
                    "end_state": "阿宁：这是母亲留给我的。",
                    "content_atoms": [{"atom_id": "CA-SD-U002", "origin": "source", "source_atom_id": "SA-B001-003", "text": "阿宁：这是母亲留给我的。"}],
                    "content_bindings": {"start_state": ["CA-SD-U002"], "end_state": ["CA-SD-U002"], "prompt_text": ["CA-SD-U002"]},
                    "generation_mode": "text_to_video",
                    "reference_asset_ids": [],
                    "continuity": {
                        "chain_id": "CHAIN-E001-S01",
                        "input_state": "STATE-E001-S01-MID",
                        "output_state": "STATE-E001-S01-END",
                    },
                    "shots": [
                        {
                            "shot": 1,
                            "camera": "缓慢推进",
                            "visual_action": "阿宁：这是母亲留给我的。",
                            "content_atom_refs": ["CA-SD-U002"],
                            "dialogue_cue_ids": ["Q002"],
                            "sound": ["官差叩门声在场外响起"],
                        }
                    ],
                    "prompt_text": "阿宁：这是母亲留给我的。",
                },
            ],
        }


    def test_seedance_prompt_cannot_add_unbound_story_content(self) -> None:
        beats = {"B001": {"content_atoms": {"SA001": {"atom_id": "SA001", "text": "孩子看向屏幕。"}}}}
        unit = {
            "source_beat_refs": ["B001"],
            "start_state": "孩子夸赞父亲。", "end_state": "母子约定保密。",
            "content_atoms": [{"atom_id": "CA001", "origin": "source", "source_atom_id": "SA001", "text": "孩子看向屏幕。"}],
            "content_bindings": {"start_state": ["CA001"], "end_state": ["CA001"], "prompt_text": ["CA001"]},
            "shots": [{"shot": 1, "visual_action": "母子约定保密。", "content_atom_refs": ["CA001"]}],
            "prompt_text": "母子约定保密。",
        }
        errors = project_tool.validate_seedance_unit_content_contract(unit, beats, {}, 1, True)
        self.assertIn("seedance_prompt_content_unproven", {item["code"] for item in errors})

    def test_seedance_text_plan_requires_boundary_and_validates_full_coverage(self) -> None:
        self.create_ready_project()
        plan_version = self.register_artifact(
            "seedance_execution_plan:E001",
            "10_Seedance兼容层/E001_执行计划V1.json",
            json.dumps(self.seedance_payload(), ensure_ascii=False),
            self.seedance_dependencies(),
        )
        code, payload = self.run_cli(
            "approve", str(self.project), "seedance_execution_plan:E001"
        )
        self.assertEqual(code, 2, payload)
        self.assertIn("Seedance执行层内容边界报告", payload["error"])

        review_dependencies = (
            "source_event_index@1",
            "story_facts@1",
            "adaptation_decision_ledger@1",
            "episode_script:E001@1",
            "episode_boundary_review:E001@1",
            f"seedance_execution_plan:E001@{plan_version}",
        )
        review_payload = {
            "schema_version": 1,
            "project_id": self.state()["project_id"],
            "generated_from": [
                {
                    "artifact_key": value.rsplit("@", 1)[0],
                    "version": int(value.rsplit("@", 1)[1]),
                }
                for value in review_dependencies
            ],
            "review_target": {
                "artifact_key": "seedance_execution_plan:E001",
                "version": plan_version,
            },
            "automation_limitations": "自动检查不能保证发现所有镜头语义偏移，仍需人工复核。",
            "findings": [
                {
                    "finding_id": "BR-SD2-E001-001",
                    "category": "source_fidelity",
                    "result": "passed",
                    "location": "E001/U001-U002",
                    "description": "执行单元只拆分钥匙争夺动作与原对白。",
                    "evidence": "人物选择、钥匙归属和场尾结果均保持 EV-0001。",
                    "source_refs": ["EV-0001"],
                }
            ],
            "conclusion": "passed",
        }
        self.register_and_approve(
            "seedance_boundary_review:E001",
            "10_Seedance兼容层/E001_内容边界V1.json",
            json.dumps(review_payload, ensure_ascii=False),
            review_dependencies,
        )
        self.approve_artifact("seedance_execution_plan:E001", plan_version)
        code, payload = self.run_cli(
            "validate-seedance",
            str(self.project),
            "--expected-episodes",
            "1",
        )
        self.assertEqual(code, 0, payload)
        self.assertTrue(payload["compatible"], payload)
        self.assertEqual(payload["summary"]["confirmed_plan_count"], 1)

    def test_seedance_plan_blocks_image_generation_and_missing_dialogue(self) -> None:
        self.create_ready_project()
        plan = self.seedance_payload()
        plan["execution_policy"]["generate_images"] = True
        plan["units"][1]["shots"][0]["dialogue_cue_ids"] = []
        version = self.register_artifact(
            "seedance_execution_plan:E001",
            "10_Seedance兼容层/E001_坏计划V1.json",
            json.dumps(plan, ensure_ascii=False),
            self.seedance_dependencies(),
        )
        code, payload = self.run_cli(
            "approve",
            str(self.project),
            "seedance_execution_plan:E001",
            "--version",
            str(version),
        )
        self.assertEqual(code, 2, payload)
        self.assertIn("seedance_image_generation_forbidden", payload["error"])
        self.assertIn("seedance_cue_coverage_missing", payload["error"])

    def test_three_layer_boundary_reports_are_required_and_current(self) -> None:
        self.create_ready_project()
        state = self.state()
        for target_key, review_key in (
            ("series_map", "series_boundary_review"),
            ("batch_outline", "batch_boundary_review"),
            ("episode_script:E001", "episode_boundary_review:E001"),
        ):
            target = state["artifacts"][target_key][-1]
            review = state["artifacts"][review_key][-1]
            self.assertEqual(target["status"], "confirmed")
            self.assertEqual(review["status"], "confirmed")
            self.assertIn(
                {"artifact_key": target_key, "version": target["version"]},
                review["depends_on"],
            )

    def test_episode_cannot_be_approved_without_current_boundary_report(self) -> None:
        self.create_ready_project()
        candidate_version = self.register_episode_candidate(file_tag="无边界报告")
        code, payload = self.run_cli(
            "approve",
            str(self.project),
            "episode_script:E001",
            "--version",
            str(candidate_version),
        )
        self.assertEqual(code, 2, payload)
        self.assertIn("缺少精确绑定当前版本", payload["error"])

    def test_suspected_overreach_requires_human_gate_and_blocks_target(self) -> None:
        self.create_ready_project()
        candidate_version = self.register_episode_candidate(file_tag="疑似越界")
        review_version = self.register_boundary_review(
            "episode_boundary_review:E001",
            "episode_script:E001",
            candidate_version,
            {
                "finding_id": "BR-SUS-001",
                "category": "change_motivation",
                "result": "suspected_overreach",
                "location": "E001/1-1",
                "description": "对白可能把守护遗物改写为报复动机。",
                "evidence": "现有证据不足以确定是否改变人物动机。",
                "human_judgment_required": True,
            },
            "needs_human_review",
            file_tag="疑似越界",
        )
        self.approve_artifact("episode_boundary_review:E001", review_version)
        code, payload = self.run_cli(
            "approve", str(self.project), "episode_script:E001", "--version", str(candidate_version)
        )
        self.assertEqual(code, 2, payload)
        self.assertIn("suspected_overreach", payload["error"])

    def test_premature_knowledge_disclosure_is_hard_blocked(self) -> None:
        self.create_ready_project()
        candidate_version = self.register_episode_candidate(file_tag="提前泄密")
        invalid_review = self.register_boundary_review(
            "episode_boundary_review:E001",
            "episode_script:E001",
            candidate_version,
            {
                "finding_id": "BR-LEAK-001",
                "category": "premature_knowledge_disclosure",
                "result": "passed",
                "location": "E001/1-1",
                "description": "人物说出了此时尚未知晓的幕后身份。",
                "evidence": "EV-0001 未提供该人物已经知情的依据。",
                "source_refs": ["EV-0001"],
            },
            "passed",
            file_tag="泄密误判",
        )
        code, payload = self.run_cli(
            "approve",
            str(self.project),
            "episode_boundary_review:E001",
            "--version",
            str(invalid_review),
        )
        self.assertEqual(code, 2, payload)
        self.assertIn("boundary_hard_block_downgraded", payload["error"])

        blocked_review = self.register_boundary_review(
            "episode_boundary_review:E001",
            "episode_script:E001",
            candidate_version,
            {
                "finding_id": "BR-LEAK-002",
                "category": "premature_knowledge_disclosure",
                "result": "blocked",
                "location": "E001/1-1",
                "description": "人物提前泄露尚未知晓的信息。",
                "evidence": "原著事件索引在本集没有该知情变化。",
            },
            "blocked",
            file_tag="泄密阻断",
        )
        self.approve_artifact("episode_boundary_review:E001", blocked_review)
        code, payload = self.run_cli(
            "approve", str(self.project), "episode_script:E001", "--version", str(candidate_version)
        )
        self.assertEqual(code, 2, payload)

    def test_auto_allowed_expression_must_trace_to_known_source(self) -> None:
        self.create_ready_project()
        candidate_version = self.register_episode_candidate(file_tag="心理外化")
        invalid_review = self.register_boundary_review(
            "episode_boundary_review:E001",
            "episode_script:E001",
            candidate_version,
            {
                "finding_id": "BR-TRACE-001",
                "category": "psychology_externalization",
                "result": "passed",
                "location": "E001/1-1",
                "description": "把心理活动转为攥紧钥匙的动作。",
                "evidence": "声称来自不存在的事件。",
                "source_refs": ["EV-NOT-FOUND"],
                "decision_ids": ["AD-AUTO-001"],
            },
            "passed",
            file_tag="错误追溯",
        )
        code, payload = self.run_cli(
            "approve",
            str(self.project),
            "episode_boundary_review:E001",
            "--version",
            str(invalid_review),
        )
        self.assertEqual(code, 2, payload)
        self.assertIn("boundary_source_ref_unknown", payload["error"])

        valid_review = self.register_boundary_review(
            "episode_boundary_review:E001",
            "episode_script:E001",
            candidate_version,
            {
                "finding_id": "BR-TRACE-002",
                "category": "psychology_externalization",
                "result": "passed",
                "location": "E001/1-1",
                "description": "把守护钥匙的心理意图转为攥紧和藏袖动作。",
                "evidence": "EV-0001 明确记录拒交钥匙的行动与结果。",
                "source_refs": ["EV-0001"],
                "decision_ids": ["AD-AUTO-001"],
            },
            "passed",
            file_tag="正确追溯",
        )
        self.approve_artifact("episode_boundary_review:E001", valid_review)
        self.approve_artifact("episode_script:E001", candidate_version)

    def test_user_authorized_story_fact_addition_can_pass_series_gate(self) -> None:
        self.create_ready_project()
        project_id = self.state()["project_id"]
        authorization_version = self.register_and_approve(
            "change_authorization",
            "03_改编圣经/用户变更授权V1.json",
            json.dumps(
                {
                    "schema_version": 1,
                    "project_id": project_id,
                    "generated_from": [
                        {"artifact_key": "project_spec", "version": 1},
                        {"artifact_key": "story_facts", "version": 1},
                        {"artifact_key": "adaptation_profile", "version": 1},
                    ],
                    "authorizations": [{
                        "authorization_id": "AUTH-001",
                        "category": "new_major_event",
                        "approved_change": "在第一集加入官差上门这一重大危机。",
                        "rationale": "用户明确要求用该事件增强阶段钩子。",
                        "scope": "E001",
                        "constraints": "不得改变阿宁持有钥匙的结果。",
                        "user_confirmation_quote": "确认加入官差上门，但钥匙仍由阿宁持有。",
                        "approved_by": "user",
                    }],
                },
                ensure_ascii=False,
            ),
            ("project_spec@1", "story_facts@1", "adaptation_profile@1"),
        )
        self.assertEqual(authorization_version, 1)
        ledger_version = self.register_and_approve(
            "adaptation_decision_ledger",
            "03_改编圣经/改编决策台账V2.json",
            json.dumps(
                {
                    "schema_version": 1,
                    "project_id": project_id,
                    "generated_from": [
                        {"artifact_key": "source_event_index", "version": 1},
                        {"artifact_key": "story_facts", "version": 1},
                        {"artifact_key": "adaptation_profile", "version": 1},
                        {"artifact_key": "adaptation_bible", "version": 1},
                        {"artifact_key": "change_authorization", "version": 1},
                    ],
                    "decisions": [
                        {
                            "decision_id": "AD-0001",
                            "operation": "preserve",
                            "boundary_class": "source_based",
                            "change_level": "no_change",
                            "source_fact_change": False,
                            "source_unit_ids": ["SRC-CH001"],
                            "target_episode_ids": ["E001"],
                            "rationale": "保留钥匙争夺。",
                            "protected_facts": ["钥匙仍由阿宁持有"],
                            "character_arc_impact": "不改变阿宁的选择。",
                            "continuity_impact": "钥匙状态不变。",
                            "status": "accepted",
                        },
                        {
                            "decision_id": "AD-0002",
                            "operation": "new_major_event",
                            "boundary_class": "user_confirmation_required",
                            "change_level": "story_fact_change",
                            "source_fact_change": True,
                            "source_unit_ids": [],
                            "target_episode_ids": ["E001"],
                            "rationale": "按用户授权加入阶段危机。",
                            "protected_facts": ["钥匙仍由阿宁持有"],
                            "character_arc_impact": "不改变阿宁守护遗物的动机。",
                            "continuity_impact": "新增官差到场状态。",
                            "authorization_ref": "AUTH-001",
                            "status": "approved_addition",
                        },
                    ],
                },
                ensure_ascii=False,
            ),
            (
                "source_event_index@1",
                "story_facts@1",
                "adaptation_profile@1",
                "adaptation_bible@1",
                "change_authorization@1",
            ),
        )
        self.assertEqual(ledger_version, 2)
        series_map_version = self.register_artifact(
            "series_map",
            "04_分集地图/地图V2_获批新增.json",
            json.dumps(
                {
                    "schema_version": 1,
                    "project_id": project_id,
                    "expected_episodes": 1,
                    "episodes": [{
                        "episode_id": "E001",
                        "title": "钥匙之争",
                        "source_unit_ids": ["SRC-CH001"],
                        "decision_ids": ["AD-0001", "AD-0002"],
                    }],
                },
                ensure_ascii=False,
            ),
            ("adaptation_bible@1", "adaptation_decision_ledger@2"),
        )
        review_version = self.register_boundary_review(
            "series_boundary_review",
            "series_map",
            series_map_version,
            {
                "finding_id": "BR-AUTH-001",
                "category": "new_major_event",
                "result": "approved_addition",
                "location": "E001",
                "description": "新增官差上门危机。",
                "evidence": "改编决策 AD-0002 已绑定用户授权 AUTH-001。",
                "decision_ids": ["AD-0002"],
                "authorization_refs": ["AUTH-001"],
            },
            "passed",
            ledger_version=2,
            file_tag="获批新增",
        )
        self.approve_artifact("series_boundary_review", review_version)
        self.approve_artifact("series_map", series_map_version)

    def test_story_fact_addition_without_user_authorization_is_rejected(self) -> None:
        self.create_ready_project()
        project_id = self.state()["project_id"]
        ledger_version = self.register_artifact(
            "adaptation_decision_ledger",
            "03_改编圣经/改编决策台账V2_未授权.json",
            json.dumps(
                {
                    "schema_version": 1,
                    "project_id": project_id,
                    "generated_from": [
                        {"artifact_key": "source_event_index", "version": 1},
                        {"artifact_key": "story_facts", "version": 1},
                        {"artifact_key": "adaptation_profile", "version": 1},
                        {"artifact_key": "adaptation_bible", "version": 1},
                    ],
                    "decisions": [{
                        "decision_id": "AD-UNAUTHORIZED",
                        "operation": "new_major_event",
                        "boundary_class": "user_confirmation_required",
                        "change_level": "story_fact_change",
                        "source_fact_change": True,
                        "source_unit_ids": [],
                        "target_episode_ids": ["E001"],
                        "rationale": "为增强钩子擅自加入危机。",
                        "protected_facts": [],
                        "character_arc_impact": "可能改变人物选择。",
                        "continuity_impact": "新增重大危机。",
                        "authorization_ref": "AUTH-NOT-FOUND",
                        "status": "approved_addition",
                    }],
                },
                ensure_ascii=False,
            ),
            (
                "source_event_index@1",
                "story_facts@1",
                "adaptation_profile@1",
                "adaptation_bible@1",
            ),
        )
        code, payload = self.run_cli(
            "approve",
            str(self.project),
            "adaptation_decision_ledger",
            "--version",
            str(ledger_version),
        )
        self.assertEqual(code, 2, payload)
        self.assertIn("adaptation_authorization_missing", payload["error"])

    def test_breakdowns_handoff_build_and_stale_propagation(self) -> None:
        self.create_ready_project()
        code, payload = self.run_cli(
            "validate-breakdowns", str(self.project), "--expected-episodes", "1"
        )
        self.assertEqual(code, 0, payload)
        code, payload = self.run_cli(
            "validate-handoff", str(self.project), "--expected-episodes", "1"
        )
        self.assertEqual(code, 0, payload)

        code, payload = self.run_cli(
            "build-handoff", str(self.project), "--expected-episodes", "1", "--output-name", "商用交付测试"
        )
        self.assertEqual(code, 0, payload)
        archive = Path(payload["archive"])
        manifest = Path(payload["manifest"])
        self.assertTrue(archive.is_file())
        self.assertTrue(manifest.is_file())
        with zipfile.ZipFile(archive) as package:
            self.assertTrue(any(name.endswith("交付清单.json") for name in package.namelist()))
            manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
            for item in manifest_payload["files"]:
                archived_path = f"商用交付测试/{item['package_path']}"
                data = package.read(archived_path)
                self.assertEqual(len(data), item["size_bytes"])
                self.assertEqual(hashlib.sha256(data).hexdigest(), item["sha256"])

        code, result = self.run_cli("approve", str(self.project), "final_package", "--note", "顺序测试")
        self.assertEqual(code, 2)
        self.assertIn("依赖必须是最新版且已获有效确认", result["error"])

        for key in ("delivery_manifest", "final_package"):
            code, result = self.run_cli("approve", str(self.project), key, "--note", "确认最终交付")
            self.assertEqual(code, 0, result)
        code, payload = self.run_cli(
            "validate-handoff", str(self.project), "--expected-episodes", "1", "--require-final-package"
        )
        self.assertEqual(code, 0, payload)

        episode_v2 = self.register_artifact(
            "episode_script:E001",
            "07_分集剧本/第001集_V2.md",
            GOOD_SCRIPT.replace("官差叩门声", "急促马蹄声"),
            ("adaptation_decision_ledger@1", "pilot_scripts@1", "pilot_review@1"),
        )
        project_id = self.state()["project_id"]
        boundary_v2 = self.register_and_approve(
            "episode_boundary_review:E001",
            "07_分集剧本/第001集内容边界V2.json",
            json.dumps(
                {
                    "schema_version": 1,
                    "project_id": project_id,
                    "generated_from": [
                        {"artifact_key": "source_event_index", "version": 1},
                        {"artifact_key": "story_facts", "version": 1},
                        {"artifact_key": "adaptation_decision_ledger", "version": 1},
                        {"artifact_key": "episode_script:E001", "version": episode_v2},
                    ],
                    "review_target": {
                        "artifact_key": "episode_script:E001",
                        "version": episode_v2,
                    },
                    "automation_limitations": "自动检查存在语义漏检风险，仍需人工复核。",
                    "findings": [{
                        "finding_id": "BR-E-002",
                        "category": "source_fidelity",
                        "result": "passed",
                        "location": "E001/1-1",
                        "description": "新版仍保持原著人物选择和事件结果。",
                        "evidence": "EV-0001 对应钥匙争夺。",
                        "source_refs": ["EV-0001"],
                    }],
                    "conclusion": "passed",
                },
                ensure_ascii=False,
            ),
            (
                "source_event_index@1",
                "story_facts@1",
                "adaptation_decision_ledger@1",
                f"episode_script:E001@{episode_v2}",
            ),
        )
        self.assertEqual(boundary_v2, 2)
        self.approve_artifact("episode_script:E001", episode_v2)
        state = self.state()
        self.assertEqual(state["artifacts"]["episode_script:E001"][-2]["status"], "superseded")
        self.assertEqual(state["artifacts"]["episode_script:E001"][-1]["status"], "confirmed")
        self.assertEqual(state["artifacts"]["character_roster"][-1]["status"], "stale")
        self.assertEqual(state["artifacts"]["delivery_manifest"][-1]["status"], "stale")
        self.assertEqual(state["artifacts"]["final_package"][-1]["status"], "stale")
        self.assertEqual(state["current_stage"], "quality_review")
        character_approval = next(
            item for item in state["approvals"]
            if item["artifact_key"] == "character_roster" and item["version"] == 1
        )
        self.assertIn("invalidated_at", character_approval)

    def test_define_batch_records_explicit_episode_scope(self) -> None:
        self.create_ready_project(expected_episodes=3)
        payload = self.define_batch("B01", ("E001", "E002"))
        self.assertEqual(payload["batch_id"], "B01")
        self.assertEqual(payload["episode_ids"], ["E001", "E002"])
        batch = self.state()["batches"]["B01"]
        self.assertEqual(batch["episode_ids"], ["E001", "E002"])
        self.assertEqual(batch["note"], "测试批次")
        self.assertTrue(batch["defined_at"])

    def test_define_batch_rejects_invalid_batch_id(self) -> None:
        self.create_ready_project(expected_episodes=2)
        code, payload = self.run_cli(
            "define-batch", str(self.project), "batch-1", "E001"
        )
        self.assertEqual(code, 2)
        self.assertIn("批次 ID", payload["error"])

    def test_define_batch_rejects_duplicate_episode_ids(self) -> None:
        self.create_ready_project(expected_episodes=2)
        code, payload = self.run_cli(
            "define-batch", str(self.project), "B01", "E001", "E001"
        )
        self.assertEqual(code, 2)
        self.assertIn("重复", payload["error"])

    def test_define_batch_rejects_episode_outside_project_spec(self) -> None:
        self.create_ready_project(expected_episodes=2)
        code, payload = self.run_cli(
            "define-batch", str(self.project), "B01", "E003"
        )
        self.assertEqual(code, 2)
        self.assertIn("项目规格", payload["error"])

    def test_define_batch_rejects_overlap_with_existing_batch(self) -> None:
        self.create_ready_project(expected_episodes=3)
        self.define_batch("B01", ("E001", "E002"))
        code, payload = self.run_cli(
            "define-batch", str(self.project), "B02", "E002", "E003"
        )
        self.assertEqual(code, 2)
        self.assertIn("B01", payload["error"])
        self.assertIn("E002", payload["error"])

    def test_batch_breakdown_validation_only_requires_batch_episodes(self) -> None:
        self.create_ready_project(expected_episodes=2)
        self.add_batch_delivery_inputs("B01")
        code, payload = self.run_cli(
            "validate-breakdowns", str(self.project), "--batch", "B01"
        )
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["batch_id"], "B01")
        self.assertEqual(payload["episode_ids"], ["E001"])
        self.assertEqual(payload["summary"]["episode_count"], 1)

        code, payload = self.run_cli(
            "validate-breakdowns", str(self.project), "--expected-episodes", "2"
        )
        self.assertEqual(code, 1, payload)
        self.assertIn(
            "breakdown_episode_missing",
            {item["code"] for item in payload["errors"]},
        )

    def test_batch_delivery_review_rejects_blocked_and_suspected_overreach(self) -> None:
        self.create_ready_project(expected_episodes=2)
        dependencies = self.add_batch_delivery_inputs("B01")
        for result, expected_text in (
            ("suspected_overreach", "suspected_overreach"),
            ("blocked", "blocked"),
        ):
            version = self.register_batch_delivery_review(
                dependencies,
                result=result,
                file_tag=result,
            )
            code, payload = self.run_cli(
                "approve",
                str(self.project),
                "batch_delivery_review:B01",
                "--version",
                str(version),
            )
            self.assertEqual(code, 2, payload)
            self.assertIn(expected_text, payload["error"])

    def test_batch_handoff_requires_series_batch_and_episode_boundary_reviews(self) -> None:
        self.create_ready_batch(expected_episodes=2)
        state_path = self.project / project_tool.STATE_FILENAME
        baseline = state_path.read_text(encoding="utf-8")
        for review_key, target_key in (
            ("series_boundary_review", "series_map"),
            ("batch_boundary_review:B01", "batch_outline:B01"),
            ("episode_boundary_review:E001", "episode_script:E001"),
        ):
            state = json.loads(baseline)
            state["artifacts"][review_key][-1]["status"] = "stale"
            state_path.write_text(
                json.dumps(state, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            code, payload = self.run_cli(
                "build-handoff",
                str(self.project),
                "--batch",
                "B01",
                "--output-name",
                f"缺失边界-{review_key.replace(':', '-')}",
            )
            self.assertEqual(code, 1, payload)
            unusable_targets = {
                item.get("artifact_key")
                for item in payload["errors"]
                if item["code"] == "confirmed_artifact_unusable"
            }
            self.assertIn(target_key, unusable_targets)
        state_path.write_text(baseline, encoding="utf-8")

    def test_batch_handoff_builds_independent_scoped_artifacts(self) -> None:
        self.create_ready_batch(expected_episodes=2)
        code, full_result = self.run_cli(
            "validate-handoff", str(self.project), "--expected-episodes", "2"
        )
        self.assertEqual(code, 1, full_result)
        self.assertIn(
            "episode_not_confirmed",
            {item["code"] for item in full_result["errors"]},
        )

        code, payload = self.run_cli(
            "build-handoff",
            str(self.project),
            "--batch",
            "B01",
            "--output-name",
            "B01批次交付",
        )
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["batch_id"], "B01")
        self.assertEqual(payload["artifact_key"], "batch_package:B01")
        self.assertEqual(
            payload["manifest_artifact_key"],
            "batch_delivery_manifest:B01",
        )
        manifest_payload = json.loads(
            Path(payload["manifest"]).read_text(encoding="utf-8")
        )
        self.assertEqual(
            manifest_payload["package_type"],
            "batch_production_ready_script_package",
        )
        self.assertEqual(manifest_payload["batch_id"], "B01")
        self.assertEqual(manifest_payload["episode_ids"], ["E001"])
        packaged_keys = {
            item["artifact_key"] for item in manifest_payload["files"]
        }
        for required_key in (
            "series_map",
            "series_boundary_review",
            "batch_outline:B01",
            "batch_boundary_review:B01",
            "episode_script:E001",
            "episode_boundary_review:E001",
            "character_roster:B01",
            "scene_catalog:B01",
            "prop_costume_ledger:B01",
            "dialogue_cue_sheet:B01",
            "continuity_ledger:B01",
            "quality_report:B01",
            "production_readiness_report:B01",
            "batch_delivery_review:B01",
        ):
            self.assertIn(required_key, packaged_keys)
        state = self.state()
        self.assertIn("batch_delivery_manifest:B01", state["artifacts"])
        self.assertIn("batch_package:B01", state["artifacts"])
        self.assertNotIn("delivery_manifest", state["artifacts"])
        self.assertNotIn("final_package", state["artifacts"])

    def test_batch_artifacts_do_not_change_full_series_handoff_behavior(self) -> None:
        self.create_ready_project()
        code, payload = self.run_cli(
            "build-handoff",
            str(self.project),
            "--expected-episodes",
            "1",
            "--output-name",
            "全剧交付",
        )
        self.assertEqual(code, 0, payload)
        full_manifest = self.state()["artifacts"]["delivery_manifest"][-1].copy()
        full_package = self.state()["artifacts"]["final_package"][-1].copy()

        dependencies = self.add_batch_delivery_inputs("B01")
        review_version = self.register_batch_delivery_review(dependencies)
        self.approve_artifact("batch_delivery_review:B01", review_version)
        code, payload = self.run_cli(
            "validate-handoff", str(self.project), "--expected-episodes", "1"
        )
        self.assertEqual(code, 0, payload)
        state = self.state()
        self.assertEqual(state["artifacts"]["delivery_manifest"][-1], full_manifest)
        self.assertEqual(state["artifacts"]["final_package"][-1], full_package)

    def test_batch_manifest_and_package_cannot_be_registered_manually(self) -> None:
        self.init_project()
        artifact_path = self.write_project_file("09_定稿交付/伪造.json", "{}")
        for key in ("batch_delivery_manifest:B01", "batch_package:B01"):
            code, payload = self.run_cli(
                "register-artifact",
                str(self.project),
                key,
                str(artifact_path),
            )
            self.assertEqual(code, 2, payload)
            self.assertIn("build-handoff", payload["error"])

    def test_batch_handoff_requires_continuity_snapshot(self) -> None:
        self.create_ready_batch(expected_episodes=1)
        state = self.state()
        state["artifacts"]["batch_continuity_snapshot:B01"][-1]["status"] = "stale"
        (self.project / project_tool.STATE_FILENAME).write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        result = project_tool.validate_batch_handoff_state(self.project, "B01")
        self.assertFalse(result["ready"])

    def test_series_handoff_assembles_current_batch_packages(self) -> None:
        self.create_ready_batch(expected_episodes=1)
        code, batch_payload = self.run_cli(
            "build-handoff",
            str(self.project),
            "--batch",
            "B01",
            "--output-name",
            "B01汇总输入",
        )
        self.assertEqual(code, 0, batch_payload)
        self.approve_artifact(
            "batch_delivery_manifest:B01",
            batch_payload["manifest_artifact_version"],
        )
        self.approve_artifact("batch_package:B01", batch_payload["version"])
        review_version = self.register_cross_batch_continuity_review()
        self.approve_artifact("cross_batch_continuity_review", review_version)
        validation = project_tool.validate_series_handoff_state(
            self.project, expected_episodes=1
        )
        self.assertTrue(validation["ready"], validation)
        code, payload = self.run_cli(
            "build-handoff",
            str(self.project),
            "--series",
            "--expected-episodes",
            "1",
            "--output-name",
            "全剧批次汇总",
        )
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["manifest_artifact_key"], "series_delivery_manifest")
        self.assertEqual(payload["artifact_key"], "final_package")

    def test_series_handoff_manifest_and_package_approve_with_scoped_dependencies(
        self,
    ) -> None:
        self.create_ready_batch(expected_episodes=1)
        code, batch_payload = self.run_cli(
            "build-handoff",
            str(self.project),
            "--batch",
            "B01",
            "--output-name",
            "B01汇总输入",
        )
        self.assertEqual(code, 0, batch_payload)
        self.approve_artifact(
            "batch_delivery_manifest:B01",
            batch_payload["manifest_artifact_version"],
        )
        self.approve_artifact("batch_package:B01", batch_payload["version"])
        review_version = self.register_cross_batch_continuity_review()
        self.approve_artifact("cross_batch_continuity_review", review_version)
        code, payload = self.run_cli(
            "build-handoff",
            str(self.project),
            "--series",
            "--expected-episodes",
            "1",
            "--output-name",
            "全剧批次汇总-可确认",
        )
        self.assertEqual(code, 0, payload)
        self.approve_artifact(
            "series_delivery_manifest",
            payload["manifest_artifact_version"],
        )
        self.approve_artifact("final_package", payload["version"])
        state = self.state()
        self.assertEqual(
            state["artifacts"]["series_delivery_manifest"][-1]["status"],
            "confirmed",
        )
        self.assertEqual(
            state["artifacts"]["final_package"][-1]["status"],
            "confirmed",
        )
        code, stage_payload = self.run_cli(
            "set-stage", str(self.project), "final_delivery", "completed"
        )
        self.assertEqual(code, 0, stage_payload)

    def test_series_handoff_rejects_missing_episode_coverage(self) -> None:
        self.create_ready_batch(expected_episodes=2)
        code, payload = self.run_cli(
            "build-handoff", str(self.project), "--batch", "B01", "--output-name", "B01单批"
        )
        self.assertEqual(code, 0, payload)
        self.approve_artifact(
            "batch_delivery_manifest:B01", payload["manifest_artifact_version"]
        )
        self.approve_artifact("batch_package:B01", payload["version"])
        review_version = self.register_cross_batch_continuity_review()
        self.approve_artifact("cross_batch_continuity_review", review_version)
        validation = project_tool.validate_series_handoff_state(
            self.project, expected_episodes=2
        )
        self.assertFalse(validation["ready"])
        self.assertIn(
            "series_batch_coverage_invalid",
            {item["code"] for item in validation["errors"]},
        )

    def test_cross_batch_continuity_review_must_pass(self) -> None:
        self.create_ready_batch(expected_episodes=1)
        version = self.register_cross_batch_continuity_review(conclusion="blocked")
        code, payload = self.run_cli(
            "approve",
            str(self.project),
            "cross_batch_continuity_review",
            "--version",
            str(version),
        )
        self.assertEqual(code, 2, payload)
        self.assertIn("cross_batch_review_conclusion_invalid", payload["error"])

    def test_legacy_full_handoff_reports_deprecation_warning(self) -> None:
        self.create_ready_project()
        code, payload = self.run_cli(
            "build-handoff",
            str(self.project),
            "--expected-episodes",
            "1",
            "--output-name",
            "旧全剧兼容包",
        )
        self.assertEqual(code, 0, payload)
        self.assertIn(
            "legacy_full_handoff_deprecated",
            {item["code"] for item in payload["warnings"]},
        )

    def test_breakdown_rejects_cross_reference_mismatch(self) -> None:
        self.create_ready_project()
        state = self.state()
        scene_path = self.project / state["artifacts"]["scene_catalog"][-1]["path"]
        payload = json.loads(scene_path.read_text(encoding="utf-8"))
        payload["records"][0]["character_ids"] = ["C001"]
        scene_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        result = project_tool.validate_breakdowns_state(self.project, expected_episodes=1)
        self.assertFalse(result["valid"])
        codes = {item["code"] for item in result["errors"]}
        self.assertTrue({"artifact_hash_mismatch", "catalog_characters_mismatch"} & codes)

    def test_non_object_breakdown_record_is_rejected(self) -> None:
        self.create_ready_project()
        state = self.state()
        record = state["artifacts"]["character_roster"][-1]
        path = self.project / record["path"]
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["records"].append("junk")
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        record["sha256"] = project_tool.sha256_file(path)
        record["size_bytes"] = path.stat().st_size
        (self.project / project_tool.STATE_FILENAME).write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        result = project_tool.validate_breakdowns_state(self.project, expected_episodes=1)
        self.assertFalse(result["valid"])
        self.assertIn("breakdown_record_invalid", {item["code"] for item in result["errors"]})

    def test_quality_report_rejects_non_object_issue(self) -> None:
        self.create_ready_project()
        state = self.state()
        record = state["artifacts"]["quality_report"][-1]
        path = self.project / record["path"]
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["issues"] = ["junk"]
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        record["sha256"] = project_tool.sha256_file(path)
        record["size_bytes"] = path.stat().st_size
        (self.project / project_tool.STATE_FILENAME).write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        result = project_tool.validate_handoff_state(self.project, expected_episodes=1)
        self.assertFalse(result["ready"])
        self.assertIn("quality_issue_invalid", {item["code"] for item in result["errors"]})

    def test_scene_catalog_rejects_empty_required_fields(self) -> None:
        self.create_ready_project()
        state = self.state()
        record = state["artifacts"]["scene_catalog"][-1]
        path = self.project / record["path"]
        payload = json.loads(path.read_text(encoding="utf-8"))
        for field in ("location_id", "location_name", "time", "space", "entry_state", "exit_state"):
            payload["records"][0][field] = ""
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        record["sha256"] = project_tool.sha256_file(path)
        record["size_bytes"] = path.stat().st_size
        (self.project / project_tool.STATE_FILENAME).write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        result = project_tool.validate_handoff_state(self.project, expected_episodes=1)
        self.assertFalse(result["ready"])
        codes = {item["code"] for item in result["errors"]}
        self.assertIn("catalog_scene_field_empty", codes)
        self.assertIn("catalog_scene_time_invalid", codes)
        self.assertIn("catalog_scene_space_invalid", codes)

    def test_scene_catalog_must_match_script_heading(self) -> None:
        self.create_ready_project()
        state = self.state()
        record = state["artifacts"]["scene_catalog"][-1]
        path = self.project / record["path"]
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["records"][0].update(
            {"location_name": "偏院", "time": "夜", "space": "内"}
        )
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        record["sha256"] = project_tool.sha256_file(path)
        record["size_bytes"] = path.stat().st_size
        (self.project / project_tool.STATE_FILENAME).write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        result = project_tool.validate_breakdowns_state(self.project, expected_episodes=1)
        self.assertFalse(result["valid"])
        codes = {item["code"] for item in result["errors"]}
        self.assertIn("catalog_location_name_mismatch", codes)
        self.assertIn("catalog_time_mismatch", codes)
        self.assertIn("catalog_space_mismatch", codes)

    def test_scene_catalog_location_id_cannot_bind_different_names(self) -> None:
        self.create_ready_project()
        state = self.state()
        record = state["artifacts"]["scene_catalog"][-1]
        path = self.project / record["path"]
        payload = json.loads(path.read_text(encoding="utf-8"))
        conflicting = dict(payload["records"][0])
        conflicting.update({"scene_id": "1-2", "location_name": "偏院"})
        payload["records"].append(conflicting)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        record["sha256"] = project_tool.sha256_file(path)
        record["size_bytes"] = path.stat().st_size
        (self.project / project_tool.STATE_FILENAME).write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        result = project_tool.validate_breakdowns_state(self.project, expected_episodes=1)
        self.assertFalse(result["valid"])
        self.assertIn(
            "catalog_location_id_name_conflict",
            {item["code"] for item in result["errors"]},
        )

    def test_continuity_ledger_requires_exact_sources_and_scene_coverage(self) -> None:
        self.create_ready_project()
        state = self.state()
        record = state["artifacts"]["continuity_ledger"][-1]
        path = self.project / record["path"]
        valid_payload = json.loads(path.read_text(encoding="utf-8"))

        def validate(content: str) -> dict:
            path.write_text(content, encoding="utf-8")
            record["sha256"] = project_tool.sha256_file(path)
            record["size_bytes"] = path.stat().st_size
            (self.project / project_tool.STATE_FILENAME).write_text(
                json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            return project_tool.validate_handoff_state(self.project, expected_episodes=1)

        result = validate("{not-json")
        self.assertFalse(result["ready"])
        self.assertIn(
            "continuity_ledger_json_required",
            {item["code"] for item in result["errors"]},
        )

        wrong_sources = json.loads(json.dumps(valid_payload, ensure_ascii=False))
        wrong_sources["generated_from"] = []
        result = validate(json.dumps(wrong_sources, ensure_ascii=False))
        self.assertIn(
            "continuity_source_versions_mismatch",
            {item["code"] for item in result["errors"]},
        )

        missing_scene = json.loads(json.dumps(valid_payload, ensure_ascii=False))
        missing_scene["records"] = []
        result = validate(json.dumps(missing_scene, ensure_ascii=False))
        self.assertIn(
            "continuity_scene_missing",
            {item["code"] for item in result["errors"]},
        )

        extra_scene = json.loads(json.dumps(valid_payload, ensure_ascii=False))
        extra_record = dict(extra_scene["records"][0])
        extra_record["scene_id"] = "1-2"
        extra_scene["records"].append(extra_record)
        result = validate(json.dumps(extra_scene, ensure_ascii=False))
        self.assertIn(
            "continuity_scene_extra",
            {item["code"] for item in result["errors"]},
        )

        incomplete = json.loads(json.dumps(valid_payload, ensure_ascii=False))
        del incomplete["records"][0]["relative_time"]
        incomplete["records"][0]["character_states"] = {}
        incomplete["records"][0]["end_state"] = ""
        result = validate(json.dumps(incomplete, ensure_ascii=False))
        errors = result["errors"]
        self.assertTrue(
            any(
                item["code"] == "continuity_record_field_missing"
                and item.get("field") == "relative_time"
                for item in errors
            )
        )
        empty_fields = {
            item.get("field")
            for item in errors
            if item["code"] == "continuity_record_field_empty"
        }
        self.assertTrue({"character_states", "end_state"}.issubset(empty_fields))

    def test_handoff_binds_expected_episodes_to_project_spec(self) -> None:
        self.create_ready_project()
        result = project_tool.validate_handoff_state(self.project, expected_episodes=2)
        self.assertFalse(result["ready"])
        self.assertIn("expected_episodes_mismatch", {item["code"] for item in result["errors"]})

    def test_handoff_rejects_series_map_count_conflict(self) -> None:
        self.create_ready_project()
        state = self.state()
        record = state["artifacts"]["series_map"][-1]
        path = self.project / record["path"]
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["expected_episodes"] = 5
        payload["episodes"] = [
            {"episode_id": f"E{number:03d}", "title": f"第{number}集"}
            for number in range(1, 6)
        ]
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        record["sha256"] = project_tool.sha256_file(path)
        record["size_bytes"] = path.stat().st_size
        (self.project / project_tool.STATE_FILENAME).write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        result = project_tool.validate_handoff_state(self.project, expected_episodes=1)
        self.assertFalse(result["ready"])
        self.assertIn("series_map_episode_count_mismatch", {item["code"] for item in result["errors"]})

    def test_handoff_accepts_legacy_and_backbone_series_map_granularity(self) -> None:
        self.create_ready_project()
        legacy_result = project_tool.validate_handoff_state(
            self.project, expected_episodes=1
        )
        self.assertTrue(legacy_result["ready"], legacy_result)

        self.update_artifact_json(
            "series_map", lambda payload: payload.update({"granularity": "backbone"})
        )
        backbone_result = project_tool.validate_handoff_state(
            self.project, expected_episodes=1
        )
        self.assertTrue(backbone_result["ready"], backbone_result)

    def test_handoff_rejects_invalid_or_incomplete_backbone_series_map(self) -> None:
        self.create_ready_project(expected_episodes=2)
        self.update_artifact_json(
            "series_map", lambda payload: payload.update({"granularity": "summary"})
        )
        invalid_result = project_tool.validate_handoff_state(
            self.project, expected_episodes=2
        )
        self.assertIn(
            "series_map_granularity_invalid",
            {item["code"] for item in invalid_result["errors"]},
        )
        invalid_state = project_tool.validate_state(self.project)
        self.assertIn(
            "series_map_granularity_invalid",
            {item["code"] for item in invalid_state["errors"]},
        )

        def make_incomplete(payload: dict) -> None:
            payload["granularity"] = "backbone"
            payload["episodes"] = payload["episodes"][:1]

        self.update_artifact_json("series_map", make_incomplete)
        incomplete_result = project_tool.validate_handoff_state(
            self.project, expected_episodes=2
        )
        self.assertIn(
            "series_map_episode_coverage_invalid",
            {item["code"] for item in incomplete_result["errors"]},
        )
        incomplete_state = project_tool.validate_state(self.project)
        self.assertIn(
            "series_map_episode_coverage_invalid",
            {item["code"] for item in incomplete_state["errors"]},
        )

    def test_v08_backbone_requires_summary_and_warns_for_optional_fields(self) -> None:
        self.create_ready_project()

        def make_missing_summary(payload: dict) -> None:
            payload["contract_version"] = 2
            payload["granularity"] = "backbone"
            payload["episodes"] = [{"episode_id": "E001"}]

        self.update_artifact_json("series_map", make_missing_summary)
        missing = project_tool.validate_state(self.project)
        self.assertIn(
            "series_map_backbone_summary_missing",
            {item["code"] for item in missing["errors"]},
        )

        def add_summary(payload: dict) -> None:
            payload["episodes"][0]["summary"] = "阿宁拒绝交出母亲留下的钥匙。"

        self.update_artifact_json("series_map", add_summary)
        valid = project_tool.validate_state(self.project)
        self.assertTrue(valid["valid"], valid)
        self.assertIn(
            "series_map_backbone_field_recommended",
            {item["code"] for item in valid["warnings"]},
        )

    def test_batch_source_detail_rejects_chapter_summary(self) -> None:
        self.create_ready_project()
        self.define_batch("B01")
        project_id = self.state()["project_id"]
        scope_version = self.register_and_approve(
            "batch_source_scope:B01",
            "01_原著解析/B01_原著范围.json",
            json.dumps(
                {
                    "schema_version": 1,
                    "project_id": project_id,
                    "batch_id": "B01",
                    "episode_ids": ["E001"],
                    "required_source_unit_ids": ["SRC-CH001"],
                    "generated_from": [
                        {"artifact_key": "series_map", "version": 1},
                        {"artifact_key": "source_corpus", "version": 1},
                    ],
                },
                ensure_ascii=False,
            ),
            ("series_map@1", "source_corpus@1"),
        )
        path = self.write_json(
            "01_原著解析/B01_错误细化.json",
            {
                "schema_version": 1,
                "project_id": project_id,
                "batch_id": "B01",
                "generated_from": [
                    {"artifact_key": "batch_source_scope:B01", "version": scope_version},
                    {"artifact_key": "source_event_index", "version": 1},
                    {"artifact_key": "source_corpus", "version": 1},
                ],
                "units": [
                    {
                        "source_unit_id": "SRC-CH001",
                        "granularity": "chapter_summary",
                        "events": [
                            {
                                "event_id": "EV-B01-001",
                                "summary": "钥匙争夺开始。",
                                "source_refs": ["SRC-CH001"],
                            }
                        ],
                    }
                ],
            },
        )
        code, payload = self.run_cli(
            "register-artifact",
            str(self.project),
            "batch_source_detail:B01",
            str(path),
            "--status",
            "awaiting_approval",
            "--depends-on",
            f"batch_source_scope:B01@{scope_version}",
            "--depends-on",
            "source_event_index@1",
            "--depends-on",
            "source_corpus@1",
        )
        self.assertEqual(code, 0, payload)
        code, payload = self.run_cli(
            "approve",
            str(self.project),
            "batch_source_detail:B01",
            "--version",
            str(payload["version"]),
        )
        self.assertEqual(code, 2, payload)
        self.assertIn("batch_source_detail_granularity_invalid", payload["error"])

    def test_batch_handoff_requires_current_source_scope_and_detail(self) -> None:
        self.create_ready_batch(expected_episodes=2)
        state = self.state()
        state["artifacts"]["batch_source_detail:B01"][-1]["status"] = "stale"
        (self.project / project_tool.STATE_FILENAME).write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        result = project_tool.validate_batch_handoff_state(self.project, "B01")
        self.assertFalse(result["ready"])
        self.assertIn(
            "confirmed_artifact_unusable",
            {item["code"] for item in result["errors"]},
        )

    def test_source_event_index_accepts_legacy_and_tracked_chapter_summary(self) -> None:
        self.create_ready_project()
        legacy_result = project_tool.validate_state(self.project)
        self.assertTrue(legacy_result["valid"], legacy_result)

        def make_summary(payload: dict) -> None:
            unit = payload["units"][0]
            unit["granularity"] = "chapter_summary"
            event = unit["events"][0]
            for field in ("cause", "action", "outcome", "state_change"):
                del event[field]
            payload["upgrade_pending"] = ["SRC-CH001"]

        self.update_artifact_json("source_event_index", make_summary)
        summary_result = project_tool.validate_state(self.project)
        self.assertTrue(summary_result["valid"], summary_result)


    def test_source_event_index_rejects_unknown_character_id(self) -> None:
        self.create_ready_project()

        def add_unknown_character(payload: dict) -> None:
            payload["units"][0]["events"][0]["participants"].append("CHAR-UNKNOWN")

        self.update_artifact_json("source_event_index", add_unknown_character)
        result = project_tool.validate_state(self.project)
        self.assertIn(
            "event_participant_unknown",
            {item["code"] for item in result["errors"]},
        )

    def test_source_event_index_schema_v2_requires_canonical_entities(self) -> None:
        self.create_ready_project()

        def remove_entities(payload: dict) -> None:
            payload.pop("entities", None)

        self.update_artifact_json("source_event_index", remove_entities)
        result = project_tool.validate_state(self.project)
        self.assertIn(
            "event_entities_missing",
            {item["code"] for item in result["errors"]},
        )

    def test_source_event_index_accepts_typed_short_character_location_and_prop_ids(self) -> None:
        self.create_ready_project()

        def add_typed_entities(payload: dict) -> None:
            payload["entities"].extend(
                [
                    {"entity_id": "L001", "entity_type": "location", "canonical_name": "院门", "aliases": []},
                    {"entity_id": "P001", "entity_type": "prop", "canonical_name": "钥匙", "aliases": []},
                ]
            )

        self.update_artifact_json("source_event_index", add_typed_entities)
        result = project_tool.validate_state(self.project)
        self.assertNotIn(
            "event_entity_id_invalid",
            {item["code"] for item in result["errors"]},
            result,
        )

    def test_source_event_index_requires_exact_upgrade_pending_tracking(self) -> None:
        self.create_ready_project()

        def make_untracked_summary(payload: dict) -> None:
            payload["units"][0]["granularity"] = "chapter_summary"
            payload["upgrade_pending"] = []

        self.update_artifact_json("source_event_index", make_untracked_summary)
        result = project_tool.validate_state(self.project)
        self.assertIn(
            "event_upgrade_pending_mismatch",
            {item["code"] for item in result["errors"]},
        )

    def test_source_event_index_rejects_invalid_granularity(self) -> None:
        self.create_ready_project()

        def make_invalid(payload: dict) -> None:
            payload["units"][0]["granularity"] = "outline"
            payload["upgrade_pending"] = []

        self.update_artifact_json("source_event_index", make_invalid)
        result = project_tool.validate_state(self.project)
        self.assertIn(
            "event_unit_granularity_invalid",
            {item["code"] for item in result["errors"]},
        )

    def test_chapter_summary_source_index_still_requires_full_unit_coverage(self) -> None:
        self.create_ready_project()
        second_source = self.write_project_file(
            "00_原始材料/标准化正文_第002章.txt",
            "管家请来族老商议钥匙归属。\n",
        )

        def add_corpus_unit(payload: dict) -> None:
            payload["source_units"].append(
                {
                    "source_unit_id": "SRC-CH002",
                    "source_id": self.state()["sources"][0]["source_id"],
                    "source_locator": "第2章",
                    "ordinal": 2,
                    "content_path": second_source.relative_to(self.project).as_posix(),
                    "content_sha256": project_tool.sha256_file(second_source),
                }
            )

        self.update_artifact_json("source_corpus", add_corpus_unit)

        def keep_only_first_summary(payload: dict) -> None:
            payload["units"][0]["granularity"] = "chapter_summary"
            payload["upgrade_pending"] = ["SRC-CH001"]

        self.update_artifact_json("source_event_index", keep_only_first_summary)
        result = project_tool.validate_state(self.project)
        self.assertIn(
            "event_unit_coverage_mismatch",
            {item["code"] for item in result["errors"]},
        )

    def test_boolean_version_is_invalid(self) -> None:
        self.create_ready_project()
        state = self.state()
        state["artifacts"]["project_spec"][0]["version"] = True
        for approval in state["approvals"]:
            if approval["artifact_key"] == "project_spec":
                approval["version"] = True
        for dependency in state["artifacts"]["source_corpus"][0]["depends_on"]:
            if dependency["artifact_key"] == "project_spec":
                dependency["version"] = True
        (self.project / project_tool.STATE_FILENAME).write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        result = project_tool.validate_state(self.project)
        self.assertFalse(result["valid"])
        self.assertIn("artifact_version_invalid", {item["code"] for item in result["errors"]})

    def test_no_cascade_still_exposes_invalid_dependency(self) -> None:
        self.create_ready_project()
        code, payload = self.run_cli(
            "mark-stale", str(self.project), "batch_outline", "--reason", "大纲需返修", "--no-cascade"
        )
        self.assertEqual(code, 0, payload)
        result = project_tool.validate_state(self.project)
        self.assertFalse(result["valid"])
        self.assertIn("confirmed_artifact_unusable", {item["code"] for item in result["errors"]})
        code, payload = self.run_cli(
            "set-stage", str(self.project), "batch_writing", "completed", "--note", "尝试绕过"
        )
        self.assertEqual(code, 2)

    def test_scoped_episode_cannot_bind_wrong_batch(self) -> None:
        self.create_ready_project()
        batch_path = self.write_project_file("05_批次大纲/E001大纲V1.md", "# E001 大纲\n")
        code, payload = self.run_cli(
            "register-artifact", str(self.project), "batch_outline:B001:E001", str(batch_path),
            "--status", "awaiting_approval", "--depends-on", "adaptation_decision_ledger@1",
            "--depends-on", "series_map@1",
            "--depends-on", "series_plan_review@1",
        )
        self.assertEqual(code, 0, payload)
        script_path = self.write_project_file(
            "07_分集剧本/第002集_V1.md",
            GOOD_SCRIPT.replace("第1集", "第2集").replace("1-1", "2-1"),
        )
        code, payload = self.run_cli(
            "register-artifact", str(self.project), "episode_script:E002", str(script_path),
            "--status", "awaiting_approval", "--depends-on", "adaptation_decision_ledger@1",
            "--depends-on", "batch_outline:B001:E001@1", "--depends-on", "pilot_review@1",
        )
        self.assertEqual(code, 2)
        self.assertIn("依赖剧集范围不足", payload["error"])

    def test_episode_key_mismatch_cannot_be_approved(self) -> None:
        self.create_ready_project()
        path = self.write_project_file("07_分集剧本/错绑第002集.md", GOOD_SCRIPT)
        code, payload = self.run_cli(
            "register-artifact", str(self.project), "episode_script:E002", str(path),
            "--status", "awaiting_approval", "--depends-on", "adaptation_decision_ledger@1",
            "--depends-on", "batch_outline@1", "--depends-on", "pilot_review@1",
        )
        self.assertEqual(code, 0, payload)
        code, payload = self.run_cli("approve", str(self.project), "episode_script:E002")
        self.assertEqual(code, 2)
        self.assertIn("与文件中的第1集不一致", payload["error"])

    def test_validate_project_checks_script_key_and_bad_version_without_crash(self) -> None:
        self.create_ready_project()
        state = self.state()
        original_record = dict(state["artifacts"]["episode_script:E001"][-1])
        state["artifacts"]["episode_script:E002"] = [original_record]
        state["approvals"].append({
            "approval_id": "test-mismatch", "artifact_key": "episode_script:E002",
            "version": 1, "approved_at": "2026-01-01T00:00:00+00:00", "approved_by": "test",
        })
        state["artifacts"]["project_spec"].append({
            "version": "bad", "artifact_type": "project_spec",
            "path": original_record["path"], "size_bytes": original_record["size_bytes"],
            "sha256": original_record["sha256"], "status": "draft", "depends_on": [],
            "registered_at": "2026-01-01T00:00:00+00:00", "note": "损坏版本测试",
        })
        (self.project / project_tool.STATE_FILENAME).write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        result = project_tool.validate_state(self.project)
        self.assertFalse(result["valid"])
        codes = {item["code"] for item in result["errors"]}
        self.assertIn("artifact_version_invalid", codes)
        self.assertIn("episode_script_key_mismatch", codes)


    def test_genre_profile_validation_and_approval(self) -> None:
        self.create_ready_project()
        bad = {
            "schema_version": 1,
            "project_id": self.state()["project_id"],
            "generated_from": [{"artifact_key": "story_facts", "version": 1}],
            "tags": [
                {"tag_id": "audience.female", "layer": "audience", "label": "女频", "evidence": ["EV-0001:阿宁的选择驱动主线"], "confidence": "high"},
                {"tag_id": "audience.male", "layer": "audience", "label": "男频", "evidence": ["无"], "confidence": "high"},
                {"tag_id": "genre.house_intrigue", "layer": "genre", "label": "宅斗", "evidence": [], "confidence": "certain"},
            ],
            "primary_genre": "genre.revenge",
            "adaptation_directives": {},
        }
        version = self.register_artifact(
            "genre_profile", "02_改编定位/题材标签卡V1.json",
            json.dumps(bad, ensure_ascii=False), ("story_facts@1",),
        )
        code, payload = self.run_cli(
            "approve", str(self.project), "genre_profile", "--version", str(version)
        )
        self.assertEqual(code, 2, payload)
        for expected in (
            "genre_audience_count_invalid",
            "genre_tag_evidence_missing",
            "genre_tag_confidence_invalid",
            "genre_primary_invalid",
            "genre_directives_missing",
        ):
            self.assertIn(expected, payload["error"], expected)

        good = {
            "schema_version": 1,
            "project_id": self.state()["project_id"],
            "generated_from": [{"artifact_key": "story_facts", "version": 1}],
            "tags": [
                {"tag_id": "audience.female", "layer": "audience", "label": "女频", "evidence": ["EV-0001:阿宁拒交钥匙,主线由其选择驱动"], "confidence": "high"},
                {"tag_id": "genre.house_intrigue", "layer": "genre", "label": "宅斗/家族", "evidence": ["EV-0001:钥匙代表家宅资源控制权"], "confidence": "medium"},
                {"tag_id": "trope.hidden_identity", "layer": "trope", "label": "隐藏身份", "evidence": ["EV-0001:母亲遗物暗示未揭身世"], "confidence": "low"},
            ],
            "primary_genre": "genre.house_intrigue",
            "adaptation_directives": {
                "hook_preferences": ["证据反转"],
                "pacing_notes": "每集一次公开对峙",
                "asset_bias": ["府邸主场景复用"],
                "risk_checks": ["称谓礼制核对"],
            },
            "uncertainties": ["是否含重生元素:现有片段无证据"],
        }
        self.register_and_approve(
            "genre_profile", "02_改编定位/题材标签卡V2.json",
            json.dumps(good, ensure_ascii=False), ("story_facts@1",),
        )

    def test_add_source_marks_dependency_chain_stale(self) -> None:
        self.create_ready_project()
        extra = self.root / "第2章.txt"
        extra.write_text("管家连夜请来族老，要开祠堂议钥匙归属。\n", encoding="utf-8")
        code, payload = self.run_cli("add-source", str(self.project), str(extra))
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["source_corpus_marked_stale"], 1)
        state = self.state()
        self.assertEqual(len(state["sources"]), 2)
        corpus = max(state["artifacts"]["source_corpus"], key=lambda item: item["version"])
        self.assertEqual(corpus["status"], "stale")
        index = max(state["artifacts"]["source_event_index"], key=lambda item: item["version"])
        self.assertEqual(index["status"], "stale")
        code, payload = self.run_cli("add-source", str(self.project), str(extra))
        self.assertEqual(code, 2, payload)
        self.assertIn("已登记过", payload["error"])

    def test_shot_plan_duration_deviation_requires_note(self) -> None:
        self.create_ready_project()
        self.register_ai_layer_prerequisites()
        plan = self.shot_plan_payload()
        plan["target_duration_seconds"] = 60
        plan.pop("duration_deviation_note", None)
        version = self.register_artifact(
            "ai_shot_plan:E001",
            "10_AI视频执行包/E001_超差分镜计划V1.json",
            json.dumps(plan, ensure_ascii=False),
            self.shot_plan_dependencies(),
        )
        code, payload = self.run_cli(
            "approve", str(self.project), "ai_shot_plan:E001", "--version", str(version)
        )
        self.assertEqual(code, 2, payload)
        self.assertIn("shotplan_duration_deviation", payload["error"])

    def register_ai_layer_prerequisites(self) -> None:
        self.register_and_approve(
            "style_anchor", "10_AI视频执行包/风格锚点V1.md", "# 风格锚点\n半写实国漫。\n",
            ("adaptation_bible@1",),
        )
        for character_id, name, appearance in (
            ("C001", "阿宁", "黑发少女，青布衫，身材轻盈，五官清秀"),
            ("C002", "管家", "灰发老者，灰袍，身形微弯，面部轮廓清晰"),
        ):
            anchor = {
                "contract_version": 2,
                "character_id": character_id,
                "display_name": name,
                "role_kind": "stable",
                "source_appearance": {"source_refs": ["SRC-CH001"], "confirmed_details": [appearance]},
                "visual_design": {
                    "auto_completed": True,
                    "face": appearance,
                    "hair": appearance,
                    "body": appearance,
                    "wardrobe": appearance,
                    "distinctive_features": [],
                },
                "turnaround_prompt": {
                    "layout": "左侧约三分之一为完整正面头肩肖像；右侧依次并排展示全身正面、侧面和背面",
                    "consistency_rules": ["四个视图五官、发型、身材比例和服装完全一致"],
                    "full_text": f"{appearance}。左侧为完整正面头肩肖像，右侧依次并排展示全身正面、侧面和背面。",
                },
                "forbidden_story_implications": ["不得暗示原著未公开身份"],
            }
            self.register_and_approve(
                f"character_anchor:{character_id}",
                f"10_AI视频执行包/角色锚点_{character_id}V1.json",
                json.dumps(anchor, ensure_ascii=False),
                ("character_roster@1",),
            )
        self.register_and_approve(
            "scene_anchor:L001", "10_AI视频执行包/场景锚点_L001V1.md", "# 院门\n灰砖院门，日景。\n",
            ("scene_catalog@1",),
        )
        profile = {
            "schema_version": 1,
            "project_id": self.state()["project_id"],
            "generated_from": [{"artifact_key": "project_spec", "version": 1}],
            "model_family": "Seedance 2.0",
            "provider_model_id": "doubao-seedance-2-0-test",
            "capability_snapshot": {
                "status": "user_confirmed",
                "checked_at": "2026-07-26",
                "source_urls": ["https://seed.bytedance.com/zh/seedance2_0"],
            },
            "capabilities": {
                "task_duration_seconds": {"min": 4, "max": 15},
                "ratios": ["16:9"],
                "resolutions": ["1080p"],
                "generate_audio": True,
                "lip_sync": True,
                "max_reference_images": 4,
                "supports_first_frame": True,
                "supports_first_last_frame": None,
                "supports_continuation": True,
                "max_clear_speakers": 1,
                "input_modes": ["text_to_video", "first_frame", "continuation"],
            },
        }
        self.register_and_approve(
            "model_capability_profile:seedance-2-0",
            "10_AI视频执行包/模型能力档案V1.json",
            json.dumps(profile, ensure_ascii=False),
            ("project_spec@1",),
        )

    def shot_plan_dependencies(self) -> tuple[str, ...]:
        return (
            "source_event_index@1",
            "story_facts@1",
            "adaptation_decision_ledger@1",
            "episode_script:E001@1",
            "episode_boundary_review:E001@1",
            "dialogue_cue_sheet@1",
            "style_anchor@1",
            "character_anchor:C001@1",
            "character_anchor:C002@1",
            "scene_anchor:L001@1",
        )

    def shot_plan_payload(self) -> dict:
        state_a = {"characters": {
            "C001": {"position": "门槛外", "facing": "面向管家", "wardrobe": "青布衫", "props": ["钥匙"], "injuries": "无", "knowledge": "不知官差将至"},
            "C002": {"position": "院门内", "facing": "面向阿宁", "wardrobe": "灰袍", "props": [], "injuries": "无", "knowledge": "不知官差将至"},
        }}
        state_b = {"characters": {
            "C001": {"position": "门槛外", "facing": "面向管家", "wardrobe": "青布衫", "props": ["钥匙(藏袖后)"], "injuries": "无", "knowledge": "不知官差将至"},
            "C002": {"position": "堵住院门", "facing": "面向阿宁", "wardrobe": "灰袍", "props": [], "injuries": "无", "knowledge": "不知官差将至"},
        }}
        characters = [
            {"character_id": "C001", "space_id": "courtyard-gate", "presence": "on_screen", "anchor_ref": {"artifact_key": "character_anchor:C001", "version": 1}, "appearance_lock": "黑发少女，青布衫", "wardrobe": "青布衫"},
            {"character_id": "C002", "space_id": "courtyard-gate", "presence": "on_screen", "anchor_ref": {"artifact_key": "character_anchor:C002", "version": 1}, "appearance_lock": "灰袍老者", "wardrobe": "灰袍"},
        ]
        return {
            "schema_version": 1,
            "content_contract_version": 1,
            "shot_language_contract_version": 2,
            "project_id": self.state()["project_id"],
            "episode_id": "E001",
            "generated_from": [
                {"artifact_key": value.rsplit("@", 1)[0], "version": int(value.rsplit("@", 1)[1])}
                for value in self.shot_plan_dependencies()
            ],
            "hard_blocks": ["不得提前揭示门外官差身份", "不得展示钥匙对应的箱柜内部"],
            "target_duration_seconds": 60,
            "duration_deviation_note": "最小测试夹具仅覆盖两个分镜单元",
            "source_fidelity": {
                "source_order_preserved": True,
                "within_source_endpoint": True,
                "protected_facts_preserved": True,
                "unsupported_story_facts": [],
                "dialogue_intent_preserved": True,
            },
            "asset_budget": {"max_scene_anchors": 2, "max_speaking_characters": 4},
            "units": [
                {
                    "unit_id": "SP-E001-U001",
                    "sequence": 1,
                    "scene_id": "1-1",
                    "narrative_task": "管家：把钥匙交出来。",
                    "shot_language": {"shot_size": {"start": "medium_shot", "end": "medium_shot"}, "camera_angle": "平视", "composition": "双人对峙", "camera_movement": {"type": "static", "subject": "", "description": "固定中景，阿宁与管家在院门两侧对峙。"}, "visual_focus": "钥匙", "transition": "直接切入"},
                    "production_feasibility": {"dialogue_fits_duration": True, "action_fits_duration": True, "physical_preconditions_complete": True, "time_span_supported": True, "screen_text_post_plan_complete": True},
                    "duration_seconds": 3,
                    "action_start": "管家：把钥匙交出来。",
                    "action_end": "管家：把钥匙交出来。",
                    "source_refs": ["EV-0001"],
                    "source_beat_refs": ["B001"],
                    "preserved_fact_ids": [],
                    "new_fact_claims": [],
                    "decision_ids": ["AD-0001"],
                    "content_atoms": [{"atom_id": "CA-U001-001", "origin": "source", "source_atom_id": "SA-B001-002", "text": "管家：把钥匙交出来。"}],
                    "content_bindings": {"narrative_task": ["CA-U001-001"], "action_start": ["CA-U001-001"], "action_end": ["CA-U001-001"]},
                    "fact_realizations": [],
                    "characters_on_screen": characters,
                    "scene_anchor_ref": {"artifact_key": "scene_anchor:L001", "version": 1},
                    "dialogue": [{"cue_id": "Q001", "lip_sync": True}],
                    "space_zones": [{"space_id": "courtyard-gate", "kind": "exterior"}],
                    "sound_events": [{"sound_id": "S001", "description": "院外蝉鸣", "source_type": "ambient", "space_id": "courtyard-gate", "scope": "unit"}],
                    "action_flow": {"enter_states": ["阿宁在门槛外", "管家在院门内"], "steps": [{"step_id": "A001", "content_atom_refs": ["CA-U001-001"], "requires": ["阿宁在门槛外", "管家在院门内"], "produces": ["管家伸手拦路"], "min_duration_seconds": 1}], "exit_states": ["管家伸手拦路"]},
                    "time_span_mode": "continuous",
                    "negative_constraints": ["不出现官差", "无字幕"],
                    "generation_strategy": "text_to_video",
                    "state_chain": {"chain_id": "CHAIN-E001-S01", "enter": state_a, "exit": state_b},
                },
                {
                    "unit_id": "SP-E001-U002",
                    "sequence": 2,
                    "scene_id": "1-1",
                    "narrative_task": "阿宁：这是母亲留给我的。",
                    "shot_language": {"shot_size": {"start": "medium_close_up", "end": "close_up"}, "camera_angle": "平视", "composition": "阿宁前景管家后景", "camera_movement": {"type": "push_in", "subject": "C001", "description": "从阿宁上半身缓慢推近至藏钥匙的手。"}, "visual_focus": "藏钥匙的手", "transition": "动作衔接"},
                    "production_feasibility": {"dialogue_fits_duration": True, "action_fits_duration": True, "physical_preconditions_complete": True, "time_span_supported": True, "screen_text_post_plan_complete": True},
                    "duration_seconds": 4,
                    "action_start": "阿宁：这是母亲留给我的。",
                    "action_end": "阿宁：这是母亲留给我的。",
                    "source_refs": ["EV-0001"],
                    "source_beat_refs": ["B001"],
                    "preserved_fact_ids": [],
                    "new_fact_claims": [],
                    "decision_ids": ["AD-0001"],
                    "content_atoms": [{"atom_id": "CA-U002-001", "origin": "source", "source_atom_id": "SA-B001-003", "text": "阿宁：这是母亲留给我的。"}],
                    "content_bindings": {"narrative_task": ["CA-U002-001"], "action_start": ["CA-U002-001"], "action_end": ["CA-U002-001"]},
                    "fact_realizations": [],
                    "characters_on_screen": characters,
                    "scene_anchor_ref": {"artifact_key": "scene_anchor:L001", "version": 1},
                    "dialogue": [{"cue_id": "Q002", "lip_sync": True}],
                    "space_zones": [{"space_id": "courtyard-gate", "kind": "exterior"}],
                    "sound_events": [{"sound_id": "S002", "description": "场外叩门声", "source_type": "sfx", "space_id": "courtyard-gate", "scope": "unit"}],
                    "action_flow": {"enter_states": ["管家伸手拦路"], "steps": [{"step_id": "A002", "content_atom_refs": ["CA-U002-001"], "requires": ["管家伸手拦路"], "produces": ["阿宁藏好钥匙", "管家堵住院门"], "min_duration_seconds": 2}], "exit_states": ["阿宁藏好钥匙", "管家堵住院门"]},
                    "time_span_mode": "continuous",
                    "negative_constraints": ["不出现官差", "无字幕"],
                    "generation_strategy": "tail_frame_chain",
                    "continuation_from_unit_id": "SP-E001-U001",
                    "state_chain": {"chain_id": "CHAIN-E001-S01", "enter": state_b, "exit": state_b},
                },
            ],
        }

    def approve_shot_plan_with_review(
        self,
        plan_version: int,
        *,
        file_tag: str = "AI分镜",
    ) -> None:
        review_version = self.register_boundary_review(
            "ai_video_boundary_review:E001",
            "ai_shot_plan:E001",
            plan_version,
            {
                "finding_id": "BR-AI-E001-001",
                "category": "source_fidelity",
                "result": "passed",
                "location": "E001/U001-U002",
                "description": "分镜单元只拆分钥匙争夺动作与原对白。",
                "evidence": "人物选择、钥匙归属和场尾结果均保持 EV-0001。",
                "source_refs": ["EV-0001"],
            },
            "passed",
            file_tag=file_tag,
        )
        self.update_artifact_json(
            "ai_video_boundary_review:E001",
            lambda payload: payload["findings"].extend([
                {
                    "finding_id": "BR-AI-E001-002",
                    "category": "character_scene_consistency",
                    "result": "passed",
                    "location": "E001/U001-U002",
                    "description": "现场人物、角色锚点和状态链一致。",
                    "evidence": "C001/C002 均绑定同 ID 锚点且标记 on_screen。",
                    "source_refs": ["EV-0001"],
                },
                {
                    "finding_id": "BR-AI-E001-003",
                    "category": "production_feasibility",
                    "result": "passed",
                    "location": "E001/U001-U002",
                    "description": "对白、动作和镜头语言满足制作要求。",
                    "evidence": "两个单元均声明完整 shot_language 与 production_feasibility。",
                    "source_refs": ["EV-0001"],
                },
                {
                    "finding_id": "BR-AI-E001-004",
                    "category": "screen_text_postproduction",
                    "result": "passed",
                    "location": "E001/U001-U002",
                    "description": "本测试集不存在剧情必要屏幕文字。",
                    "evidence": "screen_text_post_plan_complete=true。",
                    "source_refs": ["EV-0001"],
                },
            ]),
        )
        self.approve_artifact("ai_video_boundary_review:E001", review_version)
        self.approve_artifact("ai_shot_plan:E001", plan_version)

    def test_render_storyboard_from_confirmed_shot_plan(self) -> None:
        import render_storyboard

        self.create_ready_project()
        self.register_ai_layer_prerequisites()
        plan = self.shot_plan_payload()
        plan["hard_blocks"] = ["不得展示钥匙对应的箱柜内部"]
        plan["units"][0]["prompt_text"] = (
            "动作起点：管家：把钥匙交出来。动作终点：管家：把钥匙交出来。"
            "现场人物：黑发少女，青布衫；灰袍老者。"
            "镜头运动：固定中景，阿宁与管家在院门两侧对峙。"
            "声音：院外蝉鸣。对白：管家：把钥匙交出来。"
            "禁止：不出现官差；无字幕。"
        )
        plan_version = self.register_artifact(
            "ai_shot_plan:E001",
            "10_AI视频执行包/E001_分镜计划V1.json",
            json.dumps(plan, ensure_ascii=False),
            self.shot_plan_dependencies(),
        )
        self.approve_shot_plan_with_review(plan_version)
        output = render_storyboard.render(self.project, "E001")
        self.assertTrue(output.is_file())
        page = output.read_text(encoding="utf-8")
        for expected in (
            "SP-E001-U001",
            "管家：把钥匙交出来。",
            "节奏时间轴",
            "不得展示钥匙对应的箱柜内部",
            "通用提示词",
            "character_anchor:C001",
            "景别：",
            "中景",
            "镜头运动：",
            "固定中景，阿宁与管家在院门两侧对峙。",
        ):
            self.assertIn(expected, page, expected)
        self.assertNotIn("。。", page)

    def prepare_episode_delivery_project(self) -> None:
        self.create_ready_project()
        self.register_ai_layer_prerequisites()
        plan_version = self.register_artifact(
            "ai_shot_plan:E001",
            "10_AI视频执行包/E001_分镜计划V1.json",
            json.dumps(self.shot_plan_payload(), ensure_ascii=False),
            self.shot_plan_dependencies(),
        )
        self.approve_shot_plan_with_review(plan_version)

    def run_production_preflight(self) -> dict:
        code, payload = self.run_cli(
            "startup-preflight",
            str(self.project),
            "--mode",
            "production",
            "--run-id",
            "TEST-PRODUCTION",
        )
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["status"], "execution_ready")
        return payload

    def test_render_commands_require_production_preflight(self) -> None:
        self.prepare_episode_delivery_project()

        for command in ("render-storyboard", "render-episode-delivery"):
            with self.subTest(command=command):
                code, payload = self.run_cli(command, str(self.project), "E001")
                self.assertEqual(code, 2, payload)
                self.assertEqual(payload["error"], "execution_preflight_required")

    def test_render_commands_reject_stale_production_preflight(self) -> None:
        self.prepare_episode_delivery_project()

        for command in ("render-storyboard", "render-episode-delivery"):
            with self.subTest(command=command):
                self.run_production_preflight()
                state = self.state()
                state["agent_runtime"]["execution_control"]["preflight"][
                    "fingerprint"
                ] = f"stale-test-fingerprint-{command}"
                (self.project / project_tool.STATE_FILENAME).write_text(
                    json.dumps(state, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                code, payload = self.run_cli(command, str(self.project), "E001")
                self.assertEqual(code, 2, payload)
                self.assertEqual(payload["error"], "execution_preflight_stale")

    def test_render_storyboard_checks_ai_source_contract_once(self) -> None:
        self.prepare_episode_delivery_project()
        self.run_production_preflight()
        original = project_tool.validate_ai_video_source_contract_ready
        with mock.patch.object(
            project_tool,
            "validate_ai_video_source_contract_ready",
            wraps=original,
        ) as contract_mock:
            code, payload = self.run_cli(
                "render-storyboard", str(self.project), "E001"
            )
        self.assertEqual(code, 0, payload)
        self.assertEqual(contract_mock.call_count, 1)

    def test_render_episode_delivery_checks_ai_source_contract_once(self) -> None:
        self.prepare_episode_delivery_project()
        self.run_production_preflight()
        original = project_tool.validate_ai_video_source_contract_ready
        with mock.patch.object(
            project_tool,
            "validate_ai_video_source_contract_ready",
            wraps=original,
        ) as contract_mock:
            code, payload = self.run_cli(
                "render-episode-delivery", str(self.project), "E001"
            )
        self.assertEqual(code, 0, payload)
        self.assertEqual(contract_mock.call_count, 1)

    def test_prompt_executability_rejects_generic_template(self) -> None:
        unit = {
            "prompt_text": "半写实都市国漫；阿宁藏好钥匙；无字幕。",
            "action_start": "1-1场上一状态完成",
            "action_end": "阿宁藏好钥匙",
            "characters_on_screen": [
                {"character_id": "C001", "appearance_lock": "黑发少女，青布衫"}
            ],
            "sound_events": [{"description": "院外蝉鸣"}],
            "shot_language": {
                "camera_movement": {"description": "从阿宁上半身推近至藏钥匙的手。"}
            },
            "space_zones": [{"space_id": "courtyard-gate", "description": "院门外"}],
            "negative_constraints": ["不出现官差", "无字幕"],
            "dialogue": [{"cue_id": "Q001", "lip_sync": True}],
        }
        cues = {"Q001": {"speaker_name": "管家", "text": "把钥匙交出来。"}}
        codes = {
            item["code"]
            for item in project_tool.validate_unit_prompt_executability(unit, cues, 1)
        }
        self.assertTrue(
            {
                "shotplan_prompt_placeholder_state",
                "shotplan_prompt_appearance_missing",
                "shotplan_prompt_sound_missing",
                "shotplan_prompt_dialogue_missing",
                "shotplan_prompt_camera_missing",
                "shotplan_prompt_environment_missing",
                "shotplan_prompt_negative_missing",
            }.issubset(codes)
        )

    def test_prompt_executability_accepts_complete_prompt(self) -> None:
        prompt = (
            "场景：院门外。现场人物：黑发少女，青布衫。"
            "动作起点：阿宁站在门槛外。动作终点：阿宁藏好钥匙。"
            "镜头运动：从阿宁上半身推近至藏钥匙的手。"
            "声音：院外蝉鸣。对白：管家说‘把钥匙交出来。’"
            "禁止：不出现官差；无字幕。"
        )
        unit = {
            "prompt_text": prompt,
            "action_start": "阿宁站在门槛外",
            "action_end": "阿宁藏好钥匙",
            "characters_on_screen": [
                {"character_id": "C001", "appearance_lock": "黑发少女，青布衫"}
            ],
            "sound_events": [{"description": "院外蝉鸣"}],
            "shot_language": {
                "camera_movement": {"description": "从阿宁上半身推近至藏钥匙的手。"}
            },
            "space_zones": [{"space_id": "courtyard-gate", "description": "院门外"}],
            "negative_constraints": ["不出现官差", "无字幕"],
            "dialogue": [{"cue_id": "Q001", "lip_sync": True}],
        }
        cues = {"Q001": {"speaker_name": "管家", "text": "把钥匙交出来。"}}
        self.assertEqual(
            project_tool.validate_unit_prompt_executability(unit, cues, 1), []
        )

    def test_prompt_executability_rejects_glued_sound_and_negative_segments(self) -> None:
        prompt = (
            "场景：院门外。现场人物：黑发少女，青布衫。"
            "动作起点：阿宁站在门槛外。动作终点：阿宁藏好钥匙。"
            "镜头运动：从阿宁上半身推近至藏钥匙的手。"
            "声音：院外蝉鸣负面：不出现官差；无字幕。"
        )
        unit = {
            "prompt_text": prompt,
            "action_start": "阿宁站在门槛外",
            "action_end": "阿宁藏好钥匙",
            "characters_on_screen": [
                {"character_id": "C001", "appearance_lock": "黑发少女，青布衫"}
            ],
            "sound_events": [{"description": "院外蝉鸣"}],
            "shot_language": {
                "camera_movement": {"description": "从阿宁上半身推近至藏钥匙的手。"}
            },
            "space_zones": [{"space_id": "courtyard-gate", "description": "院门外"}],
            "negative_constraints": ["不出现官差", "无字幕"],
            "dialogue": [],
        }
        codes = {
            item["code"]
            for item in project_tool.validate_unit_prompt_executability(unit, {}, 1)
        }
        self.assertIn("shotplan_prompt_sound_format_invalid", codes)

    def test_render_episode_delivery_outputs_exact_pair(self) -> None:
        self.prepare_episode_delivery_project()
        self.run_production_preflight()
        code, payload = self.run_cli(
            "render-episode-delivery", str(self.project), "E001"
        )
        self.assertEqual(code, 0, payload)
        output_dir = self.project / "09_定稿交付/分集交付/E001"
        self.assertEqual(
            sorted(path.name for path in output_dir.iterdir()),
            ["E001_剧本.docx", "E001_故事板.html"],
        )
        with zipfile.ZipFile(output_dir / "E001_剧本.docx") as archive:
            document_xml = archive.read("word/document.xml").decode("utf-8")
        self.assertIn("测试项目", document_xml)
        self.assertIn("人物三视图描述：", document_xml)
        self.assertIn("阿宁", document_xml)
        html_text = (output_dir / "E001_故事板.html").read_text(encoding="utf-8")
        self.assertIn("景别：", html_text)
        self.assertIn("镜头运动：", html_text)

    def test_render_episode_deliveries_batch_reports_failures(self) -> None:
        self.prepare_episode_delivery_project()
        self.run_production_preflight()
        code, payload = self.run_cli(
            "render-episode-deliveries",
            str(self.project),
            "E001",
            "E999",
        )
        self.assertEqual(code, 1, payload)
        self.assertEqual(payload["rendered_count"], 1)
        self.assertEqual(payload["failed_count"], 1)
        self.assertTrue(payload["results"][0]["ok"])
        self.assertFalse(payload["results"][1]["ok"])

    def test_episode_delivery_inputs_freeze_hashes_and_invalidate_fingerprint(
        self,
    ) -> None:
        self.prepare_episode_delivery_project()
        state = self.state()
        inputs, errors = project_tool.episode_delivery_inputs(
            self.project, state, "E001"
        )
        input_type = getattr(project_tool, "EpisodeDeliveryInputs", None)
        self.assertIsNotNone(input_type, "逐集交付输入必须使用冻结对象")
        self.assertIsInstance(inputs, input_type)
        self.assertEqual(errors, [])
        self.assertTrue(inputs.dependencies)
        for dependency in inputs.dependencies:
            self.assertEqual(
                set(dependency),
                {"artifact_key", "version", "path", "sha256"},
            )
            path = self.project / dependency["path"]
            self.assertTrue(path.is_file())
            self.assertEqual(dependency["sha256"], project_tool.sha256_file(path))
        original_fingerprint = inputs.input_fingerprint

        anchor_key = next(
            key for key in state["artifacts"] if key.startswith("character_anchor:")
        )
        anchor_record = project_tool.latest_record(state, anchor_key)
        anchor_path = self.project / anchor_record["path"]
        anchor_path.write_text(
            anchor_path.read_text(encoding="utf-8") + "\n",
            encoding="utf-8",
        )
        anchor_record["sha256"] = project_tool.sha256_file(anchor_path)
        anchor_record["size_bytes"] = anchor_path.stat().st_size
        (self.project / project_tool.STATE_FILENAME).write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        updated_inputs, updated_errors = project_tool.episode_delivery_inputs(
            self.project, self.state(), "E001"
        )
        self.assertEqual(updated_errors, [])
        self.assertNotEqual(
            updated_inputs.input_fingerprint,
            original_fingerprint,
        )

    def test_render_episode_delivery_registers_official_manifest(self) -> None:
        self.prepare_episode_delivery_project()
        self.run_production_preflight()
        code, payload = self.run_cli(
            "render-episode-delivery", str(self.project), "E001"
        )
        self.assertEqual(code, 0, payload)
        self.assertIs(payload.get("official_delivery"), True, payload)
        self.assertEqual(
            payload.get("generation_entrypoint"),
            "project_tool render-episode-delivery",
        )
        self.assertIsInstance(payload.get("input_fingerprint"), str)
        self.assertEqual(
            set(payload.get("outputs", {})),
            {"docx", "html"},
        )
        for output in payload["outputs"].values():
            self.assertTrue((self.project / output["path"]).is_file())
            self.assertEqual(
                output["sha256"],
                project_tool.sha256_file(self.project / output["path"]),
            )
        manifest_path = self.project / payload["manifest"]
        self.assertTrue(manifest_path.is_file())
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(
            manifest["generation_entrypoint"],
            "project_tool render-episode-delivery",
        )
        state = self.state()
        record = project_tool.latest_record(
            state, "episode_delivery_manifest:E001"
        )
        self.assertIsInstance(record, dict)
        self.assertEqual(record["status"], "confirmed")
        html_path = self.project / payload["outputs"]["html"]["path"]
        self.assertIn(
            'name="ai-director-render-contract"',
            html_path.read_text(encoding="utf-8"),
        )

        code, validated = self.run_cli(
            "validate-episode-delivery", str(self.project), "E001"
        )
        self.assertEqual(code, 0, validated)
        self.assertIs(validated.get("official_delivery"), True, validated)

    def test_direct_storyboard_render_cannot_become_official_delivery(self) -> None:
        import render_storyboard

        self.prepare_episode_delivery_project()
        self.run_production_preflight()
        state = self.state()
        inputs, errors = project_tool.episode_delivery_inputs(
            self.project, state, "E001"
        )
        self.assertEqual(errors, [])
        output = (
            self.project
            / "09_定稿交付"
            / "分集交付"
            / "E001"
            / "E001_故事板.html"
        )
        render_storyboard.render(
            self.project,
            "E001",
            output,
            state=state,
            preloaded=inputs.storyboard_payloads,
        )
        self.assertTrue(output.is_file())

        code, payload = self.run_cli(
            "validate-episode-delivery", str(self.project), "E001"
        )
        self.assertEqual(code, 2, payload)
        self.assertIs(payload.get("official_delivery"), False, payload)
        self.assertIn(
            "episode_delivery_manifest_missing",
            {item["code"] for item in payload.get("errors", [])},
        )

    def test_episode_delivery_reuses_and_rerenders_after_tamper_or_input_change(
        self,
    ) -> None:
        import render_episode_script
        import render_storyboard

        self.prepare_episode_delivery_project()
        self.run_production_preflight()
        docx_calls = 0
        storyboard_calls = 0
        original_docx = render_episode_script.write_docx
        original_storyboard = render_storyboard.render

        def counted_docx(*args, **kwargs):
            nonlocal docx_calls
            docx_calls += 1
            return original_docx(*args, **kwargs)

        def counted_storyboard(*args, **kwargs):
            nonlocal storyboard_calls
            storyboard_calls += 1
            return original_storyboard(*args, **kwargs)

        with mock.patch.object(
            render_episode_script, "write_docx", side_effect=counted_docx
        ), mock.patch.object(
            render_storyboard, "render", side_effect=counted_storyboard
        ):
            code, first = self.run_cli(
                "render-episode-delivery", str(self.project), "E001"
            )
            self.assertEqual(code, 0, first)
            self.assertFalse(first["reused"])
            code, repeated = self.run_cli(
                "render-episode-delivery", str(self.project), "E001"
            )
            self.assertEqual(code, 0, repeated)
            self.assertTrue(repeated["reused"])
            self.assertEqual(docx_calls, 1)
            self.assertEqual(storyboard_calls, 1)

            html_path = self.project / first["outputs"]["html"]["path"]
            html_path.write_text(
                html_path.read_text(encoding="utf-8") + "\n<!-- tampered -->\n",
                encoding="utf-8",
            )
            code, tampered = self.run_cli(
                "validate-episode-delivery", str(self.project), "E001"
            )
            self.assertEqual(code, 2, tampered)
            self.assertIn(
                "episode_delivery_output_hash_mismatch",
                {item["code"] for item in tampered["errors"]},
            )
            code, repaired = self.run_cli(
                "render-episode-delivery", str(self.project), "E001"
            )
            self.assertEqual(code, 0, repaired)
            self.assertFalse(repaired["reused"])
            self.assertEqual(docx_calls, 2)
            self.assertEqual(storyboard_calls, 2)

            state = self.state()
            anchor_key = next(
                key
                for key in state["artifacts"]
                if key.startswith("character_anchor:")
            )
            anchor_record = project_tool.latest_record(state, anchor_key)
            anchor_path = self.project / anchor_record["path"]
            anchor_path.write_text(
                anchor_path.read_text(encoding="utf-8") + "\n",
                encoding="utf-8",
            )
            anchor_record["sha256"] = project_tool.sha256_file(anchor_path)
            anchor_record["size_bytes"] = anchor_path.stat().st_size
            (self.project / project_tool.STATE_FILENAME).write_text(
                json.dumps(state, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            code, stale = self.run_cli(
                "validate-episode-delivery", str(self.project), "E001"
            )
            self.assertEqual(code, 2, stale)
            self.assertIn(
                "episode_delivery_input_stale",
                {item["code"] for item in stale["errors"]},
            )
            code, refreshed = self.run_cli(
                "render-episode-delivery", str(self.project), "E001"
            )
            self.assertEqual(code, 0, refreshed)
            self.assertFalse(refreshed["reused"])
            self.assertEqual(docx_calls, 3)
            self.assertEqual(storyboard_calls, 3)
            self.assertNotEqual(
                refreshed["input_fingerprint"],
                first["input_fingerprint"],
            )

    def test_validation_context_memoizes_shared_dependency_dag(self) -> None:
        self.create_ready_project()
        context_type = getattr(project_tool, "ValidationContext", None)
        self.assertIsNotNone(context_type, "缺少单次校验运行上下文")
        state = self.state()
        counts = Counter()
        original = project_tool.validate_dependency_shape

        def counted(key, dependencies):
            counts[key] += 1
            return original(key, dependencies)

        with mock.patch.object(
            project_tool, "validate_dependency_shape", side_effect=counted
        ):
            context = context_type()
            for key in ("quality_report", "production_readiness_report"):
                record = project_tool.latest_record(state, key)
                self.assertTrue(
                    project_tool.confirmed_record_is_usable(
                        state,
                        key,
                        record,
                        self.project,
                        context=context,
                    )
                )

        self.assertEqual(counts["project_spec"], 1)
        self.assertEqual(counts["episode_script:E001"], 1)
        self.assertEqual(counts["quality_report"], 1)

    def test_validation_context_invalidates_when_upstream_hash_changes(self) -> None:
        self.create_ready_project()
        context_type = getattr(project_tool, "ValidationContext", None)
        self.assertIsNotNone(context_type, "缺少单次校验运行上下文")
        state = self.state()
        parent_key = "quality_report"
        parent_record = project_tool.latest_record(state, parent_key)
        upstream_record = project_tool.latest_record(state, "project_spec")
        self.assertIsInstance(parent_record, dict)
        self.assertIsInstance(upstream_record, dict)
        path = self.project / upstream_record["path"]
        counts = Counter()
        original = project_tool.validate_dependency_shape

        def counted(key, dependencies):
            counts[key] += 1
            return original(key, dependencies)

        with mock.patch.object(
            project_tool, "validate_dependency_shape", side_effect=counted
        ):
            context = context_type()
            self.assertTrue(
                project_tool.confirmed_record_is_usable(
                    state,
                    parent_key,
                    parent_record,
                    self.project,
                    context=context,
                )
            )
            path.write_text(
                path.read_text(encoding="utf-8") + "\n",
                encoding="utf-8",
            )
            upstream_record["sha256"] = project_tool.sha256_file(path)
            upstream_record["size_bytes"] = path.stat().st_size
            self.assertTrue(
                project_tool.confirmed_record_is_usable(
                    state,
                    parent_key,
                    parent_record,
                    self.project,
                    context=context,
                )
            )

        self.assertEqual(counts[parent_key], 2)
        self.assertEqual(counts["project_spec"], 2)

    def test_validate_handoff_reuses_single_full_state_validation(self) -> None:
        self.create_ready_project()
        calls = 0
        original = project_tool.validate_state

        def counted(*args, **kwargs):
            nonlocal calls
            calls += 1
            return original(*args, **kwargs)

        with mock.patch.object(project_tool, "validate_state", side_effect=counted):
            result = project_tool.validate_handoff_state(
                self.project,
                expected_episodes=1,
            )

        self.assertTrue(result["ready"], result)
        self.assertEqual(calls, 1)

    def test_render_episode_delivery_reuses_preloaded_storyboard_inputs(self) -> None:
        self.prepare_episode_delivery_project()
        self.run_production_preflight()
        state = self.state()
        plan_record = project_tool.latest_record(state, "ai_shot_plan:E001")
        anchor_key = next(
            key for key in state["artifacts"] if key.startswith("character_anchor:")
        )
        anchor_record = project_tool.latest_record(state, anchor_key)
        watched = {
            (self.project / plan_record["path"]).resolve(): 0,
            (self.project / anchor_record["path"]).resolve(): 0,
        }
        original = Path.read_text

        def counted(path, *args, **kwargs):
            resolved = path.resolve()
            if resolved in watched:
                watched[resolved] += 1
            return original(path, *args, **kwargs)

        with mock.patch.object(Path, "read_text", new=counted):
            code, payload = self.run_cli(
                "render-episode-delivery", str(self.project), "E001"
            )

        self.assertEqual(code, 0, payload)
        self.assertEqual(set(watched.values()), {1})

    def test_storyboard_outputs_share_one_render_and_invalidate_on_new_plan(self) -> None:
        import render_storyboard

        self.create_ready_project()
        self.register_ai_layer_prerequisites()
        plan = self.shot_plan_payload()
        plan_version = self.register_artifact(
            "ai_shot_plan:E001",
            "10_AI视频执行包/E001_分镜计划V1.json",
            json.dumps(plan, ensure_ascii=False),
            self.shot_plan_dependencies(),
        )
        self.approve_shot_plan_with_review(plan_version)
        self.run_production_preflight()
        collect_calls = 0
        original = render_storyboard.collect_anchors

        def counted(*args, **kwargs):
            nonlocal collect_calls
            collect_calls += 1
            return original(*args, **kwargs)

        with mock.patch.object(
            render_storyboard, "collect_anchors", side_effect=counted
        ):
            code, first = self.run_cli(
                "render-storyboard", str(self.project), "E001"
            )
            self.assertEqual(code, 0, first)
            code, delivery = self.run_cli(
                "render-episode-delivery", str(self.project), "E001"
            )
            self.assertEqual(code, 0, delivery)
            execution_html = self.project / "10_AI视频执行包/E001_故事板.html"
            delivery_html = (
                self.project
                / "09_定稿交付/分集交付/E001/E001_故事板.html"
            )
            first_text = execution_html.read_text(encoding="utf-8")
            self.assertEqual(
                first_text,
                delivery_html.read_text(encoding="utf-8"),
            )
            self.assertEqual(collect_calls, 4)

            updated_plan = self.shot_plan_payload()
            updated_plan["hard_blocks"] = ["输入版本变化后必须重新渲染"]
            plan_version = self.register_artifact(
                "ai_shot_plan:E001",
                "10_AI视频执行包/E001_分镜计划V2.json",
                json.dumps(updated_plan, ensure_ascii=False),
                self.shot_plan_dependencies(),
            )
            self.approve_shot_plan_with_review(
                plan_version,
                file_tag="AI分镜V2",
            )
            code, updated = self.run_cli(
                "render-storyboard", str(self.project), "E001"
            )
            self.assertEqual(code, 0, updated)

        self.assertEqual(collect_calls, 8)
        self.assertNotEqual(
            first_text,
            execution_html.read_text(encoding="utf-8"),
        )

    def test_render_storyboard_resolves_scoped_dialogue_cue_sheet_dependency(self) -> None:
        import render_storyboard

        project = self.root / "scoped-storyboard"
        plan_path = project / "10_AI视频执行包/E001_分镜计划V1.json"
        cue_path = project / "08_连续性与质检/台词声音表_B01_V1.json"
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        cue_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "project_id": "P-SCOPED",
                    "episode_id": "E001",
                    "target_duration_seconds": 3,
                    "total_duration_seconds": 3,
                    "hard_blocks": ["不新增剧情"],
                    "asset_budget": {},
                    "units": [
                        {
                            "unit_id": "SP-E001-U001",
                            "sequence": 1,
                            "scene_id": "1-1",
                            "narrative_task": "管家索要钥匙",
                            "duration_seconds": 3,
                            "action_start": "管家伸手",
                            "action_end": "阿宁握紧钥匙",
                            "characters_on_screen": [],
                            "dialogue": [{"cue_id": "Q001", "lip_sync": True}],
                            "sound": [],
                            "negative_constraints": ["无字幕"],
                            "generation_strategy": "text_to_video",
                            "state_chain": {"chain_id": "CHAIN-1", "enter": {"characters": {}}, "exit": {"characters": {}}},
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        cue_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "project_id": "P-SCOPED",
                    "records": [
                        {
                            "cue_id": "Q001",
                            "speaker_name": "管家",
                            "text": "把钥匙交出来。",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (project / "project_state.json").write_text(
            json.dumps(
                {
                    "name": "作用域台词表测试",
                    "artifacts": {
                        "ai_shot_plan:E001": [
                            {
                                "version": 1,
                                "status": "confirmed",
                                "path": "10_AI视频执行包/E001_分镜计划V1.json",
                                "depends_on": [
                                    {"artifact_key": "dialogue_cue_sheet:B01", "version": 1}
                                ],
                            }
                        ],
                        "dialogue_cue_sheet:B01": [
                            {
                                "version": 1,
                                "status": "confirmed",
                                "path": "08_连续性与质检/台词声音表_B01_V1.json",
                                "depends_on": [],
                            }
                        ],
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        output = render_storyboard.render(project, "E001")
        page = output.read_text(encoding="utf-8")
        self.assertIn("<b>管家</b>:把钥匙交出来。", page)
        self.assertNotIn("<b>?</b>:Q001", page)


    def test_ai_execution_prompt_cannot_add_unbound_story_content(self) -> None:
        shot_units = {
            "SP-E001-U001": {
                "content_atoms": [{"atom_id": "CA001", "text": "温喻驾车离开。"}],
                "characters_on_screen": [{"character_id": "C001"}],
            }
        }
        task = {
            "source_unit_ids": ["SP-E001-U001"],
            "content_atom_refs": ["CA001"],
            "prompt": {
                "style_ref": "STYLE-1", "subject": [{"character_id": "C001"}],
                "action": "温喻抬起手机说让他来。", "camera": "固定中景",
                "environment": "使用绑定场景锚点", "negative": ["禁止新增剧情"],
            },
            "prompt_compiler_version": 1,
            "prompt_text": "伪造提示词",
        }
        errors = project_tool.validate_ai_execution_content_contract(task, shot_units, 1)
        self.assertIn("aiexec_prompt_content_unproven", {item["code"] for item in errors})

    def test_ai_shot_plan_gate_and_execution_plan_full_pass(self) -> None:
        self.create_ready_project()
        self.register_ai_layer_prerequisites()
        plan_version = self.register_artifact(
            "ai_shot_plan:E001",
            "10_AI视频执行包/E001_分镜计划V1.json",
            json.dumps(self.shot_plan_payload(), ensure_ascii=False),
            self.shot_plan_dependencies(),
        )
        code, payload = self.run_cli("approve", str(self.project), "ai_shot_plan:E001")
        self.assertEqual(code, 2, payload)
        self.assertIn("AI分镜内容边界报告", payload["error"])
        self.approve_shot_plan_with_review(plan_version)

        execution = {
            "schema_version": 1,
            "project_id": self.state()["project_id"],
            "episode_id": "E001",
            "generated_from": [
                {"artifact_key": "ai_shot_plan:E001", "version": plan_version},
                {"artifact_key": "model_capability_profile:seedance-2-0", "version": 1},
            ],
            "execution_policy": {"generate_images": False, "submit_video_requests": False},
            "reference_assets": [],
            "tasks": [
                {
                    "task_id": "VT-E001-T001",
                    "sequence": 1,
                    "source_unit_ids": ["SP-E001-U001", "SP-E001-U002"],
                    "content_atom_refs": ["CA-U001-001", "CA-U002-001"],
                    "duration_seconds": 7,
                    "generation_mode": "text_to_video",
                    "reference_asset_ids": [],
                    "clear_speakers": 1,
                    "prompt": {
                        "style_ref": "半写实国漫统一头",
                        "subject": [
                            {"character_id": "C001", "appearance_lock": "黑发少女，青布衫"},
                            {"character_id": "C002", "appearance_lock": "灰袍老者"},
                        ],
                        "action": "管家：把钥匙交出来。；阿宁：这是母亲留给我的。",
                        "camera": "固定中景切缓慢推进",
                        "environment": "使用绑定场景锚点",
                        "dialogue": [{"cue_id": "Q001"}, {"cue_id": "Q002"}],
                        "sound": ["蝉鸣", "叩门声"],
                        "negative": ["不出现官差", "无字幕"],
                    },
                    "prompt_compiler_version": 1,
                    "prompt_text": "",
                    "chain": {"chain_id": "CHAIN-E001-S01", "input_state": "STATE-S01-START", "output_state": "STATE-S01-END"},
                },
            ],
            "total_duration_seconds": 7,
        }
        execution["tasks"][0]["prompt_text"] = project_tool.compile_ai_execution_prompt_text(
            execution["tasks"][0]["prompt"]
        )
        self.register_and_approve(
            "ai_video_execution_plan:E001:seedance-2-0",
            "10_AI视频执行包/E001_执行计划V1.json",
            json.dumps(execution, ensure_ascii=False),
            (
                f"ai_shot_plan:E001@{plan_version}",
                "model_capability_profile:seedance-2-0@1",
            ),
        )

    def test_validate_ai_shot_plans_accepts_confirmed_plans(self) -> None:
        self.create_ready_project()
        self.register_ai_layer_prerequisites()
        plan_version = self.register_artifact(
            "ai_shot_plan:E001",
            "10_AI视频执行包/E001_分镜计划V1.json",
            json.dumps(self.shot_plan_payload(), ensure_ascii=False),
            self.shot_plan_dependencies(),
        )
        self.approve_shot_plan_with_review(plan_version)
        code, payload = self.run_cli(
            "validate-ai-shot-plans",
            str(self.project),
            "--expected-episodes",
            "1",
        )
        self.assertEqual(code, 0, payload)
        self.assertIs(payload["compatible"], True)
        self.assertEqual(len(payload["plans"]), 1)
        self.assertEqual(payload["plans"][0]["artifact_key"], "ai_shot_plan:E001")
        self.assertEqual(
            payload["plans"][0]["boundary_review"]["artifact_key"],
            "ai_video_boundary_review:E001",
        )

    def test_validate_ai_shot_plans_rejects_unconfirmed_plan(self) -> None:
        self.create_ready_project()
        self.register_ai_layer_prerequisites()
        self.register_artifact(
            "ai_shot_plan:E001",
            "10_AI视频执行包/E001_分镜计划V1.json",
            json.dumps(self.shot_plan_payload(), ensure_ascii=False),
            self.shot_plan_dependencies(),
        )
        code, payload = self.run_cli(
            "validate-ai-shot-plans",
            str(self.project),
            "--expected-episodes",
            "1",
        )
        self.assertEqual(code, 1, payload)
        self.assertIn(
            "ai_shot_plan_not_confirmed",
            {item["code"] for item in payload["errors"]},
        )

    def test_approve_artifacts_batch_continues_on_invalid_ref(self) -> None:
        self.create_ready_project()
        profile_version = self.register_artifact(
            "adaptation_profile",
            "02_改编定位/定位V2.md",
            "# 改编定位 v2\n",
            ("project_spec@1", "story_facts@1"),
        )
        bible_version = self.register_artifact(
            "adaptation_bible",
            "03_改编圣经/圣经V2.md",
            "# 改编圣经 v2\n",
            (f"adaptation_profile@{profile_version}",),
        )
        code, payload = self.run_cli(
            "approve-artifacts",
            str(self.project),
            f"adaptation_profile@{profile_version}",
            f"adaptation_bible@{bible_version}",
            "BAD_REF",
        )
        self.assertEqual(code, 1, payload)
        self.assertEqual(payload["approved_count"], 2)
        self.assertEqual(payload["failed_count"], 1)
        self.assertTrue(all(item["ok"] for item in payload["results"][:2]))
        self.assertFalse(payload["results"][2]["ok"])

    def test_ai_shot_plan_blocks_quality_violations(self) -> None:
        self.create_ready_project()
        self.register_ai_layer_prerequisites()
        plan = self.shot_plan_payload()
        plan["units"][0]["narrative_task"] = "E001-2-1：管家：把钥匙交出来。"
        plan["units"][0]["dialogue"] = [
            {"cue_id": "Q001", "lip_sync": True},
            {"cue_id": "Q002", "lip_sync": True},
        ]
        plan["units"][0]["characters_on_screen"] = [
            {"character_id": "C001", "presence": "on_screen", "anchor_ref": {"artifact_key": "character_anchor:C001", "version": 1}, "appearance_lock": "", "wardrobe": "青布衫"},
        ]
        plan["units"][1]["dialogue"] = []
        plan["units"][1]["duration_seconds"] = 6
        plan["units"][1]["state_chain"]["enter"] = {"characters": {"C001": {"position": "错误位置"}}}
        plan["units"][1]["scene_anchor_ref"] = {"artifact_key": "scene_anchor:L001", "version": 99}
        version = self.register_artifact(
            "ai_shot_plan:E001",
            "10_AI视频执行包/E001_坏分镜计划V1.json",
            json.dumps(plan, ensure_ascii=False),
            self.shot_plan_dependencies(),
        )
        code, payload = self.run_cli(
            "approve", str(self.project), "ai_shot_plan:E001", "--version", str(version)
        )
        self.assertEqual(code, 2, payload)
        for expected in (
            "shotplan_scene_action_mismatch",
            "shotplan_multi_lip_sync",
            "shotplan_appearance_lock_missing",
            "shotplan_over_4s_rationale_missing",
            "shotplan_state_chain_break",
            "shotplan_scene_anchor_invalid",
        ):
            self.assertIn(expected, payload["error"], expected)

    def test_action_scene_id_uses_episode_and_scene_prefix(self) -> None:
        self.assertEqual(
            project_tool.action_scene_id_from_field("E001-2-1：管家：把钥匙交出来。"),
            "1-2",
        )

    def test_ai_shot_plan_accepts_matching_action_scene_prefix(self) -> None:
        self.create_ready_project()
        self.register_ai_layer_prerequisites()
        plan = self.shot_plan_payload()
        plan["units"][0]["narrative_task"] = "E001-1-2：管家：把钥匙交出来。"
        self.register_artifact(
            "ai_shot_plan:E001",
            "10_AI视频执行包/E001_前缀正确分镜计划V1.json",
            json.dumps(plan, ensure_ascii=False),
            self.shot_plan_dependencies(),
        )
        state = self.state()
        record = project_tool.latest_record(state, "ai_shot_plan:E001")
        errors = project_tool.validate_ai_shot_plan_payload(
            self.project,
            state,
            "ai_shot_plan:E001",
            record,
            plan,
        )
        codes = {item["code"] for item in errors}
        self.assertNotIn("shotplan_scene_action_mismatch", codes)

    def test_ai_shot_plan_rejects_wrong_action_scene_prefix(self) -> None:
        self.create_ready_project()
        self.register_ai_layer_prerequisites()
        plan = self.shot_plan_payload()
        plan["units"][0]["narrative_task"] = "E001-2-1：管家：把钥匙交出来。"
        version = self.register_artifact(
            "ai_shot_plan:E001",
            "10_AI视频执行包/E001_前缀错误分镜计划V1.json",
            json.dumps(plan, ensure_ascii=False),
            self.shot_plan_dependencies(),
        )
        code, payload = self.run_cli(
            "approve", str(self.project), "ai_shot_plan:E001", "--version", str(version)
        )
        self.assertEqual(code, 2, payload)
        self.assertIn("shotplan_scene_action_mismatch", payload["error"])

    def test_ai_execution_plan_respects_model_profile(self) -> None:
        self.create_ready_project()
        self.register_ai_layer_prerequisites()
        plan_version = self.register_artifact(
            "ai_shot_plan:E001",
            "10_AI视频执行包/E001_分镜计划V1.json",
            json.dumps(self.shot_plan_payload(), ensure_ascii=False),
            self.shot_plan_dependencies(),
        )
        self.approve_shot_plan_with_review(plan_version)
        execution = {
            "schema_version": 1,
            "project_id": self.state()["project_id"],
            "episode_id": "E001",
            "generated_from": [
                {"artifact_key": "ai_shot_plan:E001", "version": plan_version},
                {"artifact_key": "model_capability_profile:seedance-2-0", "version": 1},
            ],
            "execution_policy": {"generate_images": False, "submit_video_requests": False},
            "reference_assets": [],
            "tasks": [
                {
                    "task_id": "VT-E001-T001",
                    "sequence": 1,
                    "source_unit_ids": ["SP-E001-U001", "SP-E001-U002"],
                    "duration_seconds": 3,
                    "generation_mode": "multimodal_reference",
                    "reference_asset_ids": [],
                    "clear_speakers": 2,
                    "prompt": {
                        "style_ref": "半写实国漫统一头",
                        "subject": [],
                        "action": "钥匙争夺",
                        "camera": "固定中景",
                        "environment": "院门",
                        "negative": ["无字幕"],
                    },
                    "prompt_text": "钥匙争夺。",
                    "chain": {"chain_id": "CHAIN-E001-S01", "input_state": "A", "output_state": "B"},
                },
            ],
            "total_duration_seconds": 3,
        }
        version = self.register_artifact(
            "ai_video_execution_plan:E001:seedance-2-0",
            "10_AI视频执行包/E001_坏执行计划V1.json",
            json.dumps(execution, ensure_ascii=False),
            (
                f"ai_shot_plan:E001@{plan_version}",
                "model_capability_profile:seedance-2-0@1",
            ),
        )
        code, payload = self.run_cli(
            "approve",
            str(self.project),
            "ai_video_execution_plan:E001:seedance-2-0",
            "--version",
            str(version),
        )
        self.assertEqual(code, 2, payload)
        for expected in (
            "aiexec_task_duration_invalid",
            "aiexec_generation_mode_invalid",
            "aiexec_clear_speakers_exceeded",
        ):
            self.assertIn(expected, payload["error"], expected)


    def register_spec_with_rights(self, rights_mode: str | None, file_tag: str) -> int:
        spec: dict = {
            "schema_version": 1,
            "project_id": self.state()["project_id"],
            "expected_episodes": 2,
        }
        if rights_mode is not None:
            spec["rights_mode"] = rights_mode
        return self.register_artifact(
            "project_spec",
            f"01_原著解析/项目规格_{file_tag}.json",
            json.dumps(spec, ensure_ascii=False),
        )

    def test_project_spec_rights_mode_invalid_value_rejects_approve(self) -> None:
        self.init_project()
        version = self.register_spec_with_rights("public_domain", "非法")
        code, payload = self.run_cli(
            "approve", str(self.project), "project_spec", "--version", str(version)
        )
        self.assertEqual(code, 2, payload)
        self.assertIn("rights_mode 非法", payload["error"])

    def test_handoff_rejects_non_string_rights_note(self) -> None:
        self.create_ready_project()
        state = self.state()
        record = state["artifacts"]["project_spec"][-1]
        path = self.project / record["path"]
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["rights_mode"] = "licensed"
        payload["rights_note"] = ["不是字符串"]
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        record["sha256"] = project_tool.sha256_file(path)
        record["size_bytes"] = path.stat().st_size
        (self.project / project_tool.STATE_FILENAME).write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        result = project_tool.validate_handoff_state(self.project, expected_episodes=1)

        self.assertFalse(result["ready"])
        self.assertIn(
            "project_spec_rights_note_invalid",
            {item["code"] for item in result["errors"]},
        )

    def test_project_spec_without_rights_mode_defaults_to_owned(self) -> None:
        self.init_project()
        version = self.register_spec_with_rights(None, "缺省")
        code, payload = self.run_cli(
            "approve", str(self.project), "project_spec", "--version", str(version)
        )
        self.assertEqual(code, 0, payload)
        self.assertNotIn("rights_notice", payload)
        code, payload = self.run_cli("show", str(self.project), "--summary")
        self.assertEqual(code, 0, payload)
        self.assertNotIn("rights_notice", payload)

    def test_rights_mode_unclear_notifies_once_without_blocking(self) -> None:
        self.init_project()
        version = self.register_spec_with_rights("unclear", "待确认")
        code, payload = self.run_cli(
            "approve", str(self.project), "project_spec", "--version", str(version)
        )
        self.assertEqual(code, 0, payload)  # unclear 不阻塞确认
        self.assertIn("rights_notice", payload)
        self.assertIn("rights_mode=unclear", payload["rights_notice"])
        # 只提示一次：确认时已提示，后续 show 不再重复
        code, payload = self.run_cli("show", str(self.project), "--summary")
        self.assertEqual(code, 0, payload)
        self.assertNotIn("rights_notice", payload)

    def test_rights_mode_unclear_show_notifies_once(self) -> None:
        self.init_project()
        self.register_spec_with_rights("unclear", "展示提示")
        code, payload = self.run_cli("show", str(self.project), "--summary")
        self.assertEqual(code, 0, payload)
        self.assertIn("rights_notice", payload)
        code, payload = self.run_cli("show", str(self.project), "--summary")
        self.assertEqual(code, 0, payload)
        self.assertNotIn("rights_notice", payload)

    # ------- 时长契约（项目规格 / 分镜计划绑定 / 剧本秒数预算） -------

    def register_spec_with_duration(self, duration_fields: dict, file_tag: str) -> int:
        spec: dict = {
            "schema_version": 1,
            "project_id": self.state()["project_id"],
            "expected_episodes": 2,
        }
        spec.update(duration_fields)
        return self.register_artifact(
            "project_spec",
            f"01_原著解析/项目规格_{file_tag}.json",
            json.dumps(spec, ensure_ascii=False),
        )

    def test_default_generation_policy_is_60_seconds_and_15_shots(self) -> None:
        self.init_project()
        result = project_tool.validate_state(self.project)
        self.assertEqual(
            result["generation_policy"],
            {
                "target_duration_seconds": 60,
                "duration_source": "default_60_seconds",
                "tolerance_ratio": 0.1,
                "recommended_shot_units": 15,
            },
        )

    def test_project_spec_accepts_valid_duration_contract(self) -> None:
        self.init_project()
        version = self.register_spec_with_duration(
            {
                "target_duration_seconds": 90,
                "duration_policy": {
                    "tolerance_ratio": 0.15,
                    "dialogue_chars_per_second": [3.5, 4.5],
                },
            },
            "合法时长",
        )
        code, payload = self.run_cli(
            "approve", str(self.project), "project_spec", "--version", str(version)
        )
        self.assertEqual(code, 0, payload)
        self.assertEqual(
            project_tool.project_target_duration_seconds(self.project, self.state()), 90
        )

    def test_project_spec_rejects_invalid_duration_fields(self) -> None:
        for index, (fields, expected) in enumerate((
            ({"target_duration_seconds": 0}, "target_duration_seconds"),
            ({"target_duration_seconds": "90秒"}, "target_duration_seconds"),
            ({"duration_policy": {"tolerance_ratio": 1.5}}, "tolerance_ratio"),
            ({"duration_policy": {"dialogue_chars_per_second": [4.5, 3.5]}}, "递增"),
            ({"duration_policy": {"inflation_redline_ratio": 0.25}}, "inflation_redline_ratio"),
            ({"duration_policy": "宽松"}, "duration_policy"),
        )):
            with self.subTest(fields=fields):
                if index:
                    self.tearDown()
                    self.setUp()
                self.init_project()
                version = self.register_spec_with_duration(fields, f"非法{index}")
                code, payload = self.run_cli(
                    "approve", str(self.project), "project_spec", "--version", str(version)
                )
                self.assertEqual(code, 2, payload)
                self.assertIn("时长契约非法", payload["error"])
                self.assertIn(expected, payload["error"])

    def register_spec_with_episode_count(self, expected_episodes: int, basis, file_tag: str) -> int:
        spec: dict = {
            "schema_version": 1,
            "project_id": self.state()["project_id"],
            "expected_episodes": expected_episodes,
        }
        if basis is not None:
            spec["episode_count_basis"] = basis
        return self.register_artifact(
            "project_spec",
            f"01_原著解析/项目规格_{file_tag}.json",
            json.dumps(spec, ensure_ascii=False),
        )

    def register_and_approve_content_index(self, spec_version: int = 1, expected_episodes: int = 1) -> None:
        """登记并确认原著语料与事件索引（依赖已确认项目规格）。"""
        project_id = self.state()["project_id"]
        normalized_source = self.write_project_file(
            "01_原著解析/标准化正文_第001章.txt",
            "测验员公布萧炎斗之力三段。\n萧薰儿测出九段。\n萧炎离开测验广场。\n",
        )
        source_corpus = {
            "schema_version": 1,
            "project_id": project_id,
            "generated_from": [{"artifact_key": "project_spec", "version": spec_version}],
            "source_units": [
                {
                    "source_unit_id": "SRC-CH001",
                    "source_id": self.state()["sources"][0]["source_id"],
                    "source_locator": "第1章",
                    "ordinal": 1,
                    "content_path": normalized_source.relative_to(self.project).as_posix(),
                    "content_sha256": project_tool.sha256_file(normalized_source),
                }
            ],
        }
        self.register_and_approve(
            "source_corpus",
            "01_原著解析/原著语料V1.json",
            json.dumps(source_corpus, ensure_ascii=False),
            (f"project_spec@{spec_version}",),
        )
        source_event_index = {
            "schema_version": 2,
            "content_contract_version": 1,
            "project_id": project_id,
            "generated_from": [{"artifact_key": "source_corpus", "version": 1}],
            "entities": [
                {"entity_id": "C001", "entity_type": "character", "canonical_name": "萧炎", "aliases": []},
                {"entity_id": "C002", "entity_type": "character", "canonical_name": "测验员", "aliases": []},
                {"entity_id": "C003", "entity_type": "character", "canonical_name": "萧薰儿", "aliases": []},
            ],
            "fact_definitions": [],
            "temporal_constraints": [],
            "units": [
                {
                    "source_unit_id": "SRC-CH001",
                    "source_locator": "第1章",
                    "granularity": "unit_detail",
                    "status": "ready",
                    "events": [
                        {
                            "event_id": "EV001",
                            "ordinal": 1,
                            "summary": "测验广场事件",
                            "participants": ["C001", "C002", "C003"],
                            "cause": "年度测验",
                            "action": "公布成绩",
                            "outcome": "萧炎离场",
                            "state_change": "萧炎被孤立",
                            "source_refs": ["SRC-CH001"],
                            "beats": [
                                {
                                    "beat_id": "B001",
                                    "ordinal": 1,
                                    "summary": "公布三段",
                                    "source_refs": ["SRC-CH001", "第1章"],
                                    "protected_fact_ids": [],
                                    "required_fact_ids": [],
                                    "content_atoms": [
                                        {
                                            "atom_id": "SA-B001-001",
                                            "kind": "action",
                                            "text": "测验员公布萧炎斗之力三段。",
                                            "source_unit_id": "SRC-CH001",
                                            "source_locator": "第1章",
                                            "source_excerpt": "测验员公布萧炎斗之力三段。",
                                        }
                                    ],
                                },
                                {
                                    "beat_id": "B002",
                                    "ordinal": 2,
                                    "summary": "萧薰儿九段",
                                    "source_refs": ["SRC-CH001", "第1章"],
                                    "protected_fact_ids": [],
                                    "required_fact_ids": [],
                                    "content_atoms": [
                                        {
                                            "atom_id": "SA-B002-001",
                                            "kind": "action",
                                            "text": "萧薰儿测出九段。",
                                            "source_unit_id": "SRC-CH001",
                                            "source_locator": "第1章",
                                            "source_excerpt": "萧薰儿测出九段。",
                                        }
                                    ],
                                },
                                {
                                    "beat_id": "B003",
                                    "ordinal": 3,
                                    "summary": "萧炎离开",
                                    "source_refs": ["SRC-CH001", "第1章"],
                                    "protected_fact_ids": [],
                                    "required_fact_ids": [],
                                    "content_atoms": [
                                        {
                                            "atom_id": "SA-B003-001",
                                            "kind": "action",
                                            "text": "萧炎离开测验广场。",
                                            "source_unit_id": "SRC-CH001",
                                            "source_locator": "第1章",
                                            "source_excerpt": "萧炎离开测验广场。",
                                        }
                                    ],
                                },
                            ],
                        }
                    ],
                }
            ],
            "episode_scopes": {
                f"E{number:03d}": {
                    "allowed_beat_ids": ["B001", "B002", "B003"],
                    "first_beat_id": "B001",
                    "last_beat_id": "B003",
                }
                for number in range(1, expected_episodes + 1)
            },
            "upgrade_pending": [],
        }
        self.register_and_approve(
            "source_event_index",
            "01_原著解析/事件索引V1.json",
            json.dumps(source_event_index, ensure_ascii=False),
            ("source_corpus@1",),
        )

    def test_estimate_episodes_requires_event_index(self) -> None:
        self.init_project()
        code, payload = self.run_cli(
            "estimate-episodes", str(self.project)
        )
        self.assertEqual(code, 2, payload)
        self.assertIn("尚未建立可统计的原著事件索引", payload["error"])

    def test_estimate_episodes_counts_beats_and_returns_range(self) -> None:
        self.init_project()
        basis = {
            "total_events": 1,
            "total_beats": 3,
            "counted_units": "beats",
            "primary_count": 3,
            "units_per_episode": {"min": 4, "max": 8},
            "estimated_min_episodes": 1,
            "estimated_max_episodes": 1,
            "selected_episodes": 1,
            "user_override": False,
        }
        spec_version = self.register_spec_with_episode_count(1, basis, "估算前")
        self.approve_artifact("project_spec", spec_version)
        self.register_and_approve_content_index(spec_version, expected_episodes=1)
        code, payload = self.run_cli(
            "estimate-episodes", str(self.project)
        )
        self.assertEqual(code, 0, payload)
        estimate = payload["estimate"]
        self.assertEqual(estimate["total_events"], 1)
        self.assertEqual(estimate["total_beats"], 3)
        self.assertEqual(estimate["counted_units"], "beats")
        self.assertEqual(estimate["primary_count"], 3)
        # 3 个戏剧单元，每集 4-8 个 → 建议 1 集；章节数量不参与判定
        self.assertEqual(estimate["estimated_min_episodes"], 1)
        self.assertEqual(estimate["estimated_max_episodes"], 1)
        self.assertEqual(estimate["recommended_episodes"], 1)
        self.assertNotIn("registered", estimate)

    def test_estimate_episodes_register_artifact(self) -> None:
        self.init_project()
        basis = {
            "total_events": 1,
            "total_beats": 3,
            "counted_units": "beats",
            "primary_count": 3,
            "units_per_episode": {"min": 4, "max": 8},
            "estimated_min_episodes": 1,
            "estimated_max_episodes": 1,
            "selected_episodes": 1,
            "user_override": False,
        }
        spec_version = self.register_spec_with_episode_count(1, basis, "登记前")
        self.approve_artifact("project_spec", spec_version)
        self.register_and_approve_content_index(spec_version, expected_episodes=1)
        code, payload = self.run_cli(
            "estimate-episodes", str(self.project), "--register"
        )
        self.assertEqual(code, 0, payload)
        estimate = payload["estimate"]
        self.assertTrue(estimate["registered"])
        records = self.state()["artifacts"]["episode_count_estimate"]
        self.assertEqual(records[-1]["status"], "awaiting_approval")
        self.assertTrue(
            (self.project / records[-1]["path"]).is_file()
        )

    def test_project_spec_approve_without_content_allows_legacy_flow(self) -> None:
        """尚未有原著语料/事件索引时，旧流程允许先确认规格（不阻塞）。"""
        self.init_project()
        version = self.register_spec_with_episode_count(2, None, "无内容")
        code, payload = self.run_cli(
            "approve", str(self.project), "project_spec", "--version", str(version)
        )
        self.assertEqual(code, 0, payload)

    def test_project_spec_approve_requires_episode_count_basis_when_content_exists(self) -> None:
        """已有原著事件索引却无事件量依据时，禁止按章节数确认集数。"""
        self.init_project()
        first = self.register_spec_with_episode_count(2, None, "初版")
        self.approve_artifact("project_spec", first)
        self.register_and_approve_content_index(first, expected_episodes=1)
        second = self.register_spec_with_episode_count(2, None, "缺依据")
        code, payload = self.run_cli(
            "approve", str(self.project), "project_spec", "--version", str(second)
        )
        self.assertEqual(code, 2, payload)
        self.assertIn("episode_count_basis", payload["error"])
        self.assertIn("事件量", payload["error"])

    def test_project_spec_approve_accepts_basis_within_estimate(self) -> None:
        self.init_project()
        basis = {
            "total_events": 1,
            "total_beats": 3,
            "counted_units": "beats",
            "primary_count": 3,
            "units_per_episode": {"min": 4, "max": 8},
            "estimated_min_episodes": 1,
            "estimated_max_episodes": 1,
            "selected_episodes": 1,
            "user_override": False,
            "note": "按事件量估算",
        }
        first = self.register_spec_with_episode_count(1, basis, "初版")
        self.approve_artifact("project_spec", first)
        self.register_and_approve_content_index(first, expected_episodes=1)
        second = self.register_spec_with_episode_count(1, basis, "有依据")
        code, payload = self.run_cli(
            "approve", str(self.project), "project_spec", "--version", str(second)
        )
        self.assertEqual(code, 0, payload)

    def test_project_spec_approve_rejects_episode_count_outside_estimate(self) -> None:
        self.init_project()
        basis = {
            "total_events": 1,
            "total_beats": 3,
            "counted_units": "beats",
            "primary_count": 3,
            "units_per_episode": {"min": 4, "max": 8},
            "estimated_min_episodes": 1,
            "estimated_max_episodes": 1,
            "selected_episodes": 2,
            "user_override": False,
        }
        first = self.register_spec_with_episode_count(1, basis, "初版")
        self.approve_artifact("project_spec", first)
        self.register_and_approve_content_index(first, expected_episodes=1)
        second = self.register_spec_with_episode_count(2, basis, "超区间")
        code, payload = self.run_cli(
            "approve", str(self.project), "project_spec", "--version", str(second)
        )
        self.assertEqual(code, 2, payload)
        self.assertIn("超出事件量估算区间", payload["error"])

    def test_project_spec_approve_accepts_user_override_with_confirmation(self) -> None:
        self.init_project()
        basis = {
            "total_events": 1,
            "total_beats": 3,
            "counted_units": "beats",
            "primary_count": 3,
            "units_per_episode": {"min": 4, "max": 8},
            "estimated_min_episodes": 1,
            "estimated_max_episodes": 1,
            "selected_episodes": 3,
            "user_override": True,
            "user_confirmation": "用户明确要求压缩为3集",
        }
        first = self.register_spec_with_episode_count(1, basis, "初版")
        self.approve_artifact("project_spec", first)
        self.register_and_approve_content_index(first, expected_episodes=1)
        second = self.register_spec_with_episode_count(3, basis, "用户覆盖")
        code, payload = self.run_cli(
            "approve", str(self.project), "project_spec", "--version", str(second)
        )
        self.assertEqual(code, 0, payload)

    def register_spec_with_ai_video_phase(self, phase, file_tag: str) -> int:
        spec: dict = {
            "schema_version": 1,
            "project_id": self.state()["project_id"],
            "expected_episodes": 1,
        }
        if phase is not None:
            spec["ai_video_phase"] = phase
        return self.register_artifact(
            "project_spec",
            f"01_原著解析/项目规格_{file_tag}.json",
            json.dumps(spec, ensure_ascii=False),
        )

    def register_model_capability_profile(self, file_tag: str) -> int:
        profile = {
            "schema_version": 1,
            "project_id": self.state()["project_id"],
            "generated_from": [{"artifact_key": "project_spec", "version": 1}],
            "model_family": "Seedance 2.0",
            "provider_model_id": "doubao-seedance-2-0-test",
            "capability_snapshot": {
                "status": "user_confirmed",
                "checked_at": "2026-08-06",
                "source_urls": ["https://example.invalid/seedance2_0"],
            },
            "capabilities": {
                "task_duration_seconds": {"min": 4, "max": 15},
                "ratios": ["16:9"],
                "resolutions": ["1080p"],
                "generate_audio": True,
                "lip_sync": True,
                "max_reference_images": 4,
                "supports_first_frame": True,
                "supports_first_last_frame": None,
                "supports_continuation": True,
                "max_clear_speakers": 1,
                "input_modes": ["text_to_video", "first_frame", "continuation"],
            },
        }
        return self.register_artifact(
            "model_capability_profile:seedance-2-0",
            f"10_AI视频执行包/模型能力档案_{file_tag}.json",
            json.dumps(profile, ensure_ascii=False),
            ("project_spec@1",),
        )

    def test_project_spec_rejects_invalid_ai_video_phase(self) -> None:
        self.init_project()
        version = self.register_spec_with_ai_video_phase("always", "非法")
        code, payload = self.run_cli(
            "approve", str(self.project), "project_spec", "--version", str(version)
        )
        self.assertEqual(code, 2, payload)
        self.assertIn("ai_video_phase 非法", payload["error"])

    def test_project_spec_accepts_valid_ai_video_phase(self) -> None:
        self.init_project()
        for phase in ("after_script_storyboard_confirm", "auto"):
            self.tearDown()
            self.setUp()
            self.init_project()
            version = self.register_spec_with_ai_video_phase(phase, phase)
            code, payload = self.run_cli(
                "approve", str(self.project), "project_spec", "--version", str(version)
            )
            self.assertEqual(code, 0, payload)
            self.assertEqual(
                project_tool.project_ai_video_phase(self.project, self.state()), phase
            )

    def test_default_ai_video_phase_is_after_script_storyboard_confirm(self) -> None:
        """未声明 ai_video_phase 时，默认先交付剧本＋故事板，执行层需用户确认。"""
        self.init_project()
        version = self.register_spec_with_ai_video_phase(None, "缺省")
        code, payload = self.run_cli(
            "approve", str(self.project), "project_spec", "--version", str(version)
        )
        self.assertEqual(code, 0, payload)
        self.assertEqual(
            project_tool.project_ai_video_phase(self.project, self.state()),
            "after_script_storyboard_confirm",
        )

    def test_ai_video_execution_plan_requires_continuation_confirmation_by_default(self) -> None:
        """默认两段式：未取得用户确认时，AI 视频执行层制品不能登记。"""
        self.init_project()
        spec_version = self.register_spec_with_ai_video_phase(None, "缺省")
        self.approve_artifact("project_spec", spec_version)
        code, payload = self.run_cli(
            "register-artifact",
            str(self.project),
            "model_capability_profile:seedance-2-0",
            str(
                self.write_project_file(
                    "10_AI视频执行包/模型能力档案_缺省.json",
                    "{}",
                )
            ),
            "--status",
            "awaiting_approval",
            "--depends-on",
            "project_spec@1",
        )
        self.assertEqual(code, 2, payload)
        self.assertIn("ai_video_phase_not_confirmed", payload["error"])
        self.assertNotIn("model_capability_profile", self.state()["artifacts"])

    def test_ai_video_execution_plan_allowed_with_auto_phase(self) -> None:
        """显式 ai_video_phase=auto 时，执行层制品可正常登记。"""
        self.init_project()
        spec_version = self.register_spec_with_ai_video_phase("auto", "auto")
        self.approve_artifact("project_spec", spec_version)
        version = self.register_model_capability_profile("auto")
        records = self.state()["artifacts"]["model_capability_profile:seedance-2-0"]
        self.assertEqual(records[-1]["version"], version)

    def test_ai_video_execution_plan_allowed_with_authorization(self) -> None:
        """默认两段式下，登记并确认 ai_video_continuation_authorization 后允许执行层制品。"""
        self.init_project()
        spec_version = self.register_spec_with_ai_video_phase(None, "缺省")
        self.approve_artifact("project_spec", spec_version)
        authorization = {
            "schema_version": 1,
            "project_id": self.state()["project_id"],
            "generated_from": [{"artifact_key": "project_spec", "version": spec_version}],
            "scope": "剧本＋故事板交付后用户确认继续 AI 视频执行层",
            "user_statement": "用户确认继续执行 AI 视频相关工作",
            "confirmed_at": "2026-08-06",
        }
        self.register_and_approve(
            "ai_video_continuation_authorization",
            "09_定稿交付/AI视频继续授权V1.json",
            json.dumps(authorization, ensure_ascii=False),
            (f"project_spec@{spec_version}",),
        )
        version = self.register_model_capability_profile("授权后")
        records = self.state()["artifacts"]["model_capability_profile:seedance-2-0"]
        self.assertEqual(records[-1]["version"], version)

    def test_script_storyboard_artifacts_not_gated_by_default(self) -> None:
        """剧本＋故事板路径制品（分镜计划、分镜边界、锚点、逐集交付）不受执行层门禁影响。"""
        self.init_project()
        spec_version = self.register_spec_with_ai_video_phase(None, "缺省")
        self.approve_artifact("project_spec", spec_version)
        for kind in (
            "ai_shot_plan",
            "ai_video_boundary_review",
            "character_anchor",
            "scene_anchor",
            "prop_anchor",
            "style_anchor",
            "episode_delivery_manifest",
        ):
            with self.subTest(kind=kind):
                # 不应触发执行层确认门禁
                project_tool.ensure_ai_video_execution_allowed(
                    self.project, self.state(), kind
                )

    def test_project_spec_without_duration_uses_default_generation_policy(self) -> None:
        """项目规格未声明时长时，统一使用 60 秒默认值。"""
        self.init_project()
        version = self.register_spec_with_duration({}, "无时长")
        code, payload = self.run_cli(
            "approve", str(self.project), "project_spec", "--version", str(version)
        )
        self.assertEqual(code, 0, payload)
        state = self.state()
        self.assertEqual(
            project_tool.project_target_duration_seconds(self.project, state), 60
        )
        self.assertEqual(
            project_tool.project_duration_source(self.project, state), "default_60_seconds"
        )

    def set_project_spec_duration(self, **duration_fields) -> None:
        """把时长字段写入已确认的项目规格文件并同步散列。"""
        state = self.state()
        record = state["artifacts"]["project_spec"][-1]
        path = self.project / record["path"]
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload.update(duration_fields)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        record["sha256"] = project_tool.sha256_file(path)
        record["size_bytes"] = path.stat().st_size
        (self.project / project_tool.STATE_FILENAME).write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )



    def test_source_content_atom_must_match_original_excerpt(self) -> None:
        self.project.mkdir(parents=True, exist_ok=True)
        corpus = {"source_units": [{"source_unit_id": "SRC-CH001", "content_path": "source.txt"}]}
        (self.project / "source.txt").write_text("温喻驾车离开。", encoding="utf-8")
        event_index = {"units": [{"events": [{"ordinal": 1, "beats": [{
            "beat_id": "B001", "ordinal": 1,
            "content_atoms": [{
                "atom_id": "SA001", "kind": "action", "text": "温喻打开导航。",
                "source_unit_id": "SRC-CH001", "source_locator": "第1章",
                "source_excerpt": "温喻驾车离开。",
            }],
        }]}]}]}
        errors = project_tool.validate_source_content_contract(self.project, corpus, event_index)
        self.assertIn("event_content_atom_text_mismatch", {item["code"] for item in errors})

    def test_source_fact_definition_must_cover_required_fact(self) -> None:
        event_index = {
            "fact_definitions": [],
            "units": [{"events": [{"ordinal": 1, "beats": [{
                "beat_id": "B001", "ordinal": 1, "required_fact_ids": ["F-AGE"]
            }]}]}],
        }
        errors = project_tool.validate_fact_definition_contract(event_index)
        self.assertIn("story_required_fact_missing", {item["code"] for item in errors})

    def test_content_contract_rejects_unbound_action_text(self) -> None:
        beats = {
            "B001": {
                "content_atoms": {
                    "SA001": {"atom_id": "SA001", "text": "温喻驾车离开。"}
                }
            }
        }
        unit = {
            "source_beat_refs": ["B001"],
            "narrative_task": "温喻打开导航。",
            "action_start": "温喻打开导航。",
            "action_end": "母亲发来聚餐消息。",
            "content_atoms": [
                {"atom_id": "CA001", "origin": "source", "source_atom_id": "SA001", "text": "温喻驾车离开。"}
            ],
            "content_bindings": {
                "narrative_task": ["CA001"],
                "action_start": ["CA001"],
                "action_end": ["CA001"],
            },
            "action_flow": {"steps": []},
        }
        errors = project_tool.validate_unit_content_contract(unit, beats, {}, 1, True)
        self.assertIn("shotplan_unproven_content", {item["code"] for item in errors})

    def test_required_fact_coverage_rejects_omitted_beat_fact(self) -> None:
        event_index = {
            "episode_scopes": {"E001": {"allowed_beat_ids": ["B001", "B002"]}},
            "fact_definitions": [
                {"fact_id": "F-AGE", "fact_type": "age", "source_beat_ids": ["B002"]}
            ],
            "units": [{"events": [{"ordinal": 1, "beats": [
                {"beat_id": "B001", "ordinal": 1, "required_fact_ids": []},
                {"beat_id": "B002", "ordinal": 2, "required_fact_ids": ["F-AGE"]},
            ]}]}],
        }
        plan = {"units": [{"source_beat_refs": ["B001"], "dialogue": [], "fact_realizations": []}]}
        errors = project_tool.validate_required_fact_coverage(event_index, plan, "E001")
        self.assertIn("shotplan_required_fact_coverage_missing", {item["code"] for item in errors})

    def test_required_fact_coverage_rejects_missing_carrier(self) -> None:
        event_index = {
            "episode_scopes": {"E001": {"allowed_beat_ids": ["B001"]}},
            "fact_definitions": [
                {"fact_id": "F-ID", "fact_type": "identity", "source_beat_ids": ["B001"]}
            ],
            "units": [{"events": [{"ordinal": 1, "beats": [
                {"beat_id": "B001", "ordinal": 1, "required_fact_ids": ["F-ID"]},
            ]}]}],
        }
        plan = {"units": [{
            "source_beat_refs": ["B001"],
            "dialogue": [],
            "fact_realizations": [{"fact_id": "F-ID", "carrier": "dialogue_cue", "carrier_id": "Q-NOT-EXISTS"}],
        }]}
        errors = project_tool.validate_required_fact_coverage(event_index, plan, "E001")
        codes = {item["code"] for item in errors}
        self.assertIn("shotplan_fact_carrier_missing", codes)
        self.assertIn("shotplan_required_fact_coverage_missing", codes)

    def test_source_timeline_rejects_wrong_relative_day_offset(self) -> None:
        event_index = {
            "units": [{"events": [{"ordinal": 1, "beats": [
                {"beat_id": "B001", "ordinal": 1, "story_time": {"day_index": 0, "day_part": "morning"}},
                {"beat_id": "B002", "ordinal": 2, "story_time": {"day_index": 1, "day_part": "afternoon"}},
            ]}]}],
            "temporal_constraints": [{
                "constraint_id": "TC001", "anchor_beat_id": "B001", "target_beat_id": "B002",
                "source_unit_id": "SRC-CH001", "expression_text": "后天下午",
            }],
        }
        errors = project_tool.validate_source_timeline_contract(
            event_index, {"SRC-CH001": "比赛安排在后天下午。"}
        )
        self.assertIn("event_temporal_offset_mismatch", {item["code"] for item in errors})

    def test_shot_plan_timeline_rejects_continuous_multi_day_unit(self) -> None:
        event_index = {"units": [{"events": [{"ordinal": 1, "beats": [
            {"beat_id": "B001", "ordinal": 1, "story_time": {"day_index": 0, "day_part": "night"}},
            {"beat_id": "B002", "ordinal": 2, "story_time": {"day_index": 4, "day_part": "afternoon"}},
        ]}]}], "temporal_constraints": []}
        plan = {"units": [{"source_beat_refs": ["B001", "B002"], "time_span_mode": "continuous"}]}
        errors = project_tool.validate_shot_plan_timeline_contract(event_index, plan, {})
        self.assertIn("shotplan_continuous_time_jump", {item["code"] for item in errors})

    def test_generic_semantic_guards_block_invalid_storyboard(self) -> None:
        event_index = {
            "schema_version": 2,
            "episode_scopes": {"E001": {"allowed_beat_ids": ["B001", "B002", "B003"], "first_beat_id": "B001", "last_beat_id": "B003"}},
            "units": [{
                "events": [
                    {"ordinal": 1, "beats": [
                        {"beat_id": "B001", "ordinal": 1, "protected_fact_ids": ["F001"]},
                        {"beat_id": "B002", "ordinal": 2, "protected_fact_ids": []},
                    ]},
                    {"ordinal": 2, "beats": [
                        {"beat_id": "B003", "ordinal": 1, "protected_fact_ids": []}
                    ]},
                ]
            }],
        }
        story_facts = {"facts": [{"fact_id": "F001"}]}
        plan = {"units": [
            {"source_beat_refs": ["B002"], "preserved_fact_ids": [], "new_fact_claims": []},
            {"source_beat_refs": ["B001"], "preserved_fact_ids": [], "new_fact_claims": ["新增关系"], "decision_ids": []},
        ]}
        source_errors = project_tool.validate_shot_plan_source_contract(
            event_index, story_facts, plan, "E001"
        )
        cues = {
            "Q001": {
                "cue_id": "Q001", "speaker_id": "CHAR-B", "delivery_mode": "screen_video",
                "text": "必须保留的关键句",
            }
        }
        unit = {
            "duration_seconds": 1,
            "characters_on_screen": [{"character_id": "CHAR-B"}],
            "screen_video_characters": [],
            "dialogue": [{"cue_id": "Q001"}],
            "state_chain": {"enter": {"characters": {"CHAR-B": {"position": "尚未到场"}}}},
            "action_flow": {
                "enter_states": ["state-a"],
                "steps": [{
                    "step_id": "A1", "requires": ["missing-state"],
                    "produces": ["state-b"], "min_duration_seconds": 2,
                }],
                "exit_states": ["state-b"],
            },
            "time_span_mode": "continuous",
            "screen_text": {
                "required_text": "必须准确显示的文字",
                "render_mode": "video_model",
            },
        }
        character_errors = project_tool.validate_unit_character_modes(unit, cues, 1)
        feasibility_errors = project_tool.validate_unit_feasibility(unit, cues, (3.5, 4.5), 1)
        codes = {item["code"] for item in source_errors + character_errors + feasibility_errors}
        self.assertTrue({
            "shotplan_source_order_violation",
            "shotplan_protected_fact_missing",
            "shotplan_unauthorized_fact_added",
            "shotplan_nonvisual_character_on_screen",
            "shotplan_character_presence_conflict",
            "shotplan_dialogue_capacity_exceeded",
            "shotplan_action_precondition_missing",
            "shotplan_action_capacity_exceeded",
            "shotplan_screen_text_overlay_missing",
        }.issubset(codes), codes)
        self.assertEqual(
            project_tool.computed_boundary_conclusion(source_errors + character_errors + feasibility_errors, []),
            "blocked",
        )

    def dialogue_source_contract_fixture(self) -> tuple[dict, dict, dict]:
        self.create_ready_project()
        state = self.state()
        corpus_record = state["artifacts"]["source_corpus"][-1]
        corpus_path = self.project / corpus_record["path"]
        corpus_payload = json.loads(corpus_path.read_text(encoding="utf-8"))
        source_unit = corpus_payload["source_units"][0]
        source_path = self.project / source_unit["content_path"]
        source_path.write_text(
            "管家：把钥匙交出来。\n阿宁：这是母亲留给我的。\n",
            encoding="utf-8",
        )
        source_unit["content_sha256"] = project_tool.sha256_file(source_path)
        corpus_path.write_text(
            json.dumps(corpus_payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        corpus_record["sha256"] = project_tool.sha256_file(corpus_path)
        corpus_record["size_bytes"] = corpus_path.stat().st_size
        (self.project / project_tool.STATE_FILENAME).write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        event_record = state["artifacts"]["source_event_index"][-1]
        event_path = self.project / event_record["path"]
        event_payload = json.loads(event_path.read_text(encoding="utf-8"))
        event_payload["schema_version"] = 2
        event_payload["episode_scopes"] = {
            "E001": {
                "allowed_beat_ids": ["B001"],
                "first_beat_id": "B001",
                "last_beat_id": "B001",
            }
        }
        event = event_payload["units"][0]["events"][0]
        event["ordinal"] = 1
        event["beats"] = [
            {
                "beat_id": "B001",
                "ordinal": 1,
                "source_refs": ["第1章"],
                "protected_fact_ids": [],
            },
            {
                "beat_id": "B002",
                "ordinal": 2,
                "source_refs": ["第2章"],
                "protected_fact_ids": [],
            },
        ]
        event_path.write_text(
            json.dumps(event_payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        event_record["sha256"] = project_tool.sha256_file(event_path)
        event_record["size_bytes"] = event_path.stat().st_size
        (self.project / project_tool.STATE_FILENAME).write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        generated_from = [
            {"artifact_key": "source_corpus", "version": 1},
            {"artifact_key": "source_event_index", "version": 1},
            {"artifact_key": "episode_script:E001", "version": 1},
            {"artifact_key": "episode_boundary_review:E001", "version": 1},
        ]
        record = {
            "artifact_type": "dialogue_cue_sheet",
            "depends_on": generated_from,
        }
        payload = {
            "schema_version": 1,
            "contract_version": 2,
            "project_id": state["project_id"],
            "generated_from": generated_from,
            "records": [
                {
                    "cue_id": "Q001",
                    "episode_id": "E001",
                    "scene_id": "1-1",
                    "speaker_id": "C002",
                    "speaker_name": "管家",
                    "type": "dialogue",
                    "delivery_mode": "on_screen",
                    "text": "把钥匙交出来。",
                    "source_unit_id": "SRC-CH001",
                    "source_locator": "第1章",
                    "source_beat_refs": ["B001"],
                }
            ],
        }
        return state, record, payload

    def test_dialogue_rewrite_operation_and_boundary_category_are_removed(self) -> None:
        self.assertNotIn(
            "dialogue_rewrite", project_tool.ALLOWED_ADAPTATION_OPERATIONS
        )
        self.assertNotIn(
            "dialogue_rewrite", project_tool.AUTO_ALLOWED_BOUNDARY_CATEGORIES
        )

    def test_dialogue_cue_sheet_accepts_exact_source_without_rewrite_metadata(self) -> None:
        state, record, payload = self.dialogue_source_contract_fixture()
        errors = project_tool.validate_dialogue_cue_sheet_payload(
            self.project, state, "dialogue_cue_sheet", record, payload
        )
        self.assertEqual(errors, [])




    def test_dialogue_cue_sheet_rejects_final_voice_placeholder(self) -> None:
        state, record, payload = self.dialogue_source_contract_fixture()
        corpus_record = state["artifacts"]["source_corpus"][-1]
        corpus_payload = json.loads((self.project / corpus_record["path"]).read_text(encoding="utf-8"))
        source_path = self.project / corpus_payload["source_units"][0]["content_path"]
        source_path.write_text(source_path.read_text(encoding="utf-8") + "20XX年六月十七日。\n", encoding="utf-8")
        payload["records"][0]["text"] = "20XX年六月十七日。"
        errors = project_tool.validate_dialogue_cue_sheet_payload(
            self.project, state, "dialogue_cue_sheet:E001", record, payload
        )
        self.assertIn(
            "dialogue_placeholder_forbidden", {item["code"] for item in errors}
        )

    def test_dialogue_cue_sheet_rejects_unknown_canonical_speaker(self) -> None:
        state, record, payload = self.dialogue_source_contract_fixture()
        payload["records"][0]["speaker_id"] = "C999"
        errors = project_tool.validate_dialogue_cue_sheet_payload(
            self.project, state, "dialogue_cue_sheet:E001", record, payload
        )
        self.assertIn(
            "dialogue_speaker_unknown", {item["code"] for item in errors}
        )

    def test_shot_plan_rejects_unknown_canonical_character(self) -> None:
        unit = {
            "characters_on_screen": [{"character_id": "C999"}],
            "screen_video_characters": [],
            "dialogue": [],
            "state_chain": {"enter": {"characters": {"C999": {"position": "门外"}}}},
        }
        errors = project_tool.validate_unit_character_registry(unit, {"C001", "C002"}, 1)
        self.assertIn(
            "shotplan_character_unknown", {item["code"] for item in errors}
        )

    def test_dialogue_cue_sheet_rejects_source_beat_outside_episode_scope(self) -> None:
        state, record, payload = self.dialogue_source_contract_fixture()
        payload["records"][0]["source_beat_refs"] = ["B002"]
        payload["records"][0]["source_locator"] = "第2章"
        errors = project_tool.validate_dialogue_cue_sheet_payload(
            self.project, state, "dialogue_cue_sheet:E001", record, payload
        )
        self.assertIn(
            "dialogue_source_boundary_exceeded", {item["code"] for item in errors}
        )

    def test_dialogue_cue_sheet_rejects_fake_source_locator(self) -> None:
        state, record, payload = self.dialogue_source_contract_fixture()
        payload["records"][0]["source_locator"] = "第99章"
        errors = project_tool.validate_dialogue_cue_sheet_payload(
            self.project, state, "dialogue_cue_sheet:E001", record, payload
        )
        self.assertIn(
            "dialogue_source_locator_mismatch", {item["code"] for item in errors}
        )

    def test_dialogue_cue_sheet_rejects_rewritten_text(self) -> None:
        state, record, payload = self.dialogue_source_contract_fixture()
        payload["records"][0]["text"] = "把钥匙交给我。"
        errors = project_tool.validate_dialogue_cue_sheet_payload(
            self.project, state, "dialogue_cue_sheet", record, payload
        )
        self.assertIn(
            "dialogue_not_exact_source", {item["code"] for item in errors}
        )

    def test_dialogue_cue_sheet_rejects_legacy_rewrite_fields(self) -> None:
        state, record, payload = self.dialogue_source_contract_fixture()
        payload["records"][0].update(
            {
                "source_text": "把钥匙交出来。",
                "preservation_mode": "exact",
                "adaptation_note": "保持人物语气",
                "new_fact_claims": [],
            }
        )
        errors = project_tool.validate_dialogue_cue_sheet_payload(
            self.project, state, "dialogue_cue_sheet", record, payload
        )
        self.assertIn(
            "dialogue_generated_metadata_forbidden",
            {item["code"] for item in errors},
        )

    def test_ai_video_review_cannot_pass_without_semantic_coverage(self) -> None:
        self.create_ready_project()
        self.register_ai_layer_prerequisites()
        plan = self.shot_plan_payload()
        plan_version = self.register_artifact(
            "ai_shot_plan:E001",
            "10_AI视频执行包/E001_语义覆盖测试V1.json",
            json.dumps(plan, ensure_ascii=False),
            self.shot_plan_dependencies(),
        )
        review_version = self.register_boundary_review(
            "ai_video_boundary_review:E001",
            "ai_shot_plan:E001",
            plan_version,
            {
                "finding_id": "BR-AI-E001-001",
                "category": "source_fidelity",
                "result": "passed",
                "location": "E001",
                "description": "仅检查来源忠实度。",
                "evidence": "EV-0001",
                "source_refs": ["EV-0001"],
            },
            "passed",
        )
        code, payload = self.run_cli(
            "approve", str(self.project), "ai_video_boundary_review:E001",
            "--version", str(review_version),
        )
        self.assertEqual(code, 2, payload)
        self.assertIn("boundary_semantic_coverage_missing", payload["error"])



    def test_first_unit_tail_frame_chain_requires_previous_episode_tail(self) -> None:
        units = [
            {
                "unit_id": "SP-E002-U001",
                "sequence": 1,
                "generation_strategy": "tail_frame_chain",
            }
        ]
        errors = project_tool.validate_tail_frame_contract(units, {}, "E002")
        self.assertIn(
            "shotplan_cross_episode_tail_missing", {item["code"] for item in errors}
        )

    def test_same_episode_tail_frame_chain_requires_previous_unit_binding(self) -> None:
        units = [
            {"unit_id": "SP-E001-U001", "sequence": 1, "generation_strategy": "text_to_video"},
            {"unit_id": "SP-E001-U002", "sequence": 2, "generation_strategy": "tail_frame_chain"},
        ]
        errors = project_tool.validate_tail_frame_contract(units, {}, "E001")
        self.assertIn(
            "shotplan_tail_previous_unit_missing", {item["code"] for item in errors}
        )

    def test_shot_plan_requires_explicit_character_space_partition(self) -> None:
        unit = {
            "space_zones": [
                {"space_id": "car-a", "kind": "vehicle"},
                {"space_id": "car-b", "kind": "vehicle"},
            ],
            "characters_on_screen": [
                {"character_id": "C001", "space_id": "car-a"},
                {"character_id": "C002"},
            ],
            "sound_events": [],
        }
        errors = project_tool.validate_unit_spatial_audio_contract(unit, {}, 1, True)
        self.assertIn(
            "shotplan_character_space_missing", {item["code"] for item in errors}
        )

    def test_phone_video_audio_must_be_scoped_to_current_unit(self) -> None:
        unit = {
            "space_zones": [{"space_id": "living-room", "kind": "room"}],
            "characters_on_screen": [],
            "sound_events": [
                {
                    "sound_id": "S001",
                    "description": "手机视频里的说话声",
                    "source_type": "device",
                    "space_id": "living-room",
                    "device_id": "phone-1",
                    "scope": "scene",
                }
            ],
            "dialogue": [{"cue_id": "Q001", "audio_event_id": "S001"}],
        }
        cues = {"Q001": {"delivery_mode": "phone_video"}}
        errors = project_tool.validate_unit_spatial_audio_contract(unit, cues, 1, True)
        self.assertIn(
            "shotplan_device_audio_scope_invalid", {item["code"] for item in errors}
        )

    def test_shot_plan_requires_executable_shot_contract(self) -> None:
        unit = {
            "duration_seconds": 2,
            "dialogue": [],
            "action_flow": {
                "enter_states": ["车内"],
                "steps": [{
                    "step_id": "A1",
                    "requires": ["车内"],
                    "produces": ["已下车"],
                    "min_duration_seconds": 3,
                }],
                "exit_states": ["已下车"],
            },
            "time_span_mode": "continuous",
        }
        errors = project_tool.validate_unit_feasibility(unit, {}, (3.5, 4.5), 1)
        self.assertIn(
            "shotplan_action_capacity_exceeded", {item["code"] for item in errors}
        )

    def test_shot_plan_rejects_nonvisual_character_in_on_screen_list(self) -> None:
        unit = {
            "characters_on_screen": [{"character_id": "C001"}],
            "screen_video_characters": [],
            "dialogue": [{"cue_id": "Q001"}],
            "state_chain": {"enter": {"characters": {}}},
        }
        cues = {
            "Q001": {
                "cue_id": "Q001",
                "speaker_id": "C001",
                "delivery_mode": "phone_audio",
            }
        }
        errors = project_tool.validate_unit_character_modes(unit, cues, 1)
        self.assertIn(
            "shotplan_nonvisual_character_on_screen", {item["code"] for item in errors}
        )

    def test_shot_plan_blocks_failed_source_fidelity_guard(self) -> None:
        event_index = {
            "schema_version": 2,
            "episode_scopes": {"E001": {"allowed_beat_ids": ["B001", "B002"], "first_beat_id": "B001", "last_beat_id": "B002"}},
            "units": [{
                "events": [{
                    "ordinal": 1,
                    "beats": [
                        {"beat_id": "B001", "ordinal": 1, "protected_fact_ids": []},
                        {"beat_id": "B002", "ordinal": 2, "protected_fact_ids": []},
                    ],
                }],
            }],
        }
        plan = {
            "schema_version": 2,
            "units": [
                {"source_beat_refs": ["B002"], "preserved_fact_ids": [], "new_fact_claims": []},
                {"source_beat_refs": ["B001"], "preserved_fact_ids": [], "new_fact_claims": []},
            ],
        }
        errors = project_tool.validate_shot_plan_source_contract(
            event_index, {"facts": []}, plan, "E001"
        )
        self.assertIn(
            "shotplan_source_order_violation", {item["code"] for item in errors}
        )


    def test_shot_plan_rejects_beat_not_explicitly_allowed_for_episode(self) -> None:
        event_index = {
            "schema_version": 2,
            "episode_scopes": {
                "E001": {
                    "allowed_beat_ids": ["B001", "B003"],
                    "first_beat_id": "B001",
                    "last_beat_id": "B003",
                }
            },
            "units": [{
                "events": [{
                    "ordinal": 1,
                    "beats": [
                        {"beat_id": "B001", "ordinal": 1, "source_refs": ["第1章"], "protected_fact_ids": []},
                        {"beat_id": "B002", "ordinal": 2, "source_refs": ["第1章"], "protected_fact_ids": []},
                        {"beat_id": "B003", "ordinal": 3, "source_refs": ["第1章"], "protected_fact_ids": []},
                    ],
                }],
            }],
        }
        plan = {
            "schema_version": 2,
            "units": [
                {"source_beat_refs": ["B002"], "preserved_fact_ids": [], "new_fact_claims": []},
            ],
        }
        errors = project_tool.validate_shot_plan_source_contract(
            event_index, {"facts": []}, plan, "E001"
        )
        self.assertIn(
            "shotplan_source_boundary_exceeded", {item["code"] for item in errors}
        )

    def test_dialogue_cue_sheet_rejects_source_order_regression(self) -> None:
        state, record, payload = self.dialogue_source_contract_fixture()
        event_record = state["artifacts"]["source_event_index"][-1]
        event_path = self.project / event_record["path"]
        event_payload = json.loads(event_path.read_text(encoding="utf-8"))
        event_payload["episode_scopes"]["E001"]["allowed_beat_ids"] = ["B001", "B002"]
        event_payload["episode_scopes"]["E001"]["last_beat_id"] = "B002"
        event_path.write_text(json.dumps(event_payload, ensure_ascii=False), encoding="utf-8")
        event_record["sha256"] = project_tool.sha256_file(event_path)
        event_record["size_bytes"] = event_path.stat().st_size
        payload["records"] = [
            {**payload["records"][0], "cue_id": "Q002", "source_beat_refs": ["B002"], "source_locator": "第2章"},
            {**payload["records"][0], "cue_id": "Q001", "source_beat_refs": ["B001"], "source_locator": "第1章"},
        ]
        errors = project_tool.validate_dialogue_cue_sheet_payload(
            self.project, state, "dialogue_cue_sheet:E001", record, payload
        )
        self.assertIn(
            "dialogue_source_order_violation", {item["code"] for item in errors}
        )

    def test_shot_plan_must_declare_duration_when_spec_declares_it(self) -> None:
        """核心回归：省略 target_duration_seconds 曾可整段跳过时长校验。"""
        self.create_ready_project()
        self.register_ai_layer_prerequisites()
        self.set_project_spec_duration(target_duration_seconds=90)
        plan = self.shot_plan_payload()
        plan.pop("target_duration_seconds", None)
        version = self.register_artifact(
            "ai_shot_plan:E001",
            "10_AI视频执行包/E001_缺时长分镜计划V1.json",
            json.dumps(plan, ensure_ascii=False),
            self.shot_plan_dependencies(),
        )
        code, payload = self.run_cli(
            "approve", str(self.project), "ai_shot_plan:E001", "--version", str(version)
        )
        self.assertEqual(code, 2, payload)
        self.assertIn("shotplan_target_duration_missing", payload["error"])

    def test_shot_plan_duration_must_match_project_spec(self) -> None:
        self.create_ready_project()
        self.register_ai_layer_prerequisites()
        self.set_project_spec_duration(target_duration_seconds=90)
        plan = self.shot_plan_payload()
        plan["target_duration_seconds"] = 30
        plan["duration_deviation_note"] = "自报值与项目规格不一致，偏差说明不能替代绑定"
        version = self.register_artifact(
            "ai_shot_plan:E001",
            "10_AI视频执行包/E001_错时长分镜计划V1.json",
            json.dumps(plan, ensure_ascii=False),
            self.shot_plan_dependencies(),
        )
        code, payload = self.run_cli(
            "approve", str(self.project), "ai_shot_plan:E001", "--version", str(version)
        )
        self.assertEqual(code, 2, payload)
        self.assertIn("shotplan_target_duration_mismatch", payload["error"])

    def test_shot_plan_without_spec_duration_uses_default_60_seconds(self) -> None:
        """项目规格未声明时长时，分镜仍必须绑定默认 60 秒目标。"""
        self.create_ready_project()
        self.register_ai_layer_prerequisites()
        plan = self.shot_plan_payload()
        plan["target_duration_seconds"] = 30
        version = self.register_artifact(
            "ai_shot_plan:E001",
            "10_AI视频执行包/E001_默认时长分镜计划V1.json",
            json.dumps(plan, ensure_ascii=False),
            self.shot_plan_dependencies(),
        )
        code, payload = self.run_cli(
            "approve", str(self.project), "ai_shot_plan:E001", "--version", str(version)
        )
        self.assertEqual(code, 2, payload)
        self.assertIn("shotplan_target_duration_mismatch", payload["error"])

    def test_custom_tolerance_ratio_tightens_duration_deviation(self) -> None:
        self.create_ready_project()
        self.register_ai_layer_prerequisites()
        plan = self.shot_plan_payload()
        total = sum(unit["duration_seconds"] for unit in plan["units"])
        # 取一个偏差约 12% 的目标：默认 10% 会拦截，显式 5% 同样应拦截。
        target = max(1, round(total / 0.88))
        self.set_project_spec_duration(
            target_duration_seconds=target,
            duration_policy={"tolerance_ratio": 0.05},
        )
        plan["target_duration_seconds"] = target
        plan.pop("duration_deviation_note", None)
        version = self.register_artifact(
            "ai_shot_plan:E001",
            "10_AI视频执行包/E001_严容差分镜计划V1.json",
            json.dumps(plan, ensure_ascii=False),
            self.shot_plan_dependencies(),
        )
        code, payload = self.run_cli(
            "approve", str(self.project), "ai_shot_plan:E001", "--version", str(version)
        )
        self.assertEqual(code, 2, payload)
        self.assertIn("shotplan_duration_deviation", payload["error"])

    def test_script_dialogue_budget_warns_without_blocking(self) -> None:
        script = self.root / "超载剧本.md"
        script.write_text(GOOD_SCRIPT, encoding="utf-8")
        # 目标时长设得远低于净对白推算秒数，必然触发超载预警。
        result = project_tool.validate_script_file(script, target_duration_seconds=3)
        codes = {item["code"] for item in result["warnings"]}
        self.assertIn("episode_dialogue_budget_over", codes)
        self.assertTrue(result["valid"])  # 只预警不阻断
        self.assertNotIn(
            "episode_dialogue_budget_over",
            {item["code"] for item in result["errors"]},
        )
        estimate = result["duration_estimate"]
        self.assertGreater(estimate["spoken_char_count"], 0)
        self.assertIn("非配音实测", estimate["estimate_basis"])

    def test_validate_project_propagates_current_script_duration_warnings(self) -> None:
        self.create_ready_project()
        overloaded = GOOD_SCRIPT.replace(
            "管家：把钥匙交出来。", "管家：" + "把钥匙交出来。" * 120
        )
        version = self.register_episode_candidate(content=overloaded, file_tag="时长预警传播")
        result = project_tool.validate_state(self.project)
        warnings = [
            item
            for item in result["warnings"]
            if item.get("artifact_key") == "episode_script:E001"
            and item.get("version") == version
        ]
        self.assertIn("episode_dialogue_budget_over", {item["code"] for item in warnings}, result)
        self.assertIn("scene_duration_unbalanced", {item["code"] for item in warnings}, result)

    def test_script_duration_estimate_absent_without_target(self) -> None:
        """不传目标时长时输出与改动前逐字段一致，且不产生任何时长预警。"""
        script = self.root / "常规剧本.md"
        script.write_text(GOOD_SCRIPT, encoding="utf-8")
        baseline = project_tool.validate_script_file(script)
        self.assertNotIn("duration_estimate", baseline)
        self.assertEqual(
            sorted(baseline["scenes"][0]), ["heading", "line", "scene_id"]
        )
        codes = {item["code"] for item in baseline["warnings"]}
        self.assertNotIn("episode_dialogue_budget_over", codes)
        self.assertNotIn("scene_duration_unbalanced", codes)
        # 目标时长充裕时同样不应报警（防假阳性）
        relaxed = project_tool.validate_script_file(script, target_duration_seconds=600)
        relaxed_codes = {item["code"] for item in relaxed["warnings"]}
        self.assertNotIn("episode_dialogue_budget_over", relaxed_codes)
        self.assertNotIn("scene_duration_unbalanced", relaxed_codes)

    def test_init_defaults_to_direct_self_owned_import(self) -> None:
        code, payload = self.run_cli(
            "init", str(self.project), "--name", "直通项目", "--source", str(self.source)
        )
        self.assertEqual(code, 0, payload)
        self.assertEqual(
            self.state()["source_policy"],
            {
                "source_kind": "self_owned",
                "official_review_enabled": False,
                "official_url": None,
                "content_authority": "uploaded_files",
            },
        )
        self.assertEqual(payload["source_policy"], self.state()["source_policy"])
        self.assertNotIn("入料体检卡", payload)
        self.assertFalse(
            (self.project / "01_原著解析" / "入料体检.json").exists()
        )

    def test_partial_storyline_import_does_not_run_intake_check(self) -> None:
        self.source.write_text("第7章 片段开始，正文尚未结束", encoding="utf-8")
        code, payload = self.run_cli(
            "init",
            str(self.project),
            "--source",
            str(self.source),
            "--source-kind",
            "storyline",
        )
        self.assertEqual(code, 0, payload)
        self.assertEqual(self.state()["source_policy"]["source_kind"], "storyline")
        self.assertNotIn("入料体检卡", payload)

    def test_published_novel_can_request_official_review(self) -> None:
        code, payload = self.run_cli(
            "init",
            str(self.project),
            "--source",
            str(self.source),
            "--source-kind",
            "published_novel",
            "--official-review",
            "--official-url",
            "https://example.com/book",
        )
        self.assertEqual(code, 0, payload)
        self.assertEqual(
            payload["source_policy"],
            {
                "source_kind": "published_novel",
                "official_review_enabled": True,
                "official_url": "https://example.com/book",
                "content_authority": "uploaded_files",
            },
        )

    def test_init_rejects_invalid_official_review_combinations(self) -> None:
        cases = (
            ("self_owned", True, "https://example.com/book"),
            ("storyline", True, "https://example.com/book"),
            ("published_novel", True, None),
            ("published_novel", False, "https://example.com/book"),
            ("published_novel", True, "ftp://example.com/book"),
        )
        for index, (source_kind, review_enabled, official_url) in enumerate(cases):
            project = self.root / f"非法审核_{index}"
            arguments = [
                "init",
                str(project),
                "--source",
                str(self.source),
                "--source-kind",
                source_kind,
            ]
            if review_enabled:
                arguments.append("--official-review")
            if official_url is not None:
                arguments.extend(["--official-url", official_url])
            code, payload = self.run_cli(
                *arguments,
            )
            self.assertEqual(code, 2, (source_kind, review_enabled, official_url, payload))
            self.assertFalse(project.exists())

    def test_garble_threshold_is_accepted_but_ignored(self) -> None:
        code, payload = self.run_cli(
            "init",
            str(self.project),
            "--source",
            str(self.source),
            "--garble-threshold",
            "nan",
        )
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["deprecated_options"], ["--garble-threshold"])
        self.assertNotIn("入料体检卡", payload)

    def test_add_source_does_not_create_or_update_intake_check(self) -> None:
        self.init_project()
        report_path = self.project / "01_原著解析" / "入料体检.json"
        self.assertFalse(report_path.exists())
        extra = self.root / "第3章.txt"
        extra.write_text("第三章 决裂\n管家请来族老，要开祠堂议钥匙归属。\n", encoding="utf-8")
        code, payload = self.run_cli(
            "add-source",
            str(self.project),
            str(extra),
            "--garble-threshold",
            "0.25",
        )
        self.assertEqual(code, 0, payload)
        self.assertFalse(report_path.exists())
        self.assertNotIn("入料体检卡", payload)
        self.assertEqual(payload["deprecated_options"], ["--garble-threshold"])

    def test_old_state_without_source_policy_remains_valid(self) -> None:
        self.init_project()
        state = self.state()
        del state["source_policy"]
        (self.project / project_tool.STATE_FILENAME).write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        result = project_tool.validate_state(self.project)
        self.assertTrue(result["valid"], result)

    def test_validate_project_rejects_malformed_source_policy(self) -> None:
        self.init_project()
        state = self.state()
        state["source_policy"] = {
            "source_kind": "storyline",
            "official_review_enabled": True,
            "official_url": "https://example.com/book",
            "content_authority": "uploaded_files",
        }
        (self.project / project_tool.STATE_FILENAME).write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        result = project_tool.validate_state(self.project)
        self.assertIn(
            "source_policy_invalid", {item["code"] for item in result["errors"]}
        )

    def test_source_review_is_valid_and_non_blocking_for_published_novel(self) -> None:
        code, payload = self.run_cli(
            "init",
            str(self.project),
            "--source",
            str(self.source),
            "--source-kind",
            "published_novel",
            "--official-review",
            "--official-url",
            "https://example.com/book",
        )
        self.assertEqual(code, 0, payload)
        state = self.state()
        review = {
            "schema_version": 1,
            "project_id": state["project_id"],
            "source_kind": "published_novel",
            "official_url": "https://example.com/book",
            "checked_at": "2026-07-28T16:00:00+08:00",
            "uploaded_source_ids": [state["sources"][0]["source_id"]],
            "checks": {
                "title": "matched",
                "author": "matched",
                "chapter_coverage": "partial",
                "sample_content": "inconclusive",
            },
            "conclusion": "mismatch",
            "evidence": [],
            "automation_limitations": "仅核对指定页面可见信息。",
        }
        self.register_artifact(
            "source_review",
            "01_原著解析/来源审核.json",
            json.dumps(review, ensure_ascii=False),
        )
        result = project_tool.validate_state(self.project)
        self.assertTrue(result["valid"], result)

    def test_set_stage_records_split_time_and_summary_aggregates(self) -> None:
        self.init_project()
        code, payload = self.run_cli(
            "set-stage", str(self.project), "source_analysis", "in_progress",
            "--machine-time-seconds", "120.5", "--human-wait-seconds", "30",
        )
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["machine_time_seconds"], 120.5)
        self.assertEqual(payload["human_wait_seconds"], 30)
        events = [
            event
            for event in self.state()["history"]
            if event.get("event") == "stage_changed"
        ]
        self.assertEqual(events[-1]["machine_time_seconds"], 120.5)
        self.assertEqual(events[-1]["human_wait_seconds"], 30)
        code, payload = self.run_cli(
            "set-stage", str(self.project), "source_analysis", "awaiting_approval",
            "--machine-time-seconds", "9.5",
        )
        self.assertEqual(code, 0, payload)
        code, payload = self.run_cli("show", str(self.project), "--summary")
        self.assertEqual(code, 0, payload)
        tracking = payload["time_tracking"]
        self.assertEqual(tracking["machine_time_seconds"], 130.0)
        self.assertEqual(tracking["human_wait_seconds"], 30.0)
        self.assertEqual(
            tracking["by_stage"]["source_analysis"]["machine_time_seconds"], 130.0
        )

    def test_init_expected_episodes_hint_enables_batch_before_project_spec(self) -> None:
        code, payload = self.run_cli(
            "init", str(self.project), "--name", "提示项目",
            "--source", str(self.source), "--expected-episodes", "6",
        )
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["expected_episodes_hint"], 6)
        self.assertEqual(self.state()["expected_episodes_hint"], 6)

        code, payload = self.run_cli("define-batch", str(self.project), "B01", "E001", "E002")
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["episode_scope_source"], "init_hint")
        self.assertEqual(
            {item["code"] for item in payload["warnings"]},
            {"episode_scope_from_init_hint"},
        )

        code, payload = self.run_cli("define-batch", str(self.project), "B02", "E007")
        self.assertEqual(code, 2, payload)
        self.assertIn("init 登记的目标集数提示", payload["error"])
        self.assertTrue(project_tool.validate_state(self.project)["valid"])

    def test_confirmed_project_spec_overrides_init_hint(self) -> None:
        code, payload = self.run_cli(
            "init", str(self.project), "--name", "提示项目",
            "--source", str(self.source), "--expected-episodes", "6",
        )
        self.assertEqual(code, 0, payload)
        self.register_and_approve(
            "project_spec",
            "01_原著解析/项目规格V1.json",
            json.dumps(
                {
                    "schema_version": 1,
                    "project_id": self.state()["project_id"],
                    "expected_episodes": 4,
                    "target_runtime": "按项目实读复核",
                    "handoff_target": "可直接进入导演拆镜",
                },
                ensure_ascii=False,
            ),
        )
        # project_spec 是交付权威：它比 init 提示更小时，超出部分必须被拒绝。
        code, payload = self.run_cli("define-batch", str(self.project), "B01", "E005")
        self.assertEqual(code, 2, payload)
        self.assertIn("项目规格", payload["error"])

        code, payload = self.run_cli("define-batch", str(self.project), "B01", "E004")
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["episode_scope_source"], "project_spec")
        self.assertNotIn("warnings", payload)

    def test_awaiting_project_spec_does_not_override_confirmed_authority(self) -> None:
        self.init_project()
        confirmed = {
            "schema_version": 1,
            "project_id": self.state()["project_id"],
            "expected_episodes": 4,
            "target_runtime": "按项目实读复核",
            "handoff_target": "可直接进入导演拆镜",
        }
        self.register_and_approve(
            "project_spec",
            "01_原著解析/项目规格V1.json",
            json.dumps(confirmed, ensure_ascii=False),
        )
        self.register_artifact(
            "project_spec",
            "01_原著解析/项目规格V2_未确认.json",
            json.dumps({**confirmed, "expected_episodes": 99}, ensure_ascii=False),
        )

        code, payload = self.run_cli("define-batch", str(self.project), "B02", "E005")
        self.assertEqual(code, 2, payload)
        self.assertIn("项目规格 expected_episodes（4）", payload["error"])
        self.assertEqual(project_tool.project_expected_episodes(self.project, self.state()), 4)

    def test_rolling_batch_schema_v2_allows_unknown_final_count_only_with_user_confirmation(self) -> None:
        self.init_project()
        spec = {
            "schema_version": 2,
            "project_id": self.state()["project_id"],
            "scope_mode": "rolling_batch",
            "batch_size": 3,
            "target_duration_seconds": 60,
            "initial_source_window_units": 3,
            "final_expected_episodes": None,
        }
        self.register_and_approve(
            "project_spec", "01_原著解析/项目规格V2.json", json.dumps(spec, ensure_ascii=False)
        )
        code, payload = self.run_cli(
            "define-batch", str(self.project), "B01", "E001", "E002", "E003"
        )
        self.assertEqual(code, 2, payload)
        self.assertIn("--confirmed-by-user", payload["error"])
        code, payload = self.run_cli(
            "define-batch", str(self.project), "B01", "E001", "E002", "E003",
            "--confirmed-by-user",
        )
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["episode_scope_source"], "confirmed_batches")
        self.assertIsNone(project_tool.project_expected_episodes(self.project, self.state()))
        self.assertEqual(project_tool.confirmed_episode_ids(self.state()), ["E001", "E002", "E003"])

    def test_init_without_expected_episodes_still_requires_project_spec(self) -> None:
        self.init_project()
        self.assertIsNone(self.state()["expected_episodes_hint"])
        code, payload = self.run_cli("define-batch", str(self.project), "B01", "E001")
        self.assertEqual(code, 2, payload)
        self.assertIn("无法读取目标集数", payload["error"])

    def test_validate_project_rejects_invalid_expected_episodes_hint(self) -> None:
        self.init_project()
        state = self.state()
        state["expected_episodes_hint"] = 0
        (self.project / project_tool.STATE_FILENAME).write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        result = project_tool.validate_state(self.project)
        self.assertFalse(result["valid"])
        self.assertIn(
            "expected_episodes_hint_invalid",
            {item["code"] for item in result["errors"]},
        )

    def test_prose_shot_language_warns_without_blocking(self) -> None:
        for index, prose_line in enumerate(
            (
                "△【特写】雨水砸在屋檐上，镜头推近，35mm，时长3秒。",
                "△镜头缓缓推近阿宁的脸，特写她攥紧钥匙的手。",
                "△大特写：钥匙上的划痕。",
                "△俯拍全景，院中青石板上的拖痕清晰可见。",
                "△切黑。3秒后淡入。",
                "△手持跟拍，长焦压缩背景。",
                "△给一个特写，钥匙边缘的缺口。",
                "△画面停留约3秒后叠化到下一场。",
                "△以特写呈现她颤抖的手指。",
                "△主观镜头：阿宁看向墙上的字。",
            )
        ):
            with self.subTest(prose_line=prose_line):
                script = self.root / f"prose-{index}.md"
                script.write_text(
                    GOOD_SCRIPT.replace(
                        "△阿宁攥着钥匙退到门槛外。",
                        f"△阿宁攥着钥匙退到门槛外。\n{prose_line}",
                    ),
                    encoding="utf-8",
                )
                result = project_tool.validate_script_file(script)
                # 语义判断留给人工：只预警，不阻断已确认流程。
                self.assertTrue(result["valid"], result)
                self.assertIn(
                    "shot_language_suspected",
                    {item["code"] for item in result["warnings"]},
                )

    def test_prose_shot_language_does_not_warn_on_clean_script_or_dialogue(self) -> None:
        clean = self.root / "clean.md"
        clean.write_text(GOOD_SCRIPT, encoding="utf-8")
        result = project_tool.validate_script_file(clean)
        self.assertNotIn(
            "shot_language_suspected", {item["code"] for item in result["warnings"]}
        )

        # 角色可以在台词里提到镜头词；台词原文不得被当作镜头语言。
        in_dialogue = self.root / "in-dialogue.md"
        in_dialogue.write_text(
            GOOD_SCRIPT.replace(
                "管家：把钥匙交出来。",
                "管家：把钥匙交出来。给我个特写我都认得出来。",
            ),
            encoding="utf-8",
        )
        result = project_tool.validate_script_file(in_dialogue)
        self.assertTrue(result["valid"], result)
        self.assertNotIn(
            "shot_language_suspected", {item["code"] for item in result["warnings"]}
        )

        for narrative_line in (
            "△远景处的城墙在雨里只剩一道轮廓。",
            "△阿宁盯着那两个字看了很久，手心攥紧。",
            "△管家绕出柜台，走过来低头看钥匙，脸色一变。",
        ):
            with self.subTest(narrative_line=narrative_line):
                self.assertEqual(project_tool.prose_shot_language_hits(narrative_line), [])

    def test_tabular_director_field_still_blocks_not_just_warns(self) -> None:
        script = self.root / "tabular.md"
        script.write_text(GOOD_SCRIPT + "\n景别：特写\n", encoding="utf-8")
        result = project_tool.validate_script_file(script)
        self.assertFalse(result["valid"])
        codes = {item["code"] for item in result["errors"]}
        self.assertIn("director_field_forbidden", codes)

    def test_set_stage_without_time_fields_keeps_summary_clean(self) -> None:
        self.init_project()
        code, payload = self.run_cli(
            "set-stage", str(self.project), "source_analysis", "in_progress"
        )
        self.assertEqual(code, 0, payload)
        self.assertNotIn("machine_time_seconds", payload)
        events = [
            event
            for event in self.state()["history"]
            if event.get("event") == "stage_changed"
        ]
        self.assertNotIn("machine_time_seconds", events[-1])
        # 旧项目/旧记录无耗时字段：show --summary 不报错也不显示 time_tracking
        code, payload = self.run_cli("show", str(self.project), "--summary")
        self.assertEqual(code, 0, payload)
        self.assertNotIn("time_tracking", payload)

    def test_set_stage_rejects_negative_time(self) -> None:
        self.init_project()
        code, payload = self.run_cli(
            "set-stage", str(self.project), "source_analysis", "in_progress",
            "--machine-time-seconds", "-1",
        )
        self.assertEqual(code, 2, payload)
        self.assertIn("不能为负数", payload["error"])

    def test_set_stage_rejects_non_finite_time(self) -> None:
        self.init_project()
        for value in ("nan", "inf", "-inf"):
            time_argument = (
                f"--machine-time-seconds={value}"
                if value.startswith("-")
                else "--machine-time-seconds"
            )
            arguments = [
                "set-stage",
                str(self.project),
                "source_analysis",
                "in_progress",
                time_argument,
            ]
            if not value.startswith("-"):
                arguments.append(value)
            code, payload = self.run_cli(
                *arguments,
            )
            self.assertEqual(code, 2, (value, payload))
            self.assertIn("有限数字", payload["error"])


    def character_anchor_v2(self) -> dict:
        return {
            "contract_version": 2,
            "character_id": "C001",
            "display_name": "温喻",
            "role_kind": "stable",
            "source_appearance": {
                "source_refs": ["SRC-CH001:P003"],
                "confirmed_details": ["二十多岁", "黑色长发"],
            },
            "visual_design": {
                "auto_completed": True,
                "face": "鹅蛋脸，眉形清晰，五官比例自然",
                "hair": "黑色长发，发尾自然垂落",
                "body": "成年女性，身材修长，比例自然",
                "wardrobe": "现代都市通勤服，低饱和配色",
                "distinctive_features": [],
            },
            "turnaround_prompt": {
                "layout": "左侧约三分之一为完整正面头肩肖像；右侧依次为全身正面、侧面和背面",
                "consistency_rules": ["四个视图五官、发型、身材比例和服装完全一致"],
                "full_text": "温喻完整三视图描述",
            },
            "forbidden_story_implications": ["不得暗示未公开身份"],
        }

    def test_character_anchor_v2_accepts_source_and_visual_design_separation(self) -> None:
        payload = self.character_anchor_v2()
        self.assertEqual(project_tool.validate_character_anchor_payload(payload), [])

    def test_character_anchor_v2_rejects_missing_turnaround_layout(self) -> None:
        payload = self.character_anchor_v2()
        payload["turnaround_prompt"]["layout"] = ""
        codes = {
            item["code"]
            for item in project_tool.validate_character_anchor_payload(payload)
        }
        self.assertIn("character_anchor_turnaround_layout_missing", codes)

    def test_character_anchor_v2_rejects_plot_claim_in_visual_design(self) -> None:
        payload = self.character_anchor_v2()
        payload["visual_design"]["distinctive_features"] = [
            "家族继承人徽记，证明真实身份"
        ]
        codes = {
            item["code"]
            for item in project_tool.validate_character_anchor_payload(payload)
        }
        self.assertIn("character_anchor_visual_story_claim", codes)

    def partition_fixture_paths(self) -> tuple[Path, Path, Path]:
        corpus = self.write_json(
            "01_原著解析/source_corpus_partition.json",
            {
                "schema_version": 1,
                "source_units": [
                    {"source_unit_id": "SU001", "ordinal": 1, "estimated_tokens": 2000, "complexity_points": 5},
                    {"source_unit_id": "SU002", "ordinal": 2, "estimated_tokens": 2000, "complexity_points": 5},
                    {"source_unit_id": "SU003", "ordinal": 3, "estimated_tokens": 3000, "complexity_points": 7},
                ],
            },
        )
        policy = self.write_json(
            "01_原著解析/partition_policy.json",
            {
                "policy": {
                    "max_input_tokens": 7000,
                    "reserved_output_tokens": 2000,
                    "chars_per_token_estimate": 1.8,
                    "max_complexity_points": 20,
                    "concurrency_mode": "bounded",
                    "max_parallel_tasks": "auto",
                    "single_state_writer": True,
                }
            },
        )
        plan = self.project / "tmp/source-analysis/run-001/partition-plan.json"
        return corpus, policy, plan

    def test_plan_source_partitions_does_not_modify_project_state(self) -> None:
        self.init_project()
        corpus, policy, plan = self.partition_fixture_paths()
        before = (self.project / "project_state.json").read_bytes()
        code, payload = self.run_cli(
            "plan-source-partitions",
            str(self.project),
            "--source-corpus", str(corpus),
            "--policy", str(policy),
            "--output", str(plan),
        )
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["partition_count"], 2)
        self.assertTrue(plan.is_file())
        self.assertEqual((self.project / "project_state.json").read_bytes(), before)

    def test_merge_source_analysis_shards_writes_only_requested_output(self) -> None:
        self.init_project()
        corpus, policy, plan = self.partition_fixture_paths()
        code, payload = self.run_cli(
            "plan-source-partitions",
            str(self.project),
            "--source-corpus", str(corpus),
            "--policy", str(policy),
            "--output", str(plan),
        )
        self.assertEqual(code, 0, payload)
        shard_dir = self.project / "tmp/source-analysis/run-001/shards"
        self.write_json(
            "tmp/source-analysis/run-001/shards/SP001.json",
            {
                "schema_version": 1,
                "partition_id": "SP001",
                "source_unit_ids": ["SU001", "SU002"],
                "units": [
                    {"source_unit_id": "SU001", "status": "ready", "events": [{"event_id": "EV001"}]},
                    {"source_unit_id": "SU002", "status": "ready", "events": [{"event_id": "EV002"}]},
                ],
            },
        )
        self.write_json(
            "tmp/source-analysis/run-001/shards/SP002.json",
            {
                "schema_version": 1,
                "partition_id": "SP002",
                "source_unit_ids": ["SU003"],
                "units": [
                    {"source_unit_id": "SU003", "status": "ready", "events": [{"event_id": "EV003"}]},
                ],
            },
        )
        before = (self.project / "project_state.json").read_bytes()
        output = self.project / "01_原著解析/source_event_index_candidate.json"
        code, payload = self.run_cli(
            "merge-source-analysis-shards",
            str(self.project),
            "--plan", str(plan),
            "--shard-dir", str(shard_dir),
            "--output", str(output),
        )
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["unit_count"], 3)
        self.assertTrue(output.is_file())
        self.assertEqual((self.project / "project_state.json").read_bytes(), before)

    def test_rolling_source_commands_write_only_requested_project_outputs(self) -> None:
        self.init_project()
        project_id = self.state()["project_id"]
        self.register_and_approve(
            "project_spec",
            "01_原著解析/rolling_command_spec_v2.json",
            json.dumps(
                {
                    "schema_version": 2,
                    "project_id": project_id,
                    "scope_mode": "rolling_batch",
                    "batch_size": 1,
                    "initial_source_window_units": 2,
                    "final_expected_episodes": None,
                    "target_duration_seconds": 60,
                },
                ensure_ascii=False,
            ),
        )
        code, payload = self.run_cli(
            "define-batch",
            str(self.project),
            "B01",
            "E001",
            "--confirmed-by-user",
        )
        self.assertEqual(code, 0, payload)
        corpus = self.write_json(
            "01_原著解析/rolling_corpus.json",
            {
                "schema_version": 1,
                "source_units": [
                    {"source_unit_id": "SU001", "ordinal": 1, "estimated_tokens": 100, "complexity_points": 1, "content_sha256": "hash-1"},
                    {"source_unit_id": "SU002", "ordinal": 2, "estimated_tokens": 100, "complexity_points": 1, "content_sha256": "hash-2"},
                ],
            },
        )
        registry = self.write_json(
            "01_原著解析/chapter_registry_v1.json",
            {"schema_version": 1, "records": []},
        )
        progress = self.write_json(
            "01_原著解析/rolling_progress_v2.json",
            {
                "schema_version": 2,
                "current_batch_id": "B01",
                "completed_window_count": 1,
                "batch_readiness": "needs_more_source",
                "source_gap_reasons": ["测试窗口尚未覆盖SU002"],
                "carryover_event_ids": [],
                "event_consumption": {},
                "next_read_start": "SU002",
            },
        )
        analysis = self.write_json("tmp/SU001_analysis.json", {"events": []})
        registry_v2 = self.project / "01_原著解析/chapter_registry_v2.json"
        code, payload = self.run_cli(
            "register-source-analysis", str(self.project),
            "--source-corpus", str(corpus), "--registry", str(registry),
            "--source-unit-id", "SU001", "--analysis", str(analysis),
            "--contract-version", "1", "--output", str(registry_v2),
        )
        self.assertEqual(code, 0, payload)
        plan = self.project / "tmp/rolling_plan.json"
        code, payload = self.run_cli(
            "plan-rolling-source-window", str(self.project),
            "--source-corpus", str(corpus), "--registry", str(registry_v2),
            "--progress", str(progress), "--window-size", "2", "--output", str(plan),
        )
        self.assertEqual(code, 0, payload)
        self.assertEqual(json.loads(plan.read_text())["new_analysis_source_unit_ids"], ["SU002"])

    def rolling_window_v2_fixture(
        self,
        *,
        define_batch: bool,
        confirm_spec: bool = True,
        readiness: str = "initial_window",
        completed_window_count: int = 0,
        registry_has_first_unit: bool = False,
    ) -> tuple[Path, Path, Path]:
        self.init_project()
        project_id = self.state()["project_id"]
        spec = {
            "schema_version": 2,
            "project_id": project_id,
            "scope_mode": "rolling_batch",
            "batch_size": 1,
            "initial_source_window_units": 2,
            "final_expected_episodes": None,
            "target_duration_seconds": 60,
        }
        if confirm_spec:
            self.register_and_approve(
                "project_spec",
                "01_原著解析/滚动项目规格V2.json",
                json.dumps(spec, ensure_ascii=False),
            )
        if define_batch:
            code, payload = self.run_cli(
                "define-batch",
                str(self.project),
                "B01",
                "E001",
                "--confirmed-by-user",
            )
            self.assertEqual(code, 0, payload)
        corpus = self.write_json(
            "01_原著解析/rolling_gate_corpus.json",
            {
                "schema_version": 1,
                "source_units": [
                    {"source_unit_id": "SU001", "ordinal": 1, "estimated_tokens": 100, "complexity_points": 1, "content_sha256": "hash-1"},
                    {"source_unit_id": "SU002", "ordinal": 2, "estimated_tokens": 100, "complexity_points": 1, "content_sha256": "hash-2"},
                    {"source_unit_id": "SU003", "ordinal": 3, "estimated_tokens": 100, "complexity_points": 1, "content_sha256": "hash-3"},
                ],
            },
        )
        records = []
        if registry_has_first_unit:
            records.append(
                {
                    "source_unit_id": "SU001",
                    "content_sha256": "hash-1",
                    "analysis_contract_version": 1,
                    "analysis_status": "analyzed",
                    "analysis_path": "tmp/SU001.json",
                    "analysis_sha256": "analysis-1",
                    "idempotency_key": "SU001:hash-1:v1",
                }
            )
        registry = self.write_json(
            "01_原著解析/rolling_gate_registry.json",
            {"schema_version": 1, "records": records},
        )
        source_gap_reasons = (
            ["当前窗口只够支撑E001，B01仍缺少后续冲突结果"]
            if readiness == "needs_more_source"
            else []
        )
        progress = self.write_json(
            "01_原著解析/rolling_gate_progress.json",
            {
                "schema_version": 2,
                "current_batch_id": "B01",
                "completed_window_count": completed_window_count,
                "batch_readiness": readiness,
                "source_gap_reasons": source_gap_reasons,
                "carryover_event_ids": [],
                "event_consumption": {},
                "next_read_start": None if readiness == "ready_for_batch" else ("SU002" if completed_window_count else "SU001"),
            },
        )
        return corpus, registry, progress

    def test_rolling_window_requires_confirmed_rolling_project_spec(self) -> None:
        corpus, registry, progress = self.rolling_window_v2_fixture(
            define_batch=False,
            confirm_spec=False,
        )
        output = self.project / "tmp/rolling_without_confirmed_spec.json"
        code, payload = self.run_cli(
            "plan-rolling-source-window",
            str(self.project),
            "--source-corpus", str(corpus),
            "--registry", str(registry),
            "--progress", str(progress),
            "--window-size", "2",
            "--output", str(output),
        )
        self.assertEqual(code, 2, payload)
        self.assertIn("rolling_batch", payload["error"])
        self.assertIn("项目规格", payload["error"])
        self.assertFalse(output.exists())

    def test_rolling_window_requires_confirmed_project_batch(self) -> None:
        corpus, registry, progress = self.rolling_window_v2_fixture(define_batch=False)
        output = self.project / "tmp/rolling_without_batch.json"
        code, payload = self.run_cli(
            "plan-rolling-source-window",
            str(self.project),
            "--source-corpus", str(corpus),
            "--registry", str(registry),
            "--progress", str(progress),
            "--window-size", "2",
            "--output", str(output),
        )
        self.assertEqual(code, 2, payload)
        self.assertIn("B01", payload["error"])
        self.assertIn("已确认批次", payload["error"])
        self.assertFalse(output.exists())

    def test_rolling_window_allows_initial_window_after_b01_confirmation(self) -> None:
        corpus, registry, progress = self.rolling_window_v2_fixture(define_batch=True)
        output = self.project / "tmp/rolling_b01_initial.json"
        code, payload = self.run_cli(
            "plan-rolling-source-window",
            str(self.project),
            "--source-corpus", str(corpus),
            "--registry", str(registry),
            "--progress", str(progress),
            "--window-size", "2",
            "--output", str(output),
        )
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["batch_id"], "B01")
        self.assertEqual(payload["planned_window_number"], 1)
        self.assertTrue(payload["checkpoint_required_after_window"])
        self.assertEqual(
            json.loads(output.read_text(encoding="utf-8"))["new_analysis_source_unit_ids"],
            ["SU001", "SU002"],
        )

    def test_rolling_window_blocks_next_window_when_b01_is_ready(self) -> None:
        corpus, registry, progress = self.rolling_window_v2_fixture(
            define_batch=True,
            readiness="ready_for_batch",
            completed_window_count=1,
            registry_has_first_unit=True,
        )
        output = self.project / "tmp/rolling_b01_should_stop.json"
        code, payload = self.run_cli(
            "plan-rolling-source-window",
            str(self.project),
            "--source-corpus", str(corpus),
            "--registry", str(registry),
            "--progress", str(progress),
            "--window-size", "2",
            "--output", str(output),
        )
        self.assertEqual(code, 2, payload)
        self.assertIn("B01", payload["error"])
        self.assertIn("转入", payload["error"])
        self.assertFalse(output.exists())

    def test_rolling_window_requires_checkpoint_after_registered_analysis(self) -> None:
        corpus, registry, progress = self.rolling_window_v2_fixture(
            define_batch=True,
            registry_has_first_unit=True,
        )
        output = self.project / "tmp/rolling_b01_checkpoint_required.json"
        code, payload = self.run_cli(
            "plan-rolling-source-window",
            str(self.project),
            "--source-corpus", str(corpus),
            "--registry", str(registry),
            "--progress", str(progress),
            "--window-size", "2",
            "--output", str(output),
        )
        self.assertEqual(code, 2, payload)
        self.assertIn("initial_window", payload["error"])
        self.assertIn("ready_for_batch", payload["error"])
        self.assertFalse(output.exists())

    def test_production_context_manifest_excludes_tests_and_development_plans(self) -> None:
        self.init_project()
        output = self.project / "tmp/production_context.json"
        code, payload = self.run_cli(
            "build-production-context-manifest",
            str(self.project),
            "--stage", "source_analysis",
            "--output", str(output),
        )
        self.assertEqual(code, 0, payload)
        loaded = json.loads(output.read_text())
        paths = loaded["allowed_plugin_paths"]
        self.assertTrue(paths)
        self.assertFalse(any("test_" in path for path in paths))
        self.assertFalse(any("docs/superpowers/plans" in path for path in paths))

    def agent_task_args(
        self,
        *,
        task_type: str = "source_analysis",
        acceptance_command: str = "schema-only",
        artifact_key: str | None = None,
        scope: dict | None = None,
        input_filename: str = "agent_input.json",
        scheduling_mode: str | None = None,
        max_parallel_tasks: int | None = None,
        service_capacity: int | None = None,
        host_task_id: str | None = None,
        active_host_task_ids: list[str] | None = None,
        stage: str = "source_analysis",
        operation: str | None = None,
        input_content: str = "冻结输入",
        delegation_directive: str | None = "继续执行",
        warnings: list[str] | None = None,
        major_ambiguities: list[str] | None = None,
        ensure_preflight: bool = True,
    ) -> list[str]:
        if ensure_preflight:
            self.ensure_production_preflight()
        input_path = self.write_project_file(
            f"01_原著解析/{input_filename}",
            json.dumps(
                {"source_unit_id": "SU001", "content": input_content},
                ensure_ascii=False,
            ),
        )
        arguments = [
            "plan-agent-slice",
            str(self.project),
            "--task-type",
            task_type,
            "--scope-json",
            json.dumps(
                scope
                or {"batch_id": "B01", "episode_id": "E001", "source_unit_id": "SU001"}
            ),
            "--input-ref",
            f"source_corpus@1={input_path}",
            "--contract-version",
            "1",
            "--acceptance-command",
            acceptance_command,
            "--coordinator-slice",
            "source_window",
            "--run-id",
            "RUN-TEST-001",
            "--stage",
            stage,
            "--output-schema-version",
            "1",
        ]
        if operation is not None:
            arguments.extend(["--operation", operation])
        if delegation_directive is not None:
            arguments.extend(["--delegation-directive", delegation_directive])
        if artifact_key is not None:
            arguments.extend(["--artifact-key", artifact_key])
        if scheduling_mode is not None:
            arguments.extend(["--scheduling-mode", scheduling_mode])
        if max_parallel_tasks is not None:
            arguments.extend(["--max-parallel-tasks", str(max_parallel_tasks)])
        if service_capacity is not None:
            arguments.extend(["--service-capacity", str(service_capacity)])
        if host_task_id is not None:
            arguments.extend(["--host-task-id", host_task_id])
        for active_host_task_id in active_host_task_ids or []:
            arguments.extend(["--active-host-task-id", active_host_task_id])
        for warning in warnings or []:
            arguments.extend(["--warning", warning])
        for ambiguity in major_ambiguities or []:
            arguments.extend(["--major-ambiguity", ambiguity])
        return arguments

    def ensure_production_preflight(
        self,
        *,
        run_id: str = "RUN-TEST-001",
        mode: str = "production",
        development_task_id: str | None = None,
    ) -> dict:
        arguments = [
            "startup-preflight",
            str(self.project),
            "--run-id",
            run_id,
            "--mode",
            mode,
        ]
        if development_task_id is not None:
            arguments.extend(["--development-task-id", development_task_id])
        code, payload = self.run_cli(*arguments)
        self.assertEqual(code, 0, payload)
        return payload

    def set_delivery_target(self, delivery_target: str) -> None:
        self.update_artifact_json(
            "project_spec",
            lambda payload: payload.update(
                {"delivery_target": delivery_target}
            ),
        )

    def downgrade_source_event_index_to_v1(self) -> None:
        def downgrade(payload: dict) -> None:
            payload["schema_version"] = 1
            payload.pop("content_contract_version", None)
            payload.pop("episode_scopes", None)
            for unit in payload.get("units", []):
                for event in unit.get("events", []):
                    event.pop("beats", None)

        self.update_artifact_json("source_event_index", downgrade)

    def prepare_agent_source_contract_project(
        self,
        *,
        delivery_target: str,
        schema_version: int,
    ) -> None:
        self.init_project()
        project_id = self.state()["project_id"]
        self.register_and_approve(
            "project_spec",
            "01_原著解析/项目规格V1.json",
            json.dumps(
                {
                    "schema_version": 1,
                    "project_id": project_id,
                    "expected_episodes": 1,
                    "delivery_target": delivery_target,
                },
                ensure_ascii=False,
            ),
        )
        normalized_source = self.write_project_file(
            "01_原著解析/标准化正文_第001章.txt",
            "阿宁守住母亲留下的钥匙。\n",
        )
        source_corpus = {
            "schema_version": 1,
            "project_id": project_id,
            "generated_from": [
                {"artifact_key": "project_spec", "version": 1}
            ],
            "source_units": [
                {
                    "source_unit_id": "SRC-CH001",
                    "source_id": self.state()["sources"][0]["source_id"],
                    "source_locator": "第1章",
                    "ordinal": 1,
                    "content_path": normalized_source.relative_to(
                        self.project
                    ).as_posix(),
                    "content_sha256": project_tool.sha256_file(
                        normalized_source
                    ),
                }
            ],
        }
        self.register_and_approve(
            "source_corpus",
            "01_原著解析/原著语料V1.json",
            json.dumps(source_corpus, ensure_ascii=False),
            ("project_spec@1",),
        )
        event = {
            "event_id": "EV-0001",
            "ordinal": 1,
            "summary": "阿宁守住母亲留下的钥匙",
            "participants": ["C001"],
            "cause": "钥匙是母亲遗物",
            "action": "阿宁拒绝交出钥匙",
            "outcome": "钥匙仍由阿宁持有",
            "state_change": "守护钥匙的冲突建立",
            "source_refs": ["SRC-CH001"],
        }
        source_event_index = {
            "schema_version": schema_version,
            "project_id": project_id,
            "generated_from": [
                {"artifact_key": "source_corpus", "version": 1}
            ],
            "units": [
                {
                    "source_unit_id": "SRC-CH001",
                    "source_locator": "第1章",
                    "status": "ready",
                    "events": [event],
                }
            ],
        }
        if schema_version == 2:
            source_event_index.update(
                {
                    "content_contract_version": 1,
                    "entities": [
                        {
                            "entity_id": "C001",
                            "entity_type": "character",
                            "canonical_name": "阿宁",
                            "aliases": [],
                        }
                    ],
                    "fact_definitions": [],
                    "temporal_constraints": [],
                    "episode_scopes": {
                        "E001": {
                            "allowed_beat_ids": ["B001"],
                            "first_beat_id": "B001",
                            "last_beat_id": "B001",
                        }
                    },
                }
            )
            event["beats"] = [
                {
                    "beat_id": "B001",
                    "ordinal": 1,
                    "source_refs": ["SRC-CH001", "第1章"],
                    "protected_fact_ids": [],
                    "required_fact_ids": [],
                    "content_atoms": [
                        {
                            "atom_id": "SA-B001-001",
                            "kind": "action",
                            "text": "阿宁守住母亲留下的钥匙。",
                            "source_unit_id": "SRC-CH001",
                            "source_locator": "第1章",
                            "source_excerpt": "阿宁守住母亲留下的钥匙。",
                        }
                    ],
                }
            ]
        self.register_and_approve(
            "source_event_index",
            "01_原著解析/原著事件索引V1.json",
            json.dumps(source_event_index, ensure_ascii=False),
            ("source_corpus@1",),
        )

    def test_production_preflight_runs_once_and_reruns_on_environment_change(self) -> None:
        self.init_project()
        original_validate_state = project_tool.validate_state
        with mock.patch.object(
            project_tool,
            "validate_state",
            wraps=original_validate_state,
        ) as validate_state_mock:
            with mock.patch.dict(
                os.environ,
                {"AI_DIRECTOR_ENVIRONMENT_REVISION": "env-a"},
                clear=False,
            ):
                first = self.ensure_production_preflight()
                second = self.ensure_production_preflight()
            with mock.patch.dict(
                os.environ,
                {"AI_DIRECTOR_ENVIRONMENT_REVISION": "env-b"},
                clear=False,
            ):
                third = self.ensure_production_preflight()

        self.assertFalse(first["reused"])
        self.assertEqual(first["preflight_run_count"], 1)
        self.assertTrue(second["reused"])
        self.assertEqual(second["preflight_run_count"], 1)
        self.assertFalse(third["reused"])
        self.assertEqual(third["preflight_run_count"], 2)
        self.assertEqual(third["rerun_reason"], "environment_changed")
        self.assertEqual(validate_state_mock.call_count, 2)

    def test_execution_failure_allows_one_preflight_rerun(self) -> None:
        self.init_project()
        first_preflight = self.ensure_production_preflight()
        self.assertEqual(first_preflight["preflight_run_count"], 1)
        code, planned = self.run_cli(*self.agent_task_args())
        self.assertEqual(code, 0, planned)
        task = json.loads(
            (self.project / planned["task_path"]).read_text(encoding="utf-8")
        )
        failed_result = self.write_agent_result(
            task,
            status="failed",
            error_code="429_too_many_requests",
        )
        code, failed = self.run_cli(
            "accept-agent-result",
            str(self.project),
            "--task-id",
            task["task_id"],
            "--result",
            str(failed_result),
        )
        self.assertEqual(code, 0, failed)
        rerun = self.ensure_production_preflight()
        reused = self.ensure_production_preflight()
        self.assertFalse(rerun["reused"])
        self.assertEqual(rerun["rerun_reason"], "execution_failure")
        self.assertEqual(rerun["preflight_run_count"], 2)
        self.assertTrue(reused["reused"])
        self.assertEqual(reused["preflight_run_count"], 2)

    def test_production_mode_locks_and_blocks_development_operations(self) -> None:
        self.init_project()
        code, missing_development_task = self.run_cli(
            "startup-preflight",
            str(self.project),
            "--run-id",
            "RUN-DEV-MISSING",
            "--mode",
            "development",
        )
        self.assertEqual(code, 2, missing_development_task)
        self.assertIn(
            "development_task_id_required",
            missing_development_task["error"],
        )
        preflight = self.ensure_production_preflight()
        self.assertEqual(preflight["execution_mode"], "production")

        code, rejected_mode = self.run_cli(
            "startup-preflight",
            str(self.project),
            "--run-id",
            "RUN-TEST-001",
            "--mode",
            "development",
            "--development-task-id",
            "DEV-001",
        )
        self.assertEqual(code, 2, rejected_mode)
        self.assertIn("execution_mode_locked", rejected_mode["error"])

        code, rejected_task = self.run_cli(
            *self.agent_task_args(
                task_type="development_test",
                operation="development_test",
            )
        )
        self.assertEqual(code, 2, rejected_task)
        self.assertIn("production_operation_forbidden", rejected_task["error"])

        code, planned = self.run_cli(*self.agent_task_args())
        self.assertEqual(code, 0, planned)
        task = json.loads(
            (self.project / planned["task_path"]).read_text(encoding="utf-8")
        )
        self.assertEqual(task["execution_mode"], "production")
        self.assertFalse(task["execution_policy"]["source_mutation_allowed"])
        self.assertFalse(task["execution_policy"]["development_tests_allowed"])
        self.assertFalse(task["execution_policy"]["design_review_allowed"])

    def test_environment_change_requires_preflight_before_more_planning(self) -> None:
        self.init_project()
        with mock.patch.dict(
            os.environ,
            {"AI_DIRECTOR_ENVIRONMENT_REVISION": "env-a"},
            clear=False,
        ):
            self.ensure_production_preflight()
            code, first = self.run_cli(
                *self.agent_task_args(ensure_preflight=False)
            )
            self.assertEqual(code, 0, first)
        with mock.patch.dict(
            os.environ,
            {"AI_DIRECTOR_ENVIRONMENT_REVISION": "env-b"},
            clear=False,
        ):
            code, stale = self.run_cli(
                *self.agent_task_args(
                    input_filename="environment_changed.json",
                    ensure_preflight=False,
                )
            )
            self.assertEqual(code, 2, stale)
            self.assertIn("execution_preflight_stale", stale["error"])
            refreshed = self.ensure_production_preflight()
            self.assertFalse(refreshed["reused"])
            self.assertEqual(refreshed["rerun_reason"], "environment_changed")

    def test_ai_video_schema_v1_blocks_production_extraction_before_task_creation(
        self,
    ) -> None:
        self.prepare_agent_source_contract_project(
            delivery_target="ai_video",
            schema_version=1,
        )

        code, payload = self.run_cli(
            *self.agent_task_args(
                task_type="production_extraction",
                stage="quality_review",
                operation="production_extraction",
            )
        )
        self.assertEqual(code, 2, payload)
        self.assertEqual(payload["error"], "ai_video_source_contract_not_ready")
        runtime_root = self.project / ".ai-director/runtime"
        self.assertEqual(list((runtime_root / "tasks").glob("*.json")), [])
        self.assertEqual(list((runtime_root / "candidates").glob("*")), [])

    def test_ai_video_schema_v2_allows_production_extraction(self) -> None:
        self.prepare_agent_source_contract_project(
            delivery_target="ai_video",
            schema_version=2,
        )

        code, payload = self.run_cli(
            *self.agent_task_args(
                task_type="production_extraction",
                stage="quality_review",
                operation="production_extraction",
            )
        )
        self.assertEqual(code, 0, payload)
        self.assertFalse(payload["reused"])
        self.assertEqual(payload["attempt"], 1)

    def test_human_team_schema_v1_allows_production_extraction(self) -> None:
        self.prepare_agent_source_contract_project(
            delivery_target="human_team",
            schema_version=1,
        )

        code, payload = self.run_cli(
            *self.agent_task_args(
                task_type="production_extraction",
                stage="quality_review",
                operation="production_extraction",
            )
        )
        self.assertEqual(code, 0, payload)
        self.assertFalse(payload["reused"])
        self.assertEqual(payload["attempt"], 1)

    def test_same_active_planned_task_is_reused_without_duplicate_planning(self) -> None:
        self.init_project()
        arguments = self.agent_task_args()
        code, first = self.run_cli(*arguments)
        self.assertEqual(code, 0, first)
        code, second = self.run_cli(
            *self.agent_task_args(delegation_directive=None)
        )
        self.assertEqual(code, 0, second)
        self.assertTrue(second["reused"])
        self.assertEqual(second["reuse_reason"], "active_planned_task_reused")
        self.assertEqual(second["task_id"], first["task_id"])
        self.assertTrue(second["authorization_reused"])
        self.assertEqual(
            len(list((self.project / ".ai-director/runtime/tasks").glob("*.json"))),
            1,
        )

    def test_completed_task_with_missing_output_is_reexecuted(self) -> None:
        self.init_project()
        arguments = self.agent_task_args()
        code, planned = self.run_cli(*arguments)
        self.assertEqual(code, 0, planned)
        task = json.loads(
            (self.project / planned["task_path"]).read_text(encoding="utf-8")
        )
        candidate = (
            self.project / task["allowed_write_directory"] / "analysis.json"
        )
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_text('{"events":[]}', encoding="utf-8")
        result = self.write_agent_result(
            task,
            candidate_output_paths=[
                candidate.relative_to(self.project).as_posix()
            ],
        )
        code, accepted = self.run_cli(
            "accept-agent-result",
            str(self.project),
            "--task-id",
            task["task_id"],
            "--result",
            str(result),
        )
        self.assertEqual(code, 0, accepted)
        candidate.unlink()

        code, replanned = self.run_cli(*arguments)
        self.assertEqual(code, 0, replanned)
        self.assertFalse(replanned["reused"])
        self.assertEqual(replanned["attempt"], 2)
        self.assertEqual(replanned["idempotency_key"], task["idempotency_key"])
        self.assertEqual(
            replanned["recovered_from_invalid_task_id"],
            task["task_id"],
        )

    def test_completed_task_with_changed_output_hash_is_reexecuted(self) -> None:
        self.init_project()
        arguments = self.agent_task_args()
        code, planned = self.run_cli(*arguments)
        self.assertEqual(code, 0, planned)
        task = json.loads(
            (self.project / planned["task_path"]).read_text(encoding="utf-8")
        )
        candidate = (
            self.project / task["allowed_write_directory"] / "analysis.json"
        )
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_text('{"events":[]}', encoding="utf-8")
        result = self.write_agent_result(
            task,
            candidate_output_paths=[
                candidate.relative_to(self.project).as_posix()
            ],
        )
        code, accepted = self.run_cli(
            "accept-agent-result",
            str(self.project),
            "--task-id",
            task["task_id"],
            "--result",
            str(result),
        )
        self.assertEqual(code, 0, accepted)
        candidate.write_text('{"events":[{"changed":true}]}', encoding="utf-8")

        code, replanned = self.run_cli(*arguments)
        self.assertEqual(code, 0, replanned)
        self.assertFalse(replanned["reused"])
        self.assertEqual(replanned["attempt"], 2)
        self.assertEqual(
            replanned["recovered_from_invalid_task_id"],
            task["task_id"],
        )

    def test_decision_idempotency_key_includes_versions_contract_and_input_hash(self) -> None:
        self.init_project()
        code, first = self.run_cli(
            *self.agent_task_args(input_content="输入A")
        )
        self.assertEqual(code, 0, first)
        first_task = json.loads(
            (self.project / first["task_path"]).read_text(encoding="utf-8")
        )
        candidate = (
            self.project / first_task["allowed_write_directory"] / "analysis.json"
        )
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_text('{"events":[]}', encoding="utf-8")
        result = self.write_agent_result(
            first_task,
            candidate_output_paths=[
                candidate.relative_to(self.project).as_posix()
            ],
        )
        code, accepted = self.run_cli(
            "accept-agent-result",
            str(self.project),
            "--task-id",
            first_task["task_id"],
            "--result",
            str(result),
        )
        self.assertEqual(code, 0, accepted)

        code, second = self.run_cli(
            *self.agent_task_args(
                input_content="输入B",
                delegation_directive="按方案完成",
            )
        )
        self.assertEqual(code, 0, second)
        second_task = json.loads(
            (self.project / second["task_path"]).read_text(encoding="utf-8")
        )
        identity = second_task["decision_identity"]
        self.assertNotEqual(first_task["idempotency_key"], second_task["idempotency_key"])
        self.assertEqual(identity["project_id"], self.state()["project_id"])
        self.assertEqual(identity["stage"], "source_analysis")
        self.assertEqual(identity["operation"], "source_analysis")
        self.assertEqual(identity["rule_version"], project_tool.agent_runtime.RULE_VERSION)
        self.assertEqual(identity["runtime_version"], project_tool.agent_runtime.RUNTIME_VERSION)
        self.assertEqual(identity["plugin_version"], project_tool.agent_runtime.PLUGIN_VERSION)
        self.assertEqual(identity["output_contract_version"], 1)
        self.assertEqual(identity["output_schema_version"], 1)
        self.assertNotEqual(
            first_task["decision_identity"]["input_hash"],
            identity["input_hash"],
        )

    def test_delegation_authorization_reuses_and_invalidates_by_scope(self) -> None:
        self.init_project()
        code, first = self.run_cli(
            *self.agent_task_args(delegation_directive="继续执行")
        )
        self.assertEqual(code, 0, first)
        self.assertFalse(first["authorization_reused"])
        first_authorization_id = first["authorization_id"]

        code, reused = self.run_cli(
            *self.agent_task_args(delegation_directive=None)
        )
        self.assertEqual(code, 0, reused)
        self.assertTrue(reused["authorization_reused"])
        self.assertEqual(reused["authorization_id"], first_authorization_id)

        code, changed_input = self.run_cli(
            *self.agent_task_args(
                input_content="输入已变化",
                delegation_directive=None,
            )
        )
        self.assertEqual(code, 2, changed_input)
        self.assertIn("delegation_authorization_required", changed_input["error"])

        code, changed_stage = self.run_cli(
            *self.agent_task_args(
                stage="batch_writing",
                delegation_directive=None,
            )
        )
        self.assertEqual(code, 2, changed_stage)
        self.assertIn("delegation_authorization_required", changed_stage["error"])

    def test_negated_delegation_directives_never_create_authorization(self) -> None:
        for directive in (
            "不要继续执行",
            "请勿按方案完成",
            "不能继续执行",
            "不应继续执行",
            "无需继续执行",
            "do not continue execution",
            "don't complete as planned",
            "cannot continue execution",
            "should not continue execution",
        ):
            with self.subTest(directive=directive):
                self.assertFalse(
                    project_tool.agent_runtime.directive_is_explicit(directive)
                )

    def test_negated_delegation_directive_overrides_existing_authorization(self) -> None:
        self.init_project()
        code, first = self.run_cli(
            *self.agent_task_args(delegation_directive="继续执行")
        )
        self.assertEqual(code, 0, first)

        code, stopped = self.run_cli(
            *self.agent_task_args(delegation_directive="不要继续执行")
        )
        self.assertEqual(code, 2, stopped)
        self.assertIn("delegation_authorization_required", stopped["error"])

    def test_warning_is_recorded_once_and_does_not_block(self) -> None:
        self.init_project()
        code, first = self.run_cli(
            *self.agent_task_args(warnings=["optional_context_missing"])
        )
        self.assertEqual(code, 0, first)
        self.assertEqual(first["warning_count"], 1)
        code, second = self.run_cli(
            *self.agent_task_args(
                warnings=["optional_context_missing"],
                delegation_directive=None,
            )
        )
        self.assertEqual(code, 0, second)
        self.assertTrue(second["reused"])
        code, runtime = self.run_cli("show-agent-runtime", str(self.project))
        self.assertEqual(code, 0, runtime)
        notices = runtime["execution_control"]["decision_notices"]
        warning_notices = [
            item for item in notices if item["severity"] == "warning"
        ]
        self.assertEqual(len(warning_notices), 1)
        self.assertEqual(warning_notices[0]["occurrence_count"], 2)

    def test_major_ambiguity_blocks_and_pauses_unrelated_active_tasks(self) -> None:
        self.init_project()
        code, first = self.run_cli(
            *self.agent_task_args(
                host_task_id="HOST-ACTIVE-001",
                active_host_task_ids=["HOST-ACTIVE-001"],
            )
        )
        self.assertEqual(code, 0, first)

        code, blocked = self.run_cli(
            *self.agent_task_args(
                input_filename="blocked_input.json",
                input_content="需要重大判断的新输入",
                delegation_directive="继续执行",
                major_ambiguities=["missing_required_story_decision"],
                active_host_task_ids=["HOST-ACTIVE-001"],
            )
        )
        self.assertEqual(code, 2, blocked)
        self.assertIn("major_ambiguity_blocked", blocked["error"])

        code, runtime = self.run_cli("show-agent-runtime", str(self.project))
        self.assertEqual(code, 0, runtime)
        self.assertEqual(runtime["execution_control"]["status"], "blocked")
        self.assertEqual(
            runtime["execution_control"]["active_blocker"]["severity"],
            "major_ambiguity",
        )
        self.assertEqual(runtime["run"]["status"], "blocked")
        self.assertEqual(runtime["run"]["active_task_ids"], [])
        self.assertEqual(runtime["agent_runtime"]["status"], "blocked")
        self.assertEqual(runtime["agent_runtime"]["active_task_ids"], [])
        first_task = json.loads(
            (self.project / first["task_path"]).read_text(encoding="utf-8")
        )
        self.assertEqual(first_task["status"], "paused")

        code, unrelated = self.run_cli(
            *self.agent_task_args(
                input_filename="unrelated_input.json",
                input_content="无关并行验证",
                delegation_directive="继续执行",
            )
        )
        self.assertEqual(code, 2, unrelated)
        self.assertIn("active_execution_blocker", unrelated["error"])

    def test_candidate_acceptance_failure_blocks_unrelated_tasks(self) -> None:
        self.init_project()
        code, first = self.run_cli(
            *self.agent_task_args(
                host_task_id="HOST-INVALID-CANDIDATE",
                active_host_task_ids=["HOST-INVALID-CANDIDATE"],
            )
        )
        self.assertEqual(code, 0, first)
        first_task = json.loads(
            (self.project / first["task_path"]).read_text(encoding="utf-8")
        )
        invalid_candidate = (
            self.project
            / first_task["allowed_write_directory"]
            / "invalid.json"
        )
        invalid_candidate.parent.mkdir(parents=True, exist_ok=True)
        invalid_candidate.write_text("not-json", encoding="utf-8")
        result = self.write_agent_result(
            first_task,
            candidate_output_paths=[
                invalid_candidate.relative_to(self.project).as_posix()
            ],
        )
        code, rejected = self.run_cli(
            "accept-agent-result",
            str(self.project),
            "--task-id",
            first_task["task_id"],
            "--result",
            str(result),
        )
        self.assertEqual(code, 2, rejected)
        self.assertIn("candidate_validation_failed", rejected["error"])

        code, runtime = self.run_cli("show-agent-runtime", str(self.project))
        self.assertEqual(code, 0, runtime)
        blocker = runtime["execution_control"]["active_blocker"]
        self.assertEqual(blocker["severity"], "acceptance_failure")
        blocked_task = json.loads(
            (self.project / first["task_path"]).read_text(encoding="utf-8")
        )
        self.assertEqual(blocked_task["status"], "acceptance_failed")

        code, unrelated = self.run_cli(
            *self.agent_task_args(
                input_filename="after_acceptance_failure.json",
                input_content="不应继续的新任务",
            )
        )
        self.assertEqual(code, 2, unrelated)
        self.assertIn("active_execution_blocker", unrelated["error"])

    def test_missing_candidate_in_result_envelope_uses_acceptance_blocker(self) -> None:
        self.init_project()
        code, planned = self.run_cli(*self.agent_task_args())
        self.assertEqual(code, 0, planned)
        task = json.loads(
            (self.project / planned["task_path"]).read_text(encoding="utf-8")
        )
        result = self.write_agent_result(task, candidate_output_paths=[])
        code, rejected = self.run_cli(
            "accept-agent-result",
            str(self.project),
            "--task-id",
            task["task_id"],
            "--result",
            str(result),
        )
        self.assertEqual(code, 2, rejected)
        self.assertIn("candidate_validation_failed", rejected["error"])
        blocked_task = json.loads(
            (self.project / planned["task_path"]).read_text(encoding="utf-8")
        )
        self.assertEqual(blocked_task["status"], "acceptance_failed")
        code, runtime = self.run_cli("show-agent-runtime", str(self.project))
        self.assertEqual(code, 0, runtime)
        self.assertEqual(
            runtime["execution_control"]["active_blocker"]["severity"],
            "acceptance_failure",
        )

    def test_preflight_rerun_does_not_clear_active_blocker(self) -> None:
        self.init_project()
        with mock.patch.dict(
            os.environ,
            {"AI_DIRECTOR_ENVIRONMENT_REVISION": "env-a"},
            clear=False,
        ):
            self.ensure_production_preflight()
            code, blocked = self.run_cli(
                *self.agent_task_args(
                    input_filename="blocked_preflight.json",
                    input_content="需要重大判断",
                    major_ambiguities=["missing_required_story_decision"],
                    ensure_preflight=False,
                )
            )
            self.assertEqual(code, 2, blocked)
        with mock.patch.dict(
            os.environ,
            {"AI_DIRECTOR_ENVIRONMENT_REVISION": "env-b"},
            clear=False,
        ):
            code, rerun = self.run_cli(
                "startup-preflight",
                str(self.project),
                "--run-id",
                "RUN-TEST-001",
                "--mode",
                "production",
            )
        self.assertEqual(code, 0, rerun)
        self.assertEqual(rerun["rerun_reason"], "environment_changed")
        self.assertEqual(rerun["status"], "blocked")
        code, runtime = self.run_cli("show-agent-runtime", str(self.project))
        self.assertEqual(code, 0, runtime)
        self.assertEqual(runtime["execution_control"]["status"], "blocked")
        self.assertIsNotNone(runtime["execution_control"]["active_blocker"])

    def test_resolving_blocker_reactivates_paused_task_from_checkpoint(self) -> None:
        self.init_project()
        code, first = self.run_cli(
            *self.agent_task_args(
                host_task_id="HOST-PAUSED-001",
                active_host_task_ids=["HOST-PAUSED-001"],
            )
        )
        self.assertEqual(code, 0, first)
        code, blocked = self.run_cli(
            *self.agent_task_args(
                input_filename="recovery_blocker.json",
                input_content="需要重大判断",
                major_ambiguities=["missing_required_story_decision"],
                active_host_task_ids=["HOST-PAUSED-001"],
            )
        )
        self.assertEqual(code, 2, blocked)
        code, runtime = self.run_cli("show-agent-runtime", str(self.project))
        self.assertEqual(code, 0, runtime)
        blocker_id = runtime["execution_control"]["active_blocker"]["blocker_id"]

        code, resolved = self.run_cli(
            "startup-preflight",
            str(self.project),
            "--run-id",
            "RUN-TEST-001",
            "--mode",
            "production",
            "--resolve-blocker-id",
            blocker_id,
            "--resolution-note",
            "必需决策已经补齐",
        )
        self.assertEqual(code, 0, resolved)
        self.assertEqual(resolved["status"], "execution_ready")
        self.assertEqual(resolved["resumed_task_ids"], [first["task_id"]])
        code, resumed_runtime = self.run_cli(
            "show-agent-runtime", str(self.project)
        )
        self.assertEqual(code, 0, resumed_runtime)
        self.assertEqual(resumed_runtime["run"]["status"], "running")
        self.assertEqual(
            resumed_runtime["run"]["active_task_ids"], [first["task_id"]]
        )
        self.assertEqual(resumed_runtime["agent_runtime"]["status"], "running")
        self.assertEqual(
            resumed_runtime["agent_runtime"]["active_task_ids"],
            [first["task_id"]],
        )

        paused_task = json.loads(
            (self.project / first["task_path"]).read_text(encoding="utf-8")
        )
        self.assertEqual(paused_task["status"], "planned")
        self.assertEqual(paused_task["host_task_status"], "unbound")
        self.assertEqual(paused_task["recovery_state"], "none")
        checkpoint_path = self.project / paused_task["last_checkpoint_path"]
        self.assertTrue(checkpoint_path.is_file())
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        self.assertEqual(checkpoint["status"], "recovery_required")

        code, resumed = self.run_cli(
            *self.agent_task_args(
                host_task_id="HOST-RESUMED-001",
                active_host_task_ids=["HOST-RESUMED-001"],
                delegation_directive=None,
                ensure_preflight=False,
            )
        )
        self.assertEqual(code, 0, resumed)
        self.assertTrue(resumed["reused"])
        self.assertEqual(resumed["task_id"], first["task_id"])
        self.assertEqual(resumed["reuse_reason"], "active_host_task_reused")
        self.assertEqual(resumed["checkpoint_path"], paused_task["last_checkpoint_path"])

    def test_failed_preflight_does_not_resolve_blocker_or_resume_tasks(self) -> None:
        self.init_project()
        code, first = self.run_cli(
            *self.agent_task_args(
                host_task_id="HOST-PREFLIGHT-FAILURE",
                active_host_task_ids=["HOST-PREFLIGHT-FAILURE"],
            )
        )
        self.assertEqual(code, 0, first)
        code, blocked = self.run_cli(
            *self.agent_task_args(
                input_filename="failed_preflight_blocker.json",
                input_content="需要重大判断",
                major_ambiguities=["missing_required_story_decision"],
                active_host_task_ids=["HOST-PREFLIGHT-FAILURE"],
            )
        )
        self.assertEqual(code, 2, blocked)
        code, runtime = self.run_cli("show-agent-runtime", str(self.project))
        self.assertEqual(code, 0, runtime)
        blocker_id = runtime["execution_control"]["active_blocker"]["blocker_id"]

        with mock.patch.dict(
            os.environ,
            {"AI_DIRECTOR_ENVIRONMENT_REVISION": "invalid-environment"},
            clear=False,
        ), mock.patch.object(
            project_tool.agent_runtime,
            "PLUGIN_VERSION",
            "0.8.90",
        ):
            code, failed = self.run_cli(
                "startup-preflight",
                str(self.project),
                "--run-id",
                "RUN-TEST-001",
                "--mode",
                "production",
                "--resolve-blocker-id",
                blocker_id,
                "--resolution-note",
                "尝试修复但环境仍无效",
            )
        self.assertEqual(code, 2, failed)
        self.assertIn("startup_preflight_environment_invalid", failed["error"])

        blocked_task = json.loads(
            (self.project / first["task_path"]).read_text(encoding="utf-8")
        )
        self.assertEqual(blocked_task["status"], "paused")
        code, after = self.run_cli("show-agent-runtime", str(self.project))
        self.assertEqual(code, 0, after)
        self.assertEqual(
            after["execution_control"]["active_blocker"]["blocker_id"],
            blocker_id,
        )
        self.assertEqual(after["execution_control"]["status"], "blocked")

    def test_repeated_accept_invalidates_missing_accepted_output(self) -> None:
        self.init_project()
        arguments = self.agent_task_args()
        code, planned = self.run_cli(*arguments)
        self.assertEqual(code, 0, planned)
        task = json.loads(
            (self.project / planned["task_path"]).read_text(encoding="utf-8")
        )
        candidate = (
            self.project / task["allowed_write_directory"] / "analysis.json"
        )
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_text('{"events":[]}', encoding="utf-8")
        result = self.write_agent_result(
            task,
            candidate_output_paths=[
                candidate.relative_to(self.project).as_posix()
            ],
        )
        code, accepted = self.run_cli(
            "accept-agent-result",
            str(self.project),
            "--task-id",
            task["task_id"],
            "--result",
            str(result),
        )
        self.assertEqual(code, 0, accepted)
        candidate.unlink()

        code, rejected = self.run_cli(
            "accept-agent-result",
            str(self.project),
            "--task-id",
            task["task_id"],
            "--result",
            str(result),
        )
        self.assertEqual(code, 2, rejected)
        self.assertIn("accepted_result_invalidated", rejected["error"])
        invalidated = json.loads(
            (self.project / planned["task_path"]).read_text(encoding="utf-8")
        )
        self.assertEqual(invalidated["status"], "invalidated")

        code, replanned = self.run_cli(*arguments)
        self.assertEqual(code, 0, replanned)
        self.assertEqual(replanned["attempt"], 2)
        self.assertEqual(replanned["idempotency_key"], task["idempotency_key"])

    def write_agent_result(
        self,
        task: dict,
        *,
        status: str = "completed",
        candidate_output_paths: list[str] | None = None,
        error_code: str | None = None,
        telemetry: dict | None = None,
    ) -> Path:
        result_path = self.project / "tmp" / f"{task['task_id']}-worker-result.json"
        payload = {
            "schema_version": 1,
            "task_id": task["task_id"],
            "idempotency_key": task["idempotency_key"],
            "status": status,
            "candidate_output_paths": candidate_output_paths or [],
            "error_code": error_code,
            "telemetry": telemetry
            or {
                "machine_time_seconds": 1.0,
                "model_time_seconds": 2.0,
                "agent_time_seconds": 3.0,
                "human_wait_seconds": 4.0,
                "reconnect_wait_seconds": 5.0,
                "error_class": "none" if status == "completed" else error_code,
            },
        }
        return self.write_project_file(
            result_path.relative_to(self.project).as_posix(),
            json.dumps(payload, ensure_ascii=False),
        )

    def test_write_agent_result_cli_builds_valid_envelope(self) -> None:
        self.init_project()
        code, planned = self.run_cli(*self.agent_task_args())
        self.assertEqual(code, 0, planned)
        task = json.loads(
            (self.project / planned["task_path"]).read_text(encoding="utf-8")
        )
        candidate = (
            self.project / task["allowed_write_directory"] / "analysis.json"
        )
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_text('{"events":[]}\n', encoding="utf-8")
        candidate_relative = candidate.relative_to(self.project).as_posix()

        code, payload = self.run_cli(
            "write-agent-result",
            str(self.project),
            "--task-id",
            task["task_id"],
            "--status",
            "completed",
            "--candidate-output",
            candidate_relative,
            "--machine-time-seconds",
            "1.25",
        )
        self.assertEqual(code, 0, payload)
        result_path = self.project / payload["result_path"]
        self.assertTrue(result_path.is_file())
        result = json.loads(result_path.read_text(encoding="utf-8"))
        self.assertEqual(
            project_tool.agent_runtime.validate_result_envelope(
                task, result, self.project
            ),
            [],
        )
        self.assertEqual(
            set(result["telemetry"]),
            {*project_tool.agent_runtime.TIMING_FIELDS, "error_class"},
        )
        self.assertEqual(result["telemetry"]["machine_time_seconds"], 1.25)
        self.assertEqual(result["telemetry"]["error_class"], "none")

        code, accepted = self.run_cli(
            "accept-agent-result",
            str(self.project),
            "--task-id",
            task["task_id"],
            "--result",
            str(result_path),
        )
        self.assertEqual(code, 0, accepted)
        self.assertEqual(accepted["status"], "accepted")

    def test_plan_agent_slice_freezes_context_and_reuses_completed_result(self) -> None:
        self.init_project()
        arguments = self.agent_task_args()
        code, payload = self.run_cli(*arguments)
        self.assertEqual(code, 0, payload)
        self.assertFalse(payload["reused"])
        task_path = self.project / payload["task_path"]
        task = json.loads(task_path.read_text(encoding="utf-8"))
        self.assertEqual(task["context_inheritance"], "none")
        self.assertEqual(task["max_parallel_tasks"], 2)
        self.assertTrue(task["single_state_writer"])
        self.assertEqual(task["state_write_policy"], "supervisor_only")
        self.assertEqual(task["supervisor_mode"], "single_layer_host")
        self.assertIsNone(task["host_task_id"])
        self.assertEqual(task["attempt"], 1)
        self.assertTrue(task["input_refs"][0]["sha256"])
        candidate_dir = self.project / task["allowed_write_directory"]
        candidate = candidate_dir / "analysis.json"
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_text(json.dumps({"events": []}), encoding="utf-8")
        result_path = self.write_agent_result(
            task,
            candidate_output_paths=[
                candidate.relative_to(self.project).as_posix()
            ],
        )
        code, accepted = self.run_cli(
            "accept-agent-result",
            str(self.project),
            "--task-id",
            task["task_id"],
            "--result",
            str(result_path),
        )
        self.assertEqual(code, 0, accepted)
        self.assertEqual(accepted["status"], "accepted")

        code, reused = self.run_cli(*arguments)
        self.assertEqual(code, 0, reused)
        self.assertTrue(reused["reused"])
        self.assertEqual(reused["task_id"], task["task_id"])
        self.assertEqual(
            len(list((self.project / ".ai-director/runtime/tasks").glob("*.json"))),
            1,
        )

    def test_accept_agent_result_rejects_candidate_outside_frozen_write_scope(self) -> None:
        self.init_project()
        code, payload = self.run_cli(*self.agent_task_args())
        self.assertEqual(code, 0, payload)
        task = json.loads(
            (self.project / payload["task_path"]).read_text(encoding="utf-8")
        )
        outside = self.write_project_file("tmp/outside.json", '{"events":[]}')
        result_path = self.write_agent_result(
            task,
            candidate_output_paths=[outside.relative_to(self.project).as_posix()],
        )
        code, rejected = self.run_cli(
            "accept-agent-result",
            str(self.project),
            "--task-id",
            task["task_id"],
            "--result",
            str(result_path),
        )
        self.assertEqual(code, 2, rejected)
        self.assertIn("candidate_output_path_forbidden", rejected["error"])
        blocked_task = json.loads(
            (self.project / payload["task_path"]).read_text(encoding="utf-8")
        )
        self.assertEqual(blocked_task["status"], "acceptance_failed")
        code, runtime = self.run_cli("show-agent-runtime", str(self.project))
        self.assertEqual(code, 0, runtime)
        self.assertEqual(
            runtime["execution_control"]["active_blocker"]["severity"],
            "acceptance_failure",
        )

    def test_agent_task_stops_after_two_failures_and_writes_checkpoint(self) -> None:
        self.init_project()
        arguments = self.agent_task_args()
        code, payload = self.run_cli(*arguments)
        self.assertEqual(code, 0, payload)
        task1 = json.loads(
            (self.project / payload["task_path"]).read_text(encoding="utf-8")
        )
        result1 = self.write_agent_result(
            task1,
            status="failed",
            error_code="429_too_many_requests",
        )
        code, failed1 = self.run_cli(
            "accept-agent-result",
            str(self.project),
            "--task-id",
            task1["task_id"],
            "--result",
            str(result1),
        )
        self.assertEqual(code, 0, failed1)
        self.assertEqual(failed1["status"], "retryable")
        self.assertEqual(failed1["next_attempt"], 2)

        code, payload = self.run_cli(*arguments)
        self.assertEqual(code, 0, payload)
        self.assertFalse(payload["reused"])
        task2 = json.loads(
            (self.project / payload["task_path"]).read_text(encoding="utf-8")
        )
        self.assertEqual(task2["attempt"], 2)
        self.assertEqual(task2["idempotency_key"], task1["idempotency_key"])
        result2 = self.write_agent_result(
            task2,
            status="failed",
            error_code="stream_disconnect_without_completion",
        )
        code, failed2 = self.run_cli(
            "accept-agent-result",
            str(self.project),
            "--task-id",
            task2["task_id"],
            "--result",
            str(result2),
        )
        self.assertEqual(code, 0, failed2)
        self.assertEqual(failed2["status"], "blocked")
        self.assertTrue(failed2["checkpoint_path"])
        self.assertTrue((self.project / failed2["checkpoint_path"]).is_file())
        code, runtime = self.run_cli("show-agent-runtime", str(self.project))
        self.assertEqual(code, 0, runtime)
        self.assertEqual(runtime["run"]["active_task_ids"], [])
        self.assertEqual(runtime["agent_runtime"]["active_task_ids"], [])
        self.assertEqual(runtime["execution_control"]["status"], "blocked")
        self.assertEqual(
            runtime["execution_control"]["active_blocker"]["severity"],
            "execution_failure",
        )

        code, blocked = self.run_cli(*arguments)
        self.assertEqual(code, 2, blocked)
        self.assertIn("active_execution_blocker", blocked["error"])

    def test_accept_agent_result_registers_one_artifact_and_separates_runtime_timing(self) -> None:
        self.init_project()
        arguments = self.agent_task_args(
            task_type="episode_script",
            acceptance_command="validate-script",
            artifact_key="episode_script:E001",
        )
        code, payload = self.run_cli(*arguments)
        self.assertEqual(code, 0, payload)
        task = json.loads(
            (self.project / payload["task_path"]).read_text(encoding="utf-8")
        )
        candidate_dir = self.project / task["allowed_write_directory"]
        candidate = candidate_dir / "E001.md"
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_text(GOOD_SCRIPT, encoding="utf-8")
        result_path = self.write_agent_result(
            task,
            candidate_output_paths=[
                candidate.relative_to(self.project).as_posix()
            ],
        )
        code, accepted = self.run_cli(
            "accept-agent-result",
            str(self.project),
            "--task-id",
            task["task_id"],
            "--result",
            str(result_path),
            "--artifact-key",
            "episode_script:E001",
            "--artifact-status",
            "awaiting_approval",
        )
        self.assertEqual(code, 0, accepted)
        self.assertEqual(accepted["registered_artifact"]["version"], 1)

        runtime = self.state()["agent_runtime"]
        self.assertEqual(
            set(runtime["timing_totals"]),
            {
                "machine_time_seconds",
                "model_time_seconds",
                "agent_time_seconds",
                "human_wait_seconds",
                "reconnect_wait_seconds",
            },
        )
        self.assertEqual(
            runtime["error_counts"],
            {},
        )

        code, reused = self.run_cli(
            "accept-agent-result",
            str(self.project),
            "--task-id",
            task["task_id"],
            "--result",
            str(result_path),
            "--artifact-key",
            "episode_script:E001",
            "--artifact-status",
            "awaiting_approval",
        )
        self.assertEqual(code, 0, reused)
        self.assertTrue(reused["reused"])
        self.assertEqual(len(self.state()["artifacts"]["episode_script:E001"]), 1)

    def test_accept_agent_result_clears_completed_host_task(self) -> None:
        self.init_project()
        arguments = self.agent_task_args()
        code, planned = self.run_cli(*arguments)
        self.assertEqual(code, 0, planned)
        code, bound = self.run_cli(
            *self.agent_task_args(
                host_task_id="HOST-WORKER-COMPLETE",
                active_host_task_ids=["HOST-WORKER-COMPLETE"],
            )
        )
        self.assertEqual(code, 0, bound)
        task = json.loads(
            (self.project / planned["task_path"]).read_text(encoding="utf-8")
        )
        candidate = (
            self.project / task["allowed_write_directory"] / "analysis.json"
        )
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_text('{"events":[]}', encoding="utf-8")
        result = self.write_agent_result(
            task,
            candidate_output_paths=[
                candidate.relative_to(self.project).as_posix()
            ],
        )
        code, accepted = self.run_cli(
            "accept-agent-result",
            str(self.project),
            "--task-id",
            task["task_id"],
            "--result",
            str(result),
        )
        self.assertEqual(code, 0, accepted)
        code, runtime = self.run_cli(
            "show-agent-runtime",
            str(self.project),
        )
        self.assertEqual(code, 0, runtime)
        self.assertEqual(runtime["run"]["active_host_task_ids"], [])
        self.assertEqual(runtime["agent_runtime"]["active_host_task_ids"], [])
        self.assertEqual(runtime["run"]["status"], "completed")
        self.assertEqual(runtime["agent_runtime"]["status"], "completed")
        self.assertEqual(
            runtime["execution_control"]["status"],
            "execution_ready",
        )

    def test_plan_agent_slice_distinguishes_independent_tasks_and_serial_conflicts(self) -> None:
        self.init_project()
        first_args = self.agent_task_args(
            scope={"batch_id": "B01", "episode_id": "E001", "source_unit_id": "SU001"},
            scheduling_mode="independent",
            max_parallel_tasks=4,
            service_capacity=3,
        )
        code, first = self.run_cli(*first_args)
        self.assertEqual(code, 0, first)
        self.assertEqual(first["effective_parallel_limit"], 3)
        code, first_bound = self.run_cli(
            *self.agent_task_args(
                scope={"batch_id": "B01", "episode_id": "E001", "source_unit_id": "SU001"},
                scheduling_mode="independent",
                max_parallel_tasks=4,
                service_capacity=3,
                host_task_id="HOST-WORKER-001",
                active_host_task_ids=["HOST-WORKER-001"],
            )
        )
        self.assertEqual(code, 0, first_bound)
        self.assertEqual(first_bound["reuse_reason"], "active_host_task_reused")

        second_args = self.agent_task_args(
            scope={"batch_id": "B01", "episode_id": "E001", "source_unit_id": "SU002"},
            input_filename="agent_input_2.json",
            scheduling_mode="independent",
            max_parallel_tasks=4,
            service_capacity=3,
            active_host_task_ids=["HOST-WORKER-001"],
        )
        code, second = self.run_cli(*second_args)
        self.assertEqual(code, 0, second)
        self.assertFalse(second["reused"])
        self.assertEqual(second["active_task_count"], 2)
        code, second_bound = self.run_cli(
            *self.agent_task_args(
                scope={"batch_id": "B01", "episode_id": "E001", "source_unit_id": "SU002"},
                input_filename="agent_input_2.json",
                scheduling_mode="independent",
                max_parallel_tasks=4,
                service_capacity=3,
                host_task_id="HOST-WORKER-002",
                active_host_task_ids=["HOST-WORKER-001", "HOST-WORKER-002"],
            )
        )
        self.assertEqual(code, 0, second_bound)

        serial_args = self.agent_task_args(
            scope={"batch_id": "B01", "episode_id": "E001", "source_unit_id": "SU003"},
            input_filename="agent_input_3.json",
            scheduling_mode="serial",
            active_host_task_ids=["HOST-WORKER-001", "HOST-WORKER-002"],
        )
        code, rejected = self.run_cli(*serial_args)
        self.assertEqual(code, 2, rejected)
        self.assertIn("serial_task_conflict", rejected["error"])

    def test_plan_agent_slice_reuses_unexpired_hostless_lease(self) -> None:
        self.init_project()
        arguments = self.agent_task_args()
        code, first = self.run_cli(*arguments)
        self.assertEqual(code, 0, first)

        code, reused = self.run_cli(*arguments)
        self.assertEqual(code, 0, reused)
        self.assertTrue(reused["reused"])
        self.assertEqual(reused["reuse_reason"], "active_planned_task_reused")
        self.assertEqual(reused["status"], "planned")
        self.assertEqual(reused["attempt"], 1)
        self.assertEqual(reused["task_id"], first["task_id"])
        self.assertEqual(
            len(list((self.project / ".ai-director/runtime/tasks").glob("*.json"))),
            1,
        )

    def test_plan_agent_slice_recovers_expired_hostless_lease_once(self) -> None:
        self.init_project()
        arguments = self.agent_task_args()
        code, first = self.run_cli(*arguments)
        self.assertEqual(code, 0, first)
        first_path = self.project / first["task_path"]
        task1 = json.loads(first_path.read_text(encoding="utf-8"))
        task1["activity_lease_expires_at"] = "2000-01-01T00:00:00+00:00"
        first_path.write_text(
            json.dumps(task1, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        code, recovered = self.run_cli(*arguments)
        self.assertEqual(code, 0, recovered)
        self.assertFalse(recovered["reused"])
        self.assertEqual(recovered["attempt"], 2)
        self.assertEqual(recovered["idempotency_key"], first["idempotency_key"])
        self.assertEqual(recovered["recovered_from_task_id"], first["task_id"])
        self.assertTrue((self.project / recovered["checkpoint_path"]).is_file())

        abandoned = json.loads(first_path.read_text(encoding="utf-8"))
        self.assertEqual(abandoned["status"], "abandoned")
        self.assertEqual(abandoned["recovery_state"], "recovery_required")

    def test_plan_agent_slice_blocks_after_two_expired_hostless_leases(self) -> None:
        self.init_project()
        arguments = self.agent_task_args()
        code, first = self.run_cli(*arguments)
        self.assertEqual(code, 0, first)
        first_path = self.project / first["task_path"]
        task1 = json.loads(first_path.read_text(encoding="utf-8"))
        task1["activity_lease_expires_at"] = "2000-01-01T00:00:00+00:00"
        first_path.write_text(
            json.dumps(task1, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        code, second = self.run_cli(*arguments)
        self.assertEqual(code, 0, second)
        self.assertEqual(second["attempt"], 2)
        second_path = self.project / second["task_path"]
        task2 = json.loads(second_path.read_text(encoding="utf-8"))
        task2["activity_lease_expires_at"] = "2000-01-01T00:00:00+00:00"
        second_path.write_text(
            json.dumps(task2, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        code, blocked = self.run_cli(*arguments)
        self.assertEqual(code, 2, blocked)
        self.assertIn("two_abandoned_attempts_blocked", blocked["error"])
        self.assertEqual(
            len(list((self.project / ".ai-director/runtime/tasks").glob("*.json"))),
            2,
        )
        blocked_task = json.loads(second_path.read_text(encoding="utf-8"))
        self.assertEqual(blocked_task["status"], "blocked")
        self.assertEqual(blocked_task["recovery_state"], "blocked")

    def test_plan_agent_slice_recovers_hostless_active_task_once(self) -> None:
        self.init_project()
        arguments = self.agent_task_args()
        code, first = self.run_cli(*arguments)
        self.assertEqual(code, 0, first)
        task1_path = self.project / first["task_path"]

        code, bound = self.run_cli(
            *self.agent_task_args(
                host_task_id="HOST-WORKER-001",
                active_host_task_ids=["HOST-WORKER-001"],
            )
        )
        self.assertEqual(code, 0, bound)
        self.assertTrue(bound["reused"])
        self.assertEqual(bound["reuse_reason"], "active_host_task_reused")
        self.assertEqual(bound["host_task_id"], "HOST-WORKER-001")

        code, recovered = self.run_cli(*arguments)
        self.assertEqual(code, 0, recovered)
        self.assertFalse(recovered["reused"])
        self.assertEqual(recovered["attempt"], 2)
        self.assertEqual(recovered["recovered_from_task_id"], first["task_id"])
        self.assertTrue((self.project / recovered["checkpoint_path"]).is_file())

        task1 = json.loads(task1_path.read_text(encoding="utf-8"))
        self.assertEqual(task1["status"], "abandoned")
        self.assertEqual(task1["recovery_state"], "recovery_required")
        checkpoint = json.loads(
            (self.project / recovered["checkpoint_path"]).read_text(encoding="utf-8")
        )
        self.assertEqual(checkpoint["status"], "recovery_required")
        self.assertEqual(recovered["idempotency_key"], first["idempotency_key"])

    def test_plan_agent_slice_blocks_after_two_hostless_attempts(self) -> None:
        self.init_project()
        arguments = self.agent_task_args()
        code, first = self.run_cli(*arguments)
        self.assertEqual(code, 0, first)
        code, _bound1 = self.run_cli(
            *self.agent_task_args(
                host_task_id="HOST-WORKER-001",
                active_host_task_ids=["HOST-WORKER-001"],
            )
        )
        self.assertEqual(code, 0, _bound1)
        code, second = self.run_cli(*arguments)
        self.assertEqual(code, 0, second)
        self.assertEqual(second["attempt"], 2)
        code, _bound2 = self.run_cli(
            *self.agent_task_args(
                host_task_id="HOST-WORKER-002",
                active_host_task_ids=["HOST-WORKER-002"],
            )
        )
        self.assertEqual(code, 0, _bound2)

        code, blocked = self.run_cli(*arguments)
        self.assertEqual(code, 2, blocked)
        self.assertIn("two_abandoned_attempts_blocked", blocked["error"])
        task2 = json.loads(
            (self.project / second["task_path"]).read_text(encoding="utf-8")
        )
        self.assertEqual(task2["status"], "blocked")
        self.assertEqual(task2["recovery_state"], "blocked")
        code, runtime = self.run_cli("show-agent-runtime", str(self.project))
        self.assertEqual(code, 0, runtime)
        self.assertEqual(runtime["run"]["active_task_ids"], [])
        self.assertEqual(runtime["agent_runtime"]["active_task_ids"], [])
        self.assertEqual(runtime["execution_control"]["status"], "blocked")
        self.assertEqual(
            runtime["execution_control"]["active_blocker"]["severity"],
            "host_task_lost",
        )
        code, unrelated = self.run_cli(
            *self.agent_task_args(
                input_filename="after_host_loss.json",
                input_content="阻断后不应继续",
            )
        )
        self.assertEqual(code, 2, unrelated)
        self.assertIn("active_execution_blocker", unrelated["error"])

    def test_startup_preflight_migrates_v089_completed_task_without_regeneration(self) -> None:
        self.init_project()
        input_path = self.write_project_file(
            "01_原著解析/legacy_input.json",
            json.dumps(
                {"source_unit_id": "SU001", "content": "冻结输入"},
                ensure_ascii=False,
            ),
        )
        input_ref = {
            "artifact_key": "source_corpus",
            "version": 1,
            "path": input_path.relative_to(self.project).as_posix(),
            "sha256": project_tool.sha256_file(input_path),
        }
        scope = {"batch_id": "B01", "episode_id": "E001"}
        legacy_key = project_tool.agent_runtime.canonical_sha256(
            {
                "task_type": "episode_script",
                "scope": scope,
                "input_refs": [
                    {
                        "artifact_key": input_ref["artifact_key"],
                        "version": input_ref["version"],
                        "sha256": input_ref["sha256"],
                    }
                ],
                "contract_version": 1,
            }
        )
        task_id = project_tool.agent_runtime.task_id_for(legacy_key, 1)
        write_directory = (
            f"{project_tool.agent_runtime.RUNTIME_DIRECTORY}/candidates/{task_id}"
        )
        candidate = self.write_project_file(
            f"{write_directory}/analysis.json",
            '{"events":[]}',
        )
        legacy_task = {
            "schema_version": 1,
            "run_id": "RUN-TEST-001",
            "task_id": task_id,
            "task_type": "episode_script",
            "scope": scope,
            "attempt": 1,
            "max_attempts": 2,
            "idempotency_key": legacy_key,
            "contract_version": 1,
            "input_refs": [input_ref],
            "allowed_read_paths": [input_ref["path"]],
            "allowed_write_directory": write_directory,
            "acceptance_command": "schema-only",
            "artifact_key": None,
            "return_max_chars": 1000,
            "context_inheritance": "none",
            "max_parallel_tasks": 2,
            "effective_parallel_limit": 2,
            "service_capacity": 2,
            "scheduling_mode": "independent",
            "scheduling_key": project_tool.agent_runtime.canonical_sha256(scope),
            "single_state_writer": True,
            "state_write_policy": "supervisor_only",
            "supervisor_mode": "single_layer_host",
            "coordinator_slice": "source_window",
            "host_task_id": None,
            "host_task_status": "completed",
            "recovery_state": "none",
            "status": "accepted",
            "created_at": project_tool.now_iso(),
        }
        task_path = project_tool.agent_runtime.task_path_for(self.project, task_id)
        project_tool.agent_runtime.atomic_write_json(task_path, legacy_task)
        legacy_result = project_tool.agent_runtime.build_result_envelope(
            task_id=task_id,
            idempotency_key=legacy_key,
            status="completed",
            candidate_output_paths=[
                candidate.relative_to(self.project).as_posix()
            ],
            telemetry={
                "machine_time_seconds": 0,
                "model_time_seconds": 0,
                "agent_time_seconds": 0,
                "human_wait_seconds": 0,
                "reconnect_wait_seconds": 0,
                "error_class": "none",
            },
        )
        project_tool.agent_runtime.atomic_write_json(
            project_tool.agent_runtime.result_path_for(self.project, task_id),
            legacy_result,
        )

        preflight = self.ensure_production_preflight()
        self.assertEqual(preflight["legacy_tasks_migrated"], 1)
        migrated = json.loads(task_path.read_text(encoding="utf-8"))
        self.assertEqual(migrated["legacy_idempotency_key"], legacy_key)
        self.assertIn("decision_identity", migrated)
        self.assertTrue(migrated["accepted_outputs"])

        code, reused = self.run_cli(
            *self.agent_task_args(
                task_type="episode_script",
                scope=scope,
                input_filename="legacy_input.json",
                stage="batch_writing",
                delegation_directive="继续执行",
                ensure_preflight=False,
            )
        )
        self.assertEqual(code, 0, reused)
        self.assertTrue(reused["reused"])
        self.assertEqual(reused["reuse_reason"], "completed_result_reused")
        self.assertEqual(reused["task_id"], task_id)
        self.assertEqual(
            len(list((self.project / ".ai-director/runtime/tasks").glob("*.json"))),
            1,
        )

    def test_accept_agent_result_rejects_abandoned_older_attempt(self) -> None:
        self.init_project()
        arguments = self.agent_task_args()
        code, first = self.run_cli(*arguments)
        self.assertEqual(code, 0, first)
        code, _bound = self.run_cli(
            *self.agent_task_args(
                host_task_id="HOST-WORKER-001",
                active_host_task_ids=["HOST-WORKER-001"],
            )
        )
        self.assertEqual(code, 0, _bound)
        code, second = self.run_cli(*arguments)
        self.assertEqual(code, 0, second)

        task1 = json.loads(
            (self.project / first["task_path"]).read_text(encoding="utf-8")
        )
        old_candidate = (
            self.project / task1["allowed_write_directory"] / "late-analysis.json"
        )
        old_candidate.parent.mkdir(parents=True, exist_ok=True)
        old_candidate.write_text('{"events":[]}', encoding="utf-8")
        old_result = self.write_agent_result(
            task1,
            candidate_output_paths=[
                old_candidate.relative_to(self.project).as_posix()
            ],
        )
        code, rejected = self.run_cli(
            "accept-agent-result",
            str(self.project),
            "--task-id",
            task1["task_id"],
            "--result",
            str(old_result),
        )
        self.assertEqual(code, 2, rejected)
        self.assertIn("stale_attempt_result_rejected", rejected["error"])
        self.assertFalse(
            project_tool.agent_runtime.result_path_for(
                self.project, task1["task_id"]
            ).exists()
        )

        task2 = json.loads(
            (self.project / second["task_path"]).read_text(encoding="utf-8")
        )
        new_candidate = (
            self.project / task2["allowed_write_directory"] / "analysis.json"
        )
        new_candidate.parent.mkdir(parents=True, exist_ok=True)
        new_candidate.write_text('{"events":[]}', encoding="utf-8")
        new_result = self.write_agent_result(
            task2,
            candidate_output_paths=[
                new_candidate.relative_to(self.project).as_posix()
            ],
        )
        code, accepted = self.run_cli(
            "accept-agent-result",
            str(self.project),
            "--task-id",
            task2["task_id"],
            "--result",
            str(new_result),
        )
        self.assertEqual(code, 0, accepted)
        self.assertEqual(accepted["status"], "accepted")

    def test_startup_preflight_runs_minimum_flow_without_model_or_novel_name(self) -> None:
        self.init_project()
        code, payload = self.run_cli(
            "startup-preflight",
            str(self.project),
            "--run-id",
            "RUN-PREFLIGHT-001",
        )
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["status"], "execution_ready")
        self.assertFalse(payload["reused"])
        self.assertEqual(payload["execution_mode"], "production")
        self.assertEqual(
            payload["flow"],
            [
                "state_read",
                "runtime_directories",
                "state_lock",
                "command_contracts",
                "execution_mode_lock",
                "environment_fingerprint",
            ],
        )
        self.assertTrue(
            (self.project / ".ai-director/runtime/tasks").is_dir()
        )
        self.assertNotIn("测试项目", payload["run_scope"])

    def test_error_recovery_policy_keeps_429_stream_and_context_distinct(self) -> None:
        runtime = project_tool.agent_runtime
        self.assertEqual(
            runtime.recovery_policy_for("429_too_many_requests")["action"],
            "rate_limit_backoff",
        )
        self.assertEqual(
            runtime.recovery_policy_for("stream_disconnect_without_completion")["action"],
            "fresh_agent_reconnect",
        )
        self.assertEqual(
            runtime.recovery_policy_for("context_window_exceeded")["action"],
            "fresh_agent_reduced_context",
        )

    def test_project_state_lock_is_reentrant_for_single_writer_helpers(self) -> None:
        self.init_project()
        with project_tool.agent_runtime.project_state_write_lock(self.project):
            with project_tool.agent_runtime.project_state_write_lock(self.project):
                self.assertTrue((self.project / project_tool.STATE_FILENAME).is_file())

    def test_operator_brief_recommends_continuing_a_clean_project(self) -> None:
        self.init_project()
        code, payload = self.run_cli(
            "operator-brief", str(self.project)
        )
        self.assertEqual(code, 0, payload)
        self.assertEqual(payload["schema_version"], 1)
        self.assertTrue(payload["readiness"]["state_valid"])
        self.assertFalse(payload["readiness"]["execution_blocked"])
        self.assertEqual(
            payload["recommended_action"]["kind"],
            "continue_current_stage",
        )
        self.assertEqual(payload["current_stage"]["key"], "project_setup")
        self.assertEqual(payload["counts"]["source_count"], 1)
        self.assertEqual(payload["counts"]["artifact_key_count"], 0)

    def test_operator_brief_prioritizes_stale_and_approval_attention(self) -> None:
        self.init_project()
        brief_file = self.write_project_file(
            "01_原著解析/project_spec_candidate.json",
            json.dumps({"expected_episodes": 1}, ensure_ascii=False),
        )
        code, registered = self.run_cli(
            "register-artifact",
            str(self.project),
            "project_spec",
            str(brief_file),
            "--status",
            "awaiting_approval",
        )
        self.assertEqual(code, 0, registered)

        code, brief = self.run_cli("operator-brief", str(self.project))
        self.assertEqual(code, 0, brief)
        self.assertEqual(
            brief["recommended_action"]["kind"], "review_artifact"
        )
        self.assertEqual(
            brief["recommended_action"]["target"], "project_spec"
        )
        self.assertEqual(
            brief["attention"]["awaiting_approval"][0]["version"], 1
        )
        self.assertTrue(brief["readiness"]["human_decision_required"])

        code, stale = self.run_cli(
            "mark-stale",
            str(self.project),
            "project_spec",
            "--reason",
            "上游需求发生变化",
        )
        self.assertEqual(code, 0, stale)
        code, brief = self.run_cli("operator-brief", str(self.project))
        self.assertEqual(code, 0, brief)
        self.assertEqual(
            brief["recommended_action"]["kind"],
            "refresh_stale_artifact",
        )
        self.assertEqual(brief["attention"]["stale_artifacts"][0]["version"], 1)
        self.assertEqual(
            brief["counts"]["artifact_statuses"]["stale"], 1
        )

    def test_isolated_minimum_workflow_closure_and_runtime_resume(self) -> None:
        self.create_ready_project()
        project_root = self.project.resolve()
        script_record = self.state()["artifacts"]["episode_script:E001"][-1]
        script_path = project_root / script_record["path"]

        validation = project_tool.validate_script_file(script_path)
        self.assertTrue(validation["valid"], validation)
        scenes, cues = project_tool.extract_script_index(
            script_path,
            "episode_script:E001",
        )
        self.assertEqual(len(scenes), 1)
        self.assertEqual(len(cues), 2)

        code, payload = self.run_cli(
            "validate-project", str(project_root)
        )
        self.assertEqual(code, 0, payload)
        code, payload = self.run_cli(
            "validate-breakdowns",
            str(project_root),
            "--expected-episodes",
            "1",
        )
        self.assertEqual(code, 0, payload)

        self.register_ai_layer_prerequisites()
        plan_version = self.register_artifact(
            "ai_shot_plan:E001",
            "10_AI视频执行包/E001_分镜计划_闭环.json",
            json.dumps(self.shot_plan_payload(), ensure_ascii=False),
            self.shot_plan_dependencies(),
        )
        self.approve_shot_plan_with_review(plan_version)
        self.run_production_preflight()
        code, delivery = self.run_cli(
            "render-episode-delivery",
            str(project_root),
            "E001",
        )
        self.assertEqual(code, 0, delivery)
        output_dir = project_root / "09_定稿交付/分集交付/E001"
        docx_path = output_dir / "E001_剧本.docx"
        html_path = output_dir / "E001_故事板.html"
        self.assertTrue(docx_path.is_file())
        self.assertTrue(html_path.is_file())
        self.assertEqual(docx_path.parent, output_dir)
        self.assertIn("景别：", html_path.read_text(encoding="utf-8"))

        first_args = self.agent_task_args(
            task_type="source_analysis",
            scope={"batch_id": "B01", "episode_id": "E001", "source_unit_id": "SU001"},
            input_filename="closure_input_1.json",
            scheduling_mode="independent",
        )
        code, first_plan = self.run_cli(*first_args)
        self.assertEqual(code, 0, first_plan)
        first_task = json.loads(
            (project_root / first_plan["task_path"]).read_text(encoding="utf-8")
        )
        code, first_bound = self.run_cli(
            *self.agent_task_args(
                task_type="source_analysis",
                scope={"batch_id": "B01", "episode_id": "E001", "source_unit_id": "SU001"},
                input_filename="closure_input_1.json",
                scheduling_mode="independent",
                host_task_id="HOST-CLOSURE-001",
                active_host_task_ids=["HOST-CLOSURE-001"],
            )
        )
        self.assertEqual(code, 0, first_bound)

        second_args = self.agent_task_args(
            task_type="source_analysis",
            scope={"batch_id": "B01", "episode_id": "E001", "source_unit_id": "SU002"},
            input_filename="closure_input_2.json",
            scheduling_mode="independent",
            active_host_task_ids=["HOST-CLOSURE-001"],
        )
        code, second_plan = self.run_cli(*second_args)
        self.assertEqual(code, 0, second_plan)
        self.assertEqual(second_plan["active_task_count"], 2)
        code, second_bound = self.run_cli(
            *self.agent_task_args(
                task_type="source_analysis",
                scope={"batch_id": "B01", "episode_id": "E001", "source_unit_id": "SU002"},
                input_filename="closure_input_2.json",
                scheduling_mode="independent",
                host_task_id="HOST-CLOSURE-002",
                active_host_task_ids=["HOST-CLOSURE-001", "HOST-CLOSURE-002"],
            )
        )
        self.assertEqual(code, 0, second_bound)

        candidate = (
            project_root / first_task["allowed_write_directory"] / "analysis.json"
        )
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_text('{"events":[]}\n', encoding="utf-8")
        result_path = self.write_agent_result(
            first_task,
            candidate_output_paths=[
                candidate.relative_to(project_root).as_posix()
            ],
        )
        code, accepted = self.run_cli(
            "accept-agent-result",
            str(project_root),
            "--task-id",
            first_task["task_id"],
            "--result",
            str(result_path),
        )
        self.assertEqual(code, 0, accepted)
        code, resumed = self.run_cli(
            *self.agent_task_args(
                task_type="source_analysis",
                scope={"batch_id": "B01", "episode_id": "E001", "source_unit_id": "SU001"},
                input_filename="closure_input_1.json",
                scheduling_mode="independent",
                active_host_task_ids=["HOST-CLOSURE-002"],
            )
        )
        self.assertEqual(code, 0, resumed)
        self.assertTrue(resumed["reused"])
        code, runtime = self.run_cli(
            "show-agent-runtime", str(project_root)
        )
        self.assertEqual(code, 0, runtime)
        self.assertEqual(runtime["run"]["active_task_ids"], [second_plan["task_id"]])



if __name__ == "__main__":
    unittest.main()
