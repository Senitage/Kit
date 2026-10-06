"""Stage 0 setup checks: is this machine ready to run Kit?

Each check returns a CheckResult and never raises, so ``kit check`` always
prints a full report. Outside effects (commands, HTTP, file writes, the
Anthropic client) are passed in, so every check is testable with fakes.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import anthropic
import httpx

from kit.paths import KitPaths
from kit.settings import Settings

Runner = Callable[[list[str]], subprocess.CompletedProcess]
WRITE_TEST_NAME = ".kit-write-test"


class Status(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    SKIP = "SKIP"


@dataclass
class CheckResult:
    name: str
    status: Status
    detail: str


def run_command(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)


def check_data_dir(paths: KitPaths) -> CheckResult:
    missing = [d for d in paths.all_dirs() if not d.is_dir()]
    if missing:
        return CheckResult(
            "data folder", Status.FAIL, f"{paths.root} is not set up; run `kit init`"
        )
    probe = paths.state_dir / WRITE_TEST_NAME
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as e:
        return CheckResult("data folder", Status.FAIL, f"can't write to {paths.state_dir}: {e}")
    return CheckResult("data folder", Status.PASS, str(paths.root))


def check_gpu(run: Runner = run_command) -> CheckResult:
    try:
        result = run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"])
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return CheckResult("gpu", Status.FAIL, f"nvidia-smi didn't run ({e}); install the driver")
    if result.returncode != 0 or not result.stdout.strip():
        return CheckResult("gpu", Status.FAIL, f"nvidia-smi failed: {result.stderr.strip()}")
    return CheckResult("gpu", Status.PASS, result.stdout.strip().splitlines()[0])


def _model_installed(wanted: str, installed: list[str]) -> bool:
    if ":" not in wanted:
        wanted = f"{wanted}:latest"
    return wanted in installed


def check_ollama(settings: Settings, client: httpx.Client) -> CheckResult:
    base, model = settings.ollama.url, settings.ollama.model
    try:
        tags = client.get(f"{base}/api/tags", timeout=10).raise_for_status().json()
    except httpx.HTTPError as e:
        return CheckResult("ollama", Status.FAIL, f"can't reach Ollama at {base}: {e}")
    installed = [m.get("name", "") for m in tags.get("models", [])]
    if not _model_installed(model, installed):
        detail = f"model {model} not pulled; run `ollama pull {model}`"
        return CheckResult("ollama", Status.FAIL, detail)
    try:
        reply = (
            client.post(
                f"{base}/api/generate",
                json={
                    "model": model,
                    "prompt": "Reply with the single word: ready",
                    "stream": False,
                },
                timeout=300,
            )
            .raise_for_status()
            .json()
        )
    except httpx.HTTPError as e:
        return CheckResult("ollama", Status.FAIL, f"{model} didn't answer: {e}")
    tokens, ns = reply.get("eval_count", 0), reply.get("eval_duration", 0)
    speed = f", {tokens / (ns / 1e9):.0f} tokens/s" if tokens and ns else ""
    on_gpu = _loaded_on_gpu(client, base, model)
    if on_gpu is False:
        detail = f"{model} answered{speed}, but it's running on the CPU, not the GPU"
        return CheckResult("ollama", Status.WARN, detail)
    return CheckResult("ollama", Status.PASS, f"{model} answered{speed}")


def _loaded_on_gpu(client: httpx.Client, base: str, model: str) -> bool | None:
    """True/False from Ollama's running-models list; None if it can't tell."""
    try:
        running = client.get(f"{base}/api/ps", timeout=10).raise_for_status().json()
    except httpx.HTTPError:
        return None
    for m in running.get("models", []):
        if m.get("name") == model or m.get("model") == model:
            return m.get("size_vram", 0) > 0
    return None


def check_tailscale(run: Runner = run_command) -> CheckResult:
    try:
        result = run(["tailscale", "status", "--json"])
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return CheckResult("tailscale", Status.FAIL, f"tailscale didn't run ({e}); install it")
    try:
        status = json.loads(result.stdout)
    except json.JSONDecodeError:
        return CheckResult("tailscale", Status.FAIL, f"unexpected output: {result.stderr.strip()}")
    state = status.get("BackendState")
    if state != "Running":
        detail = f"Tailscale is {state}; sign in with `tailscale up`"
        return CheckResult("tailscale", Status.FAIL, detail)
    me = status.get("Self", {})
    addresses = ", ".join(me.get("TailscaleIPs", []))
    return CheckResult("tailscale", Status.PASS, f"{me.get('HostName', '?')} at {addresses}")


def try_write(folder: Path) -> OSError | None:
    """Create and delete a tiny test file. Returns the error, or None if writing worked."""
    probe = folder / WRITE_TEST_NAME
    try:
        with probe.open("x", encoding="utf-8") as f:
            f.write("kit write test")
    except OSError as e:
        return e
    try:
        probe.unlink()
    except OSError:
        pass
    return None


Writer = Callable[[Path], OSError | None]


def check_nas(settings: Settings, write: Writer = try_write) -> list[CheckResult]:
    nas = settings.nas
    if not nas.read_only_shares and not nas.vault:
        return [CheckResult("nas", Status.SKIP, "no shares in settings.toml yet")]
    results = []
    for name, location in nas.read_only_shares.items():
        label, folder = f"nas: {name}", Path(location)
        if not folder.is_dir():
            results.append(CheckResult(label, Status.FAIL, f"can't open {location}"))
            continue
        if write(folder) is None:
            detail = f"Kit can write to {location}; make it read-only for the kit user"
            results.append(CheckResult(label, Status.FAIL, detail))
        else:
            results.append(CheckResult(label, Status.PASS, f"{location} is readable and read-only"))
    if nas.vault:
        folder = Path(nas.vault)
        if not folder.is_dir():
            results.append(CheckResult("nas: vault", Status.FAIL, f"can't open {nas.vault}"))
        elif (error := write(folder)) is not None:
            detail = f"can't write to {nas.vault}: {error}"
            results.append(CheckResult("nas: vault", Status.FAIL, detail))
        else:
            results.append(CheckResult("nas: vault", Status.PASS, f"{nas.vault} is writable"))
    return results


ClientFactory = Callable[[str], anthropic.Anthropic]


def make_anthropic_client(api_key: str) -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=api_key)


def check_claude(
    settings: Settings, api_key: str | None, make_client: ClientFactory = make_anthropic_client
) -> CheckResult:
    """Checks the key and model with a free model lookup; no tokens are spent."""
    if not api_key:
        return CheckResult("claude", Status.FAIL, "no API key; see docs/stage-0-setup.md")
    model = settings.claude.model
    try:
        info = make_client(api_key).models.retrieve(model)
    except anthropic.AuthenticationError:
        return CheckResult("claude", Status.FAIL, "the API key was rejected")
    except anthropic.NotFoundError:
        return CheckResult("claude", Status.FAIL, f"model {model} not found for this key")
    except anthropic.APIConnectionError as e:
        return CheckResult("claude", Status.FAIL, f"can't reach the Claude API: {e}")
    except anthropic.APIStatusError as e:
        return CheckResult("claude", Status.FAIL, f"Claude API error {e.status_code}: {e.message}")
    return CheckResult("claude", Status.PASS, f"key works; {info.display_name} is available")
