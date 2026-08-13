---
name: claudex5-subagent-routing
description: Use when Superpowers subagent-driven-development or executing-plans runs an implementation plan and Claudex5 must select the implementation review and judgment roles.
---

# Claudex5 Subagent Routing

## Ownership

Superpowers owns plan reading, worktree choice, task ledger, execution, checkpoints, and review gates. Claudex5 owns model and agent choice. After selecting a Superpowers mode, load this adapter and start without asking again.

The main Claude session retains requirements, architecture, boundaries, integration, verification, and the final report. Inspect every delegated result.

## Review Plans Before Implementation

Fable remains the plan owner. Run fresh, read-only `harness_sol_plan_review` with `gpt-5.6-sol` high when a plan crosses multiple modules or services; covers authentication, authorization, security, data migration, or destructive state; has difficult rollback, material architecture change, or high operational risk; is ambiguous or has multiple viable approaches; or contains five or more executable tasks. Skip simple plans. Use `[Codex Sol · high] Plan review` as the visible title and require `APPROVE` or `NEEDS CHANGES`. On changes, Fable revises and requests one fresh recheck. If it still blocks, stop before implementation and ask the user.

When `claudex5` is available, run automatic Codex roles through `claudex5 codex-run --role ROLE --label LABEL --sandbox MODE --prompt-file FILE`; it records lifecycle metadata but never the prompt. Use `harness_sol_plan_review`, `harness_sol_research`, `harness_luna_implementation`, `harness_sol_review`, `harness_sol_adversarial_review`, or capability-gated `harness_spark_ui_iteration`. Use `read-only` for research and reviews and the narrowest writable sandbox for implementation. Preserve manual `/codex:*` commands as best-effort observability only.

## Route Each Workflow Role

1. Use `harness-researcher` for read-only codebase exploration.
2. Use `harness-implementer` for the primary scoped task implementation. Escalate to `harness-implementer-opus` only after evidence shows Sonnet is insufficient or the task is high risk.
3. For exactly one small existing-UI change, use a fresh official Codex-plugin pass with `gpt-5.3-codex-spark` only when its installed capability marker exists. Otherwise remain on `harness-implementer`.
4. Use fresh `gpt-5.6-sol` high contexts for independent difficult-problem research and normal task review. Add a separate adversarial review when risk warrants it. Prefix a visible task title or description with `[Codex Sol · high]` when the invoking interface supports one.
5. Use `gpt-5.6-luna` max only for a bounded alternative implementation with explicit file ownership and acceptance criteria. It is never the default implementer. Use `[Codex Luna · max]` as its visible task prefix; use `[Codex-Spark]` for an eligible Spark pass.
6. Use `harness-architecture-reviewer` after architecture-significant changes.
7. Use `harness-judge` to reconcile conflicting evidence. Use its Opus fallback only when Fable is unavailable or the decision is high risk.
8. Finish with the repository's applicable deterministic `build`, `lint`, `typecheck`, and `test` commands. Run each through `claudex5 gate-run --name NAME -- COMMAND` when available. Language-model review never replaces these gates.

Use fresh review contexts and non-overlapping writers.

## Exclude Competing Routers

Do not automatically load `fable-advisor`, route through a Grok lane, or let another orchestration skill replace this matrix. Use another routing skill, plugin lane, or model only when the user explicitly names that exact choice for the current task. Superpowers workflow skills remain allowed because they own process, not routing.
