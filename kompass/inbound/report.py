"""Inbound numbers for the Module 5 case study. Usage: python -m kompass.inbound.report [--include-test]"""
import argparse
import json

from kompass.db import connect


def summary(include_test: bool = False) -> dict:
    con = connect(read_only=True)
    where = "" if include_test else "WHERE NOT l.is_test"
    rows = con.execute(f"""SELECT json_extract_string(d.detail, '$.route'),
                                  CAST(json_extract(d.detail, '$.seconds') AS DOUBLE),
                                  json_extract(d.detail, '$.possible_hot')::BOOLEAN
                           FROM lead_decisions d JOIN leads l USING (lead_id) {where}
                           {'AND' if where else 'WHERE'} d.step = 'route'""").fetchall()
    humans = con.execute(f"""SELECT count(DISTINCT d.lead_id) FROM lead_decisions d JOIN leads l USING (lead_id)
                             {where} {'AND' if where else 'WHERE'} d.step = 'human_requested'""").fetchone()[0]
    con.close()
    if not rows:
        return {"leads": 0}
    secs = sorted(r[1] for r in rows if r[1] is not None)
    routes = {}
    for r in rows:
        routes[r[0]] = routes.get(r[0], 0) + 1
    return {"leads": len(rows), "routes": routes, "median_seconds_to_route": secs[len(secs) // 2],
            "p95_seconds": secs[int(len(secs) * 0.95) - 1] if len(secs) > 1 else secs[0],
            "possible_hot_from_personal_email": sum(bool(r[2]) for r in rows),
            "human_requested_rate": round(humans / len(rows), 3)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--include-test", action="store_true")
    print(json.dumps(summary(ap.parse_args().include_test), indent=2))
