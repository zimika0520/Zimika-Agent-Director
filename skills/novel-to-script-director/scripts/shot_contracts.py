#!/usr/bin/env python3
"""Shared deterministic shot-size and camera-movement contracts."""
from __future__ import annotations

from typing import Any

SHOT_SIZE_VALUES = {
    "extreme_long_shot",
    "long_shot",
    "full_shot",
    "medium_shot",
    "medium_close_up",
    "close_up",
    "extreme_close_up",
    "over_the_shoulder",
    "two_shot",
}
CAMERA_MOVEMENT_VALUES = {
    "static",
    "push_in",
    "pull_out",
    "pan",
    "tilt",
    "track",
    "crane",
    "orbit",
    "handheld",
}
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


def _error(code: str, message: str, unit_index: int, **extra: Any) -> dict[str, Any]:
    return {"code": code, "message": message, "unit": unit_index, **extra}


def validate_shot_framing_contract(
    unit: dict[str, Any], unit_index: int, *, strict: bool
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    shot_language = unit.get("shot_language")
    if not isinstance(shot_language, dict):
        shot_language = {}

    shot_size = shot_language.get("shot_size")
    if strict:
        if not isinstance(shot_size, dict):
            errors.append(_error("shotplan_shot_size_missing", "分镜缺少结构化景别", unit_index))
        else:
            for edge in ("start", "end"):
                if shot_size.get(edge) not in SHOT_SIZE_VALUES:
                    errors.append(
                        _error(
                            "shotplan_shot_size_invalid",
                            f"分镜 {edge} 景别非法",
                            unit_index,
                            field=edge,
                        )
                    )
    elif not (
        isinstance(shot_size, str) and shot_size.strip()
    ) and not isinstance(shot_size, dict):
        errors.append(_error("shotplan_shot_size_missing", "分镜缺少景别", unit_index))

    movement = shot_language.get("camera_movement")
    if strict:
        if not isinstance(movement, dict):
            errors.append(
                _error(
                    "shotplan_camera_movement_missing",
                    "分镜缺少结构化镜头运动",
                    unit_index,
                )
            )
            return errors
        movement_type = movement.get("type")
        if movement_type not in CAMERA_MOVEMENT_VALUES:
            errors.append(
                _error(
                    "shotplan_camera_movement_invalid",
                    "镜头运动类型非法",
                    unit_index,
                )
            )
        subject = movement.get("subject")
        if movement_type != "static" and (
            not isinstance(subject, str) or not subject.strip()
        ):
            errors.append(
                _error(
                    "shotplan_camera_subject_missing",
                    "非固定镜头必须声明跟随或聚焦对象",
                    unit_index,
                )
            )
        description = movement.get("description")
        if not isinstance(description, str) or not description.strip():
            errors.append(
                _error(
                    "shotplan_camera_description_missing",
                    "镜头运动必须写明起点、运动和结束位置",
                    unit_index,
                )
            )
    elif not (
        isinstance(movement, str) and movement.strip()
    ) and not isinstance(movement, dict):
        errors.append(
            _error(
                "shotplan_camera_movement_missing",
                "分镜缺少镜头运动",
                unit_index,
            )
        )
    return errors


def shot_size_text(unit: dict[str, Any]) -> str:
    shot_language = unit.get("shot_language")
    shot_size = shot_language.get("shot_size") if isinstance(shot_language, dict) else None
    if isinstance(shot_size, str):
        return shot_size.strip() or "未声明"
    if not isinstance(shot_size, dict):
        return "未声明"
    start = SHOT_SIZE_LABELS.get(shot_size.get("start"), "未声明")
    end = SHOT_SIZE_LABELS.get(shot_size.get("end"), "未声明")
    return start if start == end else f"{start} → {end}"


def camera_movement_text(unit: dict[str, Any]) -> str:
    shot_language = unit.get("shot_language")
    movement = shot_language.get("camera_movement") if isinstance(shot_language, dict) else None
    if isinstance(movement, str):
        return movement.strip() or "未声明"
    if not isinstance(movement, dict):
        return "未声明"
    description = movement.get("description")
    return description.strip() if isinstance(description, str) and description.strip() else "未声明"


def compile_shot_instruction(unit: dict[str, Any]) -> str:
    size_text = shot_size_text(unit).replace(" → ", "到")
    return f"景别：{size_text}。镜头运动：{camera_movement_text(unit)}"
