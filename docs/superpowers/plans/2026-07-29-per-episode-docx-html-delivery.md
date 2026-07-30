# Per-Episode DOCX and HTML Delivery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver each confirmed episode as one PDF-style editable DOCX script plus one HTML AI storyboard, both derived from the same episode script, character anchors, and shot-plan versions.

**Architecture:** Upgrade character anchors to a structured v2 visual contract, add required shot-size and camera-movement fields to each AI shot unit, and render both user-facing files deterministically. The literary script remains free of director language; the DOCX renderer injects first-appearance turnaround descriptions from canonical anchors, while the HTML renderer displays validated shot data and the same anchors.

**Tech Stack:** Python 3 standard library (`json`, `zipfile`, XML escaping), existing `project_tool.py`, existing `render_storyboard.py`, `unittest`, HTML/CSS.

## Global Constraints

- Final user-visible output is exactly `E001_剧本.docx` plus `E001_故事板.html` for each episode directory.
- DOCX layout follows the provided screenplay PDF: work title, episode title, scene heading, characters, turnaround description, props, action/dialogue, final visible hook, and `【画面骤黑】`.
- Do not expose Markdown `#`/`##`, internal `场尾状态：`, or internal `集尾钩子：` labels in the DOCX.
- Character turnaround output is text only; never generate or embed images.
- The first visible appearance of a character in each episode prints the full canonical turnaround description; later scenes reference the first scene.
- Named/stable/recurring characters use full turnaround text; temporary speaking roles use a concise full layout; crowds use one group appearance description; VO/OS-only characters wait until visible appearance.
- Missing source appearance may be completed as visual design, but visual design must not claim source authority or add identity, relationship, ability, backstory, or unrevealed plot facts.
- Every HTML shot unit requires validated shot size and camera movement. These fields never enter the literary DOCX.
- Dialogue, VO, and OS text must remain byte-for-byte aligned with the confirmed cue sheet; rendering cannot rewrite content.
- Preserve all current uncommitted source changes. Do not reset, stage, commit, push, install cache, or bump the plugin version without separate user authorization.
- Add only deterministic validation and one final integration fixture; do not add model self-scoring or repeated review loops.

---

## File Structure

- Create `skills/novel-to-script-director/scripts/render_episode_script.py`: parse confirmed script, resolve visible appearances, inject canonical turnaround text, and write a minimal valid DOCX using the standard library.
- Create `skills/novel-to-script-director/scripts/shot_contracts.py`: shared shot-size labels, camera-movement enums, deterministic validation, and prompt compilation used by project validation and HTML rendering.
- Create `skills/novel-to-script-director/scripts/test_episode_delivery.py`: focused renderer and paired-delivery integration tests.
- Modify `skills/novel-to-script-director/scripts/project_tool.py`: character-anchor v2 validation, shot framing/movement validation, prompt compilation, paired delivery command, and freshness checks.
- Modify `skills/novel-to-script-director/scripts/render_storyboard.py`: display validated shot size/movement and structured turnaround anchors.
- Modify `skills/novel-to-script-director/scripts/test_project_tool.py`: contract and CLI tests.
- Modify `skills/novel-to-script-director/references/production-data-schemas.md`: character anchor v2, character presence mode, and shot framing/movement schemas.
- Modify `skills/novel-to-script-director/references/artifact-contracts.md`: anchor authority and paired-delivery dependency rules.
- Modify `skills/novel-to-script-director/references/script-format-and-quality.md`: final PDF-style screenplay layout.
- Modify `skills/novel-to-script-director/references/ai-video-production.md`: framing and camera-movement production rules.
- Modify `skills/novel-to-script-director/references/workflow.md`: per-episode delivery loop.
- Modify `skills/novel-to-script-director/references/production-ready-delivery.md`: output layout and acceptance criteria.
- Modify `skills/novel-to-script-director/SKILL.md`, `README.md`, and `CHANGELOG.md`: public workflow documentation; version metadata remains unchanged until release approval.

---

### Task 1: Define and Validate Character Anchor v2

**Files:**
- Modify: `skills/novel-to-script-director/references/production-data-schemas.md:274-295, 500-end`
- Modify: `skills/novel-to-script-director/references/artifact-contracts.md:180-360`
- Modify: `skills/novel-to-script-director/scripts/project_tool.py:118-167, 5413-6065`
- Modify: `skills/novel-to-script-director/scripts/test_project_tool.py:39-end`

**Interfaces:**
- Consumes: confirmed `character_roster` records and original source references.
- Produces: `validate_character_anchor_payload(payload: dict) -> list[dict]` and a structured v2 payload consumed by both renderers.

- [ ] **Step 1: Add the character anchor v2 schema**

Document this exact shape:

```json
{
  "contract_version": 2,
  "character_id": "C001",
  "display_name": "温喻",
  "role_kind": "stable",
  "source_appearance": {
    "source_refs": ["SRC-CH001:P003"],
    "confirmed_details": ["二十多岁", "黑色长发"]
  },
  "visual_design": {
    "auto_completed": true,
    "face": "鹅蛋脸，眉形清晰，五官比例自然",
    "hair": "黑色长发，发尾自然垂落",
    "body": "成年女性，身材修长，比例自然",
    "wardrobe": "现代都市通勤服，低饱和配色",
    "distinctive_features": []
  },
  "turnaround_prompt": {
    "layout": "左侧约三分之一为完整正面头肩肖像，头部及颈部完整可见；右侧依次并排展示全身正面、全身侧面和全身背面",
    "consistency_rules": [
      "四个视图五官完全一致",
      "四个视图发型和发色完全一致",
      "四个视图身材比例完全一致",
      "四个视图服装和配色完全一致"
    ],
    "full_text": "可直接交付的完整人物三视图文字描述"
  },
  "forbidden_story_implications": [
    "不得通过伤疤、徽记或特殊道具暗示原著未公开的身份和经历"
  ]
}
```

`role_kind` accepts `stable`, `temporary_speaking`, or `crowd_group`.

- [ ] **Step 2: Extend character appearances with visibility mode**

Update the `character_roster.appearances[]` schema:

```json
{
  "episode_id": "E001",
  "scene_id": "1-1",
  "presence_mode": "on_screen",
  "entry_state": "",
  "exit_state": ""
}
```

`presence_mode` accepts `on_screen`, `voice_only`, or `crowd_group`.

- [ ] **Step 3: Write failing validation tests**

Add this fixture helper and the tests to `ProjectToolTests`:

```python
    def character_anchor_v2(self):
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

    def test_character_anchor_v2_accepts_source_and_visual_design_separation(self):
        payload = self.character_anchor_v2()
        self.assertEqual(project_tool.validate_character_anchor_payload(payload), [])

    def test_character_anchor_v2_rejects_missing_turnaround_layout(self):
        payload = self.character_anchor_v2()
        payload["turnaround_prompt"]["layout"] = ""
        codes = {item["code"] for item in project_tool.validate_character_anchor_payload(payload)}
        self.assertIn("character_anchor_turnaround_layout_missing", codes)

    def test_character_anchor_v2_rejects_plot_claim_in_visual_design(self):
        payload = self.character_anchor_v2()
        payload["visual_design"]["distinctive_features"] = ["家族继承人徽记，证明真实身份"]
        codes = {item["code"] for item in project_tool.validate_character_anchor_payload(payload)}
        self.assertIn("character_anchor_visual_story_claim", codes)
```

- [ ] **Step 4: Run focused tests and verify failure**

Run:

```bash
cd skills/novel-to-script-director/scripts
PYTHONDONTWRITEBYTECODE=1 python3 test_project_tool.py ProjectToolTests.test_character_anchor_v2_accepts_source_and_visual_design_separation ProjectToolTests.test_character_anchor_v2_rejects_missing_turnaround_layout ProjectToolTests.test_character_anchor_v2_rejects_plot_claim_in_visual_design
```

Expected: failure because `validate_character_anchor_payload()` does not exist.

- [ ] **Step 5: Implement the validator**

Add:

```python
CHARACTER_ANCHOR_ROLE_KINDS = {"stable", "temporary_speaking", "crowd_group"}
CHARACTER_PRESENCE_MODES = {"on_screen", "voice_only", "crowd_group"}
VISUAL_STORY_CLAIM_PATTERNS = (
    re.compile(r"真实身份|继承人|血统|能力觉醒|家族徽记|伤疤来源|秘密组织"),
)


def validate_character_anchor_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    if payload.get("contract_version") != 2:
        errors.append(issue("character_anchor_contract_version_invalid", "人物锚点必须使用 contract_version 2"))
    if payload.get("role_kind") not in CHARACTER_ANCHOR_ROLE_KINDS:
        errors.append(issue("character_anchor_role_kind_invalid", "人物锚点 role_kind 非法"))
    turnaround = payload.get("turnaround_prompt")
    if not isinstance(turnaround, dict) or not nonempty_string(turnaround.get("layout")):
        errors.append(issue("character_anchor_turnaround_layout_missing", "缺少人物三视图布局描述"))
    if not isinstance(turnaround, dict) or not nonempty_string(turnaround.get("full_text")):
        errors.append(issue("character_anchor_turnaround_text_missing", "缺少完整人物三视图文字描述"))
    visual_text = json.dumps(payload.get("visual_design", {}), ensure_ascii=False)
    if any(pattern.search(visual_text) for pattern in VISUAL_STORY_CLAIM_PATTERNS):
        errors.append(issue("character_anchor_visual_story_claim", "视觉设定包含身份、能力、身世或未揭露剧情暗示"))
    return errors
```

Use the project’s existing non-empty-string helper if its name differs; do not add a second equivalent helper.

- [ ] **Step 6: Dispatch validation for structured character anchors**

In `validate_structured_development_artifact()`, call the new validator when `artifact_type == "character_anchor"` and the payload is JSON. Keep legacy text anchors readable by the old HTML renderer, but make the new paired-delivery command require v2.

- [ ] **Step 7: Run focused tests**

Run the command from Step 4 again.

Expected: all three tests pass.

---

### Task 2: Add Required Shot Size and Camera Movement Contracts

**Files:**
- Create: `skills/novel-to-script-director/scripts/shot_contracts.py`
- Modify: `skills/novel-to-script-director/references/production-data-schemas.md:500-end`
- Modify: `skills/novel-to-script-director/references/ai-video-production.md:65-150`
- Modify: `skills/novel-to-script-director/scripts/project_tool.py:4474-5015`
- Modify: `skills/novel-to-script-director/scripts/test_project_tool.py:3900-end`

**Interfaces:**
- Consumes: each `ai_shot_plan.visual_units[]` record.
- Produces in `shot_contracts.py`:
  - `validate_shot_framing_contract(unit: dict, unit_index: int) -> list[dict]`
  - `compile_shot_instruction(unit: dict) -> str`
  - `shot_size_text(unit: dict) -> str`

- [ ] **Step 1: Add the shot schema**

Document:

```json
{
  "shot_size": {
    "start": "medium_shot",
    "end": "close_up"
  },
  "camera_movement": {
    "type": "push_in",
    "subject": "C001",
    "description": "从温喻腰部中景缓慢推近至面部近景，最终停在她握紧的手机上"
  }
}
```

Allowed shot sizes:

```text
extreme_long_shot, long_shot, full_shot, medium_shot,
medium_close_up, close_up, extreme_close_up,
over_the_shoulder, two_shot
```

Allowed movement types:

```text
static, push_in, pull_out, pan, tilt, track, crane, orbit, handheld
```

- [ ] **Step 2: Write failing framing tests**

Add `import shot_contracts` beside the existing test imports, then add:

```python
    def test_shot_plan_requires_shot_size_and_camera_movement(self):
        unit = self.shot_plan_payload()["visual_units"][0]
        unit.pop("shot_size", None)
        unit.pop("camera_movement", None)
        codes = {item["code"] for item in shot_contracts.validate_shot_framing_contract(unit, 1)}
        self.assertIn("shotplan_shot_size_missing", codes)
        self.assertIn("shotplan_camera_movement_missing", codes)

    def test_non_static_camera_movement_requires_subject_and_description(self):
        unit = self.shot_plan_payload()["visual_units"][0]
        unit["shot_size"] = {"start": "medium_shot", "end": "close_up"}
        unit["camera_movement"] = {"type": "push_in", "subject": "", "description": ""}
        codes = {item["code"] for item in shot_contracts.validate_shot_framing_contract(unit, 1)}
        self.assertIn("shotplan_camera_subject_missing", codes)
        self.assertIn("shotplan_camera_description_missing", codes)
```

- [ ] **Step 3: Run focused tests and verify failure**

Run:

```bash
cd skills/novel-to-script-director/scripts
PYTHONDONTWRITEBYTECODE=1 python3 test_project_tool.py ProjectToolTests.test_shot_plan_requires_shot_size_and_camera_movement ProjectToolTests.test_non_static_camera_movement_requires_subject_and_description
```

Expected: failure because the new fields and validator are absent.

- [ ] **Step 4: Implement framing validation**

Create `shot_contracts.py` with the sets and validator below, then add `import shot_contracts` to `project_tool.py`:

```python
from __future__ import annotations

from typing import Any


SHOT_SIZE_VALUES = {
    "extreme_long_shot", "long_shot", "full_shot", "medium_shot",
    "medium_close_up", "close_up", "extreme_close_up",
    "over_the_shoulder", "two_shot",
}
CAMERA_MOVEMENT_VALUES = {
    "static", "push_in", "pull_out", "pan", "tilt",
    "track", "crane", "orbit", "handheld",
}


def validate_shot_framing_contract(unit: dict[str, Any], unit_index: int) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    shot_size = unit.get("shot_size")
    if not isinstance(shot_size, dict):
        errors.append({"code": "shotplan_shot_size_missing", "message": "分镜缺少景别", "unit": unit_index})
        shot_size = {}
    else:
        for edge in ("start", "end"):
            if shot_size.get(edge) not in SHOT_SIZE_VALUES:
                errors.append({"code": "shotplan_shot_size_invalid", "message": f"分镜 {edge} 景别非法", "unit": unit_index, "field": edge})
    movement = unit.get("camera_movement")
    if not isinstance(movement, dict):
        errors.append({"code": "shotplan_camera_movement_missing", "message": "分镜缺少镜头运动", "unit": unit_index})
        return errors
    movement_type = movement.get("type")
    if movement_type not in CAMERA_MOVEMENT_VALUES:
        errors.append({"code": "shotplan_camera_movement_invalid", "message": "镜头运动类型非法", "unit": unit_index})
    subject = movement.get("subject")
    if movement_type != "static" and (not isinstance(subject, str) or not subject.strip()):
        errors.append({"code": "shotplan_camera_subject_missing", "message": "非固定镜头必须声明跟随或聚焦对象", "unit": unit_index})
    description = movement.get("description")
    if not isinstance(description, str) or not description.strip():
        errors.append({"code": "shotplan_camera_description_missing", "message": "镜头运动必须写明起点、运动和结束位置", "unit": unit_index})
    return errors
```

- [ ] **Step 5: Compile validated framing into AI prompt text**

In the same `shot_contracts.py`, add:

```python
SHOT_SIZE_LABELS = {
    "extreme_long_shot": "大远景",
    "long_shot": "远景",
    "full_shot": "全景",
    "medium_shot": "中景",
    "medium_close_up": "中近景",
    "close_up": "近景",
    "extreme_close_up": "大特写",
    "over_the_shoulder": "过肩镜头",
    "two_shot": "双人镜头",
}


def shot_size_text(unit: dict[str, Any]) -> str:
    shot_size = unit["shot_size"]
    start = SHOT_SIZE_LABELS[shot_size["start"]]
    end = SHOT_SIZE_LABELS[shot_size["end"]]
    return start if start == end else f"{start} → {end}"


def compile_shot_instruction(unit: dict[str, Any]) -> str:
    size_text = shot_size_text(unit).replace(" → ", "到")
    return f"景别：{size_text}。镜头运动：{unit['camera_movement']['description']}。"
```

In `project_tool.compile_ai_execution_prompt_text()`, prepend `shot_contracts.compile_shot_instruction(unit)` for the matching execution unit. The renderer and compiler must not infer missing values from prose.

- [ ] **Step 6: Call validation from `validate_ai_shot_plan_payload()`**

Append `shot_contracts.validate_shot_framing_contract(unit, unit_index)` issues for every visual unit before the payload can be approved.

- [ ] **Step 7: Run focused tests**

Run the command from Step 3 again.

Expected: both tests pass.

---

### Task 3: Implement the Deterministic DOCX Episode Renderer

**Files:**
- Create: `skills/novel-to-script-director/scripts/render_episode_script.py`
- Create: `skills/novel-to-script-director/scripts/test_episode_delivery.py`

**Interfaces:**
- Consumes: confirmed episode script text, confirmed character roster JSON, structured character-anchor v2 payloads, project title, and episode ID.
- Produces:
  - `parse_episode_script(text: str) -> dict`
  - `build_turnaround_insertions(episode_id: str, scenes: list[dict], roster: dict, anchors: dict[str, dict]) -> dict[str, list[str]]`
  - `render_docx(project_path: Path, episode: str, output: Path | None = None) -> Path`

- [ ] **Step 1: Write failing parser and first-appearance tests**

Create tests:

```python
import tempfile
import unittest
import zipfile
from pathlib import Path

import render_episode_script


class EpisodeDeliveryTests(unittest.TestCase):
    def test_first_visible_appearance_expands_then_references(self):
        scenes = [
            {"scene_id": "1-1", "character_names": ["温喻"]},
            {"scene_id": "1-2", "character_names": ["温喻"]},
        ]
        roster = {
            "records": [{
                "character_id": "C001",
                "name": "温喻",
                "appearances": [
                    {"episode_id": "E001", "scene_id": "1-1", "presence_mode": "on_screen", "entry_state": "", "exit_state": ""},
                    {"episode_id": "E001", "scene_id": "1-2", "presence_mode": "on_screen", "entry_state": "", "exit_state": ""},
                ],
            }]
        }
        anchors = {"C001": {"turnaround_prompt": {"full_text": "温喻完整三视图描述"}}}
        insertions = render_episode_script.build_turnaround_insertions("E001", scenes, roster, anchors)
        self.assertEqual(insertions["1-1"], ["温喻：温喻完整三视图描述"])
        self.assertEqual(insertions["1-2"], ["温喻沿用本集1-1场人物设定。"])

    def test_voice_only_character_is_not_inserted_until_visible(self):
        scenes = [
            {"scene_id": "1-1", "character_names": ["傅聿珹"]},
            {"scene_id": "1-2", "character_names": ["傅聿珹"]},
        ]
        roster = {
            "records": [{
                "character_id": "C002",
                "name": "傅聿珹",
                "appearances": [
                    {"episode_id": "E001", "scene_id": "1-1", "presence_mode": "voice_only", "entry_state": "", "exit_state": ""},
                    {"episode_id": "E001", "scene_id": "1-2", "presence_mode": "on_screen", "entry_state": "", "exit_state": ""},
                ],
            }]
        }
        anchors = {"C002": {"turnaround_prompt": {"full_text": "傅聿珹完整三视图描述"}}}
        insertions = render_episode_script.build_turnaround_insertions("E001", scenes, roster, anchors)
        self.assertNotIn("1-1", insertions)
        self.assertEqual(insertions["1-2"], ["傅聿珹：傅聿珹完整三视图描述"])
```

- [ ] **Step 2: Run focused tests and verify failure**

Run:

```bash
cd skills/novel-to-script-director/scripts
PYTHONDONTWRITEBYTECODE=1 python3 test_episode_delivery.py
```

Expected: failure because `render_episode_script.py` does not exist.

- [ ] **Step 3: Implement script parsing**

Reuse the current scene-heading, character-line, prop-line, action-line, and dialogue regex semantics from `project_tool.validate_script_file()`. The parsed structure must retain original line order and original dialogue text. Do not normalize or rewrite dialogue.

Implement:

```python
def parse_episode_script(text: str) -> dict[str, Any]:
    return {
        "work_title": "",
        "episode_heading": "第1集：标题",
        "scenes": [
            {
                "scene_id": "1-1",
                "heading": "1-1 场景：地点 夜 / 内",
                "character_names": ["温喻"],
                "lines": [],
            }
        ],
    }
```

The return shape above is normative; actual values come from the script.

- [ ] **Step 4: Implement visible-appearance insertion rules**

`build_turnaround_insertions()` must:

```text
1. Filter roster appearances to the requested episode.
2. Ignore presence_mode=voice_only.
3. For stable and temporary_speaking roles, expand full_text at first on_screen scene.
4. For later on_screen scenes, reference the first scene ID.
5. For crowd_group, insert one group appearance description without per-person expansion.
6. Raise DeliveryError if an on-screen stable/temporary role lacks a v2 anchor.
```

- [ ] **Step 5: Implement a standard-library DOCX writer**

Create a valid Office Open XML ZIP containing:

```text
[Content_Types].xml
_rels/.rels
word/document.xml
word/styles.xml
word/_rels/document.xml.rels
```

Use fixed paragraph styles:

```text
WorkTitle: centered, bold, 18pt
EpisodeTitle: centered, bold, 16pt
SceneHeading: left, bold, 12pt
Metadata: left, 11pt
Action: left, 11pt
Dialogue: left indent, 11pt
Blackout: centered, bold, 11pt
```

Escape all user content with XML escaping. Insert `人物三视图描述：` immediately after the scene’s `人物：` line and before `道具：`.

- [ ] **Step 6: Add DOCX package tests**

Add a test that renders a temporary DOCX, opens it with `zipfile.ZipFile`, reads `word/document.xml`, and asserts:

```python
self.assertIn("第1集：标题", document_xml)
self.assertIn("人物三视图描述：", document_xml)
self.assertIn("温喻完整三视图描述", document_xml)
self.assertIn("温喻沿用本集1-1场人物设定。", document_xml)
self.assertNotIn("# 第1集", document_xml)
self.assertNotIn("集尾钩子：", document_xml)
```

- [ ] **Step 7: Run focused renderer tests**

Run:

```bash
cd skills/novel-to-script-director/scripts
PYTHONDONTWRITEBYTECODE=1 python3 test_episode_delivery.py
```

Expected: all tests pass and the DOCX ZIP contains the required files.

---

### Task 4: Upgrade the HTML Storyboard Renderer

**Files:**
- Modify: `skills/novel-to-script-director/scripts/render_storyboard.py:28-500`
- Modify: `skills/novel-to-script-director/scripts/test_episode_delivery.py`

**Interfaces:**
- Consumes: confirmed `ai_shot_plan` units with Task 2 fields and character-anchor v2 payloads from Task 1.
- Produces: HTML cards that display shot size, camera movement, and canonical turnaround text.

- [ ] **Step 1: Write failing HTML assertions**

Add a fixture that renders one confirmed shot plan and asserts:

```python
self.assertIn("景别：中景 → 近景", html_text)
self.assertIn("镜头运动：从温喻腰部中景缓慢推近", html_text)
self.assertIn("人物三视图描述", html_text)
self.assertIn("温喻完整三视图描述", html_text)
```

- [ ] **Step 2: Run focused test and verify failure**

Run:

```bash
cd skills/novel-to-script-director/scripts
PYTHONDONTWRITEBYTECODE=1 python3 test_episode_delivery.py EpisodeDeliveryTests.test_storyboard_displays_framing_and_turnaround
```

Expected: failure because the renderer does not display the new fields.

- [ ] **Step 3: Add formatting helpers**

Import the shared module and add only the HTML-specific movement helper:

```python
import shot_contracts


def camera_movement_text(unit: dict[str, Any]) -> str:
    return str(unit["camera_movement"]["description"])
```

Use `shot_contracts.shot_size_text(unit)` for the displayed label. Do not duplicate enum mappings in the renderer.

- [ ] **Step 4: Render framing rows in every card**

Insert before narrative task:

```html
<div class="row"><b>景别：</b>中景 → 近景</div>
<div class="row"><b>镜头运动：</b>从温喻腰部中景缓慢推近至面部近景。</div>
```

- [ ] **Step 5: Render structured turnaround anchors**

For v2 `character_anchor` payloads, display `display_name` and `turnaround_prompt.full_text`. Preserve legacy text rendering for old projects, but the paired-delivery command will require v2.

- [ ] **Step 6: Run focused HTML tests**

Run the command from Step 2 again.

Expected: test passes.

---

### Task 5: Add One Paired Per-Episode Delivery Command

**Files:**
- Modify: `skills/novel-to-script-director/scripts/project_tool.py:2565-2575, 6974-7235, 9935-10130`
- Modify: `skills/novel-to-script-director/scripts/test_project_tool.py`
- Modify: `skills/novel-to-script-director/scripts/test_episode_delivery.py`

**Interfaces:**
- Consumes: current confirmed `episode_script:E001`, matching `episode_boundary_review:E001`, current scoped/global character roster, required character-anchor v2 records, and confirmed `ai_shot_plan:E001` plus `ai_video_boundary_review:E001`.
- Produces: `render-episode-delivery <project> E001` and exactly two user-visible files.

- [ ] **Step 1: Write failing readiness and CLI tests**

Add:

```python
    def test_render_episode_delivery_requires_current_confirmed_inputs(self):
        result = project_tool.validate_episode_delivery_readiness(self.project, "E001")
        self.assertTrue(result["ready"])

    def test_render_episode_delivery_outputs_exact_pair(self):
        exit_code = project_tool.main(["render-episode-delivery", str(self.project), "E001"])
        self.assertEqual(exit_code, 0)
        output_dir = self.project / "09_定稿交付/分集交付/E001"
        self.assertEqual(
            sorted(path.name for path in output_dir.iterdir()),
            ["E001_剧本.docx", "E001_故事板.html"],
        )
```

- [ ] **Step 2: Run focused tests and verify failure**

Run:

```bash
cd skills/novel-to-script-director/scripts
PYTHONDONTWRITEBYTECODE=1 python3 test_episode_delivery.py EpisodeDeliveryTests.test_render_episode_delivery_requires_current_confirmed_inputs EpisodeDeliveryTests.test_render_episode_delivery_outputs_exact_pair
```

Expected: failure because readiness and command functions do not exist.

- [ ] **Step 3: Implement readiness validation**

Add:

```python
def validate_episode_delivery_readiness(project_path: Path, episode: str) -> dict[str, Any]:
    return {
        "ready": not errors,
        "episode": episode,
        "errors": errors,
        "dependencies": dependency_refs,
    }
```

The function must require current confirmed records and matching boundary reviews. It must verify file hash/size through existing `confirmed_record_is_usable()` logic and require character-anchor v2 for every on-screen stable or temporary speaking role.

- [ ] **Step 4: Implement the command**

Add:

```python
def command_render_episode_delivery(args: argparse.Namespace) -> int:
    import render_episode_script
    import render_storyboard

    project_path, _state = load_state(args.project)
    episode = str(args.episode).upper()
    if not re.fullmatch(r"E\d{3,6}", episode):
        raise ToolError("集号必须使用 E001 形式")
    readiness = validate_episode_delivery_readiness(project_path, episode)
    if not readiness["ready"]:
        raise ToolError(json.dumps(readiness, ensure_ascii=False))
    output_dir = project_path / "09_定稿交付" / "分集交付" / episode
    output_dir.mkdir(parents=True, exist_ok=True)
    script_output = render_episode_script.render_docx(
        project_path, episode, output_dir / f"{episode}_剧本.docx"
    )
    html_output = render_storyboard.render(
        project_path, episode, output_dir / f"{episode}_故事板.html"
    )
    print_json({
        "ok": True,
        "episode": episode,
        "outputs": [str(script_output), str(html_output)],
        "dependencies": readiness["dependencies"],
    })
    return 0
```

Do not create a third user-visible manifest file in the episode directory. Dependency refs and hashes may be recorded in project history/state or an internal non-delivery path.

- [ ] **Step 5: Register the parser command**

Add:

```text
render-episode-delivery <project> <episode>
```

No optional output directory is needed for the public command; the fixed episode directory is the delivery contract.

- [ ] **Step 6: Run focused paired-delivery tests**

Run the command from Step 2 again.

Expected: both tests pass and the directory contains exactly two files.

---

### Task 6: Update the Public Workflow and Delivery Documentation

**Files:**
- Modify: `skills/novel-to-script-director/references/script-format-and-quality.md:1-70`
- Modify: `skills/novel-to-script-director/references/workflow.md:90-145`
- Modify: `skills/novel-to-script-director/references/production-ready-delivery.md:1-100`
- Modify: `skills/novel-to-script-director/references/ai-video-production.md:28-90`
- Modify: `skills/novel-to-script-director/SKILL.md:10-35, 130-220`
- Modify: `README.md:1-175`
- Modify: `CHANGELOG.md:1-30`

**Interfaces:**
- Consumes: implemented commands and contracts from Tasks 1-5.
- Produces: exact user-facing format and workflow instructions.

- [ ] **Step 1: Replace the Markdown delivery example with PDF-style text**

Use:

```text
小说名称

第1集：本集标题

1-1 场景：地点 日/夜 / 内/外
人物：角色A、角色B

人物三视图描述：
角色A：完整三视图文字描述。
角色B：完整三视图文字描述。

道具：道具A、道具B

△可见动作。
角色A：原著对白。
【画面骤黑】
```

- [ ] **Step 2: Document first-appearance and visibility rules**

Include stable, temporary speaking, crowd, and VO/OS behavior exactly as specified in Global Constraints.

- [ ] **Step 3: Document the per-episode loop**

Add:

```text
confirmed episode script
-> current extraction tables and continuity
-> character anchors
-> AI shot plan with shot size and camera movement
-> confirmed AI-video boundary review
-> render-episode-delivery
-> E001_剧本.docx + E001_故事板.html
```

- [ ] **Step 4: Document literary-script/director-layer separation**

State that shot size and camera movement are required in HTML shot units and forbidden in literary DOCX content.

- [ ] **Step 5: Update CHANGELOG without changing version metadata**

Add an `Unreleased` section describing the planned behavior now implemented. Do not edit `.codex-plugin/plugin.json` or the README version line until release authorization.

- [ ] **Step 6: Run documentation checks**

Run:

```bash
git diff --check -- ai-director/skills/novel-to-script-director ai-director/README.md ai-director/CHANGELOG.md
```

Expected: exit code `0` and no output.

---

### Task 7: Run One Complete Episode Delivery Fixture

**Files:**
- Modify: `skills/novel-to-script-director/scripts/test_episode_delivery.py`
- Modify: `skills/novel-to-script-director/scripts/test_project_tool.py`

**Interfaces:**
- Consumes: all previous tasks.
- Produces: one full E001 proof with DOCX and HTML from the same versions.

- [ ] **Step 1: Build a minimal confirmed E001 project fixture**

The fixture must include:

```text
project_spec
source_corpus
source_event_index
story_facts
episode_script:E001
episode_boundary_review:E001
character_roster with on_screen and voice_only examples
character_anchor:C001 v2
scene_catalog
prop_costume_ledger
dialogue_cue_sheet with exact source dialogue
continuity_ledger
ai_shot_plan:E001 with shot_size and camera_movement
ai_video_boundary_review:E001
```

- [ ] **Step 2: Run paired delivery once**

Call:

```bash
python3 project_tool.py render-episode-delivery <fixture-project> E001
```

- [ ] **Step 3: Verify the DOCX**

Open the DOCX ZIP and assert:

```text
- work title and episode title exist
- first visible character appearance has full turnaround text
- later appearance references first scene
- voice-only appearance does not trigger turnaround output
- dialogue text equals the cue-sheet source text
- Markdown headings and internal hook labels are absent
```

- [ ] **Step 4: Verify the HTML**

Assert:

```text
- every shot displays shot size
- every shot displays camera movement
- canonical turnaround text is present
- dialogue equals the same cue-sheet source text
- shot order matches ai_shot_plan sequence
```

- [ ] **Step 5: Verify exactly two user-visible outputs**

Assert the E001 directory contains only:

```text
E001_剧本.docx
E001_故事板.html
```

- [ ] **Step 6: Run focused and full verification once**

Run:

```bash
cd skills/novel-to-script-director/scripts
PYTHONDONTWRITEBYTECODE=1 python3 test_episode_delivery.py
PYTHONDONTWRITEBYTECODE=1 python3 test_project_tool.py
python3 -m py_compile project_tool.py render_storyboard.py render_episode_script.py
cd ../../../..
python3 -m json.tool .codex-plugin/plugin.json >/dev/null
git diff --check
```

Expected: all tests pass, DOCX/HTML fixture checks pass, compilation succeeds, manifest JSON remains valid, and `git diff --check` has no output.

- [ ] **Step 7: Report completion without release actions**

Report exact changed files, test counts, generated fixture paths, and remaining release steps. Do not commit, push, install cache, or bump version until the user explicitly authorizes release.
