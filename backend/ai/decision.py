# OWNER: Member 2
# Unified routing: combines the check results with the active rule version and returns
# route + confidence + risk + plain-language explanation + auditor trace.
#
# Routes (team contract): cleared | needs_proof | human_review.
# "cleared" only means "passed automated checks, waiting for an officer". It never
# moves money and never promises money.
#
# Routing order (Execution Plan §4):
#   1. critical flag (identity not verified, duplicate, scam, unavailable service,
#      name mismatch, name unknown, any policy critical flag)      -> human_review
#   2. income above the policy limit                               -> human_review
#   3. confidence < proof_confidence_min                           -> human_review
#   4. confidence >= clear_confidence_min and nothing missing      -> cleared
#   5. the only problems are missing / unclear proof               -> needs_proof
#   6. anything else (e.g. name only partly matches)               -> human_review
from typing import Any, Dict, List, Optional, Tuple

from . import data_sources
from .names import CONFIRMED as NAME_CONFIRMED, UNCERTAIN as NAME_UNCERTAIN

MODEL_VERSION = "m2-v1"
ROUTES = ("cleared", "needs_proof", "human_review")

DEFAULT_POLICY = {
    "clear_confidence_min": 0.95,
    "proof_confidence_min": 0.70,
    "max_monthly_income": 50000,
    "required_documents": ["identity_proof"],
    "critical_flags": [],
}
DOC_GOOD = 0.80          # document quality at or above this needs no new photo
MAX_CONFIDENCE = 0.99    # the model never claims certainty

CRITICAL = ("identity_not_verified", "identity_mismatch", "identity_not_found", "duplicate_claim",
            "scam_suspected", "service_unavailable", "low_name_match", "name_match_unknown")
PROOF = ("document_missing", "document_quality_low", "income_missing")

RISK_WEIGHTS = {
    "duplicate_claim": 0.60, "scam_suspected": 0.70, "identity_not_verified": 0.50,
    "low_name_match": 0.45, "name_match_unknown": 0.30, "name_match_uncertain": 0.20,
    "income_above_limit": 0.30, "document_quality_low": 0.10, "document_missing": 0.10,
    "income_missing": 0.05, "service_unavailable": 0.30,
}
BASE_RISK = 0.02


# ---------------------------------------------------------------------------
# thresholds: payload -> platform rules table -> built-in defaults
# ---------------------------------------------------------------------------
def _from_rules_shape(rules: Dict[str, Any]) -> Dict[str, Any]:
    """Accepts Member 1's policy dict or Member 3's {"version", "rules": [{field, op, value}]}."""
    policy: Dict[str, Any] = {}
    for key in DEFAULT_POLICY:
        if key in rules:
            policy[key] = rules[key]
    for r in rules.get("rules", []) if isinstance(rules.get("rules"), list) else []:
        if isinstance(r, dict) and r.get("field") == "monthly_income" and r.get("op") in ("lte", "lt"):
            policy["max_monthly_income"] = r.get("value")
    return policy


def resolve_policy(rule_version: Any, supplied: Optional[Dict[str, Any]], tenant_id: Optional[str]) -> Tuple[Dict[str, Any], str, Any]:
    """Returns (policy, source, version_from_source)."""
    if isinstance(supplied, dict):
        found = _from_rules_shape(supplied)
        if found:
            return {**DEFAULT_POLICY, **found}, "request", supplied.get("version", rule_version)
    src = data_sources.rule(rule_version, tenant_id)
    if src.ok and src.rows:
        row = src.rows[0]
        found = _from_rules_shape(row["conditions_json"] or {})
        return {**DEFAULT_POLICY, **found}, "platform_rules_table", row["version"]
    return dict(DEFAULT_POLICY), "built_in_defaults", None


# ---------------------------------------------------------------------------
def evaluate(case_id: Any, rule_version: Any, inp: Dict[str, Any], supplied_rules: Optional[Dict[str, Any]] = None,
             tenant_id: Optional[str] = None, extra_flags: Optional[List[str]] = None) -> Dict[str, Any]:
    policy, source, source_version = resolve_policy(rule_version, supplied_rules, tenant_id)
    clear_min = float(policy["clear_confidence_min"])
    proof_min = float(policy["proof_confidence_min"])
    max_income = policy.get("max_monthly_income")

    identity = inp.get("identity_verified") is True
    name = inp.get("name_match_score")
    doc = inp.get("document_quality")
    income = inp.get("monthly_income")
    flags: List[str] = []
    checks: Dict[str, str] = {}

    def flag(f: str) -> None:
        if f not in flags:
            flags.append(f)

    # identity
    if identity:
        checks["identity"] = "verified in mock registry"
    else:
        flag("identity_not_verified")
        checks["identity"] = "NOT verified" if inp.get("identity_verified") is False else "unknown (treated as not verified)"
    # name
    if name is None:
        flag("name_match_unknown")
        checks["name_match"] = "unknown (no registry name or check failed) - not treated as a match"
        name_part = 0.5
    else:
        name_part = float(name)
        if name_part >= NAME_CONFIRMED:
            checks["name_match"] = f"confirmed ({name_part:.2f} >= {NAME_CONFIRMED})"
        elif name_part >= NAME_UNCERTAIN:
            flag("name_match_uncertain")
            checks["name_match"] = f"uncertain ({NAME_UNCERTAIN} <= {name_part:.2f} < {NAME_CONFIRMED})"
        else:
            flag("low_name_match")
            checks["name_match"] = f"mismatch ({name_part:.2f} < {NAME_UNCERTAIN})"
    # document
    if doc is None:
        flag("document_missing")
        doc_part = 0.85
        checks["document"] = "no usable document quality (missing or not analysed)"
    else:
        q = float(doc)
        doc_part = 1.0 if q >= DOC_GOOD else 0.80 + 0.20 * (q / DOC_GOOD)
        if q < DOC_GOOD:
            flag("document_quality_low")
            checks["document"] = f"quality {q:.2f} < {DOC_GOOD} - a clearer document is needed"
        else:
            checks["document"] = f"quality {q:.2f} >= {DOC_GOOD}"
    # other signals
    if inp.get("duplicate_flag") is True:
        flag("duplicate_claim")
    if inp.get("scam_flag") is True:
        flag("scam_suspected")
    checks["duplicates"] = "possible duplicate found" if inp.get("duplicate_flag") is True else (
        "none found" if inp.get("duplicate_flag") is False else "not checked")
    checks["scam_message"] = "scam indicators found" if inp.get("scam_flag") is True else (
        "no scam indicators" if inp.get("scam_flag") is False else "no message checked")
    # eligibility
    if income is None:
        flag("income_missing")
        checks["income_threshold"] = "monthly income missing"
    elif max_income is not None and float(income) > float(max_income):
        flag("income_above_limit")
        checks["income_threshold"] = f"failed ({income} > {max_income})"
    else:
        checks["income_threshold"] = f"passed ({income} <= {max_income})" if max_income is not None else "no limit in policy"
    for f in extra_flags or []:
        flag(str(f))

    id_part = 1.0 if identity else 0.5
    confidence = round(min(MAX_CONFIDENCE, name_part * doc_part * id_part), 3)
    remain = 1.0 - BASE_RISK
    for f in flags:
        remain *= 1.0 - RISK_WEIGHTS.get(f, 0.0)
    risk = round(1.0 - remain, 3)

    critical = [f for f in flags if f in CRITICAL or f in (policy.get("critical_flags") or [])]
    proof = [f for f in flags if f in PROOF]
    other = [f for f in flags if f not in critical and f not in proof]
    if critical:
        route, why = "human_review", f"critical flag(s) {critical} always go to an officer"
    elif "income_above_limit" in flags:
        route, why = "human_review", "income above policy limit; an officer decides"
    elif confidence < proof_min:
        route, why = "human_review", f"confidence {confidence} < proof_confidence_min {proof_min}"
    elif confidence >= clear_min and not proof and not other:
        route, why = "cleared", f"confidence {confidence} >= clear_confidence_min {clear_min} and no open flags"
    elif proof and not other:
        route, why = "needs_proof", f"only missing/unclear proof {proof}; confidence {confidence} >= {proof_min}"
    else:
        route, why = "human_review", f"confidence {confidence} below clear threshold because of {other or flags}"

    explanation = explain(route, flags)
    return {
        "case_id": case_id,
        "route": route,
        "confidence": confidence,
        "risk_score": risk,
        "flags": flags,
        "rule_version": rule_version if rule_version is not None else source_version,
        "model_version": MODEL_VERSION,
        "user_explanation": explanation["user_explanation"],
        "user_explanation_ur": explanation["user_explanation_ur"],
        "missing_evidence": _missing(flags),
        "auditor_trace": {
            "model_version": MODEL_VERSION,
            "input": dict(inp),
            "checks": checks,
            "confidence_components": {"name": round(name_part, 3), "document": round(doc_part, 3),
                                      "identity": id_part, "formula": "min(0.99, name * document * identity)"},
            "risk_flags_weights": {f: RISK_WEIGHTS.get(f, 0.0) for f in flags},
            "thresholds": {"clear_confidence_min": clear_min, "proof_confidence_min": proof_min,
                           "max_monthly_income": max_income, "name_confirmed": NAME_CONFIRMED,
                           "name_uncertain": NAME_UNCERTAIN, "document_good": DOC_GOOD},
            "thresholds_source": source,
            "rule_applied": f"{rule_version if rule_version is not None else source_version} "
                            f"(clear>={clear_min}, proof>={proof_min}, max_income={max_income}, source={source})",
            "critical_flags": critical,
            "proof_flags": proof,
            "routing_reason": why,
        },
    }


def _missing(flags: List[str]) -> List[str]:
    out = []
    if "document_missing" in flags:
        out.append("identity_document")
    if "document_quality_low" in flags:
        out.append("clearer_identity_document")
    if "income_missing" in flags:
        out.append("field:monthly_income")
    return out


# ---------------------------------------------------------------------------
# plain-language explanations (Spec §07). No jargon, no promise of money.
# Urdu text: prototype translation, should be reviewed by a native speaker.
# ---------------------------------------------------------------------------
BASE = {
    "cleared": ("Your details passed the automated checks. Your application is moving forward; "
                "an officer makes the final decision.",
                "آپ کی تفصیلات خودکار جانچ میں کامیاب رہیں۔ آپ کی درخواست آگے بڑھ رہی ہے؛ حتمی فیصلہ ایک افسر کرے گا۔"),
    "needs_proof": ("We need a clearer document or additional information.",
                    "ہمیں زیادہ واضح دستاویز یا مزید معلومات درکار ہیں۔"),
    "human_review": ("We cannot verify this confidently. An officer will review it.",
                     "ہم اس کی تصدیق یقین سے نہیں کر سکے۔ ایک افسر اس کا جائزہ لے گا۔"),
}
NEXT = {
    "cleared": ("You do not need to do anything now. We will tell you when there is an update.",
                "ابھی آپ کو کچھ کرنے کی ضرورت نہیں۔ کوئی پیش رفت ہونے پر ہم آپ کو بتائیں گے۔"),
    "needs_proof": ("Please add what is asked for from your case page.",
                    "براہ کرم مطلوبہ چیز اپنے کیس کے صفحے سے شامل کریں۔"),
    "human_review": ("You do not need to do anything now. An officer may contact you.",
                     "ابھی آپ کو کچھ کرنے کی ضرورت نہیں۔ افسر آپ سے رابطہ کر سکتا ہے۔"),
}
REASONS = {
    "document_quality_low": ("The photo of your document was not clear enough to read.",
                             "آپ کی دستاویز کی تصویر واضح نہیں تھی۔"),
    "document_missing": ("An identity document has not been added yet.",
                         "شناختی دستاویز ابھی شامل نہیں کی گئی۔"),
    "income_missing": ("Your monthly income is missing from the application.",
                       "درخواست میں آپ کی ماہانہ آمدن درج نہیں ہے۔"),
    "name_match_uncertain": ("The name on your application is close to, but not the same as, the identity record.",
                             "درخواست پر درج نام شناختی ریکارڈ سے ملتا جلتا ہے مگر بالکل ایک جیسا نہیں۔"),
    "low_name_match": ("The name on your application does not match the identity record.",
                       "درخواست پر درج نام شناختی ریکارڈ سے مطابقت نہیں رکھتا۔"),
    "identity_mismatch": ("The details on your application do not match the identity record.",
                          "درخواست کی تفصیلات شناختی ریکارڈ سے مطابقت نہیں رکھتیں۔"),
    "name_match_unknown": ("We could not compare your name with the identity record.",
                           "ہم آپ کے نام کا شناختی ریکارڈ سے موازنہ نہیں کر سکے۔"),
    "identity_not_verified": ("We could not confirm your identity in the registry.",
                              "ہم رجسٹری میں آپ کی شناخت کی تصدیق نہیں کر سکے۔"),
    "identity_not_found": ("We could not find your identity record.",
                           "ہمیں آپ کا شناختی ریکارڈ نہیں ملا۔"),
    "duplicate_claim": ("We found another application that may match your details.",
                        "ہمیں ایک اور درخواست ملی ہے جو آپ کی تفصیلات سے مل سکتی ہے۔"),
    "scam_suspected": ("A message attached to your application looks like a known scam. "
                       "Do not share any codes or send money to anyone.",
                       "آپ کی درخواست کے ساتھ منسلک پیغام فراڈ جیسا لگتا ہے۔ کسی کو کوڈ نہ بتائیں اور نہ ہی رقم بھیجیں۔"),
    "service_unavailable": ("One of our checking services was not available, so a person will check instead.",
                            "ہماری جانچ کی ایک سروس دستیاب نہیں تھی، اس لیے ایک افسر جانچ کرے گا۔"),
    "income_above_limit": ("Your stated income is above the current programme limit.",
                           "آپ کی بتائی گئی آمدن پروگرام کی موجودہ حد سے زیادہ ہے۔"),
    "eligibility_failed": ("Some details do not meet the current programme rules.",
                           "کچھ تفصیلات پروگرام کے موجودہ قواعد پر پوری نہیں اترتیں۔"),
    "CONSENT_REQUIRED": ("We need your permission before we can process your application.",
                         "درخواست پر کارروائی سے پہلے ہمیں آپ کی اجازت درکار ہے۔"),
    "CONSENT_REVOKED": ("Your permission to process this application was withdrawn.",
                        "اس درخواست پر کارروائی کی اجازت واپس لے لی گئی ہے۔"),
}
# Most important first; at most MAX_REASONS shown to the citizen.
ORDER = ("scam_suspected", "CONSENT_REVOKED", "CONSENT_REQUIRED", "identity_not_found", "identity_not_verified",
         "identity_mismatch", "low_name_match", "duplicate_claim", "name_match_uncertain", "name_match_unknown",
         "income_above_limit", "eligibility_failed", "service_unavailable", "document_missing",
         "document_quality_low", "income_missing")
MAX_REASONS = 2


def explain(route: str, flags: Optional[List[str]] = None) -> Dict[str, Any]:
    if route not in ROUTES:
        raise ValueError(f"unknown route {route!r}")
    flags = [str(f) for f in (flags or [])]
    known = [f for f in ORDER if f in flags]
    if route == "cleared":
        known = []  # nothing to explain beyond "passed"
    if route == "needs_proof":
        known = [f for f in known if f in PROOF] or known
    # A name mismatch already explains an unverified identity; avoid saying both.
    if "low_name_match" in known and "identity_not_verified" in known:
        known.remove("identity_not_verified")
    chosen = known[:MAX_REASONS]
    en = [BASE[route][0]] + [REASONS[f][0] for f in chosen] + [NEXT[route][0]]
    ur = [BASE[route][1]] + [REASONS[f][1] for f in chosen] + [NEXT[route][1]]
    return {
        "user_explanation": " ".join(en) + " (Prototype)",
        "user_explanation_ur": " ".join(ur) + " (پروٹوٹائپ)",
        "reasons": [REASONS[f][0] for f in chosen],
        "next_step": NEXT[route][0],
    }
