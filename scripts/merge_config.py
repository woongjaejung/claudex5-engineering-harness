#!/usr/bin/env python3
"""Safely merge Claudex5-owned settings into Claude Code and Codex config."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import tempfile
import tomllib
from pathlib import Path


START_MARKER = "<!-- BEGIN CLAUDEX5 ENGINEERING HARNESS -->"
END_MARKER = "<!-- END CLAUDEX5 ENGINEERING HARNESS -->"

CODEX_AGENT_FILES = {
    "harness_sol_research": "harness-sol-research.toml",
    "harness_luna_implementation": "harness-luna-implementation.toml",
    "harness_sol_review": "harness-sol-review.toml",
    "harness_sol_adversarial_review": "harness-sol-adversarial-review.toml",
}

_WRITE_JOURNAL: dict[Path, str] | None = None


def parse_toml(text: str) -> dict:
    """Parse TOML with Python's standards-compliant parser."""
    return tomllib.loads(text)


def assert_safe_target(path: Path) -> None:
    """Reject target files or their configuration directory when symlinked."""
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError(f"refusing symbolic link configuration target: {path}")


def atomic_write(path: Path, text: str, mode: int | None = None) -> None:
    """Write text atomically while retaining an existing file's permissions."""
    assert_safe_target(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    current_mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else mode
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        if current_mode is not None:
            os.chmod(temporary_name, current_mode)
        if _WRITE_JOURNAL is not None:
            _WRITE_JOURNAL[path] = hashlib.sha256(text.encode("utf-8")).hexdigest()
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def replace_managed_block(text: str, start: str, end: str, body: str) -> str:
    """Insert or replace exactly one marker-delimited managed block."""
    start_count = text.count(start)
    end_count = text.count(end)
    if start_count != end_count or start_count > 1:
        raise ValueError("unbalanced or duplicate managed block markers")

    normalized_body = body.strip("\n")
    block = f"{start}\n{normalized_body}\n{end}"
    if start_count == 1:
        pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.DOTALL)
        return pattern.sub(block, text, count=1)

    separator = "" if not text else ("\n" if text.endswith("\n") else "\n\n")
    return f"{text}{separator}{block}\n"


def remove_managed_block(text: str, start: str, end: str) -> str:
    start_count = text.count(start)
    end_count = text.count(end)
    if start_count != end_count or start_count > 1:
        raise ValueError("unbalanced or duplicate managed block markers")
    if start_count == 0:
        return text
    pattern = re.compile(r"\n?" + re.escape(start) + r".*?" + re.escape(end) + r"\n?", re.DOTALL)
    result = pattern.sub("\n", text, count=1)
    return result.rstrip() + ("\n" if result.strip() else "")


def merge_instruction_file(path: Path, managed_body: str) -> None:
    assert_safe_target(path)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    merged = replace_managed_block(existing, START_MARKER, END_MARKER, managed_body)
    atomic_write(path, merged, mode=0o644)


def merge_claude_settings(path: Path, enable_plugin: bool, harden: bool = False) -> list[str]:
    """Merge only official Codex plugin registration into Claude settings."""
    assert_safe_target(path)
    existing = path.read_text(encoding="utf-8") if path.exists() else "{}"
    settings = json.loads(existing)
    if not isinstance(settings, dict):
        raise ValueError("Claude settings root must be a JSON object")

    warnings: list[str] = []
    if settings.get("skipDangerousModePermissionPrompt") is True:
        if harden:
            settings["skipDangerousModePermissionPrompt"] = False
        else:
            warnings.append("Claude dangerous-mode permission warning is currently skipped")

    if enable_plugin:
        plugins = settings.setdefault("enabledPlugins", {})
        if not isinstance(plugins, dict):
            raise ValueError("enabledPlugins must be a JSON object")
        plugins["codex@openai-codex"] = True

        marketplaces = settings.setdefault("extraKnownMarketplaces", {})
        if not isinstance(marketplaces, dict):
            raise ValueError("extraKnownMarketplaces must be a JSON object")
        marketplaces.setdefault(
            "openai-codex",
            {"source": {"source": "github", "repo": "openai/codex-plugin-cc"}},
        )

    rendered = json.dumps(settings, indent=2, ensure_ascii=False) + "\n"
    json.loads(rendered)
    atomic_write(path, rendered, mode=0o600)
    return warnings


def _toml_header_name(line: str) -> str | None:
    """Return a TOML table header body while respecting quoted `]` characters."""
    stripped = line.lstrip()
    if not stripped.startswith("["):
        return None
    array_header = stripped.startswith("[[")
    position = 2 if array_header else 1
    quote: str | None = None
    escaped = False
    start = position
    while position < len(stripped):
        character = stripped[position]
        if quote == '"':
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                quote = None
        elif quote == "'":
            if character == "'":
                quote = None
        elif character in ('"', "'"):
            quote = character
        elif array_header and stripped.startswith("]]", position):
            remainder = stripped[position + 2 :].strip()
            if remainder and not remainder.startswith("#"):
                return None
            return stripped[start:position].strip()
        elif not array_header and character == "]":
            remainder = stripped[position + 1 :].strip()
            if remainder and not remainder.startswith("#"):
                return None
            return stripped[start:position].strip()
        position += 1
    return None


def _section_bounds(lines: list[str]) -> list[tuple[int, int, str]]:
    headers: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        name = _toml_header_name(line)
        if name is not None:
            headers.append((index, name))
    return [
        (start, headers[position + 1][0] if position + 1 < len(headers) else len(lines), name)
        for position, (start, name) in enumerate(headers)
    ]


def _remove_owned_codex_sections(text: str, harden: bool) -> str:
    lines = text.splitlines(keepends=True)
    remove_indices: set[int] = set()
    owned = {f"agents.{name}" for name in CODEX_AGENT_FILES}
    for start, end, name in _section_bounds(lines):
        if name in owned or (harden and name == 'projects."/"'):
            remove_indices.update(range(start, end))
    return "".join(line for index, line in enumerate(lines) if index not in remove_indices).rstrip() + "\n"


def _enable_multi_agent(text: str) -> str:
    lines = text.splitlines(keepends=True)
    sections = _section_bounds(lines)
    feature_section = next(((start, end) for start, end, name in sections if name == "features"), None)
    if feature_section is None:
        base = text.rstrip()
        return f"{base}\n\n[features]\nmulti_agent = true\n" if base else "[features]\nmulti_agent = true\n"

    start, end = feature_section
    for index in range(start + 1, end):
        if re.match(r"^\s*multi_agent\s*=", lines[index]):
            lines[index] = "multi_agent = true\n"
            return "".join(lines)
    lines.insert(start + 1, "multi_agent = true\n")
    return "".join(lines)


def _quote_toml(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def merge_codex_config(path: Path, agent_dir: Path, harden: bool) -> list[str]:
    """Merge multi-agent registration and four namespaced agent tables."""
    assert_safe_target(path)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    parsed_existing = parse_toml(existing)
    warnings: list[str] = []
    root_trusted = parsed_existing.get("projects", {}).get("/", {}).get("trust_level") == "trusted"
    explicit_root_table = bool(re.search(r'^\s*\[projects\."/"\]\s*(?:#.*)?$', existing, re.MULTILINE))
    if harden and root_trusted and not explicit_root_table:
        raise ValueError("cannot safely harden inline root project trust; convert it to [projects.\"/\"] first")
    if root_trusted and not harden:
        warnings.append("Codex root project trust is preserved; rerun with --harden to remove it")

    merged = _remove_owned_codex_sections(existing, harden=harder_bool(harden))
    merged = _enable_multi_agent(merged)
    tables: list[str] = []
    for name, filename in CODEX_AGENT_FILES.items():
        description = {
            "harness_sol_research": "Independent difficult-problem research in a fresh context.",
            "harness_luna_implementation": "Bounded alternative implementation with explicit acceptance criteria.",
            "harness_sol_review": "Independent normal code review in a fresh context.",
            "harness_sol_adversarial_review": "Adversarial review of assumptions, edge cases, and failure modes.",
        }[name]
        tables.append(
            f"[agents.{name}]\n"
            f"description = {_quote_toml(description)}\n"
            f"config_file = {_quote_toml(str(agent_dir / filename))}\n"
        )
    merged = merged.rstrip() + "\n\n" + "\n".join(tables)
    parse_toml(merged)
    atomic_write(path, merged, mode=0o600)
    return warnings


def harder_bool(value: bool) -> bool:
    """Reject truthy non-booleans at the configuration boundary."""
    if not isinstance(value, bool):
        raise TypeError("harden must be a boolean")
    return value


def remove_harness_config(home: Path) -> None:
    claude_md = home / ".claude" / "CLAUDE.md"
    codex_md = home / ".codex" / "AGENTS.md"
    for path in (claude_md, codex_md):
        if path.exists():
            atomic_write(
                path,
                remove_managed_block(path.read_text(encoding="utf-8"), START_MARKER, END_MARKER),
            )

    config_path = home / ".codex" / "config.toml"
    if config_path.exists():
        original = config_path.read_text(encoding="utf-8")
        cleaned = _remove_owned_codex_sections(original, harden=False)
        parse_toml(cleaned)
        atomic_write(config_path, cleaned)


def install_from_repository(home: Path, repository: Path, harden: bool) -> list[str]:
    global _WRITE_JOURNAL
    targets = (
        home / ".claude" / "CLAUDE.md",
        home / ".codex" / "AGENTS.md",
        home / ".claude" / "settings.json",
        home / ".codex" / "config.toml",
    )
    originals = {
        path: (path.read_bytes(), stat.S_IMODE(path.stat().st_mode)) if path.exists() else None
        for path in targets
    }
    warnings: list[str] = []
    write_journal: dict[Path, str] = {}
    _WRITE_JOURNAL = write_journal
    try:
        merge_instruction_file(
            targets[0],
            (repository / "claude" / "managed-CLAUDE.md").read_text(encoding="utf-8"),
        )
        merge_instruction_file(
            targets[1],
            (repository / "codex" / "managed-AGENTS.md").read_text(encoding="utf-8"),
        )
        warnings.extend(merge_claude_settings(targets[2], True, harden))
        warnings.extend(merge_codex_config(targets[3], home / ".codex" / "agents", harden))
    except Exception:
        for path, original in originals.items():
            expected_digest = write_journal.get(path)
            if expected_digest is None:
                continue
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected_digest:
                continue
            if original is None:
                path.unlink(missing_ok=True)
            else:
                data, mode = original
                atomic_write(path, data.decode("utf-8"), mode=mode)
        raise
    finally:
        _WRITE_JOURNAL = None
    return warnings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("install", "uninstall"))
    parser.add_argument("--home", required=True, type=Path)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--harden", action="store_true")
    args = parser.parse_args()

    home = args.home.expanduser().resolve()
    if str(home) == "/":
        parser.error("--home must not be /")
    if args.action == "install":
        for warning in install_from_repository(home, args.repo.resolve(), args.harden):
            print(f"WARNING: {warning}")
    else:
        remove_harness_config(home)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
