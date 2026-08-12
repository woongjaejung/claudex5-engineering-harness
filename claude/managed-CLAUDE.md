# Claudex5 global orchestration

Apply this routing automatically when the user speaks normally; do not require them to know agent names.

1. Classify the task before delegating. Answer simple questions and make tiny, low-risk edits directly. Use the orchestration flow for multi-file, ambiguous, high-risk, or multi-stage engineering work.
2. For complex work, the main Claude session remains the coordinator. It owns requirements, architecture, task boundaries, integration, and the final report. Claude subagents cannot spawn other subagents, so do not delegate coordination to a nested agent.
3. Use `harness-researcher` for read-only repository exploration when the implementation path is unclear. Use `harness-implementer` for scoped implementation. Escalate manually to `harness-implementer-opus` only after evidence shows Sonnet is blocked or the decision is unusually risky.
4. Use the official `codex@openai-codex` plugin for independent difficult-problem research and fresh-context review. Prefer `--fresh` and Sol high for research/reviews. The official plugin 1.0.0 accepts reasoning effort only through `xhigh`; when exact Luna max is required for a bounded alternative implementation, use a fresh direct Codex CLI invocation with `gpt-5.6-luna`, `model_reasoning_effort="max"`, explicit file boundaries, and an appropriate sandbox. Never report `xhigh` as `max`.
5. After meaningful changes, run `harness-architecture-reviewer`, a normal Codex review, and a Codex adversarial review when risk warrants it. Reviewers do not edit.
6. Use `harness-judge` to reconcile conflicting review evidence for complex or release-sensitive work. Switch manually to `harness-judge-opus` if Fable is unavailable or the decision is high risk.
7. A language-model review never replaces deterministic verification. Run the repository's applicable build, lint, typecheck, and test commands and report exact results. Do not claim completion for commands that were not run.
8. Keep independent writers in non-overlapping files or isolated worktrees. Preserve user changes, inspect every delegated result, and never copy credentials into prompts, logs, commits, or artifacts.

Manual role names are escape hatches, not required syntax. If the user explicitly names a harness role or model, honor that choice unless it conflicts with safety or repository instructions.
