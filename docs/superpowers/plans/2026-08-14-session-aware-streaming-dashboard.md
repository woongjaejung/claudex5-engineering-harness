# Session-Aware Streaming Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add stable path-aware session selection, human-readable task metadata and elapsed time, an all-sessions terminal/web view, and one secure SSE-backed web stream with polling fallback.

**Architecture:** Extend the append-only lifecycle model with optional safe metadata and idempotent timestamps, then add a pure session-query module shared by the CLI and web server. Keep HTTP/SSE transport in `web.py`, move the existing embedded page assets into fixed local files, and let the browser render either one pinned session or a project-grouped bundle without reading any unrestricted Claude data.

**Tech Stack:** Python 3.11 standard library, POSIX shell, local HTML/CSS/vanilla JavaScript, `unittest`, Node.js syntax checks, and loopback-only `ThreadingHTTPServer`.

## Global Constraints

- Work only on `agent/session-aware-streaming-dashboard`; keep `main` unchanged until the user explicitly requests integration.
- Preserve existing configuration, foreign hooks, user changes, private runtime history, credentials, and installer backups.
- Store only sanitized session titles (120 characters), task subjects (120 characters), and task/agent descriptions (160 characters); never store prompts, code, commands, tool output, responses, transcript paths, output-file paths, environment variables, or arbitrary nested hook data.
- Retain directory mode `0700`, file mode `0600`, component-level symlink rejection, bounded locking, atomic snapshots, append-only recovery, loopback-only HTTP binding, trusted `Host` validation, no CORS, no-store caching, and the current restrictive Content Security Policy.
- Keep schema-version-1 snapshots readable. Add optional fields without rewriting retained state or event history.
- Use official `TaskCompleted` hooks only with Claude Code 2.1.33 or newer and `TaskCreated` hooks only with Claude Code 2.1.84 or newer; retain legacy Task tool hooks on every supported version.
- Resolve a dashboard selection once at startup. Do not switch a terminal dashboard because another session receives an event.
- In all-session views, show every running session. Terminal output includes only the latest completed session per project; web output can expand every retained completed session.
- Send browser snapshot data only when the bundle revision changes. Use SSE first, five-second polling only as fallback, and never let a late polling response overwrite newer SSE state.
- Use test-driven development: add a focused failing test, run it and confirm the expected failure, write the minimum production change, and rerun the focused test before broader tests.
- Do not use `harness_spark_ui_iteration`: the web task changes transport, state, and multiple components, so it is outside Spark's single-detail UI scope.

---

## File Structure

### New files

- `scripts/live_graph/sessions.py`: pure selection, catalog, grouping, bundle, and revision contracts shared by terminal and web paths.
- `scripts/live_graph/assets/index.html`: fixed local dashboard document.
- `scripts/live_graph/assets/style.css`: compact single-session and project-grid presentation.
- `scripts/live_graph/assets/app.mjs`: selection, rendering, elapsed-time updates, SSE lifecycle, and polling fallback.
- `tests/test_live_graph_sessions.py`: pure selection and bundle tests.
- `tests/test_live_graph_web_assets.py`: fixed-asset and JavaScript contract tests.

### Modified files

- `scripts/live_graph/model.py`: optional metadata, lifecycle timestamps, metadata-only updates, and conservative compatibility-node reconciliation.
- `scripts/live_graph/store.py`: safe text handling and deterministic snapshot enumeration.
- `scripts/live_graph/record.py`: official task hooks, session title, stable task IDs, and explicit Agent-tool description correlation.
- `scripts/live_graph/terminal.py`: elapsed-time formatting, descriptive nodes, catalog, and all-session rendering.
- `scripts/live_graph/web.py`: fixed assets, validated logical selection, snapshot bundles, and SSE transport.
- `scripts/live_graph_cli.py`: `sessions`, `--select`, `--all`, non-interactive rules, and startup pinning.
- `scripts/common.sh`, `install.sh`, `uninstall.sh`, `scripts/merge_config.py`, `verify.sh`: version-aware, exact-once hook installation and failure-atomic removal.
- `tests/test_live_graph_model.py`, `tests/test_live_graph_store.py`, `tests/test_live_graph_record.py`, `tests/test_live_graph_terminal.py`, `tests/test_live_graph_cli.py`, `tests/test_live_graph_web.py`: focused behavior and security regression coverage.
- `tests/test_common.sh`, `tests/test_merge_config.py`, `tests/test_install.sh`, `tests/test_verify.sh`: version gating, merge ownership, failure-atomic uninstall, and structural verification.
- `README.md`, `docs/usage-ko.md`: English and Korean usage, selection behavior, all mode, SSE/fallback, privacy, update, and troubleshooting.
- `.github/workflows/verify.yml`, `CONTRIBUTING.md`: check the extracted JavaScript asset rather than extracting an embedded Python string.

---

### Task 1: Extend the lifecycle model with safe metadata and honest timestamps

**Files:**
- Modify: `scripts/live_graph/model.py`
- Modify: `scripts/live_graph/store.py`
- Test: `tests/test_live_graph_model.py`
- Test: `tests/test_live_graph_store.py`

**Interfaces:**
- Consumes: existing `sanitize_label(value, limit=120)`, `new_snapshot`, `reduce_event`, and `StateStore.append` contracts.
- Produces: optional run `title`; optional node `description`, `created_at`, `started_at`, `finished_at`, and `superseded_by`; metadata-only `node.updated` events.
- Produces: conservative compatibility reconciliation invoked by both stable `task.created` and stable `task.updated` events, with an optional explicit `supersedes` compatibility identifier.
- Produces: `StateStore.append` string-only validation plus sanitization of `description` at 160 characters and `session_title` at 120 characters.

- [ ] **Step 1: Write failing reducer tests for safe metadata and timestamps**

Add focused tests that create a waiting task, start it, update its description, and finish it:

```python
def test_node_metadata_and_lifecycle_timestamps_are_idempotent(self) -> None:
    reduce_event(self.snapshot, self.event(
        "created", 1, "task.created", "task:5",
        label="Docker smoke test", description="Verify startup and rollback",
    ))
    reduce_event(self.snapshot, self.event(
        "started", 2, "task.updated", "task:5", state="running",
    ))
    reduce_event(self.snapshot, self.event(
        "metadata", 3, "node.updated", "task:5",
        description="Verify image startup, health check, and rollback",
    ))
    reduce_event(self.snapshot, self.event(
        "finished", 4, "task.updated", "task:5", state="passed",
    ))
    reduce_event(self.snapshot, self.event(
        "duplicate", 5, "task.updated", "task:5", state="passed",
    ))

    node = self.snapshot["nodes"]["task:5"]
    self.assertEqual(node["created_at"], "2026-08-13T00:00:01Z")
    self.assertEqual(node["started_at"], "2026-08-13T00:00:02Z")
    self.assertEqual(node["finished_at"], "2026-08-13T00:00:04Z")
    self.assertEqual(node["description"], "Verify image startup, health check, and rollback")
```

Also assert that `session.started` stores a sanitized title, running `task.updated` assigns `started_at`, a terminal update never changes the first `finished_at`, and invalid `superseded_by` or transient `supersedes` identifiers fail validation.

- [ ] **Step 2: Run the model tests and confirm RED**

Run:

```bash
python3 -m unittest tests.test_live_graph_model -v
```

Expected: failures because `created_at`, `description`, `node.updated`, title propagation, and stable finish timestamps do not exist.

- [ ] **Step 3: Implement minimal metadata merging and timestamp transitions**

Add one bounded metadata helper and call it from create/start/update/finish paths:

```python
def _merge_metadata(node: dict[str, Any], payload: dict[str, Any]) -> None:
    label = payload.get("label", payload.get("title"))
    if isinstance(label, str) and label:
        node["label"] = sanitize_label(label)
    description = payload.get("description")
    if isinstance(description, str) and description:
        node["description"] = sanitize_label(description, limit=160)
    superseded_by = payload.get("superseded_by")
    if superseded_by is not None:
        node["superseded_by"] = validate_identifier(
            superseded_by, name="superseding node identifier"
        )
    for key in ("role", "model", "effort"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            node[key] = sanitize_label(value)
```

Set `created_at` on first observation. Set `started_at` only on the first running transition and `finished_at` only on the first terminal transition. Let `node.updated` merge allowlisted metadata without changing state. Let `session.started` set `snapshot["title"]` only from a non-empty string.

- [ ] **Step 4: Add conservative compatibility-node reconciliation tests**

Create two `task:compat-*` nodes with the same label and prove an official stable task does not merge ambiguously. Create exactly one matching compatibility node and prove both a stable `task.created` event and a stable-first `task.updated` event set its `superseded_by`, copy its `depends_on` edges to the stable node, and leave the original append-only evidence in `nodes`. Add an explicit `supersedes: task:compat-<tool-use-id>` case and prove it reconciles that exact compatibility node without label inference.

- [ ] **Step 5: Run the reconciliation test and confirm RED**

Run:

```bash
python3 -m unittest tests.test_live_graph_model.SnapshotReductionTests.test_unique_compatibility_task_is_superseded_by_stable_task -v
```

Expected: failure because reconciliation and dependency copying are absent.

- [ ] **Step 6: Implement stable-ID reconciliation without transcript inference**

Add `_reconcile_compatibility_task(snapshot, stable_id, payload)`. Call it before reducing every non-compatibility stable `task.created` and `task.updated` event, so a stable TaskUpdate observed before an official TaskCreated event cannot leave a duplicate node. If `payload["supersedes"]` is an exact validated `task:compat-*` identifier, reconcile only that node. Otherwise find unsuperseded compatibility tasks whose non-empty sanitized label exactly matches the stable event. Reconcile only when exactly one candidate exists: set `candidate["superseded_by"] = stable_id` and recreate each candidate `depends_on` edge with the stable ID as source. Never merge on an empty or ambiguous label.

- [ ] **Step 7: Add store tests for description limits and secret redaction**

Append a 200-character description and a synthetic bearer-shaped description. Assert the first persists as exactly 160 characters and the second persists only as `[REDACTED]`. Call `StateStore.append` directly with mappings and lists in `label`, `title`, `session_title`, and `description`; assert each is rejected before the event-log write and no stringified nested object appears in any private state file. Task 2 adds the equivalent recorder-boundary checks.

- [ ] **Step 8: Run the direct persistence-boundary test and confirm RED**

Run:

```bash
python3 -m unittest tests.test_live_graph_store.StateStoreTests.test_non_string_text_fields_are_rejected_before_persistence -v
```

Expected: failure because the current store passes arbitrary objects to `sanitize_label`, which stringifies them.

- [ ] **Step 9: Enforce string-only text fields before persistence**

At the start of `StateStore.append`, before opening the run lock, event log, or snapshot, validate the allowlisted payload keys `label`, `title`, `session_title`, and `description`. If a present value is not a string, raise `ValueError("invalid event text field")`; do not coerce it. Only after that check may the existing event construction sanitize `label`/`title`/`session_title` at 120 characters and `description` at 160 characters. Preserve the current fixed secret-redaction marker and reject-before-write guarantee.

- [ ] **Step 10: Run focused and regression tests**

Run:

```bash
python3 -m unittest tests.test_live_graph_model tests.test_live_graph_store -v
```

Expected: all focused tests pass, including existing recovery, lock, symlink, permission, and transition tests.

- [ ] **Step 11: Commit Task 1**

```bash
git add scripts/live_graph/model.py scripts/live_graph/store.py tests/test_live_graph_model.py tests/test_live_graph_store.py
git commit -m "feat: enrich live graph lifecycle metadata"
```

---

### Task 2: Collect stable task events and explicitly correlated agent descriptions

**Files:**
- Modify: `scripts/live_graph/record.py`
- Test: `tests/test_live_graph_record.py`

**Interfaces:**
- Consumes: Task 1 `node.updated`, descriptions, session title, and `task:compat-*` reconciliation.
- Produces: `TaskCreated -> task.created`, `TaskCompleted -> idempotent task.created metadata enrichment`, legacy provisional task IDs, explicit `PostToolUse:TaskCreate` compatibility-to-stable mapping, and `PostToolUse:Agent -> node.updated` only with an explicit structured agent ID. Only successful `PostToolUse:TaskUpdate` changes task state.

- [ ] **Step 1: Add official hook normalization tests**

Add fixtures shaped like current Claude Code hook input:

```python
created = normalize_hook({
    "hook_event_name": "TaskCreated",
    "session_id": "session-1",
    "task_id": "task-001",
    "task_subject": "Implement user authentication",
    "task_description": "Add login and signup endpoints",
    "teammate_name": "implementer",
    "transcript_path": "/private/transcript.jsonl",
})[0]
self.assertEqual(created["event_type"], "task.created")
self.assertEqual(created["node_id"], "task:task-001")
self.assertEqual(created["payload"]["label"], "Implement user authentication")
self.assertEqual(created["payload"]["description"], "Add login and signup endpoints")
self.assertNotIn("teammate_name", json.dumps(created))
self.assertNotIn("transcript", json.dumps(created))
```

Add the matching `TaskCompleted` fixture and assert it idempotently targets the same stable ID and preserves safe subject and description without claiming `passed`. `TaskCompleted` fires before all blocking hooks have accepted completion, so the later successful `PostToolUse:TaskUpdate` remains the authoritative terminal-state event.

- [ ] **Step 2: Run official-hook tests and confirm RED**

Run:

```bash
python3 -m unittest tests.test_live_graph_record.HookNormalizationTests -v
```

Expected: official task events currently normalize to no events.

- [ ] **Step 3: Implement official task and session-title allowlists**

Use `_safe_identifier(payload.get("task_id"), "task:")`, `task_subject`, and string-only `task_description`. Pass descriptions through `sanitize_label(..., limit=160)`. Normalize both official hooks to the idempotent `task.created` metadata path; never mark a task passed from the pre-completion `TaskCompleted` hook. Add `session_title` to `SessionStart` only when it is a non-empty string. Ignore `teammate_name`, deprecated `team_name`, and all common private fields. Stable explicit task identifiers always take precedence over compatibility identifiers.

- [ ] **Step 4: Add legacy namespace and Agent correlation tests**

Assert `PreToolUse:TaskCreate` prefers a valid explicit `tool_input.taskId` or `tool_input.id`; only when neither exists may it create `task:compat-<tool_use_id>`. Add a successful `PostToolUse:TaskCreate` fixture whose structured response contains a stable task ID and whose top-level `tool_use_id` identifies the compatibility node. Assert it emits a stable `task.created` event with `payload.supersedes` set to that exact compatibility ID, plus only safe label and description fields. Add a separate `PostToolUse` fixture with `tool_name: "Agent"`, safe `tool_input.description`, secret-bearing `tool_input.prompt`, and `tool_response.agentId`. Assert exactly one `node.updated` event targets `agent:<agentId>`, contains only the 160-character description, and excludes prompt, response, output file, and nested telemetry.

Also assert Agent tool output without an explicit valid `agentId` is ignored rather than title-matched to a subagent.

- [ ] **Step 5: Run legacy/stable TaskCreate correlation tests and confirm RED**

Run:

```bash
python3 -m unittest tests.test_live_graph_record.HookNormalizationTests.test_post_task_create_explicitly_supersedes_compatibility_node -v
```

Expected: failure because current legacy normalization prefers `tool_use_id` and has no successful `PostToolUse:TaskCreate` path.

- [ ] **Step 6: Implement explicit TaskCreate compatibility mapping**

For `PreToolUse:TaskCreate`, inspect only the structured `tool_input`: prefer a valid `taskId`, then `id`; otherwise validate the top-level `tool_use_id` and namespace it as `task:compat-<tool-use-id>`. For successful `PostToolUse:TaskCreate`, read the stable task ID only from the structured response's `taskId`/`id`, read safe subject/description from the allowlisted input/response strings, and emit a stable `task.created`. When a valid top-level `tool_use_id` exists, include `supersedes: task:compat-<tool-use-id>` so Task 1 performs exact reconciliation. Do not copy the response object, prompt, output, transcript, or error text.

- [ ] **Step 7: Run Agent correlation tests and confirm RED**

Run:

```bash
python3 -m unittest tests.test_live_graph_record.HookNormalizationTests.test_agent_description_requires_explicit_structured_agent_id -v
```

Expected: failure because Agent-tool correlation is not implemented.

- [ ] **Step 8: Implement explicit Agent metadata updates**

Read only `tool_input.description` and `tool_response.agentId`/`agent_id`. Emit:

```python
_event(
    "node.updated",
    f"agent:{safe_agent_id}",
    {"description": sanitize_label(description, limit=160)},
)
```

Do not emit an event without both safe strings. Do not read `prompt`, final text, `outputFile`, `resolvedModel`, usage, or transcript fields.

- [ ] **Step 9: Extend end-to-end persistence privacy tests**

Record SessionStart, legacy PreToolUse:TaskCreate, successful PostToolUse:TaskCreate with explicit stable ID mapping, TaskCreated, SubagentStart, Agent PostToolUse, TaskCompleted, successful PostToolUse:TaskUpdate, SubagentStop, and SessionEnd. Assert the legacy-only path projects one visible stable node rather than a provisional/stable duplicate; stable nodes carry safe descriptions, remain non-terminal until the successful TaskUpdate observation, and then carry honest terminal timestamps. Concatenate every private state file and prove synthetic prompt, command, tool-output, assistant-message, output-file, and transcript values are absent.

- [ ] **Step 10: Run recorder regression tests**

Run:

```bash
python3 -m unittest tests.test_live_graph_record -v
```

Expected: all recorder and non-blocking entry-point tests pass.

- [ ] **Step 11: Commit Task 2**

```bash
git add scripts/live_graph/record.py tests/test_live_graph_record.py
git commit -m "feat: collect stable Claude task metadata"
```

---

### Task 3: Install modern hooks only on compatible Claude Code versions

**Files:**
- Modify: `scripts/common.sh`
- Modify: `install.sh`
- Modify: `uninstall.sh`
- Modify: `scripts/merge_config.py`
- Modify: `verify.sh`
- Test: `tests/test_common.sh`
- Test: `tests/test_merge_config.py`
- Test: `tests/test_install.sh`
- Test: `tests/test_verify.sh`

**Interfaces:**
- Consumes: Claude Code semantic version text from `claude --version`.
- Produces: `claudex5_version_at_least ACTUAL REQUIRED`; `claudex5_hook_groups(enable_task_created, enable_task_completed)`; exact owned group enumeration for merge, verify, downgrade cleanup, and uninstall.

- [ ] **Step 1: Add shell version-gate tests**

Test exact boundaries `2.1.32 < 2.1.33`, `2.1.33 >= 2.1.33`, `2.1.83 < 2.1.84`, `2.1.84 >= 2.1.84`, and `2.2.0 >= 2.1.84`. At the command-output boundary, accept exactly `2.1.226` and `2.1.226 (Claude Code)`. Reject `2.1.84-beta.1`, output containing multiple version tokens, malformed output, and command failure instead of guessing. Assert fallback installs only base hooks and emits exactly one warning.

- [ ] **Step 2: Run the common-shell tests and confirm RED**

Run:

```bash
bash tests/test_common.sh
```

Expected: failure because `claudex5_version_at_least` is undefined.

- [ ] **Step 3: Implement numeric three-component comparison**

Parse exactly three dot-separated non-negative integers in shell and compare major, minor, then patch numerically. Treat the full trimmed `claude --version` output as valid only when it is exactly `N.N.N` or `N.N.N (Claude Code)`; do not extract a matching substring from arbitrary or prerelease output. If the command fails or the full output is invalid, install only the legacy/base hook set and print one stable warning.

- [ ] **Step 4: Reshape owned hook groups and write merge tests first**

Replace the one-group-per-event dictionary with tuples so `PostToolUse` can own both `TaskUpdate` and `Agent` groups:

```python
BASE_CLAUDEX5_HOOK_GROUPS = {
    "SessionStart": (owned_group(),),
    "PreToolUse": (owned_group(matcher="TaskCreate"),),
    "PostToolUse": (
        owned_group(matcher="TaskCreate"),
        owned_group(matcher="TaskUpdate"),
        owned_group(matcher="Agent"),
    ),
    "SubagentStart": (owned_group(),),
    "SubagentStop": (owned_group(),),
    "Stop": (owned_group(),),
    "SessionEnd": (owned_group(),),
}
TASK_COMPLETED_HOOK_GROUPS = {"TaskCompleted": (owned_group(),)}
TASK_CREATED_HOOK_GROUPS = {"TaskCreated": (owned_group(),)}
```

Add tests proving foreign groups stay structurally equivalent after JSON parsing/rendering, every selected owned group appears exactly once after two installs, pre-existing duplicate owned groups are repaired to one, unsupported modern groups are absent, a latest-to-old-version reinstall removes only unsupported owned groups, and uninstall removes every possible owned group regardless of which version originally installed it. `TaskCreated` and `TaskCompleted` owned objects must not contain a matcher.

- [ ] **Step 5: Run merge tests and confirm RED**

Run:

```bash
python3 -m unittest tests.test_merge_config.ClaudeSettingsTests -v
```

Expected: failure because current loops assume one dictionary group per event and lack capability flags.

- [ ] **Step 6: Implement conditional merge and unconditional owned removal**

Make install first remove exact owned groups that are outside the selected capability set, then normalize every selected owned group to exactly one occurrence without changing foreign group order. Make uninstall iterate the union of all Claudex5 groups so upgrading or downgrading Claude cannot orphan a modern hook. Keep the existing digest-aware configuration transaction and exact-equality removal behavior.

Move verifier capability detection before its structural-only early exit so install and verification compute the same expected group set. On a supported runtime, missing modern hooks fail with a rerun instruction. On an old or unknown runtime, the missing modern capability is a warning rather than an installation failure.

- [ ] **Step 7: Add install and verifier fixtures for old, intermediate, and current Claude**

Use fake `claude --version` outputs:

- `2.1.32`: base hooks only;
- `2.1.33`: base plus `TaskCompleted`;
- `2.1.84`: base plus `TaskCompleted` and `TaskCreated`;
- `2.1.226`: both official task hooks.

For each fixture, run install twice, assert exact-once selected hooks, preserve a foreign `PostToolUse` group, run structural verification, uninstall, and assert all owned groups are gone while the foreign group remains.

- [ ] **Step 8: Add a failing whole-uninstall rollback test**

Inject a failure after one owned link has been removed. Assert configuration files and every previously removed exact managed link return to their pre-uninstall state, while a concurrent user-modified target is not overwritten. Confirm private run history is never part of the removal journal.

- [ ] **Step 9: Run the rollback test and confirm RED**

Run:

```bash
bash tests/test_install.sh
```

Expected: the injected link-removal failure leaves a partial uninstall with the current script.

- [ ] **Step 10: Make the full uninstall failure-atomic**

Before configuration removal, take the existing private backup and capture expected file state. Journal each exact managed link target before removing it. If a later link removal or verification step fails, restore only configuration files whose digest still matches the transaction's expected state and recreate only links that the transaction removed and whose paths remain absent. Never overwrite a concurrent user change or a foreign file. Preserve the current behavior of leaving runtime history untouched.

- [ ] **Step 11: Run configuration and installation regression tests**

Run:

```bash
bash tests/test_common.sh
python3 -m unittest tests.test_merge_config -v
bash tests/test_install.sh
bash tests/test_verify.sh
```

Expected: all version, merge, rollback, exact ownership, and credential-safety fixtures pass.

- [ ] **Step 12: Commit Task 3**

```bash
git add scripts/common.sh install.sh uninstall.sh scripts/merge_config.py verify.sh tests/test_common.sh tests/test_merge_config.py tests/test_install.sh tests/test_verify.sh
git commit -m "feat: gate Claude lifecycle hooks by version"
```

---

### Task 4: Add deterministic session enumeration, grouping, and bundles

**Files:**
- Create: `scripts/live_graph/sessions.py`
- Modify: `scripts/live_graph/store.py`
- Create: `tests/test_live_graph_sessions.py`
- Modify: `tests/test_live_graph_store.py`

**Interfaces:**
- Produces: `StateStore.snapshots(cwd: Path | str | None = None) -> list[dict[str, object]]`.
- Produces: immutable `SessionSelection(mode: str, session_id: str | None)` with `one(session_id)` and `all()` constructors.
- Produces: `catalog(snapshots) -> list[dict]`, `group_snapshots(snapshots, completed_limit) -> list[dict]`, `build_bundle(store, selection, completed_limit=None) -> dict`, and `bundle_revision(snapshots) -> str`.
- Consumes: only validated logical IDs and canonical `cwd` values from `StateStore`.

- [ ] **Step 1: Write store enumeration tests**

Create running and terminal sessions in two paths. Assert `snapshots()` sorts running first, then `updated_at` descending, then ID; `snapshots(project)` uses canonical path equality; malformed directories are ignored; and `latest()` delegates to the same ordering without changing existing behavior.

- [ ] **Step 2: Run enumeration tests and confirm RED**

Run:

```bash
python3 -m unittest tests.test_live_graph_store.StateStoreTests.test_snapshots_are_deterministic_and_path_filtered -v
```

Expected: failure because `snapshots` does not exist.

- [ ] **Step 3: Implement one private iterator and public snapshot enumeration**

Refactor duplicated directory walking into `_snapshots_unordered()` while preserving symlink checks and lock-aware `load`. `snapshots(cwd)` returns a new list and never returns paths.

- [ ] **Step 4: Write pure selection and grouping tests**

Cover:

```python
self.assertEqual(SessionSelection.one("session-1").session_id, "session-1")
with self.assertRaises(ValueError):
    SessionSelection.one("../escape")
```

Assert project grouping uses full canonical paths, all running sessions are included, `completed_limit=1` retains only the newest completed session per project, `completed_limit=None` retains all completed sessions, superseded nodes and edges touching them are omitted from bundle snapshots, and the catalog retains complete IDs plus raw timestamps while exposing safe display fields. Every bundle, including `SessionSelection.one(...)`, must catalog all retained sessions machine-wide so the persistent selector can switch without restarting the server; only the `projects` graph projection is selection-scoped. Add a focused-bundle fixture selecting session A while proving session B appears in `catalog` but not in the focused graph. Catalogs and bundles must not contain preformatted relative ages, because wall-clock-only changes must not change the SSE revision.

- [ ] **Step 5: Run query tests and confirm RED**

Run:

```bash
python3 -m unittest tests.test_live_graph_sessions -v
```

Expected: import failure because `sessions.py` is not present.

- [ ] **Step 6: Implement immutable logical selections and bundle projection**

Use a frozen dataclass:

```python
@dataclass(frozen=True)
class SessionSelection:
    mode: str
    session_id: str | None = None

    @classmethod
    def one(cls, session_id: str) -> "SessionSelection":
        return cls("session", validate_identifier(session_id, name="session identifier"))

    @classmethod
    def all(cls) -> "SessionSelection":
        return cls("all", None)
```

`build_bundle` returns `schema_version`, `revision`, `selection`, `catalog`, and `projects`. Enumerate all retained snapshots once for every mode and always build `catalog` from that complete list. For a single selection, locate exactly that validated session in the enumerated set, project only that snapshot into `projects`, and raise `LookupError("selected session is unavailable")` if missing. For all, group the same enumerated set. Deep-copy projected snapshots before removing superseded nodes and their edges.

Compute the revision with SHA-256 over `session_id`, `schema_version`, `sequence`, and `updated_at` for every catalog session, sorted by session ID, plus the logical selection. This makes session creation, deletion, and updates refresh the selector even in focused mode without letting one-second wall-clock repainting change the revision. Do not hash labels, descriptions, paths, or other user text.

- [ ] **Step 7: Run focused query/store tests**

Run:

```bash
python3 -m unittest tests.test_live_graph_store tests.test_live_graph_sessions -v
```

Expected: all enumeration, grouping, projection, and security tests pass.

- [ ] **Step 8: Commit Task 4**

```bash
git add scripts/live_graph/store.py scripts/live_graph/sessions.py tests/test_live_graph_store.py tests/test_live_graph_sessions.py
git commit -m "feat: query and group Claudex5 sessions"
```

---

### Task 5: Add the session selector, sessions command, pinned terminal view, and elapsed time

**Files:**
- Modify: `scripts/live_graph_cli.py`
- Modify: `scripts/live_graph/terminal.py`
- Modify: `tests/test_live_graph_cli.py`
- Modify: `tests/test_live_graph_terminal.py`

**Interfaces:**
- Consumes: Task 4 `SessionSelection`, `catalog`, `group_snapshots`, and `build_bundle`.
- Produces: `format_duration(node, now) -> str`, `render_session_catalog(rows, now, unicode=True) -> str`, and `render_all_sessions(bundle, columns, now, unicode=True) -> str`.
- Produces: CLI `sessions [--all]`, mutually exclusive dashboard `--session-id|--all|--select`, and `_resolve_dashboard_selection(...) -> SessionSelection | None`.

- [ ] **Step 1: Write deterministic elapsed-time tests with an injected clock**

Use an aware UTC `datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)` and assert:

- running from `11:56:42Z` -> `running 3m 18s`;
- waiting from `11:48:00Z` -> `waiting 12m`;
- passed from `11:50:00Z` to `11:57:42Z` -> `passed in 7m 42s`;
- a non-degraded task observed waiting at `11:50:00Z` and terminal at `11:57:42Z`, without `started_at`, -> `passed in 7m 42s` using `created_at` as the honest fallback;
- a late-observed/degraded agent, review, gate, or session without `started_at` -> `duration unknown` even if it has creation and finish timestamps;
- malformed or missing time -> `duration unknown`.

Assert wide output puts the subject on the first line and a 160-character description plus duration on the second. Assert narrow output clips the description before the subject/state/duration.

- [ ] **Step 2: Run terminal tests and confirm RED**

Run:

```bash
python3 -m unittest tests.test_live_graph_terminal -v
```

Expected: failures because current rendering has no clock, descriptions, or durations.

- [ ] **Step 3: Implement pure timestamp parsing and rendering**

Accept RFC 3339 `Z` and offset timestamps with `datetime.fromisoformat`. Clamp negative durations to unknown. For terminal tasks only, use `created_at` as the fallback start when `started_at` is absent and the task is not marked degraded/late-observed. Do not invent this fallback for agents, reviews, gates, or sessions. Format exact boundaries as seconds below 60, minutes/seconds below one hour, hours/minutes below one day, and days/hours thereafter. Filter `superseded_by` nodes defensively even though bundles already project them out.

- [ ] **Step 4: Write CLI parser, selector, and pinning tests**

Test parser rejection for combined `--session-id`, `--all`, and `--select`. Unit-test an interactive selector with injected input/output for numeric choice, default Enter, `A`, invalid retry, EOF, and `Q`. Test these automatic cases:

- one running session in current path -> select it;
- multiple current-path running sessions in a TTY -> show selector;
- no current-path sessions in a TTY -> show machine-wide selector;
- one retained current-path candidate in non-TTY -> select it;
- ambiguous non-TTY -> exit 2 and mention only `--session-id` and `--all`.

Start follow mode with one selected session, append an event to a different newer session, and assert the resolver is not called again and the original selection stays pinned. After one valid render, make the selected store read raise `TimeoutError`, then recover on the following read. Assert the terminal retains the last graph with a view-only `STATE READ DEGRADED` marker, does not exit or switch sessions, and clears the marker after recovery.

- [ ] **Step 5: Run CLI tests and confirm RED**

Run:

```bash
python3 -m unittest tests.test_live_graph_cli -v
```

Expected: parser and command failures because the new options and resolver are absent.

- [ ] **Step 6: Implement CLI commands and one-time selection resolution**

Create a mutually exclusive argument group:

```python
target = dashboard.add_mutually_exclusive_group()
target.add_argument("--session-id")
target.add_argument("--all", action="store_true")
target.add_argument("--select", action="store_true")
```

Resolve before entering terminal refresh or starting the web server. Pass the immutable selection into every subsequent snapshot call. Keep `--once` deterministic and non-interactive unless `--select` is explicitly supplied with a TTY.

In terminal follow mode, cache the last valid bundle. Catch transient `OSError`, `TimeoutError`, and recoverable snapshot-corruption errors after an initial successful load; render the cached graph with a fixed view-only `STATE READ DEGRADED` marker and retry the same pinned selection. Never persist the marker. Initial resolution/load failures still return the existing deterministic command error.

Add `sessions --all`. Default `sessions` uses all running plus one completed per project; `--all` uses every retained session. Keep this first version human-readable only rather than adding an unrequested machine-output contract.

- [ ] **Step 7: Implement all-session terminal rendering**

Render a project heading with the full path, then session summaries with title/fallback, status, progress, updated age, and each running node's subject/duration. Do not render every completed node in `--all`. Preserve existing ASCII and narrow-width fallbacks.

- [ ] **Step 8: Run terminal and CLI regression tests**

Run:

```bash
python3 -m unittest tests.test_live_graph_terminal tests.test_live_graph_cli -v
```

Expected: all existing wrapper, signal, exit-code, and new selection tests pass.

- [ ] **Step 9: Commit Task 5**

```bash
git add scripts/live_graph_cli.py scripts/live_graph/terminal.py tests/test_live_graph_cli.py tests/test_live_graph_terminal.py
git commit -m "feat: select and inspect multiple live sessions"
```

---

### Task 6: Replace browser polling with a secure single SSE transport

**Files:**
- Modify: `scripts/live_graph/web.py`
- Create: `scripts/live_graph/assets/index.html`
- Create: `scripts/live_graph/assets/style.css`
- Create: `scripts/live_graph/assets/app.mjs`
- Modify: `tests/test_live_graph_web.py`
- Create: `tests/test_live_graph_web_assets.py`

**Interfaces:**
- Consumes: Task 4 `SessionSelection` and `build_bundle`.
- Produces: `create_server(store, selection, host, port, stream_interval=1.0, keepalive_interval=15.0)` and `serve_dashboard(store, selection, host, port, open_browser)`.
- Produces fixed routes `/`, `/app.mjs`, `/style.css`, `/api/snapshot`, and `/api/events`; API selection query is exactly `selection=all` or `session=<validated-id>`.

- [ ] **Step 1: Add fixed-asset extraction and security tests**

Assert the three asset files exist, the HTML loads only `/style.css` and `/app.mjs`, no asset contains external asset references, analytics code, or inline script, and `node --check scripts/live_graph/assets/app.mjs` succeeds. Exercise the HTTP server and assert every referenced asset resolves locally. Update existing tests to import no large embedded string from `web.py`.

- [ ] **Step 2: Run asset tests and confirm RED**

Run:

```bash
python3 -m unittest tests.test_live_graph_web_assets -v
```

Expected: failure because fixed assets do not exist.

- [ ] **Step 3: Move current assets without changing behavior**

Move `INDEX_HTML`, `STYLE_CSS`, and `APP_JS` byte-for-byte into the fixed files first. Load them from a constant directory derived from `Path(__file__).parent`. Run the current web tests and Node syntax check before adding SSE behavior.

- [ ] **Step 4: Write bundle snapshot and query-validation tests**

Update the memory store to implement `snapshots()` and `load()`. Assert `/api/snapshot?session=selected-session` returns a bundle for only that session, `/api/snapshot?selection=all` returns project groups, an unknown valid session returns fixed 404, and invalid/multiple selection parameters return fixed 400 before any store call.

Retain and extend the foreign-`Host` test to cover both `/api/snapshot` and `/api/events` before storage access.

- [ ] **Step 5: Run HTTP bundle tests and confirm RED**

Run:

```bash
python3 -m unittest tests.test_live_graph_web.WebDashboardTests.test_snapshot_routes_accept_only_valid_logical_selections -v
```

Expected: failure because current server accepts one constructor session and returns raw snapshots.

- [ ] **Step 6: Implement fixed logical selection parsing**

Use `urllib.parse.urlsplit` and `parse_qs(..., strict_parsing=True)`. Accept one of:

```text
selection=all
session=<validated identifier>
```

No query uses a filesystem path. Build the initial root URL with `urllib.parse.urlencode` from the CLI's pinned logical choice; the static page reads it without server-side string interpolation.

- [ ] **Step 7: Write SSE stream tests**

Open `/api/events?session=selected-session` with a short injected interval. Assert response headers include `text/event-stream`, no-store, CSP, no CORS, and no `Content-Length`. Read and decode the initial event:

```text
event: snapshot
data: {"revision":"...",...}

```

Keep state unchanged and assert the next emitted item is a comment keepalive, not a duplicate snapshot. Change the memory-store sequence and assert exactly one new snapshot event. Close the client and prove a second client and normal snapshot requests remain healthy.

After one valid snapshot frame, inject a transient `TimeoutError`. Assert the stream emits one fixed `event: degraded` frame without user or exception text, retains the last revision, and continues retrying. Restore the store with a changed bundle and assert the next snapshot frame recovers normally. Also inject an initial store failure before headers and assert the request returns a fixed 503 response instead of opening an unusable event stream.

- [ ] **Step 8: Run SSE tests and confirm RED**

Run:

```bash
python3 -m unittest tests.test_live_graph_web.WebDashboardTests.test_sse_sends_initial_changed_only_and_keepalive_frames -v
```

Expected: 404 because `/api/events` is absent.

- [ ] **Step 9: Implement bounded SSE streaming**

Set the handler protocol to HTTP/1.1. After `Host` and selection validation, build and validate the initial bundle before sending event-stream headers; return a fixed 503 if this initial read fails. Retain the first valid revision, check at `stream_interval`, send only changed revisions, and send `: keepalive\n\n` at the keepalive deadline. After a valid frame, catch transient store `OSError`, `TimeoutError`, and recoverable corruption separately from client disconnects; emit at most one fixed `event: degraded` notification for a contiguous failure period, preserve the last revision, and keep retrying until a changed valid bundle is available. Flush after frames. Catch `BrokenPipeError` and `ConnectionResetError` as client disconnects without logging user content. Let daemon request threads end when clients disconnect or the server closes.

- [ ] **Step 10: Run web transport regression tests**

Run:

```bash
python3 -m unittest tests.test_live_graph_web tests.test_live_graph_web_assets -v
node --check scripts/live_graph/assets/app.mjs
```

Expected: all fixed-route, Host, selection, SSE, disconnect, and syntax tests pass.

- [ ] **Step 11: Commit Task 6**

```bash
git add scripts/live_graph/web.py scripts/live_graph/assets tests/test_live_graph_web.py tests/test_live_graph_web_assets.py
git commit -m "feat: stream live graph bundles over SSE"
```

---

### Task 7: Build the compact project-grid web experience and resilient fallback

**Files:**
- Modify: `scripts/live_graph/assets/index.html`
- Modify: `scripts/live_graph/assets/style.css`
- Modify: `scripts/live_graph/assets/app.mjs`
- Modify: `tests/test_live_graph_web_assets.py`
- Modify: `tests/test_live_graph_web.py`

**Interfaces:**
- Consumes: Task 6 bundle and SSE contracts.
- Produces: browser `applyBundle`, `renderAll`, `renderFocused`, `formatDuration`, `openStream`, `startFallbackPolling`, and `selectTarget` behavior.

- [ ] **Step 1: Add pure JavaScript behavior checks before UI changes**

Export production-pure helpers `formatDuration`, `buildAllViewModel`, and `canApplyPollResult` from `app.mjs`. Import the real module from Node using a `data:` module URL and assert fixed-clock duration formatting, project grouping order, completed collapse defaults, and rejection of a polling result from an older selection generation.

Create the real transport through `createTransport({EventSourceImpl, fetchImpl, timers})`. Test it with contract-complete fakes that record opened URLs and invoke real callbacks: one active EventSource per selection, fallback beginning at 5000 ms after stream failure, local elapsed repaint at 1000 ms, and polling cancellation after a healthy SSE event. Cover both `EventSourceImpl` being absent and its constructor throwing: polling starts immediately, continues every 5000 ms, SSE construction is retried periodically, eventual SSE recovery cancels polling, and a stale in-flight poll result from the old generation is rejected. Assertions target transport state and applied revisions, not source text or mock existence.

Add staged-selection tests. Keep selection A active while preflighting B through `/api/snapshot`; if B is unknown or has disappeared since catalog rendering, preserve A's URL, selector value, bundle, and transport. If B passes preflight but disappears before the first valid SSE snapshot, confirm absence with the snapshot endpoint, roll back atomically to A, and reopen A's transport. Then start B and C preflights in that order but resolve C first and B last; assert only C commits and the late B result cannot change C's URL, selector, bundle, or transport. Assert no stale response from a rolled-back selection can overwrite the restored selection.

- [ ] **Step 2: Run asset behavior tests and confirm RED**

Run:

```bash
python3 -m unittest tests.test_live_graph_web_assets -v
```

Expected: failures because the current app uses one-second polling and only a single SVG graph.

- [ ] **Step 3: Implement the transport state machine**

Maintain:

```javascript
let selectionGeneration = 0;
let selectionAttemptGeneration = 0;
let stream = null;
let streamHealthy = false;
let fallbackTimer = null;
let lastBundle = null;
```

Represent a selection switch as pending state. At preflight start, increment a separate monotonically increasing `selectionAttemptGeneration`, capture it in the request, and abort the previous candidate request when `AbortController` is available. Keep the current URL, selector value, bundle, and transport alive while fetching the candidate's `/api/snapshot`. A preflight response may commit only when its attempt generation still equals the latest attempt; otherwise discard it even if it succeeded. If the current preflight fails, discard the candidate without changing visible or transport state. After a valid current candidate bundle, increment `selectionGeneration`, save the previous committed selection for rollback, close the old stream, clear its timers, commit the candidate URL and selector, render the candidate bundle, and open exactly one candidate `EventSource`. If the candidate stream fails before its first valid SSE snapshot, distinguish transient failure from deletion by confirming the candidate through `/api/snapshot`; only a fixed 404 triggers restoration of the saved selection, URL, bundle, and one reopened transport. Ignore every transport or polling callback whose captured selection generation is stale.

When `EventSource` is unavailable or construction throws, enter polling immediately and retry the same snapshot URL every 5000 ms while periodically retrying SSE construction. After an established stream fails, retain the last graph with `RECONNECTING`, begin polling after the bounded failure window, and continue periodic SSE retry. Apply a polling response only when its captured generation still matches and `streamHealthy` is false. Stop polling on the next healthy SSE snapshot. Treat the server's fixed `degraded` event as connection degradation without clearing the last bundle.

- [ ] **Step 4: Implement the A-layout responsive project grid**

Add:

- a persistent session selector with `All sessions` and every catalog item;
- project sections labeled by full canonical path;
- an expanded running-session grid;
- a native accessible completed-session disclosure per project;
- compact session cards with title, state, progress, updated age, running time, and reduced graph;
- focused full-graph mode after card activation;
- `Back to all sessions` with saved scroll position.

Use buttons for selectable cards, `details/summary` for completed disclosure, visible focus styles, and `aria-live` only for connection status so one-second durations do not create screen-reader chatter.

- [ ] **Step 5: Compact full graph nodes and add task detail access**

Use 180×62 full-graph nodes, 230-pixel horizontal rank spacing, and 94-pixel vertical spacing as the first verified target. Show subject, state/duration, and model/effort within the node. Attach an SVG `<title>` and a keyboard/click detail panel containing the complete sanitized subject and description. Render all user text with `textContent`.

- [ ] **Step 6: Run automated web checks**

Run:

```bash
python3 -m unittest tests.test_live_graph_web tests.test_live_graph_web_assets -v
node --check scripts/live_graph/assets/app.mjs
```

Expected: all transport ordering, safe rendering, layout-contract, and HTTP tests pass.

- [ ] **Step 7: Verify the real browser at desktop and narrow widths**

Create private synthetic snapshots through `claudex5 event` for two projects, at least two running sessions, two completed sessions, safe descriptions, dependencies, a model-bearing agent, and running timestamps. Start:

```bash
claudex5 dashboard --web --all --no-open --port 0
```

Using browser automation, verify at 1440×900 and 390×844:

- project grouping and responsive columns;
- completed sections initially collapsed and expandable;
- card focus and Back restoration;
- selector switching without server restart;
- elapsed labels advance locally;
- cards do not clip subject/state/model;
- keyboard focus is visible;
- disconnect retains the last graph and shows reconnecting;
- SSE recovery stops fallback polling.

Capture screenshots under a temporary ignored directory, inspect them visually, and do not commit them.

- [ ] **Step 8: Commit Task 7**

```bash
git add scripts/live_graph/assets/index.html scripts/live_graph/assets/style.css scripts/live_graph/assets/app.mjs tests/test_live_graph_web.py tests/test_live_graph_web_assets.py
git commit -m "feat: add compact multi-session dashboard UI"
```

---

### Task 8: Document, verify, and independently review the completed feature

**Files:**
- Modify: `README.md`
- Modify: `docs/usage-ko.md`
- Modify: `SECURITY.md`
- Modify: `CONTRIBUTING.md`
- Modify: `.github/workflows/verify.yml`

**Interfaces:**
- Consumes: all user-facing commands and transport behavior from Tasks 1–7.
- Produces: exact English and Korean usage, update/uninstall behavior, compatibility notes, privacy statement, troubleshooting, and CI verification commands.

- [ ] **Step 1: Update English, Korean, and security documentation**

Keep the root README entirely English and put Korean instructions only in `docs/usage-ko.md`. Include examples for ordinary automatic selection, forced selection, all mode, non-interactive ambiguity, server SSH tunnel, SSE fallback, no-prompt-storage privacy, updating with `git pull && ./install.sh && ./verify.sh --strict`, uninstall, and retained-history cleanup.

Update the Mermaid architecture diagram to show hooks -> private snapshots -> shared selector -> terminal and one SSE stream -> project grid. Update `SECURITY.md` with the new bounded subject/description allowlist and explicitly forbidden Agent fields: `prompt`, response content, `outputFile`, usage telemetry, and transcript paths. Review the prose directly against the approved design; do not add brittle tests that grep human documentation for literal wording. Retain the existing English-only README test.

- [ ] **Step 2: Update CI JavaScript checks**

Replace the temporary extraction of `APP_JS` from Python with:

```bash
node --check scripts/live_graph/assets/app.mjs
```

Document the same command in `CONTRIBUTING.md`.

- [ ] **Step 3: Run the complete deterministic verification suite**

Run each command and retain its exit status:

```bash
python3 -m unittest discover -s tests -v
bash tests/test_install.sh
bash tests/test_bootstrap.sh
bash tests/test_verify.sh
bash -n install.sh link.sh verify.sh uninstall.sh bootstrap-system.sh scripts/common.sh project-template/scripts/*.sh tests/*.sh
node --check scripts/live_graph/assets/app.mjs
./verify.sh --secrets-only --repo "$PWD"
git diff --check
git status --short
```

Expected: zero test failures, zero shell syntax errors, valid JavaScript, no candidate secrets, no whitespace errors, and only intentional branch changes.

- [ ] **Step 4: Run isolated installation verification**

Install into a fresh temporary home with fake current Claude/Codex CLIs, run `verify.sh --strict --structural-only`, inspect hook counts, run `claudex5 sessions`, start a synthetic single and all dashboard, then uninstall. Confirm foreign hooks remain, owned links and hooks are removed, and private run history is preserved.

- [ ] **Step 5: Request two fresh read-only reviews**

Dispatch `harness_sol_review` to review correctness, maintainability, backward compatibility, and test coverage. Separately dispatch `harness_sol_adversarial_review` to attack SSE disconnects, selection races, path/Host validation, hook duplication, privacy leakage, corrupted snapshots, and rollback behavior. Reviewers must not edit files.

For every actionable finding, reproduce it or point to exact code evidence, add a failing regression test, implement the smallest fix, and rerun the complete verification suite. If a finding is rejected, record the concrete counter-evidence.

- [ ] **Step 6: Commit documentation and final verification updates**

```bash
git add README.md docs/usage-ko.md SECURITY.md CONTRIBUTING.md .github/workflows/verify.yml
git commit -m "docs: explain session-aware streaming dashboards"
```

- [ ] **Step 7: Prepare integration handoff without pushing or merging**

Report the branch, commit list, files changed, exact verification counts, screenshots inspected, review decisions, remaining limitations, local update commands, server update commands, and rollback commands. Do not push, open a pull request, merge, or reinstall the current laptop until the user explicitly requests that action.

---

## Plan Self-Review Checklist

- Every approved selection rule maps to Tasks 4–5.
- Human-readable subjects, 160-character descriptions, explicit agent correlation, and elapsed-time rules map to Tasks 1–2 and 5.
- Current official hooks, legacy compatibility, version gates, exact ownership, and failure-atomic removal map to Task 3.
- Project-grouped all mode and completed-session policies map to Tasks 4, 5, and 7.
- Single-stream SSE, changed-only events, keepalive, reconnect, five-second fallback, and stale-response rejection map to Tasks 6–7.
- Loopback/Host/path validation and privacy regression coverage map to Tasks 1–3, 6, and 8.
- English-only README, Korean-only Korean usage, update, uninstall, troubleshooting, and architecture documentation map to Task 8.
- No step requires prompts, transcripts, unrestricted tool data, external web assets, a JavaScript package, or a schema migration.
