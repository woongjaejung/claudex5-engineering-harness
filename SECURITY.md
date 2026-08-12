# Security Policy

## Supported versions

Security fixes are applied to the latest commit on the default branch. Tagged releases may be introduced later; until then, update with `git pull --ff-only` and rerun `./install.sh`.

## Reporting a vulnerability

Do not open a public issue containing credentials, tokens, private repository content, account identifiers, or an unpatched exploit.

Use GitHub's **Private vulnerability reporting** feature on the repository's Security tab. Include:

- affected commit and operating system;
- exact installer or verifier command;
- impact and reachable attack path;
- a minimal reproduction with synthetic values only;
- whether the issue can overwrite user files, weaken permissions, or expose credentials.

If private vulnerability reporting is not enabled, open a public issue asking the maintainer to enable a private reporting channel, without including sensitive details.

## Security boundaries

This project protects its own managed configuration workflow. It does not secure unrelated Claude/Codex plugins, shell startup files, projects, model output, or the host operating system.

The installer intentionally does not read or copy Claude/Codex authentication files. `verify.sh` detects common credential formats but cannot prove that arbitrary prose contains no sensitive business data. Review every staged diff before publishing.

