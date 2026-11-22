"""Slack review: post drafts with Approve / Edit / Reject, and handle the button clicks.

Setup (Slack app):
- Bot token scopes: chat:write. Env: SLACK_BOT_TOKEN, SLACK_CHANNEL, SLACK_SIGNING_SECRET
- Interactivity request URL: https://<your-host>/slack/actions  (run: uvicorn kompass.review.slack:app)
Nothing is ever sent to a prospect from here: approval only marks the draft ready for a human to send.
"""
import hashlib
import hmac
import json
import os
import time

import httpx
from fastapi import FastAPI, HTTPException, Request

from kompass.review.store import record_review

SLACK_API = "https://slack.com/api"


def blocks_for(d: dict) -> list[dict]:
    why = "\n".join(f"• {c['claim']} [{c['source_id']}]" for c in d["why_now"]) or "—"
    srcs = "\n".join(f"[{k}] <{v}|source>" for k, v in d["sources"].items())
    return [
        {"type": "header", "text": {"type": "plain_text", "text": f"{d['name']} ({d['domain']})"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*Why now*\n{why}"}},
        {"type": "section", "text": {"type": "mrkdwn", "text":
            f"*Send to:* {d.get('play', {}).get('persona', '?')}  ·  *Channel:* {d.get('play', {}).get('channel', '?')}\n"
            f"_{d.get('play', {}).get('channel_note', '')}_"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*Draft* (prompt {d['prompt_version']})\n>{d['body']}"}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": srcs}]},
        {"type": "actions", "elements": [
            {"type": "button", "style": "primary", "text": {"type": "plain_text", "text": "Approve"},
             "action_id": "approve", "value": d["draft_id"]},
            {"type": "button", "text": {"type": "plain_text", "text": "Edit"},
             "action_id": "edit", "value": d["draft_id"]},
            {"type": "button", "style": "danger", "text": {"type": "plain_text", "text": "Reject"},
             "action_id": "reject", "value": d["draft_id"]},
        ]},
    ]


def post_for_review(d: dict) -> bool:
    token, channel = os.environ.get("SLACK_BOT_TOKEN"), os.environ.get("SLACK_CHANNEL")
    if not (token and channel):
        return False
    r = httpx.post(f"{SLACK_API}/chat.postMessage", headers={"Authorization": f"Bearer {token}"},
                   json={"channel": channel, "text": f"Review draft for {d['name']}", "blocks": blocks_for(d)},
                   timeout=10)
    return r.status_code == 200 and r.json().get("ok", False)


def verify(secret: str, ts: str, body: bytes, sig: str) -> bool:
    if not ts or abs(time.time() - int(ts)) > 300:      # replay protection
        return False
    base = f"v0:{ts}:{body.decode()}".encode()
    expected = "v0=" + hmac.new(secret.encode(), base, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig or "")


def _edit_modal(draft_id: str, body: str) -> dict:
    return {"type": "modal", "callback_id": "edit_submit", "private_metadata": draft_id,
            "title": {"type": "plain_text", "text": "Edit draft"},
            "submit": {"type": "plain_text", "text": "Save edit"},
            "blocks": [
                {"type": "input", "block_id": "body", "label": {"type": "plain_text", "text": "Final text"},
                 "element": {"type": "plain_text_input", "action_id": "v", "multiline": True, "initial_value": body}},
                {"type": "input", "block_id": "reason", "optional": True,
                 "label": {"type": "plain_text", "text": "Why did you change it?"},
                 "element": {"type": "plain_text_input", "action_id": "v"}}]}


app = FastAPI(title="kompass-review")


@app.post("/slack/actions")
async def actions(request: Request):
    raw = await request.body()
    secret = os.environ.get("SLACK_SIGNING_SECRET", "")
    if not verify(secret, request.headers.get("X-Slack-Request-Timestamp", ""), raw,
                  request.headers.get("X-Slack-Signature", "")):
        raise HTTPException(401, "bad signature")
    form = await request.form()
    payload = json.loads(form["payload"])
    user = payload.get("user", {}).get("username", "slack-user")

    if payload["type"] == "block_actions":
        act = payload["actions"][0]
        if act["action_id"] in ("approve", "reject"):
            record_review(act["value"], act["action_id"], reviewer=user)
            return {"text": f"{act['action_id']}d"}
        if act["action_id"] == "edit":
            from kompass.db import connect
            con = connect(read_only=True)
            body = con.execute("SELECT body FROM drafts WHERE draft_id=?", [act["value"]]).fetchone()[0]
            con.close()
            httpx.post(f"{SLACK_API}/views.open", timeout=10,
                       headers={"Authorization": f"Bearer {os.environ.get('SLACK_BOT_TOKEN', '')}"},
                       json={"trigger_id": payload["trigger_id"], "view": _edit_modal(act["value"], body)})
            return {}
    if payload["type"] == "view_submission":
        v = payload["view"]
        vals = v["state"]["values"]
        record_review(v["private_metadata"], "edit", reviewer=user, final_body=vals["body"]["v"]["value"],
                      reason=(vals.get("reason", {}).get("v", {}) or {}).get("value") or "")
        return {"response_action": "clear"}
    return {}
