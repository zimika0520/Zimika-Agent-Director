#!/usr/bin/env python3
"""“AI 导演”制作就绪剧本项目的本地状态、校验与打包工具。

仅使用 Python 标准库，所有状态修改都通过同目录临时文件 + os.replace
原子落盘，避免中断时破坏 project_state.json。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import sys
import tempfile
import unicodedata
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import source_partition
import shot_contracts


SCHEMA_VERSION = 1
STATE_FILENAME = "project_state.json"

# 项目规格 rights_mode 枚举：来源只来自用户提供，插件不联网检索正文。
# 缺省（旧项目无该字段）按 owned 语义处理，不报错。
RIGHTS_MODES = ("owned", "licensed", "unclear")
DEFAULT_RIGHTS_MODE = "owned"
RIGHTS_UNCLEAR_NOTICE = (
    "提示（仅此一次，不阻塞流程）：项目规格 rights_mode=unclear，"
    "请用户确认该来源的权利状态（自有改为 owned，第三方授权改为 licensed 并记录 rights_note）。"
    "插件不联网检索正文，也不等待授权，按用户提供的来源继续推进。"
)

SOURCE_KINDS = ("self_owned", "storyline", "published_novel")
DEFAULT_SOURCE_KIND = "self_owned"

# 默认生成策略：用户未明确指定时，按约 60 秒、±10%、约 15 个分镜单元规划。
# project_spec 中的显式值优先于默认值。
DEFAULT_TARGET_DURATION_SECONDS = 60
DEFAULT_DURATION_TOLERANCE_RATIO = 0.1
DEFAULT_RECOMMENDED_SHOT_UNITS = 15
# 中文配音约 3.5—4.5 字/秒，是样本推算值而非行业标准，只用于预警不作实测结论。
DEFAULT_DIALOGUE_CHARS_PER_SECOND = (3.5, 4.5)
# 单场时长比例带：单集目标时长 ÷ 场数 后允许的上下浮动，取自文档示例
#（90 秒 3 场 → 每场约 20—45 秒，即均值 30 秒的 2/3 到 3/2）。
SCENE_DURATION_BAND = (2 / 3, 3 / 2)

# 入料体检（init/add-source 时的来源体检卡）。体检只提示，不阻塞。
INTAKE_CHECK_FILENAME = "入料体检.json"
INTAKE_ANALYZABLE_SUFFIXES = {".txt", ".md", ".markdown"}
DEFAULT_GARBLE_THRESHOLD = 0.01
SENTENCE_END_CHARS = "。！？…”’』」）)】》>\"'!?"
CHAPTER_HEADING_PATTERN = re.compile(
    r"第\s*([0-9０-９一二两三四五六七八九十百千零〇]+)\s*([章回])"
)
CHINESE_DIGIT_VALUES = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
CHINESE_UNIT_VALUES = {"十": 10, "百": 100, "千": 1000}

PROJECT_DIRECTORIES = (
    "00_原始内容",
    "01_原著解析",
    "02_改编定位",
    "03_改编圣经",
    "04_分集地图",
    "05_批次大纲",
    "06_试写剧本",
    "07_分集剧本",
    "08_连续性与质检",
    "09_定稿交付",
    "10_AI视频执行包",
)

# 旧项目在该目录加入前初始化；校验时缺失不报错，注册相关制品时按需创建。
OPTIONAL_PROJECT_DIRECTORIES = {"10_AI视频执行包"}

STAGES = {
    "project_setup": "项目建档",
    "source_analysis": "原著解析",
    "adaptation_positioning": "改编定位",
    "adaptation_bible": "改编圣经",
    "series_planning": "全剧规划",
    "batch_outline": "批次大纲",
    "pilot_writing": "试写",
    "batch_writing": "批量写作",
    "quality_review": "质量复核",
    "final_delivery": "定稿交付",
}

STAGE_STATUSES = {
    "pending",
    "in_progress",
    "awaiting_approval",
    "completed",
    "stale",
    "blocked",
}

ARTIFACT_TYPES = {
    "project_spec": "项目规格",
    "source_review": "来源官网审核",
    "source_corpus": "原著语料库",
    "chapter_analysis_registry": "章节分析登记表",
    "rolling_source_progress": "滚动来源进度",
    "source_event_index": "原著事件索引",
    "story_facts": "故事事实库",
    "adaptation_profile": "改编定位卡",
    "genre_profile": "题材标签卡",
    "rolling_summary": "全局滚动摘要",
    "change_authorization": "改编变更授权记录",
    "adaptation_bible": "改编圣经",
    "adaptation_decision_ledger": "改编决策台账",
    "series_map": "全剧分集地图",
    "series_boundary_review": "全剧地图内容边界报告",
    "series_plan_review": "全剧规划审核报告",
    "batch_source_scope": "批次原著范围",
    "batch_source_detail": "批次原著细化",
    "batch_outline": "批次详细大纲",
    "batch_boundary_review": "批次大纲内容边界报告",
    "pilot_scripts": "试写剧本",
    "pilot_review": "试写审核报告",
    "episode_script": "分集分场文学剧本",
    "episode_boundary_review": "分集剧本内容边界报告",
    "character_roster": "角色提取表",
    "scene_catalog": "场景提取表",
    "prop_costume_ledger": "道具服装台账",
    "dialogue_cue_sheet": "台词声音表",
    "continuity_ledger": "连续性台账",
    "batch_continuity_snapshot": "批次连续性快照",
    "cross_batch_continuity_review": "跨批连续性审核",
    "quality_report": "质检报告",
    "production_readiness_report": "制作就绪复核报告",
    "seedance_execution_plan": "Seedance文字执行计划",
    "seedance_boundary_review": "Seedance执行层内容边界报告",
    "style_anchor": "风格锚点",
    "character_anchor": "角色锚点",
    "scene_anchor": "场景锚点",
    "prop_anchor": "道具锚点",
    "generation_retry_ledger": "生成重试台账",
    "model_capability_profile": "模型能力档案",
    "ai_shot_plan": "AI分镜单元计划",
    "ai_video_boundary_review": "AI分镜内容边界报告",
    "ai_video_execution_plan": "AI视频执行计划",
    "batch_delivery_review": "批次交付审核报告",
    "batch_delivery_manifest": "批次交付清单",
    "batch_package": "批次制作就绪包",
    "series_delivery_manifest": "全剧批次汇总清单",
    "delivery_manifest": "交付清单",
    "final_package": "全剧定稿包",
}

# 边 A -> B 表示 B 的正确性依赖 A。某个已确认的 A 出现新版本时，
# 已存在的 B 及其所有下游制品都应重新评估。
DEPENDENCY_GRAPH = {
    "project_spec": {"source_corpus", "story_facts", "adaptation_profile"},
    "source_corpus": {
        "chapter_analysis_registry",
        "rolling_source_progress",
        "source_event_index",
        "batch_source_scope",
        "batch_source_detail",
        "dialogue_cue_sheet",
    },
    "chapter_analysis_registry": {"rolling_source_progress", "source_event_index"},
    "rolling_source_progress": {"batch_source_scope", "batch_source_detail"},
    "source_event_index": {
        "story_facts",
        "adaptation_decision_ledger",
        "series_plan_review",
        "seedance_execution_plan",
        "seedance_boundary_review",
        "ai_shot_plan",
        "ai_video_boundary_review",
        "batch_source_detail",
    },
    "story_facts": {
        "adaptation_profile",
        "genre_profile",
        "seedance_execution_plan",
        "seedance_boundary_review",
        "ai_shot_plan",
        "ai_video_boundary_review",
    },
    "adaptation_profile": {"change_authorization", "adaptation_bible"},
    "genre_profile": {"adaptation_profile"},
    "change_authorization": {"adaptation_decision_ledger"},
    "adaptation_bible": {"adaptation_decision_ledger"},
    "adaptation_decision_ledger": {
        "series_map",
        "series_boundary_review",
        "batch_outline",
        "batch_boundary_review",
        "episode_script",
        "episode_boundary_review",
        "seedance_execution_plan",
        "seedance_boundary_review",
        "ai_shot_plan",
        "ai_video_boundary_review",
    },
    "series_map": {"series_boundary_review", "batch_source_scope"},
    "series_boundary_review": {"series_plan_review"},
    "series_plan_review": {"batch_outline"},
    "batch_source_scope": {"batch_source_detail", "batch_outline"},
    "batch_source_detail": {"batch_outline"},
    "batch_outline": {"batch_boundary_review"},
    "batch_boundary_review": {"pilot_scripts"},
    "pilot_scripts": {"pilot_review"},
    "pilot_review": {"episode_script"},
    "episode_boundary_review": {
        "character_roster",
        "scene_catalog",
        "prop_costume_ledger",
        "dialogue_cue_sheet",
        "continuity_ledger",
        "seedance_execution_plan",
        "seedance_boundary_review",
        "ai_shot_plan",
        "ai_video_boundary_review",
    },
    "episode_script": {
        "episode_boundary_review",
        "ai_shot_plan",
        "rolling_summary",
        "character_roster",
        "scene_catalog",
        "prop_costume_ledger",
        "dialogue_cue_sheet",
        "continuity_ledger",
        "quality_report",
        "production_readiness_report",
        "delivery_manifest",
        "seedance_execution_plan",
        "seedance_boundary_review",
    },
    "character_roster": {
        "production_readiness_report", "delivery_manifest", "final_package",
        "seedance_execution_plan",
    },
    "scene_catalog": {
        "production_readiness_report", "delivery_manifest", "final_package",
        "seedance_execution_plan",
    },
    "prop_costume_ledger": {
        "production_readiness_report", "delivery_manifest", "final_package",
        "seedance_execution_plan",
    },
    "dialogue_cue_sheet": {
        "production_readiness_report", "delivery_manifest", "final_package",
        "seedance_execution_plan", "ai_shot_plan",
    },
    "continuity_ledger": {
        "production_readiness_report", "delivery_manifest", "final_package",
        "seedance_execution_plan",
        "batch_continuity_snapshot",
    },
    "quality_report": {"production_readiness_report", "delivery_manifest", "final_package"},
    "production_readiness_report": {"delivery_manifest", "final_package"},
    "batch_delivery_review": {"batch_delivery_manifest", "batch_package"},
    "batch_continuity_snapshot": {"cross_batch_continuity_review"},
    "cross_batch_continuity_review": {"series_delivery_manifest", "final_package"},
    "batch_delivery_manifest": {"batch_package", "series_delivery_manifest", "final_package"},
    "batch_package": {"series_delivery_manifest", "final_package"},
    "series_delivery_manifest": {"final_package"},
    "seedance_execution_plan": {"seedance_boundary_review", "generation_retry_ledger"},
    "style_anchor": {"seedance_execution_plan", "seedance_boundary_review", "ai_shot_plan", "ai_video_boundary_review", "ai_video_execution_plan"},
    "character_anchor": {"seedance_execution_plan", "seedance_boundary_review", "ai_shot_plan", "ai_video_boundary_review", "ai_video_execution_plan"},
    "scene_anchor": {"seedance_execution_plan", "seedance_boundary_review", "ai_shot_plan", "ai_video_boundary_review", "ai_video_execution_plan"},
    "prop_anchor": {"seedance_execution_plan", "seedance_boundary_review", "ai_shot_plan", "ai_video_boundary_review", "ai_video_execution_plan"},
    "model_capability_profile": {"ai_video_execution_plan"},
    "ai_shot_plan": {"ai_video_boundary_review", "ai_video_execution_plan", "generation_retry_ledger"},
    "ai_video_boundary_review": {"ai_video_execution_plan"},
    "delivery_manifest": {"final_package"},
}

# 每个元组元素是一组“至少命中一个”的直接上游类型；多个组必须全部满足。
# 这既保留试写/正式剧本的分支，也阻止以空依赖绕过制作链路。
REQUIRED_UPSTREAM_GROUPS: dict[str, tuple[frozenset[str], ...]] = {
    "source_corpus": (frozenset({"project_spec"}),),
    "chapter_analysis_registry": (frozenset({"source_corpus"}),),
    "rolling_source_progress": (
        frozenset({"source_corpus"}),
        frozenset({"chapter_analysis_registry"}),
    ),
    "source_event_index": (frozenset({"source_corpus"}),),
    "story_facts": (frozenset({"source_event_index"}),),
    "adaptation_profile": (
        frozenset({"project_spec"}),
        frozenset({"story_facts"}),
    ),
    "adaptation_bible": (frozenset({"adaptation_profile"}),),
    "genre_profile": (frozenset({"story_facts"}),),
    "change_authorization": (
        frozenset({"project_spec"}),
        frozenset({"story_facts"}),
        frozenset({"adaptation_profile"}),
    ),
    "adaptation_decision_ledger": (
        frozenset({"source_event_index"}),
        frozenset({"story_facts"}),
        frozenset({"adaptation_profile"}),
        frozenset({"adaptation_bible"}),
    ),
    "series_map": (
        frozenset({"adaptation_bible"}),
        frozenset({"adaptation_decision_ledger"}),
    ),
    "series_boundary_review": (
        frozenset({"source_event_index"}),
        frozenset({"story_facts"}),
        frozenset({"adaptation_decision_ledger"}),
        frozenset({"series_map"}),
    ),
    "series_plan_review": (
        frozenset({"source_event_index"}),
        frozenset({"adaptation_bible"}),
        frozenset({"adaptation_decision_ledger"}),
        frozenset({"series_map"}),
        frozenset({"series_boundary_review"}),
    ),
    "batch_outline": (
        frozenset({"adaptation_decision_ledger"}),
        frozenset({"series_map"}),
        frozenset({"series_plan_review"}),
    ),
    "batch_source_scope": (
        frozenset({"series_map"}),
        frozenset({"source_corpus"}),
    ),
    "batch_source_detail": (
        frozenset({"batch_source_scope"}),
        frozenset({"source_event_index"}),
        frozenset({"source_corpus"}),
    ),
    "batch_boundary_review": (
        frozenset({"source_event_index"}),
        frozenset({"story_facts"}),
        frozenset({"adaptation_decision_ledger"}),
        frozenset({"batch_outline"}),
    ),
    "pilot_scripts": (
        frozenset({"batch_outline"}),
        frozenset({"batch_boundary_review"}),
    ),
    "pilot_review": (frozenset({"pilot_scripts"}),),
    "style_anchor": (frozenset({"adaptation_bible"}),),
    "character_anchor": (frozenset({"character_roster"}),),
    "scene_anchor": (frozenset({"scene_catalog"}),),
    "prop_anchor": (frozenset({"prop_costume_ledger"}),),
    "generation_retry_ledger": (frozenset({"seedance_execution_plan", "ai_video_execution_plan"}),),
    "model_capability_profile": (frozenset({"project_spec"}),),
    "ai_shot_plan": (
        frozenset({"source_event_index"}),
        frozenset({"episode_script"}),
        frozenset({"episode_boundary_review"}),
        frozenset({"dialogue_cue_sheet"}),
        frozenset({"style_anchor"}),
        frozenset({"character_anchor"}),
        frozenset({"scene_anchor"}),
    ),
    "ai_video_boundary_review": (
        frozenset({"source_event_index"}),
        frozenset({"story_facts"}),
        frozenset({"adaptation_decision_ledger"}),
        frozenset({"ai_shot_plan"}),
    ),
    "ai_video_execution_plan": (
        frozenset({"ai_shot_plan"}),
        frozenset({"model_capability_profile"}),
    ),
    "episode_script": (
        frozenset({"adaptation_decision_ledger"}),
        frozenset({"batch_outline", "pilot_scripts"}),
        frozenset({"pilot_review"}),
    ),
    "episode_boundary_review": (
        frozenset({"source_event_index"}),
        frozenset({"story_facts"}),
        frozenset({"adaptation_decision_ledger"}),
        frozenset({"episode_script"}),
    ),
    "character_roster": (
        frozenset({"episode_script"}),
        frozenset({"episode_boundary_review"}),
    ),
    "scene_catalog": (
        frozenset({"episode_script"}),
        frozenset({"episode_boundary_review"}),
    ),
    "prop_costume_ledger": (
        frozenset({"episode_script"}),
        frozenset({"episode_boundary_review"}),
    ),
    "dialogue_cue_sheet": (
        frozenset({"source_corpus"}),
        frozenset({"source_event_index"}),
        frozenset({"episode_script"}),
        frozenset({"episode_boundary_review"}),
    ),
    "continuity_ledger": (
        frozenset({"episode_script"}),
        frozenset({"episode_boundary_review"}),
    ),
    "quality_report": (
        frozenset({"episode_script"}),
        frozenset({"character_roster"}),
        frozenset({"scene_catalog"}),
        frozenset({"prop_costume_ledger"}),
        frozenset({"dialogue_cue_sheet"}),
        frozenset({"continuity_ledger"}),
    ),
    "production_readiness_report": (
        frozenset({"episode_script"}),
        frozenset({"character_roster"}),
        frozenset({"scene_catalog"}),
        frozenset({"prop_costume_ledger"}),
        frozenset({"dialogue_cue_sheet"}),
        frozenset({"continuity_ledger"}),
        frozenset({"quality_report"}),
    ),
    "seedance_execution_plan": (
        frozenset({"source_event_index"}),
        frozenset({"story_facts"}),
        frozenset({"adaptation_decision_ledger"}),
        frozenset({"episode_script"}),
        frozenset({"episode_boundary_review"}),
        frozenset({"character_roster"}),
        frozenset({"scene_catalog"}),
        frozenset({"prop_costume_ledger"}),
        frozenset({"dialogue_cue_sheet"}),
        frozenset({"continuity_ledger"}),
    ),
    "seedance_boundary_review": (
        frozenset({"source_event_index"}),
        frozenset({"story_facts"}),
        frozenset({"adaptation_decision_ledger"}),
        frozenset({"episode_script"}),
        frozenset({"episode_boundary_review"}),
        frozenset({"seedance_execution_plan"}),
    ),
    "delivery_manifest": (
        frozenset({"project_spec"}),
        frozenset({"source_corpus"}),
        frozenset({"source_event_index"}),
        frozenset({"story_facts"}),
        frozenset({"adaptation_profile"}),
        frozenset({"adaptation_bible"}),
        frozenset({"adaptation_decision_ledger"}),
        frozenset({"series_map"}),
        frozenset({"series_boundary_review"}),
        frozenset({"series_plan_review"}),
        frozenset({"batch_boundary_review"}),
        frozenset({"pilot_review"}),
        frozenset({"episode_script"}),
        frozenset({"episode_boundary_review"}),
        frozenset({"character_roster"}),
        frozenset({"scene_catalog"}),
        frozenset({"prop_costume_ledger"}),
        frozenset({"dialogue_cue_sheet"}),
        frozenset({"continuity_ledger"}),
        frozenset({"quality_report"}),
        frozenset({"production_readiness_report"}),
    ),
    "batch_delivery_review": (
        frozenset({"series_map"}),
        frozenset({"series_boundary_review"}),
        frozenset({"batch_source_scope"}),
        frozenset({"batch_source_detail"}),
        frozenset({"batch_outline"}),
        frozenset({"batch_boundary_review"}),
        frozenset({"episode_script"}),
        frozenset({"episode_boundary_review"}),
        frozenset({"character_roster"}),
        frozenset({"scene_catalog"}),
        frozenset({"prop_costume_ledger"}),
        frozenset({"dialogue_cue_sheet"}),
        frozenset({"continuity_ledger"}),
        frozenset({"quality_report"}),
        frozenset({"production_readiness_report"}),
        frozenset({"batch_continuity_snapshot"}),
    ),
    "batch_continuity_snapshot": (
        frozenset({"episode_script"}),
        frozenset({"episode_boundary_review"}),
        frozenset({"continuity_ledger"}),
    ),
    "cross_batch_continuity_review": (
        frozenset({"batch_continuity_snapshot"}),
    ),
    "batch_delivery_manifest": (
        frozenset({"series_map"}),
        frozenset({"series_boundary_review"}),
        frozenset({"batch_source_scope"}),
        frozenset({"batch_source_detail"}),
        frozenset({"batch_outline"}),
        frozenset({"batch_boundary_review"}),
        frozenset({"episode_script"}),
        frozenset({"episode_boundary_review"}),
        frozenset({"character_roster"}),
        frozenset({"scene_catalog"}),
        frozenset({"prop_costume_ledger"}),
        frozenset({"dialogue_cue_sheet"}),
        frozenset({"continuity_ledger"}),
        frozenset({"quality_report"}),
        frozenset({"production_readiness_report"}),
        frozenset({"batch_delivery_review"}),
        frozenset({"batch_continuity_snapshot"}),
    ),
    "batch_package": (
        frozenset({"series_map"}),
        frozenset({"series_boundary_review"}),
        frozenset({"batch_source_scope"}),
        frozenset({"batch_source_detail"}),
        frozenset({"batch_outline"}),
        frozenset({"batch_boundary_review"}),
        frozenset({"episode_script"}),
        frozenset({"episode_boundary_review"}),
        frozenset({"character_roster"}),
        frozenset({"scene_catalog"}),
        frozenset({"prop_costume_ledger"}),
        frozenset({"dialogue_cue_sheet"}),
        frozenset({"continuity_ledger"}),
        frozenset({"quality_report"}),
        frozenset({"production_readiness_report"}),
        frozenset({"batch_delivery_review"}),
        frozenset({"batch_delivery_manifest"}),
        frozenset({"batch_continuity_snapshot"}),
    ),
    "series_delivery_manifest": (
        frozenset({"project_spec"}),
        frozenset({"series_map"}),
        frozenset({"series_boundary_review"}),
        frozenset({"series_plan_review"}),
        frozenset({"batch_delivery_manifest"}),
        frozenset({"batch_package"}),
        frozenset({"batch_continuity_snapshot"}),
        frozenset({"cross_batch_continuity_review"}),
    ),
    "final_package": (
        frozenset({"delivery_manifest", "series_delivery_manifest"}),
    ),
}

# 这些上游允许存在但并非所有项目都必需；例如没有主要新增时不会有变更授权记录。
OPTIONAL_UPSTREAM_TYPES: dict[str, frozenset[str]] = {
    "adaptation_decision_ledger": frozenset({"change_authorization"}),
    "genre_profile": frozenset({"source_event_index", "project_spec"}),
    "adaptation_profile": frozenset({"genre_profile"}),
    "batch_outline": frozenset({"batch_source_scope", "batch_source_detail"}),
    "rolling_summary": frozenset({"episode_script", "episode_boundary_review", "continuity_ledger"}),
    "delivery_manifest": frozenset({"change_authorization"}),
    "final_package": frozenset({"change_authorization"}),
    "ai_shot_plan": frozenset({
        "source_event_index",
        "story_facts",
        "adaptation_decision_ledger",
        "prop_anchor",
        "character_roster",
        "scene_catalog",
        "prop_costume_ledger",
        "continuity_ledger",
    }),
    "ai_video_execution_plan": frozenset({
        "source_event_index",
        "story_facts",
        "adaptation_decision_ledger",
        "episode_script",
        "episode_boundary_review",
        "dialogue_cue_sheet",
        "style_anchor",
        "character_anchor",
        "scene_anchor",
        "prop_anchor",
        "continuity_ledger",
        "ai_video_boundary_review",
    }),
}
OPTIONAL_UPSTREAM_TYPES["final_package"] = frozenset(
    set(ARTIFACT_TYPES) - {"final_package", "delivery_manifest", "series_delivery_manifest"}
)

# 内容边界报告先绑定仍处于 awaiting_approval 的目标稿并获确认，随后目标稿
# 才能通过门禁。这里刻意不把报告写成目标稿的 depends_on，以免制造循环依赖；
# 目标稿的可用性由下方的精确反向绑定检查持续保证。
BOUNDARY_REVIEW_FOR_TARGET: dict[str, str] = {
    "series_map": "series_boundary_review",
    "batch_outline": "batch_boundary_review",
    "episode_script": "episode_boundary_review",
    "seedance_execution_plan": "seedance_boundary_review",
    "ai_shot_plan": "ai_video_boundary_review",
}
BOUNDARY_TARGET_FOR_REVIEW: dict[str, str] = {
    review_type: target_type
    for target_type, review_type in BOUNDARY_REVIEW_FOR_TARGET.items()
}

ARTIFACT_STAGE = {
    "project_spec": "project_setup",
    "source_review": "source_analysis",
    "source_corpus": "source_analysis",
    "chapter_analysis_registry": "source_analysis",
    "rolling_source_progress": "source_analysis",
    "source_event_index": "source_analysis",
    "story_facts": "source_analysis",
    "adaptation_profile": "adaptation_positioning",
    "genre_profile": "adaptation_positioning",
    "rolling_summary": "batch_writing",
    "change_authorization": "adaptation_bible",
    "adaptation_bible": "adaptation_bible",
    "adaptation_decision_ledger": "adaptation_bible",
    "series_map": "series_planning",
    "series_boundary_review": "series_planning",
    "series_plan_review": "series_planning",
    "batch_source_scope": "batch_outline",
    "batch_source_detail": "batch_outline",
    "batch_outline": "batch_outline",
    "batch_boundary_review": "batch_outline",
    "pilot_scripts": "pilot_writing",
    "pilot_review": "pilot_writing",
    "episode_script": "batch_writing",
    "episode_boundary_review": "batch_writing",
    "character_roster": "quality_review",
    "scene_catalog": "quality_review",
    "prop_costume_ledger": "quality_review",
    "dialogue_cue_sheet": "quality_review",
    "continuity_ledger": "quality_review",
    "batch_continuity_snapshot": "quality_review",
    "cross_batch_continuity_review": "final_delivery",
    "quality_report": "quality_review",
    "production_readiness_report": "quality_review",
    "seedance_execution_plan": "final_delivery",
    "seedance_boundary_review": "final_delivery",
    "model_capability_profile": "final_delivery",
    "ai_shot_plan": "final_delivery",
    "ai_video_boundary_review": "final_delivery",
    "ai_video_execution_plan": "final_delivery",
    "batch_delivery_review": "final_delivery",
    "batch_delivery_manifest": "final_delivery",
    "batch_package": "final_delivery",
    "series_delivery_manifest": "final_delivery",
    "delivery_manifest": "final_delivery",
    "final_package": "final_delivery",
}

ARTIFACT_STATUSES = {
    "draft",
    "awaiting_approval",
    "confirmed",
    "stale",
    "superseded",
}

BATCH_ID_RE = re.compile(r"B\d{2,4}")
EPISODE_ID_RE = re.compile(r"E\d{3,6}")

HANDOFF_REQUIRED_TYPES = (
    "project_spec",
    "source_corpus",
    "source_event_index",
    "story_facts",
    "adaptation_profile",
    "adaptation_bible",
    "adaptation_decision_ledger",
    "series_map",
    "series_boundary_review",
    "series_plan_review",
    "batch_boundary_review",
    "pilot_review",
    "episode_boundary_review",
    "character_roster",
    "scene_catalog",
    "prop_costume_ledger",
    "dialogue_cue_sheet",
    "continuity_ledger",
    "quality_report",
    "production_readiness_report",
)

PACKAGE_TYPE_DIRECTORY = {
    "project_spec": "01_全剧规划",
    "adaptation_profile": "01_全剧规划",
    "change_authorization": "01_全剧规划",
    "adaptation_bible": "01_全剧规划",
    "adaptation_decision_ledger": "01_全剧规划",
    "series_map": "01_全剧规划",
    "batch_source_scope": "01_全剧规划",
    "batch_source_detail": "01_全剧规划",
    "genre_profile": "01_全剧规划",
    "rolling_summary": "04_连续性质检",
    "episode_script": "02_分集剧本",
    "character_roster": "03_制作提取表",
    "scene_catalog": "03_制作提取表",
    "prop_costume_ledger": "03_制作提取表",
    "dialogue_cue_sheet": "03_制作提取表",
    "continuity_ledger": "04_连续性质检",
    "batch_continuity_snapshot": "04_连续性质检",
    "cross_batch_continuity_review": "04_连续性质检",
    "series_boundary_review": "04_连续性质检",
    "series_plan_review": "04_连续性质检",
    "batch_outline": "01_全剧规划",
    "batch_boundary_review": "04_连续性质检",
    "pilot_review": "04_连续性质检",
    "episode_boundary_review": "04_连续性质检",
    "quality_report": "04_连续性质检",
    "production_readiness_report": "04_连续性质检",
    "seedance_execution_plan": "05_AI视频执行包",
    "seedance_boundary_review": "04_连续性质检",
    "style_anchor": "05_AI视频执行包",
    "character_anchor": "05_AI视频执行包",
    "scene_anchor": "05_AI视频执行包",
    "prop_anchor": "05_AI视频执行包",
    "generation_retry_ledger": "05_AI视频执行包",
    "model_capability_profile": "05_AI视频执行包",
    "ai_shot_plan": "05_AI视频执行包",
    "ai_video_execution_plan": "05_AI视频执行包",
    "ai_video_boundary_review": "04_连续性质检",
    "batch_delivery_review": "04_连续性质检",
    "batch_delivery_manifest": "02_批次包",
    "batch_package": "02_批次包",
}

STAGE_COMPLETION_ARTIFACTS = {
    "project_setup": ("project_spec",),
    "source_analysis": ("source_corpus", "source_event_index", "story_facts"),
    "adaptation_positioning": ("adaptation_profile",),
    "adaptation_bible": ("adaptation_bible", "adaptation_decision_ledger"),
    "series_planning": ("series_map", "series_boundary_review", "series_plan_review"),
    "batch_outline": ("batch_outline", "batch_boundary_review"),
    "pilot_writing": ("pilot_scripts", "pilot_review"),
    "batch_writing": ("episode_script", "episode_boundary_review"),
    "quality_review": (
        "character_roster",
        "scene_catalog",
        "prop_costume_ledger",
        "dialogue_cue_sheet",
        "continuity_ledger",
        "quality_report",
        "production_readiness_report",
    ),
    "final_delivery": ("delivery_manifest", "final_package"),
}


class ToolError(Exception):
    """用户可修正的 CLI 错误。"""


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_json_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ToolError(f"无法读取 JSON：{path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ToolError(f"JSON 顶层必须是对象：{path}")
    return payload


def resolve_project_input(project_path: Path, raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    path = path if path.is_absolute() else project_path / path
    path = path.resolve()
    if project_path != path and project_path not in path.parents:
        raise ToolError("输入路径必须位于项目目录内")
    if not path.exists():
        raise ToolError(f"输入路径不存在：{path}")
    return path


def resolve_project_output(project_path: Path, raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    path = path if path.is_absolute() else project_path / path
    path = path.resolve()
    if project_path != path and project_path not in path.parents:
        raise ToolError("输出路径必须位于项目目录内")
    return path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False))


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        # 文件已持久化后，尽可能同步目录项。Windows 不支持时安全跳过。
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
        except (AttributeError, OSError):
            return
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def state_path(project: str | Path) -> Path:
    return Path(project).expanduser().resolve() / STATE_FILENAME


def load_state(project: str | Path) -> tuple[Path, dict[str, Any]]:
    project_path = Path(project).expanduser().resolve()
    path = project_path / STATE_FILENAME
    if not path.is_file():
        raise ToolError(f"未找到项目状态文件：{path}")
    try:
        with path.open("r", encoding="utf-8") as handle:
            state = json.load(handle)
    except json.JSONDecodeError as exc:
        raise ToolError(f"项目状态 JSON 损坏：{exc}") from exc
    except OSError as exc:
        raise ToolError(f"无法读取项目状态：{exc}") from exc
    if not isinstance(state, dict):
        raise ToolError("项目状态顶层必须是 JSON 对象")
    return project_path, state


def save_state(project_path: Path, state: dict[str, Any]) -> None:
    state["updated_at"] = now_iso()
    atomic_write_json(project_path / STATE_FILENAME, state)


def safe_relative_path(path: Path, project_path: Path) -> str:
    resolved = path.expanduser().resolve()
    try:
        relative = resolved.relative_to(project_path.resolve())
    except ValueError as exc:
        raise ToolError(f"制品必须位于项目目录内：{resolved}") from exc
    if relative == Path(STATE_FILENAME):
        raise ToolError(f"{STATE_FILENAME} 不能注册为制品")
    return relative.as_posix()


def path_from_record(project_path: Path, stored_path: Any) -> Path | None:
    if not isinstance(stored_path, str) or not stored_path or Path(stored_path).is_absolute():
        return None
    candidate = (project_path / stored_path).resolve()
    try:
        candidate.relative_to(project_path.resolve())
    except ValueError:
        return None
    return candidate


def safe_copy_source(source: Path, destination_directory: Path) -> Path:
    """用排他创建保证即使同名文件或并发初始化也不覆盖。"""
    stem = source.stem or "source"
    suffix = source.suffix
    attempt = 1
    while True:
        filename = source.name if attempt == 1 else f"{stem} ({attempt}){suffix}"
        destination = destination_directory / filename
        try:
            output_handle = destination.open("xb")
        except FileExistsError:
            attempt += 1
            continue
        try:
            with source.open("rb") as input_handle, output_handle:
                shutil.copyfileobj(input_handle, output_handle, length=1024 * 1024)
                output_handle.flush()
                os.fsync(output_handle.fileno())
        except Exception:
            # destination 由本次的 xb 创建，复制中断时只删该半成品。
            destination.unlink(missing_ok=True)
            raise
        try:
            shutil.copystat(source, destination, follow_symlinks=True)
        except OSError:
            # 时间戳不影响源文件完整性。
            pass
        return destination


def artifact_type(artifact_key: str) -> str:
    base = artifact_key.split(":", 1)[0]
    if base not in ARTIFACT_TYPES:
        allowed = "、".join(sorted(ARTIFACT_TYPES))
        raise ToolError(
            f"未知制品类型 {base!r}。可用类型：{allowed}；"
            "可使用“类型:范围”区分批次或集，如 episode_script:E001"
        )
    if ":" in artifact_key and not artifact_key.split(":", 1)[1].strip():
        raise ToolError("制品 key 的范围不能为空")
    if not re.fullmatch(r"[A-Za-z0-9_.:-]+", artifact_key):
        raise ToolError("制品 key 只能包含字母、数字、_、-、.、:")
    return base


def episode_scope_ids(artifact_key: str) -> set[int] | None:
    if ":" not in artifact_key:
        return None
    scope = artifact_key.split(":", 1)[1]
    matches = [int(value) for value in re.findall(r"E(\d{1,6})", scope, re.IGNORECASE)]
    if not matches:
        return None
    if len(matches) == 2 and "-" in scope and matches[0] <= matches[1]:
        return set(range(matches[0], matches[1] + 1))
    return set(matches)


def artifact_scopes_overlap(source_key: str, target_key: str) -> bool:
    source_ids = episode_scope_ids(source_key)
    target_ids = episode_scope_ids(target_key)
    if source_ids is None or target_ids is None:
        return True
    return bool(source_ids & target_ids)


def version_sort_key(record: dict[str, Any]) -> int:
    version = record.get("version")
    return version if type(version) is int else -1


def downstream_types(source_type: str) -> set[str]:
    discovered: set[str] = set()
    pending = list(DEPENDENCY_GRAPH.get(source_type, set()))
    while pending:
        candidate = pending.pop()
        if candidate in discovered:
            continue
        discovered.add(candidate)
        pending.extend(DEPENDENCY_GRAPH.get(candidate, set()))
    return discovered


def latest_record(state: dict[str, Any], key: str) -> dict[str, Any] | None:
    records = state.get("artifacts", {}).get(key, [])
    if not isinstance(records, list) or not records:
        return None
    valid = [record for record in records if isinstance(record, dict)]
    if not valid:
        return None
    return max(valid, key=version_sort_key)


def confirmed_records_before(
    state: dict[str, Any], key: str, version: int
) -> list[dict[str, Any]]:
    records = state.get("artifacts", {}).get(key, [])
    return [
        record
        for record in records
        if isinstance(record, dict)
        and type(record.get("version")) is int
        and record["version"] < version
        and record.get("status") == "confirmed"
    ]


def invalidate_approvals(
    state: dict[str, Any], key: str, version: int, reason: str, timestamp: str
) -> None:
    for approval in state.get("approvals", []):
        if (
            isinstance(approval, dict)
            and approval.get("artifact_key") == key
            and approval.get("version") == version
            and not approval.get("invalidated_at")
        ):
            approval["invalidated_at"] = timestamp
            approval["invalidation_reason"] = reason


def has_active_approval(
    state: dict[str, Any], key: str, version: int | None
) -> bool:
    if type(version) is not int:
        return False
    return any(
        isinstance(approval, dict)
        and approval.get("artifact_key") == key
        and approval.get("version") == version
        and not approval.get("invalidated_at")
        for approval in state.get("approvals", [])
    )


def recompute_current_stage(state: dict[str, Any]) -> None:
    stages = state.get("stages")
    if not isinstance(stages, dict):
        return
    for priority_statuses in ({"blocked", "stale"}, {"in_progress", "awaiting_approval"}):
        for stage_key in STAGES:
            stage = stages.get(stage_key)
            if isinstance(stage, dict) and stage.get("status") in priority_statuses:
                state["current_stage"] = stage_key
                return


def mark_downstream_stale(
    state: dict[str, Any],
    source_key: str,
    reason: str,
    timestamp: str,
    source_versions: Iterable[int],
) -> list[dict[str, Any]]:
    affected: list[dict[str, Any]] = []
    artifacts = state.get("artifacts", {})
    if not isinstance(artifacts, dict):
        return affected
    invalidated_refs = {(source_key, version) for version in source_versions}
    changed = True
    while changed:
        changed = False
        for key, records in artifacts.items():
            if not isinstance(key, str) or not isinstance(records, list):
                continue
            valid_records = [item for item in records if isinstance(item, dict)]
            if not valid_records:
                continue
            current = max(valid_records, key=version_sort_key)
            current_ref = (key, current.get("version"))
            if current_ref in invalidated_refs:
                continue
            dependency_refs = {
                (dependency.get("artifact_key"), dependency.get("version"))
                for dependency in current.get("depends_on", [])
                if isinstance(dependency, dict)
            }
            if not dependency_refs.intersection(invalidated_refs):
                continue
            if current.get("status") not in {"confirmed", "awaiting_approval", "draft"}:
                continue
            previous_status = current.get("status")
            current["status"] = "stale"
            current["stale_at"] = timestamp
            current["stale_reason"] = reason
            invalidate_approvals(state, key, current.get("version"), reason, timestamp)
            try:
                current_type = artifact_type(key)
            except ToolError:
                current_type = ""
            stage_key = ARTIFACT_STAGE.get(current_type)
            stage = state.get("stages", {}).get(stage_key) if stage_key else None
            if isinstance(stage, dict):
                stage["status"] = "stale"
                stage["updated_at"] = timestamp
                stage["note"] = reason
            affected.append(
                {
                    "artifact_key": key,
                    "version": current.get("version"),
                    "previous_status": previous_status,
                }
            )
            invalidated_refs.add(current_ref)
            changed = True
    if affected:
        recompute_current_stage(state)
    return affected


def append_history(state: dict[str, Any], event: str, details: dict[str, Any]) -> None:
    history = state.setdefault("history", [])
    if not isinstance(history, list):
        raise ToolError("项目 history 结构无效，请先运行 validate-project")
    history.append(
        {
            "event_id": str(uuid.uuid4()),
            "event": event,
            "at": now_iso(),
            **details,
        }
    )


def confirm_record(
    state: dict[str, Any], key: str, record: dict[str, Any], reason: str
) -> list[dict[str, Any]]:
    version = record["version"]
    previous_confirmed = confirmed_records_before(state, key, version)
    timestamp = now_iso()
    if previous_confirmed:
        previous_versions = [old_record["version"] for old_record in previous_confirmed]
        for old_record in previous_confirmed:
            old_record["status"] = "superseded"
            old_record["superseded_at"] = timestamp
            old_record["superseded_by_version"] = version
            invalidate_approvals(state, key, old_record["version"], reason, timestamp)
        affected = mark_downstream_stale(state, key, reason, timestamp, previous_versions)
    else:
        affected = []
    record["status"] = "confirmed"
    record["confirmed_at"] = timestamp
    record.pop("stale_at", None)
    record.pop("stale_reason", None)
    return affected


def parse_dependency(value: str, state: dict[str, Any]) -> dict[str, Any]:
    if "@" in value:
        key, raw_version = value.rsplit("@", 1)
        try:
            version = int(raw_version)
        except ValueError as exc:
            raise ToolError(f"依赖版本必须是整数：{value}") from exc
    else:
        key = value
        current = latest_record(state, key)
        if current is None:
            raise ToolError(f"依赖制品不存在：{key}")
        version = current.get("version")
    artifact_type(key)
    records = state.get("artifacts", {}).get(key, [])
    selected = next(
        (
            record
            for record in records
            if isinstance(record, dict) and record.get("version") == version
        ),
        None,
    )
    if selected is None:
        raise ToolError(f"依赖制品版本不存在：{key}@{version}")
    current = latest_record(state, key)
    if current is None or current.get("version") != version:
        raise ToolError(f"依赖必须使用最新版：{key}@{version}")
    if selected.get("status") not in {"confirmed", "awaiting_approval"}:
        raise ToolError(
            f"依赖制品不可用：{key}@{version} 状态为 {selected.get('status')}"
        )
    return {"artifact_key": key, "version": version}


def validate_dependency_shape(
    artifact_key: str, dependencies: list[dict[str, Any]]
) -> None:
    artifact_kind = artifact_type(artifact_key)
    dependency_types: set[str] = set()
    dependency_refs: set[tuple[str, Any]] = set()
    for dependency in dependencies:
        key = dependency.get("artifact_key")
        if not isinstance(key, str):
            raise ToolError("依赖制品 key 无效")
        reference = (key, dependency.get("version"))
        if reference in dependency_refs:
            raise ToolError(f"制品依赖不能重复：{key}@{dependency.get('version')}")
        dependency_refs.add(reference)
        dependency_types.add(artifact_type(key))
        target_scope = episode_scope_ids(artifact_key)
        dependency_scope = episode_scope_ids(key)
        if (
            target_scope is not None
            and dependency_scope is not None
            and not target_scope.issubset(dependency_scope)
        ):
            raise ToolError(
                f"依赖剧集范围不足：{artifact_key} 不能绑定 {key}"
            )
    required_groups = REQUIRED_UPSTREAM_GROUPS.get(artifact_kind, ())
    allowed_types = set().union(*required_groups) if required_groups else set()
    allowed_types.update(OPTIONAL_UPSTREAM_TYPES.get(artifact_kind, frozenset()))
    unexpected = dependency_types - allowed_types
    if unexpected:
        raise ToolError(
            f"{artifact_kind} 存在不允许的反向或无关依赖：{', '.join(sorted(unexpected))}"
        )
    missing_groups = [
        sorted(group) for group in required_groups if not dependency_types.intersection(group)
    ]
    if missing_groups:
        labels = ["/".join(ARTIFACT_TYPES[item] for item in group) for group in missing_groups]
        raise ToolError(
            f"{ARTIFACT_TYPES[artifact_kind]}缺少必需上游：{'、'.join(labels)}"
        )


def record_is_shallow_current(
    state: dict[str, Any],
    key: str,
    record: dict[str, Any],
    project_path: Path | None,
    allowed_statuses: frozenset[str],
) -> bool:
    """检查当前版本与文件完整性，但不递归检查依赖。

    边界报告与其目标稿存在有意的双向门禁关系：报告依赖目标稿版本，目标稿
    又必须先有报告才能确认。只在这条关系上使用浅检查以打破递归，其余依赖
    仍使用完整可用性检查。
    """
    version = record.get("version")
    if type(version) is not int or latest_record(state, key) is not record:
        return False
    status = record.get("status")
    if status not in allowed_statuses:
        return False
    if status == "confirmed" and not has_active_approval(state, key, version):
        return False
    if project_path is not None:
        artifact_path = path_from_record(project_path, record.get("path"))
        if (
            artifact_path is None
            or not artifact_path.is_file()
            or sha256_file(artifact_path) != record.get("sha256")
            or artifact_path.stat().st_size != record.get("size_bytes")
        ):
            return False
    return True


def matching_boundary_review(
    state: dict[str, Any],
    target_key: str,
    target_record: dict[str, Any],
    project_path: Path | None,
    visiting: set[tuple[str, int]] | None = None,
) -> tuple[str, dict[str, Any]] | None:
    """返回精确绑定目标当前版本且结论通过的已确认边界报告。"""
    target_type = artifact_type(target_key)
    review_type = BOUNDARY_REVIEW_FOR_TARGET.get(target_type)
    target_version = target_record.get("version")
    if review_type is None or type(target_version) is not int:
        return None
    target_ref = (target_key, target_version)
    matches: list[tuple[str, dict[str, Any]]] = []
    for review_key, review_record in latest_records_of_type(state, review_type):
        if target_ref not in record_dependency_refs(review_record):
            continue
        if not confirmed_record_is_usable(
            state, review_key, review_record, project_path, visiting
        ):
            continue
        if project_path is None:
            matches.append((review_key, review_record))
            continue
        if validate_structured_development_artifact(
            project_path, state, review_key, review_record
        ):
            continue
        report_path = path_from_record(project_path, review_record.get("path"))
        try:
            report = (
                json.loads(report_path.read_text(encoding="utf-8-sig"))
                if report_path and report_path.suffix.lower() == ".json"
                else None
            )
        except (OSError, UnicodeError, json.JSONDecodeError):
            report = None
        if isinstance(report, dict) and report.get("conclusion") == "passed":
            matches.append((review_key, review_record))
    return matches[0] if len(matches) == 1 else None


def confirmed_record_is_usable(
    state: dict[str, Any],
    key: str,
    record: dict[str, Any],
    project_path: Path | None = None,
    visiting: set[tuple[str, int]] | None = None,
) -> bool:
    version = record.get("version")
    reference = (key, version)
    if type(version) is not int:
        return False
    current = latest_record(state, key)
    if current is not record or record.get("status") != "confirmed":
        return False
    if not has_active_approval(state, key, version):
        return False
    if project_path is not None:
        artifact_path = path_from_record(project_path, record.get("path"))
        if (
            artifact_path is None
            or not artifact_path.is_file()
            or sha256_file(artifact_path) != record.get("sha256")
            or artifact_path.stat().st_size != record.get("size_bytes")
        ):
            return False
    visiting = set() if visiting is None else set(visiting)
    if reference in visiting:
        return False
    visiting.add(reference)
    dependencies = record.get("depends_on")
    if not isinstance(dependencies, list):
        return False
    try:
        validate_dependency_shape(key, dependencies)
    except ToolError:
        return False
    record_type = artifact_type(key)
    review_target_type = BOUNDARY_TARGET_FOR_REVIEW.get(record_type)
    for dependency in dependencies:
        if not isinstance(dependency, dict):
            return False
        dep_key = dependency.get("artifact_key")
        dep_version = dependency.get("version")
        dep_record = latest_record(state, dep_key) if isinstance(dep_key, str) else None
        if dep_record is None or dep_record.get("version") != dep_version:
            return False
        dep_type = artifact_type(dep_key)
        if review_target_type is not None and dep_type == review_target_type:
            if not record_is_shallow_current(
                state,
                dep_key,
                dep_record,
                project_path,
                frozenset({"awaiting_approval", "confirmed"}),
            ):
                return False
            continue
        if not confirmed_record_is_usable(
            state, dep_key, dep_record, project_path, visiting
        ):
            return False
    if record_type in BOUNDARY_REVIEW_FOR_TARGET and matching_boundary_review(
        state, key, record, project_path, visiting
    ) is None:
        return False
    return True


def load_project_spec_payload(
    project_path: Path, record: dict[str, Any]
) -> dict[str, Any] | None:
    """读取项目规格的规范 JSON；Markdown 等旧格式返回 None（不报错）。"""
    path = path_from_record(project_path, record.get("path"))
    try:
        payload = (
            json.loads(path.read_text(encoding="utf-8-sig"))
            if path and path.suffix.lower() == ".json"
            else None
        )
    except (OSError, UnicodeError, json.JSONDecodeError):
        payload = None
    return payload if isinstance(payload, dict) else None


def validate_project_spec_rights(
    project_path: Path, record: dict[str, Any]
) -> str | None:
    """approve 前校验 rights_mode：非法枚举拒绝确认；unclear 返回一次性提示文本。

    旧项目规格缺少 rights_mode 字段时按 owned 语义处理，不报错。
    """
    payload = load_project_spec_payload(project_path, record)
    if payload is None:
        return None
    mode = payload.get("rights_mode", DEFAULT_RIGHTS_MODE)
    if not isinstance(mode, str) or mode not in RIGHTS_MODES:
        raise ToolError(
            f"项目规格 rights_mode 非法：{mode!r}；"
            f"只允许 {'/'.join(RIGHTS_MODES)}，缺省字段按 owned 语义处理"
        )
    note = payload.get("rights_note")
    if note is not None and not isinstance(note, str):
        raise ToolError("项目规格 rights_note 必须是字符串（记录授权范围）")
    if mode == "unclear":
        return RIGHTS_UNCLEAR_NOTICE
    return None


def validate_ratio_option(option_name: str, value: float) -> None:
    if not math.isfinite(value) or value < 0 or value > 1:
        raise ToolError(f"{option_name} 必须是 0 到 1 之间的有限数字")


def duration_policy_issues(payload: dict[str, Any]) -> list[str]:
    """校验项目规格的时长契约字段，返回人类可读的问题描述列表。

    全部字段可选：项目未声明目标时长时返回空列表，下游使用 60 秒默认值。
    显式项目规格始终优先于默认生成策略。
    """
    problems: list[str] = []
    target = payload.get("target_duration_seconds")
    if target is not None and (type(target) is not int or target <= 0):
        problems.append("target_duration_seconds 必须是大于0的整数秒（单集目标时长）")

    policy = payload.get("duration_policy")
    if policy is None:
        return problems
    if not isinstance(policy, dict):
        problems.append("duration_policy 必须是对象")
        return problems

    if "inflation_redline_ratio" in policy:
        problems.append(
            "duration_policy.inflation_redline_ratio 已移除：旧字段没有可靠的原著范围字数消费者，"
            "请删除该字段后重新登记项目规格"
        )

    for field in ("tolerance_ratio",):
        value = policy.get(field)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            problems.append(f"duration_policy.{field} 必须是 0 到 1 之间的数字")
            continue
        try:
            validate_ratio_option(f"duration_policy.{field}", value)
        except ToolError as exc:
            problems.append(str(exc))

    rate = policy.get("dialogue_chars_per_second")
    if rate is not None:
        if (
            not isinstance(rate, list)
            or len(rate) != 2
            or any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in rate)
        ):
            problems.append("duration_policy.dialogue_chars_per_second 必须是 [下限, 上限] 两个数字")
        elif not all(math.isfinite(item) and item > 0 for item in rate) or rate[0] > rate[1]:
            problems.append("duration_policy.dialogue_chars_per_second 必须是递增的正数区间")
    return problems


def validate_project_spec_duration(
    project_path: Path, record: dict[str, Any]
) -> None:
    """approve 前校验项目规格的时长契约；字段非法时拒绝确认。"""
    payload = load_project_spec_payload(project_path, record)
    if payload is None:
        return
    problems = duration_policy_issues(payload)
    if problems:
        raise ToolError("项目规格时长契约非法：" + "；".join(problems))


def default_source_policy() -> dict[str, Any]:
    return {
        "source_kind": DEFAULT_SOURCE_KIND,
        "official_review_enabled": False,
        "official_url": None,
        "content_authority": "uploaded_files",
    }


def build_source_policy(
    source_kind: str,
    official_review_enabled: bool,
    official_url: str | None,
) -> dict[str, Any]:
    if not isinstance(source_kind, str) or source_kind not in SOURCE_KINDS:
        raise ToolError(f"source_kind 只允许 {'/'.join(SOURCE_KINDS)}")
    if type(official_review_enabled) is not bool:
        raise ToolError("official_review_enabled 必须是布尔值")
    if official_url is not None and not isinstance(official_url, str):
        raise ToolError("official_url 必须是字符串或 null")
    if source_kind != "published_novel" and (
        official_review_enabled or official_url is not None
    ):
        raise ToolError("只有 published_novel 可以开启官网审核或登记 official_url")
    if official_review_enabled:
        if not isinstance(official_url, str) or not re.fullmatch(
            r"https?://\S+", official_url.strip()
        ):
            raise ToolError("开启官网审核时必须提供 HTTP 或 HTTPS official_url")
    elif official_url is not None:
        raise ToolError("未开启官网审核时不能登记 official_url")
    return {
        "source_kind": source_kind,
        "official_review_enabled": official_review_enabled,
        "official_url": official_url.strip() if isinstance(official_url, str) else None,
        "content_authority": "uploaded_files",
    }


def rights_notice_already_shown(state: dict[str, Any]) -> bool:
    history = state.get("history")
    if not isinstance(history, list):
        return False
    return any(
        isinstance(item, dict) and item.get("event") == "rights_unclear_notified"
        for item in history
    )


def pending_rights_notice(project_path: Path, state: dict[str, Any]) -> str | None:
    """rights_mode=unclear 且尚未提示过时返回提示文本；提示不是错误，不阻塞。"""
    if rights_notice_already_shown(state):
        return None
    candidates = latest_records_of_type(state, "project_spec")
    if len(candidates) != 1:
        return None
    _, record = candidates[0]
    payload = load_project_spec_payload(project_path, record)
    if payload is None:
        return None
    if payload.get("rights_mode", DEFAULT_RIGHTS_MODE) == "unclear":
        return RIGHTS_UNCLEAR_NOTICE
    return None


def parse_chinese_numeral(text: str) -> int | None:
    """解析常见中文数字（十/二十/一百二十三/二百零五）；解析不了返回 None。"""
    total = 0
    current = 0
    matched = False
    for character in text:
        if character in CHINESE_DIGIT_VALUES:
            current = CHINESE_DIGIT_VALUES[character]
            matched = True
        elif character in CHINESE_UNIT_VALUES:
            unit = CHINESE_UNIT_VALUES[character]
            total += (current or 1) * unit
            current = 0
            matched = True
        else:
            return None
    return total + current if matched else None


def parse_chapter_number(raw: str) -> int | None:
    normalized = raw.translate(str.maketrans("０１２３４５６７８９", "0123456789")).strip()
    if normalized.isdigit():
        try:
            return int(normalized)
        except ValueError:
            return None
    return parse_chinese_numeral(normalized)


def extract_chapter_numbers(text: str) -> list[int]:
    numbers: list[int] = []
    for match in CHAPTER_HEADING_PATTERN.finditer(text):
        value = parse_chapter_number(match.group(1))
        if value is not None and value > 0:
            numbers.append(value)
    return numbers


def is_garbled_character(character: str) -> bool:
    if character == "�":
        return True
    category = unicodedata.category(character)
    if category in {"Cn", "Co", "Cs"}:
        return True
    return category == "Cc" and character not in "\n\r\t"


def analyze_source_text_file(path: Path) -> dict[str, Any]:
    """对单个文本来源做入料体检；只统计不判罪，异常字符计入乱码率。"""
    text = path.read_bytes().decode("utf-8-sig", errors="replace")
    visible_chars = sum(1 for character in text if not character.isspace())
    chinese_chars = sum(
        1
        for character in text
        if "一" <= character <= "鿿" or "㐀" <= character <= "䶿"
    )
    garbled_chars = sum(1 for character in text if is_garbled_character(character))
    garble_ratio = round(garbled_chars / visible_chars, 6) if visible_chars else 0.0
    chapter_numbers = extract_chapter_numbers(text)
    stripped = text.rstrip()
    tail_sample = " ".join(stripped[-40:].split()) if stripped else ""
    suspected_truncation = bool(stripped) and stripped[-1] not in SENTENCE_END_CHARS
    return {
        "analyzable": True,
        "visible_chars": visible_chars,
        "chinese_chars": chinese_chars,
        "garbled_chars": garbled_chars,
        "garble_ratio": garble_ratio,
        "chapter_numbers": chapter_numbers,
        "tail_sample": tail_sample,
        "suspected_truncation": suspected_truncation,
    }


def run_intake_check(
    project_path: Path,
    source_records: list[dict[str, Any]],
    garble_threshold: float = DEFAULT_GARBLE_THRESHOLD,
    expected_episodes: int | None = None,
) -> dict[str, Any]:
    """入料体检：体检只提示、不阻塞，报告写入 01_原著解析/入料体检.json。"""
    issues: list[dict[str, Any]] = []
    source_reports: list[dict[str, Any]] = []
    all_chapters: list[int] = []
    total_visible_chars = 0
    total_chinese_chars = 0
    max_garble_ratio = 0.0
    any_truncation = False
    any_analyzable = False
    for record in source_records:
        if not isinstance(record, dict):
            continue
        filename = record.get("filename") or record.get("stored_path") or "未知来源"
        entry: dict[str, Any] = {
            "source_id": record.get("source_id"),
            "filename": filename,
            "stored_path": record.get("stored_path"),
        }
        stored = path_from_record(project_path, record.get("stored_path"))
        if stored is None or not stored.is_file():
            entry.update({"analyzable": False, "reason": "来源文件不存在或路径无效"})
            issues.append(
                issue(
                    "source_file_unreadable",
                    f"来源无法读取，未做文本体检：{filename}",
                    level="warning",
                    filename=filename,
                )
            )
            source_reports.append(entry)
            continue
        if stored.suffix.lower() not in INTAKE_ANALYZABLE_SUFFIXES:
            entry.update(
                {
                    "analyzable": False,
                    "reason": "非纯文本格式（如 PDF/DOCX/扫描件），"
                    "需先经文档读取能力标准化后再体检",
                }
            )
            issues.append(
                issue(
                    "source_not_plain_text",
                    f"来源不是纯文本，暂未体检：{filename}；标准化文本后建议复检",
                    level="info",
                    filename=filename,
                )
            )
            source_reports.append(entry)
            continue
        try:
            analysis = analyze_source_text_file(stored)
        except OSError as exc:
            entry.update({"analyzable": False, "reason": f"读取失败：{exc}"})
            issues.append(
                issue(
                    "source_file_unreadable",
                    f"来源读取失败，未做文本体检：{filename}",
                    level="warning",
                    filename=filename,
                )
            )
            source_reports.append(entry)
            continue
        entry.update(analysis)
        source_reports.append(entry)
        any_analyzable = True
        total_visible_chars += analysis["visible_chars"]
        total_chinese_chars += analysis["chinese_chars"]
        all_chapters.extend(analysis["chapter_numbers"])
        max_garble_ratio = max(max_garble_ratio, analysis["garble_ratio"])
        if analysis["garble_ratio"] > garble_threshold:
            issues.append(
                issue(
                    "garble_ratio_exceeded",
                    f"疑似乱码率 {analysis['garble_ratio']:.2%} 超过阈值 "
                    f"{garble_threshold:.2%}：{filename}（OCR/编码问题可能导致解析失真）",
                    level="warning",
                    filename=filename,
                )
            )
        if analysis["suspected_truncation"]:
            any_truncation = True
            issues.append(
                issue(
                    "suspected_truncation",
                    f"文末不成句，疑似截断：{filename}（结尾：…{analysis['tail_sample'][-20:]}）",
                    level="warning",
                    filename=filename,
                )
            )
    unique_chapters = sorted(set(all_chapters))
    missing_chapters: list[int] = []
    duplicate_chapters = sorted(
        number for number, count in Counter(all_chapters).items() if count > 1
    )
    if unique_chapters:
        missing_chapters = [
            number
            for number in range(unique_chapters[0], unique_chapters[-1] + 1)
            if number not in set(unique_chapters)
        ]
        if missing_chapters:
            preview = "、".join(str(number) for number in missing_chapters[:20])
            more = "…" if len(missing_chapters) > 20 else ""
            issues.append(
                issue(
                    "chapters_missing",
                    f"章节序号不连续，缺 {len(missing_chapters)} 章：第 {preview}{more} 章",
                    level="warning",
                )
            )
        if duplicate_chapters:
            preview = "、".join(str(number) for number in duplicate_chapters[:20])
            issues.append(
                issue(
                    "chapters_duplicated",
                    f"章节序号重复（可能重复上传或跳号回绕）：第 {preview} 章",
                    level="warning",
                )
            )
    elif any_analyzable:
        issues.append(
            issue(
                "chapter_numbering_not_detected",
                "未识别到“第N章/第N回”模式，无法核对章节连续性；"
                "整本单文件或非章节体裁属正常情况",
                level="info",
            )
        )
    covered_chapters = len(unique_chapters) if unique_chapters else None
    coverage_assessment = "not_requested"
    if expected_episodes is not None:
        if covered_chapters is None:
            coverage_assessment = "unknown"
        elif covered_chapters < expected_episodes:
            coverage_assessment = "insufficient"
            issues.append(
                issue(
                    "chapter_coverage_below_target",
                    f"识别到 {covered_chapters} 章，少于目标 {expected_episodes} 集；"
                    "来源覆盖可能不足，请补传或确认按现有内容做截断版",
                    level="warning",
                    covered_chapters=covered_chapters,
                    expected_episodes=expected_episodes,
                )
            )
        else:
            coverage_assessment = "sufficient"
    verdict = (
        "attention_needed"
        if any(item.get("level") == "warning" for item in issues)
        else "passed"
    )
    report = {
        "schema_version": 1,
        "generated_at": now_iso(),
        "garble_threshold": garble_threshold,
        "expected_episodes": expected_episodes,
        "coverage_assessment": coverage_assessment,
        "sources": source_reports,
        "aggregate": {
            "total_chars": total_visible_chars,
            "total_chinese_chars": total_chinese_chars,
            "covered_chapters": covered_chapters,
            "chapter_min": unique_chapters[0] if unique_chapters else None,
            "chapter_max": unique_chapters[-1] if unique_chapters else None,
            "missing_chapters": missing_chapters,
            "duplicate_chapters": duplicate_chapters,
            "max_garble_ratio": max_garble_ratio,
            "suspected_truncation": any_truncation,
        },
        "issues": issues,
        "verdict": verdict,
        "note": "入料体检只提示、不阻塞；剧本仍只写到已上传内容截断点。",
    }
    report_path = project_path / PROJECT_DIRECTORIES[1] / INTAKE_CHECK_FILENAME
    atomic_write_json(report_path, report)
    report["report_path"] = report_path.relative_to(project_path).as_posix()
    return report


def intake_check_card(report: dict[str, Any]) -> dict[str, Any]:
    """入料体检卡：给 stdout 的紧凑摘要，问题存在时附一次性决策提示。"""
    aggregate = report.get("aggregate", {})
    chapter_min = aggregate.get("chapter_min")
    chapter_max = aggregate.get("chapter_max")
    card = {
        "report_path": report.get("report_path"),
        "verdict": report.get("verdict"),
        "expected_episodes": report.get("expected_episodes"),
        "coverage_assessment": report.get("coverage_assessment"),
        "total_chars": aggregate.get("total_chars"),
        "total_chinese_chars": aggregate.get("total_chinese_chars"),
        "covered_chapters": aggregate.get("covered_chapters"),
        "chapter_range": (
            f"第{chapter_min}章—第{chapter_max}章"
            if chapter_min is not None and chapter_max is not None
            else None
        ),
        "missing_chapters": aggregate.get("missing_chapters"),
        "duplicate_chapters": aggregate.get("duplicate_chapters"),
        "max_garble_ratio": aggregate.get("max_garble_ratio"),
        "suspected_truncation": aggregate.get("suspected_truncation"),
        "issues": [item.get("message") for item in report.get("issues", [])],
    }
    if report.get("verdict") == "attention_needed":
        card["decision_hint"] = (
            "入料体检发现问题，请用户一次性决定：补传缺失/更完整的来源，"
            "或按现有内容做截断版（剧本只写到已上传内容截断点）。体检不阻塞流程。"
        )
    return card


def run_intake_check_safely(
    project_path: Path,
    source_records: list[dict[str, Any]],
    garble_threshold: float,
    expected_episodes: int | None = None,
) -> dict[str, Any]:
    """体检永远不阻塞 init/add-source：内部失败降级为一条说明。"""
    try:
        return intake_check_card(
            run_intake_check(
                project_path,
                source_records,
                garble_threshold,
                expected_episodes,
            )
        )
    except Exception as exc:  # noqa: BLE001 - 体检失败不能拖垮建档
        return {
            "verdict": "check_failed",
            "issues": [f"入料体检执行失败（不影响建档）：{exc}"],
        }


def command_init(args: argparse.Namespace) -> int:
    project_path = Path(args.project).expanduser().resolve()
    path = project_path / STATE_FILENAME
    if path.exists():
        raise ToolError(f"项目已初始化，不会覆盖：{path}")
    if args.expected_episodes is not None and args.expected_episodes < 1:
        raise ToolError("--expected-episodes 必须是大于 0 的整数")
    source_policy = build_source_policy(
        args.source_kind, args.official_review, args.official_url
    )

    sources: list[Path] = []
    if not args.source:
        raise ToolError(
            "初始化改编项目必须提供至少一份原始内容；"
            "如为粘贴文本，请先保存为来源文件再使用 --source 导入"
        )
    for raw_source in args.source:
        source = Path(raw_source).expanduser().resolve()
        if not source.is_file():
            raise ToolError(f"源内容不是可读文件：{source}")
        sources.append(source)

    project_path.mkdir(parents=True, exist_ok=True)
    for directory in PROJECT_DIRECTORIES:
        (project_path / directory).mkdir(parents=True, exist_ok=True)

    imported_at = now_iso()
    source_records: list[dict[str, Any]] = []
    copied_paths: list[Path] = []
    try:
        for source in sources:
            copied = safe_copy_source(source, project_path / PROJECT_DIRECTORIES[0])
            copied_paths.append(copied)
            source_records.append(
                {
                    "source_id": str(uuid.uuid4()),
                    "original_path": str(source),
                    "stored_path": copied.relative_to(project_path).as_posix(),
                    "filename": copied.name,
                    "size_bytes": copied.stat().st_size,
                    "sha256": sha256_file(copied),
                    "imported_at": imported_at,
                }
            )
    except Exception:
        # 初始化尚未写入状态，只回滚本次创建的文件，不碰用户原有内容。
        for copied in copied_paths:
            try:
                copied.unlink(missing_ok=True)
            except OSError:
                pass
        raise

    created_at = now_iso()
    state: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "project_id": str(uuid.uuid4()),
        "name": args.name or project_path.name,
        "created_at": created_at,
        "updated_at": created_at,
        "current_stage": "project_setup",
        "directories": list(PROJECT_DIRECTORIES),
        "stages": {
            key: {
                "label": label,
                "status": "in_progress" if key == "project_setup" else "pending",
                "updated_at": created_at,
                "note": "",
            }
            for key, label in STAGES.items()
        },
        "sources": source_records,
        "source_policy": source_policy,
        "expected_episodes_hint": args.expected_episodes,
        "batches": {},
        "artifacts": {},
        "approvals": [],
        "history": [
            {
                "event_id": str(uuid.uuid4()),
                "event": "project_initialized",
                "at": created_at,
                "source_count": len(source_records),
            }
        ],
    }
    atomic_write_json(path, state)
    result = {
        "ok": True,
        "project": str(project_path),
        "project_id": state["project_id"],
        "source_count": len(source_records),
        "sources": source_records,
        "source_policy": source_policy,
        "expected_episodes_hint": args.expected_episodes,
    }
    if args.expected_episodes is not None:
        result["next_step"] = (
            "目标集数只作建档提示；权威值仍以已确认 project_spec 的 expected_episodes 为准，"
            "确认前后不一致时以 project_spec 为准"
        )
    if args.garble_threshold is not None:
        result["deprecated_options"] = ["--garble-threshold"]
    print_json(result)
    return 0


def stage_time_totals(state: dict[str, Any]) -> dict[str, Any] | None:
    """汇总 stage 历史里的两列耗时；旧项目无字段时返回 None（不报错）。"""
    history = state.get("history")
    if not isinstance(history, list):
        return None
    machine_total = 0.0
    human_total = 0.0
    by_stage: dict[str, dict[str, float]] = {}
    found = False
    for event in history:
        if not isinstance(event, dict) or event.get("event") != "stage_changed":
            continue
        machine = event.get("machine_time_seconds")
        human = event.get("human_wait_seconds")
        if not isinstance(machine, (int, float)) and not isinstance(human, (int, float)):
            continue
        found = True
        stage = event.get("stage")
        stage_key = stage if isinstance(stage, str) else "unknown"
        bucket = by_stage.setdefault(
            stage_key, {"machine_time_seconds": 0.0, "human_wait_seconds": 0.0}
        )
        if isinstance(machine, (int, float)):
            machine_total += machine
            bucket["machine_time_seconds"] += machine
        if isinstance(human, (int, float)):
            human_total += human
            bucket["human_wait_seconds"] += human
    if not found:
        return None
    return {
        "machine_time_seconds": machine_total,
        "human_wait_seconds": human_total,
        "by_stage": by_stage,
        "note": "machine_time=机器计算耗时；human_wait=人工等待耗时。两口径分开登记，用于评估流程改进。",
    }


def command_show(args: argparse.Namespace) -> int:
    project_path, state = load_state(args.project)
    rights_notice = pending_rights_notice(project_path, state)
    if args.summary:
        artifacts = state.get("artifacts", {})
        summary = {
            "schema_version": state.get("schema_version"),
            "project_id": state.get("project_id"),
            "name": state.get("name"),
            "current_stage": state.get("current_stage"),
            "stages": state.get("stages"),
            "source_count": len(state.get("sources", []))
            if isinstance(state.get("sources"), list)
            else None,
            "artifact_count": sum(len(records) for records in artifacts.values())
            if isinstance(artifacts, dict)
            else None,
            "updated_at": state.get("updated_at"),
        }
        time_totals = stage_time_totals(state)
        if time_totals is not None:
            summary["time_tracking"] = time_totals
        if rights_notice is not None:
            summary["rights_notice"] = rights_notice
        print_json(summary)
    elif rights_notice is not None:
        print_json({**state, "rights_notice": rights_notice})
    else:
        print_json(state)
    if rights_notice is not None:
        # 只提示一次：记录提示事件但不改动 updated_at（show 不算内容修改）。
        append_history(state, "rights_unclear_notified", {"notice": rights_notice})
        atomic_write_json(project_path / STATE_FILENAME, state)
    return 0


def command_define_batch(args: argparse.Namespace) -> int:
    project_path, state = load_state(args.project)
    batch_id = args.batch_id.upper()
    if not BATCH_ID_RE.fullmatch(batch_id):
        raise ToolError("批次 ID 必须使用 B01、B02 这类格式")
    episode_ids = [value.upper() for value in args.episode_ids]
    if any(not EPISODE_ID_RE.fullmatch(value) for value in episode_ids):
        raise ToolError("批次集号必须使用 E001、E002 这类格式")
    if len(episode_ids) != len(set(episode_ids)):
        raise ToolError("批次集号不能重复")
    spec = confirmed_project_spec_payload(project_path, state)
    rolling_v2 = (
        isinstance(spec, dict)
        and spec.get("schema_version") == 2
        and spec.get("scope_mode") == "rolling_batch"
    )
    expected_episodes = project_expected_episodes(project_path, state)
    episode_scope_source = "confirmed_batches" if rolling_v2 else "project_spec"
    if rolling_v2:
        if not args.confirmed_by_user:
            raise ToolError("rolling_batch新增批次必须显式提供 --confirmed-by-user")
        batch_size = spec.get("batch_size")
        if type(batch_size) is not int or batch_size < 1:
            raise ToolError("rolling_batch项目规格 batch_size 必须是正整数")
        if len(episode_ids) != batch_size:
            raise ToolError(f"rolling_batch批次必须包含 batch_size={batch_size} 集")
        previous = confirmed_episode_ids(state)
        first_expected = int(previous[-1][1:]) + 1 if previous else 1
        expected_sequence = [f"E{number:03d}" for number in range(first_expected, first_expected + len(episode_ids))]
        if episode_ids != expected_sequence:
            raise ToolError("rolling_batch新批次集号必须紧接已确认批次且连续：" + " ".join(expected_sequence))
    elif expected_episodes is None:
        # project_spec 仍是交付门禁的唯一权威；这里只让规划期的批次划分
        # 回退到 init 登记的目标集数提示，避免建档后无法定义批次。
        expected_episodes = state_expected_episodes_hint(state)
        episode_scope_source = "init_hint"
    if not rolling_v2 and expected_episodes is None:
        raise ToolError(
            "无法读取目标集数：请先登记并确认含 expected_episodes 的 project_spec，"
            "或在 init 时提供 --expected-episodes"
        )
    out_of_range = [
        value for value in episode_ids if int(value[1:]) > expected_episodes
    ] if expected_episodes is not None else []
    if out_of_range:
        scope_label = (
            f"项目规格 expected_episodes（{expected_episodes}）"
            if episode_scope_source == "project_spec"
            else f" init 登记的目标集数提示（{expected_episodes}）"
        )
        raise ToolError(
            f"批次包含超出{scope_label}的集号：" + "、".join(out_of_range)
        )
    batches = state.setdefault("batches", {})
    if not isinstance(batches, dict):
        raise ToolError("项目 batches 结构无效，请先运行 validate-project")
    if batch_id in batches:
        raise ToolError(f"批次已存在，不会覆盖：{batch_id}")
    requested = set(episode_ids)
    for existing_id, batch in batches.items():
        if not isinstance(existing_id, str) or not isinstance(batch, dict):
            continue
        existing_episodes = batch.get("episode_ids")
        overlap = (
            requested.intersection(existing_episodes)
            if isinstance(existing_episodes, list)
            else set()
        )
        if overlap:
            raise ToolError(
                f"批次 {batch_id} 与已有批次 {existing_id} 集号重叠："
                + "、".join(sorted(overlap))
            )
    defined_at = now_iso()
    batches[batch_id] = {
        "batch_id": batch_id,
        "episode_ids": episode_ids,
        "defined_at": defined_at,
        "note": args.note or "",
    }
    if rolling_v2:
        batches[batch_id].update(
            {
                "status": "confirmed",
                "confirmed_at": defined_at,
                "approval_note": args.note or "用户显式确认批次范围",
            }
        )
    append_history(
        state,
        "batch_defined",
        {
            "batch_id": batch_id,
            "episode_ids": episode_ids,
            "note": args.note or "",
        },
    )
    save_state(project_path, state)
    result = {
        "ok": True,
        "batch_id": batch_id,
        "episode_ids": episode_ids,
        "defined_at": defined_at,
        "note": args.note or "",
        "episode_scope_source": episode_scope_source,
    }
    if episode_scope_source == "init_hint":
        result["warnings"] = [
            {
                "code": "episode_scope_from_init_hint",
                "message": (
                    f"尚无已确认 project_spec，本次按 init 登记的目标集数提示（{expected_episodes}）"
                    "校验批次范围；交付门禁仍要求已确认 project_spec 的 expected_episodes"
                ),
            }
        ]
    print_json(result)
    return 0


def command_set_stage(args: argparse.Namespace) -> int:
    project_path, state = load_state(args.project)
    stages = state.get("stages")
    if not isinstance(stages, dict) or args.stage not in stages:
        raise ToolError(f"项目中不存在阶段：{args.stage}")
    if args.status not in STAGE_STATUSES:
        raise ToolError(f"无效阶段状态：{args.status}")
    if args.status == "completed":
        required_types = STAGE_COMPLETION_ARTIFACTS.get(args.stage, ())
        missing_types = [
            kind
            for kind in required_types
            if not any(
                confirmed_record_is_usable(state, key, record, project_path)
                for key, record in latest_records_of_type(state, kind)
            )
        ]
        if args.stage == "pilot_writing" and not any(
            confirmed_record_is_usable(state, key, record, project_path)
            for kind in ("pilot_scripts", "episode_script")
            for key, record in latest_records_of_type(state, kind)
        ):
            missing_types.append("pilot_scripts")
        if missing_types:
            labels = "、".join(ARTIFACT_TYPES[kind] for kind in missing_types)
            raise ToolError(f"阶段不能标记完成，缺少已确认制品：{labels}")
    timestamp = now_iso()
    previous_status = stages[args.stage].get("status")
    for option_name, option_value in (
        ("--machine-time-seconds", args.machine_time_seconds),
        ("--human-wait-seconds", args.human_wait_seconds),
    ):
        if option_value is not None:
            if not math.isfinite(option_value):
                raise ToolError(f"{option_name} 必须是有限数字")
            if option_value < 0:
                raise ToolError(f"{option_name} 不能为负数")
    stages[args.stage]["status"] = args.status
    stages[args.stage]["updated_at"] = timestamp
    if args.note is not None:
        stages[args.stage]["note"] = args.note
    if args.status in {"in_progress", "awaiting_approval", "completed", "blocked"}:
        state["current_stage"] = args.stage
    history_details: dict[str, Any] = {
        "stage": args.stage,
        "previous_status": previous_status,
        "status": args.status,
        "note": args.note or "",
    }
    # 耗时口径拆分：machine_time=机器计算，human_wait=人工等待；可选，旧记录无字段不报错。
    if args.machine_time_seconds is not None:
        history_details["machine_time_seconds"] = args.machine_time_seconds
    if args.human_wait_seconds is not None:
        history_details["human_wait_seconds"] = args.human_wait_seconds
    append_history(state, "stage_changed", history_details)
    save_state(project_path, state)
    result: dict[str, Any] = {
        "ok": True,
        "stage": args.stage,
        "previous_status": previous_status,
        "status": args.status,
    }
    if args.machine_time_seconds is not None:
        result["machine_time_seconds"] = args.machine_time_seconds
    if args.human_wait_seconds is not None:
        result["human_wait_seconds"] = args.human_wait_seconds
    print_json(result)
    return 0


def command_register_artifact(args: argparse.Namespace) -> int:
    project_path, state = load_state(args.project)
    artifact_kind = artifact_type(args.artifact_key)
    if args.status not in {"draft", "awaiting_approval"}:
        raise ToolError("登记状态只能是 draft 或 awaiting_approval；确认必须使用 approve")
    if artifact_kind in {
        "final_package",
        "delivery_manifest",
        "series_delivery_manifest",
        "batch_delivery_manifest",
        "batch_package",
    }:
        raise ToolError(
            f"{artifact_kind} 只能由 build-handoff 生成，不能手工登记"
        )
    artifact_path = Path(args.path).expanduser()
    if not artifact_path.is_absolute():
        artifact_path = project_path / artifact_path
    artifact_path = artifact_path.resolve()
    if not artifact_path.is_file():
        raise ToolError(f"制品文件不存在：{artifact_path}")
    stored_path = safe_relative_path(artifact_path, project_path)

    artifacts = state.setdefault("artifacts", {})
    if not isinstance(artifacts, dict):
        raise ToolError("项目 artifacts 结构无效，请先运行 validate-project")
    records = artifacts.setdefault(args.artifact_key, [])
    if not isinstance(records, list):
        raise ToolError(f"制品记录结构无效：{args.artifact_key}")
    versions = [
        record.get("version", 0)
        for record in records
        if isinstance(record, dict) and type(record.get("version")) is int
    ]
    if any(
        isinstance(record, dict) and record.get("path") == stored_path
        for record in records
    ):
        raise ToolError(
            "新版本必须保存为新的文件路径；复用旧路径会破坏历史版本散列"
        )
    version = max(versions, default=0) + 1
    dependencies = [parse_dependency(value, state) for value in args.depends_on]
    validate_dependency_shape(args.artifact_key, dependencies)
    registered_at = now_iso()
    record: dict[str, Any] = {
        "version": version,
        "artifact_type": artifact_kind,
        "path": stored_path,
        "size_bytes": artifact_path.stat().st_size,
        "sha256": sha256_file(artifact_path),
        "status": args.status,
        "depends_on": dependencies,
        "registered_at": registered_at,
        "note": args.note or "",
    }
    records.append(record)
    if args.status == "confirmed":
        affected = confirm_record(
            state,
            args.artifact_key,
            record,
            f"上游制品 {args.artifact_key}@{version} 已确认为新版本",
        )
    else:
        affected = []
    append_history(
        state,
        "artifact_registered",
        {
            "artifact_key": args.artifact_key,
            "version": version,
            "status": record["status"],
            "path": stored_path,
            "downstream_marked_stale": affected,
        },
    )
    save_state(project_path, state)
    print_json(
        {
            "ok": True,
            "artifact_key": args.artifact_key,
            "version": version,
            "status": record["status"],
            "sha256": record["sha256"],
            "downstream_marked_stale": affected,
        }
    )
    return 0


def command_approve(args: argparse.Namespace) -> int:
    project_path, state = load_state(args.project)
    artifact_type(args.artifact_key)
    records = state.get("artifacts", {}).get(args.artifact_key, [])
    if not isinstance(records, list) or not records:
        raise ToolError(f"制品不存在：{args.artifact_key}")
    valid_records = [item for item in records if isinstance(item, dict)]
    latest = max(valid_records, key=version_sort_key)
    version = args.version if args.version is not None else latest.get("version")
    selected = next(
        (record for record in valid_records if record.get("version") == version), None
    )
    if selected is None:
        raise ToolError(f"制品版本不存在：{args.artifact_key}@{version}")
    if selected is not latest:
        raise ToolError("只能确认制品的最新版本，历史版本保留用于追溯")
    if selected.get("status") == "confirmed":
        raise ToolError(f"制品已确认：{args.artifact_key}@{version}")
    if selected.get("status") != "awaiting_approval":
        raise ToolError(
            f"只能确认 awaiting_approval 制品，当前状态为 {selected.get('status')}"
        )
    selected_path = path_from_record(project_path, selected.get("path"))
    if selected_path is None or not selected_path.is_file():
        raise ToolError("制品文件不存在或路径无效，不能确认")
    if sha256_file(selected_path) != selected.get("sha256"):
        raise ToolError("制品文件在登记后已变更，必须登记为新版本后再确认")
    if selected_path.stat().st_size != selected.get("size_bytes"):
        raise ToolError("制品文件大小与登记记录不一致，必须登记为新版本")
    dependencies = selected.get("depends_on")
    if not isinstance(dependencies, list):
        raise ToolError("制品依赖结构无效，不能确认")
    selected_type = artifact_type(args.artifact_key)
    validate_dependency_shape(args.artifact_key, dependencies)
    review_target_type = BOUNDARY_TARGET_FOR_REVIEW.get(selected_type)
    for dependency in dependencies:
        if not isinstance(dependency, dict):
            raise ToolError("制品依赖项无效，不能确认")
        dep_key = dependency.get("artifact_key")
        dep_version = dependency.get("version")
        dep_record = latest_record(state, dep_key) if isinstance(dep_key, str) else None
        dep_type = artifact_type(dep_key) if isinstance(dep_key, str) else ""
        if review_target_type is not None and dep_type == review_target_type:
            if (
                dep_record is None
                or dep_record.get("version") != dep_version
                or not record_is_shallow_current(
                    state,
                    dep_key,
                    dep_record,
                    project_path,
                    frozenset({"awaiting_approval", "confirmed"}),
                )
            ):
                raise ToolError(
                    f"内容边界报告必须绑定目标稿当前未变更版本：{dep_key}@{dep_version}"
                )
            continue
        if (
            dep_record is None
            or dep_record.get("version") != dep_version
            or not confirmed_record_is_usable(state, dep_key, dep_record, project_path)
        ):
            raise ToolError(
                f"确认前所有依赖必须是最新版且已获有效确认：{dep_key}@{dep_version}"
            )
    if selected_type == "episode_script":
        script_result = validate_script_file(
            selected_path,
            target_duration_seconds=project_target_duration_seconds(project_path, state),
            chars_per_second=dialogue_chars_per_second(
                project_duration_policy(project_path, state)
            ),
        )
        if not script_result["valid"]:
            codes = "、".join(item["code"] for item in script_result["errors"])
            raise ToolError(f"分集剧本结构校验未通过，不能确认：{codes}")
        missing_end_states = [
            item
            for item in script_result["warnings"]
            if item.get("code") == "scene_end_state_unmarked"
        ]
        if missing_end_states:
            raise ToolError(
                "分集剧本内部稿仍有场次未标记场尾状态，不能确认；"
                "对外交付时可隐藏这些内部标记"
            )
        expected_scope = args.artifact_key.split(":", 1)[1] if ":" in args.artifact_key else ""
        episode_heading = script_result.get("episode") or {}
        heading_number = episode_heading.get("number_value")
        if not re.fullmatch(r"E\d{3,6}", expected_scope, re.IGNORECASE):
            raise ToolError("分集剧本制品 key 必须使用 episode_script:E001 形式")
        if not isinstance(heading_number, int):
            raise ToolError("无法解析分集标题中的集号")
        if int(expected_scope[1:]) != heading_number:
            raise ToolError(
                f"分集剧本 key {expected_scope} 与文件中的第{heading_number}集不一致"
            )
    rights_notice: str | None = None
    if selected_type == "project_spec":
        # 非法 rights_mode 拒绝确认；unclear 只提示一次，不阻塞。
        rights_notice = validate_project_spec_rights(project_path, selected)
        if rights_notice is not None and rights_notice_already_shown(state):
            rights_notice = None
        # 时长契约字段非法时拒绝确认；字段缺省表示项目不做时长门禁。
        validate_project_spec_duration(project_path, selected)
    if selected_type == "series_map":
        series_map_payload = load_json_artifact_payload(
            project_path, args.artifact_key, selected, []
        )
        if (
            isinstance(series_map_payload, dict)
            and series_map_payload.get("granularity", "full") == "backbone"
            and series_map_payload.get("contract_version") != 2
        ):
            raise ToolError(
                "旧 backbone 地图可读取，但再次确认前必须升级为 contract_version=2"
            )
    if selected_type == "batch_outline":
        source_errors = scoped_batch_outline_source_errors(
            state, args.artifact_key, selected
        )
        if source_errors:
            codes = "、".join(item["code"] for item in source_errors)
            raise ToolError(f"批次大纲原著细化门禁未通过：{codes}")
    if selected_type == "character_anchor":
        anchor_path = path_from_record(project_path, selected.get("path"))
        if anchor_path is not None and anchor_path.suffix.lower() == ".json":
            try:
                anchor_payload = read_json_file(anchor_path)
            except ToolError as exc:
                raise ToolError(f"人物锚点 JSON 无法读取：{exc}") from exc
            anchor_errors = validate_character_anchor_payload(anchor_payload)
            if anchor_errors:
                codes = "、".join(dict.fromkeys(item["code"] for item in anchor_errors))
                raise ToolError(f"人物锚点校验未通过，不能确认：{codes}")
    if selected_type in STRUCTURED_DEVELOPMENT_TYPES:
        structured_errors = validate_structured_development_artifact(
            project_path, state, args.artifact_key, selected
        )
        if structured_errors:
            codes = "、".join(dict.fromkeys(item["code"] for item in structured_errors))
            raise ToolError(f"规范制品校验未通过，不能确认：{codes}")
    if selected_type in BOUNDARY_REVIEW_FOR_TARGET and matching_boundary_review(
        state, args.artifact_key, selected, project_path
    ) is None:
        review_label = ARTIFACT_TYPES[BOUNDARY_REVIEW_FOR_TARGET[selected_type]]
        raise ToolError(
            f"{ARTIFACT_TYPES[selected_type]}不能确认：缺少精确绑定当前版本且结论为 passed 的已确认{review_label}；"
            "blocked 或 suspected_overreach 必须先返修、取得用户授权或完成人工判断"
        )
    affected = confirm_record(
        state,
        args.artifact_key,
        selected,
        f"上游制品 {args.artifact_key}@{version} 已确认为新版本",
    )
    approval = {
        "approval_id": str(uuid.uuid4()),
        "artifact_key": args.artifact_key,
        "version": version,
        "approved_at": now_iso(),
        "approved_by": args.approved_by,
        "note": args.note or "",
    }
    approvals = state.setdefault("approvals", [])
    if not isinstance(approvals, list):
        raise ToolError("项目 approvals 结构无效，请先运行 validate-project")
    approvals.append(approval)
    append_history(
        state,
        "artifact_approved",
        {
            "artifact_key": args.artifact_key,
            "version": version,
            "approved_by": args.approved_by,
            "downstream_marked_stale": affected,
        },
    )
    if rights_notice is not None:
        append_history(state, "rights_unclear_notified", {"notice": rights_notice})
    save_state(project_path, state)
    result = {
        "ok": True,
        "artifact_key": args.artifact_key,
        "version": version,
        "approval_id": approval["approval_id"],
        "downstream_marked_stale": affected,
    }
    if rights_notice is not None:
        result["rights_notice"] = rights_notice
    print_json(result)
    return 0


def command_mark_stale(args: argparse.Namespace) -> int:
    project_path, state = load_state(args.project)
    artifact_kind = artifact_type(args.artifact_key)
    records = state.get("artifacts", {}).get(args.artifact_key, [])
    if not isinstance(records, list) or not records:
        raise ToolError(f"制品不存在：{args.artifact_key}")
    valid_records = [item for item in records if isinstance(item, dict)]
    latest = max(valid_records, key=version_sort_key)
    version = args.version if args.version is not None else latest.get("version")
    selected = next(
        (record for record in valid_records if record.get("version") == version), None
    )
    if selected is None:
        raise ToolError(f"制品版本不存在：{args.artifact_key}@{version}")
    timestamp = now_iso()
    previous_status = selected.get("status")
    selected["status"] = "stale"
    selected["stale_at"] = timestamp
    selected["stale_reason"] = args.reason
    invalidate_approvals(state, args.artifact_key, version, args.reason, timestamp)
    stage_key = ARTIFACT_STAGE.get(artifact_kind)
    stage = state.get("stages", {}).get(stage_key) if stage_key else None
    if isinstance(stage, dict):
        stage["status"] = "stale"
        stage["updated_at"] = timestamp
        stage["note"] = args.reason
    affected = (
        mark_downstream_stale(
            state, args.artifact_key, args.reason, timestamp, [version]
        )
        if not args.no_cascade
        else []
    )
    recompute_current_stage(state)
    append_history(
        state,
        "artifact_marked_stale",
        {
            "artifact_key": args.artifact_key,
            "version": version,
            "previous_status": previous_status,
            "reason": args.reason,
            "cascade": not args.no_cascade,
            "downstream_marked_stale": affected,
        },
    )
    save_state(project_path, state)
    print_json(
        {
            "ok": True,
            "artifact_key": args.artifact_key,
            "version": version,
            "previous_status": previous_status,
            "status": "stale",
            "downstream_marked_stale": affected,
        }
    )
    return 0


def command_add_source(args: argparse.Namespace) -> int:
    """向已有项目增量登记新来源（追更补传章节），并自动标脏来源依赖链。"""
    project_path, state = load_state(args.project)
    source = Path(args.source).expanduser().resolve()
    if not source.is_file():
        raise ToolError(f"源内容不是可读文件：{source}")
    existing = state.get("sources")
    if not isinstance(existing, list):
        raise ToolError("项目状态缺少 sources 记录，无法增量补传")
    new_sha = None
    copied = safe_copy_source(source, project_path / PROJECT_DIRECTORIES[0])
    try:
        new_sha = sha256_file(copied)
        if any(
            isinstance(item, dict) and item.get("sha256") == new_sha for item in existing
        ):
            raise ToolError(f"该来源内容已登记过（sha256 相同）：{source.name}")
    except ToolError:
        try:
            copied.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    timestamp = now_iso()
    reason = args.reason or f"新增原著来源：{copied.name}"
    record = {
        "source_id": str(uuid.uuid4()),
        "original_path": str(source),
        "stored_path": copied.relative_to(project_path).as_posix(),
        "filename": copied.name,
        "size_bytes": copied.stat().st_size,
        "sha256": new_sha,
        "imported_at": timestamp,
    }
    existing.append(record)
    affected: list[Any] = []
    stale_corpus = None
    corpus_records = [
        item
        for item in state.get("artifacts", {}).get("source_corpus", [])
        if isinstance(item, dict)
    ]
    if corpus_records:
        latest = max(corpus_records, key=version_sort_key)
        if latest.get("status") in {"draft", "awaiting_approval", "confirmed"}:
            latest["status"] = "stale"
            latest["stale_at"] = timestamp
            latest["stale_reason"] = reason
            stale_corpus = latest.get("version")
            invalidate_approvals(
                state, "source_corpus", latest.get("version"), reason, timestamp
            )
            affected = mark_downstream_stale(
                state, "source_corpus", reason, timestamp, [latest.get("version")]
            )
    stage = state.get("stages", {}).get("source_analysis")
    if isinstance(stage, dict):
        stage["status"] = "in_progress"
        stage["updated_at"] = timestamp
        stage["note"] = f"{reason}；需增量更新原著语料库、事件索引与事实库"
    recompute_current_stage(state)
    append_history(
        state,
        "source_added",
        {
            "source_id": record["source_id"],
            "filename": copied.name,
            "sha256": new_sha,
            "reason": reason,
            "source_corpus_marked_stale": stale_corpus,
            "downstream_marked_stale": affected,
        },
    )
    save_state(project_path, state)
    result = {
        "ok": True,
        "source_id": record["source_id"],
        "stored_path": record["stored_path"],
        "sha256": new_sha,
        "source_corpus_marked_stale": stale_corpus,
        "downstream_marked_stale": affected,
        "next_step": "增量更新原著语料库与事件索引（新版本），再复核受影响制品",
    }
    if args.garble_threshold is not None:
        result["deprecated_options"] = ["--garble-threshold"]
    print_json(result)
    return 0


def command_plan_source_partitions(args: argparse.Namespace) -> int:
    project_path, _state = load_state(args.project)
    source_corpus_path = resolve_project_input(project_path, args.source_corpus)
    policy_path = resolve_project_input(project_path, args.policy)
    source_corpus = read_json_file(source_corpus_path)
    policy_payload = read_json_file(policy_path)
    policy = policy_payload.get("policy")
    if not isinstance(policy, dict):
        raise ToolError("分片策略 JSON 必须包含 policy 对象")
    try:
        plan = source_partition.build_partition_plan(source_corpus, policy)
    except source_partition.PartitionError as exc:
        raise ToolError(str(exc)) from exc
    validation = source_partition.validate_partition_plan(plan, source_corpus)
    if validation:
        raise ToolError(json.dumps({"errors": validation}, ensure_ascii=False))
    output = resolve_project_output(project_path, args.output)
    atomic_write_json(output, plan)
    print_json({"ok": True, "output": str(output), "partition_count": len(plan["partitions"])})
    return 0


def command_merge_source_analysis_shards(args: argparse.Namespace) -> int:
    project_path, _state = load_state(args.project)
    plan_path = resolve_project_input(project_path, args.plan)
    shard_dir = resolve_project_input(project_path, args.shard_dir)
    if not shard_dir.is_dir():
        raise ToolError(f"分析分片路径不是目录：{shard_dir}")
    plan = read_json_file(plan_path)
    shards = [read_json_file(path) for path in sorted(shard_dir.glob("*.json"))]
    try:
        payload = source_partition.merge_analysis_shards(plan, shards)
    except source_partition.PartitionError as exc:
        errors = source_partition.validate_analysis_shards(plan, shards)
        raise ToolError(json.dumps({"error": str(exc), "errors": errors}, ensure_ascii=False)) from exc
    output = resolve_project_output(project_path, args.output)
    atomic_write_json(output, payload)
    print_json({"ok": True, "output": str(output), "unit_count": len(payload["units"])})
    return 0


def command_register_source_analysis(args: argparse.Namespace) -> int:
    project_path, _state = load_state(args.project)
    corpus = read_json_file(resolve_project_input(project_path, args.source_corpus))
    registry = read_json_file(resolve_project_input(project_path, args.registry))
    analysis_path = resolve_project_input(project_path, args.analysis)
    units = corpus.get("source_units")
    unit = next(
        (
            item
            for item in units
            if isinstance(item, dict) and item.get("source_unit_id") == args.source_unit_id
        ),
        None,
    ) if isinstance(units, list) else None
    if not isinstance(unit, dict) or not isinstance(unit.get("content_sha256"), str):
        raise ToolError("source_unit_id 不存在或缺少 content_sha256")
    try:
        updated = source_partition.record_chapter_analysis(
            registry,
            source_unit_id=args.source_unit_id,
            content_sha256=unit["content_sha256"],
            analysis_contract_version=args.contract_version,
            analysis_path=analysis_path.relative_to(project_path).as_posix(),
            analysis_sha256=sha256_file(analysis_path),
        )
    except source_partition.PartitionError as exc:
        raise ToolError(str(exc)) from exc
    output = resolve_project_output(project_path, args.output)
    atomic_write_json(output, updated)
    print_json({"ok": True, "output": str(output), "record_count": len(updated["records"])})
    return 0


def command_plan_rolling_source_window(args: argparse.Namespace) -> int:
    project_path, _state = load_state(args.project)
    corpus = read_json_file(resolve_project_input(project_path, args.source_corpus))
    registry = read_json_file(resolve_project_input(project_path, args.registry))
    progress = read_json_file(resolve_project_input(project_path, args.progress))
    try:
        plan = source_partition.build_rolling_source_plan(
            corpus, registry, progress, window_size=args.window_size
        )
    except source_partition.PartitionError as exc:
        raise ToolError(str(exc)) from exc
    output = resolve_project_output(project_path, args.output)
    atomic_write_json(output, plan)
    print_json(
        {
            "ok": True,
            "output": str(output),
            "carryover_event_count": len(plan["carryover_event_ids"]),
            "new_analysis_unit_count": len(plan["new_analysis_source_unit_ids"]),
        }
    )
    return 0


def command_build_production_context_manifest(args: argparse.Namespace) -> int:
    project_path, _state = load_state(args.project)
    common = [
        "skills/novel-to-script-director/SKILL.md",
        "skills/novel-to-script-director/references/workflow.md",
        "skills/novel-to-script-director/references/artifact-contracts.md",
        "skills/novel-to-script-director/references/production-data-schemas.md",
        "skills/novel-to-script-director/scripts/project_tool.py",
    ]
    stage_paths = {
        "source_analysis": ["skills/novel-to-script-director/scripts/source_partition.py"],
        "batch_writing": ["skills/novel-to-script-director/references/script-format-and-quality.md"],
        "final_delivery": [
            "skills/novel-to-script-director/scripts/render_episode_script.py",
            "skills/novel-to-script-director/scripts/render_storyboard.py",
        ],
    }
    allowed = list(dict.fromkeys(common + stage_paths.get(args.stage, [])))
    payload = {
        "schema_version": 1,
        "stage": args.stage,
        "allowed_plugin_paths": allowed,
        "forbidden_patterns": ["test_*.py", "docs/superpowers/plans/**"],
    }
    output = resolve_project_output(project_path, args.output)
    atomic_write_json(output, payload)
    print_json({"ok": True, "output": str(output), "allowed_path_count": len(allowed)})
    return 0


def episode_delivery_inputs(
    project_path: Path, state: dict[str, Any], episode: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    errors: list[dict[str, Any]] = []
    dependencies: list[dict[str, Any]] = []

    def require_current(key: str, label: str) -> dict[str, Any] | None:
        record = latest_record(state, key)
        if not isinstance(record, dict) or not confirmed_record_is_usable(
            state, key, record, project_path
        ):
            errors.append(issue("episode_delivery_input_missing", f"缺少当前已确认{label}", artifact_key=key))
            return None
        dependencies.append({"artifact_key": key, "version": record["version"]})
        return record

    script_key = f"episode_script:{episode}"
    plan_key = f"ai_shot_plan:{episode}"
    script_record = require_current(script_key, "分集剧本")
    plan_record = require_current(plan_key, "AI分镜计划")
    if isinstance(script_record, dict) and matching_boundary_review(
        state, script_key, script_record, project_path
    ) is None:
        errors.append(issue("episode_delivery_script_review_missing", "分集剧本缺少当前 passed 内容边界报告"))
    if isinstance(plan_record, dict) and matching_boundary_review(
        state, plan_key, plan_record, project_path
    ) is None:
        errors.append(issue("episode_delivery_shot_review_missing", "AI分镜计划缺少当前 passed 内容边界报告"))

    roster_record = (
        dependency_record_of_type(state, plan_record, "character_roster")[1]
        if isinstance(plan_record, dict)
        and dependency_record_of_type(state, plan_record, "character_roster") is not None
        else latest_record(state, "character_roster")
    )
    if not isinstance(roster_record, dict) or not confirmed_record_is_usable(
        state, "character_roster", roster_record, project_path
    ):
        errors.append(issue("episode_delivery_roster_missing", "缺少当前已确认角色提取表"))
        roster_payload = None
    else:
        dependencies.append({"artifact_key": "character_roster", "version": roster_record["version"]})
        roster_path = path_from_record(project_path, roster_record.get("path"))
        roster_payload = read_json_file(roster_path) if roster_path else None

    plan_payload: dict[str, Any] | None = None
    anchors: dict[str, dict[str, Any]] = {}
    if isinstance(plan_record, dict):
        plan_path = path_from_record(project_path, plan_record.get("path"))
        plan_payload = read_json_file(plan_path) if plan_path else None
        if not isinstance(plan_payload, dict) or plan_payload.get("shot_language_contract_version") != 2:
            errors.append(issue("episode_delivery_shot_contract_v2_required", "逐集交付要求 shot_language_contract_version=2"))
        for dependency in plan_record.get("depends_on", []):
            if not isinstance(dependency, dict):
                continue
            key = dependency.get("artifact_key")
            version = dependency.get("version")
            if not isinstance(key, str) or not key.startswith("character_anchor:"):
                continue
            record = next(
                (
                    item
                    for item in state.get("artifacts", {}).get(key, [])
                    if isinstance(item, dict) and item.get("version") == version
                ),
                None,
            ) if type(version) is int else None
            if not isinstance(record, dict) or not confirmed_record_is_usable(
                state, key, record, project_path
            ):
                errors.append(issue("episode_delivery_anchor_missing", "人物锚点不是当前可用确认版本", artifact_key=key))
                continue
            anchor_path = path_from_record(project_path, record.get("path"))
            if anchor_path is None or anchor_path.suffix.lower() != ".json":
                errors.append(issue("episode_delivery_anchor_v2_required", "逐集交付要求 JSON 人物锚点v2", artifact_key=key))
                continue
            payload = read_json_file(anchor_path)
            anchor_errors = validate_character_anchor_payload(payload)
            if anchor_errors:
                errors.extend(anchor_errors)
                continue
            anchors[payload["character_id"]] = payload
            dependencies.append({"artifact_key": key, "version": version})

    script_text: str | None = None
    if isinstance(script_record, dict):
        script_path = path_from_record(project_path, script_record.get("path"))
        if script_path is not None:
            try:
                script_text = script_path.read_text(encoding="utf-8-sig")
            except (OSError, UnicodeError):
                script_text = None
        if not isinstance(script_text, str):
            errors.append(issue("episode_delivery_script_unreadable", "分集剧本无法读取"))

    return (
        {
            "episode": episode,
            "script_text": script_text,
            "roster": roster_payload,
            "anchors": anchors,
            "plan": plan_payload,
            "dependencies": dependencies,
        },
        errors,
    )


def validate_episode_delivery_readiness(
    project_path: Path, episode: str
) -> dict[str, Any]:
    state_path = project_path / STATE_FILENAME
    state = read_json_file(state_path)
    _inputs, errors = episode_delivery_inputs(project_path, state, episode)
    return {
        "ready": not errors,
        "episode": episode,
        "errors": errors,
        "dependencies": _inputs["dependencies"],
    }


def command_render_episode_delivery(args: argparse.Namespace) -> int:
    import render_episode_script
    import render_storyboard

    project_path, state = load_state(args.project)
    episode = str(args.episode).upper()
    if not EPISODE_ID_RE.fullmatch(episode):
        raise ToolError("集号必须使用 E001 形式")
    inputs, errors = episode_delivery_inputs(project_path, state, episode)
    if errors:
        codes = "、".join(dict.fromkeys(item["code"] for item in errors))
        raise ToolError(f"逐集交付未就绪：{codes}")
    parsed = render_episode_script.parse_episode_script(inputs["script_text"])
    insertions = render_episode_script.build_turnaround_insertions(
        episode, parsed["scenes"], inputs["roster"], inputs["anchors"]
    )
    output_dir = project_path / "09_定稿交付" / "分集交付" / episode
    allowed_names = {f"{episode}_剧本.docx", f"{episode}_故事板.html"}
    if output_dir.exists():
        extras = [path.name for path in output_dir.iterdir() if path.name not in allowed_names]
        if extras:
            raise ToolError(f"逐集交付目录存在非目标文件，拒绝覆盖：{extras}")
    output_dir.mkdir(parents=True, exist_ok=True)
    script_output = render_episode_script.write_docx(
        str(state.get("name") or project_path.name),
        parsed,
        insertions,
        output_dir / f"{episode}_剧本.docx",
    )
    html_output = render_storyboard.render(
        project_path, episode, output_dir / f"{episode}_故事板.html"
    )
    print_json(
        {
            "ok": True,
            "episode": episode,
            "outputs": [str(script_output), str(html_output)],
            "dependencies": inputs["dependencies"],
        }
    )
    return 0


def command_render_storyboard(args: argparse.Namespace) -> int:
    """委托 render_storyboard 模块,把已确认分镜计划渲染成 HTML 故事板(只读)。"""
    import render_storyboard

    project_path, _state = load_state(args.project)
    requested_output = resolve_project_output(project_path, args.output) if args.output else None
    output = render_storyboard.render(
        project_path,
        args.episode,
        requested_output,
    )
    print_json({"ok": True, "output": str(output)})
    return 0


def issue(code: str, message: str, **location: Any) -> dict[str, Any]:
    return {"code": code, "message": message, **location}


ALLOWED_ADAPTATION_OPERATIONS = frozenset({
    "preserve",
    "compress",
    "merge",
    "reorder",
    "omit",
    "bridge_addition",
    "psychology_externalization",
    "scene_transition",
    "time_compression",
    "action_completion",
    "crowd_environment_reaction",
    "dramatic_expansion",
    "named_character",
    "merge_character",
    "new_subplot",
    "new_relationship",
    "new_ability",
    "new_major_event",
    "change_motivation",
    "change_choice",
    "change_cause",
    "change_outcome",
    "change_world_rule",
    "change_ending_nature",
    "hook_crisis",
})

AUTO_ALLOWED_BOUNDARY_CATEGORIES = frozenset({
    "psychology_externalization",
    "scene_transition",
    "time_compression",
    "action_completion",
    "crowd_environment_reaction",
    "dramatic_expansion",
})

DIALOGUE_REWRITE_METADATA_FIELDS = frozenset({
    "source_text",
    "delivered_text",
    "preservation_mode",
    "adaptation_note",
    "rewrite_reason",
    "rewrite_rationale",
    "semantic_match_score",
    "voice_preservation",
    "rewrite_approved",
    "new_fact_claims",
})

SPOKEN_CUE_TYPES = frozenset({"dialogue", "vo", "os"})
SPOKEN_DELIVERY_MODES = frozenset({
    "on_screen",
    "off_screen",
    "voice_over",
    "phone_audio",
    "screen_video",
    "phone_video",
})


STRUCTURED_DEVELOPMENT_TYPES = {
    "source_review",
    "source_corpus",
    "chapter_analysis_registry",
    "rolling_source_progress",
    "source_event_index",
    "batch_source_scope",
    "batch_source_detail",
    "batch_continuity_snapshot",
    "cross_batch_continuity_review",
    "change_authorization",
    "adaptation_decision_ledger",
    "series_boundary_review",
    "batch_boundary_review",
    "episode_boundary_review",
    "series_plan_review",
    "pilot_review",
    "seedance_execution_plan",
    "seedance_boundary_review",
    "genre_profile",
    "model_capability_profile",
    "dialogue_cue_sheet",
    "ai_shot_plan",
    "ai_video_boundary_review",
    "ai_video_execution_plan",
    "batch_delivery_review",
}

BATCH_BREAKDOWN_TYPES = (
    "character_roster",
    "scene_catalog",
    "prop_costume_ledger",
    "dialogue_cue_sheet",
    "continuity_ledger",
)


def batch_episode_ids(state: dict[str, Any], batch_id: str) -> list[str] | None:
    batches = state.get("batches", {})
    batch = batches.get(batch_id) if isinstance(batches, dict) else None
    episode_ids = batch.get("episode_ids") if isinstance(batch, dict) else None
    if not isinstance(episode_ids, list) or not episode_ids:
        return None
    if not all(
        isinstance(value, str) and EPISODE_ID_RE.fullmatch(value)
        for value in episode_ids
    ):
        return None
    return list(episode_ids)


def batch_delivery_input_keys(
    state: dict[str, Any], batch_id: str
) -> list[str] | None:
    episode_ids = batch_episode_ids(state, batch_id)
    if episode_ids is None:
        return None
    return [
        "series_map",
        "series_boundary_review",
        f"batch_source_scope:{batch_id}",
        f"batch_source_detail:{batch_id}",
        f"batch_outline:{batch_id}",
        f"batch_boundary_review:{batch_id}",
        *[f"episode_script:{episode_id}" for episode_id in episode_ids],
        *[f"episode_boundary_review:{episode_id}" for episode_id in episode_ids],
        *[f"{kind}:{batch_id}" for kind in BATCH_BREAKDOWN_TYPES],
        f"quality_report:{batch_id}",
        f"production_readiness_report:{batch_id}",
        f"batch_continuity_snapshot:{batch_id}",
    ]


def record_dependency_refs(record: dict[str, Any]) -> set[tuple[str, int]]:
    dependencies = record.get("depends_on")
    if not isinstance(dependencies, list):
        return set()
    return {
        (item.get("artifact_key"), item.get("version"))
        for item in dependencies
        if isinstance(item, dict)
        and isinstance(item.get("artifact_key"), str)
        and type(item.get("version")) is int
    }


def scoped_batch_outline_source_errors(
    state: dict[str, Any], artifact_key: str, record: dict[str, Any]
) -> list[dict[str, Any]]:
    if ":" not in artifact_key:
        return []
    batch_id = artifact_key.split(":", 1)[1]
    if not BATCH_ID_RE.fullmatch(batch_id):
        return []
    errors: list[dict[str, Any]] = []
    dependency_refs = record_dependency_refs(record)
    for key in (
        f"batch_source_scope:{batch_id}",
        f"batch_source_detail:{batch_id}",
    ):
        current = latest_record(state, key)
        version = current.get("version") if isinstance(current, dict) else None
        if type(version) is not int or (key, version) not in dependency_refs:
            errors.append(
                issue(
                    "batch_outline_source_dependency_missing",
                    "作用域批次大纲必须绑定当前批次原著范围和原著细化版本",
                    artifact_key=artifact_key,
                    missing_dependency=key,
                )
            )
    return errors


def payload_generated_refs(payload: dict[str, Any]) -> tuple[list[tuple[str, int]], set[tuple[str, int]]]:
    generated_from = payload.get("generated_from")
    if not isinstance(generated_from, list):
        return [], set()
    valid = [
        (item.get("artifact_key"), item.get("version"))
        for item in generated_from
        if isinstance(item, dict)
        and isinstance(item.get("artifact_key"), str)
        and type(item.get("version")) is int
    ]
    return valid, set(valid)


def load_json_artifact_payload(
    project_path: Path,
    artifact_key: str,
    record: dict[str, Any],
    errors: list[dict[str, Any]],
) -> dict[str, Any] | None:
    artifact_path = path_from_record(project_path, record.get("path"))
    try:
        payload = (
            json.loads(artifact_path.read_text(encoding="utf-8-sig"))
            if artifact_path and artifact_path.suffix.lower() == ".json"
            else None
        )
    except (OSError, UnicodeError, json.JSONDecodeError):
        payload = None
    if not isinstance(payload, dict):
        errors.append(
            issue(
                "structured_artifact_json_required",
                f"{ARTIFACT_TYPES.get(record.get('artifact_type'), artifact_key)}必须是规范 JSON",
                artifact_key=artifact_key,
            )
        )
        return None
    return payload


def dependency_payload_of_type(
    project_path: Path,
    state: dict[str, Any],
    record: dict[str, Any],
    dependency_type: str,
) -> dict[str, Any] | None:
    for dependency in record.get("depends_on", []):
        if not isinstance(dependency, dict):
            continue
        key = dependency.get("artifact_key")
        version = dependency.get("version")
        if not isinstance(key, str):
            continue
        try:
            if artifact_type(key) != dependency_type:
                continue
        except ToolError:
            continue
        records = state.get("artifacts", {}).get(key, [])
        dependency_record = next(
            (
                item
                for item in records
                if isinstance(item, dict) and item.get("version") == version
            ),
            None,
        )
        if dependency_record is None:
            return None
        dependency_path = path_from_record(project_path, dependency_record.get("path"))
        try:
            payload = (
                json.loads(dependency_path.read_text(encoding="utf-8-sig"))
                if dependency_path and dependency_path.suffix.lower() == ".json"
                else None
            )
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None
    return None


def state_expected_episodes_hint(state: dict[str, Any]) -> int | None:
    """init --expected-episodes 登记的目标集数提示；只用于规划期，不作交付权威。"""
    value = state.get("expected_episodes_hint")
    return value if type(value) is int and value > 0 else None


def effective_confirmed_project_spec_record(
    project_path: Path, state: dict[str, Any]
) -> dict[str, Any] | None:
    """返回最高版本的有效确认项目规格，忽略其后的草稿或待确认版本。"""
    records = state.get("artifacts", {}).get("project_spec", [])
    if not isinstance(records, list):
        return None
    candidates = sorted(
        (record for record in records if isinstance(record, dict)),
        key=version_sort_key,
        reverse=True,
    )
    for record in candidates:
        version = record.get("version")
        if record.get("status") != "confirmed" or type(version) is not int:
            continue
        if not has_active_approval(state, "project_spec", version):
            continue
        path = path_from_record(project_path, record.get("path"))
        if (
            path is None
            or not path.is_file()
            or sha256_file(path) != record.get("sha256")
            or path.stat().st_size != record.get("size_bytes")
        ):
            continue
        dependencies = record.get("depends_on")
        if dependencies != []:
            continue
        return record
    return None


def project_expected_episodes(project_path: Path, state: dict[str, Any]) -> int | None:
    record = effective_confirmed_project_spec_record(project_path, state)
    if record is None:
        return None
    path = path_from_record(project_path, record.get("path"))
    try:
        payload = (
            json.loads(path.read_text(encoding="utf-8-sig"))
            if path and path.suffix.lower() == ".json"
            else None
        )
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if isinstance(payload, dict) and payload.get("scope_mode") == "rolling_batch" and payload.get("schema_version") == 2:
        expected = payload.get("final_expected_episodes")
    else:
        expected = payload.get("expected_episodes") if isinstance(payload, dict) else None
    return expected if type(expected) is int and expected > 0 else None


def confirmed_project_spec_payload(
    project_path: Path, state: dict[str, Any]
) -> dict[str, Any] | None:
    """当前有效确认项目规格；更新版本未确认时继续使用上一份有效确认。"""
    record = effective_confirmed_project_spec_record(project_path, state)
    if record is None:
        return None
    return load_project_spec_payload(project_path, record)


def confirmed_episode_ids(state: dict[str, Any]) -> list[str]:
    batches = state.get("batches", {})
    if not isinstance(batches, dict):
        return []
    values: set[str] = set()
    for batch in batches.values():
        if not isinstance(batch, dict) or batch.get("status", "confirmed") != "confirmed":
            continue
        episode_ids = batch.get("episode_ids")
        if isinstance(episode_ids, list):
            values.update(
                value
                for value in episode_ids
                if isinstance(value, str) and EPISODE_ID_RE.fullmatch(value)
            )
    return sorted(values, key=lambda value: int(value[1:]))


def project_target_duration_seconds(
    project_path: Path, state: dict[str, Any]
) -> int:
    """返回单集目标时长；显式项目规格优先，否则使用 60 秒默认值。"""
    payload = confirmed_project_spec_payload(project_path, state)
    value = payload.get("target_duration_seconds") if isinstance(payload, dict) else None
    return value if type(value) is int and value > 0 else DEFAULT_TARGET_DURATION_SECONDS


def project_duration_source(project_path: Path, state: dict[str, Any]) -> str:
    payload = confirmed_project_spec_payload(project_path, state)
    value = payload.get("target_duration_seconds") if isinstance(payload, dict) else None
    return "explicit_project_spec" if type(value) is int and value > 0 else "default_60_seconds"


def project_duration_policy(
    project_path: Path, state: dict[str, Any]
) -> dict[str, Any]:
    """项目规格的时长策略；缺省值来自 script-format-and-quality.md 的既有约定。"""
    payload = confirmed_project_spec_payload(project_path, state)
    policy = payload.get("duration_policy") if isinstance(payload, dict) else None
    return policy if isinstance(policy, dict) else {}


def duration_tolerance_ratio(policy: dict[str, Any]) -> float:
    """分镜计划合计时长的允许偏差；缺省为 0.1（±10%）。"""
    value = policy.get("tolerance_ratio")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return DEFAULT_DURATION_TOLERANCE_RATIO
    if not math.isfinite(value) or value < 0 or value > 1:
        return DEFAULT_DURATION_TOLERANCE_RATIO
    return float(value)


def dialogue_chars_per_second(policy: dict[str, Any]) -> tuple[float, float]:
    """中文配音字/秒推算区间；缺省 3.5—4.5 是样本推算值，不是行业标准。"""
    value = policy.get("dialogue_chars_per_second")
    if (
        isinstance(value, list)
        and len(value) == 2
        and all(
            not isinstance(item, bool)
            and isinstance(item, (int, float))
            and math.isfinite(item)
            and item > 0
            for item in value
        )
        and value[0] <= value[1]
    ):
        return float(value[0]), float(value[1])
    return DEFAULT_DIALOGUE_CHARS_PER_SECOND


def validate_series_map_payload(
    state: dict[str, Any],
    payload: dict[str, Any],
    expected_episodes: int | None,
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    if type(payload.get("schema_version")) is not int or payload.get("schema_version") != 1:
        errors.append(issue("series_map_schema_invalid", "全剧分集地图 schema_version 必须为1"))
    if payload.get("project_id") != state.get("project_id"):
        errors.append(issue("series_map_project_mismatch", "全剧分集地图 project_id 不一致"))
    granularity = payload.get("granularity", "full")
    if granularity not in {"full", "backbone"}:
        errors.append(
            issue(
                "series_map_granularity_invalid",
                "全剧分集地图 granularity 必须为 full 或 backbone",
            )
        )
    contract_version = payload.get("contract_version")
    if granularity == "backbone" and contract_version == 2:
        episodes = payload.get("episodes")
        if isinstance(episodes, list):
            for index, episode in enumerate(episodes):
                if not isinstance(episode, dict):
                    continue
                summary = episode.get("summary")
                if not isinstance(summary, str) or not summary.strip():
                    errors.append(
                        issue(
                            "series_map_backbone_summary_missing",
                            "v0.8 backbone 每集必须包含非空 summary",
                            episode_index=index,
                            episode_id=episode.get("episode_id"),
                        )
                    )
    map_episode_count = payload.get("expected_episodes")
    if type(map_episode_count) is not int or map_episode_count < 1:
        errors.append(
            issue(
                "series_map_episode_count_invalid",
                "全剧分集地图 expected_episodes 必须是大于0的整数",
            )
        )
        coverage_count = expected_episodes
    else:
        coverage_count = expected_episodes or map_episode_count
        if expected_episodes is not None and map_episode_count != expected_episodes:
            errors.append(
                issue(
                    "series_map_episode_count_mismatch",
                    "全剧分集地图、项目规格和交付参数的总集数不一致",
                )
            )
    map_episodes = payload.get("episodes")
    actual_episode_ids = {
        item.get("episode_id")
        for item in map_episodes
        if isinstance(item, dict) and isinstance(item.get("episode_id"), str)
    } if isinstance(map_episodes, list) else set()
    required_episode_ids = {
        f"E{number:03d}" for number in range(1, coverage_count + 1)
    } if type(coverage_count) is int and coverage_count > 0 else set()
    if (
        not isinstance(map_episodes, list)
        or not required_episode_ids
        or len(map_episodes) != len(required_episode_ids)
        or actual_episode_ids != required_episode_ids
    ):
        errors.append(
            issue(
                "series_map_episode_coverage_invalid",
                "全剧分集地图 episodes 必须逐一覆盖 E001...EN，不能缺集、重集或多集",
            )
        )
    return errors


def series_map_payload_warnings(payload: dict[str, Any]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    if payload.get("granularity", "full") != "backbone":
        return warnings
    if payload.get("contract_version") != 2:
        warnings.append(
            issue(
                "series_map_backbone_upgrade_required",
                "旧 backbone 可读取，但再次确认、批次细化或交付前必须升级为 contract_version=2",
            )
        )
        return warnings
    missing: list[dict[str, Any]] = []
    for episode in payload.get("episodes", []):
        if not isinstance(episode, dict):
            continue
        fields = [
            field
            for field in ("goal", "core_conflict", "source_hint", "end_hook")
            if not isinstance(episode.get(field), str) or not episode[field].strip()
        ]
        if fields:
            missing.append({"episode_id": episode.get("episode_id"), "fields": fields})
    if missing:
        warnings.append(
            issue(
                "series_map_backbone_field_recommended",
                "backbone 推荐补充 goal/core_conflict/source_hint/end_hook；缺少时不阻塞",
                missing=missing,
            )
        )
    return warnings


def dependency_record_of_type(
    state: dict[str, Any],
    record: dict[str, Any],
    dependency_type: str,
) -> tuple[str, dict[str, Any]] | None:
    matches: list[tuple[str, dict[str, Any]]] = []
    for dependency in record.get("depends_on", []):
        if not isinstance(dependency, dict):
            continue
        key = dependency.get("artifact_key")
        version = dependency.get("version")
        if not isinstance(key, str):
            continue
        try:
            if artifact_type(key) != dependency_type:
                continue
        except ToolError:
            continue
        dependency_record = next(
            (
                item
                for item in state.get("artifacts", {}).get(key, [])
                if isinstance(item, dict) and item.get("version") == version
            ),
            None,
        )
        if dependency_record is not None:
            matches.append((key, dependency_record))
    return matches[0] if len(matches) == 1 else None


def source_reference_ids(event_index: dict[str, Any] | None) -> set[str]:
    references: set[str] = set()
    units = event_index.get("units") if isinstance(event_index, dict) else None
    if not isinstance(units, list):
        return references
    for unit in units:
        if not isinstance(unit, dict):
            continue
        for value in (unit.get("source_unit_id"), unit.get("source_locator")):
            if isinstance(value, str) and value.strip():
                references.add(value)
        events = unit.get("events")
        if not isinstance(events, list):
            continue
        for event in events:
            if not isinstance(event, dict):
                continue
            event_id = event.get("event_id")
            if isinstance(event_id, str) and event_id.strip():
                references.add(event_id)
            for value in event.get("source_refs", []):
                if isinstance(value, str) and value.strip():
                    references.add(value)
    return references


def validate_seedance_unit_content_contract(
    unit: dict[str, Any],
    beats: dict[str, dict[str, Any]],
    decisions_by_id: dict[str, dict[str, Any]],
    unit_index: int,
    strict_contract: bool = False,
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    if not strict_contract and "content_atoms" not in unit:
        return errors
    refs = unit.get("source_beat_refs") if isinstance(unit.get("source_beat_refs"), list) else []
    source_atoms: dict[str, dict[str, Any]] = {}
    for beat_id in refs:
        beat = beats.get(beat_id)
        if isinstance(beat, dict):
            source_atoms.update(beat.get("content_atoms", {}))
    atoms_raw = unit.get("content_atoms")
    if not isinstance(atoms_raw, list) or not atoms_raw:
        return [issue("seedance_content_atoms_missing", "Seedance严格执行单元必须声明 content_atoms", unit_index=unit_index)]
    atoms: dict[str, dict[str, Any]] = {}
    for atom in atoms_raw:
        if not isinstance(atom, dict) or not isinstance(atom.get("atom_id"), str) or not isinstance(atom.get("text"), str):
            errors.append(issue("seedance_content_atom_invalid", "Seedance content atom 非法", unit_index=unit_index))
            continue
        atom_id = atom["atom_id"]
        if atom.get("origin") == "source":
            source_atom = source_atoms.get(atom.get("source_atom_id"))
            if not isinstance(source_atom, dict) or compact_dialogue_text(atom["text"]) != compact_dialogue_text(str(source_atom.get("text", ""))):
                errors.append(issue("seedance_content_atom_source_mismatch", "Seedance source atom 必须逐字继承来源 beat", unit_index=unit_index, atom_id=atom_id))
        elif atom.get("origin") == "approved_decision":
            decision = decisions_by_id.get(atom.get("decision_id"))
            authorized = decision.get("authorized_content") if isinstance(decision, dict) else None
            if not isinstance(decision, dict) or decision.get("status") != "accepted" or not isinstance(authorized, list) or atom["text"] not in authorized:
                errors.append(issue("seedance_content_atom_decision_invalid", "Seedance决策 atom 未获逐字授权", unit_index=unit_index, atom_id=atom_id))
        else:
            errors.append(issue("seedance_content_atom_invalid", "Seedance content atom origin 无效", unit_index=unit_index, atom_id=atom_id))
        atoms[atom_id] = atom
    bindings = unit.get("content_bindings")
    if not isinstance(bindings, dict):
        return errors + [issue("seedance_content_bindings_missing", "Seedance严格执行单元必须声明 content_bindings", unit_index=unit_index)]
    for field in ("start_state", "end_state", "prompt_text"):
        atom_ids = bindings.get(field)
        compiled = compiled_content_atom_text(atom_ids, atoms) if isinstance(atom_ids, list) else None
        if compiled is None or compact_dialogue_text(str(unit.get(field, ""))) != compact_dialogue_text(compiled):
            errors.append(issue("seedance_prompt_content_unproven", f"{field} 必须由绑定 content atoms 确定性编译", unit_index=unit_index, field=field))
    shots = unit.get("shots")
    if isinstance(shots, list):
        for shot_index, shot in enumerate(shots, 1):
            if not isinstance(shot, dict):
                continue
            atom_ids = shot.get("content_atom_refs")
            compiled = compiled_content_atom_text(atom_ids, atoms) if isinstance(atom_ids, list) else None
            if compiled is None or compact_dialogue_text(str(shot.get("visual_action", ""))) != compact_dialogue_text(compiled):
                errors.append(issue("seedance_prompt_content_unproven", "shots[].visual_action 必须由绑定 content atoms 确定性编译", unit_index=unit_index, shot_index=shot_index))
    return errors


def validate_seedance_execution_payload(
    project_path: Path,
    state: dict[str, Any],
    artifact_key: str,
    record: dict[str, Any],
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    """校验纯文字 Seedance 执行层；不调用模型，也不接受嵌入图片数据。"""
    errors: list[dict[str, Any]] = []
    scope = artifact_key.split(":", 1)[1] if ":" in artifact_key else ""
    if not re.fullmatch(r"E\d{3,6}", scope, re.IGNORECASE):
        errors.append(issue("seedance_key_scope_invalid", "Seedance执行计划 key 必须使用 seedance_execution_plan:E001 形式"))
    episode_id = payload.get("episode_id")
    if not isinstance(episode_id, str) or episode_id.upper() != scope.upper():
        errors.append(issue("seedance_episode_mismatch", "Seedance执行计划 episode_id 与制品 key 不一致"))

    embedded_text = json.dumps(payload, ensure_ascii=False)
    if re.search(r"data:(?:image|video|audio)/|\bb64_json\b|\bbase64\b", embedded_text, re.IGNORECASE):
        errors.append(issue("seedance_embedded_binary_forbidden", "Seedance文字执行计划禁止嵌入 Base64 或 data URI 媒体数据"))

    model_profile = payload.get("model_profile")
    if not isinstance(model_profile, dict):
        errors.append(issue("seedance_model_profile_invalid", "model_profile 必须是对象"))
        model_profile = {}
    family = model_profile.get("family")
    if not isinstance(family, str) or re.sub(r"\s+", "", family).lower() not in {
        "seedance2.0", "seedance2"
    }:
        errors.append(issue("seedance_model_family_invalid", "model_profile.family 必须明确为 Seedance 2.0"))
    provider_model_id = model_profile.get("provider_model_id")
    if provider_model_id is not None and (
        not isinstance(provider_model_id, str) or not provider_model_id.strip()
    ):
        errors.append(issue("seedance_provider_model_id_invalid", "provider_model_id 如填写必须是非空字符串"))
    snapshot = model_profile.get("capability_snapshot")
    if not isinstance(snapshot, dict):
        errors.append(issue("seedance_capability_snapshot_missing", "必须记录模型能力核验快照，避免把旧接口参数冒充当前事实"))
        snapshot = {}
    if snapshot.get("status") not in {"verified", "user_confirmed"}:
        errors.append(issue("seedance_capability_status_invalid", "能力快照 status 必须为 verified 或 user_confirmed"))
    if not isinstance(snapshot.get("checked_at"), str) or not snapshot["checked_at"].strip():
        errors.append(issue("seedance_capability_checked_at_missing", "能力快照缺少 checked_at"))
    source_urls = snapshot.get("source_urls")
    if not isinstance(source_urls, list) or not source_urls or not all(
        isinstance(value, str) and value.startswith("https://") for value in source_urls
    ):
        errors.append(issue("seedance_capability_sources_invalid", "能力快照必须提供非空 HTTPS 来源列表"))
    elif not any(
        "seed.bytedance.com" in value or "volcengine.com" in value
        for value in source_urls
    ):
        errors.append(issue("seedance_official_source_missing", "能力快照至少需要一条字节 Seed 或火山引擎官方来源"))

    execution_policy = payload.get("execution_policy")
    if not isinstance(execution_policy, dict):
        errors.append(issue("seedance_execution_policy_invalid", "execution_policy 必须是对象"))
        execution_policy = {}
    if execution_policy.get("generate_images") is not False:
        errors.append(issue("seedance_image_generation_forbidden", "Seedance兼容层必须明确 generate_images: false"))
    if execution_policy.get("submit_video_requests") is not False:
        errors.append(issue("seedance_video_submission_forbidden", "本插件只生成文字执行层，必须明确 submit_video_requests: false"))
    if execution_policy.get("asset_handling") not in {"text_only", "existing_assets_only"}:
        errors.append(issue("seedance_asset_policy_invalid", "asset_handling 只能为 text_only 或 existing_assets_only"))
    for field in ("prompt_language", "subtitle_policy", "timing_policy"):
        if not isinstance(execution_policy.get(field), str) or not execution_policy[field].strip():
            errors.append(issue("seedance_execution_policy_field_missing", f"execution_policy 缺少 {field}", field=field))
    if execution_policy.get("timing_policy") != "unit_duration_only":
        errors.append(issue("seedance_timing_policy_invalid", "timing_policy 必须为 unit_duration_only，不在提示词内硬锁秒点"))

    constraints = payload.get("model_constraints")
    if not isinstance(constraints, dict):
        errors.append(issue("seedance_model_constraints_invalid", "model_constraints 必须是对象"))
        constraints = {}
    duration_range = constraints.get("unit_duration_seconds")
    if not isinstance(duration_range, dict):
        errors.append(issue("seedance_duration_range_invalid", "unit_duration_seconds 必须包含 min 与 max"))
        duration_range = {}
    minimum = duration_range.get("min")
    maximum = duration_range.get("max")
    if type(minimum) is not int or type(maximum) is not int or minimum < 1 or maximum < minimum or maximum > 60:
        errors.append(issue("seedance_duration_range_invalid", "单元时长范围必须是1至60秒内的有效整数区间"))
        minimum, maximum = 1, 60
    for field in ("ratio", "resolution"):
        if not isinstance(constraints.get(field), str) or not constraints[field].strip():
            errors.append(issue("seedance_model_constraint_field_missing", f"model_constraints 缺少 {field}", field=field))
    if type(constraints.get("generate_audio")) is not bool:
        errors.append(issue("seedance_audio_flag_invalid", "model_constraints.generate_audio 必须是布尔值"))

    reference_assets = payload.get("reference_assets")
    if not isinstance(reference_assets, list):
        errors.append(issue("seedance_reference_assets_invalid", "reference_assets 必须是数组；纯文本模式使用空数组"))
        reference_assets = []
    asset_ids: set[str] = set()
    for index, asset in enumerate(reference_assets):
        if not isinstance(asset, dict):
            errors.append(issue("seedance_reference_asset_invalid", "参考素材记录必须是对象", asset_index=index))
            continue
        asset_id = asset.get("asset_id")
        if not isinstance(asset_id, str) or not asset_id.strip():
            errors.append(issue("seedance_reference_asset_id_invalid", "参考素材缺少 asset_id", asset_index=index))
        elif asset_id in asset_ids:
            errors.append(issue("seedance_reference_asset_id_duplicate", f"参考素材 ID 重复：{asset_id}"))
        else:
            asset_ids.add(asset_id)
        if asset.get("origin") not in {"user_provided", "existing_project", "generated_elsewhere"}:
            errors.append(issue("seedance_reference_asset_origin_invalid", "参考素材只能来自用户、现有项目或外部既有资产，不能由本插件生成", asset_index=index))
        if asset.get("media_type") not in {"image", "video", "audio"}:
            errors.append(issue("seedance_reference_asset_type_invalid", "参考素材 media_type 无效", asset_index=index))
        if asset.get("status") not in {"provided", "unbound"}:
            errors.append(issue("seedance_reference_asset_status_invalid", "参考素材 status 只能为 provided 或 unbound", asset_index=index))
        locator = asset.get("locator")
        if locator is not None and (
            not isinstance(locator, str) or locator.lower().startswith("data:")
        ):
            errors.append(issue("seedance_reference_asset_locator_invalid", "参考素材 locator 不能是 data URI"))

    event_index = dependency_payload_of_type(project_path, state, record, "source_event_index")
    canonical_character_ids = source_character_ids(event_index)
    valid_source_refs = source_reference_ids(event_index)
    ledger = dependency_payload_of_type(project_path, state, record, "adaptation_decision_ledger")
    decisions = ledger.get("decisions") if isinstance(ledger, dict) else None
    valid_decision_ids = {
        item.get("decision_id")
        for item in decisions
        if isinstance(item, dict) and isinstance(item.get("decision_id"), str)
    } if isinstance(decisions, list) else set()
    decisions_by_id = {
        item.get("decision_id"): item
        for item in decisions
        if isinstance(item, dict) and isinstance(item.get("decision_id"), str)
    } if isinstance(decisions, list) else {}
    beats = source_beat_index(event_index)
    if payload.get("content_contract_version") != 1:
        errors.append(issue("seedance_content_contract_upgrade_required", "Seedance执行计划必须使用 content_contract_version=1"))

    script_dependency = dependency_record_of_type(state, record, "episode_script")
    script_scenes: dict[str, dict[str, Any]] = {}
    if script_dependency is None:
        errors.append(issue("seedance_script_dependency_invalid", "执行计划必须精确绑定一份分集剧本"))
    else:
        script_key, script_record = script_dependency
        script_path = path_from_record(project_path, script_record.get("path"))
        try:
            script_scenes, _ = extract_script_index(script_path, script_key) if script_path else ({}, [])
        except (OSError, UnicodeError):
            script_scenes = {}
        if not script_scenes:
            errors.append(issue("seedance_script_unreadable", "无法从绑定剧本提取场次"))

    cue_sheet = dependency_payload_of_type(project_path, state, record, "dialogue_cue_sheet")
    cue_records = cue_sheet.get("records") if isinstance(cue_sheet, dict) else None
    cues_by_id: dict[str, dict[str, Any]] = {}
    expected_cue_ids: set[str] = set()
    if isinstance(cue_records, list):
        for cue in cue_records:
            if not isinstance(cue, dict):
                continue
            cue_id = cue.get("cue_id")
            if not isinstance(cue_id, str) or not cue_id.strip():
                continue
            cues_by_id[cue_id] = cue
            if cue.get("episode_id") == episode_id and cue.get("type") in {"dialogue", "vo", "os"}:
                expected_cue_ids.add(cue_id)
    else:
        errors.append(issue("seedance_cue_sheet_unreadable", "无法读取绑定的台词声音表"))

    global_constraints = payload.get("global_constraints")
    if not isinstance(global_constraints, list) or not global_constraints or not all(
        isinstance(value, str) and value.strip() for value in global_constraints
    ):
        errors.append(issue("seedance_global_constraints_invalid", "global_constraints 必须是非空字符串数组"))

    units = payload.get("units")
    if not isinstance(units, list) or not units:
        errors.append(issue("seedance_units_invalid", "Seedance执行计划 units 必须是非空数组"))
        return errors
    seen_unit_ids: set[str] = set()
    used_cue_ids: list[str] = []
    total_duration = 0
    previous_chain: str | None = None
    previous_output_state: str | None = None
    allowed_modes = {"text_to_video", "multimodal_reference", "first_frame", "first_last_frame", "continuation"}
    hard_timestamp = re.compile(r"(?<!\d)\d{1,2}\s*(?:[-—~至到])\s*\d{1,2}\s*秒")
    for index, unit in enumerate(units, 1):
        if not isinstance(unit, dict):
            errors.append(issue("seedance_unit_invalid", "执行单元必须是对象", unit_index=index))
            continue
        errors.extend(validate_seedance_unit_content_contract(unit, beats, decisions_by_id, index, True))
        unit_id = unit.get("unit_id")
        if not isinstance(unit_id, str) or not re.fullmatch(
            rf"SD2-{re.escape(episode_id or scope)}-U\d{{3}}", unit_id, re.IGNORECASE
        ):
            errors.append(issue("seedance_unit_id_invalid", "unit_id 必须使用 SD2-E001-U001 形式", unit_index=index))
        elif unit_id in seen_unit_ids:
            errors.append(issue("seedance_unit_id_duplicate", f"执行单元 ID 重复：{unit_id}"))
        else:
            seen_unit_ids.add(unit_id)
        if unit.get("sequence") != index:
            errors.append(issue("seedance_unit_sequence_invalid", "执行单元 sequence 必须从1连续递增", unit_index=index))
        scene_id = unit.get("scene_id")
        if not isinstance(scene_id, str) or scene_id not in script_scenes:
            errors.append(issue("seedance_scene_unknown", "执行单元引用了绑定剧本中不存在的 scene_id", unit_index=index, scene_id=scene_id))
        duration = unit.get("duration_seconds")
        if type(duration) is not int or duration < minimum or duration > maximum:
            errors.append(issue("seedance_unit_duration_invalid", "执行单元时长超出已核验模型能力区间", unit_index=index, duration=duration))
        else:
            total_duration += duration
        unit_source_refs = unit.get("source_refs")
        if not isinstance(unit_source_refs, list) or not unit_source_refs or not all(
            isinstance(value, str) and value.strip() for value in unit_source_refs
        ):
            errors.append(issue("seedance_unit_source_refs_invalid", "每个执行单元必须提供非空 source_refs", unit_index=index))
        else:
            unknown_refs = sorted(set(unit_source_refs) - valid_source_refs)
            if unknown_refs:
                errors.append(issue("seedance_unit_source_ref_unknown", "执行单元引用了事件索引中不存在的原著依据", unit_index=index, unknown=unknown_refs))
        decision_ids = unit.get("decision_ids", [])
        if not isinstance(decision_ids, list) or not all(
            isinstance(value, str) and value.strip() for value in decision_ids
        ):
            errors.append(issue("seedance_unit_decision_ids_invalid", "decision_ids 必须是字符串数组", unit_index=index))
        elif set(decision_ids) - valid_decision_ids:
            errors.append(issue("seedance_unit_decision_unknown", "执行单元引用了未知改编决策", unit_index=index, unknown=sorted(set(decision_ids) - valid_decision_ids)))
        for field in ("start_state", "end_state", "prompt_text"):
            if not isinstance(unit.get(field), str) or not unit[field].strip():
                errors.append(issue("seedance_unit_field_missing", f"执行单元缺少 {field}", unit_index=index, field=field))
        prompt_text = unit.get("prompt_text") if isinstance(unit.get("prompt_text"), str) else ""
        if hard_timestamp.search(prompt_text):
            errors.append(issue("seedance_prompt_hard_timestamp", "提示词不得使用0-3秒一类镜头内硬秒点；只在单元参数声明总时长", unit_index=index))
        mode = unit.get("generation_mode")
        if mode not in allowed_modes:
            errors.append(issue("seedance_generation_mode_invalid", "generation_mode 无效", unit_index=index))
        unit_asset_ids = unit.get("reference_asset_ids")
        if not isinstance(unit_asset_ids, list) or not all(
            isinstance(value, str) and value.strip() for value in unit_asset_ids
        ):
            errors.append(issue("seedance_unit_assets_invalid", "reference_asset_ids 必须是字符串数组", unit_index=index))
            unit_asset_ids = []
        unknown_assets = sorted(set(unit_asset_ids) - asset_ids)
        if unknown_assets:
            errors.append(issue("seedance_unit_asset_unknown", "执行单元引用了未登记参考素材", unit_index=index, unknown=unknown_assets))
        if mode == "text_to_video" and unit_asset_ids:
            errors.append(issue("seedance_text_mode_has_assets", "text_to_video 单元不得绑定参考素材", unit_index=index))
        if mode not in {"text_to_video", "continuation"} and not unit_asset_ids:
            errors.append(issue("seedance_reference_mode_without_assets", "非纯文本模式必须绑定已有参考素材", unit_index=index))
        unavailable_assets = {
            asset.get("asset_id")
            for asset in reference_assets
            if isinstance(asset, dict) and asset.get("status") != "provided"
        }
        if set(unit_asset_ids) & unavailable_assets:
            errors.append(issue("seedance_reference_asset_unbound", "执行单元绑定的参考素材尚未提供，不能声称可提交", unit_index=index))

        continuity = unit.get("continuity")
        if not isinstance(continuity, dict):
            errors.append(issue("seedance_continuity_invalid", "执行单元 continuity 必须是对象", unit_index=index))
            continuity = {}
        chain_id = continuity.get("chain_id")
        input_state = continuity.get("input_state")
        output_state = continuity.get("output_state")
        if not all(isinstance(value, str) and value.strip() for value in (chain_id, input_state, output_state)):
            errors.append(issue("seedance_continuity_field_missing", "continuity 必须包含非空 chain_id/input_state/output_state", unit_index=index))
        if previous_chain == chain_id and previous_output_state != input_state:
            errors.append(issue("seedance_continuity_chain_break", "同一连续链的上一单元 output_state 必须等于下一单元 input_state", unit_index=index))
        if mode == "continuation" and not unit_asset_ids and previous_chain != chain_id:
            errors.append(issue("seedance_continuation_chain_start", "continuation 单元必须与上一单元同链续接；链首请改用其他生成模式或绑定参考素材", unit_index=index))
        previous_chain = chain_id if isinstance(chain_id, str) else None
        previous_output_state = output_state if isinstance(output_state, str) else None

        shots = unit.get("shots")
        if not isinstance(shots, list) or not shots:
            errors.append(issue("seedance_shots_invalid", "每个执行单元必须包含非空 shots", unit_index=index))
            continue
        for shot_index, shot in enumerate(shots, 1):
            if not isinstance(shot, dict):
                errors.append(issue("seedance_shot_invalid", "镜头记录必须是对象", unit_index=index, shot_index=shot_index))
                continue
            if shot.get("shot") != shot_index:
                errors.append(issue("seedance_shot_sequence_invalid", "shot 必须从1连续递增", unit_index=index, shot_index=shot_index))
            for field in ("camera", "visual_action"):
                if not isinstance(shot.get(field), str) or not shot[field].strip():
                    errors.append(issue("seedance_shot_field_missing", f"镜头缺少 {field}", unit_index=index, shot_index=shot_index, field=field))
            if not isinstance(shot.get("sound"), list) or not all(
                isinstance(value, str) and value.strip() for value in shot.get("sound", [])
            ):
                errors.append(issue("seedance_shot_sound_invalid", "shot.sound 必须是字符串数组", unit_index=index, shot_index=shot_index))
            cue_ids = shot.get("dialogue_cue_ids")
            if not isinstance(cue_ids, list) or not all(
                isinstance(value, str) and value.strip() for value in cue_ids
            ):
                errors.append(issue("seedance_shot_cues_invalid", "dialogue_cue_ids 必须是字符串数组", unit_index=index, shot_index=shot_index))
                cue_ids = []
            for cue_id in cue_ids:
                cue = cues_by_id.get(cue_id)
                if cue is None or cue_id not in expected_cue_ids:
                    errors.append(issue("seedance_cue_unknown", "镜头引用了当前集台词表中不存在的对白 cue", unit_index=index, shot_index=shot_index, cue_id=cue_id))
                    continue
                used_cue_ids.append(cue_id)
                if cue.get("scene_id") != scene_id:
                    errors.append(issue("seedance_cue_scene_mismatch", "镜头引用的对白 cue 不属于当前场次", unit_index=index, shot_index=shot_index, cue_id=cue_id))
                cue_text = cue.get("text")
                if isinstance(cue_text, str) and normalized_text(cue_text) not in normalized_text(prompt_text):
                    errors.append(issue("seedance_prompt_cue_missing", "prompt_text 未完整保留绑定 cue 的台词文本", unit_index=index, shot_index=shot_index, cue_id=cue_id))
    if payload.get("total_duration_seconds") != total_duration:
        errors.append(issue("seedance_total_duration_mismatch", "total_duration_seconds 必须等于全部执行单元时长之和"))
    used_counts = Counter(used_cue_ids)
    missing_cues = sorted(expected_cue_ids - set(used_cue_ids))
    duplicate_cues = sorted(cue_id for cue_id, count in used_counts.items() if count > 1)
    if missing_cues:
        errors.append(issue("seedance_cue_coverage_missing", "Seedance执行计划未覆盖当前集全部对白/VO/OS", missing=missing_cues))
    if duplicate_cues:
        errors.append(issue("seedance_cue_coverage_duplicate", "同一对白 cue 在执行计划中重复绑定", duplicate=duplicate_cues))
    return errors


GENERATION_STRATEGIES = {
    "static_frame",
    "partial_animation",
    "image_to_video",
    "first_frame",
    "tail_frame_chain",
    "text_to_video",
}


def anchor_reference_error(state: dict[str, Any], ref: Any, expected_type: str) -> str | None:
    """校验锚点引用是否指向已确认的当前版本；返回错误描述或 None。"""
    if not isinstance(ref, dict):
        return "锚点引用必须是 {artifact_key, version} 对象"
    key = ref.get("artifact_key")
    version = ref.get("version")
    if not isinstance(key, str) or type(version) is not int:
        return "锚点引用必须包含 artifact_key 与整数 version"
    try:
        if artifact_type(key) != expected_type:
            return f"锚点引用类型必须是 {expected_type}"
    except ToolError:
        return "锚点引用 key 无效"
    records = [item for item in state.get("artifacts", {}).get(key, []) if isinstance(item, dict)]
    target = next((item for item in records if item.get("version") == version), None)
    if target is None:
        return f"锚点 {key} 的版本 {version} 未登记"
    if target.get("status") != "confirmed":
        return f"锚点 {key} v{version} 尚未确认"
    confirmed_versions = [
        item.get("version")
        for item in records
        if item.get("status") == "confirmed" and type(item.get("version")) is int
    ]
    if confirmed_versions and version < max(confirmed_versions):
        return f"锚点 {key} 引用已过期：存在更新的已确认版本 v{max(confirmed_versions)}"
    return None


GENRE_TAG_LAYERS = {"audience", "genre", "trope"}


def validate_genre_profile_payload(
    project_path: Path,
    state: dict[str, Any],
    artifact_key: str,
    record: dict[str, Any],
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    """校验题材标签卡：证据打标、受众唯一、主题材有效、置信度明示。"""
    errors: list[dict[str, Any]] = []
    tags = payload.get("tags")
    if not isinstance(tags, list) or not tags:
        errors.append(issue("genre_tags_missing", "tags 必须是非空数组"))
        tags = []
    tag_ids: set[str] = set()
    audience_count = 0
    genre_ids: set[str] = set()
    for index, tag in enumerate(tags, 1):
        if not isinstance(tag, dict):
            errors.append(issue("genre_tag_invalid", "标签必须是对象", tag_index=index))
            continue
        tag_id = tag.get("tag_id")
        layer = tag.get("layer")
        if not isinstance(tag_id, str) or not re.fullmatch(r"(audience|genre|trope)\.[a-z0-9_]+", tag_id):
            errors.append(issue("genre_tag_id_invalid", "tag_id 必须形如 audience.female / genre.urban / trope.rebirth", tag_index=index))
        elif tag_id in tag_ids:
            errors.append(issue("genre_tag_duplicate", f"标签重复：{tag_id}", tag_index=index))
        else:
            tag_ids.add(tag_id)
            if layer == "genre":
                genre_ids.add(tag_id)
        if layer not in GENRE_TAG_LAYERS:
            errors.append(issue("genre_tag_layer_invalid", "layer 只能为 audience/genre/trope", tag_index=index))
        elif isinstance(tag_id, str) and not tag_id.startswith(f"{layer}."):
            errors.append(issue("genre_tag_layer_mismatch", "tag_id 前缀必须与 layer 一致", tag_index=index))
        if layer == "audience":
            audience_count += 1
        if not isinstance(tag.get("label"), str) or not tag["label"].strip():
            errors.append(issue("genre_tag_label_missing", "标签缺少 label", tag_index=index))
        evidence = tag.get("evidence")
        if not isinstance(evidence, list) or not evidence or not all(
            isinstance(value, str) and value.strip() for value in evidence
        ):
            errors.append(issue("genre_tag_evidence_missing", "每个标签必须提供非空原著证据 evidence", tag_index=index))
        if tag.get("confidence") not in {"high", "medium", "low"}:
            errors.append(issue("genre_tag_confidence_invalid", "confidence 只能为 high/medium/low", tag_index=index))
    if audience_count != 1:
        errors.append(issue("genre_audience_count_invalid", "受众层标签必须恰好一个", found=audience_count))
    primary = payload.get("primary_genre")
    if not isinstance(primary, str) or primary not in genre_ids:
        errors.append(issue("genre_primary_invalid", "primary_genre 必须是已打的 genre 层标签之一"))
    directives = payload.get("adaptation_directives")
    if not isinstance(directives, dict) or not directives:
        errors.append(issue("genre_directives_missing", "必须提供 adaptation_directives（注入圣经与地图的改编倾向）"))
    uncertainties = payload.get("uncertainties")
    if uncertainties is not None and (
        not isinstance(uncertainties, list) or not all(
            isinstance(value, str) and value.strip() for value in uncertainties
        )
    ):
        errors.append(issue("genre_uncertainties_invalid", "uncertainties 必须是字符串数组"))
    return errors


def validate_model_capability_profile_payload(
    project_path: Path,
    state: dict[str, Any],
    artifact_key: str,
    record: dict[str, Any],
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    """校验模型能力档案：能力必须来自可追溯快照，不能写死或猜测。"""
    errors: list[dict[str, Any]] = []
    if not isinstance(payload.get("model_family"), str) or not payload["model_family"].strip():
        errors.append(issue("profile_model_family_missing", "model_family 必须是非空字符串"))
    provider_model_id = payload.get("provider_model_id")
    if provider_model_id is not None and (
        not isinstance(provider_model_id, str) or not provider_model_id.strip()
    ):
        errors.append(issue("profile_model_id_invalid", "provider_model_id 如填写必须是非空字符串"))
    snapshot = payload.get("capability_snapshot")
    if not isinstance(snapshot, dict):
        errors.append(issue("profile_snapshot_missing", "必须记录能力核验快照"))
        snapshot = {}
    if snapshot.get("status") not in {"verified", "user_confirmed"}:
        errors.append(issue("profile_snapshot_status_invalid", "能力快照 status 必须为 verified 或 user_confirmed"))
    if not isinstance(snapshot.get("checked_at"), str) or not snapshot["checked_at"].strip():
        errors.append(issue("profile_snapshot_checked_at_missing", "能力快照缺少 checked_at"))
    source_urls = snapshot.get("source_urls")
    if not isinstance(source_urls, list) or not source_urls or not all(
        isinstance(value, str) and value.startswith("https://") for value in source_urls
    ):
        errors.append(issue("profile_snapshot_sources_missing", "能力快照至少需要一条官方 HTTPS 来源"))
    capabilities = payload.get("capabilities")
    if not isinstance(capabilities, dict):
        errors.append(issue("profile_capabilities_missing", "capabilities 必须是对象"))
        capabilities = {}
    duration_range = capabilities.get("task_duration_seconds")
    if not isinstance(duration_range, dict):
        errors.append(issue("profile_duration_range_missing", "capabilities.task_duration_seconds 必须包含 min 与 max"))
    else:
        minimum = duration_range.get("min")
        maximum = duration_range.get("max")
        if type(minimum) is not int or type(maximum) is not int or minimum < 1 or maximum < minimum or maximum > 600:
            errors.append(issue("profile_duration_range_invalid", "任务时长范围必须是1至600秒内的有效整数区间"))
    input_modes = capabilities.get("input_modes")
    if not isinstance(input_modes, list) or not input_modes or not all(
        isinstance(value, str) and value.strip() for value in input_modes
    ):
        errors.append(issue("profile_input_modes_missing", "capabilities.input_modes 必须是非空字符串数组"))
    for flag in ("generate_audio", "lip_sync", "supports_first_frame", "supports_first_last_frame", "supports_continuation"):
        value = capabilities.get(flag)
        if value is not None and type(value) is not bool:
            errors.append(issue("profile_flag_invalid", f"capabilities.{flag} 必须是布尔值或 null（不清楚）", field=flag))
    for count_field in ("max_reference_images", "max_clear_speakers"):
        value = capabilities.get(count_field)
        if value is not None and (type(value) is not int or value < 0):
            errors.append(issue("profile_count_invalid", f"capabilities.{count_field} 必须是非负整数或 null（不清楚）", field=count_field))
    return errors


def source_beat_index(event_index: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Build a project-agnostic beat index from source_event_index schema v2."""
    result: dict[str, dict[str, Any]] = {}
    units = event_index.get("units") if isinstance(event_index, dict) else None
    if not isinstance(units, list):
        return result
    for unit in units:
        if not isinstance(unit, dict):
            continue
        for event in unit.get("events", []) if isinstance(unit.get("events"), list) else []:
            if not isinstance(event, dict) or type(event.get("ordinal")) is not int:
                continue
            event_ordinal = event["ordinal"]
            for beat in event.get("beats", []) if isinstance(event.get("beats"), list) else []:
                if not isinstance(beat, dict):
                    continue
                beat_id = beat.get("beat_id")
                beat_ordinal = beat.get("ordinal")
                if not isinstance(beat_id, str) or type(beat_ordinal) is not int:
                    continue
                content_atoms = beat.get("content_atoms")
                atom_map = {
                    atom.get("atom_id"): atom
                    for atom in content_atoms
                    if isinstance(atom, dict) and isinstance(atom.get("atom_id"), str)
                } if isinstance(content_atoms, list) else {}
                result[beat_id] = {
                    "order": (event_ordinal, beat_ordinal),
                    "source_refs": set(beat.get("source_refs", []))
                    if isinstance(beat.get("source_refs"), list)
                    else set(),
                    "protected_fact_ids": set(beat.get("protected_fact_ids", []))
                    if isinstance(beat.get("protected_fact_ids"), list)
                    else set(),
                    "required_fact_ids": set(beat.get("required_fact_ids", []))
                    if isinstance(beat.get("required_fact_ids"), list)
                    else set(),
                    "content_atoms": atom_map,
                    "story_time": beat.get("story_time") if isinstance(beat.get("story_time"), dict) else None,
                }
    return result


CONTENT_ATOM_KINDS = {
    "action", "state", "screen_text", "environment", "identity",
    "relationship", "knowledge", "causality", "time", "dialogue_context",
}
REQUIRED_FACT_TYPES = {"identity", "age", "relationship", "causality", "knowledge_change"}
STORY_DAY_PARTS = {"unknown", "dawn", "morning", "noon", "afternoon", "evening", "night", "late_night"}


def validate_source_content_contract(
    project_path: Path,
    corpus: dict[str, Any] | None,
    event_index: dict[str, Any],
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    source_texts: dict[str, str] = {}
    units = corpus.get("source_units") if isinstance(corpus, dict) else None
    if isinstance(units, list):
        for unit in units:
            if not isinstance(unit, dict):
                continue
            unit_id = unit.get("source_unit_id")
            path = path_from_record(project_path, unit.get("content_path"))
            if isinstance(unit_id, str) and path is not None and path.is_file():
                source_texts[unit_id] = path.read_text(encoding="utf-8")
    seen_atoms: set[str] = set()
    event_units = event_index.get("units") if isinstance(event_index, dict) else None
    for unit_index, event_unit in enumerate(event_units if isinstance(event_units, list) else [], 1):
        if not isinstance(event_unit, dict):
            continue
        for event_index_value, event in enumerate(event_unit.get("events", []) if isinstance(event_unit.get("events"), list) else [], 1):
            if not isinstance(event, dict):
                continue
            for beat_index, beat in enumerate(event.get("beats", []) if isinstance(event.get("beats"), list) else [], 1):
                if not isinstance(beat, dict):
                    continue
                atoms = beat.get("content_atoms")
                if not isinstance(atoms, list) or not atoms:
                    errors.append(issue("event_content_atoms_missing", "schema v2 beat 必须包含非空 content_atoms", unit_index=unit_index, event_index=event_index_value, beat_index=beat_index))
                    continue
                for atom_index, atom in enumerate(atoms, 1):
                    if not isinstance(atom, dict):
                        errors.append(issue("event_content_atom_invalid", "source content atom 必须是对象", beat_index=beat_index, atom_index=atom_index))
                        continue
                    atom_id = atom.get("atom_id")
                    text = atom.get("text")
                    excerpt = atom.get("source_excerpt")
                    source_unit_id = atom.get("source_unit_id")
                    if not isinstance(atom_id, str) or not atom_id.strip() or atom_id in seen_atoms:
                        errors.append(issue("event_content_atom_id_invalid", "source content atom ID 缺失或重复", beat_index=beat_index, atom_index=atom_index))
                    else:
                        seen_atoms.add(atom_id)
                    if atom.get("kind") not in CONTENT_ATOM_KINDS:
                        errors.append(issue("event_content_atom_kind_invalid", "source content atom kind 无效", atom_id=atom_id))
                    source_text = source_texts.get(source_unit_id) if isinstance(source_unit_id, str) else None
                    if not isinstance(excerpt, str) or not excerpt.strip() or not isinstance(source_text, str) or compact_dialogue_text(excerpt) not in compact_dialogue_text(source_text):
                        errors.append(issue("event_content_atom_excerpt_invalid", "source_excerpt 必须逐字存在于绑定原著单元", atom_id=atom_id, source_unit_id=source_unit_id))
                    if not isinstance(text, str) or not isinstance(excerpt, str) or compact_dialogue_text(text) != compact_dialogue_text(excerpt):
                        errors.append(issue("event_content_atom_text_mismatch", "source content atom text 必须等于 source_excerpt，不能改写", atom_id=atom_id))
                    if not isinstance(atom.get("source_locator"), str) or not atom["source_locator"].strip():
                        errors.append(issue("event_content_atom_locator_missing", "source content atom 缺少 source_locator", atom_id=atom_id))
    return errors


def validate_fact_definition_contract(event_index: dict[str, Any] | None) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    beats = source_beat_index(event_index)
    definitions = event_index.get("fact_definitions") if isinstance(event_index, dict) else None
    if not isinstance(definitions, list):
        return [issue("story_fact_definitions_invalid", "source_event_index.fact_definitions 必须是数组")]
    definitions_by_id: dict[str, dict[str, Any]] = {}
    for index, definition in enumerate(definitions, 1):
        if not isinstance(definition, dict):
            errors.append(issue("story_fact_definition_invalid", "事实定义必须是对象", fact_index=index))
            continue
        fact_id = definition.get("fact_id")
        if not isinstance(fact_id, str) or not fact_id.strip() or fact_id in definitions_by_id:
            errors.append(issue("story_fact_id_invalid", "fact_id 缺失或重复", fact_index=index))
            continue
        definitions_by_id[fact_id] = definition
        if definition.get("fact_type") not in REQUIRED_FACT_TYPES:
            errors.append(issue("story_fact_type_invalid", "fact_type 无效", fact_id=fact_id))
        source_beats = definition.get("source_beat_ids")
        if not isinstance(source_beats, list) or not source_beats or not all(isinstance(value, str) for value in source_beats):
            errors.append(issue("story_fact_source_beats_invalid", "source_beat_ids 必须是非空字符串数组", fact_id=fact_id))
        else:
            unknown = sorted(set(source_beats) - set(beats))
            if unknown:
                errors.append(issue("story_fact_source_beat_unknown", "事实定义引用未知 beat", fact_id=fact_id, unknown=unknown))
    required_backrefs: dict[str, set[str]] = {}
    for beat_id, beat in beats.items():
        for fact_id in beat.get("required_fact_ids", set()):
            required_backrefs.setdefault(fact_id, set()).add(beat_id)
    for fact_id, beat_ids in required_backrefs.items():
        definition = definitions_by_id.get(fact_id)
        if not isinstance(definition, dict):
            errors.append(issue("story_required_fact_missing", "beat.required_fact_ids 引用了未定义事实", fact_id=fact_id, beat_ids=sorted(beat_ids)))
            continue
        declared = set(definition.get("source_beat_ids", [])) if isinstance(definition.get("source_beat_ids"), list) else set()
        if not beat_ids.issubset(declared):
            errors.append(issue("story_required_fact_backref_mismatch", "事实定义 source_beat_ids 未覆盖所有 required_fact_ids 反向引用", fact_id=fact_id, missing=sorted(beat_ids - declared)))
    return errors


def compiled_content_atom_text(atom_ids: list[str], atoms: dict[str, dict[str, Any]]) -> str | None:
    if not atom_ids or any(atom_id not in atoms for atom_id in atom_ids):
        return None
    return "；".join(str(atoms[atom_id].get("text", "")).strip() for atom_id in atom_ids)


def validate_unit_content_contract(
    unit: dict[str, Any],
    beats: dict[str, dict[str, Any]],
    decisions_by_id: dict[str, dict[str, Any]],
    unit_index: int,
    strict_contract: bool = False,
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    if not strict_contract and "content_atoms" not in unit and "content_bindings" not in unit:
        return errors
    refs = unit.get("source_beat_refs")
    source_atom_map: dict[str, dict[str, Any]] = {}
    if isinstance(refs, list):
        for beat_id in refs:
            beat = beats.get(beat_id)
            if isinstance(beat, dict):
                source_atom_map.update(beat.get("content_atoms", {}))
    atoms_raw = unit.get("content_atoms")
    if not isinstance(atoms_raw, list) or not atoms_raw:
        errors.append(issue("shotplan_content_atoms_missing", "严格分镜单元必须声明非空 content_atoms", unit_index=unit_index))
        return errors
    atoms: dict[str, dict[str, Any]] = {}
    for atom_index, atom in enumerate(atoms_raw, 1):
        if not isinstance(atom, dict):
            errors.append(issue("shotplan_content_atom_invalid", "content atom 必须是对象", unit_index=unit_index, atom_index=atom_index))
            continue
        atom_id = atom.get("atom_id")
        text = atom.get("text")
        if not isinstance(atom_id, str) or not atom_id.strip() or atom_id in atoms or not isinstance(text, str) or not text.strip():
            errors.append(issue("shotplan_content_atom_invalid", "content atom 缺少唯一 atom_id 或非空 text", unit_index=unit_index, atom_index=atom_index))
            continue
        origin = atom.get("origin")
        if origin == "source":
            source_atom_id = atom.get("source_atom_id")
            source_atom = source_atom_map.get(source_atom_id) if isinstance(source_atom_id, str) else None
            if not isinstance(source_atom, dict) or compact_dialogue_text(text) != compact_dialogue_text(str(source_atom.get("text", ""))):
                errors.append(issue("shotplan_content_atom_source_mismatch", "source content atom 必须逐字继承当前分镜引用 beat 的原著 atom", unit_index=unit_index, atom_id=atom_id, source_atom_id=source_atom_id))
        elif origin == "approved_decision":
            decision_id = atom.get("decision_id")
            decision = decisions_by_id.get(decision_id) if isinstance(decision_id, str) else None
            authorized = decision.get("authorized_content") if isinstance(decision, dict) else None
            if (
                not isinstance(decision, dict)
                or decision.get("status") != "accepted"
                or not isinstance(authorized, list)
                or text not in authorized
            ):
                errors.append(issue("shotplan_content_atom_decision_invalid", "approved_decision atom 的文本必须逐字存在于已接受决策 authorized_content", unit_index=unit_index, atom_id=atom_id, decision_id=decision_id))
        else:
            errors.append(issue("shotplan_content_atom_invalid", "content atom origin 只能为 source 或 approved_decision", unit_index=unit_index, atom_id=atom_id))
        atoms[atom_id] = atom
    bindings = unit.get("content_bindings")
    if not isinstance(bindings, dict):
        errors.append(issue("shotplan_content_bindings_missing", "严格分镜单元必须声明 content_bindings", unit_index=unit_index))
        return errors
    for field in ("narrative_task", "action_start", "action_end"):
        atom_ids = bindings.get(field)
        compiled = compiled_content_atom_text(atom_ids, atoms) if isinstance(atom_ids, list) else None
        actual = unit.get(field)
        if compiled is None:
            errors.append(issue("shotplan_content_binding_missing", f"{field} 必须绑定有效 content atom", unit_index=unit_index, field=field))
        elif not isinstance(actual, str) or compact_dialogue_text(actual) != compact_dialogue_text(compiled):
            errors.append(issue("shotplan_unproven_content", f"{field} 必须等于绑定 content atom 的确定性编译文本", unit_index=unit_index, field=field))
    flow = unit.get("action_flow")
    steps = flow.get("steps") if isinstance(flow, dict) else None
    if isinstance(steps, list):
        for step_index, step in enumerate(steps, 1):
            if not isinstance(step, dict):
                continue
            atom_ids = step.get("content_atom_refs")
            if strict_contract and (
                not isinstance(atom_ids, list) or not atom_ids or any(atom_id not in atoms for atom_id in atom_ids)
            ):
                errors.append(issue("shotplan_action_content_binding_missing", "每个动作步骤必须绑定有效 content_atom_refs", unit_index=unit_index, step_index=step_index))
    screen_text = unit.get("screen_text")
    if isinstance(screen_text, dict) and screen_text.get("required_text"):
        atom_ids = screen_text.get("content_atom_refs")
        compiled = compiled_content_atom_text(atom_ids, atoms) if isinstance(atom_ids, list) else None
        if compiled is None:
            errors.append(issue("shotplan_screen_text_source_missing", "剧情屏显必须绑定有效 content atoms", unit_index=unit_index))
        elif compact_dialogue_text(str(screen_text.get("required_text"))) != compact_dialogue_text(compiled):
            errors.append(issue("shotplan_unproven_content", "screen_text.required_text 必须等于绑定 content atom 文本", unit_index=unit_index, field="screen_text.required_text"))
    # prompt_text 是制作字段，由已验证的动作、人物、镜头、声音和负面约束编译；
    # 不把整段生产提示词伪装成原著 content atom。其完整性由
    # validate_unit_prompt_executability 单独校验。
    return errors


def _prompt_contract_text(value: Any) -> str:
    return re.sub(r"[\s，。！？；：、‘’“”\"'（）()《》【】]+", "", str(value or ""))


def _prompt_contains(prompt_text: str, required_text: Any) -> bool:
    required = _prompt_contract_text(required_text)
    return bool(required) and required in _prompt_contract_text(prompt_text)


def validate_unit_prompt_executability(
    unit: dict[str, Any],
    cues_by_id: dict[str, dict[str, Any]],
    unit_index: int,
) -> list[dict[str, Any]]:
    """阻止只有“风格+一句动作”的模板提示词冒充可直接生成的通用提示词。"""
    prompt_text = unit.get("prompt_text")
    if prompt_text is None:
        return []
    if not isinstance(prompt_text, str) or not prompt_text.strip():
        return [issue("shotplan_prompt_text_invalid", "prompt_text 如提供必须是非空字符串", unit_index=unit_index)]

    errors: list[dict[str, Any]] = []
    action_start = unit.get("action_start")
    action_end = unit.get("action_end")
    if isinstance(action_start, str) and re.search(r"(?:本场|场)?上一状态完成|上一镜完成|承接上镜$", action_start.strip()):
        errors.append(issue("shotplan_prompt_placeholder_state", "动作起点不能使用“上一状态完成”等占位文字", unit_index=unit_index))
    elif isinstance(action_start, str) and action_start.strip() and not _prompt_contains(prompt_text, action_start):
        errors.append(issue("shotplan_prompt_action_start_missing", "prompt_text 未包含实际动作起点", unit_index=unit_index))
    if isinstance(action_end, str) and action_end.strip() and not _prompt_contains(prompt_text, action_end):
        errors.append(issue("shotplan_prompt_action_end_missing", "prompt_text 未包含动作终点", unit_index=unit_index))

    for character_index, character in enumerate(unit.get("characters_on_screen", []) or [], 1):
        if not isinstance(character, dict):
            continue
        appearance_lock = character.get("appearance_lock")
        if isinstance(appearance_lock, str) and appearance_lock.strip() and not _prompt_contains(prompt_text, appearance_lock):
            errors.append(issue("shotplan_prompt_appearance_missing", "prompt_text 未注入出场人物 appearance_lock", unit_index=unit_index, character_index=character_index, character_id=character.get("character_id")))

    sound_events = unit.get("sound_events")
    if not isinstance(sound_events, list) or not sound_events:
        errors.append(issue("shotplan_prompt_sound_missing", "通用提示词必须声明环境声、音效、对白声或明确静音", unit_index=unit_index))
    else:
        for sound_index, sound in enumerate(sound_events, 1):
            description = sound.get("description") if isinstance(sound, dict) else None
            if isinstance(description, str) and description.strip() and not _prompt_contains(prompt_text, description):
                errors.append(issue("shotplan_prompt_sound_missing", "prompt_text 未包含 sound_events 声音描述", unit_index=unit_index, sound_index=sound_index))

    movement = unit.get("shot_language", {}).get("camera_movement") if isinstance(unit.get("shot_language"), dict) else None
    movement_description = movement.get("description") if isinstance(movement, dict) else movement
    if isinstance(movement_description, str) and movement_description.strip() and not _prompt_contains(prompt_text, movement_description):
        errors.append(issue("shotplan_prompt_camera_missing", "prompt_text 未包含当前镜头运动描述", unit_index=unit_index))

    for zone_index, zone in enumerate(unit.get("space_zones", []) or [], 1):
        description = zone.get("description") if isinstance(zone, dict) else None
        if isinstance(description, str) and description.strip() and not _prompt_contains(prompt_text, description):
            errors.append(issue("shotplan_prompt_environment_missing", "prompt_text 未包含空间环境描述", unit_index=unit_index, zone_index=zone_index))

    for cue_entry in unit.get("dialogue", []) or []:
        if not isinstance(cue_entry, dict):
            continue
        cue = cues_by_id.get(cue_entry.get("cue_id"))
        if not isinstance(cue, dict):
            continue
        speaker = cue.get("speaker_name") or cue.get("speaker_id") or cue.get("character_id")
        text = cue.get("text")
        if (isinstance(speaker, str) and not _prompt_contains(prompt_text, speaker)) or (
            isinstance(text, str) and not _prompt_contains(prompt_text, text)
        ):
            errors.append(issue("shotplan_prompt_dialogue_missing", "prompt_text 未同时包含说话人和原著台词", unit_index=unit_index, cue_id=cue_entry.get("cue_id")))

    for negative_index, negative in enumerate(unit.get("negative_constraints", []) or [], 1):
        if isinstance(negative, str) and negative.strip() and not _prompt_contains(prompt_text, negative):
            errors.append(issue("shotplan_prompt_negative_missing", "prompt_text 未包含当前单元负面约束", unit_index=unit_index, negative_index=negative_index))
    return errors


def fact_definitions_by_id(event_index: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    definitions = event_index.get("fact_definitions") if isinstance(event_index, dict) else None
    if not isinstance(definitions, list):
        return {}
    return {
        item.get("fact_id"): item
        for item in definitions
        if isinstance(item, dict) and isinstance(item.get("fact_id"), str)
    }


def validate_required_fact_coverage(
    event_index: dict[str, Any] | None,
    payload: dict[str, Any],
    episode_id: str,
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    beats = source_beat_index(event_index)
    scopes = event_index.get("episode_scopes") if isinstance(event_index, dict) else None
    scope = scopes.get(episode_id) if isinstance(scopes, dict) else None
    allowed = scope.get("allowed_beat_ids") if isinstance(scope, dict) else None
    if not isinstance(allowed, list):
        return errors
    required: set[str] = set()
    for beat_id in allowed:
        beat = beats.get(beat_id)
        if isinstance(beat, dict):
            required.update(beat.get("required_fact_ids", set()))
    definitions = fact_definitions_by_id(event_index)
    covered: set[str] = set()
    for unit_index, unit in enumerate(payload.get("units", []), 1):
        if not isinstance(unit, dict):
            continue
        unit_beat_refs = set(unit.get("source_beat_refs", [])) if isinstance(unit.get("source_beat_refs"), list) else set()
        cue_ids = {
            entry.get("cue_id") for entry in unit.get("dialogue", [])
            if isinstance(entry, dict) and isinstance(entry.get("cue_id"), str)
        } if isinstance(unit.get("dialogue"), list) else set()
        flow = unit.get("action_flow")
        step_ids = {
            step.get("step_id") for step in flow.get("steps", [])
            if isinstance(step, dict) and isinstance(step.get("step_id"), str)
        } if isinstance(flow, dict) and isinstance(flow.get("steps"), list) else set()
        realizations = unit.get("fact_realizations")
        if not isinstance(realizations, list):
            if required:
                errors.append(issue("shotplan_fact_realizations_invalid", "存在必要事实时每个分镜单元 fact_realizations 必须是数组", unit_index=unit_index))
            continue
        for realization_index, realization in enumerate(realizations, 1):
            if not isinstance(realization, dict):
                errors.append(issue("shotplan_fact_realizations_invalid", "fact realization 必须是对象", unit_index=unit_index, realization_index=realization_index))
                continue
            fact_id = realization.get("fact_id")
            definition = definitions.get(fact_id) if isinstance(fact_id, str) else None
            if not isinstance(definition, dict):
                errors.append(issue("shotplan_fact_realization_unknown", "fact realization 引用了未知事实", unit_index=unit_index, fact_id=fact_id))
                continue
            source_beats = set(definition.get("source_beat_ids", [])) if isinstance(definition.get("source_beat_ids"), list) else set()
            if not source_beats.intersection(unit_beat_refs):
                errors.append(issue("shotplan_fact_beat_mismatch", "事实实现必须位于其来源 beat 对应的分镜单元", unit_index=unit_index, fact_id=fact_id))
                continue
            carrier = realization.get("carrier")
            carrier_id = realization.get("carrier_id")
            carrier_valid = (
                (carrier == "dialogue_cue" and carrier_id in cue_ids)
                or (carrier == "action_step" and carrier_id in step_ids)
                or (carrier == "screen_text" and isinstance(unit.get("screen_text"), dict) and unit["screen_text"].get("required_text"))
                or (carrier == "state_change" and isinstance(unit.get("state_chain"), dict) and isinstance(unit["state_chain"].get("exit"), dict))
            )
            if not carrier_valid:
                errors.append(issue("shotplan_fact_carrier_missing", "fact realization 声明的真实载体不存在", unit_index=unit_index, fact_id=fact_id, carrier=carrier, carrier_id=carrier_id))
                continue
            covered.add(fact_id)
    missing = sorted(required - covered)
    if missing:
        errors.append(issue("shotplan_required_fact_coverage_missing", "当前集必要事实未通过真实载体覆盖", episode_id=episode_id, missing=missing))
    return errors


def chinese_number_to_int(value: str) -> int | None:
    if value.isdigit():
        return int(value)
    digits = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if value in digits:
        return digits[value]
    if value == "十":
        return 10
    if "十" in value:
        left, right = value.split("十", 1)
        tens = digits.get(left, 1) if left else 1
        ones = digits.get(right, 0) if right else 0
        return tens * 10 + ones
    return None


def parse_relative_time_expression(expression: str) -> tuple[int, str | None] | None:
    text = re.sub(r"\\s+", "", expression)
    day_part_map = {"凌晨": "dawn", "早晨": "morning", "上午": "morning", "中午": "noon", "下午": "afternoon", "傍晚": "evening", "晚上": "night", "夜里": "night", "深夜": "late_night"}
    day_part = next((mapped for label, mapped in day_part_map.items() if label in text), None)
    if text.startswith(("同日", "当天")):
        return 0, day_part
    if text.startswith(("次日", "翌日", "第二天")):
        return 1, day_part
    if text.startswith("后天"):
        return 2, day_part
    match = re.match(r"([零一二两三四五六七八九十\\d]+)天后", text)
    if match:
        value = chinese_number_to_int(match.group(1))
        return (value, day_part) if value is not None else None
    return None


def validate_source_timeline_contract(
    event_index: dict[str, Any] | None,
    source_text_by_id: dict[str, str],
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    beats = source_beat_index(event_index)
    constraints = event_index.get("temporal_constraints", []) if isinstance(event_index, dict) else []
    if not isinstance(constraints, list):
        return [issue("event_temporal_constraints_invalid", "temporal_constraints 必须是数组")]
    seen: set[str] = set()
    for index, constraint in enumerate(constraints, 1):
        if not isinstance(constraint, dict):
            errors.append(issue("event_temporal_constraint_invalid", "时间约束必须是对象", constraint_index=index))
            continue
        constraint_id = constraint.get("constraint_id")
        if not isinstance(constraint_id, str) or not constraint_id.strip() or constraint_id in seen:
            errors.append(issue("event_temporal_constraint_id_invalid", "时间约束 ID 缺失或重复", constraint_index=index))
        else:
            seen.add(constraint_id)
        anchor_id = constraint.get("anchor_beat_id")
        target_id = constraint.get("target_beat_id")
        anchor = beats.get(anchor_id) if isinstance(anchor_id, str) else None
        target = beats.get(target_id) if isinstance(target_id, str) else None
        if not isinstance(anchor, dict) or not isinstance(target, dict):
            errors.append(issue("event_temporal_beat_unknown", "时间约束 anchor/target beat 不存在", constraint_index=index))
            continue
        expression = constraint.get("expression_text")
        source_unit_id = constraint.get("source_unit_id")
        source_text = source_text_by_id.get(source_unit_id) if isinstance(source_unit_id, str) else None
        if not isinstance(expression, str) or not expression.strip() or not isinstance(source_text, str) or compact_dialogue_text(expression) not in compact_dialogue_text(source_text):
            errors.append(issue("event_temporal_expression_not_in_source", "时间表达必须逐字存在于绑定原著单元", constraint_index=index))
            continue
        parsed = parse_relative_time_expression(expression)
        if parsed is None:
            errors.append(issue("event_temporal_expression_unsupported", "精确时间约束包含不支持的模糊表达", constraint_index=index, expression=expression))
            continue
        anchor_time = anchor.get("story_time")
        target_time = target.get("story_time")
        if not isinstance(anchor_time, dict) or not isinstance(target_time, dict) or type(anchor_time.get("day_index")) is not int or type(target_time.get("day_index")) is not int:
            errors.append(issue("event_story_time_missing", "时间约束涉及的 beat 必须声明整数 day_index", constraint_index=index))
            continue
        offset, expected_part = parsed
        if target_time["day_index"] - anchor_time["day_index"] != offset:
            errors.append(issue("event_temporal_offset_mismatch", "相对时间表达与目标事件 day_index 不一致", constraint_index=index, expected_offset=offset, actual_offset=target_time["day_index"] - anchor_time["day_index"]))
        if offset > 0 and target["order"] <= anchor["order"]:
            errors.append(issue("event_temporal_target_order_invalid", "未来时间表达的目标 beat 必须晚于 anchor beat", constraint_index=index))
        if expected_part is not None and target_time.get("day_part") != expected_part:
            errors.append(issue("event_temporal_day_part_mismatch", "时间表达的目标时段与 target beat 不一致", constraint_index=index, expected=expected_part, actual=target_time.get("day_part")))
    return errors


def validate_shot_plan_timeline_contract(
    event_index: dict[str, Any] | None,
    payload: dict[str, Any],
    cues_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    beats = source_beat_index(event_index)
    constraints = event_index.get("temporal_constraints", []) if isinstance(event_index, dict) else []
    constrained_beats = {
        value
        for constraint in constraints if isinstance(constraint, dict)
        for value in (constraint.get("anchor_beat_id"), constraint.get("target_beat_id"))
        if isinstance(value, str)
    } if isinstance(constraints, list) else set()
    previous_day: int | None = None
    relative_claim_re = re.compile(r"(?:同日|当天|次日|翌日|第二天|后天|[零一二两三四五六七八九十\\d]+天后)(?:凌晨|早晨|上午|中午|下午|傍晚|晚上|夜里|深夜)?")
    for unit_index, unit in enumerate(payload.get("units", []), 1):
        if not isinstance(unit, dict):
            continue
        refs = unit.get("source_beat_refs") if isinstance(unit.get("source_beat_refs"), list) else []
        times = [beats[ref].get("story_time") for ref in refs if ref in beats and isinstance(beats[ref].get("story_time"), dict)]
        days = [time.get("day_index") for time in times if type(time.get("day_index")) is int]
        mode = unit.get("time_span_mode")
        if mode == "continuous" and len(set(days)) > 1:
            errors.append(issue("shotplan_continuous_time_jump", "continuous 分镜单元不能同时引用不同故事日期的 beat", unit_index=unit_index, day_indices=sorted(set(days))))
        if days:
            current_day = min(days)
            if previous_day is not None and current_day < previous_day and mode != "flashback":
                errors.append(issue("shotplan_story_time_reversed", "非 flashback 分镜不能让故事日期倒退", unit_index=unit_index, previous_day=previous_day, current_day=current_day))
            previous_day = max(days)
        text_fields = [unit.get("narrative_task"), unit.get("action_start"), unit.get("action_end")]
        screen_text = unit.get("screen_text")
        if isinstance(screen_text, dict):
            text_fields.append(screen_text.get("required_text"))
        for entry in unit.get("dialogue", []) if isinstance(unit.get("dialogue"), list) else []:
            if isinstance(entry, dict):
                cue = cues_by_id.get(entry.get("cue_id"))
                if isinstance(cue, dict):
                    text_fields.append(cue.get("text"))
        if any(isinstance(text, str) and relative_claim_re.search(text) for text in text_fields):
            if not set(refs).intersection(constrained_beats):
                errors.append(issue("shotplan_temporal_claim_unbound", "分镜中的明确相对时间表达必须绑定原著 temporal_constraint", unit_index=unit_index))
    return errors


def validate_shot_plan_source_contract(
    event_index: dict[str, Any] | None,
    story_facts: dict[str, Any] | None,
    payload: dict[str, Any],
    episode_id: str,
) -> list[dict[str, Any]]:
    """Validate source ordering, episode boundary and fact coverage from structured data."""
    errors: list[dict[str, Any]] = []
    event_schema = event_index.get("schema_version", 1) if isinstance(event_index, dict) else 1
    plan_schema = payload.get("schema_version", 1)
    strict_contract = (
        isinstance(event_schema, int) and not isinstance(event_schema, bool) and event_schema >= 2
    ) or (
        isinstance(plan_schema, int) and not isinstance(plan_schema, bool) and plan_schema >= 2
    )
    if not strict_contract:
        return errors
    beats = source_beat_index(event_index)
    if not beats:
        errors.append(issue("shotplan_source_beat_index_missing", "AI分镜计划必须绑定带 beats 的原著事件索引"))
        return errors
    scopes = event_index.get("episode_scopes") if isinstance(event_index, dict) else None
    scope = scopes.get(episode_id) if isinstance(scopes, dict) else None
    if not isinstance(scope, dict):
        errors.append(issue("shotplan_source_scope_missing", "原著事件索引必须声明当前集 episode_scope", episode_id=episode_id))
        return errors
    allowed_ids = scope.get("allowed_beat_ids")
    if (
        not isinstance(allowed_ids, list)
        or not allowed_ids
        or len(allowed_ids) != len(set(allowed_ids))
        or not all(isinstance(value, str) and value in beats for value in allowed_ids)
    ):
        errors.append(issue("shotplan_source_scope_invalid", "episode_scope 必须声明无重复且全部存在的 allowed_beat_ids", episode_id=episode_id))
        return errors
    allowed_orders = [beats[value]["order"] for value in allowed_ids]
    if allowed_orders != sorted(allowed_orders):
        errors.append(issue("shotplan_source_scope_reversed", "allowed_beat_ids 必须严格遵循原著顺序", episode_id=episode_id))
        return errors
    first_id = scope.get("first_beat_id")
    last_id = scope.get("last_beat_id")
    if first_id != allowed_ids[0] or last_id != allowed_ids[-1]:
        errors.append(issue("shotplan_source_scope_invalid", "episode_scope 首尾 beat 必须与 allowed_beat_ids 首尾一致", episode_id=episode_id))
        return errors
    lower, upper = allowed_orders[0], allowed_orders[-1]
    allowed_set = set(allowed_ids)
    facts = story_facts.get("facts") if isinstance(story_facts, dict) else None
    known_fact_ids = {
        item.get("fact_id")
        for item in facts
        if isinstance(item, dict) and isinstance(item.get("fact_id"), str)
    } if isinstance(facts, list) else set()
    previous_order = lower
    for index, unit in enumerate(payload.get("units", []), 1):
        if not isinstance(unit, dict):
            continue
        refs = unit.get("source_beat_refs")
        if not isinstance(refs, list) or not refs or not all(isinstance(value, str) for value in refs):
            errors.append(issue("shotplan_source_beats_missing", "每个分镜单元必须引用 source_beat_refs", unit_index=index))
            continue
        unknown = sorted(set(refs) - set(beats))
        if unknown:
            errors.append(issue("shotplan_source_beat_unknown", "分镜引用了不存在的来源 beat", unit_index=index, unknown=unknown))
            continue
        orders = [beats[value]["order"] for value in refs]
        outside = sorted(set(refs) - allowed_set)
        if outside:
            errors.append(issue("shotplan_source_boundary_exceeded", "分镜引用超出当前集明确允许的原著 beat", unit_index=index, outside=outside))
        if min(orders) < previous_order:
            errors.append(issue("shotplan_source_order_violation", "分镜来源顺序发生倒退或调序", unit_index=index))
        previous_order = max(previous_order, max(orders))
        required_facts: set[str] = set()
        for ref in refs:
            required_facts.update(beats[ref]["protected_fact_ids"])
        preserved = unit.get("preserved_fact_ids")
        preserved_set = set(preserved) if isinstance(preserved, list) and all(isinstance(v, str) for v in preserved) else set()
        if required_facts - preserved_set:
            errors.append(issue("shotplan_protected_fact_missing", "分镜未覆盖来源 beat 的受保护事实", unit_index=index, missing=sorted(required_facts - preserved_set)))
        if known_fact_ids and preserved_set - known_fact_ids:
            errors.append(issue("shotplan_protected_fact_unknown", "分镜引用了未知事实 ID", unit_index=index, unknown=sorted(preserved_set - known_fact_ids)))
        new_claims = unit.get("new_fact_claims", [])
        if not isinstance(new_claims, list):
            errors.append(issue("shotplan_new_fact_claims_invalid", "new_fact_claims 必须是数组", unit_index=index))
        elif new_claims and not unit.get("decision_ids"):
            errors.append(issue("shotplan_unauthorized_fact_added", "新增事实必须绑定已批准改编决策", unit_index=index))
    return errors


def source_character_ids(event_index: dict[str, Any] | None) -> set[str]:
    entities = event_index.get("entities") if isinstance(event_index, dict) else None
    if not isinstance(entities, list):
        return set()
    return {
        entity.get("entity_id")
        for entity in entities
        if isinstance(entity, dict)
        and entity.get("entity_type") == "character"
        and isinstance(entity.get("entity_id"), str)
    }


def validate_unit_character_registry(
    unit: dict[str, Any], canonical_character_ids: set[str], unit_index: int
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    referenced: set[str] = set()
    characters = unit.get("characters_on_screen")
    if isinstance(characters, list):
        referenced.update(
            item.get("character_id")
            for item in characters
            if isinstance(item, dict) and isinstance(item.get("character_id"), str)
        )
    screen_video = unit.get("screen_video_characters")
    if isinstance(screen_video, list):
        referenced.update(value for value in screen_video if isinstance(value, str))
    state_chain = unit.get("state_chain")
    if isinstance(state_chain, dict):
        for state_name in ("enter", "exit"):
            state = state_chain.get(state_name)
            characters_state = state.get("characters") if isinstance(state, dict) else None
            if isinstance(characters_state, dict):
                referenced.update(value for value in characters_state if isinstance(value, str))
    unknown = sorted(referenced - canonical_character_ids)
    if unknown:
        errors.append(
            issue(
                "shotplan_character_unknown",
                "分镜人物必须引用原著事件索引的 canonical character ID",
                unit_index=unit_index,
                unknown=unknown,
            )
        )
    return errors


def validate_unit_character_modes(
    unit: dict[str, Any], cues_by_id: dict[str, dict[str, Any]], unit_index: int
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    characters = unit.get("characters_on_screen")
    on_screen_ids = {
        item.get("character_id")
        for item in characters
        if isinstance(item, dict) and isinstance(item.get("character_id"), str)
    } if isinstance(characters, list) else set()
    screen_video = unit.get("screen_video_characters", [])
    screen_video_ids = set(screen_video) if isinstance(screen_video, list) else set()
    nonvisual_modes = {"os", "vo", "off_screen", "voice_over", "phone_audio", "screen_video", "phone_video"}
    for entry in unit.get("dialogue", []) if isinstance(unit.get("dialogue"), list) else []:
        if not isinstance(entry, dict):
            continue
        cue = cues_by_id.get(entry.get("cue_id"), {})
        speaker = cue.get("speaker_id") or cue.get("character_id")
        mode = cue.get("delivery_mode") or cue.get("type")
        if isinstance(speaker, str) and mode in nonvisual_modes and speaker in on_screen_ids:
            errors.append(issue("shotplan_nonvisual_character_on_screen", "非现场、电话或视频人物不得进入 characters_on_screen", unit_index=unit_index, character_id=speaker, delivery_mode=mode))
        if isinstance(speaker, str) and mode in {"screen_video", "phone_video"} and speaker not in screen_video_ids:
            errors.append(issue("shotplan_screen_video_character_missing", "视频人物必须进入 screen_video_characters", unit_index=unit_index, character_id=speaker))
    enter = unit.get("state_chain", {}).get("enter", {}) if isinstance(unit.get("state_chain"), dict) else {}
    state_chars = enter.get("characters") if isinstance(enter, dict) else None
    if isinstance(state_chars, dict):
        absent_re = re.compile(r"未到场|尚未到场|已离开|不在场|未出现")
        for character_id in on_screen_ids:
            state = state_chars.get(character_id)
            position = state.get("position") if isinstance(state, dict) else None
            if isinstance(position, str) and absent_re.search(position):
                errors.append(issue("shotplan_character_presence_conflict", "人物进入状态表明不在场，却被列为现场出镜", unit_index=unit_index, character_id=character_id, position=position))
    return errors


def validate_tail_frame_contract(
    units: list[Any],
    state: dict[str, Any],
    episode_id: str,
    project_path: Path | None = None,
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    episode_match = re.fullmatch(r"E(\d{3,6})", episode_id or "", re.IGNORECASE)
    previous_unit_id: str | None = None
    for index, unit in enumerate(units, 1):
        if not isinstance(unit, dict):
            continue
        strategy = unit.get("generation_strategy")
        unit_id = unit.get("unit_id")
        if strategy == "tail_frame_chain":
            if index > 1:
                if unit.get("continuation_from_unit_id") != previous_unit_id:
                    errors.append(issue("shotplan_tail_previous_unit_missing", "同集 tail_frame_chain 必须明确绑定紧邻上一分镜单元", unit_index=index, expected=previous_unit_id))
            else:
                ref = unit.get("previous_episode_tail_ref")
                if not isinstance(ref, dict):
                    errors.append(issue("shotplan_cross_episode_tail_missing", "跨集首镜使用 tail_frame_chain 时必须绑定上一集已确认尾镜", unit_index=index))
                elif episode_match is None or int(episode_match.group(1)) <= 1:
                    errors.append(issue("shotplan_cross_episode_tail_invalid", "第一集首镜不能使用上一集尾帧续接", unit_index=index))
                else:
                    previous_episode = f"E{int(episode_match.group(1)) - 1:03d}"
                    expected_key = f"ai_shot_plan:{previous_episode}"
                    key = ref.get("artifact_key")
                    version = ref.get("version")
                    tail_unit_id = ref.get("unit_id")
                    if key != expected_key or type(version) is not int or not isinstance(tail_unit_id, str):
                        errors.append(issue("shotplan_cross_episode_tail_invalid", "上一集尾帧引用必须包含正确 artifact_key/version/unit_id", unit_index=index, expected_key=expected_key))
                    else:
                        target = next(
                            (
                                record
                                for record in state.get("artifacts", {}).get(key, [])
                                if isinstance(record, dict) and record.get("version") == version
                            ),
                            None,
                        )
                        if target is None or target.get("status") != "confirmed":
                            errors.append(issue("shotplan_cross_episode_tail_unconfirmed", "上一集尾帧引用必须指向已确认分镜计划", unit_index=index, artifact_key=key, version=version))
                        elif project_path is not None:
                            target_path = path_from_record(project_path, target.get("path"))
                            target_payload = read_json(target_path) if target_path and target_path.is_file() else None
                            target_units = target_payload.get("units") if isinstance(target_payload, dict) else None
                            last_unit_id = target_units[-1].get("unit_id") if isinstance(target_units, list) and target_units and isinstance(target_units[-1], dict) else None
                            if tail_unit_id != last_unit_id:
                                errors.append(issue("shotplan_cross_episode_tail_not_last", "跨集续接必须引用上一集最后一个分镜单元", unit_index=index, expected=last_unit_id, actual=tail_unit_id))
        previous_unit_id = unit_id if isinstance(unit_id, str) else None
    return errors


def validate_unit_spatial_audio_contract(
    unit: dict[str, Any],
    cues_by_id: dict[str, dict[str, Any]],
    unit_index: int,
    strict_contract: bool = False,
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    zones = unit.get("space_zones")
    if not strict_contract and zones is None and unit.get("sound_events") is None:
        return errors
    zone_ids: set[str] = set()
    if not isinstance(zones, list) or not zones:
        errors.append(issue("shotplan_space_zones_missing", "分镜单元必须声明非空 space_zones", unit_index=unit_index))
    else:
        for zone_index, zone in enumerate(zones, 1):
            if not isinstance(zone, dict):
                errors.append(issue("shotplan_space_zone_invalid", "space_zones 条目必须是对象", unit_index=unit_index, zone_index=zone_index))
                continue
            space_id = zone.get("space_id")
            if not isinstance(space_id, str) or not space_id.strip() or space_id in zone_ids:
                errors.append(issue("shotplan_space_zone_id_invalid", "space_id 缺失或重复", unit_index=unit_index, zone_index=zone_index))
            else:
                zone_ids.add(space_id)
            if zone.get("kind") not in {"room", "exterior", "vehicle", "device_screen", "memory", "virtual"}:
                errors.append(issue("shotplan_space_zone_kind_invalid", "space zone kind 无效", unit_index=unit_index, zone_index=zone_index))
    characters = unit.get("characters_on_screen")
    if isinstance(characters, list):
        for character_index, character in enumerate(characters, 1):
            if not isinstance(character, dict):
                continue
            space_id = character.get("space_id")
            if not isinstance(space_id, str) or space_id not in zone_ids:
                errors.append(issue("shotplan_character_space_missing", "现场人物必须绑定当前单元的有效 space_id", unit_index=unit_index, character_index=character_index, character_id=character.get("character_id")))
    sound_events = unit.get("sound_events")
    if not isinstance(sound_events, list):
        errors.append(issue("shotplan_sound_events_invalid", "sound_events 必须是数组（无声音用空数组）", unit_index=unit_index))
        sound_events = []
    sound_by_id: dict[str, dict[str, Any]] = {}
    for sound_index, sound in enumerate(sound_events, 1):
        if not isinstance(sound, dict):
            errors.append(issue("shotplan_sound_event_invalid", "sound_events 条目必须是对象", unit_index=unit_index, sound_index=sound_index))
            continue
        sound_id = sound.get("sound_id")
        if not isinstance(sound_id, str) or not sound_id.strip() or sound_id in sound_by_id:
            errors.append(issue("shotplan_sound_event_id_invalid", "sound_id 缺失或重复", unit_index=unit_index, sound_index=sound_index))
            continue
        sound_by_id[sound_id] = sound
        if not isinstance(sound.get("description"), str) or not sound["description"].strip():
            errors.append(issue("shotplan_sound_description_missing", "声音事件缺少 description", unit_index=unit_index, sound_index=sound_index))
        source_type = sound.get("source_type")
        if source_type not in {"ambient", "sfx", "device", "voice"}:
            errors.append(issue("shotplan_sound_source_type_invalid", "sound source_type 无效", unit_index=unit_index, sound_index=sound_index))
        if sound.get("space_id") not in zone_ids:
            errors.append(issue("shotplan_sound_space_invalid", "声音事件必须绑定当前单元的有效 space_id", unit_index=unit_index, sound_index=sound_index))
        if sound.get("scope") != "unit":
            code = "shotplan_device_audio_scope_invalid" if source_type == "device" else "shotplan_sound_scope_invalid"
            errors.append(issue(code, "声音生命周期必须限制在当前分镜单元，跨单元需逐单元显式续写", unit_index=unit_index, sound_index=sound_index))
        if source_type == "device" and (
            not isinstance(sound.get("device_id"), str) or not sound["device_id"].strip()
        ):
            errors.append(issue("shotplan_device_audio_source_missing", "设备声音必须声明 device_id", unit_index=unit_index, sound_index=sound_index))
    dialogue = unit.get("dialogue")
    if isinstance(dialogue, list):
        for cue_entry in dialogue:
            if not isinstance(cue_entry, dict):
                continue
            cue_id = cue_entry.get("cue_id")
            cue = cues_by_id.get(cue_id) if isinstance(cue_id, str) else None
            if not isinstance(cue, dict) or cue.get("delivery_mode") not in {"phone_audio", "phone_video", "screen_video"}:
                continue
            audio_event_id = cue_entry.get("audio_event_id")
            sound = sound_by_id.get(audio_event_id) if isinstance(audio_event_id, str) else None
            if not isinstance(sound, dict) or sound.get("source_type") != "device" or sound.get("scope") != "unit":
                errors.append(issue("shotplan_device_audio_binding_missing", "电话或屏幕视频台词必须绑定当前单元的 device sound_event", unit_index=unit_index, cue_id=cue_id))
    if strict_contract and "sound" in unit:
        errors.append(issue("shotplan_legacy_sound_forbidden", "严格分镜契约禁止使用无空间和生命周期的 sound 字符串数组", unit_index=unit_index))
    return errors


def validate_unit_feasibility(
    unit: dict[str, Any],
    cues_by_id: dict[str, dict[str, Any]],
    rate: tuple[float, float],
    unit_index: int,
    strict_contract: bool = True,
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    duration = unit.get("duration_seconds")
    spoken_chars = 0
    for entry in unit.get("dialogue", []) if isinstance(unit.get("dialogue"), list) else []:
        cue = cues_by_id.get(entry.get("cue_id"), {}) if isinstance(entry, dict) else {}
        text = cue.get("text")
        if isinstance(text, str):
            spoken_chars += len(re.sub(r"\s+", "", text))
    if isinstance(duration, (int, float)) and duration > 0 and spoken_chars > duration * rate[1]:
        errors.append(issue("shotplan_dialogue_capacity_exceeded", "按最快语速计算，对白仍超过当前镜头时长", unit_index=unit_index, spoken_chars=spoken_chars, duration=duration))
    flow = unit.get("action_flow")
    if not isinstance(flow, dict):
        if strict_contract:
            errors.append(issue("shotplan_action_flow_missing", "分镜单元必须提供结构化 action_flow", unit_index=unit_index))
    else:
        enter_states = flow.get("enter_states")
        steps = flow.get("steps")
        exit_states = flow.get("exit_states")
        if not isinstance(enter_states, list) or not all(isinstance(v, str) for v in enter_states):
            errors.append(issue("shotplan_action_enter_states_invalid", "action_flow.enter_states 必须是字符串数组", unit_index=unit_index))
            enter_states = []
        if not isinstance(steps, list) or not steps:
            errors.append(issue("shotplan_action_steps_missing", "action_flow.steps 必须是非空数组", unit_index=unit_index))
            steps = []
        available = set(enter_states)
        used_step_ids: set[str] = set()
        minimum_duration = 0.0
        for step_index, step in enumerate(steps, 1):
            if not isinstance(step, dict):
                errors.append(issue("shotplan_action_step_invalid", "动作步骤必须是对象", unit_index=unit_index, step_index=step_index))
                continue
            step_id = step.get("step_id")
            if not isinstance(step_id, str) or not step_id or step_id in used_step_ids:
                errors.append(issue("shotplan_action_step_id_invalid", "动作步骤 ID 缺失或重复", unit_index=unit_index, step_index=step_index))
            else:
                used_step_ids.add(step_id)
            requires = step.get("requires", [])
            produces = step.get("produces", [])
            if not isinstance(requires, list) or not all(isinstance(v, str) for v in requires):
                errors.append(issue("shotplan_action_requires_invalid", "动作 requires 必须是字符串数组", unit_index=unit_index, step_index=step_index))
                requires = []
            if set(requires) - available:
                errors.append(issue("shotplan_action_precondition_missing", "动作前置状态未满足", unit_index=unit_index, step_index=step_index, missing=sorted(set(requires) - available)))
            if not isinstance(produces, list) or not all(isinstance(v, str) for v in produces):
                errors.append(issue("shotplan_action_produces_invalid", "动作 produces 必须是字符串数组", unit_index=unit_index, step_index=step_index))
                produces = []
            available.update(produces)
            value = step.get("min_duration_seconds", 0)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
                minimum_duration += value
            else:
                errors.append(issue("shotplan_action_min_duration_invalid", "动作最短时长必须是非负数", unit_index=unit_index, step_index=step_index))
        if isinstance(exit_states, list) and all(isinstance(v, str) for v in exit_states):
            if set(exit_states) - available:
                errors.append(issue("shotplan_action_exit_state_unreached", "动作链未产生声明的离开状态", unit_index=unit_index))
        else:
            errors.append(issue("shotplan_action_exit_states_invalid", "action_flow.exit_states 必须是字符串数组", unit_index=unit_index))
        if isinstance(duration, (int, float)) and minimum_duration > duration:
            errors.append(issue("shotplan_action_capacity_exceeded", "动作步骤最短时长合计超过镜头时长", unit_index=unit_index, minimum=minimum_duration, duration=duration))
    time_span_mode = unit.get("time_span_mode")
    if (strict_contract or time_span_mode is not None) and time_span_mode not in {
        "continuous", "ellipsis", "montage", "flashback"
    }:
        errors.append(issue("shotplan_time_span_mode_invalid", "time_span_mode 必须为 continuous、ellipsis、montage 或 flashback", unit_index=unit_index))
    screen_text = unit.get("screen_text")
    if screen_text is not None:
        if not isinstance(screen_text, dict):
            errors.append(issue("shotplan_screen_text_invalid", "screen_text 必须是对象或 null", unit_index=unit_index))
        elif screen_text.get("required_text") and (
            screen_text.get("render_mode") != "post_production_overlay"
            or not isinstance(screen_text.get("overlay_asset_id"), str)
            or not screen_text["overlay_asset_id"].strip()
        ):
            errors.append(issue("shotplan_screen_text_overlay_missing", "剧情必要屏幕文字必须提供后期叠加资产", unit_index=unit_index))
    return errors


def computed_boundary_conclusion(target_errors: list[dict[str, Any]], findings: list[Any]) -> str:
    if target_errors or any(isinstance(item, dict) and item.get("result") == "blocked" for item in findings):
        return "blocked"
    if any(isinstance(item, dict) and item.get("result") == "suspected_overreach" for item in findings):
        return "needs_human_review"
    return "passed"


def validate_ai_shot_plan_payload(
    project_path: Path,
    state: dict[str, Any],
    artifact_key: str,
    record: dict[str, Any],
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    """校验模型无关的 AI 分镜单元计划：节奏、外形锁、台词覆盖、状态链与锚点版本。"""
    errors: list[dict[str, Any]] = []
    scope = artifact_key.split(":", 1)[1] if ":" in artifact_key else ""
    if not re.fullmatch(r"E\d{3,6}", scope, re.IGNORECASE):
        errors.append(issue("shotplan_key_scope_invalid", "AI分镜计划 key 必须使用 ai_shot_plan:E001 形式"))
    episode_id = payload.get("episode_id")
    if not isinstance(episode_id, str) or episode_id.upper() != scope.upper():
        errors.append(issue("shotplan_episode_mismatch", "AI分镜计划 episode_id 与制品 key 不一致"))
    embedded_text = json.dumps(payload, ensure_ascii=False)
    if re.search(r"data:(?:image|video|audio)/|\bb64_json\b|\bbase64\b", embedded_text, re.IGNORECASE):
        errors.append(issue("shotplan_embedded_binary_forbidden", "AI分镜计划禁止嵌入 Base64 或 data URI 媒体数据"))

    hard_blocks = payload.get("hard_blocks")
    if not isinstance(hard_blocks, list) or not hard_blocks or not all(
        isinstance(value, str) and value.strip() for value in hard_blocks
    ):
        errors.append(issue("shotplan_hard_blocks_missing", "必须提供本集 hard_blocks（禁止画面/提前泄密/越权认证清单）"))

    budget = payload.get("asset_budget")
    if not isinstance(budget, dict):
        errors.append(issue("shotplan_asset_budget_missing", "必须声明 asset_budget（从改编圣经复制的资产预算）"))
        budget = {}

    event_index = dependency_payload_of_type(project_path, state, record, "source_event_index")
    canonical_character_ids = source_character_ids(event_index)
    valid_source_refs = source_reference_ids(event_index)
    ledger = dependency_payload_of_type(project_path, state, record, "adaptation_decision_ledger")
    decisions = ledger.get("decisions") if isinstance(ledger, dict) else None
    valid_decision_ids = {
        item.get("decision_id")
        for item in decisions
        if isinstance(item, dict) and isinstance(item.get("decision_id"), str)
    } if isinstance(decisions, list) else set()
    decisions_by_id = {
        item.get("decision_id"): item
        for item in decisions
        if isinstance(item, dict) and isinstance(item.get("decision_id"), str)
    } if isinstance(decisions, list) else {}

    script_dependency = dependency_record_of_type(state, record, "episode_script")
    script_scenes: dict[str, dict[str, Any]] = {}
    if script_dependency is None:
        errors.append(issue("shotplan_script_dependency_invalid", "AI分镜计划必须精确绑定一份分集剧本"))
    else:
        script_key, script_record = script_dependency
        script_path = path_from_record(project_path, script_record.get("path"))
        try:
            script_scenes, _ = extract_script_index(script_path, script_key) if script_path else ({}, [])
        except (OSError, UnicodeError):
            script_scenes = {}
        if not script_scenes:
            errors.append(issue("shotplan_script_unreadable", "无法从绑定剧本提取场次"))

    cue_sheet = dependency_payload_of_type(project_path, state, record, "dialogue_cue_sheet")
    cue_records = cue_sheet.get("records") if isinstance(cue_sheet, dict) else None
    cues_by_id: dict[str, dict[str, Any]] = {}
    expected_cue_ids: set[str] = set()
    if isinstance(cue_records, list):
        for cue in cue_records:
            if not isinstance(cue, dict):
                continue
            cue_id = cue.get("cue_id")
            if not isinstance(cue_id, str) or not cue_id.strip():
                continue
            cues_by_id[cue_id] = cue
            if cue.get("episode_id") == episode_id and cue.get("type") in {"dialogue", "vo", "os"}:
                expected_cue_ids.add(cue_id)
    else:
        errors.append(issue("shotplan_cue_sheet_unreadable", "无法读取绑定的台词声音表"))

    units = payload.get("units")
    if not isinstance(units, list) or not units:
        errors.append(issue("shotplan_units_invalid", "units 必须是非空数组"))
        return errors

    story_facts = dependency_payload_of_type(project_path, state, record, "story_facts")
    errors.extend(validate_shot_plan_source_contract(event_index, story_facts, payload, str(episode_id or scope)))
    event_schema = event_index.get("schema_version", 1) if isinstance(event_index, dict) else 1
    plan_schema = payload.get("schema_version", 1)
    strict_contract = (
        isinstance(event_schema, int) and not isinstance(event_schema, bool) and event_schema >= 2
    ) or (
        isinstance(plan_schema, int) and not isinstance(plan_schema, bool) and plan_schema >= 2
    )
    if strict_contract and payload.get("content_contract_version") != 1:
        errors.append(issue("shotplan_content_contract_upgrade_required", "严格分镜计划必须使用 content_contract_version=1"))
    errors.extend(validate_required_fact_coverage(event_index, payload, str(episode_id or scope)))
    errors.extend(validate_shot_plan_timeline_contract(event_index, payload, cues_by_id))
    beats = source_beat_index(event_index)
    unit_rate = dialogue_chars_per_second(project_duration_policy(project_path, state))

    seen_unit_ids: set[str] = set()
    used_cue_ids: list[str] = []
    used_scene_anchor_keys: set[str] = set()
    used_character_ids: set[str] = set()
    total_unit_duration = 0.0
    previous_chain: str | None = None
    previous_exit: Any = None
    for index, unit in enumerate(units, 1):
        if not isinstance(unit, dict):
            errors.append(issue("shotplan_unit_invalid", "分镜单元必须是对象", unit_index=index))
            continue
        unit_id = unit.get("unit_id")
        if not isinstance(unit_id, str) or not re.fullmatch(
            rf"SP-{re.escape(episode_id or scope)}-U\d{{3}}", unit_id, re.IGNORECASE
        ):
            errors.append(issue("shotplan_unit_id_invalid", "unit_id 必须使用 SP-E001-U001 形式", unit_index=index))
        elif unit_id in seen_unit_ids:
            errors.append(issue("shotplan_unit_id_duplicate", f"分镜单元 ID 重复：{unit_id}"))
        else:
            seen_unit_ids.add(unit_id)
        if unit.get("sequence") != index:
            errors.append(issue("shotplan_unit_sequence_invalid", "sequence 必须从1连续递增", unit_index=index))
        scene_id = unit.get("scene_id")
        if not isinstance(scene_id, str) or (script_scenes and scene_id not in script_scenes):
            errors.append(issue("shotplan_scene_unknown", "分镜单元引用了绑定剧本中不存在的 scene_id", unit_index=index, scene_id=scene_id))
        for field in ("narrative_task", "action_start", "action_end"):
            if not isinstance(unit.get(field), str) or not unit[field].strip():
                errors.append(issue("shotplan_unit_field_missing", f"分镜单元缺少 {field}", unit_index=index, field=field))
        shot_language = unit.get("shot_language")
        if not isinstance(shot_language, dict):
            errors.append(issue("shotplan_shot_language_missing", "分镜单元必须声明 shot_language", unit_index=index))
            shot_language = {}
        shot_contract_version = payload.get("shot_language_contract_version", 1)
        if shot_contract_version not in {1, 2}:
            errors.append(issue("shotplan_shot_contract_version_invalid", "shot_language_contract_version 必须为1或2"))
            shot_contract_version = 1
        for field in ("camera_angle", "composition", "visual_focus", "transition"):
            if not isinstance(shot_language.get(field), str) or not shot_language[field].strip():
                errors.append(issue("shotplan_shot_language_field_missing", f"shot_language 缺少 {field}", unit_index=index, field=field))
        errors.extend(
            shot_contracts.validate_shot_framing_contract(
                unit, index, strict=shot_contract_version == 2
            )
        )
        duration = unit.get("duration_seconds")
        if not isinstance(duration, (int, float)) or isinstance(duration, bool) or duration <= 0 or duration > 60:
            errors.append(issue("shotplan_unit_duration_invalid", "duration_seconds 必须是0到60秒之间的数值", unit_index=index))
        elif duration > 4 and (
            not isinstance(unit.get("over_4s_rationale"), str) or not unit["over_4s_rationale"].strip()
        ):
            errors.append(issue("shotplan_over_4s_rationale_missing", "超过4秒的视觉单元必须写明持续信息变化理由 over_4s_rationale", unit_index=index))
        if isinstance(duration, (int, float)) and not isinstance(duration, bool) and 0 < duration <= 60:
            total_unit_duration += duration
        unit_source_refs = unit.get("source_refs")
        if not isinstance(unit_source_refs, list) or not unit_source_refs or not all(
            isinstance(value, str) and value.strip() for value in unit_source_refs
        ):
            errors.append(issue("shotplan_unit_source_refs_invalid", "每个分镜单元必须提供非空 source_refs", unit_index=index))
        elif valid_source_refs and set(unit_source_refs) - valid_source_refs:
            errors.append(issue("shotplan_unit_source_ref_unknown", "分镜单元引用了事件索引中不存在的原著依据", unit_index=index, unknown=sorted(set(unit_source_refs) - valid_source_refs)))
        decision_ids = unit.get("decision_ids", [])
        if not isinstance(decision_ids, list) or not all(
            isinstance(value, str) and value.strip() for value in decision_ids
        ):
            errors.append(issue("shotplan_unit_decision_ids_invalid", "decision_ids 必须是字符串数组", unit_index=index))
        elif valid_decision_ids and set(decision_ids) - valid_decision_ids:
            errors.append(issue("shotplan_unit_decision_unknown", "分镜单元引用了未知改编决策", unit_index=index, unknown=sorted(set(decision_ids) - valid_decision_ids)))

        characters = unit.get("characters_on_screen")
        if not isinstance(characters, list):
            errors.append(issue("shotplan_characters_invalid", "characters_on_screen 必须是数组（空场景用空数组）", unit_index=index))
            characters = []
        for char_index, character in enumerate(characters, 1):
            if not isinstance(character, dict):
                errors.append(issue("shotplan_character_invalid", "出场角色记录必须是对象", unit_index=index, character_index=char_index))
                continue
            character_id = character.get("character_id")
            if not isinstance(character_id, str) or not character_id.strip():
                errors.append(issue("shotplan_character_id_missing", "出场角色缺少 character_id", unit_index=index, character_index=char_index))
            else:
                used_character_ids.add(character_id)
            anchor_ref = character.get("anchor_ref")
            if (
                isinstance(character_id, str)
                and isinstance(anchor_ref, dict)
                and anchor_ref.get("artifact_key") != f"character_anchor:{character_id}"
            ):
                errors.append(issue(
                    "shotplan_character_identity_mismatch",
                    "角色 ID 必须绑定同 ID 的角色锚点，禁止跨制品身份漂移",
                    unit_index=index,
                    character_id=character_id,
                ))
            if not isinstance(character.get("appearance_lock"), str) or not character["appearance_lock"].strip():
                errors.append(issue("shotplan_appearance_lock_missing", "出场角色必须注入 appearance_lock 外形锁摘要", unit_index=index, character_index=char_index))
            anchor_error = anchor_reference_error(state, character.get("anchor_ref"), "character_anchor")
            if anchor_error:
                errors.append(issue("shotplan_character_anchor_invalid", anchor_error, unit_index=index, character_index=char_index))
        scene_anchor_ref = unit.get("scene_anchor_ref")
        anchor_error = anchor_reference_error(state, scene_anchor_ref, "scene_anchor")
        if anchor_error:
            errors.append(issue("shotplan_scene_anchor_invalid", anchor_error, unit_index=index))
        elif isinstance(scene_anchor_ref, dict):
            used_scene_anchor_keys.add(scene_anchor_ref["artifact_key"])
        for prop_index, prop_ref in enumerate(unit.get("prop_anchor_refs", []) or [], 1):
            anchor_error = anchor_reference_error(state, prop_ref, "prop_anchor")
            if anchor_error:
                errors.append(issue("shotplan_prop_anchor_invalid", anchor_error, unit_index=index, prop_index=prop_index))

        dialogue = unit.get("dialogue")
        if not isinstance(dialogue, list):
            errors.append(issue("shotplan_dialogue_invalid", "dialogue 必须是数组（无对白用空数组）", unit_index=index))
            dialogue = []
        lip_sync_count = 0
        lip_sync_speakers: set[str] = set()
        for cue_entry in dialogue:
            if not isinstance(cue_entry, dict):
                errors.append(issue("shotplan_dialogue_entry_invalid", "dialogue 条目必须是对象", unit_index=index))
                continue
            cue_id = cue_entry.get("cue_id")
            if not isinstance(cue_id, str) or not cue_id.strip():
                errors.append(issue("shotplan_cue_id_missing", "dialogue 条目缺少 cue_id", unit_index=index))
                continue
            cue = cues_by_id.get(cue_id)
            if cue is None or (expected_cue_ids and cue_id not in expected_cue_ids):
                errors.append(issue("shotplan_cue_unknown", "引用了当前集台词表中不存在的对白 cue", unit_index=index, cue_id=cue_id))
                continue
            used_cue_ids.append(cue_id)
            if cue.get("scene_id") != scene_id:
                errors.append(issue("shotplan_cue_scene_mismatch", "引用的对白 cue 不属于当前场次", unit_index=index, cue_id=cue_id))
            if cue_entry.get("lip_sync") is True:
                lip_sync_count += 1
                speaker = cue.get("speaker_id") or cue.get("character_id") or cue.get("speaker_name")
                if isinstance(speaker, str):
                    lip_sync_speakers.add(speaker)
        if lip_sync_count and len(lip_sync_speakers) > 1:
            errors.append(issue("shotplan_multi_lip_sync", "一个分镜单元只允许一名角色清晰对嘴", unit_index=index, speakers=sorted(lip_sync_speakers)))

        errors.extend(validate_unit_content_contract(unit, beats, decisions_by_id, index, strict_contract))
        errors.extend(validate_unit_character_registry(unit, canonical_character_ids, index))
        errors.extend(validate_unit_character_modes(unit, cues_by_id, index))
        errors.extend(validate_unit_spatial_audio_contract(unit, cues_by_id, index, strict_contract))
        errors.extend(validate_unit_feasibility(unit, cues_by_id, unit_rate, index, strict_contract))

        if not strict_contract and (
            not isinstance(unit.get("sound"), list) or not all(
                isinstance(value, str) and value.strip() for value in unit.get("sound", [])
            )
        ):
            errors.append(issue("shotplan_sound_invalid", "sound 必须是字符串数组", unit_index=index))
        negative = unit.get("negative_constraints")
        if not isinstance(negative, list) or not negative or not all(
            isinstance(value, str) and value.strip() for value in negative
        ):
            errors.append(issue("shotplan_negative_missing", "每个分镜单元必须提供非空 negative_constraints", unit_index=index))
        if unit.get("generation_strategy") not in GENERATION_STRATEGIES:
            errors.append(issue("shotplan_strategy_invalid", "generation_strategy 无效", unit_index=index, allowed=sorted(GENERATION_STRATEGIES)))

        unit_prompt_text = unit.get("prompt_text")
        if unit_prompt_text is not None:
            if not isinstance(unit_prompt_text, str) or not unit_prompt_text.strip():
                errors.append(issue("shotplan_prompt_text_invalid", "prompt_text 如提供必须是非空字符串", unit_index=index))
            elif re.search(r"(?<!\d)\d{1,2}\s*(?:[-—~至到])\s*\d{1,2}\s*秒", unit_prompt_text):
                errors.append(issue("shotplan_prompt_hard_timestamp", "通用提示词不得使用镜头内硬秒点", unit_index=index))
            errors.extend(validate_unit_prompt_executability(unit, cues_by_id, index))

        state_chain = unit.get("state_chain")
        if not isinstance(state_chain, dict):
            errors.append(issue("shotplan_state_chain_missing", "分镜单元必须包含 state_chain", unit_index=index))
            state_chain = {}
        chain_id = state_chain.get("chain_id")
        enter_state = state_chain.get("enter")
        exit_state = state_chain.get("exit")
        if not isinstance(chain_id, str) or not chain_id.strip():
            errors.append(issue("shotplan_chain_id_missing", "state_chain 缺少 chain_id", unit_index=index))
        for field, value in (("enter", enter_state), ("exit", exit_state)):
            if not isinstance(value, dict) or not isinstance(value.get("characters"), dict):
                errors.append(issue("shotplan_state_invalid", f"state_chain.{field} 必须包含 characters 状态对象（位置/朝向/服装/道具/伤势/知情）", unit_index=index, field=field))
        if previous_chain == chain_id and isinstance(previous_exit, dict) and isinstance(enter_state, dict):
            if previous_exit != enter_state:
                errors.append(issue("shotplan_state_chain_break", "同链上一单元 exit 状态必须与本单元 enter 状态完全一致", unit_index=index))
        previous_chain = chain_id if isinstance(chain_id, str) else None
        previous_exit = exit_state

    errors.extend(validate_tail_frame_contract(units, state, str(episode_id or scope), project_path))

    used_counts = Counter(used_cue_ids)
    missing_cues = sorted(expected_cue_ids - set(used_cue_ids))
    duplicate_cues = sorted(cue_id for cue_id, count in used_counts.items() if count > 1)
    if missing_cues:
        errors.append(issue("shotplan_cue_coverage_missing", "AI分镜计划未覆盖当前集全部对白/VO/OS", missing=missing_cues))
    if duplicate_cues:
        errors.append(issue("shotplan_cue_coverage_duplicate", "同一对白 cue 在分镜计划中重复绑定", duplicate=duplicate_cues))

    spec_duration = project_target_duration_seconds(project_path, state)
    policy = project_duration_policy(project_path, state)
    tolerance = duration_tolerance_ratio(policy)
    target_duration = payload.get("target_duration_seconds")
    if target_duration is None and spec_duration is not None:
        # v0.8.1 及以前省略该字段即可整段跳过时长校验；项目已声明目标时长时必须声明。
        errors.append(issue(
            "shotplan_target_duration_missing",
            "项目规格已声明单集目标时长，AI分镜计划必须写明 target_duration_seconds",
            project_spec=spec_duration,
        ))
    if target_duration is not None:
        if type(target_duration) is not int or target_duration <= 0:
            errors.append(issue("shotplan_target_duration_invalid", "target_duration_seconds 必须是正整数（来自项目规格的单集目标时长）"))
        else:
            if spec_duration is not None and target_duration != spec_duration:
                errors.append(issue(
                    "shotplan_target_duration_mismatch",
                    "AI分镜计划自报的单集目标时长与已确认项目规格不一致",
                    project_spec=spec_duration,
                    plan=target_duration,
                ))
            deviation = abs(total_unit_duration - target_duration) / target_duration
            if deviation > tolerance and (
                not isinstance(payload.get("duration_deviation_note"), str)
                or not payload["duration_deviation_note"].strip()
            ):
                errors.append(issue(
                    "shotplan_duration_deviation",
                    f"单元合计时长偏离单集目标超过{round(tolerance * 100)}%，须提供 duration_deviation_note 或返修",
                    total=round(total_unit_duration, 1),
                    target=target_duration,
                    tolerance_ratio=tolerance,
                ))

    max_scenes = budget.get("max_scene_anchors")
    if type(max_scenes) is int and len(used_scene_anchor_keys) > max_scenes and (
        not isinstance(payload.get("over_budget_note"), str) or not payload["over_budget_note"].strip()
    ):
        errors.append(issue("shotplan_scene_budget_exceeded", "使用的场景锚点数超出 asset_budget.max_scene_anchors，须提供 over_budget_note 或返修", used=len(used_scene_anchor_keys), budget=max_scenes))
    max_characters = budget.get("max_speaking_characters")
    if type(max_characters) is int and len(used_character_ids) > max_characters and (
        not isinstance(payload.get("over_budget_note"), str) or not payload["over_budget_note"].strip()
    ):
        errors.append(issue("shotplan_character_budget_exceeded", "出场角色数超出 asset_budget.max_speaking_characters，须提供 over_budget_note 或返修", used=len(used_character_ids), budget=max_characters))
    return errors


def compile_ai_execution_prompt_text(prompt: dict[str, Any]) -> str:
    return json.dumps(prompt, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def validate_ai_execution_content_contract(
    task: dict[str, Any],
    shot_units_by_id: dict[str, dict[str, Any]],
    task_index: int,
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    source_unit_ids = task.get("source_unit_ids") if isinstance(task.get("source_unit_ids"), list) else []
    allowed_atoms: dict[str, dict[str, Any]] = {}
    allowed_characters: set[str] = set()
    for unit_id in source_unit_ids:
        unit = shot_units_by_id.get(unit_id)
        if not isinstance(unit, dict):
            continue
        for atom in unit.get("content_atoms", []) if isinstance(unit.get("content_atoms"), list) else []:
            if isinstance(atom, dict) and isinstance(atom.get("atom_id"), str):
                allowed_atoms[atom["atom_id"]] = atom
        for character in unit.get("characters_on_screen", []) if isinstance(unit.get("characters_on_screen"), list) else []:
            if isinstance(character, dict) and isinstance(character.get("character_id"), str):
                allowed_characters.add(character["character_id"])
    atom_refs = task.get("content_atom_refs")
    if not isinstance(atom_refs, list) or not atom_refs or set(atom_refs) != set(allowed_atoms):
        errors.append(issue("aiexec_content_atom_refs_mismatch", "执行任务必须无遗漏地消费绑定分镜单元的全部 content atoms", task_index=task_index, expected=sorted(allowed_atoms), actual=sorted(atom_refs) if isinstance(atom_refs, list) else []))
        atom_refs = []
    expected_action = compiled_content_atom_text(atom_refs, allowed_atoms) if atom_refs else None
    prompt = task.get("prompt")
    if not isinstance(prompt, dict):
        return errors
    if expected_action is None or compact_dialogue_text(str(prompt.get("action", ""))) != compact_dialogue_text(expected_action):
        errors.append(issue("aiexec_prompt_content_unproven", "prompt.action 必须由绑定分镜 content atoms 确定性编译", task_index=task_index))
    subjects = prompt.get("subject")
    subject_ids = {
        item.get("character_id") for item in subjects
        if isinstance(item, dict) and isinstance(item.get("character_id"), str)
    } if isinstance(subjects, list) else set()
    if subject_ids - allowed_characters:
        errors.append(issue("aiexec_prompt_subject_unproven", "prompt.subject 包含绑定分镜未出现的人物", task_index=task_index, unknown=sorted(subject_ids - allowed_characters)))
    environment_atom_refs = task.get("environment_atom_refs", [])
    if environment_atom_refs:
        expected_environment = compiled_content_atom_text(environment_atom_refs, allowed_atoms) if isinstance(environment_atom_refs, list) else None
        if expected_environment is None or compact_dialogue_text(str(prompt.get("environment", ""))) != compact_dialogue_text(expected_environment):
            errors.append(issue("aiexec_prompt_environment_unproven", "prompt.environment 必须来自绑定环境 content atoms", task_index=task_index))
    elif prompt.get("environment") != "使用绑定场景锚点":
        errors.append(issue("aiexec_prompt_environment_unproven", "没有环境 content atom 时 prompt.environment 必须固定为使用绑定场景锚点", task_index=task_index))
    if task.get("prompt_compiler_version") != 1:
        errors.append(issue("aiexec_prompt_compiler_missing", "执行任务必须使用 prompt_compiler_version=1", task_index=task_index))
    expected_prompt_text = compile_ai_execution_prompt_text(prompt)
    if task.get("prompt_text") != expected_prompt_text:
        errors.append(issue("aiexec_prompt_text_not_compiled", "prompt_text 必须等于代码确定性编译结果", task_index=task_index))
    return errors


def validate_ai_video_execution_payload(
    project_path: Path,
    state: dict[str, Any],
    artifact_key: str,
    record: dict[str, Any],
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    """校验模型适配层执行计划：以绑定的模型能力档案为约束来源，覆盖全部分镜单元。"""
    errors: list[dict[str, Any]] = []
    scope = artifact_key.split(":", 1)[1] if ":" in artifact_key else ""
    scope_episode = scope.split(":", 1)[0] if scope else ""
    if not re.fullmatch(r"E\d{3,6}(?::[A-Za-z0-9_.-]+)?", scope, re.IGNORECASE):
        errors.append(issue("aiexec_key_scope_invalid", "执行计划 key 必须使用 ai_video_execution_plan:E001 或 ai_video_execution_plan:E001:<模型> 形式"))
    episode_id = payload.get("episode_id")
    if not isinstance(episode_id, str) or episode_id.upper() != scope_episode.upper():
        errors.append(issue("aiexec_episode_mismatch", "执行计划 episode_id 与制品 key 不一致"))
    embedded_text = json.dumps(payload, ensure_ascii=False)
    if re.search(r"data:(?:image|video|audio)/|\bb64_json\b|\bbase64\b", embedded_text, re.IGNORECASE):
        errors.append(issue("aiexec_embedded_binary_forbidden", "执行计划禁止嵌入 Base64 或 data URI 媒体数据"))
    execution_policy = payload.get("execution_policy")
    if not isinstance(execution_policy, dict):
        errors.append(issue("aiexec_policy_invalid", "execution_policy 必须是对象"))
        execution_policy = {}
    if execution_policy.get("generate_images") is not False:
        errors.append(issue("aiexec_image_generation_forbidden", "执行计划必须明确 generate_images: false"))
    if execution_policy.get("submit_video_requests") is not False:
        errors.append(issue("aiexec_video_submission_forbidden", "本插件只生成文字执行层，必须明确 submit_video_requests: false"))

    profile = dependency_payload_of_type(project_path, state, record, "model_capability_profile")
    if profile is None:
        errors.append(issue("aiexec_profile_dependency_missing", "执行计划必须绑定一份模型能力档案"))
        profile = {}
    capabilities = profile.get("capabilities") if isinstance(profile.get("capabilities"), dict) else {}
    duration_range = capabilities.get("task_duration_seconds") if isinstance(capabilities.get("task_duration_seconds"), dict) else {}
    minimum = duration_range.get("min") if type(duration_range.get("min")) is int else 1
    maximum = duration_range.get("max") if type(duration_range.get("max")) is int else 600
    input_modes = capabilities.get("input_modes")
    allowed_modes = set(input_modes) if isinstance(input_modes, list) and input_modes else {
        "text_to_video", "multimodal_reference", "first_frame", "first_last_frame", "continuation"
    }
    max_clear_speakers = capabilities.get("max_clear_speakers")
    if type(max_clear_speakers) is not int:
        max_clear_speakers = 1

    shot_plan = dependency_payload_of_type(project_path, state, record, "ai_shot_plan")
    shot_unit_ids: set[str] = set()
    shot_units_by_id: dict[str, dict[str, Any]] = {}
    if shot_plan is None:
        errors.append(issue("aiexec_shot_plan_dependency_missing", "执行计划必须绑定当前集已确认的 AI分镜计划"))
    else:
        for unit in shot_plan.get("units", []) if isinstance(shot_plan.get("units"), list) else []:
            if isinstance(unit, dict) and isinstance(unit.get("unit_id"), str):
                shot_unit_ids.add(unit["unit_id"])
                shot_units_by_id[unit["unit_id"]] = unit
        if not shot_unit_ids:
            errors.append(issue("aiexec_shot_plan_units_missing", "绑定的 AI分镜计划没有可用单元"))

    reference_assets = payload.get("reference_assets")
    if not isinstance(reference_assets, list):
        errors.append(issue("aiexec_reference_assets_invalid", "reference_assets 必须是数组；纯文本模式使用空数组"))
        reference_assets = []
    asset_ids: set[str] = set()
    unavailable_assets: set[str] = set()
    for index, asset in enumerate(reference_assets, 1):
        if not isinstance(asset, dict):
            errors.append(issue("aiexec_reference_asset_invalid", "参考素材记录必须是对象", asset_index=index))
            continue
        asset_id = asset.get("asset_id")
        if isinstance(asset_id, str) and asset_id.strip():
            asset_ids.add(asset_id)
            if asset.get("status") != "provided":
                unavailable_assets.add(asset_id)
        if asset.get("origin") not in {"user_provided", "existing_project", "generated_elsewhere"}:
            errors.append(issue("aiexec_reference_asset_origin_invalid", "参考素材不能由本插件生成", asset_index=index))

    tasks = payload.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        errors.append(issue("aiexec_tasks_invalid", "tasks 必须是非空数组"))
        return errors
    seen_task_ids: set[str] = set()
    used_unit_ids: list[str] = []
    total_duration = 0
    previous_chain: str | None = None
    previous_output_state: str | None = None
    hard_timestamp = re.compile(r"(?<!\d)\d{1,2}\s*(?:[-—~至到])\s*\d{1,2}\s*秒")
    for index, task in enumerate(tasks, 1):
        if not isinstance(task, dict):
            errors.append(issue("aiexec_task_invalid", "生成任务必须是对象", task_index=index))
            continue
        task_id = task.get("task_id")
        if not isinstance(task_id, str) or not task_id.strip():
            errors.append(issue("aiexec_task_id_missing", "生成任务缺少 task_id", task_index=index))
        elif task_id in seen_task_ids:
            errors.append(issue("aiexec_task_id_duplicate", f"生成任务 ID 重复：{task_id}"))
        else:
            seen_task_ids.add(task_id)
        if task.get("sequence") != index:
            errors.append(issue("aiexec_task_sequence_invalid", "sequence 必须从1连续递增", task_index=index))
        source_unit_ids = task.get("source_unit_ids")
        if not isinstance(source_unit_ids, list) or not source_unit_ids or not all(
            isinstance(value, str) and value.strip() for value in source_unit_ids
        ):
            errors.append(issue("aiexec_source_units_missing", "生成任务必须列出来源分镜单元 source_unit_ids", task_index=index))
            source_unit_ids = []
        unknown_units = sorted(set(source_unit_ids) - shot_unit_ids) if shot_unit_ids else []
        if unknown_units:
            errors.append(issue("aiexec_source_unit_unknown", "生成任务引用了分镜计划中不存在的单元", task_index=index, unknown=unknown_units))
        used_unit_ids.extend(source_unit_ids)
        duration = task.get("duration_seconds")
        if type(duration) is not int or duration < minimum or duration > maximum:
            errors.append(issue("aiexec_task_duration_invalid", "生成任务时长超出模型能力档案区间", task_index=index, duration=duration, allowed={"min": minimum, "max": maximum}))
        else:
            total_duration += duration
        mode = task.get("generation_mode")
        if mode not in allowed_modes:
            errors.append(issue("aiexec_generation_mode_invalid", "generation_mode 不在模型能力档案 input_modes 内", task_index=index, allowed=sorted(allowed_modes)))
        task_asset_ids = task.get("reference_asset_ids")
        if not isinstance(task_asset_ids, list) or not all(
            isinstance(value, str) and value.strip() for value in task_asset_ids
        ):
            errors.append(issue("aiexec_task_assets_invalid", "reference_asset_ids 必须是字符串数组", task_index=index))
            task_asset_ids = []
        if set(task_asset_ids) - asset_ids:
            errors.append(issue("aiexec_task_asset_unknown", "生成任务引用了未登记参考素材", task_index=index, unknown=sorted(set(task_asset_ids) - asset_ids)))
        if set(task_asset_ids) & unavailable_assets:
            errors.append(issue("aiexec_task_asset_unbound", "生成任务绑定的参考素材尚未提供", task_index=index))
        if mode == "text_to_video" and task_asset_ids:
            errors.append(issue("aiexec_text_mode_has_assets", "text_to_video 任务不得绑定参考素材", task_index=index))
        if mode not in {"text_to_video", "continuation"} and not task_asset_ids:
            errors.append(issue("aiexec_reference_mode_without_assets", "非纯文本模式必须绑定已有参考素材", task_index=index))
        clear_speakers = task.get("clear_speakers")
        if type(clear_speakers) is not int or clear_speakers < 0:
            errors.append(issue("aiexec_clear_speakers_missing", "生成任务必须声明 clear_speakers（清晰对嘴人数）", task_index=index))
        elif clear_speakers > max_clear_speakers:
            errors.append(issue("aiexec_clear_speakers_exceeded", "清晰对嘴人数超出模型能力档案上限", task_index=index, declared=clear_speakers, allowed=max_clear_speakers))
        prompt = task.get("prompt")
        if not isinstance(prompt, dict):
            errors.append(issue("aiexec_prompt_invalid", "prompt 必须是结构化对象", task_index=index))
            prompt = {}
        for field in ("style_ref", "action", "camera", "environment"):
            if not isinstance(prompt.get(field), str) or not prompt[field].strip():
                errors.append(issue("aiexec_prompt_field_missing", f"prompt 缺少 {field}", task_index=index, field=field))
        if not isinstance(prompt.get("subject"), list):
            errors.append(issue("aiexec_prompt_subject_invalid", "prompt.subject 必须是数组（空场景用空数组）", task_index=index))
        negative = prompt.get("negative")
        if not isinstance(negative, list) or not negative or not all(
            isinstance(value, str) and value.strip() for value in negative
        ):
            errors.append(issue("aiexec_prompt_negative_missing", "prompt.negative 必须是非空数组", task_index=index))
        prompt_text = task.get("prompt_text")
        if not isinstance(prompt_text, str) or not prompt_text.strip():
            errors.append(issue("aiexec_prompt_text_missing", "生成任务缺少编译后的 prompt_text", task_index=index))
        elif hard_timestamp.search(prompt_text):
            errors.append(issue("aiexec_prompt_hard_timestamp", "提示词不得使用镜头内硬秒点", task_index=index))
        errors.extend(validate_ai_execution_content_contract(task, shot_units_by_id, index))
        chain = task.get("chain")
        if not isinstance(chain, dict):
            errors.append(issue("aiexec_chain_invalid", "生成任务 chain 必须是对象", task_index=index))
            chain = {}
        chain_id = chain.get("chain_id")
        input_state = chain.get("input_state")
        output_state = chain.get("output_state")
        if not all(isinstance(value, str) and value.strip() for value in (chain_id, input_state, output_state)):
            errors.append(issue("aiexec_chain_field_missing", "chain 必须包含非空 chain_id/input_state/output_state", task_index=index))
        if previous_chain == chain_id and previous_output_state != input_state:
            errors.append(issue("aiexec_chain_break", "同链上一任务 output_state 必须等于本任务 input_state", task_index=index))
        if mode == "continuation" and not task_asset_ids and previous_chain != chain_id:
            errors.append(issue("aiexec_continuation_chain_start", "continuation 任务必须与上一任务同链续接；链首请改用其他模式或绑定参考素材", task_index=index))
        previous_chain = chain_id if isinstance(chain_id, str) else None
        previous_output_state = output_state if isinstance(output_state, str) else None

    unit_counts = Counter(used_unit_ids)
    if shot_unit_ids:
        missing_units = sorted(shot_unit_ids - set(used_unit_ids))
        duplicate_units = sorted(unit_id for unit_id, count in unit_counts.items() if count > 1)
        if missing_units:
            errors.append(issue("aiexec_unit_coverage_missing", "执行计划未覆盖分镜计划的全部单元", missing=missing_units))
        if duplicate_units:
            errors.append(issue("aiexec_unit_coverage_duplicate", "同一分镜单元被多个生成任务重复消费", duplicate=duplicate_units))
    if payload.get("total_duration_seconds") != total_duration:
        errors.append(issue("aiexec_total_duration_mismatch", "total_duration_seconds 必须等于全部生成任务时长之和"))
    return errors


def validate_source_review_payload(
    state: dict[str, Any],
    artifact_key: str,
    record: dict[str, Any],
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    if artifact_key != "source_review":
        errors.append(
            issue(
                "source_review_scope_invalid",
                "来源官网审核制品 key 必须是 source_review",
                artifact_key=artifact_key,
            )
        )
    if record_dependency_refs(record):
        errors.append(
            issue(
                "source_review_dependencies_invalid",
                "来源官网审核直接绑定上传来源 ID，不应登记制品依赖",
            )
        )
    if payload.get("schema_version") != 1:
        errors.append(issue("source_review_schema_invalid", "来源官网审核 schema_version 必须为1"))
    if payload.get("project_id") != state.get("project_id"):
        errors.append(issue("source_review_project_mismatch", "来源官网审核 project_id 不一致"))
    policy = state.get("source_policy", default_source_policy())
    if not isinstance(policy, dict):
        policy = default_source_policy()
    if (
        policy.get("source_kind") != "published_novel"
        or policy.get("official_review_enabled") is not True
    ):
        errors.append(
            issue(
                "source_review_not_enabled",
                "只有主动开启官网审核的 published_novel 项目可以登记 source_review",
            )
        )
    if payload.get("source_kind") != "published_novel":
        errors.append(issue("source_review_kind_invalid", "source_review 的 source_kind 必须为 published_novel"))
    if payload.get("official_url") != policy.get("official_url"):
        errors.append(issue("source_review_url_mismatch", "来源官网审核 URL 与项目来源策略不一致"))
    expected_source_ids = {
        item.get("source_id")
        for item in state.get("sources", [])
        if isinstance(item, dict) and isinstance(item.get("source_id"), str)
    }
    uploaded_source_ids = payload.get("uploaded_source_ids")
    if not isinstance(uploaded_source_ids, list) or not all(
        isinstance(value, str) and value for value in uploaded_source_ids
    ):
        errors.append(issue("source_review_sources_invalid", "uploaded_source_ids 必须是字符串数组"))
    elif len(uploaded_source_ids) != len(set(uploaded_source_ids)) or set(uploaded_source_ids) != expected_source_ids:
        errors.append(
            issue(
                "source_review_sources_mismatch",
                "来源官网审核必须无重复地覆盖当前全部上传来源 ID",
                missing=sorted(expected_source_ids - set(uploaded_source_ids)),
                extra=sorted(set(uploaded_source_ids) - expected_source_ids),
            )
        )
    check_statuses = {"matched", "partial", "mismatch", "inconclusive", "not_available"}
    checks = payload.get("checks")
    required_checks = ("title", "author", "chapter_coverage", "sample_content")
    if not isinstance(checks, dict) or any(
        checks.get(name) not in check_statuses for name in required_checks
    ):
        errors.append(issue("source_review_checks_invalid", "来源官网审核 checks 字段不完整或状态无效"))
    if payload.get("conclusion") not in {"matched", "partial", "mismatch", "inconclusive"}:
        errors.append(issue("source_review_conclusion_invalid", "来源官网审核 conclusion 无效"))
    for field in ("checked_at", "automation_limitations"):
        if not isinstance(payload.get(field), str) or not payload[field].strip():
            errors.append(issue("source_review_field_invalid", f"来源官网审核缺少 {field}", field=field))
    if not isinstance(payload.get("evidence"), list):
        errors.append(issue("source_review_evidence_invalid", "来源官网审核 evidence 必须是数组"))
    return errors


FINAL_OUTPUT_PLACEHOLDER_RE = re.compile(
    r"\b(?:TBD|TODO|FIXME)\b|20XX|(?:\d{2}|XX)XX年|(?:\[|【)待(?:补|定|确认)",
    re.IGNORECASE,
)


def compact_dialogue_text(value: str) -> str:
    """仅忽略排版空白；不改字词、语序或标点。"""
    return re.sub(r"\s+", "", value)


def validate_dialogue_cue_sheet_payload(
    project_path: Path,
    state: dict[str, Any],
    artifact_key: str,
    record: dict[str, Any],
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    """对白采用原著只读契约，不再支持模型改写或自填 source_text。"""
    errors: list[dict[str, Any]] = []
    if payload.get("contract_version") != 2:
        errors.append(
            issue(
                "dialogue_contract_upgrade_required",
                "台词声音表必须使用 contract_version=2 的原著对白只读契约",
                artifact_key=artifact_key,
            )
        )
    corpus = dependency_payload_of_type(
        project_path, state, record, "source_corpus"
    )
    event_index = dependency_payload_of_type(
        project_path, state, record, "source_event_index"
    )
    beats = source_beat_index(event_index)
    episode_scopes = (
        event_index.get("episode_scopes") if isinstance(event_index, dict) else None
    )
    canonical_character_ids = source_character_ids(event_index)
    if not beats or not isinstance(episode_scopes, dict):
        errors.append(
            issue(
                "dialogue_source_event_index_missing",
                "台词声音表必须直接绑定带 episode_scopes 和 beats 的原著事件索引",
                artifact_key=artifact_key,
            )
        )
    source_units = corpus.get("source_units") if isinstance(corpus, dict) else None
    source_text_by_id: dict[str, str] = {}
    if not isinstance(source_units, list):
        errors.append(
            issue(
                "dialogue_source_corpus_missing",
                "台词声音表必须直接绑定有效原著语料库",
                artifact_key=artifact_key,
            )
        )
    else:
        for unit in source_units:
            if not isinstance(unit, dict):
                continue
            unit_id = unit.get("source_unit_id")
            content_path = path_from_record(project_path, unit.get("content_path"))
            if (
                isinstance(unit_id, str)
                and unit_id
                and content_path is not None
                and content_path.is_file()
            ):
                source_text_by_id[unit_id] = content_path.read_text(encoding="utf-8")

    records = payload.get("records")
    if not isinstance(records, list) or not records:
        errors.append(
            issue(
                "dialogue_records_invalid",
                "台词声音表 records 必须是非空数组",
                artifact_key=artifact_key,
            )
        )
        return errors
    cue_ids: set[str] = set()
    previous_order_by_episode: dict[str, tuple[int, int]] = {}
    for index, cue in enumerate(records):
        if not isinstance(cue, dict):
            errors.append(
                issue(
                    "dialogue_cue_invalid",
                    "台词声音表中的每条记录必须是对象",
                    cue_index=index,
                )
            )
            continue
        cue_id = cue.get("cue_id")
        if not isinstance(cue_id, str) or not cue_id.strip():
            errors.append(
                issue(
                    "dialogue_cue_id_invalid",
                    "台词记录缺少 cue_id",
                    cue_index=index,
                )
            )
        elif cue_id in cue_ids:
            errors.append(
                issue(
                    "dialogue_cue_id_duplicate",
                    f"台词 cue_id 重复：{cue_id}",
                    cue_index=index,
                )
            )
        else:
            cue_ids.add(cue_id)
        cue_type = cue.get("type")
        delivery_mode = cue.get("delivery_mode")
        is_spoken = (
            cue_type in SPOKEN_CUE_TYPES
            or delivery_mode in SPOKEN_DELIVERY_MODES
            or isinstance(cue.get("speaker_id"), str)
        )
        if not is_spoken:
            continue
        speaker_id = cue.get("speaker_id")
        if not isinstance(speaker_id, str) or speaker_id not in canonical_character_ids:
            errors.append(
                issue(
                    "dialogue_speaker_unknown",
                    "对白、VO、OS speaker_id 必须引用原著事件索引的 canonical character ID",
                    cue_index=index,
                    cue_id=cue_id,
                    speaker_id=speaker_id,
                )
            )
        forbidden = sorted(DIALOGUE_REWRITE_METADATA_FIELDS.intersection(cue))
        if forbidden:
            errors.append(
                issue(
                    "dialogue_generated_metadata_forbidden",
                    "原著对白只读契约禁止改写元数据和模型自填 source_text",
                    cue_index=index,
                    cue_id=cue_id,
                    fields=forbidden,
                )
            )
        text = cue.get("text")
        if not isinstance(text, str) or not text.strip():
            errors.append(
                issue(
                    "dialogue_text_invalid",
                    "对白、VO、OS 必须提供非空原著文本",
                    cue_index=index,
                    cue_id=cue_id,
                )
            )
            continue
        if FINAL_OUTPUT_PLACEHOLDER_RE.search(text):
            errors.append(
                issue(
                    "dialogue_placeholder_forbidden",
                    "正式配音台词禁止包含 20XX、TBD、TODO 或待定占位符",
                    cue_index=index,
                    cue_id=cue_id,
                )
            )
        source_unit_id = cue.get("source_unit_id")
        source_locator = cue.get("source_locator")
        if not isinstance(source_locator, str) or not source_locator.strip():
            errors.append(
                issue(
                    "dialogue_source_locator_missing",
                    "对白、VO、OS 必须提供可回查的 source_locator",
                    cue_index=index,
                    cue_id=cue_id,
                )
            )
        episode_id = cue.get("episode_id")
        source_beat_refs = cue.get("source_beat_refs")
        if (
            not isinstance(source_beat_refs, list)
            or not source_beat_refs
            or not all(isinstance(value, str) and value.strip() for value in source_beat_refs)
        ):
            errors.append(
                issue(
                    "dialogue_source_beats_missing",
                    "每条对白、VO、OS 必须引用非空 source_beat_refs",
                    cue_index=index,
                    cue_id=cue_id,
                )
            )
        else:
            unknown = sorted(set(source_beat_refs) - set(beats))
            if unknown:
                errors.append(
                    issue(
                        "dialogue_source_beat_unknown",
                        "对白引用了不存在的来源 beat",
                        cue_index=index,
                        cue_id=cue_id,
                        unknown=unknown,
                    )
                )
            scope = episode_scopes.get(episode_id) if isinstance(episode_scopes, dict) else None
            allowed = scope.get("allowed_beat_ids") if isinstance(scope, dict) else None
            if not isinstance(allowed, list) or not allowed or not all(
                isinstance(value, str) and value in beats for value in allowed
            ):
                errors.append(
                    issue(
                        "dialogue_source_scope_invalid",
                        "当前集必须声明有效且非空的 allowed_beat_ids",
                        cue_index=index,
                        cue_id=cue_id,
                        episode_id=episode_id,
                    )
                )
            elif not unknown:
                outside = sorted(set(source_beat_refs) - set(allowed))
                if outside:
                    errors.append(
                        issue(
                            "dialogue_source_boundary_exceeded",
                            "对白引用超出当前集明确允许的原著 beat",
                            cue_index=index,
                            cue_id=cue_id,
                            episode_id=episode_id,
                            outside=outside,
                        )
                    )
                orders = [beats[value]["order"] for value in source_beat_refs]
                previous_order = previous_order_by_episode.get(episode_id)
                if previous_order is not None and min(orders) < previous_order:
                    errors.append(
                        issue(
                            "dialogue_source_order_violation",
                            "台词来源顺序发生倒退或调序",
                            cue_index=index,
                            cue_id=cue_id,
                            episode_id=episode_id,
                        )
                    )
                previous_order_by_episode[episode_id] = max(
                    previous_order or orders[0], max(orders)
                )
                locator_refs: set[str] = set()
                for beat_id in source_beat_refs:
                    locator_refs.update(beats[beat_id].get("source_refs", set()))
                if (
                    isinstance(source_locator, str)
                    and source_locator.strip()
                    and source_locator not in locator_refs
                    and source_unit_id not in locator_refs
                ):
                    errors.append(
                        issue(
                            "dialogue_source_locator_mismatch",
                            "source_locator/source_unit_id 与绑定 beat 的原著位置不一致",
                            cue_index=index,
                            cue_id=cue_id,
                            source_locator=source_locator,
                            source_beat_refs=source_beat_refs,
                        )
                    )
        source_text = (
            source_text_by_id.get(source_unit_id)
            if isinstance(source_unit_id, str)
            else None
        )
        if source_text is None:
            errors.append(
                issue(
                    "dialogue_source_unit_unknown",
                    "对白引用了不存在或不可读取的原著单元",
                    cue_index=index,
                    cue_id=cue_id,
                    source_unit_id=source_unit_id,
                )
            )
            continue
        if compact_dialogue_text(text) not in compact_dialogue_text(source_text):
            errors.append(
                issue(
                    "dialogue_not_exact_source",
                    "对白、VO、OS 必须逐字来自绑定的原著单元，不能润色、改写或补写",
                    cue_index=index,
                    cue_id=cue_id,
                    source_unit_id=source_unit_id,
                )
            )
    return errors


CHARACTER_ANCHOR_ROLE_KINDS = {"stable", "temporary_speaking", "crowd_group"}
CHARACTER_PRESENCE_MODES = {"on_screen", "voice_only", "crowd_group"}
VISUAL_STORY_CLAIM_PATTERNS = (
    re.compile(r"真实身份|继承人|血统|能力觉醒|家族徽记|伤疤来源|秘密组织"),
)


def _nonempty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_character_anchor_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    if payload.get("contract_version") != 2:
        errors.append(issue("character_anchor_contract_version_invalid", "人物锚点必须使用 contract_version 2"))
    if not _nonempty_text(payload.get("character_id")):
        errors.append(issue("character_anchor_id_missing", "人物锚点缺少 character_id"))
    if not _nonempty_text(payload.get("display_name")):
        errors.append(issue("character_anchor_name_missing", "人物锚点缺少 display_name"))
    if payload.get("role_kind") not in CHARACTER_ANCHOR_ROLE_KINDS:
        errors.append(issue("character_anchor_role_kind_invalid", "人物锚点 role_kind 非法"))
    source_appearance = payload.get("source_appearance")
    if not isinstance(source_appearance, dict):
        errors.append(issue("character_anchor_source_appearance_missing", "人物锚点缺少 source_appearance"))
    else:
        source_refs = source_appearance.get("source_refs")
        details = source_appearance.get("confirmed_details")
        if not isinstance(source_refs, list) or not all(_nonempty_text(value) for value in source_refs):
            errors.append(issue("character_anchor_source_refs_invalid", "source_appearance.source_refs 必须是字符串数组"))
        if not isinstance(details, list) or not all(_nonempty_text(value) for value in details):
            errors.append(issue("character_anchor_source_details_invalid", "source_appearance.confirmed_details 必须是字符串数组"))
    visual_design = payload.get("visual_design")
    if not isinstance(visual_design, dict):
        errors.append(issue("character_anchor_visual_design_missing", "人物锚点缺少 visual_design"))
        visual_design = {}
    elif visual_design.get("auto_completed") not in {True, False}:
        errors.append(issue("character_anchor_auto_completed_invalid", "visual_design.auto_completed 必须为布尔值"))
    turnaround = payload.get("turnaround_prompt")
    if not isinstance(turnaround, dict) or not _nonempty_text(turnaround.get("layout")):
        errors.append(issue("character_anchor_turnaround_layout_missing", "缺少人物三视图布局描述"))
    if not isinstance(turnaround, dict) or not _nonempty_text(turnaround.get("full_text")):
        errors.append(issue("character_anchor_turnaround_text_missing", "缺少完整人物三视图文字描述"))
    if isinstance(turnaround, dict):
        rules = turnaround.get("consistency_rules")
        if not isinstance(rules, list) or not rules or not all(_nonempty_text(value) for value in rules):
            errors.append(issue("character_anchor_consistency_rules_missing", "人物锚点必须提供三视图一致性规则"))
    visual_text = json.dumps(visual_design, ensure_ascii=False)
    if any(pattern.search(visual_text) for pattern in VISUAL_STORY_CLAIM_PATTERNS):
        errors.append(issue("character_anchor_visual_story_claim", "视觉设定包含身份、能力、身世或未揭露剧情暗示"))
    return errors


def validate_structured_development_artifact(
    project_path: Path,
    state: dict[str, Any],
    artifact_key: str,
    record: dict[str, Any],
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    artifact_kind = record.get("artifact_type")
    if artifact_kind not in STRUCTURED_DEVELOPMENT_TYPES:
        return errors
    payload = load_json_artifact_payload(project_path, artifact_key, record, errors)
    if payload is None:
        return errors
    if artifact_kind == "source_review":
        errors.extend(validate_source_review_payload(state, artifact_key, record, payload))
        return errors
    allowed_schema_versions = {1, 2} if artifact_kind == "source_event_index" else {1}
    if type(payload.get("schema_version")) is not int or payload.get("schema_version") not in allowed_schema_versions:
        errors.append(
            issue(
                "structured_schema_invalid",
                f"规范 JSON 的 schema_version 必须为{sorted(allowed_schema_versions)}",
                artifact_key=artifact_key,
            )
        )
    if payload.get("project_id") != state.get("project_id"):
        errors.append(issue("structured_project_mismatch", "规范 JSON 的 project_id 与项目不一致", artifact_key=artifact_key))
    generated_list, generated_refs = payload_generated_refs(payload)
    dependency_refs = record_dependency_refs(record)
    if (
        not isinstance(payload.get("generated_from"), list)
        or len(generated_list) != len(payload.get("generated_from", []))
        or len(generated_list) != len(generated_refs)
        or generated_refs != dependency_refs
    ):
        errors.append(
            issue(
                "structured_sources_mismatch",
                "规范 JSON 的 generated_from 必须无重复地精确绑定状态中的全部直接依赖",
                artifact_key=artifact_key,
            )
        )

    if artifact_kind == "dialogue_cue_sheet":
        errors.extend(
            validate_dialogue_cue_sheet_payload(
                project_path, state, artifact_key, record, payload
            )
        )

    elif artifact_kind == "chapter_analysis_registry":
        errors.extend(source_partition.validate_chapter_analysis_registry(payload))
        for item in payload.get("records", []):
            if not isinstance(item, dict) or item.get("analysis_status") != "analyzed":
                continue
            analysis_path = path_from_record(project_path, item.get("analysis_path"))
            if (
                analysis_path is None
                or not analysis_path.is_file()
                or sha256_file(analysis_path) != item.get("analysis_sha256")
            ):
                errors.append(
                    issue(
                        "analysis_registry_artifact_invalid",
                        "章节分析文件不存在、越界或hash不一致",
                        source_unit_id=item.get("source_unit_id"),
                    )
                )

    elif artifact_kind == "rolling_source_progress":
        errors.extend(source_partition.validate_rolling_source_progress(payload))

    elif artifact_kind == "batch_source_scope":
        scope = artifact_key.split(":", 1)[1] if ":" in artifact_key else ""
        batch_id = payload.get("batch_id")
        if not BATCH_ID_RE.fullmatch(scope) or batch_id != scope:
            errors.append(
                issue(
                    "batch_source_scope_id_invalid",
                    "批次原著范围的 key 范围与 batch_id 必须一致",
                    artifact_key=artifact_key,
                )
            )
        expected_episode_ids = batch_episode_ids(state, scope)
        episode_ids = payload.get("episode_ids")
        if expected_episode_ids is None or episode_ids != expected_episode_ids:
            errors.append(
                issue(
                    "batch_source_scope_episodes_mismatch",
                    "批次原著范围 episode_ids 必须与项目批次定义完全一致",
                )
            )
        series_map = dependency_payload_of_type(project_path, state, record, "series_map")
        if isinstance(series_map, dict) and (
            series_map.get("granularity", "full") == "backbone"
            and series_map.get("contract_version") != 2
        ):
            errors.append(
                issue(
                    "batch_source_scope_backbone_upgrade_required",
                    "批次原著范围不能绑定未升级的旧 backbone 地图",
                )
            )
        corpus = dependency_payload_of_type(project_path, state, record, "source_corpus")
        corpus_units = corpus.get("source_units") if isinstance(corpus, dict) else None
        known_ids = {
            item.get("source_unit_id")
            for item in corpus_units
            if isinstance(item, dict) and isinstance(item.get("source_unit_id"), str)
        } if isinstance(corpus_units, list) else set()
        required_ids = payload.get("required_source_unit_ids")
        if not isinstance(required_ids, list) or not required_ids or not all(
            isinstance(value, str) and value for value in required_ids
        ):
            errors.append(
                issue(
                    "batch_source_scope_units_invalid",
                    "required_source_unit_ids 必须是非空字符串数组",
                )
            )
        else:
            required_set = set(required_ids)
            if len(required_ids) != len(required_set) or not required_set.issubset(known_ids):
                errors.append(
                    issue(
                        "batch_source_scope_units_mismatch",
                        "批次原著范围不能重复或引用未知原著单元",
                        unknown=sorted(required_set - known_ids),
                    )
                )

    elif artifact_kind == "batch_source_detail":
        scope = artifact_key.split(":", 1)[1] if ":" in artifact_key else ""
        batch_id = payload.get("batch_id")
        if not BATCH_ID_RE.fullmatch(scope) or batch_id != scope:
            errors.append(
                issue(
                    "batch_source_detail_id_invalid",
                    "批次原著细化的 key 范围与 batch_id 必须一致",
                )
            )
        scope_payload = dependency_payload_of_type(
            project_path, state, record, "batch_source_scope"
        )
        required_ids = set(scope_payload.get("required_source_unit_ids", [])) if isinstance(scope_payload, dict) else set()
        units = payload.get("units")
        if not isinstance(units, list) or not units:
            errors.append(issue("batch_source_detail_units_invalid", "批次原著细化 units 必须是非空数组"))
            return errors
        actual_ids: list[str] = []
        event_ids: set[str] = set()
        for unit_index, unit in enumerate(units):
            if not isinstance(unit, dict):
                errors.append(issue("batch_source_detail_unit_invalid", "批次原著细化单元必须是对象", unit_index=unit_index))
                continue
            unit_id = unit.get("source_unit_id")
            if isinstance(unit_id, str) and unit_id:
                actual_ids.append(unit_id)
            else:
                errors.append(issue("batch_source_detail_unit_id_invalid", "批次原著细化单元缺少 source_unit_id", unit_index=unit_index))
            if unit.get("granularity") != "unit_detail":
                errors.append(
                    issue(
                        "batch_source_detail_granularity_invalid",
                        "批次原著细化中的所有单元必须为 unit_detail",
                        unit_index=unit_index,
                    )
                )
            events = unit.get("events")
            if not isinstance(events, list) or not events:
                errors.append(issue("batch_source_detail_events_invalid", "unit_detail 必须包含非空 events", unit_index=unit_index))
                continue
            for event_index, event in enumerate(events):
                if not isinstance(event, dict):
                    errors.append(issue("batch_source_detail_event_invalid", "细化事件必须是对象", unit_index=unit_index, event_index=event_index))
                    continue
                event_id = event.get("event_id")
                if not isinstance(event_id, str) or not event_id:
                    errors.append(issue("batch_source_detail_event_id_invalid", "细化事件缺少 event_id", unit_index=unit_index, event_index=event_index))
                elif event_id in event_ids:
                    errors.append(issue("batch_source_detail_event_id_duplicate", f"细化事件 ID 重复：{event_id}"))
                else:
                    event_ids.add(event_id)
                for field in ("summary", "cause", "action", "outcome", "state_change"):
                    if not isinstance(event.get(field), str) or not event[field].strip():
                        errors.append(issue("batch_source_detail_event_field_missing", f"细化事件缺少 {field}", unit_index=unit_index, event_index=event_index, field=field))
                refs = event.get("source_refs")
                if not isinstance(refs, list) or not refs or not all(isinstance(value, str) and value for value in refs):
                    errors.append(issue("batch_source_detail_refs_invalid", "细化事件 source_refs 必须是非空字符串数组", unit_index=unit_index, event_index=event_index))
        actual_set = set(actual_ids)
        if len(actual_ids) != len(actual_set) or actual_set != required_ids:
            errors.append(
                issue(
                    "batch_source_detail_coverage_mismatch",
                    "批次原著细化必须无重复地精确覆盖批次原著范围",
                    missing=sorted(required_ids - actual_set),
                    extra=sorted(actual_set - required_ids),
                )
            )

    elif artifact_kind == "batch_continuity_snapshot":
        scope = artifact_key.split(":", 1)[1] if ":" in artifact_key else ""
        if not BATCH_ID_RE.fullmatch(scope) or payload.get("batch_id") != scope:
            errors.append(issue("batch_snapshot_id_invalid", "批次连续性快照 key 与 batch_id 必须一致"))
        episode_ids = batch_episode_ids(state, scope)
        if episode_ids is None or payload.get("episode_ids") != episode_ids:
            errors.append(issue("batch_snapshot_episodes_mismatch", "批次连续性快照 episode_ids 与批次定义不一致"))
            episode_ids = episode_ids or []
        expected_refs: set[tuple[str, int]] = set()
        for episode_id in episode_ids:
            for key in (
                f"episode_script:{episode_id}",
                f"episode_boundary_review:{episode_id}",
            ):
                current = latest_record(state, key)
                if isinstance(current, dict) and type(current.get("version")) is int:
                    expected_refs.add((key, current["version"]))
        continuity_key = f"continuity_ledger:{scope}"
        continuity = latest_record(state, continuity_key)
        if isinstance(continuity, dict) and type(continuity.get("version")) is int:
            expected_refs.add((continuity_key, continuity["version"]))
        if record_dependency_refs(record) != expected_refs:
            errors.append(
                issue(
                    "batch_snapshot_sources_mismatch",
                    "批次连续性快照必须精确绑定当前批次剧本、逐集边界报告和连续性台账",
                )
            )
        required_state_fields = {
            "character_states": dict,
            "item_states": dict,
            "relationship_state": str,
            "knowledge_state": str,
            "unresolved_threads": list,
            "storyline_progress": str,
            "relative_time": str,
        }
        for state_name in ("opening_state", "closing_state"):
            state_payload = payload.get(state_name)
            if not isinstance(state_payload, dict):
                errors.append(issue("batch_snapshot_state_invalid", f"{state_name} 必须是对象"))
                continue
            for field, expected_type in required_state_fields.items():
                if not isinstance(state_payload.get(field), expected_type):
                    errors.append(
                        issue(
                            "batch_snapshot_state_field_invalid",
                            f"{state_name}.{field} 类型无效",
                            state=state_name,
                            field=field,
                        )
                    )

    elif artifact_kind == "cross_batch_continuity_review":
        if artifact_key != "cross_batch_continuity_review":
            errors.append(issue("cross_batch_review_key_invalid", "跨批连续性审核 key 必须无作用域"))
        ordered_batches = sorted(
            (
                (batch_id, batch_episode_ids(state, batch_id) or [])
                for batch_id in state.get("batches", {})
                if isinstance(batch_id, str)
            ),
            key=lambda item: int(item[1][0][1:]) if item[1] else 10**9,
        )
        expected_batch_ids = [batch_id for batch_id, episode_ids in ordered_batches if episode_ids]
        if payload.get("batch_ids") != expected_batch_ids:
            errors.append(issue("cross_batch_review_batches_mismatch", "跨批连续性审核 batch_ids 必须覆盖全部当前批次并按剧集顺序排列"))
        expected_refs: set[tuple[str, int]] = set()
        for batch_id in expected_batch_ids:
            key = f"batch_continuity_snapshot:{batch_id}"
            current = latest_record(state, key)
            if isinstance(current, dict) and type(current.get("version")) is int:
                expected_refs.add((key, current["version"]))
        if record_dependency_refs(record) != expected_refs:
            errors.append(issue("cross_batch_review_sources_mismatch", "跨批连续性审核必须精确绑定全部当前批次快照"))
        if not isinstance(payload.get("transitions"), list):
            errors.append(issue("cross_batch_review_transitions_invalid", "跨批连续性审核 transitions 必须是数组"))
        findings = payload.get("findings")
        if not isinstance(findings, list) or not findings:
            errors.append(issue("cross_batch_review_findings_invalid", "跨批连续性审核 findings 必须是非空数组"))
        if payload.get("conclusion") != "passed":
            errors.append(issue("cross_batch_review_conclusion_invalid", "跨批连续性审核结论必须为 passed"))

    elif artifact_kind == "source_corpus":
        source_ids = {
            item.get("source_id")
            for item in state.get("sources", [])
            if isinstance(item, dict) and isinstance(item.get("source_id"), str)
        }
        units = payload.get("source_units")
        if not isinstance(units, list) or not units:
            errors.append(issue("source_units_invalid", "原著语料库 source_units 必须是非空数组"))
            return errors
        seen_ids: set[str] = set()
        seen_ordinals: set[int] = set()
        for index, unit in enumerate(units):
            if not isinstance(unit, dict):
                errors.append(issue("source_unit_invalid", "原著单元必须是对象", unit_index=index))
                continue
            unit_id = unit.get("source_unit_id")
            ordinal = unit.get("ordinal")
            if not isinstance(unit_id, str) or not unit_id.strip():
                errors.append(issue("source_unit_id_invalid", "原著单元缺少 source_unit_id", unit_index=index))
            elif unit_id in seen_ids:
                errors.append(issue("source_unit_id_duplicate", f"原著单元 ID 重复：{unit_id}"))
            else:
                seen_ids.add(unit_id)
            if type(ordinal) is not int or ordinal < 1:
                errors.append(issue("source_unit_ordinal_invalid", "原著单元 ordinal 必须是大于0的整数", unit_index=index))
            elif ordinal in seen_ordinals:
                errors.append(issue("source_unit_ordinal_duplicate", f"原著单元 ordinal 重复：{ordinal}"))
            else:
                seen_ordinals.add(ordinal)
            if unit.get("source_id") not in source_ids:
                errors.append(issue("source_unit_source_unknown", "原著单元引用了未知 source_id", unit_index=index))
            if not isinstance(unit.get("source_locator"), str) or not unit["source_locator"].strip():
                errors.append(issue("source_unit_locator_invalid", "原著单元缺少可定位 source_locator", unit_index=index))
            content_path = path_from_record(project_path, unit.get("content_path"))
            if content_path is None or not content_path.is_file():
                errors.append(issue("source_unit_content_missing", "原著单元 content_path 无效或文件不存在", unit_index=index))
            else:
                expected_hash = unit.get("content_sha256")
                if not isinstance(expected_hash, str) or sha256_file(content_path) != expected_hash:
                    errors.append(issue("source_unit_content_hash_mismatch", "原著单元标准化文本散列不一致", unit_index=index))

    elif artifact_kind == "source_event_index":
        corpus = dependency_payload_of_type(project_path, state, record, "source_corpus")
        corpus_units = corpus.get("source_units") if isinstance(corpus, dict) else None
        expected_unit_ids = {
            item.get("source_unit_id")
            for item in corpus_units
            if isinstance(item, dict) and isinstance(item.get("source_unit_id"), str)
        } if isinstance(corpus_units, list) else set()
        units = payload.get("units")
        if not isinstance(units, list) or not units:
            errors.append(issue("event_units_invalid", "原著事件索引 units 必须是非空数组"))
            return errors
        legacy_granularity = (
            "upgrade_pending" not in payload
            and all(
                not isinstance(unit, dict) or "granularity" not in unit
                for unit in units
            )
        )
        upgrade_pending = payload.get("upgrade_pending", [])
        pending_ids: list[str] = []
        if not legacy_granularity:
            if not isinstance(upgrade_pending, list) or not all(
                isinstance(value, str) and value.strip()
                for value in upgrade_pending
            ):
                errors.append(
                    issue(
                        "event_upgrade_pending_invalid",
                        "原著事件索引 upgrade_pending 必须是 source_unit_id 字符串数组",
                    )
                )
            else:
                pending_ids = list(upgrade_pending)
        actual_unit_ids: list[str] = []
        chapter_summary_ids: set[str] = set()
        event_ids: set[str] = set()
        event_ordinals: set[int] = set()
        beat_ids: set[str] = set()
        schema_v2 = type(payload.get("schema_version")) is int and payload.get("schema_version") >= 2
        canonical_entity_ids: set[str] = set()
        if schema_v2:
            entities = payload.get("entities")
            if not isinstance(entities, list) or not entities:
                errors.append(issue("event_entities_missing", "schema v2 事件索引必须包含非空 canonical entities"))
            else:
                for entity_index, entity in enumerate(entities):
                    if not isinstance(entity, dict):
                        errors.append(issue("event_entity_invalid", "canonical entity 必须是对象", entity_index=entity_index))
                        continue
                    entity_id = entity.get("entity_id")
                    entity_type = entity.get("entity_type")
                    patterns = {
                        "character": r"(?:C\d{3,6}|CHAR-[A-Z0-9_.-]+)",
                        "location": r"(?:L\d{3,6}|LOC-[A-Z0-9_.-]+)",
                        "prop": r"(?:P\d{3,6}|PROP-[A-Z0-9_.-]+)",
                    }
                    pattern = patterns.get(entity_type)
                    if not isinstance(entity_id, str) or pattern is None or not re.fullmatch(pattern, entity_id):
                        errors.append(
                            issue(
                                "event_entity_id_invalid",
                                "entity_id 必须与 entity_type 匹配：character 使用 C001/CHAR-，location 使用 L001/LOC-，prop 使用 P001/PROP-",
                                entity_index=entity_index,
                                entity_id=entity_id,
                                entity_type=entity_type,
                            )
                        )
                    elif entity_id in canonical_entity_ids:
                        errors.append(
                            issue(
                                "event_entity_id_invalid",
                                "canonical entity_id 必须全局唯一",
                                entity_index=entity_index,
                                entity_id=entity_id,
                                entity_type=entity_type,
                            )
                        )
                    else:
                        canonical_entity_ids.add(entity_id)
                    if entity_type not in {"character", "location", "prop"}:
                        errors.append(issue("event_entity_type_invalid", "entity_type 只能为 character/location/prop", entity_index=entity_index))
                    if not isinstance(entity.get("canonical_name"), str) or not entity["canonical_name"].strip():
                        errors.append(issue("event_entity_name_missing", "canonical entity 缺少 canonical_name", entity_index=entity_index))
                    aliases = entity.get("aliases", [])
                    if not isinstance(aliases, list) or not all(isinstance(value, str) and value.strip() for value in aliases):
                        errors.append(issue("event_entity_aliases_invalid", "canonical entity aliases 必须是字符串数组", entity_index=entity_index))
        for index, unit in enumerate(units):
            if not isinstance(unit, dict):
                errors.append(issue("event_unit_invalid", "事件索引单元必须是对象", unit_index=index))
                continue
            unit_id = unit.get("source_unit_id")
            if isinstance(unit_id, str) and unit_id:
                actual_unit_ids.append(unit_id)
            else:
                errors.append(issue("event_unit_id_invalid", "事件索引单元缺少 source_unit_id", unit_index=index))
            granularity = unit.get("granularity", "unit_detail")
            if granularity not in {"unit_detail", "chapter_summary"}:
                errors.append(
                    issue(
                        "event_unit_granularity_invalid",
                        "事件索引 granularity 必须为 unit_detail 或 chapter_summary",
                        unit_index=index,
                    )
                )
            elif granularity == "chapter_summary" and isinstance(unit_id, str) and unit_id:
                chapter_summary_ids.add(unit_id)
            if not isinstance(unit.get("source_locator"), str) or not unit["source_locator"].strip():
                errors.append(issue("event_unit_locator_invalid", "事件索引单元缺少 source_locator", unit_index=index))
            status = unit.get("status")
            if status not in {"ready", "excluded", "failed"}:
                errors.append(issue("event_unit_status_invalid", "事件索引 status 必须为 ready、excluded 或 failed", unit_index=index))
            if status == "excluded" and (
                not isinstance(unit.get("exclusion_reason"), str) or not unit["exclusion_reason"].strip()
            ):
                errors.append(issue("event_unit_exclusion_reason_missing", "被排除原著单元必须说明 exclusion_reason", unit_index=index))
            if status == "failed":
                errors.append(issue("event_unit_failed", "原著事件提取仍有失败单元，不能确认", unit_index=index))
                if not isinstance(unit.get("error_reason"), str) or not unit["error_reason"].strip():
                    errors.append(issue("event_unit_error_reason_missing", "失败原著单元必须说明 error_reason", unit_index=index))
            events = unit.get("events")
            if not isinstance(events, list):
                errors.append(issue("event_records_invalid", "事件索引单元 events 必须是数组", unit_index=index))
                continue
            for event_index, event in enumerate(events):
                if not isinstance(event, dict):
                    errors.append(issue("event_record_invalid", "事件记录必须是对象", unit_index=index, event_index=event_index))
                    continue
                event_id = event.get("event_id")
                if not isinstance(event_id, str) or not event_id.strip():
                    errors.append(issue("event_id_invalid", "事件记录缺少 event_id", unit_index=index, event_index=event_index))
                elif event_id in event_ids:
                    errors.append(issue("event_id_duplicate", f"事件 ID 重复：{event_id}"))
                else:
                    event_ids.add(event_id)
                if schema_v2:
                    participants = event.get("participants")
                    if not isinstance(participants, list) or not all(
                        isinstance(value, str) and value.strip() for value in participants
                    ):
                        errors.append(issue("event_participants_invalid", "schema v2 事件 participants 必须是 canonical character ID 数组", unit_index=index, event_index=event_index))
                    else:
                        unknown_participants = sorted(set(participants) - canonical_entity_ids)
                        if unknown_participants:
                            errors.append(issue("event_participant_unknown", "事件引用了未登记的 canonical character ID", unit_index=index, event_index=event_index, unknown=unknown_participants))
                        non_character_ids = {
                            entity.get("entity_id")
                            for entity in payload.get("entities", [])
                            if isinstance(entity, dict) and entity.get("entity_type") != "character"
                        }
                        invalid_participants = sorted(set(participants) & non_character_ids)
                        if invalid_participants:
                            errors.append(issue("event_participant_type_invalid", "事件 participants 只能引用 character 实体", unit_index=index, event_index=event_index, invalid=invalid_participants))
                    event_ordinal = event.get("ordinal")
                    if type(event_ordinal) is not int or event_ordinal < 1 or event_ordinal in event_ordinals:
                        errors.append(issue("event_ordinal_invalid", "schema v2 事件 ordinal 必须是唯一正整数", unit_index=index, event_index=event_index))
                    else:
                        event_ordinals.add(event_ordinal)
                    beats = event.get("beats")
                    if not isinstance(beats, list) or not beats:
                        errors.append(issue("event_beats_missing", "schema v2 事件必须包含非空 beats", unit_index=index, event_index=event_index))
                        beats = []
                    local_ordinals: set[int] = set()
                    for beat_index, beat in enumerate(beats):
                        if not isinstance(beat, dict):
                            errors.append(issue("event_beat_invalid", "beat 必须是对象", unit_index=index, event_index=event_index, beat_index=beat_index))
                            continue
                        beat_id = beat.get("beat_id")
                        if not isinstance(beat_id, str) or not beat_id.strip() or beat_id in beat_ids:
                            errors.append(issue("event_beat_id_invalid", "beat_id 缺失或重复", unit_index=index, event_index=event_index, beat_index=beat_index))
                        else:
                            beat_ids.add(beat_id)
                        beat_ordinal = beat.get("ordinal")
                        if type(beat_ordinal) is not int or beat_ordinal < 1 or beat_ordinal in local_ordinals:
                            errors.append(issue("event_beat_ordinal_invalid", "beat ordinal 必须在事件内唯一且为正整数", unit_index=index, event_index=event_index, beat_index=beat_index))
                        else:
                            local_ordinals.add(beat_ordinal)
                        beat_refs = beat.get("source_refs")
                        if not isinstance(beat_refs, list) or not beat_refs or not all(isinstance(v, str) and v.strip() for v in beat_refs):
                            errors.append(issue("event_beat_source_refs_invalid", "beat 必须提供来源位置", unit_index=index, event_index=event_index, beat_index=beat_index))
                        protected = beat.get("protected_fact_ids", [])
                        if not isinstance(protected, list) or not all(isinstance(v, str) and v.strip() for v in protected):
                            errors.append(issue("event_beat_protected_facts_invalid", "protected_fact_ids 必须是字符串数组", unit_index=index, event_index=event_index, beat_index=beat_index))
                        required = beat.get("required_fact_ids")
                        if not isinstance(required, list) or not all(isinstance(v, str) and v.strip() for v in required):
                            errors.append(issue("event_beat_required_facts_invalid", "required_fact_ids 必须是字符串数组", unit_index=index, event_index=event_index, beat_index=beat_index))
                        story_time = beat.get("story_time")
                        if story_time is not None:
                            if not isinstance(story_time, dict) or type(story_time.get("day_index")) is not int or story_time.get("day_part") not in STORY_DAY_PARTS:
                                errors.append(issue("event_beat_story_time_invalid", "story_time 必须包含整数 day_index 和有效 day_part", unit_index=index, event_index=event_index, beat_index=beat_index))
                required_event_fields = (
                    ("summary",)
                    if granularity == "chapter_summary"
                    else ("summary", "cause", "action", "outcome", "state_change")
                )
                for field in required_event_fields:
                    if not isinstance(event.get(field), str) or not event[field].strip():
                        errors.append(issue("event_field_missing", f"事件记录缺少 {field}", unit_index=index, event_index=event_index, field=field))
                source_refs = event.get("source_refs")
                if not isinstance(source_refs, list) or not source_refs or not all(
                    isinstance(value, str) and value.strip() for value in source_refs
                ):
                    errors.append(issue("event_source_refs_invalid", "事件记录 source_refs 必须是非空字符串数组", unit_index=index, event_index=event_index))
        actual_set = set(actual_unit_ids)
        if len(actual_unit_ids) != len(actual_set) or actual_set != expected_unit_ids:
            errors.append(
                issue(
                    "event_unit_coverage_mismatch",
                    "原著事件索引必须与原著语料库逐单元一一对应，不能缺失、重复或多出",
                    missing=sorted(expected_unit_ids - actual_set),
                    extra=sorted(actual_set - expected_unit_ids),
                )
            )
        if not legacy_granularity and isinstance(upgrade_pending, list):
            pending_set = set(pending_ids)
            if (
                len(pending_ids) != len(pending_set)
                or pending_set != chapter_summary_ids
            ):
                errors.append(
                    issue(
                        "event_upgrade_pending_mismatch",
                        "upgrade_pending 必须无重复地逐项列出全部 chapter_summary 单元",
                        missing=sorted(chapter_summary_ids - pending_set),
                        extra=sorted(pending_set - chapter_summary_ids),
                    )
                )

        if schema_v2:
            if payload.get("content_contract_version") != 1:
                errors.append(issue("event_content_contract_upgrade_required", "schema v2 事件索引必须使用 content_contract_version=1"))
            errors.extend(validate_source_content_contract(project_path, corpus, payload))
            errors.extend(validate_fact_definition_contract(payload))
            source_texts: dict[str, str] = {}
            if isinstance(corpus_units, list):
                for source_unit in corpus_units:
                    if not isinstance(source_unit, dict):
                        continue
                    source_unit_id = source_unit.get("source_unit_id")
                    source_path = path_from_record(project_path, source_unit.get("content_path"))
                    if isinstance(source_unit_id, str) and source_path is not None and source_path.is_file():
                        source_texts[source_unit_id] = source_path.read_text(encoding="utf-8")
            errors.extend(validate_source_timeline_contract(payload, source_texts))
            episode_scopes = payload.get("episode_scopes")
            if not isinstance(episode_scopes, dict) or not episode_scopes:
                errors.append(issue("event_episode_scopes_missing", "schema v2 事件索引必须声明 episode_scopes"))
            else:
                for episode_id, scope in episode_scopes.items():
                    if not isinstance(episode_id, str) or not re.fullmatch(r"E\d{3,6}", episode_id):
                        errors.append(issue("event_episode_scope_id_invalid", "episode_scopes key 必须是规范集号", episode_id=episode_id))
                        continue
                    if not isinstance(scope, dict):
                        errors.append(issue("event_episode_scope_invalid", "episode_scope 必须是对象", episode_id=episode_id))
                        continue
                    allowed_ids = scope.get("allowed_beat_ids")
                    if (
                        not isinstance(allowed_ids, list)
                        or not allowed_ids
                        or len(allowed_ids) != len(set(allowed_ids))
                        or not all(isinstance(value, str) and value in beat_ids for value in allowed_ids)
                    ):
                        errors.append(issue("event_episode_scope_invalid", "episode_scope 必须声明无重复且全部存在的 allowed_beat_ids", episode_id=episode_id))
                        continue
                    beat_order = source_beat_index(payload)
                    allowed_orders = [beat_order[value]["order"] for value in allowed_ids]
                    if allowed_orders != sorted(allowed_orders):
                        errors.append(issue("event_episode_scope_order_invalid", "allowed_beat_ids 必须严格遵循原著顺序", episode_id=episode_id))
                    if scope.get("first_beat_id") != allowed_ids[0] or scope.get("last_beat_id") != allowed_ids[-1]:
                        errors.append(issue("event_episode_scope_bounds_mismatch", "episode_scope 首尾 beat 必须与 allowed_beat_ids 首尾一致", episode_id=episode_id))

    elif artifact_kind == "change_authorization":
        authorizations = payload.get("authorizations")
        if not isinstance(authorizations, list) or not authorizations:
            errors.append(issue("change_authorizations_invalid", "改编变更授权 authorizations 必须是非空数组"))
            return errors
        authorization_ids: set[str] = set()
        allowed_categories = {
            "named_character",
            "merge_character",
            "new_subplot",
            "new_relationship",
            "new_ability",
            "new_major_event",
            "reorder_key_event",
            "change_motivation",
            "change_choice",
            "change_cause",
            "change_outcome",
            "change_world_rule",
            "change_ending_nature",
            "hook_crisis",
        }
        for index, authorization in enumerate(authorizations):
            if not isinstance(authorization, dict):
                errors.append(issue("change_authorization_invalid", "每条改编变更授权必须是对象", authorization_index=index))
                continue
            authorization_id = authorization.get("authorization_id")
            if not isinstance(authorization_id, str) or not authorization_id.strip():
                errors.append(issue("change_authorization_id_invalid", "改编变更授权缺少 authorization_id", authorization_index=index))
            elif authorization_id in authorization_ids:
                errors.append(issue("change_authorization_id_duplicate", f"改编变更授权 ID 重复：{authorization_id}"))
            else:
                authorization_ids.add(authorization_id)
            if authorization.get("category") not in allowed_categories:
                errors.append(issue("change_authorization_category_invalid", "改编变更授权 category 无效", authorization_index=index))
            for field in (
                "approved_change",
                "rationale",
                "scope",
                "constraints",
                "user_confirmation_quote",
                "approved_by",
            ):
                if not isinstance(authorization.get(field), str) or not authorization[field].strip():
                    errors.append(issue("change_authorization_field_missing", f"改编变更授权缺少 {field}", authorization_index=index, field=field))

    elif artifact_kind == "adaptation_decision_ledger":
        event_index = dependency_payload_of_type(project_path, state, record, "source_event_index")
        event_units = event_index.get("units") if isinstance(event_index, dict) else None
        valid_source_units = {
            item.get("source_unit_id")
            for item in event_units
            if isinstance(item, dict) and isinstance(item.get("source_unit_id"), str)
        } if isinstance(event_units, list) else set()
        expected_episodes = project_expected_episodes(project_path, state)
        decisions = payload.get("decisions")
        if not isinstance(decisions, list) or not decisions:
            errors.append(issue("adaptation_decisions_invalid", "改编决策台账 decisions 必须是非空数组"))
            return errors
        authorization_by_id: dict[str, dict[str, Any]] = {}
        for dependency in record.get("depends_on", []):
            if not isinstance(dependency, dict) or not isinstance(dependency.get("artifact_key"), str):
                continue
            try:
                if artifact_type(dependency["artifact_key"]) != "change_authorization":
                    continue
            except ToolError:
                continue
            authorization_payload = dependency_payload_of_type(
                project_path, state, record, "change_authorization"
            )
            entries = authorization_payload.get("authorizations") if isinstance(authorization_payload, dict) else None
            if isinstance(entries, list):
                authorization_by_id.update(
                    {
                        entry["authorization_id"]: entry
                        for entry in entries
                        if isinstance(entry, dict)
                        and isinstance(entry.get("authorization_id"), str)
                    }
                )
        decision_ids: set[str] = set()
        for index, decision in enumerate(decisions):
            if not isinstance(decision, dict):
                errors.append(issue("adaptation_decision_invalid", "改编决策必须是对象", decision_index=index))
                continue
            decision_id = decision.get("decision_id")
            if not isinstance(decision_id, str) or not decision_id.strip():
                errors.append(issue("adaptation_decision_id_invalid", "改编决策缺少 decision_id", decision_index=index))
            elif decision_id in decision_ids:
                errors.append(issue("adaptation_decision_id_duplicate", f"改编决策 ID 重复：{decision_id}"))
            else:
                decision_ids.add(decision_id)
            operation = decision.get("operation")
            if operation not in ALLOWED_ADAPTATION_OPERATIONS:
                errors.append(issue("adaptation_operation_invalid", "改编操作类型无效", decision_index=index))
            source_unit_ids = decision.get("source_unit_ids")
            if not isinstance(source_unit_ids, list) or not all(
                isinstance(value, str) and value for value in source_unit_ids
            ):
                errors.append(issue("adaptation_source_units_invalid", "改编决策 source_unit_ids 必须是字符串数组", decision_index=index))
                source_unit_ids = []
            unknown_units = set(source_unit_ids) - valid_source_units
            if unknown_units:
                errors.append(issue("adaptation_source_unit_unknown", "改编决策引用未知原著单元", decision_index=index, unknown=sorted(unknown_units)))
            boundary_class = decision.get("boundary_class")
            change_level = decision.get("change_level")
            source_fact_change = decision.get("source_fact_change")
            if boundary_class not in {"source_based", "auto_allowed", "user_confirmation_required"}:
                errors.append(issue("adaptation_boundary_class_invalid", "改编决策 boundary_class 无效", decision_index=index))
            if change_level not in {"no_change", "expression_only", "story_fact_change"}:
                errors.append(issue("adaptation_change_level_invalid", "改编决策 change_level 无效", decision_index=index))
            if type(source_fact_change) is not bool:
                errors.append(issue("adaptation_source_fact_flag_invalid", "改编决策 source_fact_change 必须是布尔值", decision_index=index))
            if boundary_class == "source_based" and (
                change_level != "no_change" or source_fact_change is not False
            ):
                errors.append(issue("source_based_change_invalid", "原著保留项不得改变故事事实或伪装成表达新增", decision_index=index))
            if boundary_class == "auto_allowed" and (
                change_level != "expression_only" or source_fact_change is not False
            ):
                errors.append(issue("auto_change_alters_story_fact", "自动允许项只能增加表达，不能改变故事事实", decision_index=index))
            if not source_unit_ids and boundary_class != "user_confirmation_required":
                errors.append(issue("adaptation_source_unit_required", "没有原著依据的改编不能自动通过，必须绑定原著单元或用户授权", decision_index=index))
            if operation == "bridge_addition":
                for field in ("addition_basis", "purpose"):
                    if not isinstance(decision.get(field), str) or not decision[field].strip():
                        errors.append(issue("bridge_addition_field_missing", f"桥接新增缺少 {field}", decision_index=index, field=field))
                if decision.get("source_facts_unchanged") is not True:
                    errors.append(issue("bridge_addition_fact_guard_missing", "桥接新增必须声明 source_facts_unchanged: true", decision_index=index))
            target_ids = decision.get("target_episode_ids")
            if not isinstance(target_ids, list) or not target_ids or not all(
                isinstance(value, str) and re.fullmatch(r"E\d{3,6}", value) for value in target_ids
            ):
                errors.append(issue("adaptation_target_episodes_invalid", "改编决策 target_episode_ids 必须是非空规范集号数组", decision_index=index))
                target_ids = []
            if expected_episodes is not None and any(int(value[1:]) > expected_episodes for value in target_ids):
                errors.append(issue("adaptation_target_episode_out_of_range", "改编决策落点超出项目计划集数", decision_index=index))
            for field in ("rationale", "character_arc_impact", "continuity_impact"):
                if not isinstance(decision.get(field), str) or not decision[field].strip():
                    errors.append(issue("adaptation_decision_field_missing", f"改编决策缺少 {field}", decision_index=index, field=field))
            protected_facts = decision.get("protected_facts")
            if not isinstance(protected_facts, list):
                errors.append(issue("adaptation_protected_facts_invalid", "改编决策 protected_facts 必须是数组", decision_index=index))
            decision_status = decision.get("status")
            if boundary_class == "user_confirmation_required" or change_level == "story_fact_change" or source_fact_change is True:
                authorization_ref = decision.get("authorization_ref")
                if decision_status != "approved_addition":
                    errors.append(issue("adaptation_decision_unconfirmed", "改变故事事实或主要新增必须标记 approved_addition", decision_index=index))
                authorization = (
                    authorization_by_id.get(authorization_ref)
                    if isinstance(authorization_ref, str)
                    else None
                )
                if not isinstance(authorization, dict):
                    errors.append(issue("adaptation_authorization_missing", "需要用户确认的改编决策未绑定有效授权记录", decision_index=index))
                else:
                    expected_category = (
                        "reorder_key_event" if operation == "reorder" else operation
                    )
                    if authorization.get("category") != expected_category:
                        errors.append(issue("adaptation_authorization_category_mismatch", "改编决策类型与用户授权类别不一致", decision_index=index))
                if boundary_class != "user_confirmation_required" or change_level != "story_fact_change" or source_fact_change is not True:
                    errors.append(issue("adaptation_confirmation_class_mismatch", "获批的故事事实变更必须明确标记 user_confirmation_required、story_fact_change 和 source_fact_change: true", decision_index=index))
            elif decision_status != "accepted":
                errors.append(issue("adaptation_decision_unconfirmed", "自动允许的改编表达必须标记 accepted", decision_index=index))

    elif artifact_kind == "seedance_execution_plan":
        errors.extend(
            validate_seedance_execution_payload(
                project_path, state, artifact_key, record, payload
            )
        )

    elif artifact_kind == "genre_profile":
        errors.extend(
            validate_genre_profile_payload(
                project_path, state, artifact_key, record, payload
            )
        )

    elif artifact_kind == "model_capability_profile":
        errors.extend(
            validate_model_capability_profile_payload(
                project_path, state, artifact_key, record, payload
            )
        )

    elif artifact_kind == "ai_shot_plan":
        errors.extend(
            validate_ai_shot_plan_payload(
                project_path, state, artifact_key, record, payload
            )
        )

    elif artifact_kind == "ai_video_execution_plan":
        errors.extend(
            validate_ai_video_execution_payload(
                project_path, state, artifact_key, record, payload
            )
        )

    elif artifact_kind == "batch_delivery_review":
        scope = artifact_key.split(":", 1)[1] if ":" in artifact_key else ""
        batch_id = payload.get("batch_id")
        if not BATCH_ID_RE.fullmatch(scope) or batch_id != scope:
            errors.append(
                issue(
                    "batch_delivery_review_scope_invalid",
                    "批次交付审核的 key 范围与 batch_id 必须是同一个有效批次 ID",
                    artifact_key=artifact_key,
                )
            )
        required_keys = batch_delivery_input_keys(state, scope)
        if required_keys is None:
            errors.append(
                issue(
                    "batch_delivery_review_batch_missing",
                    f"批次交付审核引用的批次不存在或结构无效：{scope}",
                    artifact_key=artifact_key,
                )
            )
            required_keys = []
        expected_refs: set[tuple[str, int]] = set()
        for key in required_keys:
            current = latest_record(state, key)
            version = current.get("version") if isinstance(current, dict) else None
            if type(version) is not int:
                errors.append(
                    issue(
                        "batch_delivery_input_missing",
                        f"批次交付审核缺少当前输入：{key}",
                        artifact_key=artifact_key,
                    )
                )
            else:
                expected_refs.add((key, version))
        if dependency_refs != expected_refs:
            errors.append(
                issue(
                    "batch_delivery_sources_mismatch",
                    "批次交付审核必须精确绑定当前批次的全剧、批次、单集边界及制作交付输入",
                    artifact_key=artifact_key,
                    missing=sorted(expected_refs - dependency_refs),
                    extra=sorted(dependency_refs - expected_refs),
                )
            )
        findings = payload.get("findings")
        if not isinstance(findings, list) or not findings:
            errors.append(
                issue(
                    "batch_delivery_findings_invalid",
                    "批次交付审核 findings 必须是非空数组",
                    artifact_key=artifact_key,
                )
            )
            findings = []
        finding_ids: set[str] = set()
        has_blocked = False
        has_suspected = False
        for index, finding in enumerate(findings):
            if not isinstance(finding, dict):
                errors.append(issue("batch_delivery_finding_invalid", "批次交付审核 finding 必须是对象", finding_index=index))
                continue
            finding_id = finding.get("finding_id")
            if not isinstance(finding_id, str) or not finding_id.strip():
                errors.append(issue("batch_delivery_finding_id_invalid", "批次交付审核 finding 缺少 finding_id", finding_index=index))
            elif finding_id in finding_ids:
                errors.append(issue("batch_delivery_finding_id_duplicate", f"批次交付审核 finding_id 重复：{finding_id}"))
            else:
                finding_ids.add(finding_id)
            result = finding.get("result")
            if result not in {"passed", "suspected_overreach", "blocked"}:
                errors.append(issue("batch_delivery_result_invalid", "批次交付审核 result 必须为 passed、suspected_overreach 或 blocked", finding_index=index))
            if finding.get("category") != "delivery_boundary":
                errors.append(issue("batch_delivery_category_invalid", "批次交付审核 category 必须为 delivery_boundary", finding_index=index))
            for field in ("location", "description", "evidence"):
                if not isinstance(finding.get(field), str) or not finding[field].strip():
                    errors.append(issue("batch_delivery_field_missing", f"批次交付审核 finding 缺少 {field}", finding_index=index, field=field))
            if result == "passed":
                source_refs = finding.get("source_refs")
                if not isinstance(source_refs, list) or not source_refs or not all(
                    isinstance(value, str) and value.strip() for value in source_refs
                ):
                    errors.append(issue("batch_delivery_pass_source_missing", "批次交付审核通过项必须提供依据", finding_index=index))
            if result == "suspected_overreach":
                has_suspected = True
                errors.append(issue("batch_delivery_suspected_overreach", "批次交付审核存在 suspected_overreach，必须完成人工判断后重做审核", finding_index=index))
                if finding.get("human_judgment_required") is not True:
                    errors.append(issue("batch_delivery_human_gate_missing", "suspected_overreach 必须标记 human_judgment_required: true", finding_index=index))
            if result == "blocked":
                has_blocked = True
                errors.append(issue("batch_delivery_blocked", "批次交付审核存在 blocked，不能确认或打包", finding_index=index))
        expected_conclusion = (
            "blocked"
            if has_blocked
            else "needs_human_review"
            if has_suspected
            else "passed"
        )
        if payload.get("conclusion") != expected_conclusion:
            errors.append(
                issue(
                    "batch_delivery_conclusion_mismatch",
                    f"批次交付审核 conclusion 应为 {expected_conclusion}",
                    artifact_key=artifact_key,
                )
            )

    elif artifact_kind in {
        "series_boundary_review",
        "batch_boundary_review",
        "episode_boundary_review",
        "seedance_boundary_review",
        "ai_video_boundary_review",
    }:
        expected_target_type = {
            "series_boundary_review": "series_map",
            "batch_boundary_review": "batch_outline",
            "episode_boundary_review": "episode_script",
            "seedance_boundary_review": "seedance_execution_plan",
            "ai_video_boundary_review": "ai_shot_plan",
        }[artifact_kind]
        target_dependencies = [
            item
            for item in record.get("depends_on", [])
            if isinstance(item, dict)
            and isinstance(item.get("artifact_key"), str)
            and artifact_type(item["artifact_key"]) == expected_target_type
        ]
        if len(target_dependencies) != 1:
            errors.append(issue("boundary_target_dependency_invalid", "内容边界报告必须精确绑定一个当前层目标制品", artifact_key=artifact_key))
            target_ref = None
        else:
            target_ref = target_dependencies[0]
        review_target = payload.get("review_target")
        if not isinstance(review_target, dict) or target_ref is None or (
            review_target.get("artifact_key") != target_ref.get("artifact_key")
            or review_target.get("version") != target_ref.get("version")
        ):
            errors.append(issue("boundary_review_target_mismatch", "内容边界报告 review_target 与状态依赖不一致", artifact_key=artifact_key))
        automation_limitations = payload.get("automation_limitations")
        if not isinstance(automation_limitations, str) or not automation_limitations.strip():
            errors.append(issue("boundary_automation_limit_missing", "内容边界报告必须说明自动判断局限，不能声称百分之百正确", artifact_key=artifact_key))
        elif not any(
            marker in automation_limitations
            for marker in ("不能", "无法", "不保证", "可能", "局限", "人工")
        ):
            errors.append(issue("boundary_automation_overclaim", "自动边界检查必须明确局限或人工复核要求，不得声称百分之百正确", artifact_key=artifact_key))
        event_index = dependency_payload_of_type(project_path, state, record, "source_event_index")
        event_units = event_index.get("units") if isinstance(event_index, dict) else None
        valid_source_refs: set[str] = set()
        if isinstance(event_units, list):
            for unit in event_units:
                if not isinstance(unit, dict):
                    continue
                for value in (unit.get("source_unit_id"), unit.get("source_locator")):
                    if isinstance(value, str) and value.strip():
                        valid_source_refs.add(value)
                events = unit.get("events")
                if not isinstance(events, list):
                    continue
                for event in events:
                    if not isinstance(event, dict):
                        continue
                    event_id = event.get("event_id")
                    if isinstance(event_id, str) and event_id.strip():
                        valid_source_refs.add(event_id)
                    for value in event.get("source_refs", []):
                        if isinstance(value, str) and value.strip():
                            valid_source_refs.add(value)
        ledger = dependency_payload_of_type(project_path, state, record, "adaptation_decision_ledger")
        decisions = ledger.get("decisions") if isinstance(ledger, dict) else None
        decision_by_id = {
            item.get("decision_id"): item
            for item in decisions
            if isinstance(item, dict) and isinstance(item.get("decision_id"), str)
        } if isinstance(decisions, list) else {}
        findings = payload.get("findings")
        if not isinstance(findings, list) or not findings:
            errors.append(issue("boundary_findings_invalid", "内容边界报告 findings 必须是非空数组", artifact_key=artifact_key))
            findings = []
        finding_ids: set[str] = set()
        has_suspected = False
        has_blocked = False
        covered_semantic_categories: set[str] = set()
        required_ai_video_categories = {
            "source_fidelity",
            "character_scene_consistency",
            "production_feasibility",
            "screen_text_postproduction",
        }
        auto_allowed_categories = AUTO_ALLOWED_BOUNDARY_CATEGORIES
        confirmation_categories = {
            "named_character",
            "merge_character",
            "new_subplot",
            "new_relationship",
            "new_ability",
            "new_major_event",
            "reorder_key_event",
            "change_motivation",
            "change_choice",
            "change_cause",
            "change_outcome",
            "change_world_rule",
            "change_ending_nature",
            "hook_crisis",
        }
        hard_block_categories = {
            "major_character_change",
            "identity_change",
            "ability_change",
            "core_relationship_change",
            "motivation_change",
            "key_event_change",
            "causality_change",
            "world_rule_change",
            "ending_nature_change",
            "premature_knowledge_disclosure",
            "missing_source_or_authorization",
        }
        allowed_categories = {
            "source_fidelity",
            "character_scene_consistency",
            "production_feasibility",
            "screen_text_postproduction",
            *auto_allowed_categories,
            *confirmation_categories,
            *hard_block_categories,
        }
        for index, finding in enumerate(findings):
            if not isinstance(finding, dict):
                errors.append(issue("boundary_finding_invalid", "内容边界发现项必须是对象", finding_index=index))
                continue
            finding_id = finding.get("finding_id")
            if not isinstance(finding_id, str) or not finding_id.strip():
                errors.append(issue("boundary_finding_id_invalid", "内容边界发现项缺少 finding_id", finding_index=index))
            elif finding_id in finding_ids:
                errors.append(issue("boundary_finding_id_duplicate", f"内容边界发现项 ID 重复：{finding_id}"))
            else:
                finding_ids.add(finding_id)
            result = finding.get("result")
            if result not in {"passed", "approved_addition", "suspected_overreach", "blocked"}:
                errors.append(issue("boundary_result_invalid", "内容边界结果必须为 passed、approved_addition、suspected_overreach 或 blocked", finding_index=index))
            category = finding.get("category")
            if category not in allowed_categories:
                errors.append(issue("boundary_category_invalid", "内容边界发现项 category 无效", finding_index=index))
            if category in required_ai_video_categories and result == "passed":
                covered_semantic_categories.add(category)
            if category in hard_block_categories and result not in {"blocked", "suspected_overreach"}:
                errors.append(issue("boundary_hard_block_downgraded", "硬性阻断项不能判定为通过或已批准新增", finding_index=index))
            if category in confirmation_categories and result not in {"approved_addition", "blocked", "suspected_overreach"}:
                errors.append(issue("boundary_confirmation_bypassed", "需要用户确认的故事事实变更不能直接判定 passed", finding_index=index))
            if category in auto_allowed_categories and result == "approved_addition":
                errors.append(issue("boundary_expression_mislabeled", "只增加表达的自动允许项不应伪装成故事事实新增", finding_index=index))
            if result == "approved_addition" and category not in confirmation_categories:
                errors.append(issue("boundary_approved_category_invalid", "已批准新增必须属于需要用户确认的故事事实变更", finding_index=index))
            has_suspected = has_suspected or result == "suspected_overreach"
            has_blocked = has_blocked or result == "blocked"
            for field in ("location", "description", "evidence"):
                if not isinstance(finding.get(field), str) or not finding[field].strip():
                    errors.append(issue("boundary_finding_field_missing", f"内容边界发现项缺少 {field}", finding_index=index, field=field))
            source_refs = finding.get("source_refs")
            if result == "passed" and (
                not isinstance(source_refs, list)
                or not source_refs
                or not all(isinstance(value, str) and value.strip() for value in source_refs)
            ):
                errors.append(issue("boundary_pass_source_missing", "判定通过必须提供明确原著依据", finding_index=index))
            elif result == "passed":
                unknown_refs = sorted(set(source_refs) - valid_source_refs)
                if unknown_refs:
                    errors.append(issue("boundary_source_ref_unknown", "判定通过引用了事件索引中不存在的原著依据", finding_index=index, unknown=unknown_refs))
                if category in auto_allowed_categories:
                    expression_decision_ids = finding.get("decision_ids")
                    if not isinstance(expression_decision_ids, list) or not expression_decision_ids:
                        errors.append(issue("boundary_expression_decision_missing", "自动允许的表达变化必须绑定改编决策", finding_index=index))
                        expression_decision_ids = []
                    for decision_id in expression_decision_ids:
                        decision = decision_by_id.get(decision_id)
                        if (
                            not isinstance(decision, dict)
                            or decision.get("operation") != category
                            or decision.get("boundary_class") != "auto_allowed"
                            or decision.get("change_level") != "expression_only"
                            or decision.get("source_fact_change") is not False
                            or decision.get("status") != "accepted"
                        ):
                            errors.append(issue("boundary_expression_decision_invalid", "自动允许的表达变化未绑定同类型且不改变故事事实的有效决策", finding_index=index, decision_id=decision_id))
            if result == "approved_addition":
                decision_ids = finding.get("decision_ids")
                if not isinstance(decision_ids, list) or not decision_ids:
                    errors.append(issue("boundary_approved_decision_missing", "已批准新增必须绑定改编决策", finding_index=index))
                    decision_ids = []
                for decision_id in decision_ids:
                    decision = decision_by_id.get(decision_id)
                    if not isinstance(decision, dict) or decision.get("status") != "approved_addition" or not decision.get("authorization_ref"):
                        errors.append(issue("boundary_approved_authorization_missing", "已批准新增未绑定有效用户授权记录", finding_index=index, decision_id=decision_id))
                        continue
                    expected_category = (
                        "reorder_key_event"
                        if decision.get("operation") == "reorder"
                        else decision.get("operation")
                    )
                    if category != expected_category:
                        errors.append(issue("boundary_approved_category_mismatch", "边界发现项类别与获批改编决策类型不一致", finding_index=index, decision_id=decision_id))
                expected_authorizations = {
                    decision_by_id[decision_id].get("authorization_ref")
                    for decision_id in decision_ids
                    if isinstance(decision_by_id.get(decision_id), dict)
                    and isinstance(decision_by_id[decision_id].get("authorization_ref"), str)
                }
                authorization_refs = finding.get("authorization_refs")
                actual_authorizations = set(authorization_refs) if isinstance(authorization_refs, list) and all(
                    isinstance(value, str) and value.strip() for value in authorization_refs
                ) else set()
                if not expected_authorizations or actual_authorizations != expected_authorizations:
                    errors.append(issue("boundary_authorization_refs_mismatch", "已批准新增必须精确列出改编决策绑定的用户授权记录", finding_index=index))
            if result == "suspected_overreach" and finding.get("human_judgment_required") is not True:
                errors.append(issue("boundary_human_gate_missing", "疑似越界必须标记 human_judgment_required: true", finding_index=index))
        if artifact_kind == "ai_video_boundary_review":
            missing_semantic_categories = sorted(required_ai_video_categories - covered_semantic_categories)
            if missing_semantic_categories:
                errors.append(issue(
                    "boundary_semantic_coverage_missing",
                    "AI分镜边界报告未覆盖全部核心语义检查，不能以 passed 形成假全绿",
                    missing=missing_semantic_categories,
                ))
        target_validation_errors: list[dict[str, Any]] = []
        if artifact_kind == "ai_video_boundary_review" and isinstance(target_ref, dict):
            target_key = target_ref.get("artifact_key")
            target_version = target_ref.get("version")
            target_record = next((
                item for item in state.get("artifacts", {}).get(target_key, [])
                if isinstance(item, dict) and item.get("version") == target_version
            ), None) if isinstance(target_key, str) else None
            if isinstance(target_record, dict):
                target_validation_errors = validate_structured_development_artifact(
                    project_path, state, target_key, target_record
                )
            else:
                target_validation_errors = [issue("boundary_target_missing", "审核目标制品不存在")]
            if target_validation_errors:
                errors.append(issue(
                    "boundary_target_validation_failed",
                    "AI分镜目标仍有机器校验错误，边界报告不能判定 passed",
                    target_errors=target_validation_errors,
                ))
        expected_conclusion = computed_boundary_conclusion(target_validation_errors, findings)
        if payload.get("conclusion") != expected_conclusion:
            errors.append(issue("boundary_conclusion_mismatch", f"内容边界报告结论应为 {expected_conclusion}", artifact_key=artifact_key))

    elif artifact_kind in {"series_plan_review", "pilot_review"}:
        expected_target = "series_plan" if artifact_kind == "series_plan_review" else "pilot"
        if payload.get("review_target") != expected_target:
            errors.append(issue("development_review_target_invalid", f"审核报告 review_target 必须为 {expected_target}", artifact_key=artifact_key))
        review_issues = payload.get("issues")
        if not isinstance(review_issues, list):
            errors.append(issue("development_review_issues_invalid", "审核报告 issues 必须是数组", artifact_key=artifact_key))
            review_issues = []
        issue_ids: set[str] = set()
        open_blocking = False
        for index, review_issue in enumerate(review_issues):
            if not isinstance(review_issue, dict):
                errors.append(issue("development_review_issue_invalid", "审核问题必须是对象", issue_index=index))
                continue
            issue_id = review_issue.get("issue_id")
            if not isinstance(issue_id, str) or not issue_id.strip():
                errors.append(issue("development_review_issue_id_invalid", "审核问题缺少 issue_id", issue_index=index))
            elif issue_id in issue_ids:
                errors.append(issue("development_review_issue_id_duplicate", f"审核问题 ID 重复：{issue_id}"))
            else:
                issue_ids.add(issue_id)
            severity = review_issue.get("severity")
            status = review_issue.get("status")
            if severity not in {"blocking", "major", "minor"}:
                errors.append(issue("development_review_severity_invalid", "审核问题 severity 无效", issue_index=index))
            if status not in {"open", "resolved", "waived"}:
                errors.append(issue("development_review_status_invalid", "审核问题 status 无效", issue_index=index))
            if severity == "blocking" and status == "open":
                open_blocking = True
            for field in ("location", "evidence", "suggestion"):
                if not isinstance(review_issue.get(field), str) or not review_issue[field].strip():
                    errors.append(issue("development_review_field_missing", f"审核问题缺少 {field}", issue_index=index, field=field))
            if status == "waived" and not all(
                isinstance(review_issue.get(field), str) and review_issue[field].strip()
                for field in ("waiver_id", "reason", "approved_by")
            ):
                errors.append(issue("development_review_waiver_invalid", "豁免问题必须包含 waiver_id、reason、approved_by", issue_index=index))
        if open_blocking:
            errors.append(issue("development_review_blocker_open", "审核报告仍有未关闭阻断项"))
        if payload.get("conclusion") != "passed":
            errors.append(issue("development_review_conclusion_invalid", "审核报告结论必须为 passed"))
    return errors


def validate_state(project_path: Path) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    path = project_path / STATE_FILENAME
    if not path.is_file():
        return {
            "valid": False,
            "project": str(project_path),
            "errors": [issue("state_missing", f"缺少 {STATE_FILENAME}")],
            "warnings": [],
            "summary": {"error_count": 1, "warning_count": 0},
        }
    try:
        with path.open("r", encoding="utf-8") as handle:
            state = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "valid": False,
            "project": str(project_path),
            "errors": [issue("state_unreadable", f"无法读取状态：{exc}")],
            "warnings": [],
            "summary": {"error_count": 1, "warning_count": 0},
        }
    if not isinstance(state, dict):
        errors.append(issue("state_not_object", "状态顶层必须是 JSON 对象"))
        state = {}

    if type(state.get("schema_version")) is not int or state.get("schema_version") != SCHEMA_VERSION:
        errors.append(
            issue(
                "schema_version_invalid",
                f"schema_version 应为 {SCHEMA_VERSION}，实际为 {state.get('schema_version')!r}",
            )
        )
    project_id = state.get("project_id")
    try:
        uuid.UUID(project_id)
    except (TypeError, ValueError, AttributeError):
        errors.append(issue("project_id_invalid", "project_id 必须是有效 UUID"))
    for field in ("name", "created_at", "updated_at", "current_stage"):
        if not isinstance(state.get(field), str) or not state[field]:
            errors.append(issue("field_invalid", f"{field} 必须是非空字符串", field=field))

    directories = state.get("directories")
    if not isinstance(directories, list):
        errors.append(issue("directories_invalid", "directories 必须是数组"))
    else:
        for expected in PROJECT_DIRECTORIES:
            if expected in OPTIONAL_PROJECT_DIRECTORIES and expected not in directories:
                continue
            if expected not in directories:
                errors.append(issue("directory_untracked", f"状态未记录目录：{expected}"))
            if not (project_path / expected).is_dir():
                errors.append(issue("directory_missing", f"项目目录缺失：{expected}"))

    stages = state.get("stages")
    if not isinstance(stages, dict):
        errors.append(issue("stages_invalid", "stages 必须是对象"))
    else:
        for key, label in STAGES.items():
            stage = stages.get(key)
            if not isinstance(stage, dict):
                errors.append(issue("stage_missing", f"缺少阶段：{key}", stage=key))
                continue
            if stage.get("label") != label:
                errors.append(issue("stage_label_invalid", f"阶段 {key} 标签应为“{label}”", stage=key))
            if stage.get("status") not in STAGE_STATUSES:
                errors.append(issue("stage_status_invalid", f"阶段 {key} 状态无效", stage=key))
        if state.get("current_stage") not in STAGES:
            errors.append(issue("current_stage_invalid", "current_stage 不是已知阶段"))

    sources = state.get("sources")
    if not isinstance(sources, list):
        errors.append(issue("sources_invalid", "sources 必须是数组"))
        sources = []
    elif not sources:
        warnings.append(issue("no_sources", "项目尚未导入原始内容"))
    for index, source in enumerate(sources):
        if not isinstance(source, dict):
            errors.append(issue("source_invalid", "源记录必须是对象", source_index=index))
            continue
        for field in ("source_id", "original_path", "stored_path", "sha256", "imported_at"):
            if not isinstance(source.get(field), str) or not source[field]:
                errors.append(
                    issue("source_field_invalid", f"源记录缺少 {field}", source_index=index, field=field)
                )
        stored = path_from_record(project_path, source.get("stored_path"))
        if stored is None:
            errors.append(issue("source_path_unsafe", "源文件路径越界或无效", source_index=index))
        elif not stored.is_file():
            errors.append(issue("source_file_missing", f"源文件不存在：{source.get('stored_path')}", source_index=index))
        elif isinstance(source.get("sha256"), str) and sha256_file(stored) != source["sha256"]:
            errors.append(issue("source_hash_mismatch", f"源文件已变更：{source.get('stored_path')}", source_index=index))

    source_policy = state.get("source_policy")
    if source_policy is not None:
        if not isinstance(source_policy, dict):
            errors.append(issue("source_policy_invalid", "source_policy 必须是对象"))
        else:
            try:
                normalized_policy = build_source_policy(
                    source_policy.get("source_kind"),
                    source_policy.get("official_review_enabled"),
                    source_policy.get("official_url"),
                )
                if source_policy != normalized_policy:
                    raise ToolError("source_policy 字段不完整或 content_authority 不是 uploaded_files")
            except ToolError as exc:
                errors.append(issue("source_policy_invalid", str(exc)))

    episodes_hint = state.get("expected_episodes_hint")
    if episodes_hint is not None and (
        type(episodes_hint) is not int or episodes_hint < 1
    ):
        errors.append(
            issue(
                "expected_episodes_hint_invalid",
                "expected_episodes_hint 必须是大于0的整数或 null",
            )
        )

    batches = state.get("batches", {})
    if not isinstance(batches, dict):
        errors.append(issue("batches_invalid", "batches 必须是对象"))
        batches = {}
    assigned_episodes: dict[str, str] = {}
    expected_episodes = project_expected_episodes(project_path, state)
    for batch_id, batch in batches.items():
        if not isinstance(batch_id, str) or not BATCH_ID_RE.fullmatch(batch_id):
            errors.append(issue("batch_id_invalid", f"批次 ID 无效：{batch_id!r}"))
            continue
        if not isinstance(batch, dict):
            errors.append(issue("batch_invalid", f"批次 {batch_id} 必须是对象"))
            continue
        if batch.get("batch_id") != batch_id:
            errors.append(issue("batch_id_mismatch", f"批次 {batch_id} 的 batch_id 不一致"))
        episode_ids = batch.get("episode_ids")
        if (
            not isinstance(episode_ids, list)
            or not episode_ids
            or not all(
                isinstance(value, str) and EPISODE_ID_RE.fullmatch(value)
                for value in episode_ids
            )
        ):
            errors.append(issue("batch_episode_ids_invalid", f"批次 {batch_id} 的 episode_ids 无效"))
            episode_ids = []
        elif len(episode_ids) != len(set(episode_ids)):
            errors.append(issue("batch_episode_ids_duplicate", f"批次 {batch_id} 存在重复集号"))
        for episode_id in episode_ids:
            if expected_episodes is not None and int(episode_id[1:]) > expected_episodes:
                errors.append(
                    issue(
                        "batch_episode_out_of_range",
                        f"批次 {batch_id} 的 {episode_id} 超出项目规格",
                    )
                )
            previous_batch = assigned_episodes.get(episode_id)
            if previous_batch is not None and previous_batch != batch_id:
                errors.append(
                    issue(
                        "batch_episode_overlap",
                        f"{episode_id} 同时属于批次 {previous_batch} 和 {batch_id}",
                    )
                )
            assigned_episodes[episode_id] = batch_id
        for field in ("defined_at", "note"):
            if not isinstance(batch.get(field), str):
                errors.append(
                    issue(
                        "batch_field_invalid",
                        f"批次 {batch_id} 的 {field} 必须是字符串",
                        batch_id=batch_id,
                        field=field,
                    )
                )

    artifacts = state.get("artifacts")
    if not isinstance(artifacts, dict):
        errors.append(issue("artifacts_invalid", "artifacts 必须是对象"))
        artifacts = {}
    artifact_versions: set[tuple[str, int]] = set()
    for key, records in artifacts.items():
        if not isinstance(key, str):
            errors.append(issue("artifact_key_invalid", "制品 key 必须是字符串"))
            continue
        try:
            expected_type = artifact_type(key)
        except ToolError as exc:
            errors.append(issue("artifact_key_invalid", str(exc), artifact_key=key))
            expected_type = None
        if not isinstance(records, list) or not records:
            errors.append(issue("artifact_versions_invalid", "制品版本必须是非空数组", artifact_key=key))
            continue
        seen_versions: set[int] = set()
        for record_index, record in enumerate(records):
            location = {"artifact_key": key, "record_index": record_index}
            if not isinstance(record, dict):
                errors.append(issue("artifact_record_invalid", "制品版本必须是对象", **location))
                continue
            version = record.get("version")
            if type(version) is not int or version < 1:
                errors.append(issue("artifact_version_invalid", "制品版本必须是正整数", **location))
            elif version in seen_versions:
                errors.append(issue("artifact_version_duplicate", f"制品版本重复：{version}", **location))
            else:
                seen_versions.add(version)
                artifact_versions.add((key, version))
            if expected_type and record.get("artifact_type") != expected_type:
                errors.append(issue("artifact_type_invalid", f"制品类型应为 {expected_type}", **location))
            if record.get("status") not in ARTIFACT_STATUSES:
                errors.append(issue("artifact_status_invalid", "制品状态无效", **location))
            stored = path_from_record(project_path, record.get("path"))
            if stored is None:
                errors.append(issue("artifact_path_unsafe", "制品路径越界或无效", **location))
            elif not stored.is_file():
                errors.append(issue("artifact_file_missing", f"制品文件不存在：{record.get('path')}", **location))
            elif isinstance(record.get("sha256"), str) and sha256_file(stored) != record["sha256"]:
                errors.append(issue("artifact_hash_mismatch", f"制品文件已变更：{record.get('path')}", **location))
            elif record.get("size_bytes") != stored.stat().st_size:
                errors.append(issue("artifact_size_mismatch", f"制品文件大小已变更：{record.get('path')}", **location))
            for field in ("sha256", "registered_at"):
                if not isinstance(record.get(field), str) or not record[field]:
                    errors.append(issue("artifact_field_invalid", f"制品记录缺少 {field}", field=field, **location))
            if not isinstance(record.get("depends_on"), list):
                errors.append(issue("artifact_dependencies_invalid", "depends_on 必须是数组", **location))

    # 在全部制品版本汇总后再检查引用，避免受 JSON 键顺序影响。
    for key, records in artifacts.items():
        if not isinstance(records, list):
            continue
        for record in records:
            if not isinstance(record, dict) or not isinstance(record.get("depends_on"), list):
                continue
            for dependency in record["depends_on"]:
                if not isinstance(dependency, dict):
                    errors.append(issue("artifact_dependency_invalid", "依赖项必须是对象", artifact_key=key))
                    continue
                reference = (dependency.get("artifact_key"), dependency.get("version"))
                if reference not in artifact_versions:
                    errors.append(
                        issue(
                            "artifact_dependency_missing",
                            f"依赖制品不存在：{reference[0]}@{reference[1]}",
                            artifact_key=key,
                            version=record.get("version"),
                        )
                    )

    for key in artifacts:
        if not isinstance(key, str):
            continue
        current = latest_record(state, key)
        if current is None:
            continue
        if current.get("status") == "confirmed" and not confirmed_record_is_usable(
            state, key, current, project_path
        ):
            errors.append(
                issue(
                    "confirmed_artifact_unusable",
                    "已确认制品缺少有效审批、必需上游，或依赖的不是当前已确认版本",
                    artifact_key=key,
                    version=current.get("version"),
                )
            )

    # 规范开发制品即使已确认也持续复核其内容与依赖，防止旧项目或状态手工修改绕过审批门禁。
    for artifact_kind in sorted(STRUCTURED_DEVELOPMENT_TYPES):
        for key, record in latest_records_of_type(state, artifact_kind):
            if record.get("status") not in {"awaiting_approval", "confirmed"}:
                continue
            errors.extend(
                validate_structured_development_artifact(
                    project_path, state, key, record
                )
            )

    for key, record in latest_records_of_type(state, "series_map"):
        if record.get("status") not in {"awaiting_approval", "confirmed"}:
            continue
        payload = load_json_artifact_payload(project_path, key, record, errors)
        if payload is not None:
            errors.extend(
                validate_series_map_payload(
                    state,
                    payload,
                    project_expected_episodes(project_path, state),
                )
            )
            warnings.extend(series_map_payload_warnings(payload))

    for key, record in latest_records_of_type(state, "batch_outline"):
        if record.get("status") not in {"awaiting_approval", "confirmed"}:
            continue
        errors.extend(scoped_batch_outline_source_errors(state, key, record))

    # 只校验仍在流转中的最新版分集剧本；失效和历史版本保留追溯但不阻断当前项目。
    handoff_target_duration = project_target_duration_seconds(project_path, state)
    handoff_chars_per_second = dialogue_chars_per_second(
        project_duration_policy(project_path, state)
    )
    for key, record in latest_records_of_type(state, "episode_script"):
        if record.get("status") not in {"draft", "awaiting_approval", "confirmed"}:
            continue
        script_path = path_from_record(project_path, record.get("path"))
        if script_path is None or not script_path.is_file():
            continue
        script_result = validate_script_file(
            script_path,
            target_duration_seconds=handoff_target_duration,
            chars_per_second=handoff_chars_per_second,
        )
        warnings.extend(
            {
                **item,
                "artifact_key": key,
                "version": record.get("version"),
            }
            for item in script_result.get("warnings", [])
            if isinstance(item, dict)
        )
        if not script_result["valid"]:
            errors.append(
                issue(
                    "episode_script_invalid",
                    "当前分集剧本结构校验失败",
                    artifact_key=key,
                    version=record.get("version"),
                    script_errors=script_result["errors"],
                )
            )
            continue
        expected_scope = key.split(":", 1)[1] if ":" in key else ""
        heading_number = (script_result.get("episode") or {}).get("number_value")
        if (
            not re.fullmatch(r"E\d{3,6}", expected_scope, re.IGNORECASE)
            or not isinstance(heading_number, int)
            or int(expected_scope[1:]) != heading_number
        ):
            errors.append(
                issue(
                    "episode_script_key_mismatch",
                    "分集剧本制品 key 与文件中的集号不一致",
                    artifact_key=key,
                    version=record.get("version"),
                    heading_number=heading_number,
                )
            )

    approvals = state.get("approvals")
    if not isinstance(approvals, list):
        errors.append(issue("approvals_invalid", "approvals 必须是数组"))
    else:
        for index, approval in enumerate(approvals):
            if not isinstance(approval, dict):
                errors.append(issue("approval_invalid", "审批记录必须是对象", approval_index=index))
                continue
            reference = (approval.get("artifact_key"), approval.get("version"))
            if reference not in artifact_versions:
                errors.append(issue("approval_target_missing", f"审批对应制品不存在：{reference[0]}@{reference[1]}", approval_index=index))
            for field in ("approval_id", "approved_at", "approved_by"):
                if not isinstance(approval.get(field), str) or not approval[field]:
                    errors.append(issue("approval_field_invalid", f"审批记录缺少 {field}", approval_index=index, field=field))

    for field in ("history",):
        if not isinstance(state.get(field), list):
            errors.append(issue("field_invalid", f"{field} 必须是数组", field=field))

    return {
        "valid": not errors,
        "project": str(project_path),
        "errors": errors,
        "warnings": warnings,
        "summary": {
            "error_count": len(errors),
            "warning_count": len(warnings),
            "source_count": len(sources),
            "artifact_key_count": len(artifacts),
            "artifact_version_count": len(artifact_versions),
        },
        "generation_policy": {
            "target_duration_seconds": project_target_duration_seconds(project_path, state),
            "duration_source": project_duration_source(project_path, state),
            "tolerance_ratio": duration_tolerance_ratio(project_duration_policy(project_path, state)),
            "recommended_shot_units": DEFAULT_RECOMMENDED_SHOT_UNITS,
        },
    }


def command_validate_project(args: argparse.Namespace) -> int:
    project_path = Path(args.project).expanduser().resolve()
    result = validate_state(project_path)
    print_json(result)
    return 0 if result["valid"] else 1


def latest_records_of_type(
    state: dict[str, Any], artifact_kind: str
) -> list[tuple[str, dict[str, Any]]]:
    results: list[tuple[str, dict[str, Any]]] = []
    artifacts = state.get("artifacts", {})
    if not isinstance(artifacts, dict):
        return results
    for key in sorted(artifacts):
        if not isinstance(key, str):
            continue
        try:
            if artifact_type(key) != artifact_kind:
                continue
        except ToolError:
            continue
        record = latest_record(state, key)
        if record is not None:
            results.append((key, record))
    return results


def validate_handoff_state(
    project_path: Path,
    expected_episodes: int | None = None,
    require_final_package: bool = False,
) -> dict[str, Any]:
    project_result = validate_state(project_path)
    errors = list(project_result.get("errors", []))
    warnings = list(project_result.get("warnings", []))
    selected: list[dict[str, Any]] = []
    if expected_episodes is None:
        errors.append(
            issue(
                "expected_episodes_required",
                "制作交付校验必须明确 expected_episodes，不能在不知道总集数时声称全剧完整",
            )
        )
    elif type(expected_episodes) is not int or expected_episodes < 1:
        errors.append(issue("expected_episodes_invalid", "expected_episodes 必须大于0"))
    if errors:
        return {
            "ready": False,
            "project": str(project_path),
            "errors": errors,
            "warnings": warnings,
            "selected_artifacts": selected,
            "summary": {
                "error_count": len(errors),
                "warning_count": len(warnings),
                "confirmed_episode_count": 0,
            },
        }

    _, state = load_state(project_path)
    selected_refs: set[tuple[str, int]] = set()
    specified_episode_count: int | None = None

    project_spec_candidates = [
        (key, record)
        for key, record in latest_records_of_type(state, "project_spec")
        if key == "project_spec"
        and confirmed_record_is_usable(state, key, record, project_path)
    ]
    if len(project_spec_candidates) == 1:
        project_spec_key, project_spec_record = project_spec_candidates[0]
        project_spec_path = path_from_record(project_path, project_spec_record.get("path"))
        try:
            project_spec_payload = (
                json.loads(project_spec_path.read_text(encoding="utf-8-sig"))
                if project_spec_path and project_spec_path.suffix.lower() == ".json"
                else None
            )
        except (OSError, UnicodeError, json.JSONDecodeError):
            project_spec_payload = None
        if not isinstance(project_spec_payload, dict):
            errors.append(
                issue(
                    "project_spec_json_required",
                    "制作交付使用的项目规格必须是规范 JSON",
                    artifact_key=project_spec_key,
                )
            )
        else:
            if type(project_spec_payload.get("schema_version")) is not int or project_spec_payload.get("schema_version") != 1:
                errors.append(issue("project_spec_schema_invalid", "项目规格 schema_version 必须为1"))
            if project_spec_payload.get("project_id") != state.get("project_id"):
                errors.append(issue("project_spec_project_mismatch", "项目规格 project_id 不一致"))
            specified_episode_count = project_spec_payload.get("expected_episodes")
            rights_mode = project_spec_payload.get("rights_mode", DEFAULT_RIGHTS_MODE)
            if not isinstance(rights_mode, str) or rights_mode not in RIGHTS_MODES:
                errors.append(
                    issue(
                        "project_spec_rights_mode_invalid",
                        f"项目规格 rights_mode 非法：{rights_mode!r}；"
                        f"只允许 {'/'.join(RIGHTS_MODES)}，缺省字段按 owned 语义处理",
                    )
                )
            rights_note = project_spec_payload.get("rights_note")
            if rights_note is not None and not isinstance(rights_note, str):
                errors.append(
                    issue(
                        "project_spec_rights_note_invalid",
                        "项目规格 rights_note 必须是字符串（记录授权范围）",
                    )
                )
            for problem in duration_policy_issues(project_spec_payload):
                errors.append(
                    issue("project_spec_duration_invalid", f"项目规格时长契约非法：{problem}")
                )
            if type(specified_episode_count) is not int or specified_episode_count < 1:
                errors.append(
                    issue(
                        "project_spec_episode_count_invalid",
                        "项目规格 expected_episodes 必须是大于0的整数",
                    )
                )
            elif specified_episode_count != expected_episodes:
                errors.append(
                    issue(
                        "expected_episodes_mismatch",
                        "命令参数 expected_episodes 与已确认项目规格不一致",
                        project_spec=specified_episode_count,
                        requested=expected_episodes,
                    )
                )

    series_map_candidates = [
        (key, record)
        for key, record in latest_records_of_type(state, "series_map")
        if key == "series_map"
        and confirmed_record_is_usable(state, key, record, project_path)
    ]
    if len(series_map_candidates) == 1:
        series_map_key, series_map_record = series_map_candidates[0]
        series_map_path = path_from_record(project_path, series_map_record.get("path"))
        try:
            series_map_payload = (
                json.loads(series_map_path.read_text(encoding="utf-8-sig"))
                if series_map_path and series_map_path.suffix.lower() == ".json"
                else None
            )
        except (OSError, UnicodeError, json.JSONDecodeError):
            series_map_payload = None
        if not isinstance(series_map_payload, dict):
            errors.append(
                issue(
                    "series_map_json_required",
                    "制作交付使用的全剧分集地图必须是规范 JSON",
                    artifact_key=series_map_key,
                )
            )
        else:
            errors.extend(
                validate_series_map_payload(
                    state,
                    series_map_payload,
                    specified_episode_count or expected_episodes,
                )
            )
            warnings.extend(series_map_payload_warnings(series_map_payload))

    def select(key: str, record: dict[str, Any]) -> None:
        reference = (key, record.get("version"))
        if type(reference[1]) is not int or reference in selected_refs:
            return
        selected_refs.add(reference)
        selected.append(
            {
                "artifact_key": key,
                "artifact_type": record.get("artifact_type"),
                "version": record.get("version"),
                "path": record.get("path"),
                "sha256": record.get("sha256"),
            }
        )

    def approved_and_current(key: str, record: dict[str, Any]) -> bool:
        return confirmed_record_is_usable(state, key, record, project_path)

    singleton_types = {
        "project_spec",
        "source_corpus",
        "source_event_index",
        "story_facts",
        "adaptation_profile",
        "adaptation_bible",
        "adaptation_decision_ledger",
        "series_map",
        "series_boundary_review",
        "series_plan_review",
        "pilot_review",
        "character_roster",
        "scene_catalog",
        "prop_costume_ledger",
        "dialogue_cue_sheet",
        "continuity_ledger",
        "quality_report",
        "production_readiness_report",
    }
    for required_type in HANDOFF_REQUIRED_TYPES:
        candidates = [
            (key, record)
            for key, record in latest_records_of_type(state, required_type)
            if (
                key == required_type
                if required_type in singleton_types
                else True
            )
            and approved_and_current(key, record)
        ]
        if not candidates:
            errors.append(
                issue(
                    "handoff_artifact_missing",
                    f"缺少已确认制品：{ARTIFACT_TYPES[required_type]}",
                    artifact_type=required_type,
                )
            )
            continue
        if required_type in singleton_types and len(candidates) != 1:
            errors.append(
                issue(
                    "handoff_artifact_count_invalid",
                    f"{ARTIFACT_TYPES[required_type]}必须恰有一个已确认最新版，实际为 {len(candidates)}",
                    artifact_type=required_type,
                )
            )
            continue
        for key, record in candidates:
            select(key, record)

    # 没有故事事实新增时可以不存在授权记录；一旦存在当前有效授权，就必须随
    # 内部交付包一起保存，确保 approved_addition 可以追溯到用户确认。
    for key, record in latest_records_of_type(state, "change_authorization"):
        if key == "change_authorization" and approved_and_current(key, record):
            select(key, record)

    confirmed_episodes = {
        key: record
        for key, record in latest_records_of_type(state, "episode_script")
        if approved_and_current(key, record)
    }
    required_episode_keys = {
        f"episode_script:E{number:03d}" for number in range(1, expected_episodes + 1)
    }
    for key in sorted(required_episode_keys):
        record = confirmed_episodes.get(key)
        if record is None:
            errors.append(
                issue(
                    "episode_not_confirmed",
                    f"缺少已确认分集剧本：{key.split(':', 1)[1]}",
                    episode_id=key.split(":", 1)[1],
                )
            )
        else:
            select(key, record)
    for key in sorted(set(confirmed_episodes) - required_episode_keys):
        errors.append(
            issue(
                "episode_unexpected",
                f"存在预期集数之外或 key 不规范的已确认分集剧本：{key}",
                artifact_key=key,
            )
        )

    if require_final_package:
        manifest_candidates = [
            (key, record)
            for key, record in latest_records_of_type(state, "delivery_manifest")
            if key == "delivery_manifest" and approved_and_current(key, record)
        ]
        if not manifest_candidates:
            errors.append(issue("delivery_manifest_missing", "缺少已确认的交付清单"))
        for key, record in manifest_candidates:
            select(key, record)
        final_candidates = [
            (key, record)
            for key, record in latest_records_of_type(state, "final_package")
            if key == "final_package" and approved_and_current(key, record)
        ]
        if not final_candidates:
            errors.append(issue("final_package_missing", "缺少已确认的制作就绪交付包"))
        for key, record in final_candidates:
            select(key, record)

    breakdown_result = validate_breakdowns_state(
        project_path,
        expected_episodes=expected_episodes,
        allow_awaiting=False,
    )
    errors.extend(breakdown_result.get("errors", []))
    warnings.extend(breakdown_result.get("warnings", []))

    continuity_candidates = [
        (key, record)
        for key, record in latest_records_of_type(state, "continuity_ledger")
        if key == "continuity_ledger" and approved_and_current(key, record)
    ]
    if len(continuity_candidates) == 1:
        continuity_key, continuity_record = continuity_candidates[0]
        expected_continuity_episodes = {
            key: record
            for key, record in confirmed_episodes.items()
            if key in required_episode_keys
        }
        errors.extend(
            validate_continuity_ledger_file(
                project_path,
                state,
                continuity_key,
                continuity_record,
                expected_continuity_episodes,
            )
        )

    quality_waiver_ids: set[str] = set()
    quality_candidates = [
        (key, record)
        for key, record in latest_records_of_type(state, "quality_report")
        if key == "quality_report" and approved_and_current(key, record)
    ]
    if len(quality_candidates) == 1:
        quality_key, quality_record = quality_candidates[0]
        quality_path = path_from_record(project_path, quality_record.get("path"))
        try:
            quality_payload = (
                json.loads(quality_path.read_text(encoding="utf-8-sig"))
                if quality_path and quality_path.suffix.lower() == ".json"
                else None
            )
        except (OSError, UnicodeError, json.JSONDecodeError):
            quality_payload = None
        if not isinstance(quality_payload, dict):
            errors.append(
                issue(
                    "quality_report_json_required",
                    "质检报告必须是规范 JSON，才能核验阻断项",
                    artifact_key=quality_key,
                )
            )
        else:
            if type(quality_payload.get("schema_version")) is not int or quality_payload.get("schema_version") != 1:
                errors.append(issue("quality_schema_invalid", "质检报告 schema_version 必须为1"))
            if quality_payload.get("project_id") != state.get("project_id"):
                errors.append(issue("quality_project_mismatch", "质检报告 project_id 不一致"))
            if quality_payload.get("conclusion") != "passed":
                errors.append(issue("quality_conclusion_invalid", "质检报告结论必须为 passed"))
            quality_sources = quality_payload.get("generated_from")
            actual_quality_sources = {
                (item.get("artifact_key"), item.get("version"))
                for item in quality_sources
                if isinstance(item, dict)
            } if isinstance(quality_sources, list) else set()
            quality_binding_types = {
                "episode_script",
                "character_roster",
                "scene_catalog",
                "prop_costume_ledger",
                "dialogue_cue_sheet",
                "continuity_ledger",
            }
            expected_quality_sources = {
                (item["artifact_key"], item["version"])
                for item in selected
                if item.get("artifact_type") in quality_binding_types
            }
            if actual_quality_sources != expected_quality_sources:
                errors.append(
                    issue(
                        "quality_source_versions_mismatch",
                        "质检报告未精确绑定当前全部分集剧本版本",
                    )
                )
            state_quality_sources = {
                (item.get("artifact_key"), item.get("version"))
                for item in quality_record.get("depends_on", [])
                if isinstance(item, dict)
            }
            if state_quality_sources != expected_quality_sources:
                errors.append(
                    issue(
                        "quality_state_dependencies_mismatch",
                        "质检报告的状态依赖必须精确绑定当前剧本、提取表和连续性版本",
                    )
                )
            quality_issues = quality_payload.get("issues")
            if not isinstance(quality_issues, list):
                errors.append(issue("quality_issues_invalid", "质检报告 issues 必须是数组"))
            else:
                for index, item in enumerate(quality_issues):
                    if not isinstance(item, dict):
                        errors.append(
                            issue(
                                "quality_issue_invalid",
                                "质检报告中的每个 issue 必须是对象",
                                issue_index=index,
                            )
                        )
                        continue
                    if not isinstance(item.get("blocking"), bool):
                        errors.append(
                            issue(
                                "quality_issue_blocking_invalid",
                                "质检 issue 的 blocking 必须是布尔值",
                                issue_index=index,
                            )
                        )
                    if item.get("status") not in {"open", "resolved", "waived"}:
                        errors.append(
                            issue(
                                "quality_issue_status_invalid",
                                "质检 issue 的 status 必须为 open、resolved 或 waived",
                                issue_index=index,
                            )
                        )
                    if item.get("status") == "waived":
                        waiver_id = item.get("waiver_id")
                        if not isinstance(waiver_id, str) or not waiver_id:
                            errors.append(
                                issue(
                                    "quality_issue_waiver_missing",
                                    "被豁免的质检 issue 必须绑定 waiver_id",
                                    issue_index=index,
                                )
                            )
                        else:
                            quality_waiver_ids.add(waiver_id)
                unresolved = [
                    item
                    for item in quality_issues
                    if isinstance(item, dict)
                    and item.get("blocking") is True
                    and item.get("status") not in {"resolved", "waived"}
                ]
                if unresolved:
                    errors.append(
                        issue(
                            "quality_blockers_present",
                            "质检报告仍有未处理阻断项",
                            count=len(unresolved),
                        )
                    )

    readiness_candidates = [
        (key, record)
        for key, record in latest_records_of_type(state, "production_readiness_report")
        if key == "production_readiness_report"
        and approved_and_current(key, record)
    ]
    if len(readiness_candidates) != 1:
        errors.append(
            issue(
                "readiness_report_count_invalid",
                f"制作就绪复核报告必须恰有一个已确认最新版，实际为 {len(readiness_candidates)}",
            )
        )
    else:
        readiness_key, readiness_record = readiness_candidates[0]
        readiness_path = path_from_record(project_path, readiness_record.get("path"))
        try:
            readiness_payload = json.loads(
                readiness_path.read_text(encoding="utf-8-sig")
            ) if readiness_path and readiness_path.suffix.lower() == ".json" else None
        except (OSError, UnicodeError, json.JSONDecodeError):
            readiness_payload = None
        if not isinstance(readiness_payload, dict):
            errors.append(
                issue(
                    "readiness_report_json_required",
                    "制作就绪复核报告必须是规范 JSON",
                    artifact_key=readiness_key,
                )
            )
        else:
            if type(readiness_payload.get("schema_version")) is not int or readiness_payload.get("schema_version") != 1:
                errors.append(issue("readiness_schema_invalid", "制作就绪复核报告 schema_version 必须为1"))
            if readiness_payload.get("project_id") != state.get("project_id"):
                errors.append(issue("readiness_project_mismatch", "制作就绪复核报告 project_id 不一致"))
            if readiness_payload.get("conclusion") != "ready":
                errors.append(issue("readiness_conclusion_invalid", "制作就绪复核结论必须为 ready"))
            checks = readiness_payload.get("checks")
            required_checks = (
                "script_structure",
                "semantic_quality",
                "episode_coverage",
                "breakdown_traceability",
                "continuity",
            )
            if not isinstance(checks, dict):
                errors.append(issue("readiness_checks_invalid", "制作就绪复核 checks 必须是对象"))
            else:
                failed_checks = [name for name in required_checks if checks.get(name) != "passed"]
                if failed_checks:
                    errors.append(
                        issue(
                            "readiness_checks_incomplete",
                            "制作就绪复核的必需检查未全部通过",
                            checks=failed_checks,
                        )
                    )
            bound_sources = {
                (item.get("artifact_key"), item.get("version"))
                for item in readiness_payload.get("generated_from", [])
                if isinstance(item, dict)
            }
            binding_types = {
                "episode_script",
                "character_roster",
                "scene_catalog",
                "prop_costume_ledger",
                "dialogue_cue_sheet",
                "continuity_ledger",
                "quality_report",
            }
            expected_bindings = {
                (item["artifact_key"], item["version"])
                for item in selected
                if item.get("artifact_type") in binding_types
            }
            if bound_sources != expected_bindings:
                errors.append(
                    issue(
                        "readiness_bindings_incomplete",
                        "制作就绪复核报告必须精确绑定当前剧本、提取表、连续性和质检版本",
                        missing=sorted(expected_bindings - bound_sources),
                        extra=sorted(bound_sources - expected_bindings),
                    )
                )
            readiness_state_sources = {
                (item.get("artifact_key"), item.get("version"))
                for item in readiness_record.get("depends_on", [])
                if isinstance(item, dict)
            }
            if readiness_state_sources != expected_bindings:
                errors.append(
                    issue(
                        "readiness_state_dependencies_mismatch",
                        "制作就绪复核的状态依赖必须精确绑定当前交付输入",
                    )
                )
            blockers = readiness_payload.get("unresolved_blockers")
            if not isinstance(blockers, list) or blockers:
                errors.append(issue("readiness_blockers_present", "制作就绪复核仍有未处理阻断项"))
            runtime_verification = readiness_payload.get("runtime_verification")
            runtime_status = (
                runtime_verification.get("status")
                if isinstance(runtime_verification, dict)
                else None
            )
            if runtime_status not in {"measured", "not_measured"}:
                errors.append(issue("runtime_status_invalid", "runtime_verification.status 必须为 measured 或 not_measured"))
            waivers = readiness_payload.get("waivers")
            if not isinstance(waivers, list):
                errors.append(issue("readiness_waivers_invalid", "制作就绪复核 waivers 必须是数组"))
            else:
                readiness_waiver_ids: set[str] = set()
                for index, waiver in enumerate(waivers):
                    if not isinstance(waiver, dict) or not all(
                        isinstance(waiver.get(field), str) and waiver[field]
                        for field in ("waiver_id", "reason", "approved_by")
                    ):
                        errors.append(
                            issue(
                                "readiness_waiver_invalid",
                                "每条豁免必须包含 waiver_id、reason、approved_by",
                                waiver_index=index,
                            )
                        )
                    else:
                        readiness_waiver_ids.add(waiver["waiver_id"])
                if not quality_waiver_ids.issubset(readiness_waiver_ids):
                    errors.append(
                        issue(
                            "readiness_waiver_bindings_incomplete",
                            "制作就绪复核未登记质检报告中的全部豁免",
                            missing=sorted(quality_waiver_ids - readiness_waiver_ids),
                        )
                    )

    warnings.append(
        issue(
            "semantic_review_required",
            "此命令校验制品、版本、状态和剧集覆盖；内容审美与语义质量仍以已确认质检报告为准",
        )
    )
    return {
        "ready": not errors,
        "project": str(project_path),
        "expected_episodes": expected_episodes,
        "errors": errors,
        "warnings": warnings,
        "selected_artifacts": selected,
        "summary": {
            "error_count": len(errors),
            "warning_count": len(warnings),
            "confirmed_episode_count": len(confirmed_episodes),
            "selected_artifact_count": len(selected),
            "breakdown_valid": breakdown_result.get("valid", False),
        },
    }


def validate_batch_handoff_state(
    project_path: Path,
    batch_id: str,
) -> dict[str, Any]:
    project_result = validate_state(project_path)
    errors = list(project_result.get("errors", []))
    warnings = list(project_result.get("warnings", []))
    selected: list[dict[str, Any]] = []
    try:
        _, state = load_state(project_path)
    except ToolError as exc:
        errors.append(issue("state_unreadable", str(exc)))
        state = {}
    episode_ids = batch_episode_ids(state, batch_id)
    if episode_ids is None:
        errors.append(issue("batch_missing", f"批次不存在或结构无效：{batch_id}"))
    if errors:
        return {
            "ready": False,
            "project": str(project_path),
            "batch_id": batch_id,
            "episode_ids": episode_ids or [],
            "errors": errors,
            "warnings": warnings,
            "selected_artifacts": selected,
            "summary": {
                "error_count": len(errors),
                "warning_count": len(warnings),
                "confirmed_episode_count": 0,
                "selected_artifact_count": 0,
                "breakdown_valid": False,
            },
        }

    required_keys = batch_delivery_input_keys(state, batch_id) or []
    for key in required_keys:
        record = latest_record(state, key)
        if record is None or not confirmed_record_is_usable(
            state, key, record, project_path
        ):
            errors.append(
                issue(
                    "batch_handoff_artifact_missing",
                    f"批次交付缺少当前已确认制品：{key}",
                    artifact_key=key,
                )
            )
            continue
        selected.append(
            {
                "artifact_key": key,
                "artifact_type": record.get("artifact_type"),
                "version": record.get("version"),
                "path": record.get("path"),
                "sha256": record.get("sha256"),
            }
        )

    review_key = f"batch_delivery_review:{batch_id}"
    review_record = latest_record(state, review_key)
    if review_record is None or not confirmed_record_is_usable(
        state, review_key, review_record, project_path
    ):
        errors.append(
            issue(
                "batch_delivery_review_missing",
                "批次交付必须有精确绑定当前输入且结论为 passed 的已确认审核报告",
                artifact_key=review_key,
            )
        )
    else:
        selected.append(
            {
                "artifact_key": review_key,
                "artifact_type": review_record.get("artifact_type"),
                "version": review_record.get("version"),
                "path": review_record.get("path"),
                "sha256": review_record.get("sha256"),
            }
        )

    breakdown_result = validate_breakdowns_state(
        project_path,
        allow_awaiting=False,
        batch_id=batch_id,
    )
    errors.extend(breakdown_result.get("errors", []))
    warnings.extend(breakdown_result.get("warnings", []))

    episode_records = {
        key: latest_record(state, key)
        for key in (f"episode_script:{episode_id}" for episode_id in episode_ids)
    }
    usable_episode_records = {
        key: record
        for key, record in episode_records.items()
        if isinstance(record, dict)
        and confirmed_record_is_usable(state, key, record, project_path)
    }
    continuity_key = f"continuity_ledger:{batch_id}"
    continuity_record = latest_record(state, continuity_key)
    if isinstance(continuity_record, dict):
        errors.extend(
            validate_continuity_ledger_file(
                project_path,
                state,
                continuity_key,
                continuity_record,
                usable_episode_records,
            )
        )

    def load_delivery_json(key: str, label: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        record = latest_record(state, key)
        path = path_from_record(project_path, record.get("path")) if isinstance(record, dict) else None
        try:
            payload = (
                json.loads(path.read_text(encoding="utf-8-sig"))
                if path is not None and path.suffix.lower() == ".json"
                else None
            )
        except (OSError, UnicodeError, json.JSONDecodeError):
            payload = None
        if not isinstance(payload, dict):
            errors.append(issue("batch_report_json_required", f"{label}必须是规范 JSON", artifact_key=key))
            return record, None
        if payload.get("schema_version") != 1:
            errors.append(issue("batch_report_schema_invalid", f"{label} schema_version 必须为1", artifact_key=key))
        if payload.get("project_id") != state.get("project_id"):
            errors.append(issue("batch_report_project_mismatch", f"{label} project_id 不一致", artifact_key=key))
        return record, payload

    quality_key = f"quality_report:{batch_id}"
    quality_record, quality_payload = load_delivery_json(quality_key, "批次质检报告")
    quality_source_keys = [
        *[f"episode_script:{episode_id}" for episode_id in episode_ids],
        *[f"{kind}:{batch_id}" for kind in BATCH_BREAKDOWN_TYPES],
    ]
    quality_refs = {
        (key, latest_record(state, key).get("version"))
        for key in quality_source_keys
        if latest_record(state, key) is not None
    }
    quality_waiver_ids: set[str] = set()
    if isinstance(quality_record, dict) and isinstance(quality_payload, dict):
        if quality_payload.get("conclusion") != "passed":
            errors.append(issue("quality_conclusion_invalid", "批次质检报告结论必须为 passed"))
        if payload_generated_refs(quality_payload)[1] != quality_refs:
            errors.append(issue("quality_source_versions_mismatch", "批次质检报告未精确绑定当前批次剧本与制作提取版本"))
        if record_dependency_refs(quality_record) != quality_refs:
            errors.append(issue("quality_state_dependencies_mismatch", "批次质检报告状态依赖未精确绑定当前批次输入"))
        quality_issues = quality_payload.get("issues")
        if not isinstance(quality_issues, list):
            errors.append(issue("quality_issues_invalid", "批次质检报告 issues 必须是数组"))
        else:
            for index, item in enumerate(quality_issues):
                if not isinstance(item, dict):
                    errors.append(issue("quality_issue_invalid", "批次质检 issue 必须是对象", issue_index=index))
                    continue
                if not isinstance(item.get("blocking"), bool):
                    errors.append(issue("quality_issue_blocking_invalid", "批次质检 issue 的 blocking 必须是布尔值", issue_index=index))
                status = item.get("status")
                if status not in {"open", "resolved", "waived"}:
                    errors.append(issue("quality_issue_status_invalid", "批次质检 issue 状态无效", issue_index=index))
                if item.get("blocking") is True and status not in {"resolved", "waived"}:
                    errors.append(issue("quality_blockers_present", "批次质检仍有未处理阻断项", issue_index=index))
                if status == "waived":
                    waiver_id = item.get("waiver_id")
                    if isinstance(waiver_id, str) and waiver_id:
                        quality_waiver_ids.add(waiver_id)
                    else:
                        errors.append(issue("quality_issue_waiver_missing", "批次质检豁免项必须绑定 waiver_id", issue_index=index))

    readiness_key = f"production_readiness_report:{batch_id}"
    readiness_record, readiness_payload = load_delivery_json(
        readiness_key, "批次制作就绪复核报告"
    )
    readiness_refs = set(quality_refs)
    if isinstance(quality_record, dict) and type(quality_record.get("version")) is int:
        readiness_refs.add((quality_key, quality_record["version"]))
    if isinstance(readiness_record, dict) and isinstance(readiness_payload, dict):
        if readiness_payload.get("conclusion") != "ready":
            errors.append(issue("readiness_conclusion_invalid", "批次制作就绪复核结论必须为 ready"))
        checks = readiness_payload.get("checks")
        required_checks = (
            "script_structure",
            "semantic_quality",
            "episode_coverage",
            "breakdown_traceability",
            "continuity",
        )
        if not isinstance(checks, dict) or any(
            checks.get(name) != "passed" for name in required_checks
        ):
            errors.append(issue("readiness_checks_incomplete", "批次制作就绪复核的必需检查未全部通过"))
        if payload_generated_refs(readiness_payload)[1] != readiness_refs:
            errors.append(issue("readiness_bindings_incomplete", "批次制作就绪复核未精确绑定当前交付输入"))
        if record_dependency_refs(readiness_record) != readiness_refs:
            errors.append(issue("readiness_state_dependencies_mismatch", "批次制作就绪复核状态依赖未精确绑定当前交付输入"))
        blockers = readiness_payload.get("unresolved_blockers")
        if not isinstance(blockers, list) or blockers:
            errors.append(issue("readiness_blockers_present", "批次制作就绪复核仍有未处理阻断项"))
        runtime = readiness_payload.get("runtime_verification")
        if not isinstance(runtime, dict) or runtime.get("status") not in {"measured", "not_measured"}:
            errors.append(issue("runtime_status_invalid", "批次 runtime_verification.status 无效"))
        waivers = readiness_payload.get("waivers")
        readiness_waiver_ids = {
            item.get("waiver_id")
            for item in waivers
            if isinstance(item, dict) and isinstance(item.get("waiver_id"), str)
        } if isinstance(waivers, list) else set()
        if not isinstance(waivers, list):
            errors.append(issue("readiness_waivers_invalid", "批次制作就绪复核 waivers 必须是数组"))
        if not quality_waiver_ids.issubset(readiness_waiver_ids):
            errors.append(issue("readiness_waiver_bindings_incomplete", "批次制作就绪复核未登记全部质检豁免"))

    warnings.append(
        issue(
            "semantic_review_required",
            "批次校验核验制品、版本、边界门禁和批内覆盖；内容审美仍以已确认质检报告为准",
        )
    )
    return {
        "ready": not errors,
        "project": str(project_path),
        "batch_id": batch_id,
        "episode_ids": episode_ids,
        "errors": errors,
        "warnings": warnings,
        "selected_artifacts": selected,
        "summary": {
            "error_count": len(errors),
            "warning_count": len(warnings),
            "confirmed_episode_count": len(usable_episode_records),
            "selected_artifact_count": len(selected),
            "breakdown_valid": breakdown_result.get("valid", False),
        },
    }


def validate_series_handoff_state(
    project_path: Path,
    expected_episodes: int,
) -> dict[str, Any]:
    project_result = validate_state(project_path)
    errors = list(project_result.get("errors", []))
    warnings = list(project_result.get("warnings", []))
    selected: list[dict[str, Any]] = []
    if type(expected_episodes) is not int or expected_episodes < 1:
        errors.append(issue("expected_episodes_invalid", "expected_episodes 必须大于0"))
    try:
        _, state = load_state(project_path)
    except ToolError as exc:
        errors.append(issue("state_unreadable", str(exc)))
        state = {}
    specified = project_expected_episodes(project_path, state)
    if specified is None:
        errors.append(issue("project_expected_episodes_unknown", "无法从项目规格读取 expected_episodes"))
    elif specified != expected_episodes:
        errors.append(
            issue(
                "expected_episodes_mismatch",
                "全剧汇总参数与项目规格总集数不一致",
                specified=specified,
                requested=expected_episodes,
            )
        )

    batches = state.get("batches", {})
    ordered_batches = sorted(
        (
            (batch_id, batch_episode_ids(state, batch_id) or [])
            for batch_id in batches
            if isinstance(batch_id, str)
        ),
        key=lambda item: int(item[1][0][1:]) if item[1] else 10**9,
    ) if isinstance(batches, dict) else []
    actual_episode_ids: list[str] = [
        episode_id for _, episode_ids in ordered_batches for episode_id in episode_ids
    ]
    required_episode_ids = {
        f"E{number:03d}" for number in range(1, expected_episodes + 1)
    }
    actual_set = set(actual_episode_ids)
    if (
        not ordered_batches
        or len(actual_episode_ids) != len(actual_set)
        or actual_set != required_episode_ids
    ):
        errors.append(
            issue(
                "series_batch_coverage_invalid",
                "全剧汇总的批次必须无重叠地精确覆盖 E001...EN",
                missing=sorted(required_episode_ids - actual_set),
                extra=sorted(actual_set - required_episode_ids),
            )
        )

    def select_current(key: str, error_code: str, message: str) -> dict[str, Any] | None:
        record = latest_record(state, key)
        if record is None or not confirmed_record_is_usable(state, key, record, project_path):
            errors.append(issue(error_code, message, artifact_key=key))
            return None
        selected.append(
            {
                "artifact_key": key,
                "artifact_type": record.get("artifact_type"),
                "version": record.get("version"),
                "path": record.get("path"),
                "sha256": record.get("sha256"),
            }
        )
        return record

    for key in (
        "project_spec",
        "adaptation_profile",
        "adaptation_bible",
        "adaptation_decision_ledger",
        "series_map",
        "series_boundary_review",
        "series_plan_review",
    ):
        select_current(
            key,
            "series_global_artifact_missing",
            f"全剧汇总缺少当前已确认全局制品：{key}",
        )

    batch_ids: list[str] = []
    for batch_id, episode_ids in ordered_batches:
        if not episode_ids:
            continue
        batch_ids.append(batch_id)
        manifest_key = f"batch_delivery_manifest:{batch_id}"
        package_key = f"batch_package:{batch_id}"
        snapshot_key = f"batch_continuity_snapshot:{batch_id}"
        manifest_record = select_current(
            manifest_key,
            "series_batch_manifest_missing",
            f"全剧汇总缺少当前已确认批次清单：{manifest_key}",
        )
        select_current(
            package_key,
            "series_batch_package_missing",
            f"全剧汇总缺少当前已确认批次包：{package_key}",
        )
        select_current(
            snapshot_key,
            "series_batch_snapshot_missing",
            f"全剧汇总缺少当前已确认连续性快照：{snapshot_key}",
        )
        if isinstance(manifest_record, dict):
            path = path_from_record(project_path, manifest_record.get("path"))
            try:
                manifest_payload = json.loads(path.read_text(encoding="utf-8-sig")) if path else None
            except (OSError, UnicodeError, json.JSONDecodeError):
                manifest_payload = None
            if (
                not isinstance(manifest_payload, dict)
                or manifest_payload.get("batch_id") != batch_id
                or manifest_payload.get("episode_ids") != episode_ids
            ):
                errors.append(
                    issue(
                        "series_batch_manifest_scope_mismatch",
                        "批次清单的 batch_id 或 episode_ids 与项目批次定义不一致",
                        artifact_key=manifest_key,
                    )
                )

    review = select_current(
        "cross_batch_continuity_review",
        "cross_batch_review_missing",
        "全剧汇总缺少当前已确认且通过的跨批连续性审核",
    )
    if isinstance(review, dict):
        review_errors = validate_structured_development_artifact(
            project_path, state, "cross_batch_continuity_review", review
        )
        errors.extend(review_errors)

    return {
        "ready": not errors,
        "project": str(project_path),
        "expected_episodes": expected_episodes,
        "batch_ids": batch_ids,
        "errors": errors,
        "warnings": warnings,
        "selected_artifacts": selected,
        "summary": {
            "error_count": len(errors),
            "warning_count": len(warnings),
            "batch_count": len(batch_ids),
            "episode_count": len(actual_set),
            "selected_artifact_count": len(selected),
        },
    }


def command_validate_handoff(args: argparse.Namespace) -> int:
    project_path = Path(args.project).expanduser().resolve()
    if args.series:
        result = validate_series_handoff_state(project_path, args.expected_episodes)
    else:
        result = validate_handoff_state(
            project_path,
            expected_episodes=args.expected_episodes,
            require_final_package=args.require_final_package,
        )
        result.setdefault("warnings", []).append(
            issue(
                "legacy_full_handoff_deprecated",
                "v0.8 保留旧全剧校验仅用于兼容；新项目应使用 --batch 和 --series",
            )
        )
    print_json(result)
    return 0 if result["ready"] else 1


def package_filename(key: str, version: int, source_name: str) -> str:
    safe_key = re.sub(r"[^A-Za-z0-9_.-]+", "_", key).strip("_") or "artifact"
    return f"{safe_key}_V{version}_{source_name}"


def command_build_handoff(args: argparse.Namespace) -> int:
    project_path = Path(args.project).expanduser().resolve()
    batch_id = args.batch.upper() if args.batch is not None else None
    series_mode = bool(args.series)
    if batch_id is not None and args.expected_episodes is not None:
        raise ToolError("--batch 不能与 --expected-episodes 同时使用")
    if series_mode and args.expected_episodes is None:
        raise ToolError("--series 必须同时提供 --expected-episodes")
    if batch_id is None and not series_mode and args.expected_episodes is None:
        raise ToolError("必须提供 --batch、--series 或兼容模式 --expected-episodes")
    if series_mode:
        validation = validate_series_handoff_state(
            project_path, args.expected_episodes
        )
        manifest_key = "series_delivery_manifest"
        manifest_type = "series_delivery_manifest"
        package_key = "final_package"
        package_type = "final_package"
        manifest_package_type = "series_batch_aggregate_package"
        default_output_name = "全剧批次汇总包"
        manifest_note = "由 build-handoff --series 生成的全剧批次汇总清单"
        package_note = "由 build-handoff --series 生成的全剧批次汇总包"
    elif batch_id is not None:
        validation = validate_batch_handoff_state(project_path, batch_id)
        manifest_key = f"batch_delivery_manifest:{batch_id}"
        manifest_type = "batch_delivery_manifest"
        package_key = f"batch_package:{batch_id}"
        package_type = "batch_package"
        manifest_package_type = "batch_production_ready_script_package"
        default_output_name = f"{batch_id}_批次制作就绪剧本包"
        manifest_note = "由 build-handoff 生成的批次交付清单"
        package_note = "由 build-handoff 生成的批次制作就绪包"
    else:
        validation = validate_handoff_state(
            project_path,
            expected_episodes=args.expected_episodes,
            require_final_package=False,
        )
        manifest_key = "delivery_manifest"
        manifest_type = "delivery_manifest"
        package_key = "final_package"
        package_type = "final_package"
        manifest_package_type = "production_ready_script_package"
        default_output_name = "制作就绪剧本包"
        manifest_note = "由 build-handoff 生成的交付清单"
        package_note = "由 build-handoff 生成的制作就绪剧本包"
        validation.setdefault("warnings", []).append(
            issue(
                "legacy_full_handoff_deprecated",
                "v0.8 保留旧全剧打包仅用于兼容；新项目应使用 --batch 和 --series",
            )
        )
    if not validation["ready"]:
        print_json(validation)
        return 1

    timestamp = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d-%H%M%S")
    output_name = args.output_name or f"{default_output_name}_{timestamp}"
    if output_name in {"", ".", ".."} or Path(output_name).name != output_name:
        raise ToolError("output-name 必须是单一安全目录名，不能包含路径分隔符")
    output_dir = project_path / "09_定稿交付" / output_name
    archive_path = output_dir.with_suffix(".zip")
    if output_dir.exists() or archive_path.exists():
        raise ToolError(f"交付输出已存在，不会覆盖：{output_dir}")

    output_dir.mkdir(parents=True, exist_ok=False)
    manifest_files: list[dict[str, Any]] = []
    dependencies: list[dict[str, Any]] = []
    for selected in validation["selected_artifacts"]:
        key = selected["artifact_key"]
        version = selected["version"]
        artifact_kind = selected["artifact_type"]
        dependencies.append({"artifact_key": key, "version": version})
        category = PACKAGE_TYPE_DIRECTORY.get(artifact_kind)
        if category is None:
            continue
        source = path_from_record(project_path, selected["path"])
        if source is None or not source.is_file():
            raise ToolError(f"交付制品路径无效：{key}@{version}")
        category_dir = output_dir / category
        category_dir.mkdir(parents=True, exist_ok=True)
        destination = category_dir / source.name
        if destination.exists():
            destination = category_dir / package_filename(key, version, source.name)
        shutil.copy2(source, destination)
        manifest_files.append(
            {
                "artifact_key": key,
                "artifact_type": artifact_kind,
                "version": version,
                "package_path": destination.relative_to(output_dir).as_posix(),
                "sha256": sha256_file(destination),
                "size_bytes": destination.stat().st_size,
            }
        )

    _, state = load_state(project_path)
    manifest = {
        "schema_version": 1,
        "package_type": manifest_package_type,
        "project_id": state.get("project_id"),
        "project_name": state.get("name"),
        "built_at": now_iso(),
        "expected_episodes": args.expected_episodes,
        "files": manifest_files,
    }
    if batch_id is not None:
        manifest["batch_id"] = batch_id
        manifest["episode_ids"] = validation["episode_ids"]
    if series_mode:
        manifest["batch_ids"] = validation["batch_ids"]
        manifest["assembly_mode"] = "batch_aggregate"
    manifest_path = output_dir / "交付清单.json"
    atomic_write_json(manifest_path, manifest)
    shutil.make_archive(
        str(output_dir),
        "zip",
        root_dir=str(output_dir.parent),
        base_dir=output_dir.name,
    )

    artifacts = state.setdefault("artifacts", {})
    manifest_records = artifacts.setdefault(manifest_key, [])
    manifest_versions = [
        record.get("version", 0)
        for record in manifest_records
        if isinstance(record, dict) and type(record.get("version")) is int
    ]
    manifest_version = max(manifest_versions, default=0) + 1
    manifest_record = {
        "version": manifest_version,
        "artifact_type": manifest_type,
        "path": safe_relative_path(manifest_path, project_path),
        "size_bytes": manifest_path.stat().st_size,
        "sha256": sha256_file(manifest_path),
        "status": "awaiting_approval",
        "depends_on": list(dependencies),
        "registered_at": now_iso(),
        "note": manifest_note,
    }
    manifest_records.append(manifest_record)
    dependencies.append(
        {"artifact_key": manifest_key, "version": manifest_version}
    )

    records = artifacts.setdefault(package_key, [])
    versions = [
        record.get("version", 0)
        for record in records
        if isinstance(record, dict) and type(record.get("version")) is int
    ]
    version = max(versions, default=0) + 1
    record = {
        "version": version,
        "artifact_type": package_type,
        "path": safe_relative_path(archive_path, project_path),
        "size_bytes": archive_path.stat().st_size,
        "sha256": sha256_file(archive_path),
        "status": "awaiting_approval",
        "depends_on": dependencies,
        "registered_at": now_iso(),
        "note": package_note,
    }
    records.append(record)
    append_history(
        state,
        "delivery_manifest_built",
        {
            "artifact_key": manifest_key,
            "version": manifest_version,
            "path": manifest_record["path"],
            "file_count": len(manifest_files),
        },
    )
    append_history(
        state,
        "handoff_package_built",
        {
            "artifact_key": package_key,
            "version": version,
            "path": record["path"],
            "file_count": len(manifest_files),
        },
    )
    save_state(project_path, state)
    print_json(
        {
            "ok": True,
            "package_directory": str(output_dir),
            "archive": str(archive_path),
            "manifest": str(manifest_path),
            "manifest_artifact_key": manifest_key,
            "manifest_artifact_version": manifest_version,
            "artifact_key": package_key,
            "version": version,
            "status": "awaiting_approval",
            "file_count": len(manifest_files),
            "warnings": validation.get("warnings", []),
            **({"batch_id": batch_id} if batch_id is not None else {}),
            **({"series": True, "batch_ids": validation["batch_ids"]} if series_mode else {}),
        }
    )
    return 0


EPISODE_HEADING_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:\*{0,2})?\s*"
    r"第\s*(?P<number>[0-9零一二三四五六七八九十百千两]+)\s*集"
    r"\s*(?:[：:\-—·|]\s*)?(?P<title>.*?)\s*(?:\*{0,2})?\s*$"
)
SCENE_HEADING_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:[-*>•]\s*)?(?:\*{0,2})?\s*"
    r"(?P<scene_id>"
    r"第\s*[0-9零一二三四五六七八九十百千两]+\s*场"
    r"|场景\s*[0-9零一二三四五六七八九十百千两]+"
    r"|\d+\s*[-－—.]\s*\d+"
    r")(?P<body>.*?)\s*(?:\*{0,2})?\s*$"
)
TIME_TOKEN_RE = re.compile(
    r"(?<![一-鿿A-Za-z0-9])"
    r"(日|夜|晨|昼|午|昏|清晨|早晨|上午|中午|下午|傍晚|黄昏|深夜|凌晨|白天)"
    r"(?:景)?(?![一-鿿A-Za-z0-9])"
)
SPACE_TOKEN_RE = re.compile(
    r"(?<![一-鿿A-Za-z0-9])(内景|外景|内|外)(?![一-鿿A-Za-z0-9])"
)
CHARACTER_RE = re.compile(
    r"^\s*(?:[-*>•]\s*)?(?:\*{0,2})?\s*(?:出场)?人物\s*[：:]\s*(?P<value>.+?)\s*(?:\*{0,2})?\s*$"
)
OFF_SCENE_CHARACTER_RE = re.compile(
    r"^\s*(?:[-*>•]\s*)?(?:\*{0,2})?\s*"
    r"(?:非现场人物|画外音人物|电话声音人物|屏幕人物)"
    r"\s*[：:]\s*(?P<value>.+?)\s*(?:\*{0,2})?\s*$"
)
PROPS_RE = re.compile(
    r"^\s*(?:[-*>•]\s*)?(?:\*{0,2})?\s*(?:关键)?道具\s*[：:]\s*(?P<value>.+?)\s*(?:\*{0,2})?\s*$"
)
SCENE_END_STATE_RE = re.compile(
    r"^\s*(?:[-*>•]\s*)?(?:\*{0,2})?\s*"
    r"(?:场尾状态|离开状态|场景结果)\s*[：:]\s*(?P<value>.+?)\s*(?:\*{0,2})?\s*$"
)
ACTION_RE = re.compile(
    r"^\s*(?:[-*>•]\s*)?(?:\*{0,2})?\s*(?:[△▲※◆]|(?:画面|动作)\s*[：:])\s*(?P<value>.+)"
)
FORBIDDEN_DIRECTOR_FIELD_RE = re.compile(
    r"^\s*(?:[-*>•]\s*)?(?:\*{0,2})?\s*"
    r"(?:镜号|景别|机位|运镜|焦段|单镜时长|分镜时长|"
    r"图片提示词|生图提示词|视频提示词|负面提示词)\s*[：:]",
    re.IGNORECASE,
)
FORBIDDEN_DIRECTOR_TABLE_RE = re.compile(
    r"^(?:镜号|景别|机位|运镜|焦段|单镜时长|分镜时长|"
    r"图片提示词|生图提示词|视频提示词|负面提示词)\s*[|｜]",
    re.IGNORECASE,
)
FORBIDDEN_DIRECTOR_INLINE_RE = re.compile(
    r"(?:建议)?(?:镜号|景别|机位|运镜|焦段|单镜时长|分镜时长|"
    r"图片提示词|生图提示词|视频提示词|负面提示词)\s*[：:|｜]",
    re.IGNORECASE,
)
# 散文式镜头语言：填表式关键字之外，AI 起草最容易混进动作行的运镜、景别、
# 机位、焦段、剪辑与硬秒点写法。语义上无法保证百分之百判断（"特写"等词也可能
# 出现在正常叙事或台词里），所以只报 warning 交人工判断，不阻断校验。
PROSE_SHOT_LANGUAGE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "运镜",
        re.compile(
            r"镜头(?:缓缓|慢慢|快速|随之|再|又|即|则)?"
            r"(?:推近|推进|拉远|拉开|摇向|摇过|跟随|跟拍|下摇|上摇|平移|环绕|升起|下降|切到|切向)"
            r"|(?:推轨|轨道镜|摇臂|斯坦尼康|手持跟拍|升降镜头|环绕镜头|一镜到底|长镜头)"
        ),
    ),
    (
        "景别",
        re.compile(
            r"(?:大特写|特写|近景|中景|全景|远景|大远景|中近景|过肩镜|双人镜)"
            r"\s*[：:]|"
            r"(?:切|转|给)(?:一个)?(?:大特写|特写|近景|中景|全景|远景)|"
            r"(?:以|用)(?:大特写|特写|近景|中景|全景|远景)(?:拍|呈现|展现|表现)"
        ),
    ),
    (
        "机位",
        re.compile(
            r"(?:俯拍|仰拍|俯视镜|仰视镜|正打|反打|过肩拍|主观镜头|客观视角|"
            r"第一人称镜头|越轴|轴线)"
        ),
    ),
    (
        "焦段",
        re.compile(
            r"\d{1,3}\s*mm(?![a-z])|(?:长焦|广角|鱼眼|变焦|定焦|浅景深|大光圈)"
            r"(?:压缩|拍|镜头|下)?"
        ),
    ),
    (
        "剪辑与硬秒点",
        re.compile(
            r"(?:切黑|淡入|淡出|叠化|硬切|跳切|闪回镜头|转场镜头|黑屏)|"
            r"(?:时长|停留|保持|持续)\s*(?:约)?\s*\d+(?:\.\d+)?\s*秒|"
            r"\d+\s*[-–—~]\s*\d+\s*秒"
        ),
    ),
)


def prose_shot_language_hits(line: str) -> list[str]:
    """返回动作/描述行里疑似散文式镜头语言的类别；台词行由调用方排除。"""
    cleaned = unicodedata.normalize("NFKC", line).replace("**", "").strip()
    cleaned = re.sub(r"^(?:[-*>•]\s*)+", "", cleaned)
    cleaned = re.sub(r"^(?:[△▲※◆]\s*|(?:画面|动作)\s*[：:]\s*)", "", cleaned)
    return [
        label
        for label, pattern in PROSE_SHOT_LANGUAGE_PATTERNS
        if pattern.search(cleaned)
    ]
PLACEHOLDER_RE = re.compile(
    r"\b(?:TBD|TODO|FIXME)\b|"
    r"(?:\[待(?:补|定|确认)[^\]]*\]|【待(?:补|定|确认)[^】]*】)",
    re.IGNORECASE,
)
HOOK_RE = re.compile(
    r"^\s*(?:[-*>•]\s*)?(?:\*{0,2})?\s*(?:[【\[]\s*)?"
    r"(?:集尾钩子|结尾钩子|本集钩子|钩子)"
    r"(?:\s*[】\]])?\s*[：:]?\s*(?P<value>.*?)\s*(?:\*{0,2})?\s*$"
)
DIALOGUE_RE = re.compile(
    r"^\s*(?:[-*>•]\s*)?(?:\*{0,2})?\s*"
    r"(?P<speaker>[一-鿿A-Za-z0-9_·•]{1,20})"
    r"(?P<annotation>"
    r"(?:\s+(?:VO|OS|画外音|内心|旁白|电话声音|电话音|电话声|屏幕声音|视频声音)"
    r"|\s*[（(][^）)\r\n]{1,30}[）)])?"
    r")"
    r"\s*[：:]\s*(?P<text>\S.*?)\s*(?:\*{0,2})?\s*$",
    re.IGNORECASE,
)
NON_DIALOGUE_LABELS = {
    "人物",
    "出场人物",
    "非现场人物",
    "画外音人物",
    "电话声音人物",
    "屏幕人物",
    "道具",
    "关键道具",
    "动作",
    "画面",
    "地点",
    "场景",
    "时间",
    "集尾钩子",
    "结尾钩子",
    "本集钩子",
    "钩子",
    "备注",
    "场尾状态",
    "离开状态",
    "场景结果",
}


def parse_episode_number(value: str) -> int | None:
    if value.isdigit():
        number = int(value)
        return number if number > 0 else None
    digits = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
              "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    units = {"十": 10, "百": 100, "千": 1000}
    total = 0
    current = 0
    for character in value:
        if character in digits:
            current = digits[character]
        elif character in units:
            total += (current or 1) * units[character]
            current = 0
        else:
            return None
    number = total + current
    return number if number > 0 else None


def contains_forbidden_director_field(line: str) -> bool:
    cleaned = unicodedata.normalize("NFKC", line).replace("**", "").strip()
    cleaned = re.sub(r"^(?:[-*>•]\s*)+", "", cleaned)
    cleaned = cleaned.lstrip("|｜ ").strip()
    cleaned = re.sub(r"^(?:[△▲※◆]\s*|(?:画面|动作)\s*[：:]\s*)", "", cleaned)
    return bool(
        FORBIDDEN_DIRECTOR_FIELD_RE.match(cleaned)
        or FORBIDDEN_DIRECTOR_TABLE_RE.match(cleaned)
        or FORBIDDEN_DIRECTOR_INLINE_RE.search(cleaned)
    )


def split_declared_items(value: str) -> list[str]:
    cleaned = re.sub(r"[（(][^）)]*[）)]", "", value).strip()
    if cleaned.rstrip("。.") in {"", "无", "没有"}:
        return []
    return [
        token.strip()
        for token in re.split(r"[、,，;；/／]+", cleaned)
        if token.strip() and token.strip() not in {"无", "没有"}
    ]


def maximum_dialogue_run(block: list[tuple[int, str]]) -> tuple[int, int | None]:
    current = 0
    maximum = 0
    maximum_line: int | None = None
    for line_number, line in block:
        if dialogue_match(line):
            current += 1
            if current > maximum:
                maximum = current
                maximum_line = line_number
        elif ACTION_RE.match(line) or SCENE_END_STATE_RE.match(line):
            current = 0
        elif line.strip() and not (
            CHARACTER_RE.match(line)
            or OFF_SCENE_CHARACTER_RE.match(line)
            or PROPS_RE.match(line)
            or HOOK_RE.match(line)
        ):
            current = 0
    return maximum, maximum_line


def normalize_scene_location(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.replace("**", " ")
    normalized = re.sub(r"(?:场景|地点|场所)\s*[：:]?", " ", normalized)
    normalized = re.sub(r"[：:|/／,，、\-—()（）\[\]【】\s]+", "", normalized)
    return normalized or None


def normalize_scene_time(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = re.sub(r"\s+", "", value)
    return normalized[:-1] if normalized.endswith("景") else normalized


def normalize_scene_space(value: Any) -> str | None:
    normalized = normalize_scene_time(value)
    return normalized if normalized in {"内", "外"} else normalized


def scene_heading_values(body: str) -> tuple[str | None, str | None, str | None]:
    cleaned = body.replace("**", " ").strip()
    time_match = TIME_TOKEN_RE.search(cleaned)
    space_match = SPACE_TOKEN_RE.search(cleaned)
    without_metadata = TIME_TOKEN_RE.sub(" ", cleaned)
    without_metadata = SPACE_TOKEN_RE.sub(" ", without_metadata)
    location_name = normalize_scene_location(without_metadata)
    time_value = normalize_scene_time(time_match.group(1)) if time_match else None
    space_value = normalize_scene_space(space_match.group(1)) if space_match else None
    return location_name, time_value, space_value


def scene_heading_metadata(body: str) -> tuple[bool, bool, bool]:
    location_name, time_value, space_value = scene_heading_values(body)
    return bool(location_name), bool(time_value), bool(space_value)


def dialogue_match(line: str) -> re.Match[str] | None:
    if CHARACTER_RE.match(line) or OFF_SCENE_CHARACTER_RE.match(line) or PROPS_RE.match(line):
        return None
    match = DIALOGUE_RE.match(line)
    if not match:
        return None
    if match.group("speaker") in NON_DIALOGUE_LABELS:
        return None
    return match


def dialogue_annotation(line: str) -> str:
    match = dialogue_match(line)
    if not match:
        return ""
    return (match.group("annotation") or "").upper()


def delivery_mode_from_line(line: str) -> str:
    annotation = dialogue_annotation(line)
    if re.search(r"\bVO\b|旁白|内心", annotation):
        return "voice_over"
    if re.search(r"\bOS\b|画外音", annotation):
        return "off_screen"
    if re.search(r"电话声音|电话音|电话声", annotation):
        return "phone_audio"
    if re.search(r"屏幕声音|视频声音", annotation):
        return "screen_video"
    return "on_screen"


def spoken_char_count(text: str) -> int:
    """对白的有效发声字数：剔除空白与标点，只留真正需要读出来的字符。"""
    cleaned = unicodedata.normalize("NFKC", text)
    return sum(
        1
        for char in cleaned
        if not char.isspace() and not unicodedata.category(char).startswith("P")
    )


def estimate_dialogue_seconds(
    char_count: int, rate: tuple[float, float]
) -> tuple[float, float]:
    """按字/秒区间把发声字数换算成秒数区间。

    返回 (最快秒数, 最慢秒数)：上限字/秒对应最快，下限字/秒对应最慢。
    这是推算值，不能冒充配音实测结果。
    """
    slow_rate, fast_rate = rate
    if char_count <= 0:
        return (0.0, 0.0)
    return (char_count / fast_rate, char_count / slow_rate)


def scene_duration_band(
    target_seconds: int, scene_count: int
) -> tuple[float, float] | None:
    """按“单集目标时长 ÷ 场数”推导单场时长比例区间，不写死绝对秒数。"""
    if target_seconds <= 0 or scene_count <= 0:
        return None
    average = target_seconds / scene_count
    low, high = SCENE_DURATION_BAND
    return (average * low, average * high)


def validate_script_file(
    script_path: Path,
    fragment: bool = False,
    target_duration_seconds: int | None = None,
    chars_per_second: tuple[float, float] | None = None,
) -> dict[str, Any]:
    """校验单集文学剧本结构。

    target_duration_seconds 省略时完全不做时长推算，输出与不带该参数时逐字段一致。
    """
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    rate = chars_per_second or DEFAULT_DIALOGUE_CHARS_PER_SECOND
    if not script_path.is_file():
        return {
            "valid": False,
            "path": str(script_path),
            "errors": [issue("script_missing", "剧本文件不存在")],
            "warnings": [],
            "summary": {"error_count": 1, "warning_count": 0, "scene_count": 0},
        }
    try:
        text = script_path.read_text(encoding="utf-8-sig")
    except UnicodeError as exc:
        return {
            "valid": False,
            "path": str(script_path),
            "errors": [issue("script_encoding", f"剧本必须是 UTF-8 文本：{exc}")],
            "warnings": [],
            "summary": {"error_count": 1, "warning_count": 0, "scene_count": 0},
        }
    except OSError as exc:
        return {
            "valid": False,
            "path": str(script_path),
            "errors": [issue("script_unreadable", f"无法读取剧本：{exc}")],
            "warnings": [],
            "summary": {"error_count": 1, "warning_count": 0, "scene_count": 0},
        }
    lines = text.splitlines()
    for line_number, line in enumerate(lines, 1):
        if contains_forbidden_director_field(line):
            errors.append(
                issue(
                    "director_field_forbidden",
                    "文学剧本混入导演分镜或生成提示词字段",
                    line=line_number,
                )
            )
        elif not dialogue_match(line) and not SCENE_HEADING_RE.match(line):
            # 台词原文与场次标题不参与散文式判断：角色可以在对白里提到"特写"，
            # 场次标题的"日/外"等词也不是镜头语言。
            prose_hits = prose_shot_language_hits(line)
            if prose_hits:
                warnings.append(
                    issue(
                        "shot_language_suspected",
                        "疑似散文式镜头语言（"
                        + "、".join(prose_hits)
                        + "）；文学剧本只写可见动作，镜头表达应留给 AI 分镜计划，请人工确认",
                        line=line_number,
                    )
                )
        normalized_line = unicodedata.normalize("NFKC", line)
        if PLACEHOLDER_RE.search(normalized_line):
            errors.append(
                issue(
                    "placeholder_found",
                    "剧本仍含 TODO/TBD/待补等占位内容",
                    line=line_number,
                )
            )
    episode_heading: dict[str, Any] | None = None
    episode_headings: list[dict[str, Any]] = []
    for line_number, line in enumerate(lines, 1):
        match = EPISODE_HEADING_RE.match(line)
        if match:
            title = re.sub(r"[\s*#]+$", "", match.group("title")).strip()
            heading = {
                "number": match.group("number"),
                "number_value": parse_episode_number(match.group("number")),
                "title": title,
                "line": line_number,
            }
            episode_headings.append(heading)
            if episode_heading is None:
                episode_heading = heading
            if not title or title in {"标题", "TBD", "TODO", "待定"}:
                errors.append(issue("episode_title_missing", "分集标题缺失或仍是占位符", line=line_number))
    if episode_heading is None:
        errors.append(issue("episode_heading_missing", "缺少“第N集 + 集标题”"))
    elif len(episode_headings) > 1:
        errors.append(
            issue(
                "multiple_episode_headings",
                "一个分集剧本文件只能包含一个集标题",
                lines=[item["line"] for item in episode_headings],
            )
        )
    if episode_heading is not None and episode_heading.get("number_value") is None:
        errors.append(
            issue(
                "episode_number_invalid",
                "集号必须是大于0的阿拉伯数字或可解析中文数字",
                line=episode_heading["line"],
            )
        )

    scenes: list[dict[str, Any]] = []
    for line_number, line in enumerate(lines, 1):
        match = SCENE_HEADING_RE.match(line)
        if not match:
            continue
        has_location, has_time, has_space = scene_heading_metadata(match.group("body"))
        scenes.append(
            {
                "scene_id": re.sub(r"\s+", "", match.group("scene_id")),
                "heading": line.strip(),
                "line": line_number,
                "end_line": len(lines) + 1,
                "has_location": has_location,
                "has_time": has_time,
                "has_space": has_space,
            }
        )
    if not scenes:
        errors.append(issue("scene_heading_missing", "未识别到任何分场标题"))
    for index, scene in enumerate(scenes):
        scene["end_line"] = scenes[index + 1]["line"] if index + 1 < len(scenes) else len(lines) + 1

    seen_scene_ids: set[str] = set()
    numeric_scene_numbers: list[int] = []
    dialogue_count = 0
    action_count = 0
    unused_prop_count = 0
    long_dialogue_run_count = 0
    scene_end_state_count = 0
    total_spoken_chars = 0
    for scene in scenes:
        location = {"scene": scene["scene_id"], "line": scene["line"]}
        if scene["scene_id"] in seen_scene_ids:
            errors.append(issue("scene_id_duplicate", f"场号重复：{scene['scene_id']}", **location))
        seen_scene_ids.add(scene["scene_id"])
        numeric_match = re.fullmatch(r"(\d+)[-－—.](\d+)", scene["scene_id"])
        if numeric_match:
            scene_episode, scene_number = map(int, numeric_match.groups())
            numeric_scene_numbers.append(scene_number)
            if episode_heading and episode_heading.get("number_value") is not None:
                if scene_episode != episode_heading["number_value"]:
                    errors.append(
                        issue(
                            "scene_episode_mismatch",
                            f"场号 {scene['scene_id']} 与第{episode_heading['number']}集不一致",
                            **location,
                        )
                    )
        else:
            errors.append(
                issue(
                    "scene_id_format_invalid",
                    "场号必须使用“集号-场序号”形式，如 1-1",
                    **location,
                )
            )
        if not scene["has_location"]:
            errors.append(issue("scene_location_missing", "分场标题缺少地点", **location))
        if not scene["has_time"]:
            errors.append(issue("scene_time_missing", "分场标题缺少日/夜等时间", **location))
        if not scene["has_space"]:
            errors.append(issue("scene_space_missing", "分场标题缺少内/外景", **location))

        block_start = scene["line"]
        block_end = scene["end_line"] - 1
        block = [
            (number, lines[number - 1])
            for number in range(block_start + 1, block_end + 1)
        ]
        characters = [(number, CHARACTER_RE.match(line)) for number, line in block]
        character_matches = [(number, match) for number, match in characters if match]
        if not character_matches:
            errors.append(issue("scene_characters_missing", "分场缺少“人物：”声明", **location))
        elif any(not match.group("value").strip() for _, match in character_matches):
            errors.append(issue("scene_characters_empty", "分场人物声明为空", **location))
        declared_characters = (
            split_declared_items(character_matches[0][1].group("value"))
            if character_matches
            else []
        )
        if len(declared_characters) != len(set(declared_characters)):
            warnings.append(issue("scene_characters_duplicate", "人物声明存在重复项", **location))

        off_scene_characters = [
            (number, OFF_SCENE_CHARACTER_RE.match(line)) for number, line in block
        ]
        off_scene_matches = [
            (number, match) for number, match in off_scene_characters if match
        ]
        declared_off_scene_speakers = [
            speaker
            for _, match in off_scene_matches
            for speaker in split_declared_items(match.group("value"))
        ]
        if len(declared_off_scene_speakers) != len(set(declared_off_scene_speakers)):
            warnings.append(
                issue("scene_off_scene_speakers_duplicate", "非现场人物声明存在重复项", **location)
            )
        presence_conflicts = sorted(
            set(declared_characters).intersection(declared_off_scene_speakers)
        )
        if presence_conflicts:
            errors.append(
                issue(
                    "scene_character_presence_conflict",
                    "人物不能同时声明为现场与非现场：" + "、".join(presence_conflicts),
                    **location,
                )
            )
        declared_speakers = list(
            dict.fromkeys([*declared_characters, *declared_off_scene_speakers])
        )

        props = [(number, PROPS_RE.match(line)) for number, line in block]
        prop_matches = [(number, match) for number, match in props if match]
        if not prop_matches:
            errors.append(issue("scene_props_missing", "分场缺少“道具：”声明（无道具时请写“道具：无”）", **location))
        else:
            declared_props = split_declared_items(prop_matches[0][1].group("value"))
            if len(declared_props) != len(set(declared_props)):
                warnings.append(issue("scene_props_duplicate", "道具声明存在重复项", **location))
            body_text = "\n".join(
                line
                for number, line in block
                if number != prop_matches[0][0]
            )
            for prop in declared_props:
                normalized_prop = re.sub(r"(?:若干|数个|一把|一只|一件|一张)$", "", prop).strip()
                short_alias = normalized_prop[-2:] if len(normalized_prop) > 2 else normalized_prop
                if (
                    len(normalized_prop) >= 2
                    and normalized_prop not in body_text
                    and short_alias not in body_text
                ):
                    unused_prop_count += 1
                    warnings.append(
                        issue(
                            "prop_not_referenced",
                            f"道具栏列出“{prop}”，但本场正文未再次提及；请确认是否真正参与剧情",
                            scene=scene["scene_id"],
                            line=prop_matches[0][0],
                        )
                    )

        actions = [(number, ACTION_RE.match(line)) for number, line in block]
        action_matches = [(number, match) for number, match in actions if match]
        if not action_matches:
            errors.append(issue("scene_action_missing", "分场缺少可见动作（用“△”或“动作：”标记）", **location))
        elif len(action_matches) < 2:
            warnings.append(
                issue(
                    "scene_action_sparse",
                    "本场只有一条动作，难以证明形成了连续行动与反馈",
                    **location,
                )
            )
        action_count += len(action_matches)

        dialogues = [(number, dialogue_match(line)) for number, line in block]
        dialogue_matches = [(number, match) for number, match in dialogues if match]
        if not dialogue_matches:
            warnings.append(
                issue(
                    "scene_without_dialogue",
                    "本场没有对白；纯动作场可以成立，但需人工确认叙事信息充分",
                    **location,
                )
            )
        dialogue_count += len(dialogue_matches)
        scene_spoken_chars = sum(
            spoken_char_count(match.group("text")) for _, match in dialogue_matches
        )
        scene["spoken_chars"] = scene_spoken_chars
        total_spoken_chars += scene_spoken_chars
        for number, match in dialogue_matches:
            dialogue_text = match.group("text").strip()
            if len(dialogue_text) < 2:
                warnings.append(issue("dialogue_too_short", "对白过短，请确认不是遗漏", line=number, scene=scene["scene_id"]))
            speaker = match.group("speaker")
            speaker_base = re.sub(r"[甲乙丙丁戊己庚辛壬癸一二三四五六七八九十]+$", "", speaker)
            declared = any(
                speaker == item
                or speaker.startswith(item.rstrip("若干"))
                or (speaker_base and speaker_base in item)
                for item in declared_speakers
            )
            if declared_speakers and not declared:
                errors.append(
                    issue(
                        "dialogue_speaker_undeclared",
                        f"对白角色“{speaker}”未在本场人物表中声明",
                        line=number,
                        scene=scene["scene_id"],
                    )
                )

        max_run, max_run_line = maximum_dialogue_run(block)
        if max_run >= 4:
            long_dialogue_run_count += 1
            warnings.append(
                issue(
                    "dialogue_run_without_action",
                    f"连续 {max_run} 句对白之间没有有效动作或反应，请检查是否为站立对话",
                    scene=scene["scene_id"],
                    line=max_run_line,
                )
            )
        if dialogue_matches and action_matches and len(dialogue_matches) > len(action_matches) * 3:
            warnings.append(
                issue(
                    "dialogue_heavy_scene",
                    "本场对白量显著高于动作节点，请人工检查场景是否仍由对白主导",
                    **location,
                )
            )

        end_states = [
            (number, SCENE_END_STATE_RE.match(line)) for number, line in block
        ]
        end_state_matches = [(number, match) for number, match in end_states if match]
        scene_end_state_count += len(end_state_matches)
        if not end_state_matches:
            warnings.append(
                issue(
                    "scene_end_state_unmarked",
                    "内部稿未标记“场尾状态”；对外交付稿可隐藏，但内部连续性复核应补齐",
                    **location,
                )
            )

    if numeric_scene_numbers:
        expected_numbers = list(range(1, len(numeric_scene_numbers) + 1))
        if numeric_scene_numbers != expected_numbers:
            errors.append(
                issue(
                    "scene_number_sequence_invalid",
                    f"数字场号应从1连续递增，实际为 {numeric_scene_numbers}",
                )
            )

    hook_matches: list[tuple[int, re.Match[str]]] = []
    for line_number, line in enumerate(lines, 1):
        match = HOOK_RE.match(line)
        if match:
            hook_matches.append((line_number, match))
    if not hook_matches and not fragment:
        errors.append(issue("ending_hook_missing", "缺少明确的“集尾钩子：”"))
    elif hook_matches:
        hook_line, hook_match = hook_matches[-1]
        hook_text = hook_match.group("value").strip()
        if not hook_text:
            errors.append(issue("ending_hook_empty", "集尾钩子内容为空", line=hook_line))
        elif len(hook_text) < 6:
            warnings.append(issue("ending_hook_short", "集尾钩子较短，请人工判断悬念是否成立", line=hook_line))
        if scenes and hook_line < scenes[-1]["line"]:
            warnings.append(issue("ending_hook_position", "集尾钩子出现在最后一场之前", line=hook_line))

    if len(scenes) == 1:
        warnings.append(issue("single_scene", "本集只有一场，请人工确认节奏与内容量"))

    # 时长预算：只在项目规格声明了单集目标时长时推算，且一律只预警不阻断。
    # 字数推算不能冒充配音实读结果，故只报“最快语速下已超时”这一无歧义方向；
    # 偏短需要动作与转场余量才能判断，项目未给出该参数，只输出数据交人工判断。
    episode_seconds_fast, episode_seconds_slow = estimate_dialogue_seconds(
        total_spoken_chars, rate
    )
    duration_summary: dict[str, Any] = {
        "spoken_char_count": total_spoken_chars,
        "chars_per_second": list(rate),
        "estimated_dialogue_seconds_range": [
            round(episode_seconds_fast, 1),
            round(episode_seconds_slow, 1),
        ],
        "estimate_basis": "按字数推算的净对白秒数，未含动作、停顿与转场余量，非配音实测",
        "target_duration_seconds": target_duration_seconds,
    }
    if target_duration_seconds is not None and target_duration_seconds > 0:
        if episode_seconds_fast > target_duration_seconds:
            warnings.append(
                issue(
                    "episode_dialogue_budget_over",
                    f"净对白按最快语速{rate[1]}字/秒推算已需约{round(episode_seconds_fast, 1)}秒，"
                    f"超过单集目标{target_duration_seconds}秒，且尚未计入动作、停顿与转场；"
                    "建议在大纲层压缩，不要把超载留到成稿返修",
                    estimated_seconds=round(episode_seconds_fast, 1),
                    target=target_duration_seconds,
                )
            )
        band = scene_duration_band(target_duration_seconds, len(scenes))
        if band is not None:
            duration_summary["scene_duration_band_seconds"] = [
                round(band[0], 1),
                round(band[1], 1),
            ]
            for scene in scenes:
                scene_fast, scene_slow = estimate_dialogue_seconds(
                    scene.get("spoken_chars", 0), rate
                )
                # 用推算区间与比例带比较：区间整体越界才提示，避免边界抖动造成噪音。
                if scene_fast > band[1]:
                    warnings.append(
                        issue(
                            "scene_duration_unbalanced",
                            f"本场净对白推算约{round(scene_fast, 1)}—{round(scene_slow, 1)}秒，"
                            f"高于按目标时长推导的单场区间{round(band[0], 1)}—{round(band[1], 1)}秒，"
                            "请在大纲层确认场次划分是否失衡",
                            scene=scene["scene_id"],
                            line=scene["line"],
                        )
                    )
    result = {
        "valid": not errors,
        "validation_scope": "script_structure",
        "production_ready": False,
        "production_ready_note": "结构通过不等于制作就绪；须继续通过语义质检和 validate-handoff",
        "path": str(script_path),
        "fragment": fragment,
        "episode": episode_heading,
        "errors": errors,
        "warnings": warnings,
        "summary": {
            "error_count": len(errors),
            "warning_count": len(warnings),
            "scene_count": len(scenes),
            "action_count": action_count,
            "dialogue_count": dialogue_count,
            "ending_hook_count": len(hook_matches),
            "scene_end_state_count": scene_end_state_count,
            "unused_prop_count": unused_prop_count,
            "long_dialogue_run_count": long_dialogue_run_count,
        },
        "scenes": [
            {
                "scene_id": scene["scene_id"],
                "line": scene["line"],
                "heading": scene["heading"],
            }
            for scene in scenes
        ],
    }
    if target_duration_seconds is not None:
        # 只在调用方声明了目标时长时输出，未声明时返回结构与改动前完全一致。
        result["duration_estimate"] = duration_summary
        for entry, scene in zip(result["scenes"], scenes):
            scene_fast, scene_slow = estimate_dialogue_seconds(
                scene.get("spoken_chars", 0), rate
            )
            entry["estimated_dialogue_seconds_range"] = [
                round(scene_fast, 1),
                round(scene_slow, 1),
            ]
    return result


def cue_type_from_line(line: str) -> str:
    annotation = dialogue_annotation(line)
    if re.search(r"\bVO\b|旁白|内心", annotation):
        return "vo"
    if re.search(r"\bOS\b|画外音", annotation):
        return "os"
    return "dialogue"


def normalized_text(value: str) -> str:
    return re.sub(r"\s+", "", value).strip("。.!！?？")


def extract_script_index(
    script_path: Path, artifact_key: str
) -> tuple[dict[str, dict[str, Any]], list[tuple[str, str, str, str, str]]]:
    text = script_path.read_text(encoding="utf-8-sig")
    lines = text.splitlines()
    key_scope = artifact_key.split(":", 1)[1] if ":" in artifact_key else ""
    episode_id = key_scope if re.fullmatch(r"E\d+", key_scope, re.IGNORECASE) else ""
    if not episode_id:
        heading = next(
            (EPISODE_HEADING_RE.match(line) for line in lines if EPISODE_HEADING_RE.match(line)),
            None,
        )
        if heading:
            heading_number = parse_episode_number(heading.group("number"))
            if heading_number is not None:
                episode_id = f"E{heading_number:03d}"

    scene_positions: list[tuple[int, re.Match[str]]] = []
    for index, line in enumerate(lines):
        match = SCENE_HEADING_RE.match(line)
        if match:
            scene_positions.append((index, match))
    scenes: dict[str, dict[str, Any]] = {}
    cues: list[tuple[str, str, str, str, str]] = []
    for position, (start, match) in enumerate(scene_positions):
        end = scene_positions[position + 1][0] if position + 1 < len(scene_positions) else len(lines)
        scene_id = re.sub(r"\s+", "", match.group("scene_id"))
        location_name, time_value, space_value = scene_heading_values(match.group("body"))
        block = lines[start + 1 : end]
        characters: list[str] = []
        off_scene_speakers: list[str] = []
        props: list[str] = []
        for line in block:
            character_match = CHARACTER_RE.match(line)
            if character_match and not characters:
                characters = split_declared_items(character_match.group("value"))
            off_scene_match = OFF_SCENE_CHARACTER_RE.match(line)
            if off_scene_match:
                off_scene_speakers.extend(
                    split_declared_items(off_scene_match.group("value"))
                )
            prop_match = PROPS_RE.match(line)
            if prop_match and not props:
                props = split_declared_items(prop_match.group("value"))
            dialogue = dialogue_match(line)
            if dialogue:
                cue = (
                    scene_id,
                    dialogue.group("speaker"),
                    cue_type_from_line(line),
                    delivery_mode_from_line(line),
                    normalized_text(dialogue.group("text")),
                )
                cues.append(cue)
        scenes[scene_id] = {
            "episode_id": episode_id,
            "scene_id": scene_id,
            "location_name": location_name,
            "time": time_value,
            "space": space_value,
            "characters": characters,
            "off_scene_speakers": list(dict.fromkeys(off_scene_speakers)),
            "props": props,
            "text": "\n".join(block),
        }
    return scenes, cues


def validate_continuity_ledger_file(
    project_path: Path,
    state: dict[str, Any],
    artifact_key: str,
    record: dict[str, Any],
    episode_records: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    expected_script_sources = {
        (key, episode_record.get("version"))
        for key, episode_record in episode_records.items()
    }
    expected_review_sources: set[tuple[str, int]] = set()
    for episode_key, episode_record in sorted(episode_records.items()):
        review_match = matching_boundary_review(
            state, episode_key, episode_record, project_path
        )
        if review_match is None:
            errors.append(
                issue(
                    "continuity_boundary_review_missing",
                    "连续性台账对应的分集剧本缺少当前已通过内容边界报告",
                    artifact_key=episode_key,
                )
            )
            continue
        review_key, review_record = review_match
        expected_review_sources.add((review_key, review_record.get("version")))
    expected_sources = expected_script_sources | expected_review_sources
    state_sources = {
        (item.get("artifact_key"), item.get("version"))
        for item in record.get("depends_on", [])
        if isinstance(item, dict)
        and isinstance(item.get("artifact_key"), str)
        and artifact_type(item["artifact_key"])
        in {"episode_script", "episode_boundary_review"}
    }
    if state_sources != expected_sources:
        errors.append(
            issue(
                "continuity_dependencies_mismatch",
                "连续性台账必须精确依赖当前全部分集剧本及对应的已通过内容边界报告",
                artifact_key=artifact_key,
            )
        )

    path = path_from_record(project_path, record.get("path"))
    try:
        payload = (
            json.loads(path.read_text(encoding="utf-8-sig"))
            if path and path.suffix.lower() == ".json"
            else None
        )
    except (OSError, UnicodeError, json.JSONDecodeError):
        payload = None
    if not isinstance(payload, dict):
        errors.append(
            issue(
                "continuity_ledger_json_required",
                "连续性台账必须是规范 JSON",
                artifact_key=artifact_key,
            )
        )
        return errors
    if type(payload.get("schema_version")) is not int or payload.get("schema_version") != 1:
        errors.append(issue("continuity_schema_invalid", "连续性台账 schema_version 必须为1"))
    if payload.get("project_id") != state.get("project_id"):
        errors.append(issue("continuity_project_mismatch", "连续性台账 project_id 不一致"))
    generated_from = payload.get("generated_from")
    generated_source_list = [
        (item.get("artifact_key"), item.get("version"))
        for item in generated_from
        if isinstance(item, dict)
        and isinstance(item.get("artifact_key"), str)
        and type(item.get("version")) is int
    ] if isinstance(generated_from, list) else []
    actual_sources = set(generated_source_list)
    if (
        not isinstance(generated_from, list)
        or len(generated_source_list) != len(generated_from)
        or len(generated_source_list) != len(expected_sources)
        or actual_sources != expected_sources
    ):
        errors.append(
            issue(
                "continuity_source_versions_mismatch",
                "连续性台账 generated_from 必须精确绑定当前全部分集剧本及对应内容边界报告",
                expected=sorted(f"{key}@{version}" for key, version in expected_sources),
                actual=sorted(f"{key}@{version}" for key, version in actual_sources),
            )
        )

    script_scenes: dict[str, dict[str, Any]] = {}
    for episode_key, episode_record in sorted(episode_records.items()):
        script_path = path_from_record(project_path, episode_record.get("path"))
        if script_path is None or not script_path.is_file():
            continue
        scenes, _ = extract_script_index(script_path, episode_key)
        script_scenes.update(scenes)

    continuity_records = payload.get("records")
    if not isinstance(continuity_records, list):
        errors.append(issue("continuity_records_invalid", "连续性台账 records 必须是数组"))
        return errors
    required_fields = (
        "episode_id",
        "scene_id",
        "character_states",
        "item_states",
        "relationship_state",
        "knowledge_state",
        "unresolved_threads",
        "storyline_progress",
        "relative_time",
        "end_state",
    )

    def value_is_empty(value: Any) -> bool:
        if value is None:
            return True
        if isinstance(value, str):
            return not value.strip()
        if isinstance(value, (list, dict, tuple, set)):
            return not value
        return False

    catalog_scene_ids: set[str] = set()
    for index, continuity_record in enumerate(continuity_records):
        if not isinstance(continuity_record, dict):
            errors.append(
                issue(
                    "continuity_record_invalid",
                    "连续性台账中的每条记录必须是对象",
                    record_index=index,
                )
            )
            continue
        for field in required_fields:
            if field not in continuity_record:
                errors.append(
                    issue(
                        "continuity_record_field_missing",
                        f"连续性记录缺少 {field}",
                        record_index=index,
                        field=field,
                    )
                )
            elif value_is_empty(continuity_record[field]):
                errors.append(
                    issue(
                        "continuity_record_field_empty",
                        f"连续性记录的 {field} 不能为空",
                        record_index=index,
                        field=field,
                    )
                )
        scene_id = continuity_record.get("scene_id")
        if not isinstance(scene_id, str) or not scene_id.strip():
            continue
        if scene_id in catalog_scene_ids:
            errors.append(issue("continuity_scene_duplicate", f"连续性台账重复场次：{scene_id}"))
        catalog_scene_ids.add(scene_id)
        script_scene = script_scenes.get(scene_id)
        if script_scene is None:
            errors.append(issue("continuity_scene_extra", f"连续性台账出现剧本不存在的场次：{scene_id}"))
        elif continuity_record.get("episode_id") != script_scene.get("episode_id"):
            errors.append(issue("continuity_episode_mismatch", f"连续性场次 {scene_id} 的 episode_id 不一致"))

    for scene_id in sorted(set(script_scenes) - catalog_scene_ids):
        errors.append(issue("continuity_scene_missing", f"连续性台账缺少剧本场次：{scene_id}"))
    return errors


def load_breakdown_json(
    project_path: Path,
    state: dict[str, Any],
    artifact_kind: str,
    allowed_statuses: set[str],
    errors: list[dict[str, Any]],
    target_key: str | None = None,
) -> tuple[str, dict[str, Any], dict[str, Any]] | None:
    if target_key is not None:
        record = latest_record(state, target_key)
        candidates = (
            [(target_key, record)]
            if record is not None and record.get("status") in allowed_statuses
            else []
        )
    else:
        candidates = [
            (key, record)
            for key, record in latest_records_of_type(state, artifact_kind)
            if key == artifact_kind and record.get("status") in allowed_statuses
        ]
    if len(candidates) != 1:
        errors.append(
            issue(
                "breakdown_artifact_count_invalid",
                f"{ARTIFACT_TYPES[artifact_kind]}必须恰有一个可用最新版，实际为 {len(candidates)}",
                artifact_type=artifact_kind,
            )
        )
        return None
    key, record = candidates[0]
    path = path_from_record(project_path, record.get("path"))
    if path is None or path.suffix.lower() != ".json":
        errors.append(
            issue(
                "breakdown_json_required",
                f"{ARTIFACT_TYPES[artifact_kind]}必须登记规范 JSON 文件",
                artifact_key=key,
            )
        )
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        errors.append(
            issue(
                "breakdown_json_invalid",
                f"无法读取 {ARTIFACT_TYPES[artifact_kind]}：{exc}",
                artifact_key=key,
            )
        )
        return None
    if not isinstance(payload, dict):
        errors.append(
            issue(
                "breakdown_root_invalid",
                f"{ARTIFACT_TYPES[artifact_kind]}顶层必须是 JSON 对象",
                artifact_key=key,
            )
        )
        return None
    return key, record, payload


def validate_breakdowns_state(
    project_path: Path,
    expected_episodes: int | None = None,
    allow_awaiting: bool = False,
    batch_id: str | None = None,
) -> dict[str, Any]:
    project_result = validate_state(project_path)
    errors = list(project_result.get("errors", []))
    warnings = list(project_result.get("warnings", []))
    if errors:
        return {
            "valid": False,
            "project": str(project_path),
            "errors": errors,
            "warnings": warnings,
            "summary": {"error_count": len(errors), "warning_count": len(warnings)},
        }
    _, state = load_state(project_path)
    allowed_statuses = {"confirmed"}
    if allow_awaiting:
        allowed_statuses.add("awaiting_approval")

    requested_episode_ids: list[str] | None = None
    if batch_id is not None:
        requested_episode_ids = batch_episode_ids(state, batch_id)
        if requested_episode_ids is None:
            errors.append(issue("batch_missing", f"批次不存在或结构无效：{batch_id}"))
    elif expected_episodes is not None:
        requested_episode_ids = [
            f"E{number:03d}" for number in range(1, expected_episodes + 1)
        ]

    episode_records = {
        key: record
        for key, record in latest_records_of_type(state, "episode_script")
        if record.get("status") in allowed_statuses
    }
    if requested_episode_ids is not None:
        required_episode_keys = {
            f"episode_script:{episode_id}" for episode_id in requested_episode_ids
        }
        missing = sorted(required_episode_keys - set(episode_records))
        for key in missing:
            errors.append(
                issue(
                    "breakdown_episode_missing",
                    f"制作提取缺少可用剧本：{key}",
                    artifact_key=key,
                )
            )
        episode_records = {
            key: record for key, record in episode_records.items() if key in required_episode_keys
        }
    if not episode_records:
        errors.append(issue("breakdown_no_episode_scripts", "没有可用于制作提取的分集剧本"))

    script_scenes: dict[str, dict[str, Any]] = {}
    script_cues: list[tuple[str, str, str, str, str]] = []
    expected_script_sources: set[tuple[str, int]] = set()
    expected_review_sources: set[tuple[str, int]] = set()
    for key, record in sorted(episode_records.items()):
        path = path_from_record(project_path, record.get("path"))
        if path is None or not path.is_file():
            continue
        expected_script_sources.add((key, record["version"]))
        review_match = matching_boundary_review(state, key, record, project_path)
        if review_match is None:
            errors.append(
                issue(
                    "breakdown_boundary_review_missing",
                    "制作提取对应的分集剧本缺少当前已通过内容边界报告",
                    artifact_key=key,
                )
            )
        else:
            review_key, review_record = review_match
            expected_review_sources.add((review_key, review_record["version"]))
        scenes, cues = extract_script_index(path, key)
        duplicates = set(script_scenes) & set(scenes)
        for scene_id in sorted(duplicates):
            errors.append(
                issue(
                    "script_scene_duplicate_across_files",
                    f"场号在多个剧本文件重复：{scene_id}",
                    scene_id=scene_id,
                )
            )
        script_scenes.update(scenes)
        script_cues.extend(cues)
    expected_sources = expected_script_sources | expected_review_sources

    loaded: dict[str, tuple[str, dict[str, Any], dict[str, Any]]] = {}
    for artifact_kind in (
        "character_roster",
        "scene_catalog",
        "prop_costume_ledger",
        "dialogue_cue_sheet",
    ):
        result = load_breakdown_json(
            project_path,
            state,
            artifact_kind,
            allowed_statuses,
            errors,
            f"{artifact_kind}:{batch_id}" if batch_id is not None else None,
        )
        if result is not None:
            loaded[artifact_kind] = result

    payloads: dict[str, dict[str, Any]] = {}
    for artifact_kind, (key, record, payload) in loaded.items():
        payloads[artifact_kind] = payload
        artifact_expected_sources = set(expected_sources)
        if artifact_kind == "dialogue_cue_sheet":
            source_corpus_record = latest_record(state, "source_corpus")
            source_corpus_version = (
                source_corpus_record.get("version")
                if isinstance(source_corpus_record, dict)
                else None
            )
            if type(source_corpus_version) is int:
                artifact_expected_sources.add(
                    ("source_corpus", source_corpus_version)
                )
            else:
                errors.append(
                    issue(
                        "dialogue_source_corpus_missing",
                        "台词声音表缺少当前原著语料库",
                        artifact_key=key,
                    )
                )
            source_event_record = latest_record(state, "source_event_index")
            source_event_version = (
                source_event_record.get("version")
                if isinstance(source_event_record, dict)
                else None
            )
            if type(source_event_version) is int:
                artifact_expected_sources.add(("source_event_index", source_event_version))
            else:
                errors.append(
                    issue(
                        "dialogue_source_event_index_missing",
                        "台词声音表缺少当前原著事件索引",
                        artifact_key=key,
                    )
                )
        if type(payload.get("schema_version")) is not int or payload.get("schema_version") != 1:
            errors.append(
                issue(
                    "breakdown_schema_version_invalid",
                    "制作提取表 schema_version 必须为1",
                    artifact_key=key,
                )
            )
        if payload.get("project_id") != state.get("project_id"):
            errors.append(
                issue(
                    "breakdown_project_mismatch",
                    "制作提取表 project_id 与项目不一致",
                    artifact_key=key,
                )
            )
        if not isinstance(payload.get("records"), list):
            errors.append(
                issue(
                    "breakdown_records_invalid",
                    "制作提取表 records 必须是数组",
                    artifact_key=key,
                )
            )
        generated_from = payload.get("generated_from")
        generated_source_list = [
            (item.get("artifact_key"), item.get("version"))
            for item in generated_from
            if isinstance(item, dict)
            and isinstance(item.get("artifact_key"), str)
            and type(item.get("version")) is int
        ] if isinstance(generated_from, list) else []
        actual_sources = set(generated_source_list)
        if (
            not isinstance(generated_from, list)
            or len(generated_source_list) != len(generated_from)
            or len(generated_source_list) != len(actual_sources)
            or actual_sources != artifact_expected_sources
        ):
            errors.append(
                issue(
                    "breakdown_source_versions_mismatch",
                    "制作提取表 generated_from 未精确绑定当前分集剧本及对应内容边界报告版本",
                    artifact_key=key,
                    expected=sorted(f"{item[0]}@{item[1]}" for item in artifact_expected_sources),
                    actual=sorted(f"{item[0]}@{item[1]}" for item in actual_sources),
                )
            )
        allowed_state_source_types = {"episode_script", "episode_boundary_review"}
        if artifact_kind == "dialogue_cue_sheet":
            allowed_state_source_types.update({"source_corpus", "source_event_index"})
        state_sources = {
            (item.get("artifact_key"), item.get("version"))
            for item in record.get("depends_on", [])
            if isinstance(item, dict)
            and isinstance(item.get("artifact_key"), str)
            and artifact_type(item["artifact_key"])
            in allowed_state_source_types
        }
        if state_sources != artifact_expected_sources:
            errors.append(
                issue(
                    "breakdown_state_dependencies_mismatch",
                    "制作提取表的状态依赖必须精确绑定当前全部分集剧本及对应内容边界报告",
                    artifact_key=key,
                )
            )

    def records_of(kind: str) -> list[dict[str, Any]]:
        records = payloads.get(kind, {}).get("records", [])
        for index, item in enumerate(records if isinstance(records, list) else []):
            if not isinstance(item, dict):
                errors.append(
                    issue(
                        "breakdown_record_invalid",
                        f"{ARTIFACT_TYPES[kind]} records[{index}] 必须是对象",
                        artifact_type=kind,
                        record_index=index,
                    )
                )
        return [item for item in records if isinstance(item, dict)]

    characters = records_of("character_roster")
    character_ids: dict[str, dict[str, Any]] = {}
    character_names: dict[str, str] = {}
    character_appearances: set[tuple[str, str]] = set()
    for index, record in enumerate(characters):
        character_id = record.get("character_id")
        name = record.get("name")
        if not isinstance(character_id, str) or not character_id:
            errors.append(issue("character_id_missing", "角色记录缺少 character_id", record_index=index))
            continue
        if character_id in character_ids:
            errors.append(issue("character_id_duplicate", f"角色 ID 重复：{character_id}"))
        character_ids[character_id] = record
        if not isinstance(name, str) or not name:
            errors.append(issue("character_name_missing", f"角色 {character_id} 缺少姓名"))
        else:
            aliases = record.get("aliases", [])
            if not isinstance(aliases, list) or not all(
                isinstance(alias, str) and alias.strip() for alias in aliases
            ):
                errors.append(issue("character_aliases_invalid", f"角色 {character_id} aliases 必须是非空字符串数组"))
                aliases = []
            for character_name in [name, *aliases]:
                normalized_name = character_name.strip()
                existing_id = character_names.get(normalized_name)
                if existing_id and existing_id != character_id:
                    errors.append(issue("character_name_duplicate", f"角色姓名或别名重复：{normalized_name}"))
                else:
                    character_names[normalized_name] = character_id
        appearances = record.get("appearances")
        if not isinstance(appearances, list):
            errors.append(issue("character_appearances_invalid", f"角色 {character_id} appearances 必须是数组"))
        else:
            for appearance in appearances:
                if not isinstance(appearance, dict):
                    errors.append(issue("character_appearance_invalid", f"角色 {character_id} appearance 必须是对象"))
                    continue
                scene_id = appearance.get("scene_id")
                if scene_id not in script_scenes:
                    errors.append(issue("character_scene_unknown", f"角色 {character_id} 引用了不存在场次：{scene_id}"))
                    continue
                if appearance.get("episode_id") != script_scenes[scene_id]["episode_id"]:
                    errors.append(issue("character_episode_mismatch", f"角色 {character_id} 在场次 {scene_id} 的 episode_id 不一致"))
                character_appearances.add((character_id, scene_id))

    items = records_of("prop_costume_ledger")
    item_ids: dict[str, dict[str, Any]] = {}
    item_names: dict[str, str] = {}
    item_appearances: set[tuple[str, str]] = set()
    for index, record in enumerate(items):
        item_id = record.get("item_id")
        name = record.get("name")
        category = record.get("category")
        if not isinstance(item_id, str) or not item_id:
            errors.append(issue("item_id_missing", "道具服装记录缺少 item_id", record_index=index))
            continue
        if item_id in item_ids:
            errors.append(issue("item_id_duplicate", f"物品 ID 重复：{item_id}"))
        item_ids[item_id] = record
        if not isinstance(name, str) or not name:
            errors.append(issue("item_name_missing", f"物品 {item_id} 缺少名称"))
        else:
            aliases = record.get("aliases", [])
            if not isinstance(aliases, list) or not all(
                isinstance(alias, str) and alias.strip() for alias in aliases
            ):
                errors.append(issue("item_aliases_invalid", f"物品 {item_id} aliases 必须是非空字符串数组"))
                aliases = []
            for item_name in [name, *aliases]:
                normalized_name = item_name.strip()
                existing_id = item_names.get(normalized_name)
                if existing_id and existing_id != item_id:
                    errors.append(issue("item_name_duplicate", f"物品名称或别名重复：{normalized_name}"))
                else:
                    item_names[normalized_name] = item_id
        if category not in {"prop", "costume"}:
            errors.append(issue("item_category_invalid", f"物品 {item_id} category 必须为 prop 或 costume"))
        appearances = record.get("appearances")
        if not isinstance(appearances, list):
            errors.append(issue("item_appearances_invalid", f"物品 {item_id} appearances 必须是数组"))
        else:
            for appearance in appearances:
                if not isinstance(appearance, dict):
                    errors.append(issue("item_appearance_invalid", f"物品 {item_id} appearance 必须是对象"))
                    continue
                scene_id = appearance.get("scene_id")
                if scene_id not in script_scenes:
                    errors.append(issue("item_scene_unknown", f"物品 {item_id} 引用了不存在场次：{scene_id}"))
                    continue
                if appearance.get("episode_id") != script_scenes[scene_id]["episode_id"]:
                    errors.append(issue("item_episode_mismatch", f"物品 {item_id} 在场次 {scene_id} 的 episode_id 不一致"))
                item_appearances.add((item_id, scene_id))

    scene_records = records_of("scene_catalog")
    catalog_scenes: dict[str, dict[str, Any]] = {}
    scene_required_fields = (
        "scene_id",
        "episode_id",
        "location_id",
        "location_name",
        "time",
        "space",
        "character_ids",
        "item_ids",
        "entry_state",
        "exit_state",
    )
    scene_required_string_fields = {
        "scene_id",
        "episode_id",
        "location_id",
        "location_name",
        "time",
        "space",
        "entry_state",
        "exit_state",
    }
    allowed_scene_times = {
        "日", "夜", "晨", "昼", "午", "昏", "清晨", "早晨", "上午",
        "中午", "下午", "傍晚", "黄昏", "深夜", "凌晨", "白天",
    }
    allowed_scene_spaces = {"内", "外", "内景", "外景"}
    location_names_by_id: dict[str, str] = {}
    for index, record in enumerate(scene_records):
        scene_id = record.get("scene_id")
        if not isinstance(scene_id, str) or not scene_id:
            errors.append(issue("catalog_scene_id_missing", "场景记录缺少 scene_id", record_index=index))
            continue
        if scene_id in catalog_scenes:
            errors.append(issue("catalog_scene_duplicate", f"场景表重复：{scene_id}"))
        catalog_scenes[scene_id] = record
        for field in scene_required_fields:
            if field not in record or record[field] is None:
                errors.append(issue("catalog_scene_field_missing", f"场景 {scene_id} 缺少 {field}"))
            elif field in scene_required_string_fields and (
                not isinstance(record[field], str) or not record[field].strip()
            ):
                errors.append(issue("catalog_scene_field_empty", f"场景 {scene_id} 的 {field} 必须是非空字符串"))
        if record.get("time") not in allowed_scene_times:
            errors.append(issue("catalog_scene_time_invalid", f"场景 {scene_id} 的 time 值无效"))
        if record.get("space") not in allowed_scene_spaces:
            errors.append(issue("catalog_scene_space_invalid", f"场景 {scene_id} 的 space 值无效"))
        location_id = record.get("location_id")
        catalog_location_name = normalize_scene_location(record.get("location_name"))
        if isinstance(location_id, str) and location_id.strip() and catalog_location_name:
            existing_location_name = location_names_by_id.get(location_id)
            if existing_location_name is None:
                location_names_by_id[location_id] = catalog_location_name
            elif existing_location_name != catalog_location_name:
                errors.append(
                    issue(
                        "catalog_location_id_name_conflict",
                        f"地点 ID {location_id} 绑定了不同的 location_name",
                        scene_id=scene_id,
                        location_id=location_id,
                    )
                )
        if scene_id not in script_scenes:
            errors.append(issue("catalog_scene_extra", f"场景表出现剧本不存在的场次：{scene_id}"))
        elif record.get("episode_id") != script_scenes[scene_id]["episode_id"]:
            errors.append(issue("catalog_episode_mismatch", f"场景 {scene_id} episode_id 与剧本不一致"))
        if scene_id in script_scenes:
            script_scene = script_scenes[scene_id]
            if catalog_location_name != script_scene.get("location_name"):
                errors.append(
                    issue(
                        "catalog_location_name_mismatch",
                        f"场景 {scene_id} location_name 与剧本场头不一致",
                        expected=script_scene.get("location_name"),
                        actual=catalog_location_name,
                    )
                )
            catalog_time = normalize_scene_time(record.get("time"))
            if catalog_time != script_scene.get("time"):
                errors.append(
                    issue(
                        "catalog_time_mismatch",
                        f"场景 {scene_id} time 与剧本场头不一致",
                        expected=script_scene.get("time"),
                        actual=catalog_time,
                    )
                )
            catalog_space = normalize_scene_space(record.get("space"))
            if catalog_space != script_scene.get("space"):
                errors.append(
                    issue(
                        "catalog_space_mismatch",
                        f"场景 {scene_id} space 与剧本场头不一致",
                        expected=script_scene.get("space"),
                        actual=catalog_space,
                    )
                )
        character_id_values = record.get("character_ids")
        if not isinstance(character_id_values, list) or not all(
            isinstance(value, str) and value for value in character_id_values
        ):
            errors.append(issue("catalog_character_ids_invalid", f"场景 {scene_id} character_ids 必须是字符串数组"))
            character_id_values = []
        item_id_values = record.get("item_ids")
        if not isinstance(item_id_values, list) or not all(
            isinstance(value, str) and value for value in item_id_values
        ):
            errors.append(issue("catalog_item_ids_invalid", f"场景 {scene_id} item_ids 必须是字符串数组"))
            item_id_values = []
        for character_id in character_id_values:
            if character_id not in character_ids:
                errors.append(issue("catalog_character_unknown", f"场景 {scene_id} 引用未知角色：{character_id}"))
        for item_id in item_id_values:
            if item_id not in item_ids:
                errors.append(issue("catalog_item_unknown", f"场景 {scene_id} 引用未知物品：{item_id}"))
        if scene_id in script_scenes:
            expected_character_ids: set[str] = set()
            for declared_name in script_scenes[scene_id]["characters"]:
                character_id = character_names.get(declared_name)
                if character_id is None:
                    errors.append(issue("roster_character_missing", f"角色表缺少剧本人物：{declared_name}", scene_id=scene_id))
                else:
                    expected_character_ids.add(character_id)
                    if (character_id, scene_id) not in character_appearances:
                        errors.append(issue("character_appearance_missing", f"角色 {declared_name} 缺少场次 {scene_id} 的 appearance"))
            actual_character_ids = set(character_id_values)
            if actual_character_ids != expected_character_ids:
                errors.append(
                    issue(
                        "catalog_characters_mismatch",
                        f"场景 {scene_id} 的角色 ID 与剧本人物不一致",
                        missing=sorted(expected_character_ids - actual_character_ids),
                        extra=sorted(actual_character_ids - expected_character_ids),
                    )
                )
            expected_item_ids: set[str] = set()
            for declared_name in script_scenes[scene_id]["props"]:
                item_id = item_names.get(declared_name)
                if item_id is None:
                    errors.append(issue("ledger_prop_missing", f"道具服装台账缺少剧本道具：{declared_name}", scene_id=scene_id))
                else:
                    expected_item_ids.add(item_id)
                    if (item_id, scene_id) not in item_appearances:
                        errors.append(issue("item_appearance_missing", f"物品 {declared_name} 缺少场次 {scene_id} 的 appearance"))
            actual_item_ids = set(item_id_values)
            if actual_item_ids != expected_item_ids:
                errors.append(
                    issue(
                        "catalog_items_mismatch",
                        f"场景 {scene_id} 的物品 ID 与剧本道具不一致",
                        missing=sorted(expected_item_ids - actual_item_ids),
                        extra=sorted(actual_item_ids - expected_item_ids),
                    )
                )

    for scene_id in sorted(set(script_scenes) - set(catalog_scenes)):
        errors.append(issue("catalog_scene_missing", f"场景表缺少剧本场次：{scene_id}"))

    for character_id, scene_id in sorted(character_appearances):
        declared_ids = {
            character_names.get(name) for name in script_scenes[scene_id]["characters"]
        }
        if character_id not in declared_ids:
            errors.append(issue("character_appearance_extra", f"角色 {character_id} 的 appearance 在剧本场次 {scene_id} 未声明"))
    for item_id, scene_id in sorted(item_appearances):
        declared_ids = {item_names.get(name) for name in script_scenes[scene_id]["props"]}
        if item_id not in declared_ids:
            errors.append(issue("item_appearance_extra", f"物品 {item_id} 的 appearance 在剧本场次 {scene_id} 未声明"))

    cue_records = records_of("dialogue_cue_sheet")
    cue_ids: set[str] = set()
    extracted_cues: list[tuple[str, str, str, str, str]] = []
    allowed_cue_types = {"dialogue", "vo", "os", "environment", "sfx"}
    for index, record in enumerate(cue_records):
        cue_id = record.get("cue_id")
        scene_id = record.get("scene_id")
        cue_type = record.get("type")
        cue_text = record.get("text")
        if not isinstance(cue_id, str) or not cue_id:
            errors.append(issue("cue_id_missing", "声音记录缺少 cue_id", record_index=index))
        elif cue_id in cue_ids:
            errors.append(issue("cue_id_duplicate", f"cue_id 重复：{cue_id}"))
        else:
            cue_ids.add(cue_id)
        if cue_type not in allowed_cue_types:
            errors.append(issue("cue_type_invalid", f"声音记录 {cue_id} type 无效"))
            continue
        if scene_id not in script_scenes:
            errors.append(issue("cue_scene_unknown", f"声音记录 {cue_id} 引用不存在场次：{scene_id}"))
            continue
        if record.get("episode_id") != script_scenes[scene_id]["episode_id"]:
            errors.append(issue("cue_episode_mismatch", f"声音记录 {cue_id} 的 episode_id 与场次不一致"))
        if not isinstance(cue_text, str) or not cue_text.strip():
            errors.append(issue("cue_text_missing", f"声音记录 {cue_id} 缺少 text"))
            continue
        if cue_type in {"dialogue", "vo", "os"}:
            speaker_id = record.get("speaker_id")
            speaker_name = record.get("speaker_name")
            if speaker_id not in character_ids:
                errors.append(issue("cue_speaker_unknown", f"声音记录 {cue_id} 引用未知 speaker_id：{speaker_id}"))
            if not isinstance(speaker_name, str) or not speaker_name:
                errors.append(issue("cue_speaker_name_missing", f"声音记录 {cue_id} 缺少 speaker_name"))
                continue
            if character_names.get(speaker_name) != speaker_id:
                errors.append(
                    issue(
                        "cue_speaker_mismatch",
                        f"声音记录 {cue_id} 的 speaker_id 与 speaker_name 不对应",
                    )
                )
            extracted_cues.append(
                (
                    scene_id,
                    speaker_name,
                    cue_type,
                    record.get("delivery_mode"),
                    normalized_text(cue_text),
                )
            )
        elif normalized_text(cue_text) not in normalized_text(script_scenes[scene_id]["text"]):
            errors.append(issue("cue_not_in_script", f"声音记录 {cue_id} 的内容未出现在剧本场次中"))

    expected_counter = Counter(script_cues)
    actual_counter = Counter(extracted_cues)
    for cue, count in (expected_counter - actual_counter).items():
        errors.append(issue("cue_missing", f"台词声音表缺少 {count} 条剧本声音：{cue}"))
    for cue, count in (actual_counter - expected_counter).items():
        errors.append(issue("cue_extra", f"台词声音表多出或改写了 {count} 条声音：{cue}"))

    return {
        "valid": not errors,
        "project": str(project_path),
        "expected_episodes": expected_episodes,
        "batch_id": batch_id,
        "episode_ids": requested_episode_ids,
        "allow_awaiting": allow_awaiting,
        "errors": errors,
        "warnings": warnings,
        "summary": {
            "error_count": len(errors),
            "warning_count": len(warnings),
            "episode_count": len(episode_records),
            "script_scene_count": len(script_scenes),
            "character_count": len(character_ids),
            "catalog_scene_count": len(catalog_scenes),
            "item_count": len(item_ids),
            "script_cue_count": len(script_cues),
            "extracted_cue_count": len(extracted_cues),
        },
    }


def command_validate_breakdowns(args: argparse.Namespace) -> int:
    project_path = Path(args.project).expanduser().resolve()
    result = validate_breakdowns_state(
        project_path,
        expected_episodes=args.expected_episodes,
        allow_awaiting=args.allow_awaiting,
        batch_id=args.batch,
    )
    print_json(result)
    return 0 if result["valid"] else 1


def command_validate_script(args: argparse.Namespace) -> int:
    script_path = Path(args.path).expanduser().resolve()
    target_duration = getattr(args, "target_duration_seconds", None)
    if target_duration is not None and target_duration <= 0:
        raise ToolError("--target-duration-seconds 必须是大于0的整数秒")
    result = validate_script_file(
        script_path,
        fragment=args.fragment,
        target_duration_seconds=target_duration,
    )
    print_json(result)
    return 0 if result["valid"] else 1


def validate_seedance_state(
    project_path: Path, expected_episodes: int
) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if expected_episodes < 1:
        return {
            "compatible": False,
            "project": str(project_path),
            "expected_episodes": expected_episodes,
            "errors": [issue("expected_episodes_invalid", "预期集数必须大于0")],
            "warnings": [],
            "plans": [],
        }
    state_result = validate_state(project_path)
    errors.extend(state_result.get("errors", []))
    try:
        _, state = load_state(project_path)
    except ToolError as exc:
        errors.append(issue("state_unreadable", str(exc)))
        return {
            "compatible": False,
            "project": str(project_path),
            "expected_episodes": expected_episodes,
            "errors": errors,
            "warnings": warnings,
            "plans": [],
        }
    specified = project_expected_episodes(project_path, state)
    if specified is None:
        errors.append(issue("project_expected_episodes_unknown", "无法从已确认项目规格读取总集数"))
    elif specified != expected_episodes:
        errors.append(
            issue(
                "expected_episodes_mismatch",
                "Seedance校验参数与项目规格总集数不一致",
                specified=specified,
                requested=expected_episodes,
            )
        )
    required_keys = {
        f"seedance_execution_plan:E{number:03d}"
        for number in range(1, expected_episodes + 1)
    }
    current_plans = {
        key: record
        for key, record in latest_records_of_type(state, "seedance_execution_plan")
    }
    plans: list[dict[str, Any]] = []
    for key in sorted(required_keys):
        record = current_plans.get(key)
        if record is None or not confirmed_record_is_usable(
            state, key, record, project_path
        ):
            errors.append(
                issue(
                    "seedance_plan_not_confirmed",
                    f"缺少当前已确认且通过内容边界门禁的Seedance执行计划：{key}",
                    artifact_key=key,
                )
            )
            continue
        errors.extend(
            validate_structured_development_artifact(
                project_path, state, key, record
            )
        )
        review = matching_boundary_review(state, key, record, project_path)
        plans.append(
            {
                "artifact_key": key,
                "version": record.get("version"),
                "path": record.get("path"),
                "boundary_review": (
                    {
                        "artifact_key": review[0],
                        "version": review[1].get("version"),
                    }
                    if review is not None
                    else None
                ),
            }
        )
    for key in sorted(set(current_plans) - required_keys):
        record = current_plans[key]
        if record.get("status") == "confirmed":
            errors.append(
                issue(
                    "seedance_plan_unexpected",
                    "存在项目规格集数之外的已确认Seedance执行计划",
                    artifact_key=key,
                )
            )
    warnings.append(
        issue(
            "seedance_runtime_not_verified",
            "此命令只核验文字执行层、版本、原著边界、台词覆盖与模型能力快照；不提交视频任务，也不能证明实际生成效果。",
        )
    )
    return {
        "compatible": not errors,
        "project": str(project_path),
        "expected_episodes": expected_episodes,
        "errors": errors,
        "warnings": warnings,
        "plans": plans,
        "summary": {
            "error_count": len(errors),
            "warning_count": len(warnings),
            "confirmed_plan_count": len(plans),
        },
    }


def command_validate_seedance(args: argparse.Namespace) -> int:
    result = validate_seedance_state(
        Path(args.project).expanduser().resolve(),
        expected_episodes=args.expected_episodes,
    )
    print_json(result)
    return 0 if result["compatible"] else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="管理小说改编漫剧的本地项目状态与制品"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="初始化项目并安全复制原始内容")
    init_parser.add_argument("project", help="项目目录")
    init_parser.add_argument("--name", help="项目名称，默认为目录名")
    init_parser.add_argument(
        "--source", action="append", default=[], help="原始内容文件，可重复传入"
    )
    init_parser.add_argument(
        "--expected-episodes",
        type=int,
        help=(
            "目标集数提示，记入 expected_episodes_hint，供 project_spec 确认前定义批次使用；"
            "不用于检查上传文件完整度，交付门禁仍以已确认 project_spec 为权威"
        ),
    )
    init_parser.add_argument(
        "--source-kind",
        choices=SOURCE_KINDS,
        default=DEFAULT_SOURCE_KIND,
        help="来源类型：自营小说、故事线或已发表小说",
    )
    init_parser.add_argument(
        "--official-review",
        action="store_true",
        help="仅 published_novel 可主动开启用户指定官网审核",
    )
    init_parser.add_argument("--official-url", help="用户指定的官网或正版发布页面")
    init_parser.add_argument(
        "--garble-threshold",
        type=float,
        default=None,
        help="已废弃兼容参数；v0.8 不自动检查上传文件",
    )
    init_parser.set_defaults(handler=command_init)

    show_parser = subparsers.add_parser("show", help="显示项目状态")
    show_parser.add_argument("project", help="项目目录")
    show_parser.add_argument("--summary", action="store_true", help="只显示摘要")
    show_parser.set_defaults(handler=command_show)

    define_batch_parser = subparsers.add_parser(
        "define-batch", help="定义不可重叠的批次集号范围"
    )
    define_batch_parser.add_argument("project", help="项目目录")
    define_batch_parser.add_argument("batch_id", help="批次 ID，如 B01")
    define_batch_parser.add_argument(
        "episode_ids", nargs="+", help="批次包含的集号，如 E001 E002"
    )
    define_batch_parser.add_argument("--note", help="批次说明")
    define_batch_parser.add_argument(
        "--confirmed-by-user",
        action="store_true",
        help="rolling_batch schema v2新增批次时确认用户已明确授权该批次范围",
    )
    define_batch_parser.set_defaults(handler=command_define_batch)

    stage_parser = subparsers.add_parser("set-stage", help="设置工作流阶段状态")
    stage_parser.add_argument("project", help="项目目录")
    stage_parser.add_argument("stage", choices=tuple(STAGES), help="阶段 key")
    stage_parser.add_argument("status", choices=tuple(sorted(STAGE_STATUSES)), help="新状态")
    stage_parser.add_argument("--note", help="备注")
    stage_parser.add_argument(
        "--machine-time-seconds",
        type=float,
        help="本次阶段变更对应的机器计算耗时（秒），写入 stage 历史记录",
    )
    stage_parser.add_argument(
        "--human-wait-seconds",
        type=float,
        help="本次阶段变更对应的人工等待耗时（秒），写入 stage 历史记录",
    )
    stage_parser.set_defaults(handler=command_set_stage)

    register_parser = subparsers.add_parser("register-artifact", help="注册制品新版本")
    register_parser.add_argument("project", help="项目目录")
    register_parser.add_argument("artifact_key", help="制品 key，可用类型:范围")
    register_parser.add_argument("path", help="项目内的制品文件路径")
    register_parser.add_argument(
        "--status",
        choices=("draft", "awaiting_approval"),
        default="draft",
        help="注册状态（默认 draft）；确认必须使用 approve",
    )
    register_parser.add_argument(
        "--depends-on",
        action="append",
        default=[],
        metavar="KEY[@VERSION]",
        help="上游制品，可重复传入；省略版本时使用最新版",
    )
    register_parser.add_argument("--note", help="备注")
    register_parser.set_defaults(handler=command_register_artifact)

    approve_parser = subparsers.add_parser("approve", help="人工确认制品的最新版本")
    approve_parser.add_argument("project", help="项目目录")
    approve_parser.add_argument("artifact_key", help="制品 key")
    approve_parser.add_argument("--version", type=int, help="版本号，默认最新版")
    approve_parser.add_argument("--approved-by", default="user", help="确认人，默认 user")
    approve_parser.add_argument("--note", help="审批意见")
    approve_parser.set_defaults(handler=command_approve)

    stale_parser = subparsers.add_parser("mark-stale", help="将制品标记为需重新评估")
    stale_parser.add_argument("project", help="项目目录")
    stale_parser.add_argument("artifact_key", help="制品 key")
    stale_parser.add_argument("--version", type=int, help="版本号，默认最新版")
    stale_parser.add_argument("--reason", required=True, help="标记原因")
    stale_parser.add_argument("--no-cascade", action="store_true", help="不级联标记下游制品")
    stale_parser.set_defaults(handler=command_mark_stale)

    add_source_parser = subparsers.add_parser(
        "add-source", help="向已有项目增量补传新原著来源（追更章节），自动标脏来源依赖链"
    )
    add_source_parser.add_argument("project", help="项目目录")
    add_source_parser.add_argument("source", help="新来源文件路径")
    add_source_parser.add_argument("--reason", help="补传说明，默认记录文件名")
    add_source_parser.add_argument(
        "--garble-threshold",
        type=float,
        default=None,
        help="已废弃兼容参数；v0.8 不自动检查上传文件",
    )
    add_source_parser.set_defaults(handler=command_add_source)

    partition_parser = subparsers.add_parser(
        "plan-source-partitions", help="按语义单元与容量预算生成只读原著分析分片计划"
    )
    partition_parser.add_argument("project", help="项目目录")
    partition_parser.add_argument("--source-corpus", required=True, help="项目内 source_corpus JSON 路径")
    partition_parser.add_argument("--policy", required=True, help="项目内分片策略 JSON 路径")
    partition_parser.add_argument("--output", required=True, help="项目内分片计划输出路径")
    partition_parser.set_defaults(handler=command_plan_source_partitions)

    merge_shards_parser = subparsers.add_parser(
        "merge-source-analysis-shards", help="校验并合并独立原著分析分片；不修改项目状态"
    )
    merge_shards_parser.add_argument("project", help="项目目录")
    merge_shards_parser.add_argument("--plan", required=True, help="项目内分片计划 JSON 路径")
    merge_shards_parser.add_argument("--shard-dir", required=True, help="项目内分片结果目录")
    merge_shards_parser.add_argument("--output", required=True, help="项目内合并结果输出路径")
    merge_shards_parser.set_defaults(handler=command_merge_source_analysis_shards)

    register_analysis_parser = subparsers.add_parser(
        "register-source-analysis",
        help="把章节分析结果按章节哈希和契约版本幂等登记到新的registry文件",
    )
    register_analysis_parser.add_argument("project", help="项目目录")
    register_analysis_parser.add_argument("--source-corpus", required=True, help="项目内source_corpus JSON")
    register_analysis_parser.add_argument("--registry", required=True, help="项目内chapter registry JSON")
    register_analysis_parser.add_argument("--source-unit-id", required=True)
    register_analysis_parser.add_argument("--analysis", required=True, help="项目内章节分析JSON")
    register_analysis_parser.add_argument("--contract-version", type=int, required=True)
    register_analysis_parser.add_argument("--output", required=True, help="项目内新registry输出路径")
    register_analysis_parser.set_defaults(handler=command_register_source_analysis)

    rolling_window_parser = subparsers.add_parser(
        "plan-rolling-source-window",
        help="优先复用carryover和已分析章节，只规划下一批需要的新章节",
    )
    rolling_window_parser.add_argument("project", help="项目目录")
    rolling_window_parser.add_argument("--source-corpus", required=True)
    rolling_window_parser.add_argument("--registry", required=True)
    rolling_window_parser.add_argument("--progress", required=True)
    rolling_window_parser.add_argument("--window-size", type=int, default=3)
    rolling_window_parser.add_argument("--output", required=True)
    rolling_window_parser.set_defaults(handler=command_plan_rolling_source_window)

    context_parser = subparsers.add_parser(
        "build-production-context-manifest",
        help="生成生产任务允许加载的最小插件上下文清单",
    )
    context_parser.add_argument("project", help="项目目录")
    context_parser.add_argument("--stage", required=True, choices=tuple(STAGES))
    context_parser.add_argument("--output", required=True, help="项目内清单输出路径")
    context_parser.set_defaults(handler=command_build_production_context_manifest)

    episode_delivery_parser = subparsers.add_parser(
        "render-episode-delivery", help="从同版本剧本、人物锚点和分镜计划生成逐集DOCX与HTML"
    )
    episode_delivery_parser.add_argument("project", help="项目目录")
    episode_delivery_parser.add_argument("episode", help="集号，如 E001")
    episode_delivery_parser.set_defaults(handler=command_render_episode_delivery)

    render_parser = subparsers.add_parser(
        "render-storyboard", help="把已确认的 AI 分镜计划渲染成单文件 HTML 故事板(只读)"
    )
    render_parser.add_argument("project", help="项目目录")
    render_parser.add_argument("episode", help="集号,如 E001")
    render_parser.add_argument("--output", help="输出路径,默认 10_AI视频执行包/<集号>_故事板.html")
    render_parser.set_defaults(handler=command_render_storyboard)

    validate_project_parser = subparsers.add_parser("validate-project", help="校验项目状态、目录和制品路径")
    validate_project_parser.add_argument("project", help="项目目录")
    validate_project_parser.set_defaults(handler=command_validate_project)

    validate_handoff_parser = subparsers.add_parser(
        "validate-handoff", help="校验制作就绪剧本包的制品、状态与剧集覆盖"
    )
    validate_handoff_parser.add_argument("project", help="项目目录")
    validate_handoff_parser.add_argument(
        "--expected-episodes",
        type=int,
        required=True,
        help="预期总集数；要求 E001...EN 全部确认且不存在额外集",
    )
    validate_handoff_parser.add_argument(
        "--require-final-package",
        action="store_true",
        help="同时要求已经存在并确认 final_package",
    )
    validate_handoff_parser.add_argument(
        "--series", action="store_true", help="按已确认批次包执行全剧汇总校验"
    )
    validate_handoff_parser.set_defaults(handler=command_validate_handoff)

    validate_breakdowns_parser = subparsers.add_parser(
        "validate-breakdowns", help="校验四类制作提取表及其与剧本的双向追溯"
    )
    validate_breakdowns_parser.add_argument("project", help="项目目录")
    validate_breakdowns_parser.add_argument(
        "--expected-episodes", type=int, help="预期总集数"
    )
    validate_breakdowns_parser.add_argument(
        "--batch", help="只校验已定义批次，如 B01"
    )
    validate_breakdowns_parser.add_argument(
        "--allow-awaiting",
        action="store_true",
        help="质量复核阶段允许使用 awaiting_approval 制品",
    )
    validate_breakdowns_parser.set_defaults(handler=command_validate_breakdowns)

    build_handoff_parser = subparsers.add_parser(
        "build-handoff", help="打包已确认制品并登记 final_package"
    )
    build_handoff_parser.add_argument("project", help="项目目录")
    build_handoff_parser.add_argument(
        "--expected-episodes",
        type=int,
        help="预期总集数；--series 或旧全剧兼容模式使用",
    )
    build_scope_group = build_handoff_parser.add_mutually_exclusive_group()
    build_scope_group.add_argument(
        "--batch", help="只打包已定义且通过全部门禁的批次，如 B01"
    )
    build_scope_group.add_argument(
        "--series", action="store_true", help="汇总全部当前已确认批次包"
    )
    build_handoff_parser.add_argument(
        "--output-name", help="09_定稿交付下的新目录名；省略时自动生成且不覆盖"
    )
    build_handoff_parser.set_defaults(handler=command_build_handoff)

    validate_script_parser = subparsers.add_parser("validate-script", help="校验单集漫剧文学剧本结构")
    validate_script_parser.add_argument("path", help="UTF-8 剧本文件")
    validate_script_parser.add_argument(
        "--fragment", action="store_true", help="按试写片段校验，不强制要求整集钩子"
    )
    validate_script_parser.add_argument(
        "--target-duration-seconds",
        type=int,
        help="单集目标时长（秒）；提供后按字数推算净对白秒数并给出预警，省略则不做时长推算",
    )
    validate_script_parser.set_defaults(handler=command_validate_script)

    validate_seedance_parser = subparsers.add_parser(
        "validate-seedance",
        help="校验纯文字Seedance 2.0执行计划、台词覆盖和内容边界",
    )
    validate_seedance_parser.add_argument("project", help="项目目录")
    validate_seedance_parser.add_argument(
        "--expected-episodes",
        type=int,
        required=True,
        help="预期总集数；要求 E001...EN 均有当前确认执行计划",
    )
    validate_seedance_parser.set_defaults(handler=command_validate_seedance)

    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        return args.handler(args)
    except ToolError as exc:
        print_json({"ok": False, "error": str(exc)})
        return 2
    except KeyboardInterrupt:
        print_json({"ok": False, "error": "操作已取消"})
        return 130


if __name__ == "__main__":
    sys.exit(main())
