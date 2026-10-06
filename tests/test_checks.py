import json
import subprocess

import anthropic
import httpx
import pytest

from kit import checks
from kit.checks import Status
from kit.credentials import anthropic_api_key
from kit.settings import NasSettings, Settings


def fake_run(stdout="", returncode=0, stderr=""):
    def run(cmd):
        return subprocess.CompletedProcess(cmd, returncode, stdout, stderr)

    return run


def missing_command(cmd):
    raise FileNotFoundError(cmd[0])


# --- gpu -------------------------------------------------------------------


def test_gpu_found():
    r = checks.check_gpu(fake_run("NVIDIA GeForce RTX 2070 SUPER, 8192 MiB\n"))
    assert r.status is Status.PASS and "2070" in r.detail


def test_gpu_driver_missing():
    assert checks.check_gpu(missing_command).status is Status.FAIL


# --- ollama ----------------------------------------------------------------


def ollama_client(models, generate=None, ps=None):
    def handler(request):
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": m} for m in models]})
        if request.url.path == "/api/generate":
            return httpx.Response(200, json=generate or {"response": "ready"})
        if request.url.path == "/api/ps":
            return httpx.Response(200, json=ps or {"models": []})
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_ollama_answers_on_gpu():
    client = ollama_client(
        ["qwen3:8b"],
        generate={"response": "ready", "eval_count": 60, "eval_duration": 1_000_000_000},
        ps={"models": [{"name": "qwen3:8b", "size_vram": 5_000_000_000}]},
    )
    r = checks.check_ollama(Settings(), client)
    assert r.status is Status.PASS and "60 tokens/s" in r.detail


def test_ollama_on_cpu_is_a_warning():
    client = ollama_client(["qwen3:8b"], ps={"models": [{"name": "qwen3:8b", "size_vram": 0}]})
    assert checks.check_ollama(Settings(), client).status is Status.WARN


def test_ollama_model_not_pulled():
    r = checks.check_ollama(Settings(), ollama_client(["llama3.1:8b"]))
    assert r.status is Status.FAIL and "ollama pull qwen3:8b" in r.detail


def test_ollama_latest_tag_matches_bare_name():
    settings = Settings.model_validate({"ollama": {"model": "mistral"}})
    assert checks.check_ollama(settings, ollama_client(["mistral:latest"])).status is Status.PASS


def test_ollama_unreachable():
    def refuse(request):
        raise httpx.ConnectError("refused")

    client = httpx.Client(transport=httpx.MockTransport(refuse))
    assert checks.check_ollama(Settings(), client).status is Status.FAIL


# --- tailscale -------------------------------------------------------------


def test_tailscale_running():
    me = {"HostName": "kit-server", "TailscaleIPs": ["100.1.2.3"]}
    status = {"BackendState": "Running", "Self": me}
    r = checks.check_tailscale(fake_run(json.dumps(status)))
    assert r.status is Status.PASS and "kit-server" in r.detail


def test_tailscale_logged_out():
    r = checks.check_tailscale(fake_run(json.dumps({"BackendState": "NeedsLogin"})))
    assert r.status is Status.FAIL


def test_tailscale_not_installed():
    assert checks.check_tailscale(missing_command).status is Status.FAIL


# --- nas -------------------------------------------------------------------


def nas_settings(shares=None, vault=None):
    return Settings(nas=NasSettings(read_only_shares=shares or {}, vault=vault))


def refused(folder):
    return PermissionError("read-only")


def test_nas_not_configured_is_skipped():
    assert checks.check_nas(Settings())[0].status is Status.SKIP


def test_read_only_share_passes(tmp_path):
    r = checks.check_nas(nas_settings({"photos": str(tmp_path)}), write=refused)
    assert [x.status for x in r] == [Status.PASS]


def test_writable_share_fails(tmp_path):
    r = checks.check_nas(nas_settings({"photos": str(tmp_path)}))
    assert r[0].status is Status.FAIL and "read-only" in r[0].detail
    assert not (tmp_path / checks.WRITE_TEST_NAME).exists()


def test_missing_share_fails(tmp_path):
    r = checks.check_nas(nas_settings({"photos": str(tmp_path / "gone")}))
    assert r[0].status is Status.FAIL


def test_vault_must_be_writable(tmp_path):
    assert checks.check_nas(nas_settings(vault=str(tmp_path)))[0].status is Status.PASS
    blocked = checks.check_nas(nas_settings(vault=str(tmp_path)), write=refused)
    assert blocked[0].status is Status.FAIL


# --- claude ----------------------------------------------------------------


class FakeModels:
    def __init__(self, error=None):
        self.error = error

    def retrieve(self, model):
        if self.error:
            raise self.error
        return type("Model", (), {"display_name": "Claude Opus 5.5"})()


def fake_factory(error=None):
    return lambda key: type("Client", (), {"models": FakeModels(error)})()


def api_error(cls, status):
    request = httpx.Request("GET", "https://api.anthropic.com/v1/models/x")
    return cls("nope", response=httpx.Response(status, request=request), body=None)


def test_claude_key_works():
    r = checks.check_claude(Settings(), "sk-test", fake_factory())
    assert r.status is Status.PASS and "Opus 5.5" in r.detail


def test_claude_no_key():
    assert checks.check_claude(Settings(), None, fake_factory()).status is Status.FAIL


@pytest.mark.parametrize(
    "cls,status,words",
    [(anthropic.AuthenticationError, 401, "rejected"), (anthropic.NotFoundError, 404, "not found")],
)
def test_claude_errors_are_explained(cls, status, words):
    r = checks.check_claude(Settings(), "sk-test", fake_factory(api_error(cls, status)))
    assert r.status is Status.FAIL and words in r.detail


def test_api_key_from_secrets_folder(paths):
    paths.ensure()
    assert anthropic_api_key(paths) is None
    (paths.secrets_dir / "anthropic_api_key").write_text("sk-file\n", encoding="utf-8")
    assert anthropic_api_key(paths) == "sk-file"


def test_api_key_env_wins(paths, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-env")
    assert anthropic_api_key(paths) == "sk-env"
