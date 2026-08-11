"""Project test discovery + execution.

Reads `assurance-tests.json` from the project root (or falls back to
conventions), spawns a sibling container to run each test command, and
captures JUnit XML output. Tests run after scanners in the orchestrator.

Returned records feed into the Evidence layer via the JUnit parser.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from server.config import Settings


log = logging.getLogger(__name__)


# Container images used for convention-fallback test runs. Chosen to be
# small and standard. Override via env if a project needs something else.
_PYTEST_IMAGE = "python:3.12-alpine"
_NODE_IMAGE = "node:22-alpine"


@dataclass(frozen=True)
class TestSuite:
    """One declared test suite (entry in assurance-tests.json)."""

    id: str                          # short identifier
    type: str                        # unit-test | integration-test | e2e-test
    image: str                       # docker image to run inside
    command: tuple[str, ...]         # argv passed to the image
    working_dir: str                 # inside the container
    env: dict[str, str]
    junit_path: str | None           # path inside container where JUnit XML is written
    timeout: int                     # seconds


@dataclass(frozen=True)
class TestRunResult:
    """Outcome of running one TestSuite."""

    suite: TestSuite
    returncode: int
    junit_xml: bytes | None          # raw JUnit XML captured from junit_path
    stdout: bytes
    stderr: bytes

    @property
    def ok(self) -> bool:
        return self.returncode == 0


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def discover(project_root: Path) -> list[TestSuite]:
    """Find test declarations for a project.

    Reads `<project_root>/assurance-tests.json` if present. Otherwise
    probes for conventional pytest / package.json / Makefile setups and
    synthesises one TestSuite per discovery.
    """
    explicit = project_root / "assurance-tests.json"
    if explicit.exists():
        return _load_explicit(explicit)

    return _conventional_discovery(project_root)


def _load_explicit(path: Path) -> list[TestSuite]:
    """Parse an explicit assurance-tests.json declaration."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("could not parse %s: %s", path, exc)
        return []

    suites: list[TestSuite] = []
    for entry in doc.get("tests", []):
        suites.append(
            TestSuite(
                id=entry["id"],
                type=entry.get("type", "unit-test"),
                image=entry.get("image", _PYTEST_IMAGE),
                command=tuple(entry["command"]),
                working_dir=entry.get("working_dir", "/src"),
                env=dict(entry.get("env", {})),
                junit_path=entry.get("junit_path") or entry.get("result_path"),
                timeout=int(entry.get("timeout_seconds", 600)),
            )
        )
    return suites


def _conventional_discovery(project_root: Path) -> list[TestSuite]:
    """Probe for known test setups. Returns 0 or more synthesized suites."""
    suites: list[TestSuite] = []

    # pytest
    has_pytest = (
        (project_root / "pytest.ini").exists()
        or (project_root / "pyproject.toml").exists()
        or (project_root / "setup.py").exists()
        or any(project_root.glob("test_*.py"))
        or any(project_root.rglob("test_*.py"))
    )
    if has_pytest:
        # Build a pip-install prefix that picks up the project's declared
        # deps so tests can actually import what they need.
        install_parts = ["pip", "install", "--quiet", "pytest", "pytest-asyncio"]
        for req_file in ("requirements-server.txt", "requirements.txt"):
            if (project_root / req_file).exists():
                install_parts.extend(["-r", f"/src/{req_file}"])
                break

        # /work is a regular writable dir created at run time. /tmp is tmpfs
        # in some container setups and breaks pytest's JUnit writer.
        suites.append(
            TestSuite(
                id="pytest-convention",
                type="unit-test",
                image=_PYTEST_IMAGE,
                command=(
                    "sh", "-c",
                    "mkdir -p /work && "
                    + " ".join(install_parts)
                    + " > /dev/null 2>&1; "
                    "exec pytest --junit-xml=/work/junit.xml -p no:cacheprovider -q",
                ),
                working_dir="/src",
                env={"PYTHONDONTWRITEBYTECODE": "1"},
                junit_path="/work/junit.xml",
                timeout=600,
            )
        )

    # package.json scripts.test
    pkg = project_root / "package.json"
    if pkg.exists():
        try:
            pkg_doc = json.loads(pkg.read_text(encoding="utf-8"))
            scripts = pkg_doc.get("scripts", {})
            if "test" in scripts:
                suites.append(
                    TestSuite(
                        id="npm-test-convention",
                        type="unit-test",
                        image=_NODE_IMAGE,
                        command=("sh", "-c", "npm ci --quiet > /dev/null 2>&1; npm test -- --ci --reporter=json > /tmp/junit.json"),
                        working_dir="/src",
                        env={"CI": "true"},
                        junit_path=None,
                        timeout=600,
                    )
                )
        except (OSError, json.JSONDecodeError):
            pass

    return suites


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


async def run_suite(suite: TestSuite, project_path: str) -> TestRunResult:
    """Spawn a sibling container, run the test command, read JUnit XML out.

    Doesn't use --rm: tmpfs would be wiped on exit and we'd lose the JUnit
    file. Instead we let docker generate a name, run it, `docker cp` the
    JUnit file out, then `docker rm` the container.
    """
    container_name = f"assurance-test-{suite.id}-{asyncio.get_event_loop().time()}"
    argv: list[str] = [
        "docker", "run",
        "--name", container_name,
        "--label", "com.docker.compose.project=assurance-scan",
        "-v", f"{project_path}:/src:ro",
        "--tmpfs", "/tmp",
        "-w", suite.working_dir,
        "-v", f"{project_path}:/src-write",
    ]
    for k, v in suite.env.items():
        argv.extend(["-e", f"{k}={v}"])
    argv.extend([suite.image])
    argv.extend(suite.command)

    log.info("running test suite id=%s argv=%s", suite.id, " ".join(argv))
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    timed_out = False
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=suite.timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        stdout, stderr = b"", f"timeout after {suite.timeout}s".encode()
        timed_out = True

    # Extract JUnit XML via docker cp before removing the container.
    junit_xml: bytes | None = None
    if suite.junit_path and not timed_out:
        cp_proc = await asyncio.create_subprocess_exec(
            "docker", "cp", f"{container_name}:{suite.junit_path}", "-",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        cp_stdout, _ = await cp_proc.communicate()
        if cp_proc.returncode == 0 and cp_stdout:
            # `docker cp SRC -` returns a tar archive; extract the single file.
            junit_xml = _extract_first_file_from_tar(cp_stdout)

    # Always clean up the container (whether the tests passed or not).
    rm_proc = await asyncio.create_subprocess_exec(
        "docker", "rm", "-f", container_name,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await rm_proc.wait()

    returncode = proc.returncode if proc.returncode is not None else -1
    if timed_out:
        returncode = 124
    return TestRunResult(
        suite=suite,
        returncode=returncode,
        junit_xml=junit_xml,
        stdout=stdout or b"",
        stderr=stderr or b"",
    )


def _extract_first_file_from_tar(tar_bytes: bytes) -> bytes | None:
    """`docker cp SRC -` returns a tar archive; pull the first file payload."""
    import io
    import tarfile
    try:
        with tarfile.open(fileobj=io.BytesIO(tar_bytes)) as tf:
            for member in tf.getmembers():
                if member.isfile():
                    return tf.extractfile(member).read()
    except (tarfile.TarError, OSError) as exc:
        log.warning("could not extract JUnit XML from docker cp output: %s", exc)
        return None
    return None
