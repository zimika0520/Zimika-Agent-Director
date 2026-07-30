#!/usr/bin/env python3
from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

import render_episode_script


SCRIPT = """# 第1集：重逢

## 1-1 场景：云邸客厅 夜 / 内
人物：温喻、傅聿珹
道具：手机

△温喻推门进入，脚步停下。
傅聿珹 OS：门没锁。
温喻：我知道。
场尾状态：温喻停在门边。

## 1-2 场景：云邸客厅 夜 / 内
人物：温喻
道具：手机

△温喻低头看向手机。
集尾钩子：屏幕忽然亮起。
【画面骤黑】
"""


class EpisodeDeliveryTests(unittest.TestCase):
    def roster(self) -> dict:
        return {
            "records": [
                {
                    "character_id": "C001",
                    "name": "温喻",
                    "appearances": [
                        {"episode_id": "E001", "scene_id": "1-1", "presence_mode": "on_screen", "entry_state": "", "exit_state": ""},
                        {"episode_id": "E001", "scene_id": "1-2", "presence_mode": "on_screen", "entry_state": "", "exit_state": ""},
                    ],
                },
                {
                    "character_id": "C002",
                    "name": "傅聿珹",
                    "appearances": [
                        {"episode_id": "E001", "scene_id": "1-1", "presence_mode": "voice_only", "entry_state": "", "exit_state": ""}
                    ],
                },
            ]
        }

    def anchors(self) -> dict:
        return {
            "C001": {
                "role_kind": "stable",
                "display_name": "温喻",
                "turnaround_prompt": {"full_text": "温喻完整三视图描述"},
            },
            "C002": {
                "role_kind": "stable",
                "display_name": "傅聿珹",
                "turnaround_prompt": {"full_text": "傅聿珹完整三视图描述"},
            },
        }

    def test_first_visible_appearance_expands_then_references(self) -> None:
        parsed = render_episode_script.parse_episode_script(SCRIPT)
        insertions = render_episode_script.build_turnaround_insertions(
            "E001", parsed["scenes"], self.roster(), self.anchors()
        )
        self.assertEqual(insertions["1-1"], ["温喻：温喻完整三视图描述"])
        self.assertEqual(insertions["1-2"], ["温喻沿用本集1-1场人物设定。"])

    def test_voice_only_character_is_not_inserted(self) -> None:
        parsed = render_episode_script.parse_episode_script(SCRIPT)
        insertions = render_episode_script.build_turnaround_insertions(
            "E001", parsed["scenes"], self.roster(), self.anchors()
        )
        self.assertFalse(any("傅聿珹" in line for line in insertions["1-1"]))

    def test_docx_uses_pdf_style_and_hides_internal_labels(self) -> None:
        parsed = render_episode_script.parse_episode_script(SCRIPT)
        insertions = render_episode_script.build_turnaround_insertions(
            "E001", parsed["scenes"], self.roster(), self.anchors()
        )
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "E001_剧本.docx"
            render_episode_script.write_docx("温夜有染", parsed, insertions, output)
            with zipfile.ZipFile(output) as archive:
                names = set(archive.namelist())
                document_xml = archive.read("word/document.xml").decode("utf-8")
            self.assertTrue(
                {
                    "[Content_Types].xml",
                    "_rels/.rels",
                    "word/document.xml",
                    "word/styles.xml",
                    "word/_rels/document.xml.rels",
                }.issubset(names)
            )
            self.assertIn("温夜有染", document_xml)
            self.assertIn("第1集：重逢", document_xml)
            self.assertIn("人物三视图描述：", document_xml)
            self.assertIn("温喻完整三视图描述", document_xml)
            self.assertIn("温喻沿用本集1-1场人物设定。", document_xml)
            self.assertNotIn("# 第1集", document_xml)
            self.assertNotIn("场尾状态：", document_xml)
            self.assertNotIn("集尾钩子：", document_xml)
            self.assertIn("屏幕忽然亮起。", document_xml)

    def test_docx_omits_source_comments_from_delivery(self) -> None:
        parsed = render_episode_script.parse_episode_script(
            SCRIPT.replace("△温喻推门进入，脚步停下。", "<!-- 来源：SRC-CH001 -->\n△温喻推门进入，脚步停下。")
        )
        self.assertFalse(
            any("<!--" in line for scene in parsed["scenes"] for line in scene["lines"])
        )

    def test_docx_styles_declare_cjk_font_fallback(self) -> None:
        self.assertIn('w:eastAsia="Songti SC"', render_episode_script.STYLES_XML)


if __name__ == "__main__":
    unittest.main()
