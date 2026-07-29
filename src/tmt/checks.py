"""The tmt check gate battery: collect every failure, never stop early.

Draft gates apply to all tools, including the undeclared-composition gate
(a sibling tool id used in the body must be declared in ``requires``);
stable tools add the test (which must differ from the unmodified
scaffold), dependency-stage, portability, and origin-drift gates. Origin
drift is always a warning.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from tmt import registry, scaffold

HELP_TIMEOUT_SECONDS = 5
TEST_TIMEOUT_SECONDS = 60
_COMPANION_SUFFIXES = (".md", ".test")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def capture_help(path: Path) -> tuple[bool, str]:
    """Run ``path --help``; return (ok, help output or failure detail)."""
    try:
        completed = subprocess.run(
            [os.fspath(path), "--help"],
            capture_output=True,
            text=True,
            timeout=HELP_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return False, f"--help did not finish within {HELP_TIMEOUT_SECONDS}s"
    except OSError as error:
        return False, f"--help could not run: {error}"
    if completed.returncode != 0:
        return False, f"--help exited {completed.returncode}"
    return True, completed.stdout


def portability_findings(root: Path, tool_id: str, tool: Path) -> list[str]:
    """Hardcoded-absolute-path findings in the tool body."""
    body = tool.read_text(encoding="utf-8", errors="replace")
    findings: list[str] = []
    if "/home/" in body:
        findings.append(
            f"{tool_id}: hardcoded absolute path: body contains '/home/'"
        )
    root_text = os.fspath(root.resolve())
    if root_text in body:
        findings.append(
            f"{tool_id}: hardcoded absolute path: body contains the repo "
            f"path {root_text!r}"
        )
    return findings


def undeclared_composition(
    tool_id: str, entry: dict[str, Any], tool: Path, tools: dict[str, Any]
) -> list[str]:
    """Sibling tool ids used in the body but absent from ``requires``.

    A registered id counts as used when it appears as a standalone word
    (no adjacent ``[A-Za-z0-9_-]``), so ids embedded in longer identifiers
    do not match. Full-line comments — lines whose first non-whitespace
    character is ``#``, including the shebang — are dropped before
    scanning, so prose references to sibling tools belong there. Inline
    comments and string literals are scanned: path strings legitimately
    contain sibling ids and must keep matching. Undecodable tool bodies
    are skipped.
    """
    try:
        text = tool.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return []
    body = "\n".join(
        line
        for line in text.splitlines()
        if not line.lstrip().startswith("#")
    )
    declared = set(entry["requires"])
    failures: list[str] = []
    for other in sorted(tools):
        if other == tool_id or other in declared:
            continue
        pattern = (
            f"(?<![A-Za-z0-9_-]){re.escape(other)}(?![A-Za-z0-9_-])"
        )
        if re.search(pattern, body):
            failures.append(
                f"{tool_id}: uses sibling {other!r} without declaring it "
                "in requires"
            )
    return failures


def stable_gate_failures(
    root: Path, tool_id: str, tools: dict[str, Any]
) -> list[str]:
    """The full gate battery one tool must pass to hold ``stage: stable``.

    Reuses the ``tmt check`` gates: the per-tool draft gates, the
    undeclared-composition gate, and the stable gates. Origin-drift
    warnings are not failures and are not included.
    """
    entry = {**registry.effective(tools[tool_id]), "stage": "stable"}
    tool = root / "tools" / tool_id
    if not tool.is_file():
        return [f"{tool_id}: tools/{tool_id} missing for tmt.json entry"]
    failures = _check_tool(tool_id, entry, tool)
    failures.extend(undeclared_composition(tool_id, entry, tool, tools))
    stable_failures, _ = _check_stable(root, tool_id, entry, tool, tools)
    failures.extend(stable_failures)
    return failures


def run_checks(root: Path) -> tuple[list[str], list[str]]:
    """Run the full battery; return (failures, warnings)."""
    warnings: list[str] = []
    path = root / registry.REGISTRY_FILENAME
    if not path.is_file():
        return (
            [f"registry: {registry.REGISTRY_FILENAME} does not exist"],
            warnings,
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        return [f"registry: tmt.json does not parse: {error}"], warnings
    validation = registry.validate(data)
    if validation:
        return [f"registry: {message}" for message in validation], warnings
    failures: list[str] = []
    tools: dict[str, Any] = data["tools"]
    tools_dir = root / "tools"
    for name in sorted(_tool_files(tools_dir) - set(tools)):
        failures.append(f"tools/{name}: file has no tmt.json entry")
    for tool_id in sorted(tools):
        entry = registry.effective(tools[tool_id])
        tool = tools_dir / tool_id
        if not tool.is_file():
            failures.append(
                f"{tool_id}: tools/{tool_id} missing for tmt.json entry"
            )
            continue
        failures.extend(_check_tool(tool_id, entry, tool))
        failures.extend(
            undeclared_composition(tool_id, entry, tool, tools)
        )
        if entry["stage"] == "stable":
            stable_failures, stable_warnings = _check_stable(
                root, tool_id, entry, tool, tools
            )
            failures.extend(stable_failures)
            warnings.extend(stable_warnings)
    failures.extend(_check_requires(tools))
    return failures, warnings


def _tool_files(tools_dir: Path) -> set[str]:
    if not tools_dir.is_dir():
        return set()
    return {
        item.name
        for item in tools_dir.iterdir()
        if item.is_file()
        and not item.name.startswith(".")
        and not item.name.endswith(_COMPANION_SUFFIXES)
    }


def _check_tool(
    tool_id: str, entry: dict[str, Any], tool: Path
) -> list[str]:
    failures: list[str] = []
    lang = entry["lang"]
    if lang == "python":
        try:
            compile(
                tool.read_text(encoding="utf-8", errors="replace"),
                os.fspath(tool),
                "exec",
            )
        except (SyntaxError, ValueError) as error:
            failures.append(f"{tool_id}: python syntax error: {error}")
    elif lang == "sh":
        lint = subprocess.run(
            ["sh", "-n", os.fspath(tool)], capture_output=True, text=True
        )
        if lint.returncode != 0:
            detail = (lint.stderr.strip().splitlines() or ["sh -n failed"])[0]
            failures.append(f"{tool_id}: sh syntax error: {detail}")
    if not os.access(tool, os.X_OK):
        failures.append(
            f"{tool_id}: executable bit not set on tools/{tool_id}"
        )
        return failures
    ok, detail = capture_help(tool)
    if not ok:
        failures.append(f"{tool_id}: {detail}")
    return failures


def _check_requires(tools: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    for tool_id in sorted(tools):
        for dependency in registry.effective(tools[tool_id])["requires"]:
            if dependency not in tools:
                failures.append(
                    f"{tool_id}: requires {dependency!r} which is not "
                    "registered"
                )
    failures.extend(_find_cycles(tools))
    return failures


def _find_cycles(tools: dict[str, Any]) -> list[str]:
    graph = {
        tool_id: [
            dependency
            for dependency in registry.effective(entry)["requires"]
            if dependency in tools
        ]
        for tool_id, entry in tools.items()
    }
    failures: list[str] = []
    state: dict[str, int] = {}  # 1 = on stack, 2 = finished

    def visit(node: str, stack: list[str]) -> None:
        state[node] = 1
        stack.append(node)
        for dependency in graph[node]:
            if state.get(dependency) == 1:
                cycle = [*stack[stack.index(dependency):], dependency]
                failures.append("requires cycle: " + " -> ".join(cycle))
            elif dependency not in state:
                visit(dependency, stack)
        stack.pop()
        state[node] = 2

    for node in sorted(graph):
        if node not in state:
            visit(node, [])
    return failures


def _check_stable(
    root: Path,
    tool_id: str,
    entry: dict[str, Any],
    tool: Path,
    tools: dict[str, Any],
) -> tuple[list[str], list[str]]:
    failures: list[str] = []
    test = tool.with_name(f"{tool.name}.test")
    if not test.is_file():
        failures.append(
            f"{tool_id}: stable tool is missing tools/{tool_id}.test"
        )
    elif not os.access(test, os.X_OK):
        failures.append(
            f"{tool_id}: executable bit not set on tools/{tool_id}.test"
        )
    elif test.read_bytes() == scaffold.render_test(tool_id).encode("utf-8"):
        failures.append(
            f"{tool_id}: tools/{tool_id}.test is the unmodified scaffold; "
            "write real assertions before promoting"
        )
    else:
        failures.extend(_run_test(root, tool_id, test))
    for dependency in entry["requires"]:
        dependency_entry = tools.get(dependency)
        if (
            isinstance(dependency_entry, dict)
            and registry.effective(dependency_entry)["stage"] == "draft"
        ):
            failures.append(
                f"{tool_id}: stable tool requires draft {dependency!r}"
            )
    failures.extend(portability_findings(root, tool_id, tool))
    return failures, _origin_drift(tool_id, entry, tool)


def _run_test(root: Path, tool_id: str, test: Path) -> list[str]:
    try:
        completed = subprocess.run(
            [os.fspath(test)],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=TEST_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return [
            f"{tool_id}: tools/{tool_id}.test did not finish within "
            f"{TEST_TIMEOUT_SECONDS}s"
        ]
    except OSError as error:
        return [f"{tool_id}: tools/{tool_id}.test could not run: {error}"]
    if completed.returncode != 0:
        return [
            f"{tool_id}: tools/{tool_id}.test exited {completed.returncode}"
        ]
    return []


def _origin_drift(
    tool_id: str, entry: dict[str, Any], tool: Path
) -> list[str]:
    origin = entry["origin"]
    if not isinstance(origin, dict):
        return []
    source = Path(origin["repo"]) / "tools" / tool_id
    try:
        source_sha256 = sha256_file(source)
    except OSError:
        return []
    if source_sha256 != sha256_file(tool):
        return [
            f"{tool_id}: vendored copy differs from {origin['repo']} "
            "(sha256 drift); re-vendor deliberately to update"
        ]
    return []
