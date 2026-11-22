"""Every test runs against a fresh temp database in mock-LLM mode."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
FIXTURES = ROOT / "tests" / "fixtures"


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    monkeypatch.setenv("KOMPASS_DB", str(tmp_path / "test.duckdb"))
    monkeypatch.setenv("KOMPASS_LLM", "mock")
    yield


@pytest.fixture
def fixture_accounts_csv(tmp_path):
    p = tmp_path / "accounts.csv"
    p.write_text(
        "name,domain,country,employees,founded,ats_provider,ats_slug,source\n"
        "Testbot Robotics GmbH,testbot.example,DE,80,2018,personio,testbot,fixture\n"
        "Testbot Robotics,https://www.testbot.example/,DE,,,,,fixture_dup\n"
        "Lagerfix AG,lagerfix.example,AT,300,2015,greenhouse,lagerfix,fixture\n"
        "Bigcorp Industrie SE,bigcorp.example,DE,9000,1950,,,fixture\n"
        "Valley Bots Inc,valleybots.example,US,40,2020,lever,valleybots,fixture\n",
        encoding="utf-8")
    return p
