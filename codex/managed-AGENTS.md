# Claudex5 global Codex routing

Apply this policy automatically to ordinary user requests.

- Handle simple questions and tiny low-risk edits directly. For complex, ambiguous, multi-file, or high-risk work, make the plan and use the registered `harness_*` roles where independent context materially improves accuracy.
- Use `harness_sol_research` for difficult independent analysis, `harness_luna_implementation` only for bounded alternative implementation, `harness_sol_review` for normal review, and `harness_sol_adversarial_review` for failure-oriented review.
- Keep the primary agent responsible for integration, conflict resolution, actual repository inspection, and final verification. Treat agent output as unverified until checked against files and command results.
- Do not run overlapping writers in the same files. Preserve user changes and secrets.
- Run applicable build, lint, typecheck, and test commands before claiming completion. State what was not run and why.
- Fresh contexts are preferred for independent reviews. A review agent must not fix the code it reviews.

