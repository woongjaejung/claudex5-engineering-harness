#!/usr/bin/env python3
"""Check Codex-Spark availability through model/list without starting a model turn."""

from __future__ import annotations

import argparse
import json
import select
import subprocess
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any


SPARK_MODEL = "gpt-5.3-codex-spark"


class ProbeState(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ProbeResult:
    state: ProbeState
    reason: str


class ProtocolError(RuntimeError):
    """Raised for an invalid or rejected app-server response."""


def _send(process: subprocess.Popen[str], message: dict[str, Any]) -> None:
    if process.stdin is None:
        raise ProtocolError("app-server stdin is unavailable")
    process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
    process.stdin.flush()


def _read_response(
    process: subprocess.Popen[str], request_id: int, deadline: float
) -> dict[str, Any]:
    if process.stdout is None:
        raise ProtocolError("app-server stdout is unavailable")
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("app-server response timed out")
        readable, _, _ = select.select([process.stdout], [], [], remaining)
        if not readable:
            raise TimeoutError("app-server response timed out")
        line = process.stdout.readline()
        if not line:
            raise ProtocolError("app-server closed before responding")
        try:
            message = json.loads(line)
        except json.JSONDecodeError as error:
            raise ProtocolError("app-server returned invalid JSON") from error
        if not isinstance(message, dict) or message.get("id") != request_id:
            continue
        if "error" in message:
            raise ProtocolError("app-server rejected model/list")
        result = message.get("result")
        if not isinstance(result, dict):
            raise ProtocolError("app-server response is missing result")
        return result


def _stop_process(process: subprocess.Popen[str]) -> None:
    if process.stdin is not None:
        try:
            process.stdin.close()
        except OSError:
            pass
    if process.poll() is None:
        process.terminate()
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=1)
    if process.stdout is not None:
        process.stdout.close()


def probe_spark(codex_command: str = "codex", timeout_seconds: float = 8.0) -> ProbeResult:
    """Return whether the authenticated Codex model catalog exposes Spark."""
    process: subprocess.Popen[str] | None = None
    try:
        process = subprocess.Popen(
            [codex_command, "app-server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        deadline = time.monotonic() + timeout_seconds
        _send(
            process,
            {
                "method": "initialize",
                "id": 0,
                "params": {
                    "clientInfo": {
                        "name": "claudex5_harness_probe",
                        "title": "Claudex5 Harness Probe",
                        "version": "1.0.0",
                    }
                },
            },
        )
        _read_response(process, 0, deadline)
        _send(process, {"method": "initialized", "params": {}})

        request_id = 1
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {"limit": 100, "includeHidden": False}
            if cursor is not None:
                params["cursor"] = cursor
            _send(process, {"method": "model/list", "id": request_id, "params": params})
            result = _read_response(process, request_id, deadline)
            data = result.get("data")
            if not isinstance(data, list):
                raise ProtocolError("model/list data is not a list")
            for entry in data:
                if not isinstance(entry, dict):
                    raise ProtocolError("model/list contains an invalid entry")
                if entry.get("model") == SPARK_MODEL or entry.get("id") == SPARK_MODEL:
                    return ProbeResult(ProbeState.AVAILABLE, "Spark appears in model/list")
            next_cursor = result.get("nextCursor")
            if next_cursor is None:
                return ProbeResult(ProbeState.UNAVAILABLE, "Spark is absent from model/list")
            if not isinstance(next_cursor, str) or not next_cursor:
                raise ProtocolError("model/list returned an invalid cursor")
            cursor = next_cursor
            request_id += 1
    except (OSError, ProtocolError, TimeoutError, ValueError):
        return ProbeResult(ProbeState.UNKNOWN, "Spark availability could not be confirmed")
    finally:
        if process is not None:
            _stop_process(process)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check whether the local Codex account exposes gpt-5.3-codex-spark."
    )
    parser.add_argument("--codex-bin", default="codex")
    parser.add_argument("--timeout", type=float, default=8.0)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")

    result = probe_spark(args.codex_bin, args.timeout)
    print(result.state.value)
    return {
        ProbeState.AVAILABLE: 0,
        ProbeState.UNAVAILABLE: 1,
        ProbeState.UNKNOWN: 2,
    }[result.state]


if __name__ == "__main__":
    raise SystemExit(main())
