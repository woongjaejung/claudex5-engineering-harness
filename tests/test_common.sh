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
