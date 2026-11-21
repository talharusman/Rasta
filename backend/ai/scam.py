# OWNER: Member 2
# Explainable scam-SMS classifier: weighted regex signals (English + Roman Urdu),
# combined with a noisy-OR. No model download, deterministic, fast.
#
# Labels: likely_scam (score >= 0.60) | uncertain (0.30-0.60) | no_scam_indicators (< 0.30)
# Measured results on our synthetic set: see evaluation.py / GET /api/ai/metrics.
import re
from dataclasses import dataclass
from typing import Dict, List, Pattern

LIKELY = 0.60
UNSURE = 0.30


@dataclass(frozen=True)
class Signal:
    key: str
    label: str          # shown to the citizen
    weight: float       # 0..1, combined with noisy-OR
    pattern: Pattern
    negatable: bool = False  # ignore when the text is safety advice ("never share your OTP")


def _p(*alternatives: str) -> Pattern:
    return re.compile("|".join(f"(?:{a})" for a in alternatives), re.IGNORECASE)


SIGNALS: List[Signal] = [
    Signal("otp_request", "asks for an OTP / PIN / password", 0.55, _p(
        r"\botp\b", r"\bpin\b", r"one[\s-]?time\s+(?:pin|password|code)", r"verification\s+code",
        r"\bpassword\b", r"\bcvv\b", r"\bcode\s+(?:bhej|send|share|bata)",
        r"(?:send|share|tell|give|forward|reply\s+with)\s+(?:me\s+|us\s+)?(?:the\s+|your\s+|that\s+)?(?:\d[\s-]?digit\s+)?codes?\b"),
        negatable=True),
    # 0.60 = enough on its own: relief programmes never charge a fee (team contract example).
    Signal("fee_request", "asks you to pay a fee or send money first", 0.60, _p(
        r"(?:processing|registration|service|release|clearance|activation|verification|delivery|tax)\s+(?:fee|charges?)",
        r"\bfee\b.{0,40}\b(?:pay|send|transfer|jama|bhej)", r"(?:pay|send|transfer|deposit)\s+(?:rs\.?|pkr|rupees)\s*\d",
        r"(?:send|transfer|bhej\w*)\s+(?:money|paisay|paise|raqam|amount|rs)",
        r"\bfees?\s+(?:jama|ada)\b", r"(?:easypaisa|jazz\s?cash)\s+(?:kar|kren|karein|transfer|send|to|par|pe)\b",
        r"\b(?:jama|ada)\s+kar(?:ain|ein|en|o|wa\w*)\b", r"gift\s?cards?"),
        negatable=True),
    Signal("suspicious_link", "contains a link (official notices do not ask you to click links)", 0.35, _p(
        r"https?://", r"\bwww\.", r"\b[\w-]+\.(?:xyz|top|club|online|site|info|link|click|live|icu|buzz)\b",
        r"\bbit\.ly\b", r"\btinyurl\b", r"\bclick\s+(?:here|this|the\s+link|below)\b", r"\blink\s+(?:par|pe)\s+click")),
    Signal("short_link", "uses a shortened link that hides the real address", 0.25, _p(
        r"\bbit\.ly\b", r"\btinyurl\b", r"\bt\.co/", r"\bgoo\.gl\b", r"\bcutt\.ly\b", r"\bis\.gd\b")),
    Signal("urgency", "creates urgency or pressure", 0.20, _p(
        r"limited\s+time", r"within\s+\d+\s*(?:hours?|hrs?|minutes?|mins?)", r"\btoday\s+only\b", r"\burgent(?:ly)?\b",
        r"last\s+chance", r"\bexpires?\b", r"immediately", r"instantly", r"\bact\s+now\b", r"\bforan\b", r"\bjaldi\b",
        r"warna", r"before\s+midnight")),
    Signal("prize_lure", "promises a prize, lottery or unexpected reward", 0.35, _p(
        r"congratulations?", r"you\s+(?:have\s+)?won", r"lucky\s+draw", r"\blottery\b", r"\bprize\b",
        r"\binaam\b", r"\bjeet\w*\b", r"selected\s+(?:as\s+)?(?:a\s+)?winner", r"qur['’]?a\s+andazi")),
    Signal("money_lure", "promises money if you act on the message", 0.25, _p(
        r"\bclaim\s+(?:your|rs\.?|pkr|the|now|it)\b", r"get\s+your\s+[\w\s]{0,25}(?:money|cash|payment|reward|amount)",
        r"(?:raqam|paisay)\s+(?:hasil|wusool|le)\b")),
    Signal("personal_info_request", "asks for your CNIC, bank or account details", 0.35, _p(
        r"(?:send|share|reply\s+with|provide|enter|bhej\w*|bata\w*)\s+(?:your\s+|apna\s+|apni\s+)?(?:cnic|id\s+card|bank|account|card)",
        r"(?:apna|apni|your)\s+(?:cnic|shanakhti\s+card|card|account|bank)[^.]{0,40}\b(?:bhej\w*|send|share|bata\w*)",
        r"(?:cnic|card|account)\s+(?:number|no\.?)\s+(?:bhej|send|share|reply)", r"atm\s+card",
        r"(?:cnic|shanakhti\s+card)\s+(?:ki\s+)?(?:copy|tasveer|photo)\s+(?:bhej|send)")),
    Signal("private_number", "asks you to contact or send to a personal mobile number", 0.25, _p(
        r"(?:call|whatsapp|contact|rabta|sms|bhej\w*|send)\D{0,25}(?:\+?92|0)3\d{2}[\s-]?\d{7}",
        r"(?:\+?92|0)3\d{2}[\s-]?\d{7}\D{0,20}(?:call|whatsapp|rabta|pe|par)")),
    Signal("caller_claims_official", "someone claims to be an official contacting you directly", 0.25, _p(
        r"\b(?:se|say)\s+bol\s+rah[ae]\s+h(?:oon|un|ain)\b", r"\bi\s+am\s+(?:from|calling\s+from)\s+(?:the\s+)?\w*\s*(?:office|department|bank|nadra|bisp)",
        r"\bthis\s+is\s+(?:the\s+)?\w*\s*(?:officer|office|department)\b")),
    Signal("threat", "threatens to block, cancel or fine you", 0.25, _p(
        r"(?:will\s+be|has\s+been|is)\s+(?:blocked|suspended|cancell?ed|closed)", r"\bblock\s+ho\s+ja", r"band\s+kar\s+di",
        r"legal\s+action", r"\bfine\b.{0,20}\bpay", r"khatam\s+ho\s+jaye")),
    Signal("impersonation", "uses a government scheme name to look official", 0.10, _p(
        r"\bbisp\b", r"\bbenazir\b", r"\behsaas\b", r"\bnadra\b", r"\bgovernment\s+(?:relief|scheme|fund|grant)",
        r"\bpm\s+(?:relief|package|scheme)\b", r"\bsarkari\b", r"\bhukumat\b", r"\brasta\b")),
]

# Safety advice around a negatable keyword: "never share your OTP", "OTP kisi ko na batayein".
_NEGATION = re.compile(r"\b(?:never|not|don['’]?t|do\s+not|no\s+one|nobody|won['’]?t|will\s+not|na|mat|kabhi|nahi|nahin)\b", re.I)
# A code being DELIVERED to you ("Your OTP is 482913") is not a request for one.
_DELIVERED = re.compile(r"^[\w\s]{0,20}?\b(?:is|:)\s*\d{4,8}\b", re.I)

_EXPLAIN = {
    "likely_scam": "This message shows several warning signs of a scam: {signals}. "
                   "RASTA and government relief programmes never ask for OTPs, PINs or fees by SMS.",
    "uncertain": "This message has some warning signs ({signals}), but not enough to be sure. Treat it with care.",
    "no_scam_indicators": "We did not find common scam warning signs in this message. "
                          "This does not prove it is genuine.",
}
_ACTION = {
    "likely_scam": "Do not reply, click links, share codes or send money. Contact your nearest relief office "
                   "through its official number to check.",
    "uncertain": "Do not share any code, PIN or money. Verify the message with the official helpline before acting.",
    "no_scam_indicators": "If anything in the message asks for codes, PINs or money later, stop and verify it first.",
}


def _benign(text: str, sig: Signal, m: re.Match) -> bool:
    window = text[max(0, m.start() - 40):m.start() + 30]
    if _NEGATION.search(window):
        return True
    return sig.key == "otp_request" and bool(_DELIVERED.match(text[m.end():]))


def classify(text: str) -> Dict:
    text = (text or "").strip()
    found: List[Signal] = []
    for sig in SIGNALS:
        hits = list(sig.pattern.finditer(text))
        if not hits:
            continue
        if sig.negatable and all(_benign(text, sig, m) for m in hits):
            continue  # every mention is safety advice or a delivered code
        found.append(sig)

    # A government name on its own is normal in genuine notices; it only matters
    # together with another warning sign.
    if {s.key for s in found} == {"impersonation"}:
        found = []
    remain = 1.0
    for sig in found:
        remain *= (1.0 - sig.weight)
    score = round(1.0 - remain, 3)

    if score >= LIKELY:
        label = "likely_scam"
    elif score >= UNSURE:
        label = "uncertain"
    else:
        label = "no_scam_indicators"
    confidence = round(max(score, 1.0 - score), 3)
    labels = [s.label for s in found]
    return {
        "label": label,
        "confidence": confidence,
        "score": score,
        "signals": labels,
        "signal_keys": [s.key for s in found],
        "explanation": _EXPLAIN[label].format(signals="; ".join(labels) or "none"),
        "recommended_action": _ACTION[label],
    }
