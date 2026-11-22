"""Record human decisions on drafts. This table is the training signal for Module 3."""
import difflib
import json

from kompass.db import connect

DECISIONS = {"approve", "edit", "reject"}


def edit_distance(before: str, after: str) -> float:
    """0.0 = unchanged, 1.0 = completely rewritten (character-level)."""
    if before == after:
        return 0.0
    return round(1 - difflib.SequenceMatcher(None, before or "", after or "").ratio(), 3)


def record_review(draft_id: str, decision: str, *, reviewer: str = "unknown",
                  final_body: str | None = None, reason: str = "") -> dict:
    if decision not in DECISIONS:
        raise ValueError(f"decision must be one of {DECISIONS}")
    con = connect()
    row = con.execute("SELECT body, status FROM drafts WHERE draft_id = ?", [draft_id]).fetchone()
    if not row:
        con.close()
        raise KeyError(f"unknown draft {draft_id}")
    body, status = row
    if status == "blocked":
        con.close()
        raise PermissionError("blocked drafts cannot be approved; fix the prompt or the evidence")
    if decision == "edit" and not (final_body and final_body.strip()):
        con.close()
        raise ValueError("an edit needs the final text")
    final = final_body if decision == "edit" else (body if decision == "approve" else None)
    dist = edit_distance(body, final) if final is not None else None
    con.execute("INSERT INTO reviews (draft_id, reviewer, decision, final_body, reason, edit_distance) "
                "VALUES (?, ?, ?, ?, ?, ?)", [draft_id, reviewer, decision, final, reason, dist])
    new_status = {"approve": "approved", "edit": "edited", "reject": "rejected"}[decision]
    con.execute("UPDATE drafts SET status = ? WHERE draft_id = ?", [new_status, draft_id])
    con.close()
    return {"draft_id": draft_id, "decision": decision, "edit_distance": dist}


def pending() -> list[dict]:
    con = connect(read_only=True)
    rows = con.execute("""SELECT d.draft_id, a.name, a.domain, d.body, d.why_now, d.sources, d.prompt_version, d.play
                          FROM drafts d JOIN accounts a USING (account_id)
                          WHERE d.status = 'pending' ORDER BY d.created_at""").fetchall()
    con.close()
    return [{"draft_id": r[0], "name": r[1], "domain": r[2], "body": r[3], "why_now": json.loads(r[4]),
             "sources": json.loads(r[5]), "prompt_version": r[6], "play": json.loads(r[7] or "{}")} for r in rows]
