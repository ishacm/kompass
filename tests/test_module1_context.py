from kompass import ingest, score, classify, report
from kompass import mcp_server as m
from kompass.db import connect


def _setup(csv_path):
    ingest.ingest([str(csv_path)])
    con = connect()
    con.execute("""UPDATE accounts SET segment='cobots_and_arms', segment_confidence='high',
                   sells_b2b_industrial=true WHERE domain='testbot.example'""")
    con.execute("""UPDATE accounts SET segment='warehouse_and_logistics_automation', segment_confidence='low',
                   sells_b2b_industrial=true WHERE domain='lagerfix.example'""")
    con.close()
    score.main()


def test_duplicates_merge_and_keep_both_sources(fixture_accounts_csv):
    _setup(fixture_accounts_csv)
    con = connect(read_only=True)
    assert con.execute("SELECT count(*) FROM accounts").fetchone()[0] == 4
    srcs = con.execute("SELECT sources FROM accounts WHERE domain='testbot.example'").fetchone()[0]
    assert set(srcs) == {"fixture", "fixture_dup"}


def test_merge_never_overwrites_known_values(fixture_accounts_csv):
    _setup(fixture_accounts_csv)
    con = connect(read_only=True)
    emp = con.execute("SELECT employees FROM accounts WHERE domain='testbot.example'").fetchone()[0]
    assert emp == 80


def test_scoring_tiers_and_disqualifiers(fixture_accounts_csv):
    _setup(fixture_accounts_csv)
    con = connect(read_only=True)
    tiers = dict(con.execute("SELECT account_id, tier FROM account_scores").fetchall())
    assert tiers["testbot.example"] == "A"
    assert tiers["valleybots.example"] == "DQ"          # outside DACH


def test_low_confidence_cannot_reach_tier_a():
    s, tier, b = score.score({"segment": "cobots_and_arms", "segment_confidence": "low", "country": "DE",
                              "employees": 100, "founded": 2020, "sells_b2b_industrial": True})
    assert s >= 75 and tier == "B" and b["needs_review"]


def test_classifier_without_page_text_flags_instead_of_guessing():
    out = classify.classify_one("Unknown GmbH", "unknown.example", None)
    assert out["confidence"] == "low" and "manual review" in out["reason"]


def test_classifier_rejects_off_list_labels(monkeypatch):
    monkeypatch.setattr(classify, "complete_json", lambda *a, **k: {"segment": "space_lasers",
                                                                     "confidence": "high"})
    out = classify.classify_one("X", "x.example", "some text")
    assert out["segment"] == "other_industrial" and out["confidence"] == "low"


def test_mcp_tools_are_read_only_and_cite(fixture_accounts_csv):
    _setup(fixture_accounts_csv)
    con = connect()
    con.execute("INSERT INTO signals VALUES ('s1','testbot.example','first_sales_hire','Founding AE',"
                "'https://jobs.example/1','', now(), 0.9, 'ats', NULL)")
    con.close()
    acc = m.get_account("www.testbot.example")
    assert acc["tier"] == "A" and acc["signals"][0]["evidence_url"].startswith("https://")
    assert m.get_account("missing.example")["error"]
    assert len(m.recent_signals(days=7, min_tier="A")) == 1
    names = {t for t in dir(m) if not t.startswith("_")}
    assert "run_sql" not in names


def test_report_coverage(fixture_accounts_csv):
    _setup(fixture_accounts_csv)
    cov = report.coverage()
    assert cov["accounts"] == 4 and cov["ingest"]["duplicates_merged"] == 1
    assert 0 < cov["fill_segment"] <= 1
