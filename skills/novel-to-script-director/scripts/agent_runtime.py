#!/usr/bin/env python3
"""File-backed contracts for short-lived AI Director agent orchestration."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None


SCHEMA_VERSION = 1
DEFAULT_MAX_PARALLEL_TASKS = 2
MAX_PARALLEL_TASKS = 8
RUNTIME_DIRECTORY = ".ai-director/runtime"
TIMING_FIELDS = (
    "machine_time_seconds",
    "model_time_seconds",
    "agent_time_seconds",
    "human_wait_seconds",
    "reconnect_wait_seconds",
)
SUPPORTED_ACCEPTANCE_COMMANDS = {"none", "schema-only", "validate-script"}
SUPPORTED_SCHEDULING_MODES = {"serial", "independent"}
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


def build_idempotency_key(
    task_type: str,
    scope: dict[str, Any],
    input_refs: list[dict[str, Any]],
    contract_version: int,
) -> str:
    normalized_inputs = [
        {
            "artifact_key": item["artifact_key"],
            "version": item["version"],
            "sha256": item["sha256"],
        }
        for item in input_refs
    ]
    return canonical_sha256(
        {
            "task_type": task_type,
            "scope": scope,
            "input_refs": normalized_inputs,
            "contract_version": contract_version,
        }
    )


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

    idempotency_key = build_idempotency_key(
        task_type, scope, input_refs, contract_version
    )
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
    if result.get("idempotency_key") != task.get("idempotency_key"):
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
