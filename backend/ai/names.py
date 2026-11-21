# OWNER: Member 2
# Fuzzy name matching for Pakistani names (synthetic data only).
#
# Steps: normalise -> map known spelling variants to one form -> align tokens
# (order-insensitive, with a small penalty when the order differs) -> score 0..1.
# Thresholds (team plan): >= 0.95 confirmed, 0.70-0.95 uncertain, < 0.70 mismatch.
# A score below 0.95 is NEVER treated as an automatic match.
import re
import unicodedata
from itertools import permutations
from typing import Dict, List, Optional, Tuple

from rapidfuzz import fuzz

CONFIRMED = 0.95
UNCERTAIN = 0.70

# Honorifics that carry no identity information.
_DROP = {"mr", "mrs", "ms", "miss", "dr", "sahib", "sahiba", "janab", "mst", "mosammat"}

# Spelling variants -> one canonical form. Only true transliteration variants of the
# SAME name are listed here (never different names such as Ali / Aly is left to fuzz).
_VARIANTS: Dict[str, Tuple[str, ...]] = {
    "muhammad": ("mohammad", "mohammed", "muhammed", "mohamad", "muhamad", "mohamed", "muhamed",
                 "mohd", "mohd.", "mhd", "md", "mohammod", "muhammod"),
    "zainab": ("zenab", "zaynab", "zainub", "zeinab"),
    "ayesha": ("aisha", "aysha", "aesha", "ayisha", "ayeshah"),
    "fatima": ("fatimah", "fatma", "fatema"),
    "hussain": ("husain", "hussein", "husein", "hosain"),
    "hassan": ("hasan",),
    "ahmed": ("ahmad", "ahmd"),
    "rehman": ("rahman", "rehmaan", "rahmaan"),
    "abdul": ("abdool", "abdal", "abdel"),
    "kareem": ("karim",),
    "rahim": ("raheem",),
    "siddiqui": ("siddiqi", "siddique", "siddiqee", "sidiqui"),
    "noor": ("nur", "noorh"),
    "usman": ("osman", "uthman"),
    "yousaf": ("yusuf", "yousuf", "yusaf", "yousef"),
    "qureshi": ("qurashi", "quraishi"),
    "iqbal": ("iqbaal",),
    "mehmood": ("mahmood", "mahmud", "mehmud"),
    "parveen": ("perveen", "parvin", "parween"),
    "javed": ("javaid", "jawed"),
    "shazia": ("shaziya",),
    "tariq": ("tarik", "tareq"),
    "khatoon": ("khatun",),
    "farooq": ("faruq", "farook"),
    "zahid": ("zaheed",),
}
_CANON = {v: k for k, vs in _VARIANTS.items() for v in vs}

INITIAL_CREDIT = 0.75   # "M." against "Muhammad": plausible, never certain
MISSING_TOKEN_CREDIT = 0.5  # a name part present on one side only
ORDER_PENALTY = 0.9     # "Ali Muhammad" vs "Muhammad Ali" are often different people


def normalise(name: Optional[str]) -> List[str]:
    """Lowercase, strip accents/punctuation, drop honorifics, canonicalise variants."""
    if not name:
        return []
    text = unicodedata.normalize("NFKD", str(name))
    text = "".join(c for c in text if not unicodedata.combining(c)).casefold()
    text = re.sub(r"[^a-z\s.]", " ", text)
    tokens = []
    for raw in text.replace(".", ". ").split():
        is_initial = raw.endswith(".") and len(raw.rstrip(".")) == 1
        tok = raw.strip(".")
        if not tok or tok in _DROP:
            continue
        if tok in _CANON and not is_initial:
            tok = _CANON[tok]
        tokens.append(tok)
    return tokens


def _token_sim(a: str, b: str) -> float:
    if a == b:
        return 1.0
    if len(a) == 1 or len(b) == 1:  # an initial
        return INITIAL_CREDIT if a[0] == b[0] else 0.0
    return fuzz.ratio(a, b) / 100.0


def _align(short: List[str], long: List[str]) -> Tuple[float, bool, List[Tuple[str, str, float]]]:
    """Best one-to-one assignment of short tokens onto long tokens.
    Returns (sum of similarities, order_preserved, pairs)."""
    best = (-1.0, True, [])
    if len(long) > 7:  # names are short; fall back to greedy for absurd inputs
        used, pairs, total = set(), [], 0.0
        for s in short:
            j, sim = max(((j, _token_sim(s, t)) for j, t in enumerate(long) if j not in used),
                         key=lambda x: x[1], default=(None, 0.0))
            if j is not None:
                used.add(j)
                pairs.append((s, long[j], sim))
                total += sim
        return total, True, pairs
    for perm in permutations(range(len(long)), len(short)):
        total = sum(_token_sim(s, long[j]) for s, j in zip(short, perm))
        ordered = list(perm) == sorted(perm)
        # prefer the order-preserving assignment on ties
        if total > best[0] + 1e-9 or (abs(total - best[0]) <= 1e-9 and ordered and not best[1]):
            best = (total, ordered, [(s, long[j], round(_token_sim(s, long[j]), 3)) for s, j in zip(short, perm)])
    return best


def match_names(a: Optional[str], b: Optional[str]) -> Dict:
    """Score two names. Returns {"score", "verdict", "notes", "normalised"}."""
    ta, tb = normalise(a), normalise(b)
    if not ta or not tb:
        return {"score": 0.0, "verdict": "insufficient_data",
                "notes": ["One of the names is empty, so no match can be made."],
                "normalised": [" ".join(ta), " ".join(tb)]}
    short, long = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    total, ordered, pairs = _align(short, long)
    missing = len(long) - len(short)
    score = (total + MISSING_TOKEN_CREDIT * missing) / len(long)
    notes: List[str] = []
    if not ordered and len(short) > 1:
        score *= ORDER_PENALTY
        notes.append("Name parts appear in a different order.")
    if missing:
        notes.append(f"{missing} name part(s) appear on only one side.")
    if any(len(s) == 1 or len(t) == 1 for s, t, _ in pairs):
        notes.append("An initial or abbreviation was used; it cannot confirm the full name.")
    raw_a = [t.strip(".") for t in str(a).casefold().replace(".", ". ").split()]
    if any(t in _CANON for t in raw_a) or any(t in _CANON for t in str(b).casefold().split()):
        notes.append("Known spelling variants were treated as the same name.")
    score = round(max(0.0, min(1.0, score)), 3)
    return {"score": score, "verdict": verdict(score), "notes": notes,
            "normalised": [" ".join(ta), " ".join(tb)]}


def verdict(score: float) -> str:
    if score >= CONFIRMED:
        return "confirmed"
    if score >= UNCERTAIN:
        return "uncertain"
    return "mismatch"
