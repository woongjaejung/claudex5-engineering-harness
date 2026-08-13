# Superpowers–Claudex5 Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep Superpowers planning and task-loop mechanics while making Claudex5 the authoritative model and agent router, and detect competing `fable-advisor` orchestration on installed machines.

**Architecture:** Install one concise global Claude skill as a compatibility adapter. The adapter activates when Superpowers executes an implementation plan, maps each workflow role onto Claudex5 agents, and leaves Superpowers responsible for worktrees, ledgers, task loops, and review gates. Installation remains non-destructive: `fable-advisor` is never disabled automatically, but runtime verification warns in normal mode and fails in strict mode when it is enabled.

**Tech Stack:** Bash, Claude Code global skills, Markdown skill frontmatter, Python 3.11 test validation, existing shell integration tests

## Global Constraints

- Keep Claudex5 core behavior as global `CLAUDE.md` instructions and agents; the new skill is only a Superpowers compatibility adapter.
- Never modify the installed Superpowers or fable-advisor plugin files because plugin updates would overwrite those changes.
- Never disable, uninstall, or overwrite an existing user plugin without an explicit user command.
- Preserve the existing Claudex5 model matrix: Sonnet primary implementation, Spark only for eligible existing-UI iteration, Opus escalation, Codex Sol review, Luna bounded alternative, Fable judge, deterministic quality gate.
- Install the adapter globally through a repository-owned symbolic link and reject foreign collisions.
- Keep the root README fully English and Korean guidance in `docs/usage-ko.md`.
- Do not copy or commit credentials, tokens, plugin state, or session data.

---

### Task 1: Adapter contract and failing tests

**Files:**
- Modify: `tests/test_merge_config.py`
- Modify: `tests/test_install.sh`
- Modify: `tests/test_common.sh`

**Interfaces:**
- Produces: deterministic assertions for the adapter trigger, routing matrix, global link lifecycle, and enabled-plugin detection.
- Consumes: existing `link.sh`, `uninstall.sh`, and `scripts/common.sh` behavior.

- [ ] **Step 1: Add a failing skill contract test**

Assert that `claude/skills/claudex5-subagent-routing/SKILL.md` exists, has exactly the required `name` and `description` frontmatter keys, triggers on Superpowers plan execution, names every required Claudex5 route, forbids implicit third-party routing, and remains below 500 words.

- [ ] **Step 2: Add failing installation lifecycle tests**

Assert that installation creates `~/.claude/skills/claudex5-subagent-routing/SKILL.md`, repeated installation is idempotent, uninstall removes only the repository-owned link, and a foreign file at that path stops installation without overwrite.

- [ ] **Step 3: Add a failing generic plugin-status test**

Assert that `claudex5_plugin_enabled OUTPUT NAME` recognizes enabled `fable-advisor` and `superpowers` entries while rejecting disabled and substring-only matches.

- [ ] **Step 4: Run the focused tests and observe the missing adapter/helper failures**

Run: `python3 -m unittest tests.test_merge_config.TemplateTests -v && bash tests/test_common.sh && bash tests/test_install.sh`

Expected: failures because the adapter path, lifecycle behavior, and generic plugin helper do not exist.

### Task 2: Skill creation and safe installation

**Files:**
- Create: `claude/skills/claudex5-subagent-routing/SKILL.md`
- Modify: `claude/managed-CLAUDE.md`
- Modify: `link.sh`
- Modify: `uninstall.sh`
- Modify: `verify.sh`
- Modify: `scripts/common.sh`

**Interfaces:**
- Produces: global skill `claudex5-subagent-routing` linked at `~/.claude/skills/claudex5-subagent-routing/SKILL.md`.
- Produces: `claudex5_plugin_enabled(plugin_list: string, plugin_name: string) -> shell status`.
- Produces: normal verification warning and strict verification failure for enabled `fable-advisor`.

- [ ] **Step 1: Initialize the skill scaffold**

Run the bundled `skill-creator/scripts/init_skill.py` for `claudex5-subagent-routing` under `claude/skills`, then remove Codex-only UI metadata that Claude Code does not need.

- [ ] **Step 2: Write the minimal routing adapter**

Define Superpowers as process owner and Claudex5 as routing owner. Map researcher, primary implementer, Spark eligibility, Opus escalation, Luna alternative, per-task Sol review, architecture review, adversarial review, judge, and deterministic verification. Require exact user naming before any third-party routing skill or Grok lane is used.

- [ ] **Step 3: Add the global compatibility instruction**

Require the main Claude session to load `claudex5-subagent-routing` whenever Superpowers SDD or executing-plans is selected, without asking a second execution-mode question.

- [ ] **Step 4: Implement the link and uninstall lifecycle**

Add the repository skill to the existing collision preflight and journal-backed link creation. Uninstall the exact link only when it still targets this repository.

- [ ] **Step 5: Implement conflict detection**

Parse Claude plugin-list entries by exact plugin name and enabled status. Warn for enabled `fable-advisor` in normal verification and fail in `--strict`, including the exact disable command while preserving plugin state.

- [ ] **Step 6: Validate the skill and focused tests**

Run: `python3 "$HOME/.codex/skills/.system/skill-creator/scripts/quick_validate.py" claude/skills/claudex5-subagent-routing && python3 -m unittest tests.test_merge_config.TemplateTests -v && bash tests/test_common.sh && bash tests/test_install.sh`

Expected: skill validation and all focused tests pass.

### Task 3: Documentation and end-to-end publication

**Files:**
- Modify: `README.md`
- Modify: `docs/usage-ko.md`
- Modify if required: `.github/workflows/verify.yml`

**Interfaces:**
- Consumes: adapter installation and conflict detection from Task 2.
- Produces: public instructions for Superpowers coexistence, VPS remediation, updates, explicit routing, and troubleshooting.

- [ ] **Step 1: Document the ownership boundary in English**

Update the diagram, automatic behavior, installation, update, uninstall, and troubleshooting sections. Explain that Superpowers remains enabled and supplies process mechanics while Claudex5 selects roles.

- [ ] **Step 2: Document VPS remediation in Korean**

Show how to inspect scope, disable `fable-advisor`, restart Claude Code, reinstall, strictly verify, and keep Superpowers enabled.

- [ ] **Step 3: Run the complete deterministic suite**

Run shell syntax checks, all Python tests, isolated installation tests, bootstrap tests, credential tests, strict local verification, repository secret scan, English-only README check, and `git diff --check`.

- [ ] **Step 4: Reinstall on the laptop and inspect live links**

Run: `./install.sh && ./verify.sh --strict`

Expected: adapter link is repository-owned, Claude/Codex authentication and official Codex plugin remain ready, Spark remains consistent, and no competing orchestrator is enabled locally.

- [ ] **Step 5: Commit, fast-forward main, and push**

Review all push candidates, commit the plan and implementation, fast-forward local `main`, fetch to ensure the remote has not advanced, push `origin/main`, and confirm the GitHub Actions run succeeds.
