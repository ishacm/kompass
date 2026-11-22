from kompass import ingest, score
from kompass.aeo import run as aeo_run, analyze
from kompass.db import connect, ROOT


def _accounts(csv_path):
    ingest.ingest([str(csv_path)])
    con = connect()
    con.execute("UPDATE accounts SET segment='cobots_and_arms', segment_confidence='high', sells_b2b_industrial=true "
                "WHERE domain IN ('testbot.example','lagerfix.example')")
    con.close()
    score.main()


def test_questions_are_paired_de_en():
    qs = aeo_run.load_questions()
    assert len(qs) == 20 and all(q["de"] and q["en"] for q in qs)


def test_mention_extraction_order_word_boundaries_and_case():
    vendors = [{"id": "ur", "aliases": ["Universal Robots"]}, {"id": "mir", "aliases": ["MiR"]},
               {"id": "abb", "aliases": ["ABB"]}]
    import re
    for v in vendors:
        cs = v["id"] in ("mir", "abb")
        v["patterns"] = [re.compile(rf"(?<![\w-]){re.escape(a)}(?![\w-])", 0 if cs else re.I) for a in v["aliases"]]
    ans = "Consider MiR for transport. Universal robots are popular. A mirror-finish or abbey is unrelated."
    m = aeo_run.extract_mentions(ans, vendors)
    assert [x["vendor"] for x in m] == ["mir", "ur"]          # ordered, no 'mirror'/'abbey' false hits
    assert m[0]["position"] == 1 and "transport" in m[0]["sentence"]


def test_providers_without_keys_are_skipped_and_reported(monkeypatch):
    monkeypatch.setenv("KOMPASS_LLM", "live")
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "PERPLEXITY_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    use, skipped = aeo_run.active_providers()
    assert use == [] and len(skipped) == 4


def test_full_run_sov_stability_gaps_and_signals(fixture_accounts_csv):
    _accounts(fixture_accounts_csv)
    stats = aeo_run.run(repeats=3, question_ids=["q01", "q02", "q03"], provider_ids=["claude", "openai"])
    assert stats["answers"] == 3 * 2 * 2 * 3 and stats["mentions"] > 0
    res = analyze.report(stats["run_id"], emit=True)
    assert 0 <= res["stability"] <= 1
    assert res["share_of_voice"] and all("de_en_gap" in v for v in res["share_of_voice"].values())
    assert (ROOT / "aeo" / "reports" / f"{stats['run_id']}.md").exists()
    con = connect(read_only=True)
    n = con.execute("SELECT count(*) FROM signals WHERE signal_type='aeo_gap'").fetchone()[0]
    assert n == res["signals_emitted"]
    for f in (ROOT / "aeo" / "reports").glob(f"{stats['run_id']}*"):
        f.unlink()


def test_invisible_account_becomes_gap(fixture_accounts_csv):
    _accounts(fixture_accounts_csv)
    gaps = analyze.gap_accounts({})
    assert {g["account_id"] for g in gaps} >= {"testbot.example"} and gaps[0]["gap"] == "invisible"


def test_vendors_named_in_question_are_not_counted(fixture_accounts_csv):
    _accounts(fixture_accounts_csv)
    stats = aeo_run.run(repeats=1, question_ids=["q03"], provider_ids=["claude"])   # mentions Universal Robots
    con = connect(read_only=True)
    n = con.execute("SELECT count(*) FROM aeo_mentions WHERE vendor='universal-robots'").fetchone()[0]
    excl = con.execute("SELECT excluded_vendors FROM aeo_answers LIMIT 1").fetchone()[0]
    assert n == 0 and "universal-robots" in excl


def test_cited_domains_and_small_sample_flags(fixture_accounts_csv):
    _accounts(fixture_accounts_csv)
    stats = aeo_run.run(repeats=2, question_ids=["q01", "q04"], provider_ids=["claude"])
    res = analyze.report(stats["run_id"])
    domains = dict(res["cited_domains"])
    assert "example-robotics-review.com" in domains
    assert all(v["small_sample"] for v in res["share_of_voice"].values())   # 4 answers per language < 10
    for f in (ROOT / "aeo" / "reports").glob(f"{stats['run_id']}*"):
        f.unlink()
