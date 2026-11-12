"""Trust Certificate: a signed, hash-chained statement of what was inspected and what is guaranteed.

The supplier ships it with the batch; the customer scans the QR code and verifies the Ed25519
signature and the record hashes. It turns "we inspected it" into evidence that survives a
debit-note dispute.
"""
from __future__ import annotations

import base64
import hashlib
import html
import io
import json
import time
import uuid
from pathlib import Path

import qrcode
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

KEY_FILE = Path(__file__).resolve().parents[2] / "data" / "station_ed25519.pem"
STORE: dict[str, dict] = {}


def _key() -> Ed25519PrivateKey:
    if KEY_FILE.exists():
        return serialization.load_pem_private_key(KEY_FILE.read_bytes(), password=None)
    k = Ed25519PrivateKey.generate()
    KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    KEY_FILE.write_bytes(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                         serialization.NoEncryption()))
    return k


def _pub_b64() -> str:
    raw = _key().public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode()


def issue(session, base_url: str) -> dict:
    recs = [r for r in session.records if not r.ghost]
    chain, prev = [], "0" * 64
    for r in recs:
        body = json.dumps({"id": r.id, "decision": r.decision, "score": r.score, "review": r.review.get("final")},
                          sort_keys=True)
        h = hashlib.sha256((prev + body).encode()).hexdigest()
        chain.append({"id": r.id, "decision": r.decision, "hash": h})
        prev = h
    pol = session.cal.policy
    counts = {k: sum(1 for r in recs if r.decision == k) for k in ("PASS", "FAIL", "DOUBT")}
    reviewed = sum(1 for r in recs if r.decision == "DOUBT" and r.review.get("final") in ("GOOD", "DEFECT"))
    claim = {
        "certificate": f"CERT-{uuid.uuid4().hex[:10].upper()}",
        "issued": time.strftime("%Y-%m-%d %H:%M:%S"),
        "station": session.plant,
        "product": f"{session.source}/{session.name}",
        "parts": len(recs), "autoPassed": counts["PASS"], "rejected": counts["FAIL"], "sentToHuman": counts["DOUBT"],
        "humanResolved": reviewed,
        "guarantee": {
            "goodPartFalseRejectBound": pol.alpha_fr,
            "estimatedEscapeRate": round(pol.promised_escape, 4),
            "escapeUpper90": round(pol.escape_upper_90, 4),
            "calibration": f"{pol.n_good_calib} good (leave-one-out) + {pol.n_defect_calib} defects (5 real + imagined)",
            "shiftAlarmDuringBatch": bool(session.guard.alarmed),
        },
        "model": "DINOv2-S/14 patch memory + split-conformal two-threshold policy",
        "chainHead": prev,
        "records": len(chain),
    }
    payload = json.dumps(claim, sort_keys=True).encode()
    sig = base64.b64encode(_key().sign(payload)).decode()
    cid = claim["certificate"]
    url = base_url.rstrip("/") + f"/verify/{cid}"
    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    doc = {"claim": claim, "signature": sig, "publicKey": _pub_b64(), "chain": chain, "verifyUrl": url,
           "qr": "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()}
    STORE[cid] = doc
    return doc


def get(cid: str) -> dict | None:
    return STORE.get(cid)


def verify(doc: dict) -> tuple[bool, bool]:
    payload = json.dumps(doc["claim"], sort_keys=True).encode()
    pub = Ed25519PublicKey.from_public_bytes(base64.b64decode(doc["publicKey"]))
    try:
        pub.verify(base64.b64decode(doc["signature"]), payload)
        sig_ok = True
    except Exception:
        sig_ok = False
    chain_ok = (doc["chain"][-1]["hash"] if doc["chain"] else "0" * 64) == doc["claim"]["chainHead"]
    return sig_ok, chain_ok


def verify_html(cid: str) -> str:
    doc = STORE.get(cid)
    if not doc:
        return "<h1>Certificate not found</h1>"
    sig_ok, chain_ok = verify(doc)
    c = doc["claim"]
    g = c["guarantee"]
    ok = sig_ok and chain_ok
    e = html.escape
    rows = "".join(f"<tr><td>{e(k)}</td><td>{e(str(v))}</td></tr>" for k, v in c.items() if not isinstance(v, dict))
    grows = "".join(f"<tr><td>{e(k)}</td><td>{e(str(v))}</td></tr>" for k, v in g.items())
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sandeha Certificate {e(cid)}</title><style>
:root{{--bg:#0b1020;--fg:#e8ecf5;--mut:#93a0b8;--ok:#34d399;--bad:#f87171;--card:#121a30}}
@media (prefers-color-scheme: light){{:root{{--bg:#f6f7fb;--fg:#101528;--mut:#5b6478;--card:#fff}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif;padding:16px}}
.card{{max-width:640px;margin:auto;background:var(--card);border-radius:16px;padding:20px}}
.badge{{font-weight:700;font-size:20px;color:{'var(--ok)' if ok else 'var(--bad)'}}}
table{{width:100%;border-collapse:collapse}}td{{padding:6px 4px;border-bottom:1px solid #8882;vertical-align:top}}
td:first-child{{color:var(--mut);width:45%}}code{{word-break:break-all;font-size:12px}}</style></head><body><div class="card">
<div class="badge">{'✔ Signature valid · record chain intact' if ok else '✘ Verification failed'}</div>
<p style="color:var(--mut)">Signed by the inspection station with Ed25519. Any edit to a single decision breaks the hash chain.</p>
<table>{rows}</table><h3>Guarantee</h3><table>{grows}</table>
<p style="color:var(--mut)">Public key: <code>{e(doc['publicKey'])}</code></p></div></body></html>"""
