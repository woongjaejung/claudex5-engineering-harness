# Conditional Codex-Spark Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect account-level Spark availability without a model call and install an automatically routed Spark UI-iteration role only when access is confirmed.

**Architecture:** A dependency-free Python probe talks to `codex app-server` over JSONL and returns a three-state result. The installer converts only `available` into an `--enable-spark` flag shared by link creation and configuration merging; verification enforces structural consistency and reports runtime drift as a warning.

**Tech Stack:** Bash, Python 3.11 standard library, TOML, Codex App Server JSON-RPC, `unittest`

## Global Constraints

- Never read, copy, print, or commit Claude or Codex credential files or token values.
- Never send a model inference request merely to test Spark access.
- Enable only the exact model id `gpt-5.3-codex-spark` returned by `model/list`.
- Treat unavailable and indeterminate probes as a successful install with the existing Sonnet fallback.
- Keep the root README entirely English and Korean guidance in `docs/usage-ko.md`.
- Preserve unrelated user configuration and remove only harness-owned links and tables.

---

### Task 1: Capability probe

**Files:**
- Create: `scripts/spark_probe.py`
- Create: `tests/test_spark_probe.py`

**Interfaces:**
- Produces: `probe_spark(codex_command: str, timeout_seconds: float) -> ProbeResult`
- Produces: command exit `0` for available, `1` for unavailable, and `2` for unknown; stdout is the matching state word.

- [ ] **Step 1: Write failing probe tests**

Add fake-process tests for an available first page, an unavailable completed catalog, a paginated catalog, malformed JSON, an app-server error, and a timeout.

- [ ] **Step 2: Run the focused tests and observe the missing-module failure**

Run: `python3 -m unittest tests.test_spark_probe -v`

Expected: `ModuleNotFoundError` for `scripts.spark_probe`.

- [ ] **Step 3: Implement the minimal bounded JSONL client**

Send `initialize`, `initialized`, and paginated `model/list` requests; compare only model identifiers; terminate the child process in every result path; redact protocol details from normal output.

- [ ] **Step 4: Run the focused tests**

Run: `python3 -m unittest tests.test_spark_probe -v`

Expected: all probe tests pass.

### Task 2: Conditional installation and reconciliation

**Files:**
- Create: `codex/agents/harness-spark-ui-iteration.toml`
- Modify: `install.sh`
- Modify: `link.sh`
- Modify: `scripts/merge_config.py`
- Modify: `verify.sh`
- Modify: `tests/test_install.sh`
- Modify: `tests/test_merge_config.py`

**Interfaces:**
- Consumes: probe exit state from Task 1.
- Produces: `link.sh --enable-spark` and `merge_config.py install --enable-spark`.
- Produces: a consistent installed state in which both the Spark link and `[agents.harness_spark_ui_iteration]` exist, or both are absent.

- [ ] **Step 1: Add failing configuration and link tests**

Test enabled registration, disabled cleanup after a previous enabled install, foreign-file preservation, idempotency, uninstall cleanup, and Spark model metadata.

- [ ] **Step 2: Run focused tests and observe failures**

Run: `python3 -m unittest tests.test_merge_config -v && bash tests/test_install.sh`

Expected: failures for the missing Spark template and unsupported enable flag.

- [ ] **Step 3: Implement optional role registration**

Add the bounded UI instructions, conditional link ownership handling, conditional Codex table generation, install-time probing, and structural/runtime verification consistency rules.

- [ ] **Step 4: Run focused tests**

Run: `python3 -m unittest tests.test_merge_config tests.test_spark_probe -v && bash tests/test_install.sh && bash tests/test_verify.sh`

Expected: all focused tests pass.

### Task 3: Natural routing and user documentation

**Files:**
- Modify: `claude/managed-CLAUDE.md`
- Modify: `codex/managed-AGENTS.md`
- Modify: `README.md`
- Modify: `docs/usage-ko.md`

**Interfaces:**
- Consumes: the optional role link installed by Task 2.
- Produces: automatic routing rules, explicit invocation examples, update instructions, removal behavior, and mismatch troubleshooting.

- [ ] **Step 1: Update global routing instructions**

Allow Spark only for small existing-UI changes while the role is registered; keep Sonnet as the silent automatic fallback and prohibit Spark for high-risk or broad work.

- [ ] **Step 2: Update English documentation**

Add Spark to the architecture diagram and role matrix, explain the capability probe, show ordinary and explicit usage, and document update and troubleshooting commands without Korean text.

- [ ] **Step 3: Update Korean usage guidance**

Explain automatic eligibility, fallback, explicit role invocation, local/VPS update commands, removal, and access-mismatch recovery in Korean.

- [ ] **Step 4: Check documentation and whitespace**

Run: `git diff --check && python3 -c 'import re, pathlib; raise SystemExit(1 if re.search(r"[가-힣]", pathlib.Path("README.md").read_text()) else 0)'`

Expected: no whitespace errors and no Hangul in the root README.

### Task 4: End-to-end verification and publication

**Files:**
- Modify if required by validation: `.github/workflows/verify.yml`

**Interfaces:**
- Consumes: all prior tasks.
- Produces: test evidence, a local reconciled installation, a secret-safe commit, and a pushed default branch.

- [ ] **Step 1: Run the complete deterministic suite**

Run the same shell syntax, Python, isolated install, bootstrap, credential, repository scan, and whitespace checks defined in `.github/workflows/verify.yml`.

- [ ] **Step 2: Test the real local model-list probe**

Run: `python3 scripts/spark_probe.py`

Expected on this Pro-authorized laptop: stdout `available` and exit `0`, with no model turn started.

- [ ] **Step 3: Reinstall and strictly verify the laptop**

Run: `./install.sh && ./verify.sh --strict`

Expected: the Spark role and table are enabled consistently, existing settings remain merged, and strict verification has zero failures.

- [ ] **Step 4: Review push candidates**

Run: `git status --short`, `git diff --check`, `./verify.sh --secrets-only`, and inspect the complete diff.

Expected: only planned public files are present and the secret scan reports zero failures.

- [ ] **Step 5: Commit, fast-forward the default branch, and push**

Commit the verified feature, fast-forward `main` to the feature commit, and push `origin/main` only after confirming the remote has not advanced.
