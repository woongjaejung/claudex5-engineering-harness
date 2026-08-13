# Subagent Model Status Line Design

## Goal

Show the configured model and reasoning effort beside each running Claudex5 Claude subagent without renaming agents, converting the harness into a plugin, or changing unrelated Claude Code status-line behavior.

The intended display is:

```text
harness-researcher [Claude Sonnet 5 · high] · Trace authentication flow
harness-implementer [Claude Sonnet 5 · high] · Implement Task 1
harness-architecture-reviewer [Claude Opus 5 · high] · Review module boundaries
harness-judge [Claude Fable 5 · high] · Reconcile review evidence
```

## Decision

Use Claude Code's official `subagentStatusLine` setting and install a repository-owned renderer. Claude Code passes the visible task name and description to the renderer but does not include the resolved model. The renderer will therefore use a fixed, version-controlled mapping from each Claudex5 agent name to the same model and effort declared in its agent frontmatter.

Agent names remain stable. Encoding the model into filenames or agent identifiers was rejected because a future model change would break prompts, documentation, and saved references. Converting Claudex5 into a plugin solely for a scoped name was also rejected because it would add marketplace and plugin-lifecycle complexity without improving model accuracy.

## Renderer behavior

The renderer will read Claude Code's JSON status input from standard input and write one JSON object per Claudex5 row. Each object will preserve the task ID and render:

```text
<agent name> [<friendly model> · <effort>] · <description>
```

The mapping will cover all eight Claude roles, including Opus fallbacks. Unknown agents, including Superpowers and third-party plugin agents, will be omitted from renderer output so Claude Code keeps their default rows. The renderer will not read authentication state, call a model, use the network, or inspect transcripts.

Codex Sol, Luna, and Spark work launched through the official Codex plugin are not Claude custom subagents and therefore are not guaranteed to appear as mapped Claude rows. Global routing instructions will require their visible task descriptions to begin with `[Codex Sol · high]`, `[Codex Luna · max]`, or `[Codex-Spark]` when the invoking interface accepts a task description.

## Installation and conflicts

The repository renderer will be linked at:

```text
~/.claude/statuslines/claudex5-subagent-models.py
```

The installer will set `subagentStatusLine` only when it is absent or already points to the Claudex5 renderer. An existing foreign `subagentStatusLine` is user-owned: installation will preserve it, print a warning, and verification will explain that model labels are not active. The existing top-level `statusLine` setting is independent and will remain unchanged.

Uninstallation will remove the renderer link and settings entry only when they are still Claudex5-owned. A foreign replacement is preserved. Existing configuration backups and rollback protections apply to the settings change.

## Verification

Automated tests will prove that:

- every Claude agent frontmatter model and effort has the expected friendly label;
- mapped rows include the role, model, effort, and task description;
- unknown rows produce no override;
- malformed input fails safely without exposing data;
- installation, repeat installation, rollback, collision handling, and uninstall preserve ownership boundaries;
- a foreign `subagentStatusLine` is never overwritten or removed;
- structural and strict verification distinguish active, conflicting, and missing model-label states.

The English README will remain English-only and document the visible format and conflict behavior. The Korean guide will explain local and server updates and how to inspect the result with Claude Code's agent panel.
