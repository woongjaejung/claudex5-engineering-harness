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

The live graph recorder uses an allowlist. It stores only sanitized task labels, logical identifiers, lifecycle state, dependencies, and known role/model/effort metadata. It does not store prompts, code, shell commands, tool output, assistant messages, transcript paths, environment variables, authentication state, or model catalogs.

Runtime graph data remains outside the repository under `${XDG_STATE_HOME:-~/.local/state}/claudex5-engineering-harness/runs`, with private directory and file permissions. It is not copied during installation and is preserved during uninstall unless the user explicitly runs `claudex5 clean --all`.

The web dashboard accepts loopback hosts only, validates the request `Host` against its bound loopback address and port, and provides no public-bind override. Its fixed local assets use a restrictive Content Security Policy, disable caching and MIME sniffing, grant no cross-origin access, and load no content delivery network, analytics, font, or other remote asset. Use SSH port forwarding to view a remote machine's dashboard; do not expose its port publicly.
