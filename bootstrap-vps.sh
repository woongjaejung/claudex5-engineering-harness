#!/usr/bin/env bash
set -euo pipefail

dry_run=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) dry_run=1; shift ;;
    -h|--help)
      printf '%s\n' "Usage: ./bootstrap-vps.sh [--dry-run]"
      exit 0
      ;;
    *) printf 'ERROR: unknown argument: %s\n' "$1" >&2; exit 1 ;;
  esac
done

os_name="$(uname -s)"
os_release_file="${CLAUDEX5_OS_RELEASE:-/etc/os-release}"
os_id=""
if [[ -r "$os_release_file" ]]; then
  os_id="$(awk -F= '$1=="ID" {gsub(/"/, "", $2); print $2}' "$os_release_file")"
fi

printf '%s\n' "Claudex5 VPS bootstrap plan"
claude_version="${CLAUDEX5_CLAUDE_VERSION:-2.1.226}"
codex_version="${CLAUDEX5_CODEX_VERSION:-0.147.0}"

printf '%s\n' "  1. Ensure Git, curl, certificates, tar, xz, and Python 3.11+"
printf '%s\n' "  2. Install Node.js 22 from nodejs.org under ~/.local when needed"
printf '%s\n' "  3. Install Claude Code with Anthropic's official native installer"
printf '%s\n' "  4. Install OpenAI Codex with the official npm package"
printf '%s\n' "  5. Keep Claude and ChatGPT authentication as a machine-local login"

if [[ "$dry_run" -eq 1 ]]; then
  exit 0
fi

printf '%s\n' "WARNING: --bootstrap downloads and executes pinned-version installers from Anthropic, OpenAI/npm, and nodejs.org."
printf '%s\n' "         Review this script and the displayed versions before continuing on a sensitive host." >&2

case "$os_name:$os_id" in
  Linux:ubuntu|Linux:debian)
    missing_packages=()
    command -v git >/dev/null 2>&1 || missing_packages+=(git)
    command -v curl >/dev/null 2>&1 || missing_packages+=(curl)
    command -v tar >/dev/null 2>&1 || missing_packages+=(tar)
    command -v xz >/dev/null 2>&1 || missing_packages+=(xz-utils)
    command -v python3 >/dev/null 2>&1 || missing_packages+=(python3)
    if [[ ${#missing_packages[@]} -gt 0 ]]; then
      [[ -t 0 ]] || { printf '%s\n' "ERROR: package installation needs an interactive sudo session" >&2; exit 1; }
      printf 'About to run: sudo apt-get update && sudo apt-get install -y ca-certificates %s\n' "${missing_packages[*]}"
      sudo apt-get update
      sudo apt-get install -y ca-certificates "${missing_packages[@]}"
    fi
    ;;
  Darwin:*) ;;
  *)
    printf 'ERROR: automatic bootstrap supports macOS, Debian, and Ubuntu; detected %s (%s)\n' "$os_name" "$os_id" >&2
    exit 1
    ;;
esac

python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' || {
  printf '%s\n' "ERROR: Python 3.11 or newer is required. Install it with your distribution package manager." >&2
  exit 1
}

export PATH="$HOME/.local/bin:$PATH"
node_ok=0
if command -v node >/dev/null 2>&1 && node -p '
  const [major, minor] = process.versions.node.split(".").map(Number);
  process.exit(major > 18 || (major === 18 && minor >= 18) ? 0 : 1)
' >/dev/null 2>&1; then
  node_ok=1
fi

if [[ "$node_ok" != "1" ]]; then
  [[ "$os_name" == "Linux" ]] || {
    printf '%s\n' "ERROR: install Node.js 18.18+ with Homebrew before continuing" >&2
    exit 1
  }
  case "$(uname -m)" in
    x86_64|amd64) node_arch="x64" ;;
    aarch64|arm64) node_arch="arm64" ;;
    *) printf 'ERROR: unsupported Node.js architecture: %s\n' "$(uname -m)" >&2; exit 1 ;;
  esac
  temporary_dir="$(mktemp -d)"
  trap 'rm -rf "$temporary_dir"' EXIT
  sums_url="https://nodejs.org/dist/latest-v22.x/SHASUMS256.txt"
  effective_url="$(curl -fsSL -o "$temporary_dir/SHASUMS256.txt" -w '%{url_effective}' "$sums_url")"
  node_version="$(printf '%s' "$effective_url" | sed -E 's#^.*/(v[0-9.]+)/SHASUMS256.txt$#\1#')"
  [[ "$node_version" =~ ^v22\.[0-9]+\.[0-9]+$ ]] || { printf '%s\n' "ERROR: could not resolve Node.js 22 release" >&2; exit 1; }
  archive="node-${node_version}-linux-${node_arch}.tar.xz"
  grep "  $archive$" "$temporary_dir/SHASUMS256.txt" > "$temporary_dir/selected.sha256"
  curl -fsSL "https://nodejs.org/dist/$node_version/$archive" -o "$temporary_dir/$archive"
  (
    cd "$temporary_dir"
    if command -v sha256sum >/dev/null 2>&1; then
      sha256sum -c selected.sha256
    else
      shasum -a 256 -c selected.sha256
    fi
  )
  mkdir -p "$HOME/.local/lib" "$HOME/.local/bin"
  tar -xJf "$temporary_dir/$archive" -C "$HOME/.local/lib"
  if [[ -e "$HOME/.local/lib/node-v22" || -L "$HOME/.local/lib/node-v22" ]]; then
    mv "$HOME/.local/lib/node-v22" "$HOME/.local/lib/node-v22.previous-$(date -u +%Y%m%dT%H%M%SZ)"
  fi
  mv "$HOME/.local/lib/node-${node_version}-linux-${node_arch}" "$HOME/.local/lib/node-v22"
  for binary in node npm npx corepack; do
    ln -sfn "$HOME/.local/lib/node-v22/bin/$binary" "$HOME/.local/bin/$binary"
  done
  rm -rf "$temporary_dir"
  trap - EXIT
fi

if ! command -v claude >/dev/null 2>&1; then
  installer_dir="$(mktemp -d)"
  curl -fsSL https://claude.ai/install.sh -o "$installer_dir/claude-install.sh"
  bash "$installer_dir/claude-install.sh" "$claude_version"
  rm -rf "$installer_dir"
  export PATH="$HOME/.local/bin:$PATH"
fi

if ! command -v codex >/dev/null 2>&1; then
  mkdir -p "$HOME/.local"
  npm install -g --prefix "$HOME/.local" "@openai/codex@$codex_version"
fi

printf '%s\n' "Bootstrap complete. Authentication is intentionally not copied."
printf '%s\n' "Run: claude"
printf '%s\n' "Run: codex login --device-auth"
