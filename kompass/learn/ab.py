"""Compare production vs experiment prompts on real reviewer behaviour.

Outcome per draft: accepted (approved or edited) vs rejected, plus edit distance.
Refuses to declare a winner before each arm has enough reviews.

Usage: python -m kompass.learn.ab [--min-n 30]
"""
import argparse
import math

from kompass.db import connect


def arms() -> dict:
    con = connect(read_only=True)
    rows = con.execute("""
        SELECT d.variant, d.prompt_version, r.decision, r.edit_distance
        FROM reviews r JOIN drafts d USING (draft_id)
        WHERE d.variant IN ('production', 'experiment')""").fetchall()
    con.close()
    out: dict[str, dict] = {}
    for variant, version, decision, dist in rows:
        a = out.setdefault(variant, {"version": version, "n": 0, "accepted": 0, "dist": []})
        a["n"] += 1
        a["accepted"] += decision in ("approve", "edit")
        if dist is not None:
            a["dist"].append(dist)
    for a in out.values():
        a["acceptance_rate"] = round(a["accepted"] / a["n"], 3) if a["n"] else None
        a["avg_edit_distance"] = round(sum(a["dist"]) / len(a["dist"]), 3) if a["dist"] else None
        del a["dist"]
    return out


def two_proportion_p(x1, n1, x2, n2) -> float | None:
    if not (n1 and n2):
        return None
    p = (x1 + x2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    if se == 0:
        return 1.0
    z = abs(x1 / n1 - x2 / n2) / se
    return round(math.erfc(z / math.sqrt(2)), 4)


def verdict(min_n: int = 30) -> dict:
    a = arms()
    prod, exp = a.get("production"), a.get("experiment")
    if not (prod and exp):
        return {"arms": a, "verdict": "no experiment running"}
    if min(prod["n"], exp["n"]) < min_n:
        return {"arms": a, "verdict": f"keep running: need {min_n} reviews per arm "
                                      f"(have {prod['n']} / {exp['n']})"}
    p = two_proportion_p(exp["accepted"], exp["n"], prod["accepted"], prod["n"])
    better = exp["acceptance_rate"] > prod["acceptance_rate"]
    less_editing = (exp["avg_edit_distance"] or 1) <= (prod["avg_edit_distance"] or 1)
    if p is not None and p < 0.05 and better and less_editing:
        v = f"promote {exp['version']}: higher acceptance (p={p}) and no more editing; open a PR to change registry.yaml"
    elif p is not None and p < 0.05 and not better:
        v = f"stop experiment: {exp['version']} is worse (p={p})"
    else:
        v = f"no significant difference yet (p={p}); keep production"
    return {"arms": a, "p_value": p, "verdict": v}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-n", type=int, default=30)
    import json
    print(json.dumps(verdict(ap.parse_args().min_n), indent=2))
