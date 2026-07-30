#!/usr/bin/env python3
"""把已确认的 ai_shot_plan 渲染成单文件 HTML 故事板(纯确定性,零依赖,不调用模型)。

用法:
    python3 render_storyboard.py <项目目录> <集号如E001> [--output 输出路径]

数据来源:项目 project_state.json 中最新已确认的 ai_shot_plan:<集号>、
dialogue_cue_sheet、四类锚点、project_spec。只读,不改任何项目状态。
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import shot_contracts

STATE_FILENAME = "project_state.json"

# 参考色板(dataviz 默认,已通过六项校验;场景按登记顺序取固定槽位,不循环)
SCENE_SLOTS_LIGHT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]
SCENE_SLOTS_DARK = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300"]


def esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def compiled_content_field(unit: dict[str, Any], field: str) -> str:
    atoms = {
        atom.get("atom_id"): atom
        for atom in unit.get("content_atoms", [])
        if isinstance(atom, dict) and isinstance(atom.get("atom_id"), str)
    } if isinstance(unit.get("content_atoms"), list) else {}
    bindings = unit.get("content_bindings")
    refs = bindings.get(field) if isinstance(bindings, dict) else None
    if not isinstance(refs, list) or not refs or any(ref not in atoms for ref in refs):
        return ""
    return "；".join(str(atoms[ref].get("text", "")).strip() for ref in refs)


def compiled_screen_text(unit: dict[str, Any]) -> str:
    screen_text = unit.get("screen_text")
    if not isinstance(screen_text, dict):
        return ""
    atoms = {
        atom.get("atom_id"): atom
        for atom in unit.get("content_atoms", [])
        if isinstance(atom, dict) and isinstance(atom.get("atom_id"), str)
    } if isinstance(unit.get("content_atoms"), list) else {}
    refs = screen_text.get("content_atom_refs")
    if not isinstance(refs, list) or not refs or any(ref not in atoms for ref in refs):
        return ""
    return "；".join(str(atoms[ref].get("text", "")).strip() for ref in refs)


def load_state(project_path: Path) -> dict[str, Any]:
    path = project_path / STATE_FILENAME
    if not path.is_file():
        raise SystemExit(f"找不到项目状态文件:{path}")
    return json.loads(path.read_text(encoding="utf-8"))


def latest_confirmed(state: dict[str, Any], key: str) -> dict[str, Any] | None:
    records = [
        item
        for item in state.get("artifacts", {}).get(key, [])
        if isinstance(item, dict) and item.get("status") == "confirmed"
    ]
    if not records:
        return None
    return max(records, key=lambda item: item.get("version") or -1)


def read_artifact(project_path: Path, record: dict[str, Any] | None) -> Any:
    if record is None:
        return None
    path = project_path / str(record.get("path"))
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() == ".json":
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None
    return text


def confirmed_dependency(
    state: dict[str, Any],
    record: dict[str, Any] | None,
    artifact_prefix: str,
) -> dict[str, Any] | None:
    """优先返回目标制品精确绑定的已确认依赖,再回退到无作用域 key。"""
    if isinstance(record, dict):
        for dependency in record.get("depends_on", []):
            if not isinstance(dependency, dict):
                continue
            key = dependency.get("artifact_key")
            version = dependency.get("version")
            if not isinstance(key, str) or not (
                key == artifact_prefix or key.startswith(artifact_prefix + ":")
            ):
                continue
            for candidate in state.get("artifacts", {}).get(key, []):
                if (
                    isinstance(candidate, dict)
                    and candidate.get("version") == version
                    and candidate.get("status") == "confirmed"
                ):
                    return candidate
    return latest_confirmed(state, artifact_prefix)


def collect_anchors(state: dict[str, Any], project_path: Path, prefix: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for key in sorted(state.get("artifacts", {})):
        if key == prefix or key.startswith(prefix + ":"):
            record = latest_confirmed(state, key)
            content = read_artifact(project_path, record)
            if isinstance(content, dict):
                turnaround = content.get("turnaround_prompt")
                full_text = turnaround.get("full_text") if isinstance(turnaround, dict) else None
                if prefix == "character_anchor" and isinstance(full_text, str) and full_text.strip():
                    name = content.get("display_name") or key
                    content = f"人物三视图描述\n{name}：{full_text.strip()}"
                else:
                    content = anchor_dict_to_text(content)
            if isinstance(content, str) and content.strip():
                found.append((key, content))
    return found


def anchor_dict_to_text(payload: dict[str, Any], indent: int = 0) -> str:
    """把 JSON 锚点渲染成可读的键值文本(跳过通用元数据字段)。"""
    skip = {"schema_version", "project_id", "generated_from"}
    lines: list[str] = []
    for key, value in payload.items():
        if indent == 0 and key in skip:
            continue
        pad = "  " * indent
        if isinstance(value, dict):
            lines.append(f"{pad}{key}:")
            lines.append(anchor_dict_to_text(value, indent + 1))
        elif isinstance(value, list):
            rendered = "、".join(str(item) for item in value if not isinstance(item, (dict, list)))
            complex_items = [item for item in value if isinstance(item, (dict, list))]
            lines.append(f"{pad}{key}: {rendered}" if rendered else f"{pad}{key}:")
            for item in complex_items:
                if isinstance(item, dict):
                    lines.append(anchor_dict_to_text(item, indent + 1))
        else:
            lines.append(f"{pad}{key}: {value}")
    return "\n".join(line for line in lines if line.strip())


def duration_class(duration: Any) -> str:
    if isinstance(duration, (int, float)) and duration > 4:
        return "over4"
    return ""


def render(project_path: Path, episode: str, output: Path | None = None) -> Path:
    project_path = project_path.resolve()
    state = load_state(project_path)
    episode = episode.upper()
    plan_key = f"ai_shot_plan:{episode}"
    plan_record = latest_confirmed(state, plan_key)
    plan = read_artifact(project_path, plan_record)
    if not isinstance(plan, dict):
        raise SystemExit(f"没有已确认的 {plan_key},无法渲染;先完成分镜计划并过边界门禁")

    cue_sheet = read_artifact(
        project_path,
        confirmed_dependency(state, plan_record, "dialogue_cue_sheet"),
    )
    cues: dict[str, dict[str, Any]] = {}
    if isinstance(cue_sheet, dict):
        for cue in cue_sheet.get("records", []):
            if isinstance(cue, dict) and isinstance(cue.get("cue_id"), str):
                cues[cue["cue_id"]] = cue

    spec = read_artifact(project_path, latest_confirmed(state, "project_spec"))
    project_name = state.get("name", project_path.name)

    units = [unit for unit in plan.get("units", []) if isinstance(unit, dict)]
    total = sum(
        unit.get("duration_seconds")
        for unit in units
        if isinstance(unit.get("duration_seconds"), (int, float))
    )
    target = plan.get("target_duration_seconds")
    deviation_pct = (
        round((total - target) / target * 100, 1)
        if isinstance(target, int) and target > 0
        else None
    )

    # 场景 → 固定色槽(按首次出现顺序)
    scene_order: list[str] = []
    for unit in units:
        scene = str(unit.get("scene_id"))
        if scene not in scene_order:
            scene_order.append(scene)
    scene_slot = {scene: index % len(SCENE_SLOTS_LIGHT) for index, scene in enumerate(scene_order)}
    used_character_ids = {
        char.get("character_id")
        for unit in units
        for char in unit.get("characters_on_screen", [])
        if isinstance(char, dict) and isinstance(char.get("character_id"), str)
    }
    used_scene_anchor_keys = {
        unit.get("scene_anchor_ref", {}).get("artifact_key")
        for unit in units
        if isinstance(unit.get("scene_anchor_ref"), dict)
        and isinstance(unit["scene_anchor_ref"].get("artifact_key"), str)
    }

    buckets = {"le2": 0, "mid": 0, "gt4": 0}
    for unit in units:
        duration = unit.get("duration_seconds")
        if not isinstance(duration, (int, float)):
            continue
        if duration <= 2:
            buckets["le2"] += 1
        elif duration <= 4:
            buckets["mid"] += 1
        else:
            buckets["gt4"] += 1

    css_scene_vars_light = "\n".join(
        f"  --scene-{index}: {color};" for index, color in enumerate(SCENE_SLOTS_LIGHT)
    )
    css_scene_vars_dark = "\n".join(
        f"    --scene-{index}: {color};" for index, color in enumerate(SCENE_SLOTS_DARK)
    )

    # ---- 时间轴 ----
    timeline_blocks: list[str] = []
    elapsed = 0.0
    for unit in units:
        duration = unit.get("duration_seconds")
        width = (duration / total * 100) if isinstance(duration, (int, float)) and total else 0
        slot = scene_slot.get(str(unit.get("scene_id")), 0)
        over = " tl-over4" if duration_class(duration) else ""
        label = str(unit.get("sequence", ""))
        tooltip = f"{unit.get('unit_id')} · {duration}s · {compiled_content_field(unit, 'narrative_task')}"
        timeline_blocks.append(
            f'<div class="tl-block{over}" style="width:{width:.2f}%;background:var(--scene-{slot})" title="{esc(tooltip)}"><span>{esc(label)}</span></div>'
        )
        elapsed += duration if isinstance(duration, (int, float)) else 0
    ticks: list[str] = []
    if total:
        second = 15
        while second < total:
            ticks.append(
                f'<div class="tick" style="left:{second / total * 100:.2f}%"><i></i><b>{second}s</b></div>'
            )
            second += 15
        ticks.append(
            f'<div class="tick hook" style="left:{min(5 / total * 100, 100):.2f}%"><i></i><b>5s钩子线</b></div>'
        )

    legend_items = "".join(
        f'<span class="lg"><i style="background:var(--scene-{scene_slot[scene]})"></i>{esc(scene)}</span>'
        for scene in scene_order
    )

    # ---- 单元卡片 ----
    cards: list[str] = []
    for unit in units:
        duration = unit.get("duration_seconds")
        slot = scene_slot.get(str(unit.get("scene_id")), 0)
        over = duration_class(duration)
        duration_chip = (
            f'<span class="chip warn">⚠ {esc(duration)}s 超4秒</span>'
            if over
            else f'<span class="chip">{esc(duration)}s</span>'
        )
        characters = "".join(
            f'<span class="chip person" title="{esc(char.get("appearance_lock"))}">{esc(char.get("character_id"))}</span>'
            for char in unit.get("characters_on_screen", [])
            if isinstance(char, dict)
        ) or '<span class="muted">无人物(空镜)</span>'
        dialogue_rows: list[str] = []
        for entry in unit.get("dialogue", []) or []:
            if not isinstance(entry, dict):
                continue
            cue = cues.get(str(entry.get("cue_id")), {})
            speaker = cue.get("speaker_name") or cue.get("speaker_id") or "?"
            lip = ' <span class="chip lip">🗣对嘴</span>' if entry.get("lip_sync") else ""
            dialogue_rows.append(
                f'<li><b>{esc(speaker)}</b>:{esc(cue.get("text", entry.get("cue_id")))}{lip}</li>'
            )
        dialogue_html = f"<ul class='dlg'>{''.join(dialogue_rows)}</ul>" if dialogue_rows else '<span class="muted">无台词</span>'
        negatives = "".join(f"<li>{esc(item)}</li>" for item in unit.get("negative_constraints", []) or [])
        rationale = (
            f'<div class="row warnrow">⚠ 超4秒理由:{esc(unit.get("over_4s_rationale"))}</div>'
            if over and unit.get("over_4s_rationale")
            else ""
        )
        framing_instruction = shot_contracts.compile_shot_instruction(unit)
        prompt_text = unit.get("prompt_text")
        if not isinstance(prompt_text, str) or not prompt_text.strip():
            prompt_text = compiled_content_field(unit, "prompt_text")
        framing_prefix = framing_instruction.rstrip("。") + "。"
        compiled_prompt = (
            f"{framing_prefix}\n{prompt_text.strip()}"
            if isinstance(prompt_text, str) and prompt_text.strip()
            else framing_prefix
        )
        prompt_html = (
            f"<details><summary>通用提示词 <button class='copy' data-copy>复制</button></summary>"
            f"<pre class='prompt'>{esc(compiled_prompt)}</pre></details>"
        )
        sound_events = unit.get("sound_events") if isinstance(unit.get("sound_events"), list) else []
        sounds = "、".join(
            str(item.get("description")) for item in sound_events
            if isinstance(item, dict) and item.get("description")
        ) or "无"
        chain = unit.get("state_chain") or {}
        screen_video = "、".join(str(item) for item in unit.get("screen_video_characters", []) or []) or "无"
        screen_text = unit.get("screen_text")
        screen_text_html = ""
        verified_screen_text = compiled_screen_text(unit)
        if isinstance(screen_text, dict) and verified_screen_text:
            screen_text_html = (
                f'<div class="row">屏幕文字:{esc(verified_screen_text)} '
                f'<span class="chip">{esc(screen_text.get("render_mode"))}</span></div>'
            )
        cards.append(f"""
<article class="card" style="border-left-color:var(--scene-{slot})">
  <header>
    <span class="seq">{esc(unit.get('sequence'))}</span>
    <code>{esc(unit.get('unit_id'))}</code>
    {duration_chip}
    <span class="chip scene">场 {esc(unit.get('scene_id'))}</span>
    <span class="chip strategy">{esc(unit.get('generation_strategy'))}</span>
  </header>
  <div class="row"><b>景别：</b>{esc(shot_contracts.shot_size_text(unit))}</div>
  <div class="row"><b>镜头运动：</b>{esc(shot_contracts.camera_movement_text(unit))}</div>
  <div class="row task">{esc(compiled_content_field(unit, 'narrative_task'))}</div>
  <div class="row">动作:{esc(compiled_content_field(unit, 'action_start'))} <span class="arrow">→</span> {esc(compiled_content_field(unit, 'action_end'))}</div>
  <div class="row">现场人物:{characters}</div>
  <div class="row">屏幕视频人物:{esc(screen_video)}</div>
  <div class="row">台词:{dialogue_html}</div>
  {screen_text_html}
  <div class="row">声音:{esc(sounds)} <span class="muted">| 链 {esc(chain.get('chain_id'))}</span></div>
  <div class="row neg">禁止:<ul>{negatives}</ul></div>
  {rationale}
  {prompt_html}
</article>""")

    # ---- 锚点/阻断/统计 ----
    anchor_sections: list[str] = []
    for title, prefix in (
        ("风格锚点", "style_anchor"),
        ("角色锚点", "character_anchor"),
        ("场景锚点", "scene_anchor"),
        ("道具锚点", "prop_anchor"),
    ):
        anchors = collect_anchors(state, project_path, prefix)
        if not anchors:
            continue
        blocks = "".join(
            f'<div class="anchor"><h4>{esc(key)}</h4><pre>{esc(content.strip())}</pre></div>'
            for key, content in anchors
        )
        anchor_sections.append(f"<h3>{esc(title)}</h3><div class='anchor-grid'>{blocks}</div>")

    hard_blocks = "".join(
        f"<li>☐ {esc(item)}</li>" for item in plan.get("hard_blocks", []) or []
    )
    if deviation_pct is None:
        deviation_html = '<span class="muted">未声明目标时长</span>'
    else:
        status = "good" if abs(deviation_pct) <= 20 else "critical"
        icon = "✓" if status == "good" else "✗"
        deviation_html = (
            f'<span class="status {status}">{icon} 合计 {total:g}s / 目标 {target}s'
            f'(偏差 {deviation_pct:+g}%)</span>'
        )

    budget = plan.get("asset_budget") or {}
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    version = plan_record.get("version") if plan_record else "?"

    page = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(project_name)} · {esc(episode)} 故事板</title>
<style>
.sb-root {{
  color-scheme: light;
  --surface-1: #fcfcfb; --page: #f9f9f7;
  --ink-1: #0b0b0b; --ink-2: #52514e; --muted: #898781;
  --grid: #e1e0d9; --border: rgba(11,11,11,0.10);
  --warn: #fab219; --good-text: #006300; --crit: #d03b3b;
{css_scene_vars_light}
}}
@media (prefers-color-scheme: dark) {{
  :root:where(:not([data-theme="light"])) .sb-root {{
    color-scheme: dark;
    --surface-1: #1a1a19; --page: #0d0d0d;
    --ink-1: #ffffff; --ink-2: #c3c2b7; --muted: #898781;
    --grid: #2c2c2a; --border: rgba(255,255,255,0.10);
    --good-text: #0ca30c; --crit: #e66767;
{css_scene_vars_dark}
  }}
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; }}
.sb-root {{ font-family: system-ui, -apple-system, "Segoe UI", sans-serif; background: var(--page); color: var(--ink-1); padding: 24px; min-height: 100vh; }}
h1 {{ font-size: 20px; margin: 0 0 4px; }}
h2 {{ font-size: 15px; margin: 28px 0 10px; color: var(--ink-1); }}
h3 {{ font-size: 13px; margin: 18px 0 8px; color: var(--ink-2); }}
.meta {{ color: var(--ink-2); font-size: 13px; margin-bottom: 4px; }}
.status.good {{ color: var(--good-text); font-weight: 600; }}
.status.critical {{ color: var(--crit); font-weight: 600; }}
.tl-wrap {{ position: relative; background: var(--surface-1); border: 1px solid var(--border); border-radius: 8px; padding: 26px 10px 30px; }}
.tl {{ display: flex; gap: 2px; height: 34px; }}
.tl-block {{ position: relative; border-radius: 4px 4px 0 0; min-width: 3px; overflow: hidden; }}
.tl-block span {{ position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; font-size: 10px; color: #fff; text-shadow: 0 0 2px rgba(0,0,0,.55); }}
.tl-block.tl-over4 {{ outline: 2px solid var(--warn); outline-offset: -2px; }}
.tick {{ position: absolute; top: 8px; bottom: 12px; }}
.tick i {{ display: block; width: 1px; height: 100%; background: var(--grid); }}
.tick b {{ position: absolute; top: -12px; left: -8px; font-size: 9px; font-weight: 400; color: var(--muted); white-space: nowrap; }}
.tick.hook i {{ background: var(--warn); width: 2px; }}
.legend {{ margin-top: 10px; font-size: 12px; color: var(--ink-2); display: flex; flex-wrap: wrap; gap: 12px; }}
.lg i {{ display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 4px; vertical-align: -1px; }}
.cards {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 12px; }}
.card {{ background: var(--surface-1); border: 1px solid var(--border); border-left: 4px solid; border-radius: 8px; padding: 12px 14px; font-size: 13px; break-inside: avoid; }}
.card header {{ display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin-bottom: 8px; }}
.seq {{ font-weight: 700; font-size: 15px; }}
code {{ color: var(--ink-2); font-size: 11px; }}
.chip {{ border: 1px solid var(--border); border-radius: 10px; padding: 1px 8px; font-size: 11px; color: var(--ink-2); }}
.chip.warn {{ border-color: var(--warn); color: var(--ink-1); font-weight: 600; }}
.chip.lip {{ border-color: var(--grid); }}
.chip.person {{ cursor: help; }}
.row {{ margin: 5px 0; color: var(--ink-2); }}
.row.task {{ color: var(--ink-1); font-weight: 600; }}
.arrow {{ color: var(--muted); }}
.warnrow {{ color: var(--ink-1); background: color-mix(in srgb, var(--warn) 14%, transparent); border-radius: 6px; padding: 4px 8px; }}
.dlg {{ margin: 2px 0 0; padding-left: 18px; }}
.dlg li {{ margin: 2px 0; }}
.neg ul {{ margin: 2px 0 0; padding-left: 18px; }}
.muted {{ color: var(--muted); }}
details {{ margin-top: 8px; }}
summary {{ cursor: pointer; color: var(--ink-2); font-size: 12px; }}
pre {{ white-space: pre-wrap; word-break: break-word; font-family: inherit; font-size: 12px; background: var(--page); border: 1px solid var(--grid); border-radius: 6px; padding: 8px 10px; color: var(--ink-1); }}
.copy {{ font-size: 11px; border: 1px solid var(--border); background: var(--surface-1); color: var(--ink-2); border-radius: 6px; padding: 1px 8px; cursor: pointer; }}
.anchor-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 10px; }}
.anchor {{ background: var(--surface-1); border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; }}
.anchor h4 {{ margin: 0 0 6px; font-size: 12px; color: var(--ink-2); }}
.blocks {{ background: var(--surface-1); border: 1px solid var(--border); border-radius: 8px; padding: 10px 16px; }}
.blocks li {{ margin: 4px 0; color: var(--ink-1); }}
.stats {{ display: flex; gap: 18px; font-size: 13px; color: var(--ink-2); flex-wrap: wrap; }}
footer {{ margin-top: 30px; font-size: 11px; color: var(--muted); }}
@media print {{
  .sb-root {{ padding: 0; background: #fff; }}
  .card {{ border-left-width: 4px; }}
  details {{ open: true; }}
  .copy {{ display: none; }}
}}
</style>
</head>
<body>
<div class="sb-root">
<h1>{esc(project_name)} · {esc(episode)} 故事板</h1>
<div class="meta">ai_shot_plan v{esc(version)} · {len(units)} 个视觉单元 · {deviation_html}</div>
<div class="stats"><span>切点分布:≤2秒 {buckets['le2']} 个 · 2–4秒 {buckets['mid']} 个 · <b>&gt;4秒 {buckets['gt4']} 个</b></span>
<span>资产预算:场景锚点 {len(used_scene_anchor_keys)}/≤{esc(budget.get('max_scene_anchors', '—'))} · 出镜角色 {len(used_character_ids)}/≤{esc(budget.get('max_speaking_characters', '—'))} · 场景ID {len(scene_order)}</span></div>

<h2>节奏时间轴</h2>
<div class="tl-wrap"><div class="tl">{''.join(timeline_blocks)}</div>{''.join(ticks)}</div>
<div class="legend">{legend_items}<span class="lg"><i style="background:transparent;outline:2px solid var(--warn);outline-offset:-2px"></i>⚠ 超4秒单元</span></div>

<h2>分镜单元({len(units)})</h2>
<div class="cards">{''.join(cards)}</div>

<h2>本集必须阻断</h2>
<div class="blocks"><ul style="list-style:none;padding-left:4px;margin:0">{hard_blocks}</ul></div>

<h2>锚点资产表</h2>
{''.join(anchor_sections) or '<div class="muted">未登记锚点</div>'}

<footer>生成于 {esc(generated_at)} · 渲染自已确认制品,只读展示;规范数据以项目 JSON 为准 · AI导演插件 render_storyboard</footer>
</div>
<script>
document.querySelectorAll('[data-copy]').forEach(function(btn) {{
  btn.addEventListener('click', function(event) {{
    event.preventDefault();
    var pre = btn.closest('details').querySelector('pre');
    navigator.clipboard.writeText(pre.textContent).then(function() {{
      btn.textContent = '已复制';
      setTimeout(function() {{ btn.textContent = '复制'; }}, 1200);
    }});
  }});
}});
</script>
</body>
</html>
"""
    if output is None:
        output = project_path / "10_AI视频执行包" / f"{episode}_故事板.html"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(page, encoding="utf-8")
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="渲染 ai_shot_plan 为 HTML 故事板")
    parser.add_argument("project", help="项目目录")
    parser.add_argument("episode", help="集号,如 E001")
    parser.add_argument("--output", help="输出 HTML 路径,默认 10_AI视频执行包/<集号>_故事板.html")
    args = parser.parse_args(argv)
    output = render(
        Path(args.project).expanduser(),
        args.episode,
        Path(args.output).expanduser() if args.output else None,
    )
    print(json.dumps({"ok": True, "output": str(output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
