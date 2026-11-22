import sys
from pathlib import Path

import pytest
import yaml

from kompass.db import connect, ROOT
from kompass.learn import ab, edits

sys.path.insert(0, str(ROOT / "eval"))
from gate import compare  # noqa: E402
from run_eval import run, table  # noqa: E402

RULES = yaml.safe_load((ROOT / "eval" / "gate.yaml").read_text())
BASE = {"cases": 25, "guard_pass_rate": 0.96, "must_mention_rate": 0.9, "unsupported_claim_rate": 0.04,
        "must_not_violations": 0}


@pytest.fixture
def tmp_prompt():
    created = []

    def make(name, text):
        p = ROOT / "prompts" / "draft" / f"{name}.md"
        p.write_text(text)
        created.append(p)
        return name
    yield make
    for p in created:
        p.unlink(missing_ok=True)


def test_gate_passes_equal_and_blocks_regressions():
    assert compare(dict(BASE), BASE, RULES) == []
    worse = {**BASE, "guard_pass_rate": 0.85, "unsupported_claim_rate": 0.2, "must_not_violations": 1}
    fails = " ".join(compare(worse, BASE, RULES))
    assert "guard_pass_rate dropped" in fails and "unsupported_claim_rate rose" in fails and "forbidden" in fails


def test_broken_prompt_fails_gate_end_to_end(tmp_prompt):
    bad = tmp_prompt("v900", (ROOT / "prompts/draft/v1.md").read_text() + "\n[[mock:uncited]]\n")
    rep = run(["v1", bad], [None])
    s = {r["version"]: r["summary"] for r in rep["runs"]}
    assert s["v1"]["guard_pass_rate"] > s[bad]["guard_pass_rate"]
    assert compare(s[bad], s["v1"], RULES)                # blocked
    assert "Mock mode" in table(rep) and "synthetic" in table(rep)


def _seed_reviews(specs):
    con = connect()
    for i, (decision, before, after, reason, dist) in enumerate(specs):
        did = f"d{i}"
        con.execute("INSERT INTO drafts (draft_id, account_id, prompt_version, variant, body, status, why_now, sources) "
                    "VALUES (?, 'a', 'v1', 'production', ?, 'edited', '[]', '{}')", [did, before])
        con.execute("INSERT INTO reviews (draft_id, reviewer, decision, final_body, reason, edit_distance) "
                    "VALUES (?, 'isha', ?, ?, ?, ?)", [did, decision, after, reason, dist])
    con.close()


LONG = "Saw you're hiring a Founding AE [S1]. Teams at that stage usually need clean account lists. Worth a look?"


def test_ranking_uses_impact_not_frequency():
    small = [("edit", LONG, LONG.replace("usually", "often"), "tone", 0.05)] * 5     # frequent, cheap
    big = [("edit", LONG, "Saw the Founding AE role [S1]. Happy to share a list.", "", 0.6)] * 3  # rare, costly
    _seed_reviews(small + big)
    ranked = edits.rank(edits.collect(days=30))
    assert ranked[0]["hypothesis"] == "shorter_drafts"
    assert ranked[0]["count"] < ranked[1]["count"]       # fewer cases, but ranked first


def test_proposal_writes_new_version_and_routes_vague_edits_to_humans():
    small = [("edit", LONG, LONG.replace("usually", "often"), "tone", 0.05)] * 4
    big = [("edit", LONG, "Saw the Founding AE role [S1]. Happy to share a list.", "", 0.6)] * 3
    _seed_reviews(small + big)
    res = edits.propose(days=30, min_evidence=3)
    new = ROOT / "prompts" / "draft" / f"{res['new_version']}.md"
    prop = Path(res["proposal"])
    try:
        text = new.read_text()
        assert "Learned from reviewer edits" in text and "under 45 words" in text
        body = prop.read_text()
        assert "Needs a human" in body and "tone_or_wording" in body and "Evidence" in body
        assert edits.gate_new_version("v1", res["new_version"])
    finally:
        new.unlink(missing_ok=True)
        prop.unlink(missing_ok=True)


def test_no_proposal_without_enough_evidence():
    _seed_reviews([("edit", LONG, "Short [S1]. Ok.", "", 0.7)])
    res = edits.propose(days=30, min_evidence=3)
    assert res["proposal"] is None


def _seed_ab(prod_acc, prod_n, exp_acc, exp_n):
    con = connect()
    k = 0
    for variant, version, acc, n in (("production", "v1", prod_acc, prod_n), ("experiment", "v2", exp_acc, exp_n)):
        for i in range(n):
            did = f"ab{k}"; k += 1
            con.execute("INSERT INTO drafts (draft_id, account_id, prompt_version, variant, body, status, why_now, sources) "
                        "VALUES (?, 'a', ?, ?, 'x', 'approved', '[]', '{}')", [did, version, variant])
            con.execute("INSERT INTO reviews (draft_id, decision, edit_distance) VALUES (?, ?, ?)",
                        [did, "approve" if i < acc else "reject", 0.0 if i < acc else None])
    con.close()


def test_ab_refuses_to_call_winner_early():
    _seed_ab(5, 10, 9, 10)
    assert "keep running" in ab.verdict(min_n=30)["verdict"]


def test_ab_promotes_clear_winner():
    _seed_ab(15, 40, 34, 40)
    v = ab.verdict(min_n=30)
    assert v["verdict"].startswith("promote v2") and v["p_value"] < 0.05


def test_learned_rules_are_not_duplicated(tmp_prompt):
    base_text = (ROOT / "prompts/draft/v1.md").read_text().replace(
        "## Output", "## Learned from reviewer edits\n- Keep the whole message under 45 words.\n\n## Output")
    tmp_prompt("v901", base_text)
    big = [("edit", LONG, "Saw the Founding AE role [S1]. Happy to share a list.", "", 0.6)] * 3
    con = connect(); _ = con.close()
    _seed_reviews(big)
    con = connect(); con.execute("UPDATE drafts SET prompt_version='v901'"); con.close()
    res = edits.propose(days=30, min_evidence=3, base_version="v901")
    assert res["proposal"] is None and "already in prompt" in res["note"]


def test_golden_promotion_from_real_reviews(fixture_accounts_csv):
    from tests.test_module2_signals import _world, NOW
    from kompass.signals import run as srun
    from kompass.review.store import pending, record_review
    sys.path.insert(0, str(ROOT / "eval" / "golden"))
    from promote import candidates
    _world(fixture_accounts_csv)
    srun.draft_for_active(NOW)
    d = pending()[0]
    record_review(d["draft_id"], "edit", reviewer="isha", final_body="Saw the Founding AE role [S1]. Want the list?")
    case = candidates()[0]
    assert case["synthetic"] is False and case["signals"] and case["reference_body"].startswith("Saw the")


def test_eval_reports_tokens_per_draft():
    rep = run(["v1"], [None])
    assert "tokens_per_draft" in rep["runs"][0]["summary"]
