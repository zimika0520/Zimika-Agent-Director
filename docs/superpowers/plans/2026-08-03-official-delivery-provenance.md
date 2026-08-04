# AI Director Official Delivery Provenance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make production rendering and per-episode delivery provably originate from the current preflight, confirmed project inputs, standard render contracts, and registered output hashes.

**Architecture:** Reuse the existing execution control, project state lock, artifact registry, validation context, storyboard fingerprint cache, and result envelope builder. Add one registered `episode_delivery_manifest:<episode>` artifact and one validation command; direct renderer calls may still create candidate files, but only the project tool can create an official delivery.

**Tech Stack:** Python 3 standard library, `unittest`, JSON artifact contracts, DOCX ZIP validation, SHA-256, atomic file replacement.

---

No commits, pushes, plugin-cache refreshes, or real novel projects are allowed in this plan. Each task ends with a test and diff checkpoint instead of a commit.

### Task 1: Establish Baseline and Production Render Guard

**Files:**
- Modify: `skills/novel-to-script-director/scripts/project_tool.py`
- Test: `skills/novel-to-script-director/scripts/test_project_tool.py`

- [ ] **Step 1: Run the current affected baseline**

Run:

```bash
python3 -m unittest \
  skills.novel-to-script-director.scripts.test_project_tool.ProjectToolTests.test_render_episode_delivery_outputs_exact_pair \
  skills.novel-to-script-director.scripts.test_project_tool.ProjectToolTests.test_render_episode_delivery_reuses_preloaded_storyboard_inputs
```

If module-path import is unsupported because of the hyphenated directory, run from the scripts directory:

```bash
python3 -m unittest \
  test_project_tool.ProjectToolTests.test_render_episode_delivery_outputs_exact_pair \
  test_project_tool.ProjectToolTests.test_render_episode_delivery_reuses_preloaded_storyboard_inputs
```

Expected: existing tests pass before new behavior is introduced.

- [ ] **Step 2: Write failing tests for missing and stale preflight**

Add tests that call `render-storyboard` and `render-episode-delivery` without `startup-preflight` and assert exit code `2` with:

```python
self.assertEqual(payload["error"], "execution_preflight_required")
```

Then run `startup-preflight`, mutate the saved preflight fingerprint, rerun each rendering command, and assert:

```python
self.assertEqual(payload["error"], "execution_preflight_stale")
```

- [ ] **Step 3: Verify the new tests fail**

Run the four new test methods individually. Expected: FAIL because both render commands currently proceed without calling `require_execution_ready`.

- [ ] **Step 4: Add one shared command guard**

Add:

```python
def require_production_execution(
    project_path: Path,
    state: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    control, fingerprint = require_execution_ready(project_path, state)
    if control.get("execution_mode") != "production":
        raise agent_runtime.AgentRuntimeError("production_execution_required")
    return control, fingerprint
```

Call it at the start of `command_render_storyboard`, `command_render_episode_delivery`, and the later delivery-validation command.

- [ ] **Step 5: Run the new tests and existing render tests**

Expected: all render guard tests pass. Update old render tests to run `startup-preflight` explicitly; do not bypass the guard inside production code.

### Task 2: Build Immutable Episode Delivery Inputs

**Files:**
- Modify: `skills/novel-to-script-director/scripts/project_tool.py`
- Test: `skills/novel-to-script-director/scripts/test_project_tool.py`

- [ ] **Step 1: Write a failing input-fingerprint test**

Assert that `episode_delivery_inputs()` returns exact dependency records with:

```python
{
    "artifact_key": key,
    "version": record["version"],
    "path": record["path"],
    "sha256": record["sha256"],
}
```

and an `input_fingerprint` that changes after one dependency file is changed and its artifact version/hash is updated.

- [ ] **Step 2: Verify the test fails**

Expected: FAIL because current dependencies only contain `artifact_key` and `version`.

- [ ] **Step 3: Add normalized dependency references**

Add a helper:

```python
def delivery_dependency_ref(
    project_path: Path,
    artifact_key: str,
    record: dict[str, Any],
) -> dict[str, Any]:
    path = path_from_record(project_path, record.get("path"))
    return {
        "artifact_key": artifact_key,
        "version": record["version"],
        "path": record["path"],
        "sha256": sha256_file(path),
    }
```

Deduplicate and sort dependency references, then calculate:

```python
input_fingerprint = agent_runtime.canonical_sha256({
    "episode": episode,
    "plugin_version": agent_runtime.PLUGIN_VERSION,
    "runtime_version": agent_runtime.RUNTIME_VERSION,
    "rule_version": agent_runtime.RULE_VERSION,
    "docx_contract_version": render_episode_script.RENDER_CONTRACT_VERSION,
    "storyboard_contract_version": render_storyboard.RENDER_CONTRACT_VERSION,
    "dependencies": dependencies,
})
```

- [ ] **Step 4: Return a read-only delivery-input object**

Use a frozen dataclass or an immutable mapping containing script text, roster, anchors, storyboard payloads, normalized dependencies, and `input_fingerprint`. Keep renderer-specific payload reuse internal to `project_tool.py`.

- [ ] **Step 5: Run input and existing read-reuse tests**

Expected: the fingerprint test passes and `test_render_episode_delivery_reuses_preloaded_storyboard_inputs` still proves no duplicate input reads.

### Task 3: Create and Validate Official Delivery Manifests

**Files:**
- Modify: `skills/novel-to-script-director/scripts/project_tool.py`
- Modify: `skills/novel-to-script-director/scripts/render_storyboard.py`
- Test: `skills/novel-to-script-director/scripts/test_project_tool.py`

- [ ] **Step 1: Write failing official-delivery tests**

Add tests for:

```python
self.assertTrue(payload["official_delivery"])
self.assertEqual(payload["generation_entrypoint"], "project_tool render-episode-delivery")
self.assertIn("input_fingerprint", payload)
self.assertIn("sha256", payload["outputs"]["docx"])
self.assertIn("sha256", payload["outputs"]["html"])
```

Also assert that a direct `render_storyboard.render(..., state=fake, preloaded=fake)` call creates no `episode_delivery_manifest:E001`, and `validate-episode-delivery` returns `official_delivery: false`.

- [ ] **Step 2: Verify the tests fail**

Expected: FAIL because no manifest artifact or validation command exists.

- [ ] **Step 3: Add a stable HTML contract marker**

Set:

```python
HTML_TEMPLATE_MARKER = (
    f'<meta name="ai-director-render-contract" content="{RENDER_CONTRACT_VERSION}">'
)
```

Include it in the generated `<head>`. Validation must require this exact marker plus the existing `AI导演插件 render_storyboard` footer.

- [ ] **Step 4: Build the manifest payload**

Add:

```python
def build_episode_delivery_manifest(
    *,
    project_path: Path,
    episode: str,
    inputs: EpisodeDeliveryInputs,
    docx_path: Path,
    html_path: Path,
    storyboard_fingerprint: str,
    reused: bool,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "episode_id": episode,
        "generation_entrypoint": "project_tool render-episode-delivery",
        "plugin_version": agent_runtime.PLUGIN_VERSION,
        "runtime_version": agent_runtime.RUNTIME_VERSION,
        "rule_version": agent_runtime.RULE_VERSION,
        "docx_contract_version": render_episode_script.RENDER_CONTRACT_VERSION,
        "storyboard_contract_version": render_storyboard.RENDER_CONTRACT_VERSION,
        "input_fingerprint": inputs.input_fingerprint,
        "inputs": list(inputs.dependencies),
        "storyboard_input_fingerprint": storyboard_fingerprint,
        "outputs": {
            "docx": project_output_ref(project_path, docx_path),
            "html": project_output_ref(project_path, html_path),
        },
        "reused": reused,
        "generated_at": now_iso(),
    }
```

All paths in the payload must be project-relative.

- [ ] **Step 5: Generate files through temporary paths**

Write DOCX and HTML under the final directory using hidden temporary names, validate both, then use `os.replace()` for the final names. Write the manifest with `atomic_write_json()`.

- [ ] **Step 6: Register the manifest**

Register `episode_delivery_manifest:<episode>` as a confirmed, tool-generated artifact through the existing artifact-record format and `save_state()`. A repeated identical delivery may reuse the current manifest version; changed inputs must create a new version and new manifest path.

- [ ] **Step 7: Implement `validate_episode_delivery_state()`**

Return:

```python
{
    "official_delivery": not errors,
    "episode": episode,
    "manifest": manifest_path,
    "input_fingerprint": current_inputs.input_fingerprint,
    "outputs": manifest["outputs"],
    "errors": errors,
}
```

Check manifest registration, current inputs, hashes, output paths, HTML marker, and DOCX ZIP members `[Content_Types].xml` and `word/document.xml`.

- [ ] **Step 8: Add `validate-episode-delivery` CLI**

Register the parser and handler. A failed validation exits with code `2` and prints `official_delivery: false`; a valid delivery exits `0`.

- [ ] **Step 9: Run manifest tests**

Expected: legitimate delivery is official; direct renderer output is not.

### Task 4: Prove Reuse and Tamper Detection

**Files:**
- Modify: `skills/novel-to-script-director/scripts/project_tool.py`
- Test: `skills/novel-to-script-director/scripts/test_project_tool.py`

- [ ] **Step 1: Write failing reuse and tamper tests**

Patch `render_storyboard.render` and `render_episode_script.write_docx` with counting wrappers.

Assert:

```python
self.assertEqual(storyboard_calls, 1)
self.assertEqual(docx_calls, 1)
```

after two identical `render-episode-delivery` commands.

Overwrite one byte in HTML and assert `episode_delivery_output_hash_mismatch`.

Change an input artifact version/hash and assert `episode_delivery_input_stale`, then rerun delivery and assert both renderer counters increase.

- [ ] **Step 2: Verify the tests fail**

Expected: repeated delivery currently renders again, and no tamper validator exists.

- [ ] **Step 3: Add safe reuse**

Before rendering, validate the current manifest. Reuse only when:

- current `input_fingerprint` matches;
- both output hashes match;
- DOCX and HTML structural checks pass;
- standard generation entrypoint and contracts match.

Otherwise render both outputs again and create a new manifest version.

- [ ] **Step 4: Verify HTML dual-location reuse**

Keep the existing storyboard render cache and final delivery location. Assert both contain identical bytes and only one actual HTML page construction occurs for one input fingerprint.

- [ ] **Step 5: Run reuse and tamper tests**

Expected: identical execution returns `reused: true`; tampering or input change invalidates reuse.

### Task 5: Add a Safe Agent Result Writer

**Files:**
- Modify: `skills/novel-to-script-director/scripts/project_tool.py`
- Test: `skills/novel-to-script-director/scripts/test_project_tool.py`

- [ ] **Step 1: Write a failing CLI test**

Create a planned task and a candidate file, then call:

```bash
project_tool.py write-agent-result <project> \
  --task-id TASK-001 \
  --status completed \
  --candidate-output .ai-director/runtime/candidates/TASK-001/output.json \
  --machine-time-seconds 1.25
```

Assert the generated envelope passes `agent_runtime.validate_result_envelope()` and contains all normalized timing fields.

- [ ] **Step 2: Verify the test fails**

Expected: parser rejects `write-agent-result` because it does not exist.

- [ ] **Step 3: Implement the command**

Load the task package by task id, ensure every candidate is inside its frozen write directory, call:

```python
result = agent_runtime.build_result_envelope(
    task_id=task["task_id"],
    idempotency_key=task["idempotency_key"],
    status=args.status,
    candidate_output_paths=args.candidate_output,
    error_code=args.error_code,
    telemetry=telemetry,
)
```

Validate the envelope, atomically write it to `runtime/results/<task_id>.json`, and return its project-relative path.

- [ ] **Step 4: Run result-writer and acceptance tests**

Expected: the new CLI result can be accepted by `accept-agent-result`; invalid paths and failed results without error codes are rejected.

### Task 6: Lock Down Hostless Lease Recovery

**Files:**
- Modify only if tests expose a defect: `skills/novel-to-script-director/scripts/agent_runtime.py`
- Modify only if tests expose a defect: `skills/novel-to-script-director/scripts/project_tool.py`
- Test: `skills/novel-to-script-director/scripts/test_project_tool.py`

- [ ] **Step 1: Add an unexpired-lease regression test**

Plan a task without binding a host task, immediately plan the same decision again, and assert:

```python
self.assertEqual(payload["status"], "active_task_reused")
self.assertEqual(payload["task"]["attempt"], 1)
```

- [ ] **Step 2: Run it**

If it passes, retain the test and make no production change. If it fails, verify `planned_task_is_active()` is bypassed in the planning path before changing code.

- [ ] **Step 3: Add expired-lease and two-failure tests**

Set `activity_lease_expires_at` to a past UTC time. Assert the next plan creates attempt 2 with the same idempotency key. Expire attempt 2 and assert an active blocker is created and no third attempt is planned.

- [ ] **Step 4: Run the existing recovery suite**

Run:

```bash
python3 -m unittest \
  test_project_tool.ProjectToolTests.test_plan_agent_slice_recovers_hostless_active_task_once \
  test_project_tool.ProjectToolTests.test_plan_agent_slice_blocks_after_two_hostless_attempts
```

Expected: all old and new lease tests pass.

### Task 7: Fail AI Video Contracts Before Production Extraction

**Files:**
- Modify: `skills/novel-to-script-director/scripts/project_tool.py`
- Test: `skills/novel-to-script-director/scripts/test_project_tool.py`

- [ ] **Step 1: Write a failing early-gate test**

Create an `ai_video` project with a confirmed schema v1 `source_event_index`, complete production preflight, and plan a `production_extraction` or `storyboard_render` task.

Assert:

```python
self.assertEqual(payload["error"], "ai_video_source_contract_not_ready")
```

and assert no task package or candidate output was created.

- [ ] **Step 2: Verify the test fails**

Expected: current planning allows the task and discovers the contract problem later.

- [ ] **Step 3: Add `validate_ai_video_source_contract_ready()`**

Require the confirmed project spec to target `ai_video` or `both`, then require:

```python
event_index.get("schema_version") == 2
source_beat_index(event_index)
isinstance(event_index.get("episode_scopes"), dict)
```

For scoped episode tasks, require an `episode_scopes[episode_id]` entry with valid beat ids.

- [ ] **Step 4: Call the gate before task creation and delivery input loading**

Apply it to production extraction, dialogue extraction, storyboard rendering, and episode delivery. Do not apply it to `human_team` projects.

- [ ] **Step 5: Run the early-gate and existing boundary tests**

Expected: schema v1 stops before downstream work; valid schema v2 and human-team workflows continue.

### Task 8: Documentation and Verification

**Files:**
- Modify: `skills/novel-to-script-director/SKILL.md`
- Modify: `skills/novel-to-script-director/references/workflow.md`
- Modify: `skills/novel-to-script-director/references/production-data-schemas.md`
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Test: `skills/novel-to-script-director/scripts/test_project_tool.py`

- [ ] **Step 1: Document official-delivery semantics**

State that:

- render output without a valid manifest is a candidate only;
- `render-episode-delivery` is the only official generation entrypoint;
- `validate-episode-delivery` is required before reporting completion;
- direct renderer calls, copied files, and hand-authored HTML cannot become official delivery;
- production rendering requires current `execution_ready`.

- [ ] **Step 2: Run all affected tests**

Run the new test names plus existing orchestration, boundary, approval, recovery, and render tests. Record actual test count, duration, and failures.

- [ ] **Step 3: Run the complete automated suite**

From the scripts directory:

```bash
/usr/bin/time -p python3 -m unittest discover -p 'test_*.py'
```

Record actual test count, duration, and every failure.

- [ ] **Step 4: Run static checks**

```bash
python3 -m compileall \
  agent_runtime.py \
  project_tool.py \
  render_storyboard.py \
  render_episode_script.py
git diff --check -- ai-director
```

Expected: exit code `0`.

- [ ] **Step 5: Run an isolated one-episode closure**

Create a new temporary project under the operating-system temporary directory. Use only synthetic source and generic fixture data. Run:

1. `startup-preflight`;
2. project initialization and required confirmed fixture artifacts;
3. one episode script validation;
4. extraction and AI-video contract validation;
5. AI storyboard registration;
6. `render-episode-delivery`;
7. `validate-episode-delivery`;
8. repeat delivery and verify reuse;
9. overwrite a copied output and verify validation fails.

Record the temporary project path, DOCX path, HTML path, manifest path, total duration, and per-stage duration.

- [ ] **Step 6: Verify the primary workspace stayed unchanged**

Compare the primary workspace status captured before implementation with its current status. The only changes from this work must remain inside the isolated worktree.

- [ ] **Step 7: Produce the final report**

Report modified files, each root-cause fix, targeted/full/closure test results, isolated project outputs, and remaining risks. Do not claim release, installation, or active-plugin synchronization.
