#!/usr/bin/env python3
"""File-backed contracts for short-lived AI Director agent orchestration."""

from __future__ import annotations

import contextlib
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import tempfile
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None


SCHEMA_VERSION = 1
RUNTIME_VERSION = "2"
PLUGIN_VERSION = "0.10.0-zimika.1"
RULE_VERSION = "production-control-v1"
EXECUTION_CONTROL_SCHEMA_VERSION = 1
DEFAULT_MAX_PARALLEL_TASKS = 2
MAX_PARALLEL_TASKS = 8
RUNTIME_DIRECTORY = ".ai-director/runtime"
PLANNED_TASK_LEASE_SECONDS = 900
TIMING_FIELDS = (
    "machine_time_seconds",
    "model_time_seconds",
    "agent_time_seconds",
    "human_wait_seconds",
    "reconnect_wait_seconds",
)
SUPPORTED_ACCEPTANCE_COMMANDS = {
    "none",
    "schema-only",
    "validate-script",
}
SUPPORTED_SCHEDULING_MODES = {"serial", "independent"}
SUPPORTED_EXECUTION_MODES = {"production", "development"}
PRODUCTION_FORBIDDEN_OPERATIONS = {
    "development_test",
    "design_review",
    "skill_edit",
    "source_edit",
}
EXPLICIT_DELEGATION_MARKERS = (
    "继续执行",
    "按方案完成",
    "按当前方案完成",
    "continue execution",
    "complete as planned",
)
NEGATED_DELEGATION_PATTERNS = (
    re.compile(
        r"(?:不要|请勿|禁止|停止|别|不再|不能|不可|不应|无需|不需要|不必|不)"
        r"\s*(?:继续执行|按(?:当前)?方案完成)"
    ),
    re.compile(
        r"\b(?:do\s+not|don't|dont|never|stop|cannot|can't|cant|"
        r"should\s+not|shouldn't|shouldnt|need\s+not|no\s+need\s+to)\s+"
        r"(?:continue\s+execution|complete\s+as\s+planned)\b"
    ),
)
ERROR_CLASSES = {
    "none",
    "429_too_many_requests",
    "stream_disconnect_without_completion",
    "context_window_exceeded",
    "other",
}
INDEPENDENT_TASK_TYPES = {
    "source_analysis",
    "production_extraction",
    "character_extraction",
    "scene_extraction",
    "prop_costume_extraction",
    "dialogue_extraction",
    "docx_render",
    "html_render",
    "storyboard_render",
}
SERIAL_TASK_TYPES = {
    "episode_script",
    "episode_boundary_review",
    "global_id_normalization",
    "timeline",
    "continuity",
    "batch_close",
    "project_state",
}
RECOVERY_POLICIES = {
    "429_too_many_requests": {
        "action": "rate_limit_backoff",
        "next_step": "等待服务容量恢复后使用同一输入版本重试",
        "preserve_partial_output": False,
    },
    "stream_disconnect_without_completion": {
        "action": "fresh_agent_reconnect",
        "next_step": "关闭当前智能体并从结果检查点重新连接",
        "preserve_partial_output": True,
    },
    "context_window_exceeded": {
        "action": "fresh_agent_reduced_context",
        "next_step": "关闭当前智能体，按任务包允许路径缩小上下文后恢复",
        "preserve_partial_output": True,
    },
    "other": {
        "action": "bounded_retry_then_block",
        "next_step": "按同一任务包进行最后一次受控重试，仍失败则阻断",
        "preserve_partial_output": False,
    },
}

_LOCK_REGISTRY_GUARD = threading.Lock()
_LOCK_REGISTRY: dict[str, threading.RLock] = {}
_HELD_LOCK_HANDLES: dict[str, Any] = {}


class AgentRuntimeError(ValueError):
    """Raised when a task, result, or runtime transition violates its contract."""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def issue(code: str, message: str, **location: Any) -> dict[str, Any]:
    return {"code": code, "message": message, **location}


def canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def skill_root() -> Path:
    return Path(__file__).resolve().parents[1]


def plugin_root() -> Path:
    return Path(__file__).resolve().parents[3]


def runtime_environment_snapshot() -> dict[str, Any]:
    root = plugin_root()
    manifest_path = root / ".codex-plugin/plugin.json"
    skill_path = skill_root() / "SKILL.md"
    project_tool_path = Path(__file__).resolve().with_name("project_tool.py")
    component_paths = {
        "plugin_manifest": manifest_path,
        "skill": skill_path,
        "agent_runtime": Path(__file__).resolve(),
        "project_tool": project_tool_path,
    }
    components: dict[str, dict[str, Any]] = {}
    for name, path in component_paths.items():
        components[name] = {
            "path": str(path),
            "exists": path.is_file(),
            "sha256": sha256_file(path) if path.is_file() else None,
        }
    manifest_version = None
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            manifest = None
        if isinstance(manifest, dict):
            manifest_version = manifest.get("version")
    try:
        python_package_version = importlib.metadata.version("pip")
    except importlib.metadata.PackageNotFoundError:
        python_package_version = "unavailable"
    return {
        "plugin_version": manifest_version,
        "runtime_version": RUNTIME_VERSION,
        "rule_version": RULE_VERSION,
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.system(),
        "platform_release": platform.release(),
        "pip_version": python_package_version,
        "environment_revision": os.environ.get(
            "AI_DIRECTOR_ENVIRONMENT_REVISION", ""
        ),
        "components": components,
    }


def validate_environment_snapshot(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    if snapshot.get("plugin_version") != PLUGIN_VERSION:
        errors.append(
            issue(
                "plugin_version_mismatch",
                "运行代码版本与plugin.json不一致",
                expected=PLUGIN_VERSION,
                actual=snapshot.get("plugin_version"),
            )
        )
    components = snapshot.get("components")
    if not isinstance(components, dict):
        return errors + [
            issue("runtime_components_invalid", "运行组件快照无效")
        ]
    for name in ("plugin_manifest", "skill", "agent_runtime", "project_tool"):
        component = components.get(name)
        if not isinstance(component, dict) or component.get("exists") is not True:
            errors.append(
                issue(
                    "runtime_component_missing",
                    f"生产运行组件缺失：{name}",
                    component=name,
                )
            )
        elif not isinstance(component.get("sha256"), str):
            errors.append(
                issue(
                    "runtime_component_hash_missing",
                    f"生产运行组件缺少散列：{name}",
                    component=name,
                )
            )
    return errors


def build_preflight_fingerprint(
    *,
    project_id: str,
    project_schema_version: int,
    environment_snapshot: dict[str, Any],
) -> str:
    return canonical_sha256(
        {
            "project_id": project_id,
            "project_schema_version": project_schema_version,
            "environment": environment_snapshot,
        }
    )


def empty_execution_control() -> dict[str, Any]:
    return {
        "schema_version": EXECUTION_CONTROL_SCHEMA_VERSION,
        "status": "not_ready",
        "execution_mode": None,
        "mode_locked_at": None,
        "development_task_id": None,
        "preflight": {
            "status": "not_run",
            "fingerprint": None,
            "run_count": 0,
            "reuse_count": 0,
            "failure_generation": 0,
            "checked_failure_generation": 0,
            "last_failure": None,
            "environment": None,
            "checked_at": None,
        },
        "delegation_authorizations": [],
        "decision_notices": [],
        "active_blocker": None,
    }


def ensure_execution_control(runtime: dict[str, Any]) -> dict[str, Any]:
    control = runtime.get("execution_control")
    if not isinstance(control, dict):
        control = empty_execution_control()
        runtime["execution_control"] = control
    defaults = empty_execution_control()
    for key, value in defaults.items():
        control.setdefault(key, value)
    preflight = control.get("preflight")
    if not isinstance(preflight, dict):
        preflight = defaults["preflight"].copy()
        control["preflight"] = preflight
    for key, value in defaults["preflight"].items():
        preflight.setdefault(key, value)
    for field in ("delegation_authorizations", "decision_notices"):
        if not isinstance(control.get(field), list):
            control[field] = []
    return control


def lock_execution_mode(
    control: dict[str, Any],
    requested_mode: str,
    *,
    development_task_id: str | None = None,
) -> None:
    if requested_mode not in SUPPORTED_EXECUTION_MODES:
        raise AgentRuntimeError("execution_mode_invalid")
    if requested_mode == "development" and not development_task_id:
        raise AgentRuntimeError("development_task_id_required")
    current_mode = control.get("execution_mode")
    if current_mode is not None and current_mode != requested_mode:
        raise AgentRuntimeError("execution_mode_locked")
    if current_mode is None:
        control["execution_mode"] = requested_mode
        control["mode_locked_at"] = now_iso()
        control["development_task_id"] = (
            development_task_id if requested_mode == "development" else None
        )
    elif (
        requested_mode == "development"
        and control.get("development_task_id") != development_task_id
    ):
        raise AgentRuntimeError("development_task_id_locked")


def preflight_action(
    control: dict[str, Any],
    fingerprint: str,
) -> tuple[bool, str]:
    preflight = control["preflight"]
    previous_fingerprint = preflight.get("fingerprint")
    if previous_fingerprint is not None and previous_fingerprint != fingerprint:
        return True, "environment_changed"
    if preflight.get("status") != "execution_ready":
        return True, "initial"
    if int(preflight.get("failure_generation", 0)) > int(
        preflight.get("checked_failure_generation", 0)
    ):
        return True, "execution_failure"
    preflight["reuse_count"] = int(preflight.get("reuse_count", 0)) + 1
    return False, "unchanged"


def mark_preflight_ready(
    control: dict[str, Any],
    *,
    fingerprint: str,
    environment_snapshot: dict[str, Any],
) -> None:
    preflight = control["preflight"]
    preflight.update(
        {
            "status": "execution_ready",
            "fingerprint": fingerprint,
            "run_count": int(preflight.get("run_count", 0)) + 1,
            "checked_failure_generation": int(
                preflight.get("failure_generation", 0)
            ),
            "environment": environment_snapshot,
            "checked_at": now_iso(),
        }
    )
    blocker = control.get("active_blocker")
    control["status"] = (
        "blocked"
        if isinstance(blocker, dict) and blocker.get("status") == "active"
        else "execution_ready"
    )


def require_execution_ready(
    control: dict[str, Any],
    *,
    fingerprint: str,
    allow_active_blocker: bool = False,
) -> None:
    preflight = control.get("preflight")
    if not isinstance(preflight, dict) or preflight.get("status") != "execution_ready":
        raise AgentRuntimeError("execution_preflight_required")
    if preflight.get("fingerprint") != fingerprint:
        preflight["status"] = "stale"
        control["status"] = "preflight_required"
        raise AgentRuntimeError("execution_preflight_stale")
    blocker = control.get("active_blocker")
    if (
        isinstance(blocker, dict)
        and blocker.get("status") == "active"
        and not allow_active_blocker
    ):
        codes = ",".join(blocker.get("codes") or [])
        raise AgentRuntimeError(
            f"active_execution_blocker:{blocker.get('blocker_id')}:{codes}"
        )


def mark_execution_failure(
    control: dict[str, Any],
    *,
    task_id: str,
    error_code: str | None,
) -> None:
    preflight = control["preflight"]
    preflight["failure_generation"] = int(
        preflight.get("failure_generation", 0)
    ) + 1
    preflight["last_failure"] = {
        "task_id": task_id,
        "error_code": error_code,
        "at": now_iso(),
    }


def input_refs_sha256(input_refs: list[dict[str, Any]]) -> str:
    return canonical_sha256(
        [
            {
                "artifact_key": item["artifact_key"],
                "version": item["version"],
                "sha256": item["sha256"],
            }
            for item in sorted(
                input_refs,
                key=lambda item: (
                    str(item.get("artifact_key")),
                    int(item.get("version", 0)),
                    str(item.get("sha256")),
                ),
            )
        ]
    )


def build_legacy_idempotency_key(
    task_type: str,
    scope: dict[str, Any],
    input_refs: list[dict[str, Any]],
    contract_version: int,
) -> str:
    return canonical_sha256(
        {
            "task_type": task_type,
            "scope": scope,
            "input_refs": [
                {
                    "artifact_key": item["artifact_key"],
                    "version": item["version"],
                    "sha256": item["sha256"],
                }
                for item in input_refs
            ],
            "contract_version": contract_version,
        }
    )


def build_decision_identity(
    *,
    project_id: str,
    stage: str,
    operation: str,
    scope: dict[str, Any],
    input_refs: list[dict[str, Any]],
    output_contract_version: int,
    output_schema_version: int,
) -> dict[str, Any]:
    if not isinstance(project_id, str) or not project_id:
        raise AgentRuntimeError("decision_project_id_invalid")
    if not isinstance(stage, str) or not stage:
        raise AgentRuntimeError("decision_stage_invalid")
    if not isinstance(operation, str) or not operation:
        raise AgentRuntimeError("decision_operation_invalid")
    if type(output_contract_version) is not int or output_contract_version < 1:
        raise AgentRuntimeError("decision_output_contract_version_invalid")
    if type(output_schema_version) is not int or output_schema_version < 1:
        raise AgentRuntimeError("decision_output_schema_version_invalid")
    return {
        "project_id": project_id,
        "stage": stage,
        "operation": operation,
        "input_hash": input_refs_sha256(input_refs),
        "target_hash": canonical_sha256(scope),
        "rule_version": RULE_VERSION,
        "runtime_version": RUNTIME_VERSION,
        "plugin_version": PLUGIN_VERSION,
        "output_contract_version": output_contract_version,
        "output_schema_version": output_schema_version,
    }


def build_idempotency_key(decision_identity: dict[str, Any]) -> str:
    return canonical_sha256(decision_identity)


def execution_policy(execution_mode: str) -> dict[str, Any]:
    production = execution_mode == "production"
    return {
        "source_mutation_allowed": not production,
        "skill_mutation_allowed": not production,
        "development_tests_allowed": not production,
        "design_review_allowed": not production,
    }


def validate_operation_for_mode(
    execution_mode: str,
    operation: str,
    task_type: str,
) -> None:
    if execution_mode != "production":
        return
    if operation in PRODUCTION_FORBIDDEN_OPERATIONS or task_type in PRODUCTION_FORBIDDEN_OPERATIONS:
        raise AgentRuntimeError("production_operation_forbidden")


def delegation_scope_signature(
    *,
    project_id: str,
    run_id: str,
    decision_identity: dict[str, Any],
) -> str:
    return canonical_sha256(
        {
            "project_id": project_id,
            "execution_chain_id": run_id,
            "stage": decision_identity["stage"],
            "operation": decision_identity["operation"],
            "input_hash": decision_identity["input_hash"],
            "target_hash": decision_identity["target_hash"],
            "rule_version": decision_identity["rule_version"],
        }
    )


def directive_is_negated(raw_directive: str | None) -> bool:
    if not isinstance(raw_directive, str):
        return False
    normalized = re.sub(r"\s+", " ", raw_directive.strip().lower())
    return any(pattern.search(normalized) for pattern in NEGATED_DELEGATION_PATTERNS)


def directive_is_explicit(raw_directive: str | None) -> bool:
    if not isinstance(raw_directive, str):
        return False
    normalized = re.sub(r"\s+", " ", raw_directive.strip().lower())
    if directive_is_negated(normalized):
        return False
    return any(marker in normalized for marker in EXPLICIT_DELEGATION_MARKERS)


def resolve_delegation_authorization(
    control: dict[str, Any],
    *,
    project_id: str,
    run_id: str,
    decision_identity: dict[str, Any],
    directive: str | None,
) -> tuple[dict[str, Any], bool]:
    signature = delegation_scope_signature(
        project_id=project_id,
        run_id=run_id,
        decision_identity=decision_identity,
    )
    if directive_is_negated(directive):
        raise AgentRuntimeError("delegation_authorization_required")
    authorizations = control["delegation_authorizations"]
    existing = next(
        (
            record
            for record in reversed(authorizations)
            if isinstance(record, dict)
            and record.get("scope_signature") == signature
            and record.get("status") == "active"
        ),
        None,
    )
    if existing is not None:
        existing["reuse_count"] = int(existing.get("reuse_count", 0)) + 1
        existing["last_reused_at"] = now_iso()
        return existing, True
    if not directive_is_explicit(directive):
        raise AgentRuntimeError("delegation_authorization_required")
    record = {
        "authorization_id": f"AUTH-{uuid.uuid4().hex[:12]}",
        "status": "active",
        "project_id": project_id,
        "execution_chain_id": run_id,
        "stage": decision_identity["stage"],
        "operation": decision_identity["operation"],
        "input_hash": decision_identity["input_hash"],
        "target_hash": decision_identity["target_hash"],
        "rule_version": decision_identity["rule_version"],
        "scope_signature": signature,
        "directive": directive.strip(),
        "created_at": now_iso(),
        "reuse_count": 0,
    }
    authorizations.append(record)
    return record, False


def record_decision_warning(
    control: dict[str, Any],
    *,
    code: str,
    scope_signature: str,
    authorization_id: str,
) -> tuple[dict[str, Any], bool]:
    notices = control["decision_notices"]
    existing = next(
        (
            notice
            for notice in notices
            if isinstance(notice, dict)
            and notice.get("severity") == "warning"
            and notice.get("code") == code
            and notice.get("scope_signature") == scope_signature
            and notice.get("rule_version") == RULE_VERSION
            and notice.get("authorization_id") == authorization_id
        ),
        None,
    )
    if existing is not None:
        existing["occurrence_count"] = int(existing.get("occurrence_count", 1)) + 1
        existing["last_seen_at"] = now_iso()
        return existing, True
    notice = {
        "notice_id": f"WARN-{uuid.uuid4().hex[:12]}",
        "severity": "warning",
        "code": code,
        "scope_signature": scope_signature,
        "rule_version": RULE_VERSION,
        "authorization_id": authorization_id,
        "occurrence_count": 1,
        "created_at": now_iso(),
        "last_seen_at": now_iso(),
    }
    notices.append(notice)
    return notice, False


def activate_blocker(
    control: dict[str, Any],
    *,
    severity: str,
    codes: list[str],
    scope_signature: str,
    input_hash: str,
    authorization_id: str | None,
    task_id: str | None = None,
) -> tuple[dict[str, Any], bool]:
    normalized_codes = sorted(set(code for code in codes if code))
    existing = control.get("active_blocker")
    if (
        isinstance(existing, dict)
        and existing.get("status") == "active"
        and existing.get("severity") == severity
        and existing.get("codes") == normalized_codes
        and existing.get("scope_signature") == scope_signature
    ):
        existing["occurrence_count"] = int(existing.get("occurrence_count", 1)) + 1
        existing["last_seen_at"] = now_iso()
        control["status"] = "blocked"
        return existing, True
    blocker = {
        "blocker_id": f"BLOCK-{uuid.uuid4().hex[:12]}",
        "status": "active",
        "severity": severity,
        "codes": normalized_codes,
        "scope_signature": scope_signature,
        "input_hash": input_hash,
        "authorization_id": authorization_id,
        "task_id": task_id,
        "occurrence_count": 1,
        "created_at": now_iso(),
        "last_seen_at": now_iso(),
    }
    control["active_blocker"] = blocker
    control["status"] = "blocked"
    return blocker, False


def resolve_active_blocker(
    control: dict[str, Any],
    *,
    blocker_id: str,
    resolution_note: str,
) -> dict[str, Any]:
    blocker = control.get("active_blocker")
    if (
        not isinstance(blocker, dict)
        or blocker.get("status") != "active"
        or blocker.get("blocker_id") != blocker_id
    ):
        raise AgentRuntimeError("active_blocker_not_found")
    if not isinstance(resolution_note, str) or not resolution_note.strip():
        raise AgentRuntimeError("blocker_resolution_note_required")
    blocker["status"] = "resolved"
    blocker["resolved_at"] = now_iso()
    blocker["resolution_note"] = resolution_note.strip()
    control["active_blocker"] = None
    preflight = control.get("preflight")
    control["status"] = (
        "execution_ready"
        if isinstance(preflight, dict)
        and preflight.get("status") == "execution_ready"
        else "preflight_required"
    )
    return blocker


def planned_task_lease_expires_at() -> str:
    return (
        datetime.now(timezone.utc)
        + timedelta(seconds=PLANNED_TASK_LEASE_SECONDS)
    ).isoformat()


def planned_task_is_active(task: dict[str, Any]) -> bool:
    if task.get("status") != "planned":
        return False
    raw_expiry = task.get("activity_lease_expires_at")
    if not isinstance(raw_expiry, str):
        return False
    try:
        expiry = datetime.fromisoformat(raw_expiry)
    except ValueError:
        return False
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    return expiry > datetime.now(timezone.utc)


def runtime_root(project_path: Path) -> Path:
    return project_path / RUNTIME_DIRECTORY


def runtime_paths(project_path: Path) -> dict[str, Path]:
    root = runtime_root(project_path)
    return {
        "root": root,
        "run": root / "run.json",
        "tasks": root / "tasks",
        "results": root / "results",
        "candidates": root / "candidates",
        "checkpoints": root / "checkpoints",
        "lock": root / ".project_state.lock",
    }


def ensure_runtime_directories(project_path: Path) -> dict[str, Path]:
    paths = runtime_paths(project_path)
    for key in ("root", "tasks", "results", "candidates", "checkpoints"):
        paths[key].mkdir(parents=True, exist_ok=True)
    return paths


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
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def read_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise AgentRuntimeError(f"runtime_json_unreadable:{path}:{exc}") from exc
    if not isinstance(payload, dict):
        raise AgentRuntimeError(f"runtime_json_not_object:{path}")
    return payload


@contextlib.contextmanager
def project_state_write_lock(project_path: Path) -> Iterator[None]:
    """Serialize runtime commands that may update project_state.json."""

    project_key = str(project_path.expanduser().resolve())
    with _LOCK_REGISTRY_GUARD:
        local_lock = _LOCK_REGISTRY.setdefault(project_key, threading.RLock())
    if not local_lock.acquire(blocking=False):
        raise AgentRuntimeError("project_state_write_in_progress")

    project_existed = project_path.exists()
    if project_existed:
        paths = ensure_runtime_directories(project_path)
        lock_path = paths["lock"]
    else:
        project_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = project_path.parent / (
            f".{project_path.name}.project_state.lock"
        )
    opened_handle = False
    try:
        if project_key not in _HELD_LOCK_HANDLES:
            handle = lock_path.open("a+", encoding="utf-8")
            if fcntl is not None:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    handle.close()
                    raise AgentRuntimeError("project_state_write_in_progress") from exc
            _HELD_LOCK_HANDLES[project_key] = handle
            opened_handle = True
        yield
    finally:
        if opened_handle:
            handle = _HELD_LOCK_HANDLES.pop(project_key)
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()
            if not project_existed and not project_path.exists():
                lock_path.unlink(missing_ok=True)
        local_lock.release()


def build_task_package(
    *,
    run_id: str,
    task_id: str,
    task_type: str,
    scope: dict[str, Any],
    attempt: int,
    input_refs: list[dict[str, Any]],
    allowed_read_paths: list[str],
    allowed_write_directory: str,
    acceptance_command: str,
    contract_version: int,
    decision_identity: dict[str, Any],
    execution_mode: str,
    authorization_id: str,
    coordinator_slice: str,
    artifact_key: str | None = None,
    max_parallel_tasks: int = DEFAULT_MAX_PARALLEL_TASKS,
    scheduling_mode: str = "serial",
    scheduling_key: str | None = None,
    service_capacity: int | None = None,
) -> dict[str, Any]:
    if not isinstance(task_type, str) or not task_type.strip():
        raise AgentRuntimeError("task_type_invalid")
    if type(attempt) is not int or attempt < 1 or attempt > 2:
        raise AgentRuntimeError("task_attempt_invalid")
    if type(contract_version) is not int or contract_version < 1:
        raise AgentRuntimeError("task_contract_version_invalid")
    if not isinstance(decision_identity, dict):
        raise AgentRuntimeError("task_decision_identity_invalid")
    if execution_mode not in SUPPORTED_EXECUTION_MODES:
        raise AgentRuntimeError("task_execution_mode_invalid")
    if not isinstance(authorization_id, str) or not authorization_id:
        raise AgentRuntimeError("task_authorization_id_invalid")
    if acceptance_command not in SUPPORTED_ACCEPTANCE_COMMANDS:
        raise AgentRuntimeError("task_acceptance_command_invalid")
    if type(max_parallel_tasks) is not int or not 1 <= max_parallel_tasks <= MAX_PARALLEL_TASKS:
        raise AgentRuntimeError("task_max_parallel_tasks_invalid")
    if scheduling_mode not in SUPPORTED_SCHEDULING_MODES:
        raise AgentRuntimeError("task_scheduling_mode_invalid")
    if service_capacity is not None and (
        type(service_capacity) is not int
        or not 1 <= service_capacity <= MAX_PARALLEL_TASKS
    ):
        raise AgentRuntimeError("task_service_capacity_invalid")
    if not isinstance(scope, dict):
        raise AgentRuntimeError("task_scope_invalid")
    if not isinstance(input_refs, list):
        raise AgentRuntimeError("task_input_refs_invalid")
    if not isinstance(allowed_read_paths, list) or not all(
        isinstance(path, str) and path for path in allowed_read_paths
    ):
        raise AgentRuntimeError("task_allowed_read_paths_invalid")
    if not isinstance(allowed_write_directory, str) or not allowed_write_directory:
        raise AgentRuntimeError("task_allowed_write_directory_invalid")
    if not allowed_write_directory.startswith(f"{RUNTIME_DIRECTORY}/candidates/"):
        raise AgentRuntimeError("task_write_scope_invalid")
    if not isinstance(coordinator_slice, str) or not coordinator_slice:
        raise AgentRuntimeError("task_coordinator_slice_invalid")
    if artifact_key is not None and (
        not isinstance(artifact_key, str) or not artifact_key
    ):
        raise AgentRuntimeError("task_artifact_key_invalid")

    idempotency_key = build_idempotency_key(decision_identity)
    effective_parallel_limit = min(
        max_parallel_tasks,
        service_capacity if service_capacity is not None else max_parallel_tasks,
    )
    task = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "task_id": task_id,
        "task_type": task_type,
        "scope": scope,
        "attempt": attempt,
        "max_attempts": 2,
        "idempotency_key": idempotency_key,
        "contract_version": contract_version,
        "decision_identity": decision_identity,
        "execution_mode": execution_mode,
        "execution_policy": execution_policy(execution_mode),
        "authorization_id": authorization_id,
        "input_refs": input_refs,
        "allowed_read_paths": sorted(set(allowed_read_paths)),
        "allowed_write_directory": allowed_write_directory,
        "acceptance_command": acceptance_command,
        "artifact_key": artifact_key,
        "return_max_chars": 1000,
        "context_inheritance": "none",
        "max_parallel_tasks": max_parallel_tasks,
        "effective_parallel_limit": effective_parallel_limit,
        "service_capacity": service_capacity or max_parallel_tasks,
        "scheduling_mode": scheduling_mode,
        "scheduling_key": scheduling_key
        or canonical_sha256(
            {"coordinator_slice": coordinator_slice, "scope": scope}
        ),
        "single_state_writer": True,
        "state_write_policy": "supervisor_only",
        "supervisor_mode": "single_layer_host",
        "coordinator_slice": coordinator_slice,
        "host_task_id": None,
        "host_task_status": "unbound",
        "recovery_state": "none",
        "status": "planned",
        "created_at": now_iso(),
        "activity_lease_expires_at": planned_task_lease_expires_at(),
    }
    return task


def _project_relative(project_path: Path, raw_path: Any) -> Path | None:
    if not isinstance(raw_path, str) or not raw_path or Path(raw_path).is_absolute():
        return None
    candidate = (project_path / raw_path).resolve()
    try:
        candidate.relative_to(project_path.resolve())
    except ValueError:
        return None
    return candidate


def validate_task_package(
    task: dict[str, Any], project_path: Path, sha256_file
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    if task.get("schema_version") != SCHEMA_VERSION:
        errors.append(issue("task_schema_invalid", "任务包 schema_version 无效"))
    if task.get("context_inheritance") != "none":
        errors.append(issue("task_context_inheritance_invalid", "工作智能体不得继承会话历史"))
    if task.get("single_state_writer") is not True:
        errors.append(issue("task_single_writer_required", "任务包必须声明单一状态写入者"))
    if task.get("state_write_policy") not in {
        "supervisor_only",
        "coordinator_only",
    }:
        errors.append(issue("task_state_write_policy_invalid", "工作智能体不得写入项目状态"))
    decision_identity = task.get("decision_identity")
    if not isinstance(decision_identity, dict):
        errors.append(
            issue("task_decision_identity_invalid", "任务包缺少统一决策身份")
        )
    else:
        required_identity_fields = {
            "project_id",
            "stage",
            "operation",
            "input_hash",
            "target_hash",
            "rule_version",
            "runtime_version",
            "plugin_version",
            "output_contract_version",
            "output_schema_version",
        }
        missing_identity_fields = sorted(
            required_identity_fields - set(decision_identity)
        )
        if missing_identity_fields:
            errors.append(
                issue(
                    "task_decision_identity_incomplete",
                    "统一决策身份字段不完整",
                    missing=missing_identity_fields,
                )
            )
        elif task.get("idempotency_key") != build_idempotency_key(
            decision_identity
        ):
            errors.append(
                issue(
                    "task_idempotency_mismatch",
                    "任务幂等键与统一决策身份不一致",
                )
            )
    execution_mode = task.get("execution_mode")
    if execution_mode not in SUPPORTED_EXECUTION_MODES:
        errors.append(issue("task_execution_mode_invalid", "任务执行模式无效"))
    if task.get("execution_policy") != execution_policy(execution_mode):
        errors.append(
            issue("task_execution_policy_invalid", "任务执行策略与模式不一致")
        )
    if not isinstance(task.get("authorization_id"), str) or not task["authorization_id"]:
        errors.append(
            issue("task_authorization_id_invalid", "任务缺少委托授权ID")
        )
    if task.get("supervisor_mode", "legacy_two_level") not in {
        "single_layer_host",
        "legacy_two_level",
    }:
        errors.append(issue("task_supervisor_mode_invalid", "任务监督模式无效"))
    host_task_id = task.get("host_task_id")
    if host_task_id is not None and (
        not isinstance(host_task_id, str) or not host_task_id
    ):
        errors.append(issue("task_host_task_id_invalid", "宿主任务ID必须是非空字符串"))
    if task.get("host_task_status", "unbound") not in {
        "unbound",
        "active",
        "inactive",
        "completed",
    }:
        errors.append(issue("task_host_task_status_invalid", "宿主任务状态无效"))
    if task.get("recovery_state", "none") not in {
        "none",
        "recovery_required",
        "blocked",
    }:
        errors.append(issue("task_recovery_state_invalid", "任务恢复状态无效"))
    if (
        type(task.get("max_parallel_tasks")) is not int
        or not 1 <= task["max_parallel_tasks"] <= MAX_PARALLEL_TASKS
    ):
        errors.append(issue("task_max_parallel_tasks_invalid", "任务并发上限无效"))
    if task.get("scheduling_mode") not in SUPPORTED_SCHEDULING_MODES:
        errors.append(issue("task_scheduling_mode_invalid", "任务必须声明串行或独立调度模式"))
    if not isinstance(task.get("scheduling_key"), str) or not task["scheduling_key"]:
        errors.append(issue("task_scheduling_key_invalid", "任务缺少调度冲突键"))
    if type(task.get("effective_parallel_limit")) is not int or not 1 <= task["effective_parallel_limit"] <= MAX_PARALLEL_TASKS:
        errors.append(issue("task_effective_parallel_limit_invalid", "任务有效并发上限无效"))
    if type(task.get("service_capacity")) is not int or not 1 <= task["service_capacity"] <= MAX_PARALLEL_TASKS:
        errors.append(issue("task_service_capacity_invalid", "任务服务容量无效"))
    if task.get("acceptance_command") not in SUPPORTED_ACCEPTANCE_COMMANDS:
        errors.append(issue("task_acceptance_command_invalid", "任务包验收命令不受支持"))

    write_root = _project_relative(project_path, task.get("allowed_write_directory"))
    expected_prefix = f"{RUNTIME_DIRECTORY}/candidates/"
    if (
        write_root is None
        or not str(task.get("allowed_write_directory", "")).startswith(expected_prefix)
    ):
        errors.append(issue("task_write_scope_invalid", "任务写入目录必须位于 runtime/candidates"))

    input_refs = task.get("input_refs")
    if not isinstance(input_refs, list):
        errors.append(issue("task_input_refs_invalid", "input_refs 必须是数组"))
        input_refs = []
    for index, item in enumerate(input_refs):
        if not isinstance(item, dict):
            errors.append(issue("task_input_ref_invalid", "输入引用必须是对象", input_index=index))
            continue
        path = _project_relative(project_path, item.get("path"))
        if path is None or not path.is_file():
            errors.append(issue("task_input_path_invalid", "输入引用路径无效", input_index=index))
            continue
        expected_hash = item.get("sha256")
        if not isinstance(expected_hash, str) or sha256_file(path) != expected_hash:
            errors.append(issue("task_input_hash_mismatch", "任务输入散列已变化", input_index=index))

    allowed_read_paths = task.get("allowed_read_paths")
    if not isinstance(allowed_read_paths, list):
        errors.append(issue("task_allowed_read_paths_invalid", "allowed_read_paths 必须是数组"))
    else:
        for index, raw_path in enumerate(allowed_read_paths):
            if _project_relative(project_path, raw_path) is None:
                errors.append(issue("task_allowed_read_path_invalid", "允许读取路径越界", path_index=index))
    return errors


def build_result_envelope(
    *,
    task_id: str,
    idempotency_key: str,
    status: str,
    candidate_output_paths: list[str] | None = None,
    error_code: str | None = None,
    telemetry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if status not in {"completed", "failed"}:
        raise AgentRuntimeError("result_status_invalid")
    if status == "failed" and not error_code:
        raise AgentRuntimeError("result_error_code_required")
    return {
        "schema_version": SCHEMA_VERSION,
        "task_id": task_id,
        "idempotency_key": idempotency_key,
        "status": status,
        "candidate_output_paths": candidate_output_paths or [],
        "error_code": error_code,
        "telemetry": normalize_telemetry(telemetry or {}),
    }


def validate_result_envelope(
    task: dict[str, Any], result: dict[str, Any], project_path: Path
) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    if result.get("schema_version") != SCHEMA_VERSION:
        errors.append(issue("result_schema_invalid", "结果信封 schema_version 无效"))
    if result.get("task_id") != task.get("task_id"):
        errors.append(issue("result_task_id_mismatch", "结果信封 task_id 与任务包不一致"))
    accepted_idempotency_keys = {
        value
        for value in (
            task.get("idempotency_key"),
            task.get("legacy_idempotency_key"),
        )
        if isinstance(value, str)
    }
    if result.get("idempotency_key") not in accepted_idempotency_keys:
        errors.append(issue("result_idempotency_mismatch", "结果信封幂等键与任务包不一致"))
    status = result.get("status")
    if status not in {"completed", "failed"}:
        errors.append(issue("result_status_invalid", "结果状态必须为 completed 或 failed"))
    if status == "failed" and not isinstance(result.get("error_code"), str):
        errors.append(issue("result_error_code_required", "失败结果必须记录 error_code"))
    candidates = result.get("candidate_output_paths")
    if not isinstance(candidates, list):
        errors.append(issue("result_candidates_invalid", "candidate_output_paths 必须是数组"))
        candidates = []
    if status == "completed" and not candidates:
        errors.append(issue("result_candidates_missing", "完成结果必须至少包含一个候选文件"))

    write_root = _project_relative(project_path, task.get("allowed_write_directory"))
    for index, raw_path in enumerate(candidates):
        candidate = _project_relative(project_path, raw_path)
        if candidate is None or not candidate.is_file():
            errors.append(issue("candidate_output_missing", "候选输出不存在或越界", candidate_index=index))
            continue
        if write_root is None:
            continue
        try:
            candidate.relative_to(write_root)
        except ValueError:
            errors.append(
                issue(
                    "candidate_output_path_forbidden",
                    "候选输出必须位于任务包冻结的写入目录",
                    candidate_index=index,
                )
            )
    telemetry_errors = validate_telemetry(result.get("telemetry"))
    errors.extend(telemetry_errors)
    return errors


def accepted_output_records(
    project_path: Path,
    candidate_paths: list[str],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for raw_path in candidate_paths:
        path = _project_relative(project_path, raw_path)
        if path is None or not path.is_file():
            raise AgentRuntimeError("accepted_output_missing")
        records.append(
            {
                "path": raw_path,
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
        )
    return records


def accepted_outputs_are_intact(
    task: dict[str, Any],
    project_path: Path,
) -> bool:
    records = task.get("accepted_outputs")
    if not isinstance(records, list) or not records:
        return False
    for record in records:
        if not isinstance(record, dict):
            return False
        path = _project_relative(project_path, record.get("path"))
        if path is None or not path.is_file():
            return False
        expected_hash = record.get("sha256")
        if not isinstance(expected_hash, str) or sha256_file(path) != expected_hash:
            return False
    return True


def normalize_telemetry(payload: dict[str, Any]) -> dict[str, Any]:
    result = {field: 0.0 for field in TIMING_FIELDS}
    for field in TIMING_FIELDS:
        value = payload.get(field, 0.0)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
            result[field] = float(value)
    raw_error_class = payload.get("error_class", "none")
    result["error_class"] = (
        raw_error_class if raw_error_class in ERROR_CLASSES else "other"
    )
    return result


def validate_telemetry(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return [issue("telemetry_invalid", "telemetry 必须是对象")]
    errors: list[dict[str, Any]] = []
    for field in TIMING_FIELDS:
        value = payload.get(field)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
            errors.append(issue("telemetry_value_invalid", f"{field} 必须是非负数字", field=field))
    if payload.get("error_class") not in ERROR_CLASSES:
        errors.append(issue("telemetry_error_class_invalid", "error_class 不在已知错误分类中"))
    return errors


def classify_error(error_code: str | None) -> str:
    text = (error_code or "").lower()
    if "429" in text or "too_many" in text or "rate_limit" in text:
        return "429_too_many_requests"
    if "stream" in text or "response.completed" in text or "disconnect" in text:
        return "stream_disconnect_without_completion"
    if "context" in text or "window" in text:
        return "context_window_exceeded"
    return "other"


def recovery_policy_for(error_code: str | None) -> dict[str, Any]:
    """Return the bounded recovery action for one classified worker failure."""

    error_class = classify_error(error_code)
    policy = RECOVERY_POLICIES[error_class].copy()
    policy["error_class"] = error_class
    return policy


def infer_scheduling_mode(task_type: str, scope: dict[str, Any]) -> str:
    """Prefer explicit business serial boundaries; allow known independent work to fan out."""

    requested = scope.get("scheduling_mode") if isinstance(scope, dict) else None
    if requested in SUPPORTED_SCHEDULING_MODES:
        return requested
    if task_type in INDEPENDENT_TASK_TYPES:
        return "independent"
    if task_type in SERIAL_TASK_TYPES:
        return "serial"
    return "serial"


def make_checkpoint(
    *,
    run_id: str,
    task_id: str | None,
    idempotency_key: str | None,
    status: str,
    next_step: str,
    active_task_ids: list[str],
    result_path: str | None = None,
    failure_count: int = 0,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "task_id": task_id,
        "idempotency_key": idempotency_key,
        "status": status,
        "next_step": next_step,
        "active_task_ids": sorted(set(active_task_ids)),
        "failure_count": failure_count,
        "result_path": result_path,
        "created_at": now_iso(),
    }


def task_id_for(idempotency_key: str, attempt: int) -> str:
    if type(attempt) is not int or attempt < 1:
        raise AgentRuntimeError("task_attempt_invalid")
    return f"TASK-{idempotency_key[:12]}-A{attempt:02d}"


def result_path_for(project_path: Path, task_id: str) -> Path:
    return runtime_paths(project_path)["results"] / f"{task_id}.json"


def task_path_for(project_path: Path, task_id: str) -> Path:
    return runtime_paths(project_path)["tasks"] / f"{task_id}.json"


def checkpoint_path_for(
    project_path: Path, run_id: str, task_id: str | None, status: str
) -> Path:
    safe_run = re.sub(r"[^A-Za-z0-9_.-]+", "_", run_id)
    safe_task = re.sub(r"[^A-Za-z0-9_.-]+", "_", task_id or "none")
    return runtime_paths(project_path)["checkpoints"] / f"{safe_run}-{safe_task}-{status}.json"
