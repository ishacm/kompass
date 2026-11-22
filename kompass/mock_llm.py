"""Deterministic stand-ins for LLM calls (KOMPASS_LLM=mock).

Purpose: tests, CI and offline demos exercise the real pipeline code without an API key.
These handlers are simple keyword rules. They are NOT a model, and their output must never
be reported as a model result.
"""
import re

SEGMENT_KEYWORDS = [
    ("humanoids", ["humanoid"]),
    ("cobots_and_arms", ["cobot", "robot arm", "roboterarm", "collaborative robot"]),
    ("mobile_robots_amr", ["amr", "autonomous mobile", "mobile robot", "fahrerlos"]),
    ("machine_vision", ["machine vision", "3d vision", "bildverarbeitung", "camera"]),
    ("robot_software_and_simulation", ["robot software", "simulation", "programming platform"]),
    ("warehouse_and_logistics_automation", ["warehouse", "intralogistics", "lager", "picking"]),
    ("industrial_ai_software", ["industrial ai", "predictive maintenance", "manufacturing ai"]),
]

SIGNAL_RULES = [
    ("first_sales_hire", r"\b(founding|first)\b.*\b(account executive|sales|ae)\b"),
    ("sales_leadership_hire", r"\b(head of sales|vp sales|vertriebsleit\w*|chief revenue|cro)\b"),
    ("revops_or_gtm_ops_hire", r"\b(revops|revenue operations|sales ops|gtm engineer|crm)\b"),
    ("partner_or_channel_hire", r"\b(partner|channel)\b.*\b(manager|lead)\b"),
    ("international_expansion", r"\b(us|usa|north america|new york|boston|austin|japan)\b"),
    ("customer_deployment_hire", r"\b(field application|deployment|solutions engineer|integration engineer)\b"),
    ("sales_hire", r"\b(account executive|sales manager|business development|vertrieb\w*|key account)\b"),
]


def _segment(ctx):
    text = (ctx.get("text") or "").lower()
    for seg, kws in SEGMENT_KEYWORDS:
        if any(k in text for k in kws):
            return {"segment": seg, "sells_b2b_industrial": any(
                w in text for w in ["manufactur", "fertigung", "factory", "fabrik", "logistic", "industrie"]),
                "confidence": "medium", "reason": f"mock: matched keyword for {seg}"}
    return {"segment": "other_industrial", "sells_b2b_industrial": False, "confidence": "low",
            "reason": "mock: no keyword matched"}


def _signal(ctx):
    text = f"{ctx.get('title', '')} {ctx.get('location', '')}".lower()
    for sig, pat in SIGNAL_RULES:
        if re.search(pat, text):
            return {"signal_type": sig, "confidence": 0.7, "reason": f"mock rule: {sig}"}
    return {"signal_type": "none", "confidence": 0.6, "reason": "mock: no rule matched"}


def _draft(ctx):
    sigs = ctx.get("signals", [])
    name = ctx.get("account_name", "your team")
    if not sigs:
        return {"why_now": [], "body": ""}
    s1 = sigs[0]
    why = [{"claim": f"{name} is hiring for '{s1['title']}'", "source_id": "S1"}]
    if len(sigs) > 1:
        why.append({"claim": f"{name} also posted '{sigs[1]['title']}'", "source_id": "S2"})
    if "[[mock:uncited]]" in ctx.get("_prompt", ""):     # lets tests simulate a broken prompt
        return {"why_now": [{"claim": f"{name} grew 300% this year", "source_id": "S9"}],
                "body": f"Congrats on growing 300% at {name}. We guarantee results. Quick question?"}
    variant = ctx.get("prompt_version", "v1")
    opener = "Saw" if variant.endswith("1") else "Noticed"
    body = (f"{opener} {name} is hiring a {s1['title']} [S1]. Teams at that stage usually need signal-based "
            f"account lists before the new hire starts. Worth a 15-minute look at how I'd set that up?")
    return {"why_now": why, "body": body}


def _need(ctx):
    msg = (ctx.get("message") or "").lower()
    if re.search(r"\b(demo|pilot|outbound|pipeline|signals?|gtm|hire|hiring|project|angebot|zusammenarbeit)\b", msg):
        return {"need": "buying_intent", "confidence": "medium", "summary": "mock: buying keywords"}
    if re.search(r"\b(job|praktikum|werkstudent|application|bewerbung)\b", msg):
        return {"need": "job_or_partnership", "confidence": "medium", "summary": "mock: job keywords"}
    if re.search(r"(https?://|casino|seo services|crypto|backlinks)", msg):
        return {"need": "spam", "confidence": "high", "summary": "mock: spam pattern"}
    return {"need": "unclear", "confidence": "low", "summary": "mock: no pattern"}


def _aeo_answer(ctx):
    vendors = ctx.get("mock_vendors", [])
    q = ctx.get("question", "")
    rot = (len(q) + ctx.get("repeat_idx", 0)) % max(len(vendors), 1)
    picked = (vendors[rot:] + vendors[:rot])[:3]
    return {"answer": "Options include " + ", ".join(picked) + ". See https://www.example-robotics-review.com/list",
            "citations": ["https://www.example-industry-mag.de/cobots"] if rot % 2 else []}


def _edit_hypothesis(ctx):
    before, after = ctx.get("before", ""), ctx.get("after", "")
    if len(after) < len(before) * 0.8:
        return {"hypothesis": "shorter_drafts", "detail": "reviewer cut length"}
    if "?" not in after and "?" in before:
        return {"hypothesis": "remove_question_cta", "detail": "reviewer removed the question"}
    return {"hypothesis": "tone_or_wording", "detail": "wording changes"}


HANDLERS = {
    "segment_classify": _segment,
    "signal_classify": _signal,
    "draft": _draft,
    "inbound_need": _need,
    "aeo_answer": _aeo_answer,
    "edit_hypothesis": _edit_hypothesis,
}


def handle(purpose: str, prompt: str, context: dict) -> dict:
    if purpose not in HANDLERS:
        raise KeyError(f"no mock handler for purpose '{purpose}'")
    return HANDLERS[purpose]({**context, "_prompt": prompt})
