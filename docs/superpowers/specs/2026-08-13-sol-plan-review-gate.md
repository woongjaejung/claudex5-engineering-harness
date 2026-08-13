# Conditional Codex Sol Plan Review Gate Design

## Goal

Independently validate a Fable-authored implementation plan with a fresh, read-only `gpt-5.6-sol` high context before code changes begin when the plan is complex, ambiguous, or high risk. Keep simple plans fast and avoid unbounded review loops.

## Alternatives considered

Three approaches were considered:

1. Review every plan with Sol. This is simple and consistent, but adds latency and model usage to routine work where an independent review is unlikely to change the outcome.
2. Reuse the post-implementation code reviewer. This avoids a new role, but mixes plan-quality criteria with code-defect criteria and makes the displayed task purpose ambiguous.
3. Add a dedicated, conditional plan-review role. This creates one small configuration file but gives the reviewer a precise read-only contract and keeps pre-implementation findings separate from code-review findings.

The third approach is selected.

## Eligibility gate

Run the Sol plan review before implementation when any of these conditions applies:

- the change crosses multiple modules or services;
- authentication, authorization, security boundaries, data migration, or destructive state changes are involved;
- rollback is difficult, the architecture changes materially, or operational risk is high;
- requirements remain ambiguous or multiple viable approaches have materially different tradeoffs;
- the implementation plan contains five or more executable tasks.

Do not run this gate for simple questions, tiny edits, routine single-module changes, or plans below these thresholds unless the user explicitly requests plan review.

## Review protocol

Fable remains the plan owner. It creates the initial plan with requirements, task boundaries, dependency order, acceptance criteria, and deterministic verification.

The main Claude session then sends the complete plan and relevant requirements to a fresh `gpt-5.6-sol` high context. The reviewer is read-only and must not rewrite the plan or edit files. Its visible task description begins with `[Codex Sol · high] Plan review` when the invoking interface supports descriptions.

The reviewer evaluates:

- requirement and constraint coverage;
- unsupported assumptions and missing evidence;
- architecture and task-boundary correctness;
- dependency ordering and safe parallelism;
- test-first acceptance criteria and deterministic verification;
- security, migration, rollback, partial-failure, and recovery behavior;
- unnecessary complexity and viable simpler alternatives.

It returns exactly one decision:

- `APPROVE`: no blocking plan defect was found;
- `NEEDS CHANGES`: one or more blocking defects exist, each with exact plan evidence, impact, and a concrete correction.

Cosmetic preferences and speculative concerns without a reachable failure path are excluded.

## Revision limit and failures

On `NEEDS CHANGES`, Fable revises the plan while retaining ownership of the final design. A new Sol context may recheck the revised plan once. If the second review still reports a blocker, the main session stops before implementation and asks the user to resolve the remaining decision. It must not silently accept the plan or start an unlimited reviewer loop.

If Sol or the official Codex plugin is unavailable, the gate reports the unavailable verification. High-risk work must not represent the plan as independently verified; the user chooses whether to wait, proceed without the gate, or use the manual Opus fallback. Lower-risk work may continue only with a clear disclosure.

## Installation and verification

The repository adds `harness-sol-plan-review.toml`, registers `harness_sol_plan_review` in Codex configuration, and links it through the existing collision-safe installer. Verification requires the link and agent table. Uninstall removes only the repository-owned link and table.

Tests cover the exact model and effort, reviewer output contract, installation and rollback lifecycle, registration idempotence, routing thresholds, one-revision limit, documentation, and credential safety. No credentials, plan contents, or review output are persisted by the harness.
