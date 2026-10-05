"""The ``kit`` command."""

from __future__ import annotations

import argparse
import shutil
from importlib import resources

import httpx

from kit import checks
from kit.checks import CheckResult, Status
from kit.credentials import anthropic_api_key
from kit.paths import KitPaths
from kit.settings import SettingsError, load_settings

CHECK_NAMES = ["data", "gpu", "ollama", "tailscale", "nas", "claude"]


def cmd_paths(paths: KitPaths) -> int:
    print(f"data folder:   {paths.root}")
    print(f"settings file: {paths.settings_file}")
    print(f"secrets:       {paths.secrets_dir}")
    print(f"state:         {paths.state_dir}")
    print(f"logs:          {paths.logs_dir}")
    return 0


def cmd_init(paths: KitPaths) -> int:
    paths.ensure()
    if paths.settings_file.exists():
        print(f"kept existing {paths.settings_file}")
    else:
        example = resources.files("kit").joinpath("settings.example.toml")
        with resources.as_file(example) as src:
            shutil.copyfile(src, paths.settings_file)
        print(f"wrote {paths.settings_file}; edit it to add your NAS shares")
    print(f"Kit's data folder is ready at {paths.root}")
    return 0


def run_checks(paths: KitPaths, skip: set[str]) -> list[CheckResult]:
    results: list[CheckResult] = []
    try:
        settings = load_settings(paths.settings_file)
    except SettingsError as e:
        return [CheckResult("settings", Status.FAIL, str(e))]
    if "data" not in skip:
        results.append(checks.check_data_dir(paths))
    if "gpu" not in skip:
        results.append(checks.check_gpu())
    if "ollama" not in skip:
        with httpx.Client() as client:
            results.append(checks.check_ollama(settings, client))
    if "tailscale" not in skip:
        results.append(checks.check_tailscale())
    if "nas" not in skip:
        results.extend(checks.check_nas(settings))
    if "claude" not in skip:
        results.append(checks.check_claude(settings, anthropic_api_key(paths)))
    return results


def print_report(results: list[CheckResult]) -> None:
    width = max(len(r.name) for r in results)
    for r in results:
        print(f"[{r.status.value}] {r.name.ljust(width)}  {r.detail}")
    failed = sum(r.status is Status.FAIL for r in results)
    print()
    print("All checks passed." if not failed else f"{failed} check(s) failed.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kit", description="Kit, your personal assistant.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("paths", help="show where Kit keeps its files")
    sub.add_parser("init", help="create Kit's data folder and a starter settings file")
    check = sub.add_parser("check", help="check this machine is ready to run Kit (stage 0)")
    check.add_argument(
        "--skip", action="append", default=[], choices=CHECK_NAMES, help="skip a check (repeatable)"
    )
    args = parser.parse_args(argv)

    paths = KitPaths.default()
    if args.command == "paths":
        return cmd_paths(paths)
    if args.command == "init":
        return cmd_init(paths)
    results = run_checks(paths, set(args.skip))
    print_report(results)
    return 1 if any(r.status is Status.FAIL for r in results) else 0
