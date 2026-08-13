# Conditional Codex Sol Plan Review Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a conditional, fresh Codex Sol high review of complex or high-risk Fable implementation plans before code changes begin.

**Architecture:** A dedicated read-only Codex role defines the plan-review decision contract. Global Claude and Superpowers adapter instructions own the eligibility gate and bounded revise/recheck flow, while the existing installer registers and verifies the new role without persisting plan contents or changing credentials.

**Tech Stack:** Codex agent TOML, Claude global Markdown instructions, Bash installer, Python TOML merger, Python `unittest`

## Global Constraints

- Fable remains the plan owner and Sol never edits files or rewrites the plan.
- Trigger when any approved complexity or risk condition applies; skip routine simple plans.
- Use a fresh `gpt-5.6-sol` context with `model_reasoning_effort = "high"`.
- Allow one Fable revision and one fresh Sol recheck; stop before implementation if blocking findings remain.
- Return only `APPROVE` or `NEEDS CHANGES` with evidence-based findings.
- Never persist plan contents, review output, credentials, tokens, or model responses.
- Keep the root README fully English and Korean guidance in `docs/usage-ko.md`.

---

### Task 1: Dedicated plan-review role and registration

**Files:**
- Create: `codex/agents/harness-sol-plan-review.toml`
- Modify: `scripts/merge_config.py`
- Modify: `link.sh`
- Modify: `verify.sh`
- Modify: `tests/test_merge_config.py`
- Modify: `tests/test_install.sh`

**Interfaces:**
- Produces: Codex role key `harness_sol_plan_review` using `harness-sol-plan-review.toml`.
- Produces: reviewer decisions `APPROVE` or `NEEDS CHANGES` without file edits.
- Consumes: existing `BASE_CODEX_AGENT_FILES`, collision-safe link journal, and structural verification.

- [ ] **Step 1: Write failing template and lifecycle tests**

Add the exact file to the expected Codex role matrix, require Sol/high and reviewer contract phrases, require installation and rollback links, and require the registered `[agents.harness_sol_plan_review]` table exactly once.

- [ ] **Step 2: Run focused tests and observe missing-role failures**

Run: `python3.11 -m unittest tests.test_merge_config.TemplateTests -v && bash tests/test_install.sh`

Expected: failures because the plan-review file, link, and configuration table do not exist.

- [ ] **Step 3: Implement the minimal role**

Create a read-only reviewer prompt covering requirements, assumptions, architecture, dependencies, test-first criteria, security, migration, rollback, recovery, and simpler alternatives. Require one exact decision and evidence for every blocking finding.

- [ ] **Step 4: Register the role through the existing lifecycle**

Add the role to `BASE_CODEX_AGENT_FILES`, `CODEX_AGENT_DESCRIPTIONS`, link source/destination arrays, and `verify.sh` expected links. Existing uninstall globs remove the repository-owned link and the merger removes its owned table.

- [ ] **Step 5: Run focused lifecycle tests**

Run: `python3.11 -m unittest tests.test_merge_config -v && bash tests/test_install.sh`

Expected: all role, idempotence, rollback, collision, and uninstall tests pass.

### Task 2: Conditional pre-implementation routing gate

**Files:**
- Modify: `claude/managed-CLAUDE.md`
- Modify: `claude/skills/claudex5-subagent-routing/SKILL.md`
- Modify: `claude/agents/harness-orchestrator.md`
- Modify: `codex/managed-AGENTS.md`
- Modify: `tests/test_merge_config.py`

**Interfaces:**
- Consumes: a newly drafted implementation plan and its requirements.
- Produces: a pre-implementation route to `harness_sol_plan_review` when any eligibility condition matches.
- Produces: at most one revision and one fresh recheck before stop-and-escalate.

- [ ] **Step 1: Write a failing routing contract test**

Require all five trigger categories, explicit simple-plan skip behavior, fresh/read-only Sol high, both decision names, Fable ownership, the one-recheck limit, stop-before-code behavior, and the visible `[Codex Sol · high] Plan review` label.

- [ ] **Step 2: Run the contract test and observe missing-gate failures**

Run: `python3.11 -m unittest tests.test_merge_config.TemplateTests -v`

Expected: failure because current routing instructions do not define a pre-implementation plan gate.

- [ ] **Step 3: Implement the routing contract**

Add one concise gate to global Claude instructions, the Superpowers adapter, and Fable orchestrator. Add equivalent direct-Codex guidance. Keep the skill below its existing 500-word contract.

- [ ] **Step 4: Run routing and skill validation tests**

Run: `python3.11 -m unittest tests.test_merge_config.TemplateTests -v`

Expected: all template and routing contract tests pass.

### Task 3: Public documentation, live verification, and publication

**Files:**
- Modify: `README.md`
- Modify: `docs/usage-ko.md`

**Interfaces:**
- Produces: English and Korean explanations of automatic eligibility, decisions, fallback, visible task label, manual invocation, and update behavior.

- [ ] **Step 1: Document the new gate**

Update the architecture diagram, role matrix, automatic/manual boundaries, explicit role examples, troubleshooting, and Korean usage flow. State that simple plans skip Sol and that a second blocking review stops before implementation.

- [ ] **Step 2: Run the complete deterministic suite**

Run shell syntax checks, all Python tests, common helper tests, isolated installation tests, bootstrap tests, credential tests, secret scan, README language check, and `git diff --check`.

- [ ] **Step 3: Reinstall and strictly verify the laptop**

Run: `./install.sh && ./verify.sh --strict`

Expected: the new plan-review link and Codex table are active exactly once; Claude/ChatGPT authentication, the official Codex plugin, Spark, model status rows, and competing-router checks remain green.

- [ ] **Step 4: Run a read-only Claude routing dry run**

Ask `harness-orchestrator` to classify one simple plan and one five-task security migration plan without editing or invoking implementation. Expected: simple plan skips the gate; risky plan selects fresh Sol high, allows one revision/recheck, and stops on a second blocker.

- [ ] **Step 5: Merge, push, and verify continuous integration**

Review push candidates, commit changes, fetch and confirm `origin/main` has not advanced, fast-forward local `main`, rerun the complete suite, push `origin/main`, and wait for GitHub Actions `Verify` success.
