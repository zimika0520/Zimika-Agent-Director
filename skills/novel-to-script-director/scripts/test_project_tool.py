#!/usr/bin/env python3
from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import tempfile
import unittest
import zipfile
from types import SimpleNamespace
from pathlib import Path


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
        with contextlib.redirect_stdout(output):
            code = project_tool.main(arguments)
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

    def create_ready_project(self, expected_episodes: int = 1) -> None:
        self.init_project()
        project_id = self.state()["project_id"]
        project_spec = {
            "schema_version": 1,
            "project_id": project_id,
            "expected_episodes": expected_episodes,
            "target_runtime": "按项目实读复核",
            "handoff_target": "可直接进入导演拆镜",
        }
        self.register_and_approve(
            "project_spec",
            "01_原著解析/项目规格V1.json",
            json.dumps(project_spec, ensure_ascii=False),
        )
        normalized_source = self.write_project_file(
            "01_原著解析/标准化正文_第001章.txt",
            "阿宁守住母亲留下的钥匙。\n",
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
            "schema_version": 1,
            "project_id": project_id,
            "generated_from": [{"artifact_key": "source_corpus", "version": 1}],
            "units": [
                {
                    "source_unit_id": "SRC-CH001",
                    "source_locator": "第1章",
                    "status": "ready",
                    "events": [
                        {
                            "event_id": "EV-0001",
                            "summary": "阿宁拒绝交出母亲留下的钥匙",
                            "participants": ["阿宁", "管家"],
                            "cause": "管家索要钥匙",
                            "action": "阿宁把钥匙藏到袖后并拒绝",
                            "outcome": "管家堵住院门",
                            "state_change": "钥匙仍由阿宁持有，冲突升级",
                            "source_refs": ["SRC-CH001"],
                        }
                    ],
                }
            ],
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
        cue_payload = {
            "schema_version": 1,
            "project_id": project_id,
            "generated_from": generated_from,
            "records": [
                {"cue_id": "Q001", "episode_id": "E001", "scene_id": "1-1", "speaker_id": "C002", "speaker_name": "管家", "type": "dialogue", "text": "把钥匙交出来。"},
                {"cue_id": "Q002", "episode_id": "E001", "scene_id": "1-1", "speaker_id": "C001", "speaker_name": "阿宁", "type": "dialogue", "text": "这是母亲留给我的。"},
            ],
        }
        versions: dict[str, int] = {}
        for key, relative, payload in (
            ("character_roster", "08_连续性与质检/角色提取表V1.json", character_payload),
            ("scene_catalog", "08_连续性与质检/场景提取表V1.json", scene_payload),
            ("prop_costume_ledger", "08_连续性与质检/道具服装台账V1.json", item_payload),
            ("dialogue_cue_sheet", "08_连续性与质检/台词声音表V1.json", cue_payload),
        ):
            versions[key] = self.register_and_approve(
                key,
                relative,
                json.dumps(payload, ensure_ascii=False),
                ("episode_script:E001@1", f"episode_boundary_review:E001@{episode_boundary_version}"),
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
            scoped_versions[artifact_kind] = self.register_and_approve(
                scoped_key,
                f"08_连续性与质检/{batch_id}_{artifact_kind}_V1.json",
                json.dumps(payload, ensure_ascii=False),
                episode_dependencies,
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
                    "decision_ids": ["AD-0001"],
                    "start_state": "阿宁持钥匙退到院门外",
                    "end_state": "管家当面索要钥匙",
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
                            "visual_action": "阿宁攥着钥匙退到门槛外，管家伸手阻拦。",
                            "dialogue_cue_ids": ["Q001"],
                            "sound": ["院门外环境声"],
                        }
                    ],
                    "prompt_text": "固定中景。阿宁攥着钥匙退到门槛外，管家伸手说：\"把钥匙交出来。\"",
                },
                {
                    "unit_id": "SD2-E001-U002",
                    "sequence": 2,
                    "scene_id": "1-1",
                    "duration_seconds": 8,
                    "source_refs": ["EV-0001"],
                    "decision_ids": ["AD-0001", "AD-AUTO-001"],
                    "start_state": "管家当面索要钥匙",
                    "end_state": "阿宁仍持钥匙，管家堵住院门",
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
                            "visual_action": "阿宁把钥匙藏到袖后，管家堵住院门。",
                            "dialogue_cue_ids": ["Q002"],
                            "sound": ["官差叩门声在场外响起"],
                        }
                    ],
                    "prompt_text": "缓慢推进。阿宁把钥匙藏到袖后说：\"这是母亲留给我的。\"管家堵住院门，场外响起叩门声。",
                },
            ],
        }

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
        plan["target_duration_seconds"] = 30
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

    # ------- AI 视频三层结构（模型能力档案 / AI分镜计划 / 执行计划） -------

    def register_ai_layer_prerequisites(self) -> None:
        self.register_and_approve(
            "style_anchor", "10_AI视频执行包/风格锚点V1.md", "# 风格锚点\n半写实国漫。\n",
            ("adaptation_bible@1",),
        )
        self.register_and_approve(
            "character_anchor:C001", "10_AI视频执行包/角色锚点_C001V1.md", "# 阿宁\n黑发少女，青布衫。\n",
            ("character_roster@1",),
        )
        self.register_and_approve(
            "character_anchor:C002", "10_AI视频执行包/角色锚点_C002V1.md", "# 管家\n灰袍老者。\n",
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
            {"character_id": "C001", "anchor_ref": {"artifact_key": "character_anchor:C001", "version": 1}, "appearance_lock": "黑发少女，青布衫", "wardrobe": "青布衫"},
            {"character_id": "C002", "anchor_ref": {"artifact_key": "character_anchor:C002", "version": 1}, "appearance_lock": "灰袍老者", "wardrobe": "灰袍"},
        ]
        return {
            "schema_version": 1,
            "project_id": self.state()["project_id"],
            "episode_id": "E001",
            "generated_from": [
                {"artifact_key": value.rsplit("@", 1)[0], "version": int(value.rsplit("@", 1)[1])}
                for value in self.shot_plan_dependencies()
            ],
            "hard_blocks": ["不得提前揭示门外官差身份", "不得展示钥匙对应的箱柜内部"],
            "asset_budget": {"max_scene_anchors": 2, "max_speaking_characters": 4},
            "units": [
                {
                    "unit_id": "SP-E001-U001",
                    "sequence": 1,
                    "scene_id": "1-1",
                    "narrative_task": "管家当面索要钥匙",
                    "duration_seconds": 3,
                    "action_start": "阿宁攥钥匙退到门槛外",
                    "action_end": "管家伸手拦住去路",
                    "source_refs": ["EV-0001"],
                    "decision_ids": ["AD-0001"],
                    "characters_on_screen": characters,
                    "scene_anchor_ref": {"artifact_key": "scene_anchor:L001", "version": 1},
                    "dialogue": [{"cue_id": "Q001", "lip_sync": True}],
                    "sound": ["院外蝉鸣"],
                    "negative_constraints": ["不出现官差", "无字幕"],
                    "generation_strategy": "text_to_video",
                    "state_chain": {"chain_id": "CHAIN-E001-S01", "enter": state_a, "exit": state_b},
                },
                {
                    "unit_id": "SP-E001-U002",
                    "sequence": 2,
                    "scene_id": "1-1",
                    "narrative_task": "阿宁拒交钥匙，冲突升级",
                    "duration_seconds": 4,
                    "action_start": "阿宁把钥匙藏到袖后",
                    "action_end": "管家堵住院门",
                    "source_refs": ["EV-0001"],
                    "decision_ids": ["AD-0001"],
                    "characters_on_screen": characters,
                    "scene_anchor_ref": {"artifact_key": "scene_anchor:L001", "version": 1},
                    "dialogue": [{"cue_id": "Q002", "lip_sync": True}],
                    "sound": ["场外叩门声"],
                    "negative_constraints": ["不出现官差", "无字幕"],
                    "generation_strategy": "tail_frame_chain",
                    "state_chain": {"chain_id": "CHAIN-E001-S01", "enter": state_b, "exit": state_b},
                },
            ],
        }

    def approve_shot_plan_with_review(self, plan_version: int) -> None:
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
            file_tag="AI分镜",
        )
        self.approve_artifact("ai_video_boundary_review:E001", review_version)
        self.approve_artifact("ai_shot_plan:E001", plan_version)

    def test_render_storyboard_from_confirmed_shot_plan(self) -> None:
        import render_storyboard

        self.create_ready_project()
        self.register_ai_layer_prerequisites()
        plan = self.shot_plan_payload()
        plan["hard_blocks"] = ["不得展示钥匙对应的箱柜内部"]
        plan["units"][0]["prompt_text"] = "固定中景:管家伸手拦住攥钥匙的阿宁。"
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
            "管家当面索要钥匙",
            "节奏时间轴",
            "不得展示钥匙对应的箱柜内部",
            "通用提示词",
            "character_anchor:C001",
        ):
            self.assertIn(expected, page, expected)

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
                        "action": "管家索要钥匙，阿宁藏钥匙拒绝，管家堵门",
                        "camera": "固定中景切缓慢推进",
                        "environment": "灰砖院门，日景",
                        "dialogue": [{"cue_id": "Q001"}, {"cue_id": "Q002"}],
                        "sound": ["蝉鸣", "叩门声"],
                        "negative": ["不出现官差", "无字幕"],
                    },
                    "prompt_text": "固定中景：管家说\"把钥匙交出来。\"阿宁把钥匙藏到袖后：\"这是母亲留给我的。\"管家堵住院门。",
                    "chain": {"chain_id": "CHAIN-E001-S01", "input_state": "STATE-S01-START", "output_state": "STATE-S01-END"},
                },
            ],
            "total_duration_seconds": 7,
        }
        self.register_and_approve(
            "ai_video_execution_plan:E001:seedance-2-0",
            "10_AI视频执行包/E001_执行计划V1.json",
            json.dumps(execution, ensure_ascii=False),
            (
                f"ai_shot_plan:E001@{plan_version}",
                "model_capability_profile:seedance-2-0@1",
            ),
        )

    def test_ai_shot_plan_blocks_quality_violations(self) -> None:
        self.create_ready_project()
        self.register_ai_layer_prerequisites()
        plan = self.shot_plan_payload()
        plan["units"][0]["dialogue"] = [
            {"cue_id": "Q001", "lip_sync": True},
            {"cue_id": "Q002", "lip_sync": True},
        ]
        plan["units"][0]["characters_on_screen"] = [
            {"character_id": "C001", "anchor_ref": {"artifact_key": "character_anchor:C001", "version": 1}, "appearance_lock": "", "wardrobe": "青布衫"},
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
            "shotplan_multi_lip_sync",
            "shotplan_appearance_lock_missing",
            "shotplan_over_4s_rationale_missing",
            "shotplan_state_chain_break",
            "shotplan_scene_anchor_invalid",
        ):
            self.assertIn(expected, payload["error"], expected)

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


if __name__ == "__main__":
    unittest.main()
