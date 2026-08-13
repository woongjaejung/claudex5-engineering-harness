# Claudex5 Live Graph Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add private lifecycle collection plus terminal and local-web node-and-edge views for active Claudex5 runs.

**Architecture:** Claude hooks and explicit Codex/quality-gate wrappers normalize safe events into a locked append-only store and an atomic derived snapshot. Zero-dependency terminal and SVG web renderers consume the same snapshot, while installation merges exact namespaced hooks and links without replacing existing settings.

**Tech Stack:** Python 3.11 standard library, POSIX shell, Claude Code command hooks, `unittest`, HTML/CSS/vanilla JavaScript/SVG.

## Global Constraints

- Work only on `agent/live-graph-dashboard`; keep `main` unchanged until the user explicitly chooses integration.
- Support macOS and Debian/Ubuntu with Python 3.11 or newer and no new runtime dependency.
- Store runtime data only below `${XDG_STATE_HOME:-~/.local/state}/claudex5-engineering-harness/runs` with directories `0700` and files `0600`.
- Never persist prompts, code, commands, tool results, assistant messages, transcript paths, environment variables, credentials, tokens, or model catalogs.
- Preserve all foreign hooks, plugins, instructions, `statusLine`, and `subagentStatusLine` values.
- Bind the web dashboard only to loopback addresses.
- Keep hook failures non-blocking and never echo malformed or sensitive input.
- Use a failing behavioral test before every production-code increment.

---

### Task 1: Event model, reduction, and private state store

**Files:**
- Create: `scripts/live_graph/__init__.py`
- Create: `scripts/live_graph/model.py`
- Create: `scripts/live_graph/store.py`
- Create: `tests/test_live_graph_model.py`
- Create: `tests/test_live_graph_store.py`

**Interfaces:**
- Produces: `sanitize_label(value: object, limit: int = 120) -> str`
- Produces: `new_snapshot(session_id: str, cwd: str, timestamp: str) -> dict[str, object]`
- Produces: `reduce_event(snapshot: dict[str, object], event: dict[str, object]) -> dict[str, object]`
- Produces: `StateStore(root: Path | None = None, lock_timeout: float = 0.2)`
- Produces: `StateStore.append(session_id, event_type, node_id, payload, source="explicit") -> dict`
- Produces: `StateStore.load(session_id)`, `latest(cwd=None)`, `cleanup(max_age_days=7)`, and `clear_all()`

- [ ] **Step 1: Write failing model tests**

Create literal-fixture tests proving that secret-shaped labels become `[REDACTED]`, controls collapse to one line, terminal states cannot restart, duplicate events are idempotent, dependencies become stable edges, and a finish without a start creates a degraded terminal node.

- [ ] **Step 2: Run the model tests and observe the missing-module failure**

Run:

```bash
/opt/homebrew/bin/python3.11 -m unittest tests.test_live_graph_model -v
```

Expected: import failure for `scripts.live_graph.model`.

- [ ] **Step 3: Implement the minimal pure model**

Use dictionaries with `schema_version: 1`, stable node/edge identifiers, the seven specified node states, the five edge kinds, UTC timestamps, and role metadata for every current `harness-*` Claude and Codex role. Keep validation and state transition logic independent of the filesystem.

- [ ] **Step 4: Run model tests to green**

Run the same command and require zero failures.

- [ ] **Step 5: Write failing store tests**

Use temporary directories and real files to prove mode `0700`/`0600`, monotonically increasing sequence values, event-log and snapshot recovery, bounded cleanup, latest-active selection by canonical `cwd`, malformed final-line tolerance, earlier corruption degradation, and symlink rejection.

- [ ] **Step 6: Run store tests and observe the missing implementation failure**

Run:

```bash
/opt/homebrew/bin/python3.11 -m unittest tests.test_live_graph_store -v
```

- [ ] **Step 7: Implement the minimal locked atomic store**

Use `fcntl.flock` with non-blocking polling and a monotonic deadline, reject symlinks component-by-component, append and `fsync` the JSONL event while locked, then atomically replace `snapshot.json` in the same directory. Never accept a caller-supplied path or sequence number.

- [ ] **Step 8: Run Task 1 tests and the existing Python suite**

```bash
/opt/homebrew/bin/python3.11 -m unittest tests.test_live_graph_model tests.test_live_graph_store -v
/opt/homebrew/bin/python3.11 -m unittest discover -s tests -v
```

- [ ] **Step 9: Commit Task 1**

```bash
git add scripts/live_graph tests/test_live_graph_model.py tests/test_live_graph_store.py
git commit -m "feat: add private live graph state model"
```

---

### Task 2: Hook recorder and lifecycle normalization

**Files:**
- Create: `scripts/live_graph/record.py`
- Create: `claude/hooks/claudex5-live-graph.py`
- Create: `tests/test_live_graph_record.py`

**Interfaces:**
- Consumes: Task 1 `StateStore`, `sanitize_label`, and `reduce_event`
- Produces: `normalize_hook(payload: object) -> list[dict[str, object]]`
- Produces: `record_hook(payload: object, store: StateStore) -> list[dict[str, object]]`
- Produces: executable hook accepting exactly one JSON object on standard input

- [ ] **Step 1: Write failing recorder tests**

Exercise real hook-shaped payloads for `SessionStart`, `PreToolUse:TaskCreate`, `PostToolUse:TaskUpdate`, `SubagentStart`, `SubagentStop`, `Stop`, and `SessionEnd`. Assert that only session ID, canonical current directory, safe task title/dependencies, agent ID/type, state, role metadata, and timestamps reach persisted snapshots. Include a payload containing a fake bearer token in `last_assistant_message`, tool output, transcript paths, and commands and assert none appears anywhere under the temporary state root.

- [ ] **Step 2: Run recorder tests and confirm RED**

```bash
/opt/homebrew/bin/python3.11 -m unittest tests.test_live_graph_record -v
```

- [ ] **Step 3: Implement lifecycle normalization**

Map hook events to model events using allowlisted fields. Treat `Stop` as a checkpoint, not session completion. Ignore unknown unsafe payloads. Return quickly on store-lock timeout. Print only stable error categories such as `invalid-input` or `store-unavailable` to standard error.

- [ ] **Step 4: Implement the stable hook entry point**

Resolve the real repository from `Path(__file__).resolve()`, add it to `sys.path`, call `record.main()`, and exit zero for all runtime collection failures. Add `--self-test` as the only mode that propagates failure.

- [ ] **Step 5: Run recorder tests and a no-echo malformed-input smoke test**

```bash
/opt/homebrew/bin/python3.11 -m unittest tests.test_live_graph_record -v
printf '%s' '{"private":"bearer abcdefghijklmnopqrstuvwxyz"' | claude/hooks/claudex5-live-graph.py 2>&1 | grep -v 'abcdefghijklmnopqrstuvwxyz'
```

- [ ] **Step 6: Commit Task 2**

```bash
git add scripts/live_graph/record.py claude/hooks/claudex5-live-graph.py tests/test_live_graph_record.py
git commit -m "feat: collect safe Claude lifecycle events"
```

---

### Task 3: Terminal, web, and command-line dashboard

**Files:**
- Create: `scripts/live_graph/terminal.py`
- Create: `scripts/live_graph/web.py`
- Create: `scripts/live_graph_cli.py`
- Create: `bin/claudex5`
- Create: `tests/test_live_graph_terminal.py`
- Create: `tests/test_live_graph_web.py`
- Create: `tests/test_live_graph_cli.py`

**Interfaces:**
- Consumes: Task 1 snapshots and store selection
- Produces: `render_snapshot(snapshot, columns=120, color=False, unicode=True) -> str`
- Produces: `make_handler(store, session_id=None) -> type[BaseHTTPRequestHandler]`
- Produces: `serve_dashboard(store, session_id, host, port, open_browser) -> int`
- Produces: `main(argv: Sequence[str] | None = None) -> int`
- Produces commands: `dashboard`, `status`, `event`, `codex-run`, `gate-run`, and `clean`

- [ ] **Step 1: Write failing terminal tests**

Use a hand-built snapshot to assert literal wide graph output with branch connectors and all status symbols, literal narrow dependency-list output below 88 columns, ASCII fallback, safe clipping, deterministic ordering, current-role/model display, progress count, and empty-state output.

- [ ] **Step 2: Run terminal tests and confirm RED**

```bash
/opt/homebrew/bin/python3.11 -m unittest tests.test_live_graph_terminal -v
```

- [ ] **Step 3: Implement the terminal renderer**

Keep layout deterministic: topological rank, event sequence, then node ID. Redraw only when text changes, clear the screen only in follow mode, and handle `SIGINT` without a traceback.

- [ ] **Step 4: Write failing web tests**

Start the real standard-library HTTP server on an ephemeral loopback port. Assert fixed routes `/`, `/app.js`, `/style.css`, and `/api/snapshot`; JSON shape; `Cache-Control: no-store`; Content Security Policy; `nosniff`; 404 behavior; HTML escaping; and rejection of `0.0.0.0` and non-loopback addresses.

- [ ] **Step 5: Run web tests and confirm RED, then implement local SVG rendering**

```bash
/opt/homebrew/bin/python3.11 -m unittest tests.test_live_graph_web -v
```

Serve constant assets from memory. Use vanilla JavaScript to poll once per second, topologically rank nodes, draw SVG edges before nodes, color by state, retain the last graph on polling failure, and show a disconnected badge.

- [ ] **Step 6: Write failing CLI behavior tests**

Run the real entry point in an isolated temporary `HOME`. Assert latest-run selection, `--once`, JSON `status`, explicit start/finish events, `clean`, prompt-through-stdin Codex command construction, exact fixed role model/effort, original child exit status, and gate child exit status. Replace only the external `codex` executable with a complete fake process; keep store and subprocess behavior real.

- [ ] **Step 7: Run CLI tests and confirm RED, then implement the command**

```bash
/opt/homebrew/bin/python3.11 -m unittest tests.test_live_graph_cli -v
```

`codex-run` must invoke `codex exec --ephemeral --model <fixed-role-model> -c model_reasoning_effort="<fixed-role-effort>" --sandbox <validated-mode> -` and feed the prompt through standard input. `gate-run` must use `--` to delimit the exact child command and must not use a shell.

- [ ] **Step 8: Run all Task 3 tests and commit**

```bash
/opt/homebrew/bin/python3.11 -m unittest tests.test_live_graph_terminal tests.test_live_graph_web tests.test_live_graph_cli -v
git add bin scripts/live_graph scripts/live_graph_cli.py tests/test_live_graph_terminal.py tests/test_live_graph_web.py tests/test_live_graph_cli.py
git commit -m "feat: add live terminal and web graph dashboard"
```

---

### Task 4: Safe installation, hook merging, role routing, and quality gates

**Files:**
- Modify: `scripts/merge_config.py`
- Modify: `link.sh`
- Modify: `install.sh`
- Modify: `uninstall.sh`
- Modify: `verify.sh`
- Modify: `tests/test_merge_config.py`
- Modify: `tests/test_install.sh`
- Modify: `claude/managed-CLAUDE.md`
- Modify: `claude/skills/claudex5-subagent-routing/SKILL.md`
- Modify: `project-template/scripts/quality-gate.sh`

**Interfaces:**
- Consumes: Tasks 2 and 3 executable entry points
- Produces: idempotent exact hook entries for lifecycle and structured task events
- Produces links: `~/.local/bin/claudex5` and `~/.claude/hooks/claudex5-live-graph.py`
- Produces: uninstall removal of exact owned hook entries and links only

- [ ] **Step 1: Write failing merge and installation tests**

Assert behavior rather than source text: merge a settings fixture containing foreign old-style and current-style hooks plus both status-line keys; verify exact foreign structures remain, each Claudex5 hook appears once after two installs, the new links target this repository, modes are executable, rollback removes links and hook entries, and uninstall preserves foreign hooks and runtime history.

- [ ] **Step 2: Run focused integration tests and confirm RED**

```bash
/opt/homebrew/bin/python3.11 -m unittest tests.test_merge_config -v
CLAUDEX5_TEST_PYTHON=/opt/homebrew/bin/python3.11 bash tests/test_install.sh
```

- [ ] **Step 3: Implement exact hook merge/unmerge and links**

Define immutable owned hook objects for `SessionStart`, `PreToolUse`, `PostToolUse`, `SubagentStart`, `SubagentStop`, `Stop`, and `SessionEnd`. Append without normalizing foreign objects. Remove by exact equality only. Extend the existing transaction journal, structural verifier, collision protection, and symlink checks.

- [ ] **Step 4: Update routing and quality-gate execution**

Require `claudex5 codex-run` for automatic harness Codex roles when available and preserve manual `/codex:*` commands as an observable best-effort path. Wrap each discovered quality command with `claudex5 gate-run --name <name> --` when the command exists; fall back to direct execution with an explicit warning only when the installed command is unavailable.

- [ ] **Step 5: Validate the modified routing skill**

```bash
"$HOME/miniforge3/bin/python3" "$HOME/.codex/skills/.system/skill-creator/scripts/quick_validate.py" claude/skills/claudex5-subagent-routing
wc -w claude/skills/claudex5-subagent-routing/SKILL.md
```

Require valid frontmatter and fewer than 500 words.

- [ ] **Step 6: Run focused and full installation tests, then commit**

```bash
/opt/homebrew/bin/python3.11 -m unittest tests.test_merge_config -v
CLAUDEX5_TEST_PYTHON=/opt/homebrew/bin/python3.11 bash tests/test_install.sh
./verify.sh --secrets-only
git add scripts/merge_config.py link.sh install.sh uninstall.sh verify.sh tests/test_merge_config.py tests/test_install.sh claude/managed-CLAUDE.md claude/skills/claudex5-subagent-routing/SKILL.md project-template/scripts/quality-gate.sh
git commit -m "feat: install live graph lifecycle tracking"
```

---

### Task 5: Documentation, live smoke test, security review, and full verification

**Files:**
- Modify: `README.md`
- Modify: `docs/usage-ko.md`
- Modify: `SECURITY.md`
- Modify: `.github/workflows/verify.yml`
- Modify: `tests/test_verify.sh`

**Interfaces:**
- Consumes: all previous tasks
- Produces: public English documentation, Korean usage guide, security boundary, CI coverage, and verified local installation

- [ ] **Step 1: Extend security verification tests before changing verification behavior**

Add fixtures proving private runtime data is outside Git candidates, unsafe web-bind flags are rejected, installed state files have private permissions, and secret-shaped synthetic labels are absent from snapshots and dashboard HTTP responses.

- [ ] **Step 2: Run security verification tests and confirm RED**

```bash
bash tests/test_verify.sh
```

- [ ] **Step 3: Implement verifier and CI coverage**

Add Python live-graph tests, hook/CLI smoke tests, shell syntax checks, and security assertions to CI without requiring Claude, Codex authentication, a browser, or network access.

- [ ] **Step 4: Update public documentation**

Keep `README.md` entirely English. Add the graph architecture, commands, status legend, privacy model, SSH tunnel instructions, automatic/manual boundaries, update, uninstall, cleanup, and troubleshooting. Add equivalent Korean usage instructions only to `docs/usage-ko.md`. Document localhost-only serving and noncollection of prompts in `SECURITY.md`.

- [ ] **Step 5: Run the full deterministic suite**

```bash
for script in install.sh link.sh uninstall.sh verify.sh bootstrap-system.sh scripts/*.sh tests/*.sh project-template/scripts/*.sh bin/claudex5; do bash -n "$script"; done
/opt/homebrew/bin/python3.11 -m unittest discover -s tests -v
bash tests/test_common.sh
CLAUDEX5_TEST_PYTHON=/opt/homebrew/bin/python3.11 bash tests/test_install.sh
bash tests/test_bootstrap.sh
bash tests/test_verify.sh
./verify.sh --secrets-only
git diff --check
```

- [ ] **Step 6: Install on the laptop and run strict verification**

```bash
./install.sh
./verify.sh --strict
```

Confirm that Claude subscription login, ChatGPT subscription login, official Codex plugin readiness, existing status lines, hooks, and the new graph links all remain healthy.

- [ ] **Step 7: Run a synthetic end-to-end graph smoke test**

Use `claudex5 event` to create a private synthetic session with two dependent tasks, one Sonnet subagent, one Sol review, and lint/test gates. Confirm `claudex5 dashboard --once` shows the correct edges and terminal states. Start `claudex5 dashboard --web --no-open --port 0`, fetch the loopback snapshot once, verify headers and matching nodes, then stop the server.

- [ ] **Step 8: Review security and correctness evidence**

Inspect the full diff, runtime state permissions, hook merge results, HTTP routes, subprocess construction, cleanup boundaries, and secret scan. Resolve every blocking finding and rerun affected tests.

- [ ] **Step 9: Commit documentation and verification**

```bash
git add README.md docs/usage-ko.md SECURITY.md .github/workflows/verify.yml tests/test_verify.sh
git commit -m "docs: explain live harness graph dashboard"
```

- [ ] **Step 10: Finish the feature branch without integrating it automatically**

Run the finishing-development-branch procedure, report the branch and commits, and let the user choose local merge, pull request, or keeping the branch. Do not push or merge without that choice.
