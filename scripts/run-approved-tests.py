#!/usr/bin/env python3
"""Run ready-to-run ASVS assurance tests and emit scanner-readable JUnit XML."""
from __future__ import annotations

import argparse
import json
import re
import shlex
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception as exc:
        raise SystemExit(f"failed to read JSON {path}: {exc}") from exc


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


DEFAULT_TEST_ADAPTER = {
    "language": "javascript",
    "framework": "jest",
    "container_image": "node:20",
    "result_format": "junit",
    "command_template": "{runner} {config_flag} --runTestsByPath {test_file} --runInBand --no-cache",
    "config_path": "tests/asvs/jest.config.js",
}


def normalise_test_adapter(manifest: dict) -> dict:
    adapter = dict(DEFAULT_TEST_ADAPTER)
    adapter.update(manifest.get("test_adapter") or {})
    return adapter


def adapter_framework(adapter: dict) -> str:
    return str(adapter.get("framework") or "").lower()


def adapter_container_image(adapter: dict, override: str | None = None) -> str:
    return override or str(adapter.get("container_image") or DEFAULT_TEST_ADAPTER["container_image"])


def adapter_config_path(source_repo: Path, adapter: dict, explicit: Path | None = None) -> Path | None:
    if explicit:
        return explicit
    config_path = str(adapter.get("config_path") or "").strip()
    if not config_path:
        return None
    path = Path(config_path)
    return path if path.is_absolute() else source_repo / path


def find_pytest(source_repo: Path, explicit: str | None = None) -> Path:
    candidates = [Path(explicit)] if explicit else []
    candidates.extend([
        source_repo / ".venv" / "bin" / "pytest",
        source_repo / "venv" / "bin" / "pytest",
    ])
    for candidate in candidates:
        if candidate.exists():
            return candidate
    resolved = shutil.which("pytest")
    if resolved:
        return Path(resolved)
    raise SystemExit("could not find pytest binary; pass --pytest-bin or --runner-bin")


def build_adapter_command(
    source_repo: Path,
    adapter: dict,
    rel_path: str,
    *,
    explicit_runner: str | None = None,
    explicit_config: Path | None = None,
) -> tuple[list[str], Path | None, Path | None]:
    framework = adapter_framework(adapter)
    if framework in {"jest", "vitest"}:
        runner = find_jest(source_repo, explicit_runner or adapter.get("runner_path"))
        config = adapter_config_path(source_repo, adapter, explicit_config)
        config_flag = f"--config {shell_quote(str(config))}" if config and config.exists() else ""
        template = str(adapter.get("command_template") or DEFAULT_TEST_ADAPTER["command_template"])
    elif framework == "pytest":
        runner = find_pytest(source_repo, explicit_runner or adapter.get("runner_path"))
        config = adapter_config_path(source_repo, adapter, explicit_config)
        config_flag = f"-c {shell_quote(str(config))}" if config and config.exists() else ""
        template = str(adapter.get("command_template") or "{runner} {config_flag} {test_file}")
    else:
        raise SystemExit(
            f"test adapter framework '{framework or 'unknown'}' is not supported by run-approved-tests yet; "
            "add an adapter runner implementation before executing these tests"
        )
    command_text = template.format(
        runner=shell_quote(str(runner)),
        config=shell_quote(str(config)) if config else "",
        config_flag=config_flag,
        test_file=shell_quote(rel_path),
        source_repo=shell_quote(str(source_repo)),
    )
    return shlex.split(command_text), runner, config


def infer_source_repo(report_dir: Path) -> Path:
    match = re.match(r"^(.*)/([^/]+)-assurance-scan-[^/]+/\.assurance-scan/runtime/reports/[^/]+/?$", str(report_dir))
    if not match:
        raise SystemExit("could not infer source repository; pass --source-repo")
    return Path(match.group(1)) / match.group(2)


def selected_tests(manifest: dict, tbts: list[str], *, allow_reviewed_existing_asvs: bool = False) -> list[dict]:
    tests = manifest.get("tests") or []
    wanted = set(tbts)
    out = []
    for item in tests:
        if item.get("tbt") not in wanted:
            continue
        is_ready = item.get("status") == "ready_to_run" and item.get("safety") == "non_destructive"
        is_reviewed_existing_asvs = (
            allow_reviewed_existing_asvs
            and item.get("source") == "existing_asvs"
            and item.get("status") == "existing"
            and item.get("safety") == "review_required"
        )
        if is_ready or is_reviewed_existing_asvs:
            out.append(item)
    missing = sorted(wanted - {item.get("tbt") for item in out})
    if missing:
        expected = "ready_to_run/non_destructive"
        if allow_reviewed_existing_asvs:
            expected += " or reviewed existing_asvs"
        raise SystemExit(
            f"selected TBTs are not {expected} in the assurance test pack: "
            + ", ".join(missing)
        )
    return out


def find_jest(source_repo: Path, explicit: str | None = None) -> Path:
    candidates = [Path(explicit)] if explicit else []
    candidates.extend([
        source_repo / "services" / "tapestry-backend" / "node_modules" / ".bin" / "jest",
        source_repo / "node_modules" / ".bin" / "jest",
    ])
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise SystemExit("could not find Jest binary; pass --jest-bin")


def junit_tree(results: list[dict]) -> ET.ElementTree:
    total = len(results)
    failures = sum(1 for item in results if item["status"] == "failed")
    skipped = sum(1 for item in results if item["status"] == "skipped")
    testsuites = ET.Element("testsuites", {
        "tests": str(total),
        "failures": str(failures),
        "errors": "0",
        "skipped": str(skipped),
    })
    suite = ET.SubElement(testsuites, "testsuite", {
        "name": "ASVS approved assurance tests",
        "tests": str(total),
        "failures": str(failures),
        "errors": "0",
        "skipped": str(skipped),
    })
    for result in results:
        classname = ".".join([result["tbt"], *result.get("frs", []), result["scope_slug"]])
        case = ET.SubElement(suite, "testcase", {
            "classname": classname,
            "name": result["tbt"],
            "file": result["path"],
            "time": f"{result['seconds']:.3f}",
        })
        if result["status"] == "failed":
            failure = ET.SubElement(case, "failure", {"message": result["message"][:500] or "approved assurance test failed"})
            failure.text = result["output"][-8000:]
        elif result["status"] == "skipped":
            skipped = ET.SubElement(case, "skipped", {"message": result["message"][:500] or "approved assurance test skipped"})
            skipped.text = result["output"][-4000:]
    return ET.ElementTree(testsuites)


def write_junit(path: Path, results: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tree = junit_tree(results)
    ET.indent(tree, space="  ")
    xml_body = ET.tostring(tree.getroot(), encoding="unicode")
    path.write_text('<?xml version="1.0" encoding="UTF-8"?>\n' + xml_body + '\n')


def container_mount_root(path: Path) -> Path:
    parts = path.resolve().parts
    if len(parts) >= 4 and parts[1] == "Users":
        return Path(*parts[:4])
    return path.resolve().parent


def docker_available() -> bool:
    return Path("/var/run/docker.sock").exists()


def docker_adapter_command(source_repo: Path, adapter_cmd: list[str], adapter_paths: list[Path | None], image: str) -> list[str]:
    mounts = [container_mount_root(source_repo)]
    for candidate in adapter_paths:
        if candidate:
            root = container_mount_root(candidate)
            if root not in mounts:
                mounts.append(root)
    cmd = [
        "docker", "run", "--rm",
        "--label", "com.docker.compose.project=assurance-scan",
        "--label", "com.docker.compose.service=approved-tests",
    ]
    for mount in mounts:
        cmd.extend(["-v", f"{mount}:{mount}"])
    cmd.extend(["-w", str(source_repo), image])
    cmd.extend(adapter_cmd)
    return cmd


def should_use_docker(mode: str) -> bool:
    if mode == "docker":
        return True
    if mode == "host":
        return False
    return docker_available()


def run_one(
    source_repo: Path,
    adapter: dict,
    item: dict,
    timeout: int,
    execution_mode: str,
    test_container_image: str | None,
    explicit_runner: str | None = None,
    explicit_config: Path | None = None,
) -> dict:
    rel_path = item.get("pack_path") or item.get("manual_test_path") or ""
    test_path = source_repo / rel_path
    tbt = item.get("tbt") or item.get("pack_id") or "TBT-UNKNOWN"
    frs = item.get("frs") or []
    scope = item.get("title") or item.get("rationale") or tbt
    scope_slug = re.sub(r"[^A-Za-z0-9]+", "-", scope).strip("-")[:80] or "approved-scope"
    if not test_path.exists():
        return {
            "tbt": tbt,
            "frs": frs,
            "path": rel_path,
            "scope_slug": scope_slug,
            "status": "skipped",
            "seconds": 0.0,
            "message": f"test file not found: {rel_path}",
            "output": "",
        }
    text = test_path.read_text(errors="ignore")
    if re.search(r"\bdescribe\.skip\b|\btest\.skip\b|pytest\.mark\.skip\b|TODO\(review-required\)|review-required scaffold", text):
        return {
            "tbt": tbt,
            "frs": frs,
            "path": rel_path,
            "scope_slug": scope_slug,
            "status": "skipped",
            "seconds": 0.0,
            "message": "test still appears to be a review scaffold or skipped draft",
            "output": "",
        }

    adapter_cmd, runner_path, config_path = build_adapter_command(
        source_repo,
        adapter,
        rel_path,
        explicit_runner=explicit_runner,
        explicit_config=explicit_config,
    )
    use_docker = should_use_docker(execution_mode)
    image = adapter_container_image(adapter, test_container_image)
    cmd = docker_adapter_command(source_repo, adapter_cmd, [runner_path, config_path], image) if use_docker else adapter_cmd
    started = time.monotonic()
    proc = subprocess.run(
        cmd,
        cwd=source_repo if not use_docker else None,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )
    seconds = time.monotonic() - started
    output = proc.stdout or ""
    return {
        "tbt": tbt,
        "frs": frs,
        "path": rel_path,
        "scope_slug": scope_slug,
        "status": "passed" if proc.returncode == 0 else "failed",
        "seconds": seconds,
        "message": "" if proc.returncode == 0 else f"{adapter.get('framework', 'test adapter')} exited {proc.returncode}",
        "output": output,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report_dir", type=Path)
    parser.add_argument("--source-repo", type=Path)
    parser.add_argument("--tbt", action="append", required=True)
    parser.add_argument("--junit-out", type=Path)
    parser.add_argument("--runner-bin", help="Override the executable selected by the manifest test_adapter.")
    parser.add_argument("--jest-bin", help="Deprecated alias for --runner-bin when using the Jest adapter.")
    parser.add_argument("--pytest-bin", help="Deprecated alias for --runner-bin when using the pytest adapter.")
    parser.add_argument("--jest-config", type=Path, help="Adapter config override. Kept for compatibility with existing Jest commands.")
    parser.add_argument("--execution-mode", choices=["auto", "host", "docker"], default="auto")
    parser.add_argument("--test-container-image", default=None, help="Override the manifest test_adapter.container_image.")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument(
        "--fail-on-test-failure",
        action="store_true",
        help="Exit non-zero when executed tests fail or skip. By default, failed/skipped tests are written as observed JUnit evidence and the workflow continues so evidence can be imported.",
    )
    parser.add_argument(
        "--allow-reviewed-existing-asvs",
        action="store_true",
        help="Allow explicitly selected existing tests/asvs files that are still marked review_required in the manifest. Use only after human approval in the board.",
    )
    args = parser.parse_args()

    report_dir = args.report_dir.resolve()
    source_repo = (args.source_repo or infer_source_repo(report_dir)).resolve()
    manifest_path = report_dir / "generated-tests" / "VG_TEST_FRAMEWORK" / "manifest.json"
    manifest = load_json(manifest_path)
    tests = selected_tests(manifest, args.tbt, allow_reviewed_existing_asvs=args.allow_reviewed_existing_asvs)
    adapter = normalise_test_adapter(manifest)
    junit_out = args.junit_out or (report_dir / "generated-tests" / "VG_TEST_FRAMEWORK" / "results" / "approved-tbt-junit.xml")

    framework = adapter_framework(adapter)
    explicit_runner = args.runner_bin
    if not explicit_runner and framework in {"jest", "vitest"}:
        explicit_runner = args.jest_bin
    if not explicit_runner and framework == "pytest":
        explicit_runner = args.pytest_bin
    results = [
        run_one(
            source_repo,
            adapter,
            item,
            args.timeout,
            args.execution_mode,
            args.test_container_image,
            explicit_runner=explicit_runner,
            explicit_config=args.jest_config,
        )
        for item in tests
    ]
    write_junit(junit_out, results)

    passed = sum(1 for item in results if item["status"] == "passed")
    failed = sum(1 for item in results if item["status"] == "failed")
    skipped = sum(1 for item in results if item["status"] == "skipped")
    print(f"approved tests: passed={passed} failed={failed} skipped={skipped}")
    print(f"junit: {junit_out}")
    for item in results:
        print(f"- {item['tbt']}: {item['status']} ({item['path']})")
        if item["message"]:
            print(f"  {item['message']}")
    parent_mount = str(source_repo.parent)
    catalog = report_dir / "fr-catalog.snapshot.json"
    print("")
    print("Import observed results with:")
    print("docker run --rm -it \\")
    print("  -e ASSURANCE_SCAN_IMAGE_BUILD_PARALLELISM=2 \\")
    print("  -e ASSURANCE_SCAN_PARALLELISM=4 \\")
    print("  -v /var/run/docker.sock:/var/run/docker.sock \\")
    print(f"  -v {shell_quote(parent_mount)}:{shell_quote(parent_mount)} \\")
    print(f"  -w {shell_quote(str(source_repo))} \\")
    print(f"  assurance-scan:local scan {shell_quote(str(source_repo))} \\")
    print(f"  --fr-catalog {shell_quote(str(catalog))} \\")
    print(f"  --junit-xml {shell_quote(str(junit_out))}")
    if failed or skipped:
        print("observed test failures/skips were written to JUnit; continuing so evidence can be imported")
    return 1 if args.fail_on_test_failure and (failed or skipped) else 0


if __name__ == "__main__":
    raise SystemExit(main())
