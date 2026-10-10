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


def keys(**found):
    return lambda provider: found.get(provider)


def test_claude_key_works():
    results = checks.check_cloud(Settings(), keys(anthropic="sk-test"), fake_factory())
    assert [r.name for r in results] == ["cloud: sonnet", "cloud: opus"]
    assert all(r.status is Status.PASS for r in results) and "Opus 5.5" in results[0].detail


def test_claude_no_key():
    results = checks.check_cloud(Settings(), keys(), fake_factory())
    assert results[0].status is Status.FAIL and "anthropic API key" in results[0].detail


@pytest.mark.parametrize(
    "cls,status,words",
    [(anthropic.AuthenticationError, 401, "rejected"), (anthropic.NotFoundError, 404, "not found")],
)
def test_claude_errors_are_explained(cls, status, words):
    factory = fake_factory(api_error(cls, status))
    r = checks.check_cloud(Settings(), keys(anthropic="sk-test"), factory)[0]
    assert r.status is Status.FAIL and words in r.detail


def test_other_providers_and_local_profiles():
    s = Settings.model_validate(
        {
            "routing": {"work": "gpt-sol", "expert": "big"},
            "models": {"big": {"provider": "ollama", "model": "qwen3.8:27b"}},
        }
    )
    gpt, big = checks.check_cloud(s, keys(openai="sk-o"), fake_factory())
    assert gpt.status is Status.PASS and "openai key found" in gpt.detail
    assert big.status is Status.PASS and "locally" in big.detail
    gpt, _ = checks.check_cloud(s, keys(), fake_factory())
    assert gpt.status is Status.FAIL


def test_keys_for_each_provider(paths, monkeypatch):
    from kit.credentials import cloud_api_key

    paths.ensure()
    for env in ("OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(env, raising=False)
    assert cloud_api_key(paths, "openai") is None
    (paths.secrets_dir / "openai_api_key").write_text("sk-o\n", encoding="utf-8")
    (paths.secrets_dir / "gemini_api_key").write_text("g-file\n", encoding="utf-8")
    assert cloud_api_key(paths, "openai") == "sk-o"
    assert cloud_api_key(paths, "google") == "g-file"
    monkeypatch.setenv("GOOGLE_API_KEY", "g-env")
    assert cloud_api_key(paths, "google") == "g-env"
    assert cloud_api_key(paths, "nobody") is None


def test_api_key_from_secrets_folder(paths):
    paths.ensure()
    assert anthropic_api_key(paths) is None
    (paths.secrets_dir / "anthropic_api_key").write_text("sk-file\n", encoding="utf-8")
    assert anthropic_api_key(paths) == "sk-file"


def test_api_key_env_wins(paths, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-env")
    assert anthropic_api_key(paths) == "sk-env"


# --- eyes ------------------------------------------------------------------


def test_eyes_check_passes_warns_or_skips():
    cams = [{"index": 0, "backend": "DSHOW", "width": 1280, "height": 720, "fps": 30.0}]
    r = checks.check_eyes(Settings(), lambda: cams)
    assert r.status is Status.PASS and r.detail == "[0] 1280x720 at 30 fps via DSHOW"
    r = checks.check_eyes(Settings.model_validate({"eyes": {"camera": 2}}), lambda: cams)
    assert r.status is Status.WARN and "camera 2 (eyes.camera) not found" in r.detail
    r = checks.check_eyes(Settings(), lambda: [])
    assert r.status is Status.WARN and "no camera on this machine" in r.detail

    def no_cv2():
        raise ImportError("No module named cv2")

    r = checks.check_eyes(Settings(), no_cv2)
    assert r.status is Status.WARN and 'pip install "kit[eyes]"' in r.detail

    def broken():
        raise RuntimeError("driver fell over")

    r = checks.check_eyes(Settings(), broken)
    assert r.status is Status.WARN and "driver fell over" in r.detail
    r = checks.check_eyes(Settings.model_validate({"eyes": {"enabled": False}}), lambda: cams)
    assert r.status is Status.SKIP
