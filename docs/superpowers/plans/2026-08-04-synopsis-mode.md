# AI Director Synopsis Mode Implementation Plan (v0.8.92 baseline)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a parameterized `source_kind: synopsis` workflow that turns a user-provided synopsis and any positive target episode count into a feasibility-checked, controlled-expansion episodic script package without weakening the existing AI Director state machine or delivery gates.

**Architecture:** Reuse the existing `project_state.json`, artifact registry, dependency invalidation, approval records, boundary reviews, runtime task envelopes, episode script validators, AI shot-plan contract, HTML storyboard renderer, and DOCX renderer. The new mode adds a synopsis-specific source policy, synopsis facts and feasibility fields to the existing source-event contract, a project-level expansion policy, and deterministic validators. Adjacent episode writing remains serial; independent extraction and rendering remain bounded and state-writer-serialized.

**Tech Stack:** Python 3 standard library, `argparse`, JSON artifact contracts, `unittest`, existing `agent_runtime.py`, `project_tool.py`, `render_storyboard.py`, and `render_episode_script.py`.

---

## Scope and non-goals

- `synopsis` is a source/processing mode, not a second state machine.
- The implementation must work for `1`, `20`, `30`, `40`, or any other positive `expected_episodes`; no `20–25` special case is allowed.
- A synopsis is the only story authority. Generated bridge events are not silently promoted to source facts.
- Allowed additions are restricted to mainline-supporting school/life events, supporting characters/opponents, intermediate conflicts, dialogue/actions, transitions, and non-story-changing environment reactions.
- Core identity, ability, relationship direction, motivation, key event results, world rules, and ending nature require source evidence or explicit user authorization.
- The default synopsis policy is a 60–90 second per-episode range, at least 21 AI shot-plan units, and unrestricted empty/dialogue/non-dialogue composition. Existing modes keep their current defaults of approximately 60 seconds and 15 recommended units.
- The feature must produce the existing per-episode DOCX and HTML delivery artifacts; it must not generate images, videos, audio, or external model requests.
- Do not run the protected real novel project. All validation uses isolated temporary fixtures.

## File map

- Modify `/Users/shinchan/Downloads/小说/ai-director/skills/novel-to-script-director/scripts/project_tool.py`
  - Register `synopsis` in source policy validation and CLI choices.
  - Add synopsis-only project-policy validation.
  - Wire synopsis fact, feasibility, expansion, series-map, script, and AI shot-plan gates into existing dependency and approval paths.
  - Add the deterministic `validate-synopsis` command and synopsis fields to `show --summary`.
- Create `/Users/shinchan/Downloads/小说/ai-director/skills/novel-to-script-director/scripts/synopsis_contracts.py`
  - Own pure validation and feasibility-contract functions so synopsis rules do not further expand the already large CLI module.
- Create `/Users/shinchan/Downloads/小说/ai-director/skills/novel-to-script-director/scripts/test_synopsis_contracts.py`
  - Cover synopsis facts, dynamic episode coverage, feasibility blockers, and controlled expansion rules in isolation.
- Modify `/Users/shinchan/Downloads/小说/ai-director/skills/novel-to-script-director/scripts/test_project_tool.py`
  - Cover CLI registration, state integration, approvals, dependency invalidation, and end-to-end temporary-project behavior.
- Modify `/Users/shinchan/Downloads/小说/ai-director/skills/novel-to-script-director/SKILL.md`
  - Document synopsis input, feasibility stop, user map confirmation, sequential episode generation, and per-episode delivery.
- Modify `/Users/shinchan/Downloads/小说/ai-director/skills/novel-to-script-director/references/workflow.md`
  - Add the synopsis workflow branch while preserving the existing four gates and runtime contract.
- Modify `/Users/shinchan/Downloads/小说/ai-director/skills/novel-to-script-director/references/artifact-contracts.md`
  - Define synopsis source policy, synopsis fact fields, feasibility fields, and controlled-expansion bindings.
- Modify `/Users/shinchan/Downloads/小说/ai-director/skills/novel-to-script-director/references/production-data-schemas.md`
  - Define the machine-readable synopsis policy and fields consumed by script/shot-plan validators.
- Modify `/Users/shinchan/Downloads/小说/ai-director/skills/novel-to-script-director/references/script-format-and-quality.md`
  - Add synopsis-specific expression-quality rules for reducing AI-sounding generic prose, repeated reactions, filler dialogue, and templated hooks.
- Modify `/Users/shinchan/Downloads/小说/ai-director/README.md`
  - Add a synopsis-mode usage example and explain that target episode count is dynamic.
- Modify `/Users/shinchan/Downloads/小说/ai-director/CHANGELOG.md`
  - Add release notes only after implementation and verification are complete.

## Task 0: Finish and freeze the orchestration prerequisite

The current checkout has advanced to `0.8.92`. `plan-agent-slice`, `accept-agent-result`, `show-agent-runtime`, `write-agent-result`, `render-episode-delivery`, and `validate-episode-delivery` are already registered and implemented in the working tree. Synopsis development must not proceed against an unverified runtime, so Task 0 is a baseline verification gate, not a reimplementation of orchestration.

**Files:**
- Modify `/Users/shinchan/Downloads/小说/ai-director/skills/novel-to-script-director/scripts/agent_runtime.py`
- Modify `/Users/shinchan/Downloads/小说/ai-director/skills/novel-to-script-director/scripts/project_tool.py`
- Modify `/Users/shinchan/Downloads/小说/ai-director/skills/novel-to-script-director/scripts/test_project_tool.py`
- Test `/Users/shinchan/Downloads/小说/ai-director/skills/novel-to-script-director/scripts/test_source_partition.py`

- [ ] Inspect the existing diff and retain all unrelated user changes and deletion records.
- [ ] Confirm the current working tree is `0.8.92` and confirm these commands are registered in `argparse`: `plan-agent-slice`, `write-agent-result`, `accept-agent-result`, `show-agent-runtime`, `render-episode-delivery`, and `validate-episode-delivery`.
- [ ] Verify task envelopes contain immutable input references with versions and SHA-256 values, explicit read/write scopes, acceptance command, checkpoint path, idempotency key, and `max_attempts: 2`.
- [ ] Verify workers use `context_inheritance: none`, write only isolated candidate/result files, and never write `project_state.json`.
- [ ] Verify adjacent episode writing, continuity, global IDs, and state writes use one scheduling key and remain serial.
- [ ] Add focused tests for duplicate task reuse, stale input rejection, missing host recovery, checkpoint resume, two-failure blocking, 429 handling, stream disconnect without `response.completed`, and `context_window_exceeded`.
- [ ] Add or extend focused tests for `write-agent-result`, `render-episode-delivery`, and `validate-episode-delivery` official-delivery acceptance against the `0.8.92` working tree.
- [ ] Run the focused runtime tests in an isolated temporary project:

```bash
python3 -m unittest \
  skills/novel-to-script-director/scripts/test_project_tool.py \
  skills/novel-to-script-director/scripts/test_source_partition.py
```

- [ ] Run `python3 -m py_compile skills/novel-to-script-director/scripts/agent_runtime.py skills/novel-to-script-director/scripts/project_tool.py`.
- [ ] Treat this task as a prerequisite gate. Do not begin Task 1 until the baseline suite passes, official delivery acceptance passes, and the two-failure stop is verified.

## Task 1: Add the synopsis source policy without changing legacy modes

**Files:**
- Modify `/Users/shinchan/Downloads/小说/ai-director/skills/novel-to-script-director/scripts/project_tool.py`
- Modify `/Users/shinchan/Downloads/小说/ai-director/skills/novel-to-script-director/scripts/test_project_tool.py`

- [ ] Extend `SOURCE_KINDS` to include exactly `"synopsis"`.
- [ ] Keep `self_owned`, `storyline`, and `published_novel` behavior unchanged.
- [ ] Keep `official_review_enabled` and `official_url` invalid for `synopsis`, with a dedicated error code and Chinese message explaining that synopsis mode uses only uploaded/pasted synopsis content.
- [ ] Require `--expected-episodes` during `init` when `--source-kind synopsis` is selected; reject missing, zero, negative, and non-integer values before any project state is written.
- [ ] Keep pasted text and file input on one storage path: the host layer writes pasted text as a UTF-8 synopsis source file under `00_原始内容/`, then calls the existing source registration path. The CLI continues to hash and copy files deterministically.
- [ ] Add tests for:
  - synopsis initialization with 1, 20, 30, and 40 episodes;
  - synopsis initialization without episode count;
  - synopsis with official review flags;
  - legacy source kinds and old states;
  - source hash mismatch and project-root path guards.
- [ ] Run:

```bash
python3 -m unittest skills/novel-to-script-director/scripts/test_project_tool.py
```

## Task 2: Define the synopsis project policy and duration/shot contract

**Files:**
- Modify `/Users/shinchan/Downloads/小说/ai-director/skills/novel-to-script-director/scripts/project_tool.py`
- Modify `/Users/shinchan/Downloads/小说/ai-director/skills/novel-to-script-director/scripts/test_project_tool.py`
- Modify `/Users/shinchan/Downloads/小说/ai-director/skills/novel-to-script-director/references/artifact-contracts.md`
- Modify `/Users/shinchan/Downloads/小说/ai-director/skills/novel-to-script-director/references/production-data-schemas.md`

- [ ] Add the following synopsis-only project-spec shape:

```json
{
  "synopsis_policy": {
    "duration_seconds": {"min": 60, "max": 90},
    "minimum_shot_units": 21,
    "composition_policy": "unrestricted"
  }
}
```

- [ ] Validate both bounds as positive integers with `min <= max`; validate `minimum_shot_units` as a positive integer; accept only `"unrestricted"` for the initial composition policy.
- [ ] Use the explicit synopsis range for script and AI shot-plan validation. Do not approximate 60–90 seconds as a legacy target plus tolerance.
- [ ] Retain `target_duration_seconds` as the existing compatibility/display center when needed, but make the new range helper authoritative for synopsis validation.
- [ ] Add a `project_duration_bounds(project_path, state)` helper:
  - synopsis mode returns the explicit range;
  - legacy modes return the existing target/tolerance-derived range;
  - old projects without the new field retain current behavior.
- [ ] Add a `project_minimum_shot_units(project_path, state)` helper:
  - synopsis mode returns the explicit minimum;
  - legacy modes return the existing recommendation without turning it into a hard minimum.
- [ ] Update script and AI shot-plan gates to reject a synopsis episode outside the duration range or below the minimum unit count.
- [ ] Add tests proving:
  - synopsis defaults are 60–90 and 21;
  - custom ranges and minimums work;
  - empty/dialogue/non-dialogue ratios are not rejected;
  - legacy 60-second and tolerance behavior remains unchanged;
  - a 30-episode and 40-episode project uses the same policy without special cases.

## Task 3: Add the synopsis fact index and dynamic feasibility contract

**Files:**
- Create `/Users/shinchan/Downloads/小说/ai-director/skills/novel-to-script-director/scripts/synopsis_contracts.py`
- Create `/Users/shinchan/Downloads/小说/ai-director/skills/novel-to-script-director/scripts/test_synopsis_contracts.py`
- Modify `/Users/shinchan/Downloads/小说/ai-director/skills/novel-to-script-director/scripts/project_tool.py`
- Modify `/Users/shinchan/Downloads/小说/ai-director/skills/novel-to-script-director/scripts/test_project_tool.py`

- [ ] Reuse the existing `source_event_index` artifact key and dependency graph. Do not create a second state machine or a parallel fact authority.
- [ ] Add `source_mode: "synopsis"` and a `synopsis_profile` object to the existing event-index payload. Preserve the existing `units`, `events`, `source_refs`, and version binding fields.
- [ ] Require each synopsis fact to include:
  - stable `fact_id`;
  - `fact_type` from `character`, `relationship`, `setting`, `ability`, `event`, `motivation`, `ending`, or `constraint`;
  - non-empty fact text;
  - non-empty source references;
  - `protection` from `must_preserve`, `flexible`, or `unknown`.
- [ ] Require explicit `unknowns[]` records for unresolved facts. An unknown that affects ending nature, core relationship direction, core ability, or key result must be marked as blocking until the user supplies or approves a policy.
- [ ] Define feasibility output:

```json
{
  "requested_episodes": 40,
  "duration_seconds": {"min": 60, "max": 90},
  "minimum_shot_units": 21,
  "core_fact_groups": ["character", "relationship", "conflict", "setting"],
  "conflict_nodes": ["..."],
  "relationship_turns": ["..."],
  "hook_candidates": ["..."],
  "supporting_expansion_axes": ["..."],
  "verdict": "sufficient",
  "blocking_reasons": [],
  "warnings": []
}
```

- [ ] Implement structural checks for missing core fact groups, missing source references, invalid episode count, invalid policy values, and blocking unknowns.
- [ ] Implement a dynamic coverage check that accepts any positive episode count and rejects a candidate plan when it cannot assign each episode a non-repeating meaningful change, conflict/relationship/information progression, and hook without creating a second mainline.
- [ ] Return `sufficient`, `needs_user_input`, or `insufficient`; never allow a model-produced `"passed"` string to bypass these checks.
- [ ] Add `validate-synopsis <project>` to return the fact-index and feasibility result without generating scripts or modifying project state.
- [ ] Add `show --summary` fields for synopsis mode: requested episodes, duration bounds, minimum units, feasibility verdict, blocking reasons, and warning count.
- [ ] Test 1, 20, 30, and 40 episode inputs. Use the 20-episode school example only as a fixture, not as a rule or template.
- [ ] Add a failing fixture with strong characters but no usable conflict progression; ensure the command blocks before a series map is confirmable.

## Task 4: Add controlled-expansion validation

**Files:**
- Create `/Users/shinchan/Downloads/小说/ai-director/skills/novel-to-script-director/scripts/test_synopsis_contracts.py`
- Modify `/Users/shinchan/Downloads/小说/ai-director/skills/novel-to-script-director/scripts/synopsis_contracts.py`
- Modify `/Users/shinchan/Downloads/小说/ai-director/skills/novel-to-script-director/scripts/project_tool.py`
- Modify `/Users/shinchan/Downloads/小说/ai-director/skills/novel-to-script-director/scripts/test_project_tool.py`
- Modify `/Users/shinchan/Downloads/小说/ai-director/skills/novel-to-script-director/references/artifact-contracts.md`

- [ ] Reuse `adaptation_decision_ledger` and `change_authorization`; do not add a second expansion ledger.
- [ ] Validate an allowed bridge addition only when it includes:
  - stable `decision_id` and `expansion_id`;
  - `operation: "bridge_addition"` or an existing compatible auto-allowed operation;
  - `purpose` in the synopsis allowed categories;
  - non-empty `addition_basis`;
  - non-empty `target_episode_ids`;
  - `source_facts_unchanged: true`;
  - `change_level: "expression_only"` and `source_fact_change: false` for automatic additions;
  - `status: "accepted"` for automatic additions.
- [ ] Require `approved_addition` and a valid `authorization_ref` for new mainlines, new core relationships, new abilities, changed motivations, changed key results, changed world rules, changed ending nature, or a supporting character that becomes a mainline driver.
- [ ] Require every series-map episode and episode script expansion reference to resolve to a valid ledger entry within the episode scope.
- [ ] Reject an expansion that repeats the same source basis and story function without a new state change.
- [ ] Add a synopsis expression-quality review using the existing `quality_review` artifact:
  - no repeated dialogue, repeated reaction, or information-free empty shot used to fill episodes;
  - no generic emotional prose such as “眼底闪过一丝情绪”, “空气突然安静”, “她忍不住勾唇一笑”;
  - no templated episode hooks such as “突然传来一个声音” or “两人关系更进一步”;
  - every added event contains a concrete task, visible resistance, action chain, reaction/turn, and changed state;
  - every added event binds an `expansion_id` and a state change; the same synopsis fact cannot be reused repeatedly as a new episode;
  - character dialogue must match the existing `voice_fingerprint`, and different characters must not all use the same AI-sounding voice;
  - deterministic signals are validator warnings/errors; subjective aesthetic judgments remain human-review items and are not converted into fake AI probability scores.
- [ ] Add tests for allowed school/life bridge events, supporting opponents, transitions, environment reactions, unauthorized new mainlines, core identity changes, ability changes, ending changes, missing basis, invalid scope, duplicate expansion, and stale authorization.
- [ ] Add tests for repeated reaction dialogue, generic emotional prose, templated hooks, duplicate source-basis expansion, and character-voice collision.
- [ ] Run the focused contract tests before wiring the production path:

```bash
python3 -m unittest \
  skills/novel-to-script-director/scripts/test_synopsis_contracts.py
```

## Task 5: Integrate synopsis facts with the existing series-map and approval gates

**Files:**
- Modify `/Users/shinchan/Downloads/小说/ai-director/skills/novel-to-script-director/scripts/project_tool.py`
- Modify `/Users/shinchan/Downloads/小说/ai-director/skills/novel-to-script-director/scripts/test_project_tool.py`
- Modify `/Users/shinchan/Downloads/小说/ai-director/skills/novel-to-script-director/references/workflow.md`
- Modify `/Users/shinchan/Downloads/小说/ai-director/skills/novel-to-script-director/SKILL.md`

- [ ] Keep `series_map` as the only full-series planning artifact. Add required synopsis references to each episode payload:
  - `fact_refs`;
  - `decision_ids`;
  - `expansion_ids`;
  - `state_change`;
  - `end_hook`.
- [ ] Keep dynamic episode coverage as `E001...E{N}` based on confirmed `project_spec.expected_episodes`.
- [ ] Make synopsis map confirmation require:
  - valid synopsis fact index;
  - feasibility verdict `sufficient`;
  - valid project spec;
  - no blocking unknown;
  - series boundary review `passed`;
  - series plan review `passed`;
  - user approval of the exact map version.
- [ ] Keep map approval separate from episode script generation. A confirmed map is necessary but does not bypass per-episode boundary reviews.
- [ ] Add tests proving a map with 20, 30, and 40 episodes is accepted when complete, while a map with missing/duplicate episode IDs or unsupported expansions is rejected.

## Task 6: Integrate sequential episode production and per-episode delivery

**Files:**
- Modify `/Users/shinchan/Downloads/小说/ai-director/skills/novel-to-script-director/scripts/project_tool.py`
- Modify `/Users/shinchan/Downloads/小说/ai-director/skills/novel-to-script-director/scripts/agent_runtime.py`
- Modify `/Users/shinchan/Downloads/小说/ai-director/skills/novel-to-script-director/scripts/test_project_tool.py`
- Modify `/Users/shinchan/Downloads/小说/ai-director/skills/novel-to-script-director/references/workflow.md`
- Modify `/Users/shinchan/Downloads/小说/ai-director/skills/novel-to-script-director/SKILL.md`

- [ ] Add synopsis task scopes to the existing runtime contract:
  - synopsis fact extraction: serial;
  - feasibility/map preparation: serial;
  - episode script writing: serial scheduling key `episode_script`;
  - post-confirmation extraction: bounded parallel by independent episode;
  - AI shot-plan preparation and DOCX/HTML rendering: bounded parallel per ready episode, with one state writer.
- [ ] Ensure E002 cannot start writing until E001 has an accepted result, confirmed episode script, and current continuity checkpoint.
- [ ] Ensure a failed or disconnected worker resumes from its file checkpoint with the same idempotency key and no second valid result.
- [ ] Ensure one episode can produce the existing `render-episode-delivery` outputs:
  - `09_定稿交付/分集交付/E001/E001_剧本.docx`;
  - `09_定稿交付/分集交付/E001/E001_故事板.html`.
- [ ] Keep the default user experience as one episode delivered at a time, without requiring manual confirmation for every episode after the map is confirmed.
- [ ] Add an isolated three-episode fixture proving serial script scheduling and bounded downstream parallelism. Add a separate 40-episode map fixture proving that episode count is not a hidden limit.

## Task 7: Regression, documentation, and release gates

**Files:**
- Modify `/Users/shinchan/Downloads/小说/ai-director/README.md`
- Modify `/Users/shinchan/Downloads/小说/ai-director/CHANGELOG.md`
- Modify `/Users/shinchan/Downloads/小说/ai-director/skills/novel-to-script-director/SKILL.md`
- Modify `/Users/shinchan/Downloads/小说/ai-director/skills/novel-to-script-director/references/workflow.md`
- Modify `/Users/shinchan/Downloads/小说/ai-director/skills/novel-to-script-director/references/artifact-contracts.md`
- Modify `/Users/shinchan/Downloads/小说/ai-director/skills/novel-to-script-director/references/production-data-schemas.md`

- [ ] Document the user input contract:

```text
简介：<粘贴内容或文件>
目标集数：<任意正整数>
单集时长：<可选，synopsis 默认 60–90 秒>
最低分镜数：<可选，synopsis 默认 21 个 AI 分镜单元>
其他要求：<可选>
```

- [ ] Document that the system first returns a fact/feasibility card, then a complete map for user confirmation, then generates episodes serially.
- [ ] Document that `storyline` remains the broad legacy source kind and `synopsis` is the controlled-expansion path.
- [ ] Document that a synopsis cannot support arbitrary episode counts automatically; insufficient coverage blocks instead of filling with repetition.
- [ ] Document that synopsis “降 AI 感” is an expression-quality gate, not a separate post-generation rewrite pipeline; any future humanizer pass must be `expression_only`, must not change dialogue or facts, and must re-run boundary and continuity checks.
- [ ] Add regression tests for all three legacy source kinds, old project states, legacy duration behavior, ordinary series maps, ordinary episode scripts, existing AI shot plans, HTML rendering, and DOCX rendering.
- [ ] Add regression coverage for the new synopsis expression-quality warnings and blockers without changing legacy quality-review behavior.
- [ ] Run the full verification set:

```bash
python3 -m unittest discover -s skills/novel-to-script-director/scripts -p 'test_*.py'
python3 -m py_compile \
  skills/novel-to-script-director/scripts/project_tool.py \
  skills/novel-to-script-director/scripts/agent_runtime.py \
  skills/novel-to-script-director/scripts/synopsis_contracts.py
git diff --check
```

- [ ] Run an isolated black-box synopsis fixture through registration, fact-index validation, feasibility, map approval, E001–E003 serial production, per-episode AI shot-plan validation, and DOCX/HTML rendering.
- [ ] Run a second isolated fixture with `expected_episodes: 40` and no script generation to prove full-map coverage and absence of a 20–25 limit.
- [ ] Confirm the protected real novel project was not read or modified.
- [ ] Do not update version metadata or changelog release numbers until all gates pass and the implementation is explicitly approved for release.

## Acceptance criteria

- `init --source-kind synopsis --expected-episodes N` works for any positive N and rejects missing/invalid N.
- Pasted synopsis is normalized to the same hashed uploaded-file contract as a synopsis file.
- The synopsis fact index distinguishes source facts, unknowns, and generated additions.
- Feasibility blocks unsupported target episode counts before a map can be confirmed.
- A complete map covers exactly `E001...EN` for 20, 30, 40, and arbitrary positive N.
- Controlled expansion accepts only mainline-supporting additions with traceable basis and rejects unauthorized story-fact changes.
- Expression quality gates reject repetitive, filler-driven, and generic AI-sounding expansions without weakening the existing content-boundary and delivery gates.
- Existing project state, artifact dependencies, approval gates, AI shot-plan contract, HTML storyboard, and DOCX delivery remain compatible.
- Adjacent episode writing is serial; independent extraction/rendering is bounded and state-writer-safe.
- One ready episode can be delivered without waiting for the full series.
- Full tests, compile checks, diff checks, and isolated black-box fixtures pass.

## Self-review

- The plan starts from the current `0.8.92` baseline and treats orchestration as already implemented but requiring verification, not as unfinished work to be redone.
- The sample school story is used only as a fixture; no character, setting, plot, or 20-episode assumption appears in the contract.
- The design does not add a synopsis-specific state machine or bypass existing boundary reviews.
- Dynamic episode counts are validated through the project-spec value and exact `E001...EN` coverage.
- The 60–90 second range and 21-unit minimum are scoped to synopsis mode and do not change legacy defaults.
- Ending uncertainty is represented as a blocking unknown unless supplied by the synopsis or explicitly authorized.
- Runtime orchestration is a prerequisite because synopsis sequencing depends on immutable task envelopes, checkpoint recovery, and serial adjacent-episode scheduling.
