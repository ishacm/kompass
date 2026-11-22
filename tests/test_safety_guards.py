"""No secrets in the repo, no paid usage by accident."""
import subprocess
import sys

import pytest

from kompass import llm
from kompass.db import ROOT

sys.path.insert(0, str(ROOT / "scripts"))
import check_secrets  # noqa: E402

# fake keys are built at runtime so this file itself never contains a key-shaped string
FAKES = {
    "Anthropic key": "sk-" + "ant-" + "a1" * 20,
    "Groq key": "gsk" + "_" + "b2" * 20,
    "Google API key": "AI" + "za" + "c3" * 18,
    "Slack token": "xo" + "xb-" + "1234567890-abcdefghij",
    "Private key": "-----BEGIN " + "RSA PRIVATE KEY-----",
}


@pytest.mark.parametrize("name,value", FAKES.items())
def test_scanner_catches_keys(tmp_path, name, value):
    f = tmp_path / "leak.py"
    f.write_text(f'KEY = "{value}"\n')
    hits = check_secrets.scan([str(f)])
    assert hits and any(name in h or "Hard-coded" in h for h in hits)


def test_scanner_blocks_env_and_db_files(tmp_path):
    for name in (".env", ".env.local", "data/kompass.duckdb", "id_rsa"):
        assert check_secrets.FORBIDDEN_FILES.search(name)
    assert not check_secrets.FORBIDDEN_FILES.search(".env.example") or ".env.example" in check_secrets.ALLOWED_FILES


def test_repository_is_clean_right_now():
    out = subprocess.run([sys.executable, "scripts/check_secrets.py", "--all"], cwd=ROOT,
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stdout


def test_paid_provider_refused_by_default(monkeypatch):
    monkeypatch.setenv("KOMPASS_LLM", "live")
    monkeypatch.setenv("KOMPASS_PROVIDER", "anthropic")
    monkeypatch.delenv("KOMPASS_ALLOW_PAID", raising=False)
    with pytest.raises(llm.PaidProviderError):
        llm.complete_json("x", purpose="segment_classify")


def test_paid_provider_needs_explicit_opt_in(monkeypatch):
    monkeypatch.setenv("KOMPASS_ALLOW_PAID", "true")
    llm.check_cost(llm.provider("anthropic"))          # no exception once deliberately allowed


def test_default_and_free_providers_are_not_paid():
    assert not llm.provider().get("paid")
    for pid in ("groq", "gemini", "ollama"):
        assert not llm.provider(pid).get("paid")


def test_aeo_skips_paid_providers(monkeypatch):
    from kompass.aeo import run as aeo
    monkeypatch.setenv("KOMPASS_LLM", "live")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.delenv("KOMPASS_ALLOW_PAID", raising=False)
    use, skipped = aeo.active_providers()
    assert all(not p.get("paid") for p in use)
    assert any("claude: paid provider" in s for s in skipped)


def test_default_render_blueprint_is_free():
    import yaml
    bp = yaml.safe_load((ROOT / "render.yaml").read_text())
    assert all(s.get("plan") == "free" for s in bp["services"])
    assert "disk" not in str(bp)


def test_scheduled_jobs_receive_no_paid_keys():
    wf = (ROOT / ".github/workflows/pipeline.yml").read_text()
    for paid in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "PERPLEXITY_API_KEY", "KOMPASS_ALLOW_PAID"):
        assert paid not in wf
