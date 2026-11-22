"""Inbound form + agent for the portfolio site.

Run: uvicorn kompass.inbound.app:app --port 8080
Embed: point the portfolio's "Work with me" button at /  (or POST JSON to /api/lead).
"""
import time
from collections import defaultdict, deque
from html import escape

import yaml
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from kompass.db import ROOT
from kompass.inbound.qualify import process_lead, request_human

CFG = yaml.safe_load((ROOT / "kompass" / "config.yaml").read_text())["inbound"]
app = FastAPI(title="kompass-inbound")

RATE = {"per_ip": 5, "window_s": 600}                  # 5 submissions per IP per 10 minutes
LIMITS = {"name": 120, "email": 200, "company": 200, "message": 3000}
_hits: dict[str, deque] = defaultdict(deque)


def rate_limited(ip: str) -> bool:
    now, q = time.time(), _hits[ip]
    while q and now - q[0] > RATE["window_s"]:
        q.popleft()
    if len(q) >= RATE["per_ip"]:
        return True
    q.append(now)
    return False


def too_long(**fields) -> str | None:
    return next((k for k, v in fields.items() if len(v or "") > LIMITS[k]), None)

STYLE = """<style>body{font:16px/1.5 system-ui,sans-serif;max-width:560px;margin:48px auto;padding:0 20px;color:#1a1a1a}
label{display:block;margin:14px 0 4px;font-weight:600}input,textarea{width:100%;padding:10px;border:1px solid #ccc;
border-radius:8px;font:inherit}textarea{min-height:120px}button{margin-top:18px;padding:12px 18px;border:0;
border-radius:8px;background:#1a1a1a;color:#fff;font:inherit;cursor:pointer}.notice{background:#f4f4f0;border-radius:8px;
padding:12px 14px;font-size:14px}.check{display:flex;gap:8px;align-items:flex-start;font-weight:400}
.check input{width:auto;margin-top:5px}</style>"""


@app.get("/", response_class=HTMLResponse)
def form():
    return f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Work with me</title>{STYLE}
<h1>Work with me</h1>
<p class="notice"><strong>AI notice:</strong> {escape(CFG['ai_notice'])}</p>
<form method="post" action="/lead">
<label for="name">Name</label><input id="name" name="name" required>
<label for="email">Work email</label><input id="email" name="email" type="email" required>
<label for="company">Company</label><input id="company" name="company">
<label for="message">What are you trying to fix?</label><textarea id="message" name="message" required></textarea>
<label class="check"><input type="checkbox" name="consent" value="yes" required>
I agree that my details are processed to answer this request and deleted after {CFG['retention_days']} days
if we don't work together. <a href="/privacy">Privacy note</a></label>
<button type="submit">Send</button></form></html>"""


@app.post("/lead", response_class=HTMLResponse)
def submit(request: Request, name: str = Form(...), email: str = Form(...), company: str = Form(""),
           message: str = Form(...), consent: str = Form("")):
    if rate_limited(request.client.host if request.client else "unknown"):
        return HTMLResponse(f"<!doctype html>{STYLE}<p>Too many requests. Please try again later.</p>", 429)
    if (field := too_long(name=name, email=email, company=company, message=message)):
        return HTMLResponse(f"<!doctype html>{STYLE}<p>The {field} field is too long.</p>", 400)
    res = process_lead({"name": name, "email": email, "company": company, "message": message,
                        "consent": consent == "yes"})
    if res["route"] == "no_consent":
        return HTMLResponse(f"<!doctype html>{STYLE}<p>{escape(res['message'])}</p><a href='/'>Back</a>", 400)
    reply = escape(res["reply"]).replace("\n", "<br>")
    booking = CFG["booking_url"]
    reply = reply.replace(escape(booking), f"<a href='{escape(booking)}'>{escape(booking)}</a>")
    human = (f"<form method='post' action='/human/{res['lead_id']}'><button>I'd rather talk to a human</button></form>"
             if res["route"] in ("hot", "nurture") else "")
    return f"<!doctype html><meta charset='utf-8'>{STYLE}<h1>Thanks, {escape(name)}</h1><p>{reply}</p>{human}"


@app.post("/human/{lead_id}", response_class=HTMLResponse)
def human(lead_id: str):
    ok = request_human(lead_id)
    return f"<!doctype html>{STYLE}<p>{'Done: a human will reply personally.' if ok else 'Request not found.'}</p>"


class LeadIn(BaseModel):
    name: str
    email: str
    company: str = ""
    message: str
    consent: bool


@app.post("/api/lead")
def api_lead(lead: LeadIn, request: Request):
    if rate_limited(request.client.host if request.client else "unknown"):
        return JSONResponse({"error": "rate limited"}, status_code=429)
    if (field := too_long(**{k: getattr(lead, k) for k in LIMITS})):
        return JSONResponse({"error": f"{field} too long"}, status_code=400)
    res = process_lead(lead.model_dump())
    return JSONResponse({k: res.get(k) for k in ("lead_id", "route", "reply", "seconds")},
                        status_code=400 if res["route"] == "no_consent" else 200)


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/privacy", response_class=HTMLResponse)
def privacy():
    return f"""<!doctype html>{STYLE}<h1>Privacy note</h1>
<p>What I collect: the name, email, company and message you send.</p>
<p>Why: to answer your request (GDPR Art. 6(1)(a), your consent).</p>
<p>How: an AI assistant classifies the request and checks public information about your company's website
to route it. A human reads every handoff. No automated decision is made that has legal or similarly significant
effects on you.</p>
<p>How long: deleted after {CFG['retention_days']} days unless we start working together.</p>
<p>Your rights: access, correction, deletion, withdrawal of consent: email {escape(CFG['owner_email'])}.</p>
<p><em>Template: have it checked for your own setup.</em></p>"""
