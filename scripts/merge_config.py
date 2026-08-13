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
CLAUDEX5_SUBAGENT_STATUS_LINE = {
    "type": "command",
    "command": "~/.claude/statuslines/claudex5-subagent-models.py",
}
CLAUDEX5_HOOK_COMMAND = {
    "type": "command",
    "command": "~/.claude/hooks/claudex5-live-graph.py",
    "timeout": 5,
}


def owned_group(matcher: str | None = None) -> dict:
    """Build one exact Claudex5-owned lifecycle hook group."""
    group = {"hooks": [dict(CLAUDEX5_HOOK_COMMAND)]}
    if matcher is not None:
        group["matcher"] = matcher
    return group


BASE_CLAUDEX5_HOOK_GROUPS = {
    "SessionStart": (owned_group(),),
    "PreToolUse": (owned_group(matcher="TaskCreate"),),
    "PostToolUse": (
        owned_group(matcher="TaskCreate"),
        owned_group(matcher="TaskUpdate"),
        owned_group(matcher="Agent"),
    ),
    "SubagentStart": (owned_group(),),
    "SubagentStop": (owned_group(),),
    "Stop": (owned_group(),),
    "SessionEnd": (owned_group(),),
}
TASK_COMPLETED_HOOK_GROUPS = {"TaskCompleted": (owned_group(),)}
TASK_CREATED_HOOK_GROUPS = {"TaskCreated": (owned_group(),)}
CLAUDEX5_HOOK_GROUPS = {
    **BASE_CLAUDEX5_HOOK_GROUPS,
    **TASK_COMPLETED_HOOK_GROUPS,
    **TASK_CREATED_HOOK_GROUPS,
}


def selected_claudex5_hook_groups(
    enable_task_created: bool = False, enable_task_completed: bool = False
) -> dict[str, tuple[dict, ...]]:
    """Return the hook groups supported by the detected Claude Code version."""
    selected = dict(BASE_CLAUDEX5_HOOK_GROUPS)
    if enable_task_completed:
        selected.update(TASK_COMPLETED_HOOK_GROUPS)
    if enable_task_created:
        selected.update(TASK_CREATED_HOOK_GROUPS)
    return selected

BASE_CODEX_AGENT_FILES = {
    "harness_sol_research": "harness-sol-research.toml",
    "harness_sol_plan_review": "harness-sol-plan-review.toml",
    "harness_luna_implementation": "harness-luna-implementation.toml",
    "harness_sol_review": "harness-sol-review.toml",
    "harness_sol_adversarial_review": "harness-sol-adversarial-review.toml",
}
SPARK_AGENT_FILES = {
    "harness_spark_ui_iteration": "harness-spark-ui-iteration.toml",
}
ALL_CODEX_AGENT_FILES = {**BASE_CODEX_AGENT_FILES, **SPARK_AGENT_FILES}

CODEX_AGENT_DESCRIPTIONS = {
    "harness_sol_research": "Independent difficult-problem research in a fresh context.",
    "harness_sol_plan_review": "Fresh, read-only review of a complex or high-risk implementation plan.",
    "harness_luna_implementation": "Bounded alternative implementation with explicit acceptance criteria.",
    "harness_sol_review": "Independent normal code review in a fresh context.",
    "harness_sol_adversarial_review": "Adversarial review of assumptions, edge cases, and failure modes.",
    "harness_spark_ui_iteration": "Fast, bounded iteration on one existing user-interface detail.",
}

_WRITE_JOURNAL: dict[Path, str] | None = None
_EXPECTED_STATES: dict[Path, str | None] | None = None


def _file_digest(path: Path) -> str | None:
    if not path.exists():
        return None
    if not path.is_file():
        raise RuntimeError(f"configuration target is not a regular file: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
        if _EXPECTED_STATES is not None and path in _EXPECTED_STATES:
            if _file_digest(path) != _EXPECTED_STATES[path]:
                raise RuntimeError(f"configuration changed concurrently: {path}")
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


def merge_claude_settings(
    path: Path,
    enable_plugin: bool,
    harden: bool = False,
    enable_task_created: bool = False,
    enable_task_completed: bool = False,
) -> list[str]:
    """Merge Claudex5-owned settings while retaining foreign values verbatim."""
    assert_safe_target(path)
    existing = path.read_text(encoding="utf-8") if path.exists() else "{}"
    settings = json.loads(existing)
    if not isinstance(settings, dict):
        raise ValueError("Claude settings root must be a JSON object")

    warnings: list[str] = []
    hooks = settings.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError("hooks must be a JSON object")
    selected_groups = selected_claudex5_hook_groups(
        enable_task_created=enable_task_created,
        enable_task_completed=enable_task_completed,
    )
    for event, owned_groups in CLAUDEX5_HOOK_GROUPS.items():
        groups = hooks.setdefault(event, [])
        if not isinstance(groups, list):
            raise ValueError(f"hooks.{event} must be a JSON array")
        retained = [group for group in groups if group not in owned_groups]
        retained.extend(selected_groups.get(event, ()))
        if retained:
            hooks[event] = retained
        else:
            hooks.pop(event, None)
    if "subagentStatusLine" not in settings:
        settings["subagentStatusLine"] = dict(CLAUDEX5_SUBAGENT_STATUS_LINE)
    elif settings["subagentStatusLine"] != CLAUDEX5_SUBAGENT_STATUS_LINE:
        warnings.append(
            "foreign subagentStatusLine is preserved; Claudex5 model labels are not active"
        )
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
    owned = {f"agents.{name}" for name in ALL_CODEX_AGENT_FILES}
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


def merge_codex_config(
    path: Path, agent_dir: Path, harden: bool, enable_spark: bool = False
) -> list[str]:
    """Merge required agents and the optional, capability-gated Spark agent."""
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
    agent_files = dict(BASE_CODEX_AGENT_FILES)
    if enable_spark:
        agent_files.update(SPARK_AGENT_FILES)
    for name, filename in agent_files.items():
        description = CODEX_AGENT_DESCRIPTIONS[name]
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


def _config_state_text(
    targets: tuple[Path, ...],
    originals: dict[Path, tuple[bytes, int] | None],
    write_journal: dict[Path, str],
) -> str:
    rows = []
    for path in targets:
        relative = str(path.relative_to(path.parents[1]))
        if path in write_journal:
            rows.append(f"{relative}\tpresent\t{write_journal[path]}")
        elif originals[path] is not None:
            rows.append(f"{relative}\tpresent\t{hashlib.sha256(originals[path][0]).hexdigest()}")
        else:
            rows.append(f"{relative}\tabsent\t-")
    return "\n".join(rows) + "\n"


def remove_harness_config(home: Path, state_file: Path | None = None) -> None:
    global _EXPECTED_STATES, _WRITE_JOURNAL
    claude_md = home / ".claude" / "CLAUDE.md"
    codex_md = home / ".codex" / "AGENTS.md"
    settings_path = home / ".claude" / "settings.json"
    config_path = home / ".codex" / "config.toml"
    targets = (claude_md, codex_md, settings_path, config_path)
    originals = {
        path: (path.read_bytes(), stat.S_IMODE(path.stat().st_mode)) if path.exists() else None
        for path in targets
    }
    write_journal: dict[Path, str] = {}
    _EXPECTED_STATES = {
        path: hashlib.sha256(original[0]).hexdigest() if original is not None else None
        for path, original in originals.items()
    }
    _WRITE_JOURNAL = write_journal
    try:
        for path in (claude_md, codex_md):
            if path.exists():
                atomic_write(
                    path,
                    remove_managed_block(
                        path.read_text(encoding="utf-8"), START_MARKER, END_MARKER
                    ),
                )

        if settings_path.exists():
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
            if not isinstance(settings, dict):
                raise ValueError("Claude settings root must be a JSON object")
            changed = False
            hooks = settings.get("hooks")
            if isinstance(hooks, dict):
                for event, owned_groups in CLAUDEX5_HOOK_GROUPS.items():
                    groups = hooks.get(event)
                    if not isinstance(groups, list):
                        continue
                    retained = [group for group in groups if group not in owned_groups]
                    if retained != groups:
                        changed = True
                    if retained:
                        hooks[event] = retained
                    else:
                        hooks.pop(event, None)
                if not hooks:
                    settings.pop("hooks", None)
            if settings.get("subagentStatusLine") == CLAUDEX5_SUBAGENT_STATUS_LINE:
                del settings["subagentStatusLine"]
                changed = True
            if changed:
                atomic_write(
                    settings_path,
                    json.dumps(settings, indent=2, ensure_ascii=False) + "\n",
                )

        if config_path.exists():
            original = config_path.read_text(encoding="utf-8")
            cleaned = _remove_owned_codex_sections(original, harden=False)
            parse_toml(cleaned)
            atomic_write(config_path, cleaned)
        if state_file is not None:
            atomic_write(state_file, _config_state_text(targets, originals, write_journal), mode=0o600)
    except Exception:
        _EXPECTED_STATES = None
        _WRITE_JOURNAL = None
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
        _EXPECTED_STATES = None
        _WRITE_JOURNAL = None


def install_from_repository(
    home: Path,
    repository: Path,
    harden: bool,
    enable_spark: bool = False,
    enable_task_created: bool = False,
    enable_task_completed: bool = False,
) -> list[str]:
    global _EXPECTED_STATES, _WRITE_JOURNAL
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
    _EXPECTED_STATES = {
        path: hashlib.sha256(original[0]).hexdigest() if original is not None else None
        for path, original in originals.items()
    }
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
        warnings.extend(
            merge_claude_settings(
                targets[2],
                True,
                harden,
                enable_task_created=enable_task_created,
                enable_task_completed=enable_task_completed,
            )
        )
        warnings.extend(
            merge_codex_config(
                targets[3], home / ".codex" / "agents", harden, enable_spark=enable_spark
            )
        )
    except Exception:
        _EXPECTED_STATES = None
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
        _EXPECTED_STATES = None
        _WRITE_JOURNAL = None
    return warnings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("install", "uninstall"))
    parser.add_argument("--home", required=True, type=Path)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--harden", action="store_true")
    parser.add_argument("--enable-spark", action="store_true")
    parser.add_argument("--enable-task-created", action="store_true")
    parser.add_argument("--enable-task-completed", action="store_true")
    parser.add_argument("--state-file", type=Path)
    args = parser.parse_args()

    home = args.home.expanduser().resolve()
    if str(home) == "/":
        parser.error("--home must not be /")
    if args.action == "install":
        for warning in install_from_repository(
            home,
            args.repo.resolve(),
            args.harden,
            enable_spark=args.enable_spark,
            enable_task_created=args.enable_task_created,
            enable_task_completed=args.enable_task_completed,
        ):
            print(f"WARNING: {warning}")
    else:
        remove_harness_config(home, args.state_file)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
