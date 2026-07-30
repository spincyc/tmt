"""The tmt check gate battery: collect every failure, never stop early.

Draft gates apply to all tools, including the undeclared-composition gate
(a sibling tool id used in the body must be declared in ``requires``);
stable tools add the test (which must differ from the unmodified
scaffold), dependency-stage, portability, and origin-drift gates. Origin
drift is always a warning, and so is a ``lang`` the battery cannot lint:
the registry permits any lang, so a skipped syntax gate is disclosed
rather than failed. One repo-level gate: a tmt marker block present in
AGENTS.md must be current (see ``tmt.agentsmd``).
"""

from __future__ import annotations

import functools
import hashlib
import json
import os
import re
import selectors
import signal
import subprocess
import time
from pathlib import Path
from typing import Any

from tmt import agentsmd, paths, registry, scaffold
from tmt.registry import TmtError

HELP_TIMEOUT_SECONDS = 5
TEST_TIMEOUT_SECONDS = 60
LINT_TIMEOUT_SECONDS = 10
SHA256_MAX_BYTES = 64 * 1024 * 1024
CAPTURE_MAX_BYTES = 1024 * 1024
_COMPANION_SUFFIXES = (".md", ".test")
_READ_BLOCK_BYTES = 1024 * 1024


class _OutputTooLarge(OSError):
    """A child wrote past ``CAPTURE_MAX_BYTES`` on one stream.

    An ``OSError`` so that every ``except OSError`` already guarding a child
    process turns it into a collected failure rather than an exit-70 escape.
    """


def sha256_file(path: Path) -> str:
    """Hash a regular file, refusing anything unbounded (``/dev/zero``)."""
    if not path.is_file():
        raise OSError(f"{path} is not a regular file")
    digest = hashlib.sha256()
    read = 0
    with path.open("rb") as handle:
        while chunk := handle.read(_READ_BLOCK_BYTES):
            read += len(chunk)
            if read > SHA256_MAX_BYTES:
                raise OSError(
                    f"{path} exceeds the {SHA256_MAX_BYTES}-byte hash cap"
                )
            digest.update(chunk)
    return digest.hexdigest()


def _run(
    command: list[str], *, timeout: int, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    """Run ``command`` in its own session so a timeout kills descendants."""
    with subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    ) as process:
        try:
            stdout, stderr = _capture(process, timeout=timeout)
        except (subprocess.TimeoutExpired, _OutputTooLarge):
            _terminate_group(process)
            raise
    return subprocess.CompletedProcess(
        command, process.returncode, stdout, stderr
    )


def _capture(
    process: subprocess.Popen[bytes], *, timeout: int
) -> tuple[str, str]:
    """Drain both pipes under a byte cap as well as a deadline.

    ``communicate`` bounds only time, so a tool printing ``/dev/zero``
    exhausts memory long before the timeout can fire. The descriptors are
    read directly to keep the cap ahead of any buffering.
    """
    pipes = (("stdout", process.stdout), ("stderr", process.stderr))
    names = {pipe.fileno(): name for name, pipe in pipes if pipe is not None}
    buffers = {name: bytearray() for name in names.values()}
    deadline = time.monotonic() + timeout
    with selectors.DefaultSelector() as selector:
        for descriptor in names:
            selector.register(descriptor, selectors.EVENT_READ)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(process.args, timeout)
            for key, _ in selector.select(remaining):
                chunk = os.read(key.fd, _READ_BLOCK_BYTES)
                if not chunk:
                    selector.unregister(key.fd)
                    continue
                name = names[key.fd]
                buffers[name] += chunk
                if len(buffers[name]) > CAPTURE_MAX_BYTES:
                    raise _OutputTooLarge(
                        f"wrote more than {CAPTURE_MAX_BYTES} bytes "
                        f"to {name}"
                    )
    process.wait(timeout=max(deadline - time.monotonic(), 0))
    return (
        bytes(buffers.get("stdout", bytearray())).decode("utf-8", "replace"),
        bytes(buffers.get("stderr", bytearray())).decode("utf-8", "replace"),
    )


def _terminate_group(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except OSError:
        process.kill()
    try:
        process.communicate(timeout=HELP_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        pass


def capture_help(path: Path) -> tuple[bool, str]:
    """Run ``path --help``; return (ok, help output or failure detail)."""
    try:
        completed = _run(
            [os.fspath(path), "--help"], timeout=HELP_TIMEOUT_SECONDS
        )
    except subprocess.TimeoutExpired:
        return False, f"--help did not finish within {HELP_TIMEOUT_SECONDS}s"
    except _OutputTooLarge as error:
        return False, f"--help {error}"
    except OSError as error:
        return False, f"--help could not run: {error}"
    if completed.returncode != 0:
        return False, f"--help exited {completed.returncode}"
    return True, completed.stdout


def _read_body(tool: Path) -> str:
    try:
        return tool.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        raise TmtError("io-error", f"{tool}: {error}") from error


def portability_findings(root: Path, tool_id: str, tool: Path) -> list[str]:
    """Hardcoded-absolute-path findings in the tool body."""
    body = _read_body(tool)
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


@functools.lru_cache(maxsize=None)
def _word_pattern(word: str) -> re.Pattern[str]:
    """``word`` as a standalone-word matcher, compiled once.

    Cached because ``re``'s own cache holds 512 patterns: above that a
    registry rescans every (tool, sibling) pair through a fresh compile.
    """
    return re.compile(f"(?<![A-Za-z0-9_-]){re.escape(word)}(?![A-Za-z0-9_-])")


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
    except (OSError, UnicodeDecodeError):
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
        if _word_pattern(other).search(body):
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
    undeclared-composition gate, and the stable gates. Warnings — origin
    drift, and a ``lang`` with no syntax gate — are not failures and are
    not included: promotion runs exactly the failure battery, and
    ``tmt check`` remains where the skipped gates are disclosed.
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


def _load_for_checks(
    root: Path,
) -> tuple[dict[str, Any] | None, list[str]]:
    """The registry to check, or ``None`` plus registry-level failures."""
    path = root / registry.REGISTRY_FILENAME
    if not path.is_file():
        return None, [
            f"registry: {registry.REGISTRY_FILENAME} does not exist"
        ]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    # json.loads recurses once per nesting level, so a deeply nested
    # tmt.json overflows the stack: still a parse failure to collect, not
    # an internal error.
    except (json.JSONDecodeError, RecursionError, UnicodeDecodeError) as error:
        return None, [f"registry: tmt.json does not parse: {error}"]
    except OSError as error:
        return None, [f"registry: tmt.json cannot be read: {error}"]
    validation = registry.validate(data)
    if validation:
        return None, [f"registry: {message}" for message in validation]
    return data, []


def _gate_one(
    root: Path, tool_id: str, tools: dict[str, Any]
) -> tuple[list[str], list[str]]:
    """Every gate that applies to one tool at its declared stage."""
    failures: list[str] = []
    warnings: list[str] = []
    entry = registry.effective(tools[tool_id])
    tool = root / "tools" / tool_id
    if not tool.is_file():
        return (
            [f"{tool_id}: tools/{tool_id} missing for tmt.json entry"],
            warnings,
        )
    try:
        paths.resolve_within(root, tool, label=f"tools/{tool_id}")
    except TmtError as error:
        return [f"{tool_id}: {error}"], warnings
    warnings.extend(lang_warnings(tool_id, entry))
    try:
        failures.extend(_check_tool(tool_id, entry, tool))
        failures.extend(undeclared_composition(tool_id, entry, tool, tools))
        if entry["stage"] == "stable":
            stable_failures, stable_warnings = _check_stable(
                root, tool_id, entry, tool, tools
            )
            failures.extend(stable_failures)
            warnings.extend(stable_warnings)
    except TmtError as error:
        failures.append(f"{tool_id}: {error}")
    return failures, warnings


def run_tool_checks(
    root: Path, tool_id: str
) -> tuple[list[str], list[str]]:
    """Gate one tool only: its own gates and its own ``requires``.

    Repo-level gates (stray files, the AGENTS.md block) and other tools'
    gates are out of scope, so this never executes a tool the caller did
    not name — the point of scoping a check is not running the rest.
    """
    data, registry_failures = _load_for_checks(root)
    if data is None:
        return registry_failures, []
    tools: dict[str, Any] = data["tools"]
    if tool_id not in tools:
        raise TmtError(
            "not-found", f"tool {tool_id!r} is not registered in tmt.json"
        )
    failures, warnings = _gate_one(root, tool_id, tools)
    for dependency in registry.effective(tools[tool_id])["requires"]:
        if dependency not in tools:
            failures.append(
                f"{tool_id}: requires {dependency!r} which is not registered"
            )
    failures.extend(cycle_failures(tools, start=tool_id))
    return failures, warnings


def run_checks(root: Path) -> tuple[list[str], list[str]]:
    """Run the full battery; return (failures, warnings)."""
    warnings: list[str] = []
    data, registry_failures = _load_for_checks(root)
    if data is None:
        return registry_failures, warnings
    failures: list[str] = []
    failures.extend(agentsmd.check_failures(root))
    tools: dict[str, Any] = data["tools"]
    tools_dir = root / "tools"
    for name in sorted(_tool_files(tools_dir) - set(tools)):
        failures.append(f"tools/{name}: file has no tmt.json entry")
    for tool_id in sorted(tools):
        tool_failures, tool_warnings = _gate_one(root, tool_id, tools)
        failures.extend(tool_failures)
        warnings.extend(tool_warnings)
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


def _lint_python(tool_id: str, tool: Path) -> list[str]:
    try:
        compile(_read_body(tool), os.fspath(tool), "exec")
    except (SyntaxError, ValueError) as error:
        return [f"{tool_id}: python syntax error: {error}"]
    return []


def _lint_sh(tool_id: str, tool: Path) -> list[str]:
    try:
        lint = _run(
            ["sh", "-n", os.fspath(tool)], timeout=LINT_TIMEOUT_SECONDS
        )
    except subprocess.TimeoutExpired:
        return [
            f"{tool_id}: sh -n did not finish within "
            f"{LINT_TIMEOUT_SECONDS}s"
        ]
    except OSError as error:
        return [f"{tool_id}: sh -n could not run: {error}"]
    if lint.returncode != 0:
        detail = (lint.stderr.strip().splitlines() or ["sh -n failed"])[0]
        return [f"{tool_id}: sh syntax error: {detail}"]
    return []


# The one source of truth for which langs get a syntax gate: the dispatch
# table both runs the linters and names them in the skipped-gate warning.
_LINTERS = {"python": _lint_python, "sh": _lint_sh}


def lang_warnings(tool_id: str, entry: dict[str, Any]) -> list[str]:
    """Disclose a ``lang`` the battery has no syntax gate for.

    Never a failure: the registry permits any lang, so an escalated one
    stays usable — but ``ok`` alone would overstate what was verified.
    ``lang`` is repo-supplied, so ``repr`` keeps it on one printable line.
    """
    lang = entry["lang"]
    if lang in _LINTERS:
        return []
    gated = ", ".join(sorted(_LINTERS))
    return [
        f"{tool_id}: lang {lang!r} has no syntax gate; the body was not "
        f"linted (gated langs: {gated})"
    ]


def _check_tool(
    tool_id: str, entry: dict[str, Any], tool: Path
) -> list[str]:
    failures: list[str] = []
    linter = _LINTERS.get(entry["lang"])
    if linter is not None:
        failures.extend(linter(tool_id, tool))
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
    failures.extend(cycle_failures(tools))
    return failures


def cycle_failures(
    tools: dict[str, Any], *, start: str | None = None
) -> list[str]:
    """Cycles in the requires graph, or only those reachable from ``start``."""
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
    roots = sorted(graph) if start is None else [start]
    for root_node in roots:
        if root_node in state:
            continue
        # Iterative DFS: a pathological requires chain must not exhaust
        # the interpreter stack.
        stack: list[str] = [root_node]
        work: list[tuple[str, int]] = [(root_node, 0)]
        state[root_node] = 1
        while work:
            node, index = work[-1]
            if index < len(graph[node]):
                work[-1] = (node, index + 1)
                dependency = graph[node][index]
                if state.get(dependency) == 1:
                    cycle = [*stack[stack.index(dependency):], dependency]
                    failures.append("requires cycle: " + " -> ".join(cycle))
                elif dependency not in state:
                    state[dependency] = 1
                    stack.append(dependency)
                    work.append((dependency, 0))
                continue
            state[node] = 2
            stack.pop()
            work.pop()
    return failures


def _check_stable(
    root: Path,
    tool_id: str,
    entry: dict[str, Any],
    tool: Path,
    tools: dict[str, Any],
) -> tuple[list[str], list[str]]:
    failures = _check_test(
        root, tool_id, tool.with_name(f"{tool.name}.test")
    )
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


def _check_test(root: Path, tool_id: str, test: Path) -> list[str]:
    """Gate the stable test companion, containment first.

    The test is executed, so it is its resolved target that has to be
    inside the repository — containing the tools directory is not enough.
    A refusal is a collected failure line, never an escape from the
    battery.
    """
    if not test.is_file():
        return [f"{tool_id}: stable tool is missing tools/{tool_id}.test"]
    try:
        paths.resolve_within(root, test, label=f"tools/{tool_id}.test")
    except TmtError as error:
        return [f"{tool_id}: {error}"]
    if not os.access(test, os.X_OK):
        return [f"{tool_id}: executable bit not set on tools/{tool_id}.test"]
    if _read_body(test) == scaffold.render_test(tool_id):
        return [
            f"{tool_id}: tools/{tool_id}.test is the unmodified scaffold; "
            "write real assertions before promoting"
        ]
    return _run_test(root, tool_id, test)


def _run_test(root: Path, tool_id: str, test: Path) -> list[str]:
    try:
        completed = _run(
            [os.fspath(test)], cwd=root, timeout=TEST_TIMEOUT_SECONDS
        )
    except subprocess.TimeoutExpired:
        return [
            f"{tool_id}: tools/{tool_id}.test did not finish within "
            f"{TEST_TIMEOUT_SECONDS}s"
        ]
    except _OutputTooLarge as error:
        return [f"{tool_id}: tools/{tool_id}.test {error}"]
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
    # The source id, not the local one: a local rename must not silently
    # end drift reporting by pointing at a path that never existed upstream.
    source_id = origin.get("id") or tool_id
    source = Path(origin["repo"]) / "tools" / source_id
    try:
        source_sha256 = sha256_file(source)
        local_sha256 = sha256_file(tool)
    except OSError:
        return []
    # origin.sha256 is the content at vendoring time, so it is the merge
    # base: comparing only source-now against local-now cannot tell an
    # upstream change from the local fork this design sanctions, and would
    # advise re-vendoring — the one action that discards the fork.
    base_sha256 = origin["sha256"]
    local_moved = local_sha256 != base_sha256
    source_moved = source_sha256 != base_sha256
    if source_moved and local_moved:
        return [
            f"{tool_id}: both this copy and {origin['repo']} changed since "
            "vendoring; re-vendoring would discard the local changes"
        ]
    if source_moved:
        return [
            f"{tool_id}: {origin['repo']} has a newer version; re-vendor "
            "deliberately to take it"
        ]
    return []
