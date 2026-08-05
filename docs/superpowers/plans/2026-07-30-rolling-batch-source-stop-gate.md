# Rolling Batch Source Stop Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent source-analysis windows from running independently of B01 and enforce a machine checkpoint after every window.

**Architecture:** Upgrade rolling progress to schema v2 with explicit batch readiness. Validate the pure payload in `source_partition.py`, then add project-state gates in `project_tool.py` so only a confirmed rolling batch can request a window.

**Tech Stack:** Python 3 standard library, unittest, JSON artifacts, Codex local plugin cache.

## Global Constraints

- Do not modify `/Users/shinchan/Desktop/小说/温夜有染_AI导演项目副本`.
- Preserve existing analyzed chapter files and schema v1 read compatibility.
- Release as v0.8.7; do not overwrite v0.8.6 cache.

---

### Task 1: Add failing pure-contract tests

**Files:**
- Modify: `skills/novel-to-script-director/scripts/test_source_partition.py`

- [ ] Reject `SA01` as `current_batch_id`.
- [ ] Validate schema v2 readiness invariants.
- [ ] Reject a new window when readiness is `ready_for_batch`.
- [ ] Allow a subsequent window only for `needs_more_source` with concrete gap reasons.

### Task 2: Add failing command-level tests

**Files:**
- Modify: `skills/novel-to-script-director/scripts/test_project_tool.py`

- [ ] Reject planning without a confirmed rolling project spec and B01.
- [ ] Allow the first window after B01 is confirmed.
- [ ] Block the second window when the progress checkpoint says B01 is ready.

### Task 3: Implement schema and project-state gates

**Files:**
- Modify: `skills/novel-to-script-director/scripts/source_partition.py`
- Modify: `skills/novel-to-script-director/scripts/project_tool.py`

- [ ] Add schema v2 validation.
- [ ] Require canonical Bxx current batch IDs.
- [ ] Stop planning on `ready_for_batch`.
- [ ] Require a confirmed rolling project spec and matching confirmed project batch.
- [ ] Return the planned window number and checkpoint-required instruction.

### Task 4: Update v0.8.7 documentation and metadata

**Files:**
- Modify: `.codex-plugin/plugin.json`
- Modify: `CHANGELOG.md`
- Modify: `README.md`
- Modify: `skills/novel-to-script-director/SKILL.md`
- Modify: `skills/novel-to-script-director/references/workflow.md`
- Modify: `skills/novel-to-script-director/references/production-data-schemas.md`

- [ ] Document that SAxx is not a production batch.
- [ ] Document the stop/continue decision after every source window.
- [ ] Bump the version to 0.8.7 and update the verified test count.

### Task 5: Verify, publish, and install

- [ ] Run targeted red-green tests.
- [ ] Run the complete suite.
- [ ] Run a read-only black-box probe against the real duplicate project.
- [ ] Commit and push the plugin subtree to GitHub main.
- [ ] Remove v0.8.6 cache and install a clean v0.8.7 cache.
