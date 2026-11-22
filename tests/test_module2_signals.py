import json
from datetime import datetime

import pytest

from kompass import ingest, score
from kompass.db import connect
from kompass.review import slack
from kompass.review.store import record_review, pending, edit_distance
from kompass.signals import ats, run
from kompass.signals.activate import active_accounts
from kompass.signals.classify_signals import classify_posting
from kompass.signals.draft import guard, assign_variant
from tests.conftest import FIXTURES

NOW = datetime(2026, 11, 20)


def _world(csv_path):
    ingest.ingest([str(csv_path)])
    con = connect()
    con.execute("UPDATE accounts SET segment='cobots_and_arms', segment_confidence='high', "
                "sells_b2b_industrial=true WHERE domain IN ('testbot.example','lagerfix.example')")
    con.close()
    score.main()
    return run.collect(FIXTURES / "ats")


def test_parsers_read_all_four_ats_formats():
    fx = FIXTURES / "ats"
    p = ats.parse_personio((fx / "personio_testbot.xml").read_text(), "testbot")
    assert p[0]["url"] == "https://testbot.jobs.personio.de/job/1001" and "pipeline" in p[0]["description"]
    g = ats.parse_greenhouse(json.loads((fx / "greenhouse_lagerfix.json").read_text()))
    assert g[0]["location"] == "Wien" and "<p>" not in g[0]["description"]
    lv = ats.parse_lever(json.loads((fx / "lever_valleybots.json").read_text()))
    assert lv[0]["title"] == "Head of Sales" and lv[0]["posted_at"].startswith("2026-11-15")
    a = ats.parse_ashby(json.loads((fx / "ashby_sample.json").read_text()))
    assert a[0]["url"].startswith("https://jobs.ashbyhq.com")


def test_prefilter_skips_llm_for_irrelevant_roles():
    res = classify_posting({"title": "Embedded Software Engineer", "location": "München"})
    assert res["signal_type"] == "none" and res["llm_used"] is False


def test_collect_is_idempotent_and_only_new_postings_cost(fixture_accounts_csv):
    first = _world(fixture_accounts_csv)
    assert first["new_postings"] == 6 and first["signals"] >= 3
    assert first["llm_calls"] < first["new_postings"]           # prefilter saved calls
    second = run.collect(FIXTURES / "ats")
    assert second["new_postings"] == 0 and second["llm_calls"] == 0


def test_compounding_activation(fixture_accounts_csv):
    _world(fixture_accounts_csv)
    act = {a["account_id"]: a for a in active_accounts(NOW)}
    assert "testbot.example" in act                     # founding AE + RevOps = compounded
    assert "lagerfix.example" not in act                # one weak sales hire is not enough
    assert "valleybots.example" not in act              # disqualified (US) even with Head of Sales


def test_guard_blocks_uncited_and_invented_claims():
    sources = {"S1": {"title": "Founding Account Executive", "evidence_text": "", "url": "u"}}
    ok = {"why_now": [{"claim": "hiring AE", "source_id": "S1"}],
          "body": "You're hiring a Founding Account Executive [S1]. That's usually when list quality matters. Open to a 15-minute chat?"}
    assert guard(ok, sources) == []
    bad = {"why_now": [{"claim": "raised money", "source_id": "S9"}],
           "body": "Congrats on growing 300% this year. Quick question: synergy?"}
    issues = " ".join(guard(bad, sources))
    for expected in ["without valid source", "cites no source", "banned phrase", "number not in evidence"]:
        assert expected in issues


def test_ab_assignment_is_deterministic():
    reg = {"draft": {"production": "v1", "experiment": "v2", "experiment_share": 0.5}}
    arms = {assign_variant(f"acc{i}", reg) for i in range(200)}
    assert arms == {("production", "v1"), ("experiment", "v2")}
    assert assign_variant("acc7", reg) == assign_variant("acc7", reg)


def test_end_to_end_draft_review_and_edit_log(fixture_accounts_csv):
    _world(fixture_accounts_csv)
    stats = run.draft_for_active(NOW)
    assert stats["drafts"] == 1 and stats["blocked"] == 0
    assert run.draft_for_active(NOW)["drafts"] == 0      # one open draft per account
    d = pending()[0]
    assert d["sources"]["S1"].startswith("https://")
    res = record_review(d["draft_id"], "edit", reviewer="isha",
                        final_body="Short version [S1]. Worth a chat?", reason="too long")
    assert 0 < res["edit_distance"] <= 1
    assert pending() == []


def test_blocked_drafts_cannot_be_approved(fixture_accounts_csv):
    _world(fixture_accounts_csv)
    con = connect()
    con.execute("INSERT INTO drafts (draft_id, account_id, body, status, why_now, sources) "
                "VALUES ('b1','testbot.example','x','blocked','[]','{}')")
    con.close()
    with pytest.raises(PermissionError):
        record_review("b1", "approve")


def test_slack_signature_verification():
    import hashlib, hmac, time
    ts, body = str(int(time.time())), b"payload=%7B%7D"
    sig = "v0=" + hmac.new(b"secret", f"v0:{ts}:{body.decode()}".encode(), hashlib.sha256).hexdigest()
    assert slack.verify("secret", ts, body, sig)
    assert not slack.verify("secret", ts, body, "v0=forged")
    assert not slack.verify("secret", str(int(time.time()) - 3600), body, sig)   # replay


def test_edit_distance_bounds():
    assert edit_distance("same", "same") == 0.0
    assert edit_distance("abc", "xyz") == 1.0


def test_titles_and_names_are_humanised():
    from kompass.signals.text import clean_title, short_name
    assert clean_title("Founding Account Executive (m/w/d)") == "Founding Account Executive"
    assert clean_title("Sales Manager DACH (all genders) - Remote") == "Sales Manager DACH"
    assert short_name("Testbot Robotics GmbH") == "Testbot Robotics"
    assert short_name("Lagerfix GmbH & Co. KG") == "Lagerfix"


def test_draft_has_persona_and_dach_channel_policy(fixture_accounts_csv):
    _world(fixture_accounts_csv)
    run.draft_for_active(NOW)
    d = pending()[0]
    assert "(m/w/d)" not in d["body"] and "GmbH" not in d["body"]
    assert d["play"]["persona"] == "founder_ceo"
    assert d["play"]["channel"] == "linkedin_or_phone" and "UWG" in d["play"]["channel_note"]


def test_removed_postings_close_signals_and_deactivate(fixture_accounts_csv, tmp_path):
    _world(fixture_accounts_csv)
    assert "testbot.example" in {a["account_id"] for a in active_accounts(NOW)}
    # board now only lists the engineering role: both GTM postings were taken down
    fx = tmp_path / "ats"; fx.mkdir()
    src = (FIXTURES / "ats" / "personio_testbot.xml").read_text()
    import re as _re
    kept = _re.sub(r"<position>\s*<id>100[12]</id>.*?</position>", "", src, flags=_re.S)
    (fx / "personio_testbot.xml").write_text(kept)
    for f in (FIXTURES / "ats").glob("*.json"):
        (fx / f.name).write_text(f.read_text())
    stats = run.collect(fx)
    assert stats.get("closed") == 2
    assert "testbot.example" not in {a["account_id"] for a in active_accounts(NOW)}


def test_signal_eval_harness():
    import sys
    sys.path.insert(0, "eval")
    from signal_check import evaluate
    res = evaluate([{"title": "Founding Account Executive", "label": "first_sales_hire"},
                    {"title": "Embedded Engineer", "label": "none"},
                    {"title": "Head of Sales", "label": "sales_leadership_hire"}])
    assert res["n"] == 3 and res["signal_precision"] == 1.0


def test_funnel_report(fixture_accounts_csv):
    from kompass.signals.report import funnel
    _world(fixture_accounts_csv)
    run.draft_for_active(NOW)
    f = funnel()
    assert f["postings_scanned"] == 6 and f["drafts_total"] == 1
