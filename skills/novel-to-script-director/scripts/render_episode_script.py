#!/usr/bin/env python3
"""Deterministically render one confirmed literary episode as an editable DOCX."""
from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape


class DeliveryError(RuntimeError):
    """Raised when confirmed delivery inputs are incomplete or inconsistent."""


EPISODE_HEADING_RE = re.compile(r"^\s*#{0,2}\s*(第\s*\d+\s*集\s*[：:].+?)\s*$")
SCENE_HEADING_RE = re.compile(
    r"^\s*#{0,3}\s*((\d+)-(\d+)\s*场景\s*[：:].+?)\s*$"
)
CHARACTER_LINE_RE = re.compile(r"^\s*人物\s*[：:]\s*(.+?)\s*$")
HOOK_LINE_RE = re.compile(r"^\s*集尾钩子\s*[：:]\s*(.+?)\s*$")
SCENE_STATE_RE = re.compile(r"^\s*场尾状态\s*[：:].*$")
SOURCE_COMMENT_RE = re.compile(r"^\s*<!--.*-->\s*$")
RENDER_CONTRACT_VERSION = 1


def split_names(value: str) -> list[str]:
    return [name.strip() for name in re.split(r"[、，,；;]", value) if name.strip()]


def parse_episode_script(text: str) -> dict[str, Any]:
    episode_heading = ""
    scenes: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for raw_line in text.splitlines():
        if SOURCE_COMMENT_RE.match(raw_line):
            continue
        episode_match = EPISODE_HEADING_RE.match(raw_line)
        if episode_match and not episode_heading:
            episode_heading = re.sub(r"\s+", "", episode_match.group(1), count=1)
            # Restore the normal space-free Chinese heading but preserve title punctuation/content.
            episode_heading = episode_match.group(1).strip()
            continue
        scene_match = SCENE_HEADING_RE.match(raw_line)
        if scene_match:
            current = {
                "scene_id": f"{int(scene_match.group(2))}-{int(scene_match.group(3))}",
                "heading": scene_match.group(1).strip(),
                "character_names": [],
                "lines": [],
            }
            scenes.append(current)
            continue
        if current is None:
            continue
        character_match = CHARACTER_LINE_RE.match(raw_line)
        if character_match:
            current["character_names"] = split_names(character_match.group(1))
            current["lines"].append(f"人物：{'、'.join(current['character_names'])}")
            continue
        if SCENE_STATE_RE.match(raw_line):
            continue
        hook_match = HOOK_LINE_RE.match(raw_line)
        if hook_match:
            current["lines"].append(hook_match.group(1).strip())
            continue
        line = raw_line.strip()
        if line:
            current["lines"].append(line)
    if not episode_heading:
        raise DeliveryError("episode_heading_missing")
    if not scenes:
        raise DeliveryError("episode_scenes_missing")
    return {"episode_heading": episode_heading, "scenes": scenes}


def build_turnaround_insertions(
    episode_id: str,
    scenes: list[dict[str, Any]],
    roster: dict[str, Any],
    anchors: dict[str, dict[str, Any]],
) -> dict[str, list[str]]:
    scene_order = {
        scene.get("scene_id"): index
        for index, scene in enumerate(scenes)
        if isinstance(scene, dict) and isinstance(scene.get("scene_id"), str)
    }
    records = roster.get("records") if isinstance(roster, dict) else None
    if not isinstance(records, list):
        raise DeliveryError("character_roster_records_missing")
    insertions: dict[str, list[str]] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        character_id = record.get("character_id")
        name = record.get("name")
        appearances = record.get("appearances")
        if not isinstance(character_id, str) or not isinstance(name, str) or not isinstance(appearances, list):
            continue
        visible_scenes = sorted(
            {
                appearance.get("scene_id")
                for appearance in appearances
                if isinstance(appearance, dict)
                and str(appearance.get("episode_id", "")).upper() == episode_id.upper()
                and appearance.get("presence_mode", "on_screen") in {"on_screen", "crowd_group"}
                and appearance.get("scene_id") in scene_order
            },
            key=lambda scene_id: scene_order[scene_id],
        )
        if not visible_scenes:
            continue
        anchor = anchors.get(character_id)
        turnaround = anchor.get("turnaround_prompt") if isinstance(anchor, dict) else None
        full_text = turnaround.get("full_text") if isinstance(turnaround, dict) else None
        if not isinstance(full_text, str) or not full_text.strip():
            raise DeliveryError(f"character_anchor_v2_required:{character_id}")
        role_kind = anchor.get("role_kind", "stable")
        first_scene = visible_scenes[0]
        first_line = (
            f"{name}群体：{full_text.strip()}"
            if role_kind == "crowd_group"
            else f"{name}：{full_text.strip()}"
        )
        insertions.setdefault(first_scene, []).append(first_line)
        for scene_id in visible_scenes[1:]:
            insertions.setdefault(scene_id, []).append(
                f"{name}沿用本集{first_scene}场人物设定。"
            )
    return insertions


def _paragraph(text: str, style: str) -> str:
    preserve = ' xml:space="preserve"' if text[:1].isspace() or text[-1:].isspace() else ""
    return (
        '<w:p><w:pPr><w:pStyle w:val="'
        + style
        + '"/></w:pPr><w:r><w:t'
        + preserve
        + ">"
        + escape(text)
        + "</w:t></w:r></w:p>"
    )


def _document_xml(
    work_title: str, parsed: dict[str, Any], insertions: dict[str, list[str]]
) -> str:
    paragraphs = [_paragraph(work_title, "WorkTitle")]
    paragraphs.append(_paragraph(parsed["episode_heading"], "EpisodeTitle"))
    for scene in parsed["scenes"]:
        paragraphs.append(_paragraph(scene["heading"], "SceneHeading"))
        for line in scene["lines"]:
            paragraphs.append(_paragraph(line, "Metadata" if line.startswith(("人物：", "道具：")) else "Action"))
            if line.startswith("人物：") and scene["scene_id"] in insertions:
                paragraphs.append(_paragraph("人物三视图描述：", "Metadata"))
                for description in insertions[scene["scene_id"]]:
                    paragraphs.append(_paragraph(description, "Action"))
    body = "".join(paragraphs)
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}<w:sectPr><w:pgSz w:w=\"11906\" w:h=\"16838\"/>"
        '<w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134"/>'
        "</w:sectPr></w:body></w:document>"
    )


CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
</Types>"""
ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""
DOCUMENT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>"""
STYLES_XML = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:eastAsia="Songti SC" w:cs="Arial"/></w:rPr></w:rPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:styleId="Normal"><w:name w:val="Normal"/><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:eastAsia="Songti SC" w:cs="Arial"/><w:sz w:val="22"/><w:szCs w:val="22"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="WorkTitle"><w:name w:val="WorkTitle"/><w:basedOn w:val="Normal"/><w:pPr><w:jc w:val="center"/><w:spacing w:after="240"/></w:pPr><w:rPr><w:b/><w:sz w:val="36"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="EpisodeTitle"><w:name w:val="EpisodeTitle"/><w:basedOn w:val="Normal"/><w:pPr><w:jc w:val="center"/><w:spacing w:after="240"/></w:pPr><w:rPr><w:b/><w:sz w:val="32"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="SceneHeading"><w:name w:val="SceneHeading"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:before="180" w:after="100"/></w:pPr><w:rPr><w:b/><w:sz w:val="24"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Metadata"><w:name w:val="Metadata"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="60"/></w:pPr><w:rPr><w:b/><w:sz w:val="22"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Action"><w:name w:val="Action"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="60"/></w:pPr><w:rPr><w:sz w:val="22"/></w:rPr></w:style>
</w:styles>"""


def write_docx(
    work_title: str,
    parsed: dict[str, Any],
    insertions: dict[str, list[str]],
    output: Path,
) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", CONTENT_TYPES)
        archive.writestr("_rels/.rels", ROOT_RELS)
        archive.writestr("word/document.xml", _document_xml(work_title, parsed, insertions))
        archive.writestr("word/styles.xml", STYLES_XML)
        archive.writestr("word/_rels/document.xml.rels", DOCUMENT_RELS)
    return output
