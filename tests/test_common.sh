#!/usr/bin/env bash
set -euo pipefail

repo_root="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
# shellcheck source=../scripts/common.sh
source "$repo_root/scripts/common.sh"

fake_root="$(mktemp -d)"
trap 'rm -rf "$fake_root"' EXIT
mkdir -p "$fake_root/bin"

write_fake_node() {
  local version="$1"
  local status=0
  case "$version" in
    18.0.*|18.1.*|18.2.*|18.3.*|18.4.*|18.5.*|18.6.*|18.7.*|18.8.*|18.9.*|18.10.*|18.11.*|18.12.*|18.13.*|18.14.*|18.15.*|18.16.*|18.17.*) status=1 ;;
  esac
  cat > "$fake_root/bin/node" <<EOF
#!/usr/bin/env bash
if [[ "\${1:-}" == "-p" ]]; then exit $status; else printf '%s\n' "v$version"; fi
EOF
  chmod +x "$fake_root/bin/node"
}

write_fake_node "18.17.1"
if PATH="$fake_root/bin:/usr/bin:/bin" claudex5_node_version_ok; then
  printf '%s\n' "Node 18.17 must be rejected" >&2
  exit 1
fi

write_fake_node "18.18.0"
PATH="$fake_root/bin:/usr/bin:/bin" claudex5_node_version_ok

write_fake_node "22.1.0"
PATH="$fake_root/bin:/usr/bin:/bin" claudex5_node_version_ok

# A numeric version gate must compare all three components, rather than using
# lexical ordering or accepting a version substring from unrelated output.
if claudex5_version_at_least "2.1.32" "2.1.33"; then
  printf '%s\n' "2.1.32 must be below the TaskCompleted boundary" >&2
  exit 1
fi
claudex5_version_at_least "2.1.33" "2.1.33"
if claudex5_version_at_least "2.1.83" "2.1.84"; then
  printf '%s\n' "2.1.83 must be below the TaskCreated boundary" >&2
  exit 1
fi
claudex5_version_at_least "2.1.84" "2.1.84"
claudex5_version_at_least "2.2.0" "2.1.84"
claudex5_version_at_least "999999999999999999999999999999999999.1.0" "2.1.84"
if claudex5_version_at_least "1.999999999999999999999999999999999999.0" "2.1.84"; then
  printf '%s\n' "an oversized minor component must not override a smaller major version" >&2
  exit 1
fi

cat > "$fake_root/bin/claude" <<'EOF'
#!/usr/bin/env bash
case "${1:-}" in
  --version) printf '%s' "${FAKE_CLAUDE_VERSION:-2.1.226}" ;;
  *) exit 1 ;;
esac
EOF
chmod +x "$fake_root/bin/claude"
PATH="$fake_root/bin:/usr/bin:/bin" claudex5_claude_version
FAKE_CLAUDE_VERSION='2.1.226 (Claude Code)' PATH="$fake_root/bin:/usr/bin:/bin" claudex5_claude_version
for invalid in '2.1.84-beta.1' 'Claude Code 2.1.226 2.1.227' 'not a version' $'2.1.226\nextra'; do
  if FAKE_CLAUDE_VERSION="$invalid" PATH="$fake_root/bin:/usr/bin:/bin" claudex5_claude_version >/dev/null; then
    printf 'invalid Claude version output was accepted: %s\n' "$invalid" >&2
    exit 1
  fi
done
if PATH="/usr/bin:/bin" claudex5_claude_version >/dev/null; then
  printf '%s\n' "missing Claude command must not produce a version" >&2
  exit 1
fi

[[ "$(claudex5_hook_groups 0 0)" == $'SessionStart\nPreToolUse\nPostToolUse\nSubagentStart\nSubagentStop\nStop\nSessionEnd' ]]
[[ "$(claudex5_hook_groups 0 1 | tail -n 1)" == "TaskCompleted" ]]
[[ "$(claudex5_hook_groups 1 1 | tail -n 1)" == "TaskCreated" ]]

enabled_plugins='Installed plugins:

  ❯ codex@openai-codex
    Version: 1.0.0
    Scope: user
    Status: ✔ enabled'
disabled_plugins='Installed plugins:

  ❯ codex@openai-codex
    Version: 1.0.0
    Scope: user
    Status: disabled'
claudex5_codex_plugin_enabled "$enabled_plugins"
if claudex5_codex_plugin_enabled "$disabled_plugins"; then
  printf '%s\n' "disabled Codex plugin must not be accepted as enabled" >&2
  exit 1
fi

mixed_plugins='Installed plugins:

  ❯ superpowers@claude-plugins-official
    Version: 6.2.0
    Scope: user
    Status: ✔ enabled

  ❯ fable-advisor@fable-advisor
    Version: 4.0.0
    Scope: user
    Status: ✔ enabled

  ❯ disabled-router@third-party
    Version: 1.0.0
    Scope: user
    Status: disabled'
claudex5_plugin_enabled "$mixed_plugins" "superpowers"
claudex5_plugin_enabled "$mixed_plugins" "fable-advisor"
if claudex5_plugin_enabled "$mixed_plugins" "disabled-router"; then
  printf '%s\n' "disabled plugin must not be accepted as enabled" >&2
  exit 1
fi
if claudex5_plugin_enabled "$mixed_plugins" "fable"; then
  printf '%s\n' "substring-only plugin name must not match" >&2
  exit 1
fi

printf '%s\n' "common helper tests: PASS"
