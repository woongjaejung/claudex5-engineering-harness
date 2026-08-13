# Subagent Model Status Line Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Display each running Claudex5 Claude subagent's configured model and reasoning effort while preserving unrelated status-line configuration.

**Architecture:** A dependency-free Python renderer consumes Claude Code's `subagentStatusLine` JSON input and overrides only exact Claudex5 agent names. The installer links that renderer globally and merges one owned setting only when no foreign setting exists; verification and uninstall use the same exact ownership marker.

**Tech Stack:** Python standard library, Bash, Claude Code `subagentStatusLine`, JSON settings, Python `unittest`

## Global Constraints

- Keep agent identifiers and frontmatter model declarations unchanged.
- Render only exact Claudex5 Claude agent names; omit unknown tasks so Claude Code keeps their default rows.
- Preserve an existing foreign `subagentStatusLine` and the independent top-level `statusLine` setting.
- Never read credentials, transcripts, authentication state, or network resources.
- Keep the renderer compatible with Python 3.9 even though installation requires Python 3.11 or newer.
- Keep the root README fully English and Korean instructions in `docs/usage-ko.md`.

---

### Task 1: Model-aware row renderer

**Files:**
- Create: `claude/statuslines/claudex5-subagent-models.py`
- Create: `tests/test_subagent_statusline.py`
- Modify: `tests/test_merge_config.py`

**Interfaces:**
- Consumes: one JSON object on standard input with a `tasks` array containing `id`, `name`, and optional `description`.
- Produces: one JSON line per exact Claudex5 task with `{"id": string, "content": string}`.
- Produces: `ROLE_LABELS: dict[str, str]`, covering every file in `claude/agents/`.

- [ ] **Step 1: Write failing renderer tests**

Test exact output for `harness-implementer`, all eight role mappings, unknown-agent omission, missing descriptions, control-character-safe JSON, and malformed input returning a non-zero status without echoing input.

- [ ] **Step 2: Run the focused tests and observe the missing renderer failure**

Run: `python3.11 -m unittest tests.test_subagent_statusline -v`

Expected: failure because `claude/statuslines/claudex5-subagent-models.py` does not exist.

- [ ] **Step 3: Implement the minimal renderer**

Use `json.load(sys.stdin)`, validate the root object and `tasks` list, map exact names to friendly labels, normalize the description to one display line, and emit `json.dumps({"id": task_id, "content": content}, ensure_ascii=False)` only for mapped tasks.

- [ ] **Step 4: Add the template consistency contract**

Extend `TemplateTests` to assert that renderer keys exactly match the eight Claude agent frontmatter names and that each friendly label agrees with its `model` and `effort`.

- [ ] **Step 5: Run focused tests**

Run: `python3.11 -m unittest tests.test_subagent_statusline tests.test_merge_config.TemplateTests -v`

Expected: all renderer and template-contract tests pass.

### Task 2: Safe settings and link lifecycle

**Files:**
- Modify: `scripts/merge_config.py`
- Modify: `link.sh`
- Modify: `uninstall.sh`
- Modify: `verify.sh`
- Modify: `tests/test_merge_config.py`
- Modify: `tests/test_install.sh`

**Interfaces:**
- Produces: `CLAUDEX5_SUBAGENT_STATUS_COMMAND = "~/.claude/statuslines/claudex5-subagent-models.py"`.
- Produces: `merge_claude_settings(...) -> list[str]`, installing the owned setting only when absent or already owned.
- Produces: uninstall behavior that removes only the exact owned setting.
- Produces: global renderer link at `~/.claude/statuslines/claudex5-subagent-models.py`.

- [ ] **Step 1: Write failing settings ownership tests**

Assert absent settings gain the exact command, repeat merges are idempotent, a foreign setting and top-level `statusLine` survive unchanged with a warning, and uninstall removes only the exact owned setting.

- [ ] **Step 2: Write failing install lifecycle tests**

Assert install creates the renderer link and setting, rollback removes the new link, foreign link collisions fail without overwrite, repeat install remains stable, and uninstall removes only repository-owned state.

- [ ] **Step 3: Run focused tests and observe lifecycle failures**

Run: `python3.11 -m unittest tests.test_merge_config -v && bash tests/test_install.sh`

Expected: failures for the missing setting merge and renderer link lifecycle.

- [ ] **Step 4: Implement the settings ownership boundary**

Add the exact command constant, preserve foreign dictionaries or invalid shapes with a warning rather than overwrite, set the owned command when absent, and remove it only on exact dictionary equality during uninstall.

- [ ] **Step 5: Implement link and verification behavior**

Add the renderer source/destination to collision preflight, journal rollback, expected links, and ownership-aware uninstall. Structural verification warns for missing or foreign settings; strict verification fails. Active settings pass.

- [ ] **Step 6: Run focused lifecycle tests**

Run: `python3.11 -m unittest tests.test_merge_config -v && bash tests/test_install.sh`

Expected: all settings and lifecycle tests pass.

### Task 3: Routing labels, documentation, and publication

**Files:**
- Modify: `claude/managed-CLAUDE.md`
- Modify: `claude/skills/claudex5-subagent-routing/SKILL.md`
- Modify: `README.md`
- Modify: `docs/usage-ko.md`

**Interfaces:**
- Produces: Codex task-description convention `[Codex Sol · high]`, `[Codex Luna · max]`, and `[Codex-Spark]` when the invoking interface exposes a description.
- Produces: public update and inspection instructions for local computers and servers.

- [ ] **Step 1: Add routing and documentation contract tests**

Require all three Codex labels in managed routing instructions, require the README to remain English-only, and require both language guides to describe the Claudex5-only status-row behavior and foreign-setting preservation.

- [ ] **Step 2: Run contract tests and observe missing documentation failures**

Run: `python3.11 -m unittest tests.test_merge_config.TemplateTests -v`

Expected: failure because the Codex labels and model-status documentation are absent.

- [ ] **Step 3: Update routing instructions and documentation**

Require visible Codex task descriptions to carry the exact label when supported. Document example Claude rows, why Codex plugin tasks differ, update commands, `/agents` and `/tasks` inspection, conflict warnings, and uninstall behavior.

- [ ] **Step 4: Run the full deterministic suite**

Run shell syntax checks, all Python tests, common helper tests, isolated installation tests, bootstrap tests, credential tests, README language check, secret scan, and `git diff --check`.

- [ ] **Step 5: Reinstall and verify on the laptop**

Run: `./install.sh && ./verify.sh --strict`

Expected: the renderer link and exact setting are active, existing top-level status line remains, Claude/Codex authentication and the official plugin remain ready, Spark remains consistent, and no competing router is enabled.

- [ ] **Step 6: Commit, fast-forward main, push, and verify CI**

Review all push candidates, commit the implementation, fetch to ensure `origin/main` has not advanced, fast-forward local `main`, rerun the full suite, push `origin/main`, and confirm the GitHub Actions `Verify` workflow succeeds.
