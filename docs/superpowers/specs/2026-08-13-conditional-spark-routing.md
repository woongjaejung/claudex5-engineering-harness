# Conditional Codex-Spark Routing Design

## Goal

Use `gpt-5.3-codex-spark` automatically for small, bounded UI iteration only when the currently authenticated Codex account exposes that model. Keep installation successful and fall back to the existing Sonnet implementation path when Spark is unavailable or the capability check cannot complete.

## Decision

The installer will query the local Codex App Server `model/list` method. It will not start a model turn, inspect credential files, infer a subscription from local tokens, or save account metadata. An exact `gpt-5.3-codex-spark` model-list match enables the optional Spark role for that machine.

The alternatives were rejected for these reasons:

- Reading a subscription tier from authentication state is unsupported and would couple the harness to sensitive, unstable files.
- Sending a trial prompt to Spark would consume model usage and produce unnecessary remote work.
- Always registering Spark would expose a broken role on accounts without access.

## Installation behavior

`scripts/spark_probe.py` will perform a bounded JSONL handshake with `codex app-server`, call `model/list`, follow pagination, and return one of three machine-readable states:

- `available`: the exact Spark model is listed.
- `unavailable`: the model list completed but Spark was absent.
- `unknown`: Codex was missing, unauthenticated, timed out, or returned an invalid response.

`install.sh` treats only `available` as permission to enable Spark. `unavailable` and `unknown` both keep the normal installation successful, omit the optional role, and print a concise explanation. Reinstalling also removes only a previously harness-managed Spark link and Codex agent table when access is no longer confirmed.

When `--skip-runtime-check` is used, the installer does not probe a real account and leaves Spark disabled. This keeps isolated and continuous-integration tests deterministic.

## Routing behavior

The optional `harness_spark_ui_iteration` agent is eligible only for a small change to an existing user interface with explicit acceptance criteria. Examples include spacing, copy, one component state, or a narrow visual correction with browser verification.

Spark is not eligible for architecture, backend logic, security-sensitive behavior, data migrations, broad refactors, independent review, or ambiguous multi-file work. Those tasks retain the existing Sonnet, Luna, Sol, Opus, and Fable routes.

The Spark role link is the local capability marker. Global Claude and Codex instructions may route to Spark only while that harness-owned link exists. If Spark is not registered, ordinary requests follow the existing Sonnet implementation path without an error. An explicit Spark request receives a clear fallback explanation.

## Verification and recovery

Structural verification accepts either a consistent disabled state or a consistent enabled state. If either the Spark link or Codex table exists without the other, verification fails.

Runtime verification queries model availability again. A mismatch between current access and installed state is a warning, not a failed installation, because authentication and network availability can be transient. Running `./install.sh` reconciles the state.

Uninstallation removes the optional role under the same ownership checks as all other harness links. No credentials, tokens, model-list responses, or subscription details are written into the repository or machine-local state.

## Documentation

The English README will describe automatic eligibility, manual invocation, fallback, update, and troubleshooting. Korean text will remain confined to `docs/usage-ko.md`, which will provide equivalent usage and update guidance for the repository owner.
