# OWNER: Member 3
# Builds the notes packet an officer reads when the agent hands a case over.
# It states exactly why the agent stopped (with the real values), the evidence it saw,
# what it already tried, and what to ask the citizen. No decision is made here.
from typing import Any, Dict, List

_QUESTIONS = {
    "CONSENT_REQUIRED": ["Has the citizen given consent for this department to process the case? Ask them to grant it."],
    "CONSENT_REVOKED": ["The citizen (or their helper) withdrew consent. Do not process further without new consent."],
    "identity_mismatch": [
        "Is the identity number on the application correct? Ask the citizen to re-confirm it.",
        "Does the registry date of birth / status match what the citizen says?",
    ],
    "identity_not_found": ["The identity number was not found in the registry. Ask the citizen to re-check it."],
    "low_name_match": [
        "Is the applicant's name a spelling variant of the registry name, or a different person?",
        "Ask the citizen for the name exactly as it appears on their identity document.",
    ],
    "duplicate_claim": ["Which earlier claim does this duplicate? Should one be closed?"],
    "scam_suspected": ["Was the citizen pressured or tricked? Consider contacting them through a trusted channel."],
    "service_unavailable": ["An automated check could not run. Re-run it later or verify the item by hand."],
    "eligibility_failed": ["Which eligibility rule failed, and is there an exception that applies?"],
}


def _get(results: Dict[str, Any], step: str) -> Dict[str, Any]:
    out = results.get(step)
    return out if isinstance(out, dict) else {}


def _detail(flag: str, case: Dict[str, Any], results: Dict[str, Any]) -> str:
    identity, match = _get(results, "verify_mock_identity"), _get(results, "match_identity_name")
    record = identity.get("record") or {}
    if flag in ("identity_mismatch", "identity_not_found", "identity_not_verified"):
        return (f"registry status={identity.get('status')}, issues={identity.get('issues')}, "
                f"registry_name={record.get('name')!r}, applicant_name={case.get('applicant_name')!r}")
    if flag == "low_name_match":
        return (f"name_match_score={match.get('name_match_score')}, applicant_name="
                f"{case.get('applicant_name')!r}, registry_name={record.get('name')!r}")
    if flag == "duplicate_claim":
        dup = _get(results, "find_duplicate_claims")
        return f"duplicate_flag={dup.get('duplicate_flag')}, matches={dup.get('matches')}, identity_status={identity.get('status')}"
    if flag == "scam_suspected":
        scam = _get(results, "check_scam_message")
        return f"scam_flag={scam.get('scam_flag')}, score={scam.get('score')}, reasons={scam.get('reasons')}"
    if flag == "eligibility_failed":
        elig = _get(results, "evaluate_eligibility")
        return f"failed_rules={elig.get('failed_rules')}, rule_version={elig.get('rule_version')}"
    if flag == "service_unavailable":
        bad = {k: v.get("error") or v.get("status") for k, v in results.items()
               if isinstance(v, dict) and v.get("status") in ("unavailable", "malformed")}
        return f"steps that could not run: {bad}"
    if flag in ("CONSENT_REQUIRED", "CONSENT_REVOKED"):
        consent = results.get("check_consent")
        last = consent[-1] if isinstance(consent, list) and consent else _get(results, "check_consent")
        return f"consent check for {last.get('who')} ({last.get('grantee_id')}, scope {last.get('scope')}) returned {last.get('status')}"
    return "flag raised by the automated evaluation"


def build_officer_packet(
    case: Dict[str, Any], results: Dict[str, Any], flags: List[str], overrides: List[str],
    tried: List[str], route_reason: str = "",
) -> Dict[str, Any]:
    questions: List[str] = []
    for flag in flags:
        for q in _QUESTIONS.get(flag, []):
            if q not in questions:
                questions.append(q)
    documents = (_get(results, "analyze_document")).get("documents") or []
    evidence = [f"document {d.get('id')} ({d.get('type')}): quality={d.get('quality')}" for d in documents]
    if not documents:
        evidence.append("no documents on the case")
    identity = _get(results, "verify_mock_identity")
    evidence.append(f"identity registry: status={identity.get('status')}, issues={identity.get('issues')}")
    if "check_scam_message" in results and _get(results, "check_scam_message").get("status") != "skipped":
        evidence.append("a message was attached to the case and was scanned")
    return {
        "summary": (f"Agent stopped on case {case.get('id')} and needs an officer. "
                    f"Flags: {', '.join(flags) or 'none'}. {route_reason}").strip(),
        "why_stopped": [{"code": f, "detail": _detail(f, case, results)} for f in flags],
        "overrides_applied": list(overrides),
        "evidence": evidence,
        "what_was_tried": list(tried),
        "suggested_questions": questions or ["Review the evidence above and decide next steps."],
    }


def build_error_packet(case: Dict[str, Any], error: str, tried: List[str]) -> Dict[str, Any]:
    return {
        "summary": f"The automated run for case {case.get('id')} failed and the case was handed to an officer.",
        "why_stopped": [{"code": "agent_error", "detail": error}],
        "overrides_applied": [],
        "evidence": [],
        "what_was_tried": list(tried),
        "suggested_questions": ["Review the case from the start; automated checks did not finish."],
    }


def render_packet(packet: Dict[str, Any]) -> str:
    lines = [packet.get("summary", ""), "", "Why the agent stopped:"]
    lines += [f"  - {w['code']}: {w['detail']}" for w in packet.get("why_stopped", [])]
    if packet.get("overrides_applied"):
        lines += ["", "Overrides applied: " + ", ".join(packet["overrides_applied"])]
    lines += ["", "Evidence seen:"] + [f"  - {e}" for e in packet.get("evidence", [])]
    lines += ["", "Already tried:"] + [f"  - {t}" for t in packet.get("what_was_tried", [])]
    lines += ["", "Suggested questions:"] + [f"  - {q}" for q in packet.get("suggested_questions", [])]
    return "\n".join(lines)
