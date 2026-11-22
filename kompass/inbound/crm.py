"""Optional HubSpot sync for inbound leads (consented). Env: HUBSPOT_TOKEN (private app, contacts scope).
Failures are logged and never block routing.
"""
import os

import httpx

API = "https://api.hubapi.com"


def upsert_contact(lead: dict, route: str, reason: str) -> str | None:
    token = os.environ.get("HUBSPOT_TOKEN")
    if not token:
        return None
    first, _, last = (lead.get("name") or "").partition(" ")
    props = {"email": lead["email"], "firstname": first, "lastname": last, "company": lead.get("company", ""),
             "hs_lead_status": "NEW", "message": f"[kompass route: {route}] {reason}\n\n{lead.get('message', '')}"[:5000]}
    h = {"Authorization": f"Bearer {token}"}
    try:
        r = httpx.post(f"{API}/crm/v3/objects/contacts", headers=h, json={"properties": props}, timeout=8)
        if r.status_code == 409:   # already exists: update by email
            r = httpx.patch(f"{API}/crm/v3/objects/contacts/{lead['email']}?idProperty=email", headers=h,
                            json={"properties": props}, timeout=8)
        r.raise_for_status()
        return r.json().get("id")
    except Exception:
        return None
