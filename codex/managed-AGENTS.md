# Claudex5 global Codex routing

Apply this policy automatically to ordinary user requests.

- Handle simple questions and tiny low-risk edits directly. For complex, ambiguous, multi-file, or high-risk work, make the plan and use the registered `harness_*` roles where independent context materially improves accuracy.
- Before implementation, use `harness_sol_plan_review` in a fresh read-only context for complex or high-risk plans. The primary agent owns and revises the plan; the reviewer returns `APPROVE` or `NEEDS CHANGES`. Allow one revision and one fresh recheck, then stop before implementation for user direction if blockers remain. Skip the gate for routine simple plans.
- Use `harness_sol_adversarial_review` for failure-oriented review of a meaningful change when risk warrants it. Other registered `harness_*` roles (`harness_sol_research`, `harness_luna_implementation`, `harness_sol_review`, `harness_spark_ui_iteration`) are manual escape hatches: use one only when the user explicitly names it for the current task, and never use Spark for architecture, backend logic, security-sensitive behavior, data migration, broad refactors, or review.
- Keep the primary agent responsible for integration, conflict resolution, actual repository inspection, and final verification. Treat agent output as unverified until checked against files and command results.
- Do not run overlapping writers in the same files. Preserve user changes and secrets.
- Run applicable build, lint, typecheck, and test commands before claiming completion. State what was not run and why.
- Fresh contexts are preferred for independent reviews. A review agent must not fix the code it reviews.
