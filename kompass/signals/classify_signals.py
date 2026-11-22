"""Turn job postings into GTM buying signals.

Two stages to control cost:
1. Cheap keyword prefilter: titles with no GTM relevance become 'none' without an LLM call.
2. LLM classifier with a fixed label set and structured JSON output.
"""
import re

from kompass.llm import complete_json

SIGNAL_TYPES = ["first_sales_hire", "sales_leadership_hire", "sales_hire", "revops_or_gtm_ops_hire",
                "partner_or_channel_hire", "international_expansion", "customer_deployment_hire", "none"]

# weights used by activation; first sales hire and leadership hires are the strongest triggers
SIGNAL_WEIGHT = {"first_sales_hire": 3, "sales_leadership_hire": 3, "revops_or_gtm_ops_hire": 2,
                 "international_expansion": 2, "partner_or_channel_hire": 1, "sales_hire": 1,
                 "customer_deployment_hire": 1, "aeo_gap": 2}

PREFILTER = re.compile(
    r"sales|vertrieb|account|revenue|partner|channel|business development|bizdev|customer success|"
    r"solutions?|deployment|field application|growth|go.to.market|gtm|revops|crm|key account|"
    r"usa|united states|north america|new york|boston|austin|chicago|japan|singapore", re.I)

PROMPT = """You label job postings at B2B robotics / industrial-AI companies as go-to-market buying signals.

Posting title: {title}
Location: {location}
Description excerpt: \"\"\"{description}\"\"\"

Labels:
- first_sales_hire: founding/first sales role, or clearly the first commercial hire
- sales_leadership_hire: head/VP/director of sales, CRO, Vertriebsleitung
- sales_hire: other quota-carrying sales roles (AE, sales manager, key account)
- revops_or_gtm_ops_hire: RevOps, sales ops, CRM, GTM engineering
- partner_or_channel_hire: partner, channel, reseller, integrator management
- international_expansion: commercial role based outside DACH (e.g. US, Asia)
- customer_deployment_hire: field application, deployment, solutions or integration engineers
- none: not a GTM signal

Use only the posting text. Reply with JSON only:
{{"signal_type": "...", "confidence": 0.0-1.0, "reason": "quote the words that decided it"}}"""


def classify_posting(p: dict) -> dict:
    text = f"{p.get('title', '')} {p.get('location', '')}"
    if not PREFILTER.search(text):
        return {"signal_type": "none", "confidence": 1.0, "reason": "prefilter: no GTM keywords",
                "llm_used": False}
    out = complete_json(PROMPT.format(title=p.get("title", ""), location=p.get("location", ""),
                                      description=(p.get("description") or "")[:1500]),
                        purpose="signal_classify", max_tokens=200, context=p)
    if out.get("signal_type") not in SIGNAL_TYPES:
        out = {"signal_type": "none", "confidence": 0.0, "reason": f"off-list label: {out.get('signal_type')}"}
    try:
        out["confidence"] = max(0.0, min(1.0, float(out.get("confidence", 0))))
    except (TypeError, ValueError):
        out["confidence"] = 0.0
    out["llm_used"] = True
    return out
