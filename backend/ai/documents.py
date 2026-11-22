# OWNER: Member 2
# Document analysis for synthetic documents (ID card, income proof, utility bill).
#   1. Image quality: sharpness (variance of the Laplacian), exposure, contrast, resolution.
#      The worst problem decides the score, and the note tells the citizen what to fix.
#   2. Text: OCR with Tesseract when it is installed (optional), or text supplied by
#      the caller (e.g. already OCR'd). Without either, fields come back empty and
#      flagged "enter manually"; we never invent field values.
#   3. Fields: regex extraction with a confidence per field.
import io
import re
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from .names import match_names

Image.MAX_IMAGE_PIXELS = 40_000_000  # refuse decompression bombs

QUALITY_OK = 0.60
MAX_BYTES = 10 * 1024 * 1024

# Calibrated on synthetic cards in evaluation.py (sharp text ~ thousands, blur r>=2 < 60).
SHARP_LO, SHARP_HI = 40.0, 250.0

_TYPE_ALIASES = {
    "id_card": "id_card", "identity_document": "id_card", "identity_proof": "id_card", "cnic": "id_card",
    "national_id": "id_card", "income_proof": "income_proof", "salary_slip": "income_proof",
    "utility_bill": "utility_bill", "bill": "utility_bill",
}
FIELDS = {
    "id_card": ("name", "father_name", "identity_number", "date_of_birth"),
    "income_proof": ("name", "monthly_income", "employer"),
    "utility_bill": ("name", "address", "amount_due", "billing_month"),
    "unknown": ("name",),
}


class DocumentError(Exception):
    """The document cannot be analysed (not an image, too large, PDF without a reported quality...)."""


def canonical_type(doc_type: Optional[str]) -> str:
    return _TYPE_ALIASES.get(str(doc_type or "").strip().lower(), "unknown")


# ---------------------------------------------------------------------------
# 1. image quality
# ---------------------------------------------------------------------------
def _ramp(x: float, lo: float, hi: float) -> float:
    if hi == lo:
        return 1.0 if x >= hi else 0.0
    return float(max(0.0, min(1.0, (x - lo) / (hi - lo))))


def load_image(data: bytes) -> Image.Image:
    if not data:
        raise DocumentError("The file is empty.")
    if len(data) > MAX_BYTES:
        raise DocumentError("The file is larger than 10 MB.")
    if data.startswith(b"%PDF-"):
        raise DocumentError("PDF files cannot be quality-checked automatically.")
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, ValueError) as exc:
        raise DocumentError(f"The file is not a readable image ({type(exc).__name__}).")
    return ImageOps.exif_transpose(img)


def image_quality(img: Image.Image) -> Dict[str, Any]:
    gray = img.convert("L")
    width, height = gray.size
    # Measure sharpness at a fixed working size so the number does not depend on resolution.
    scale = 1000.0 / max(width, height)
    work = gray.resize((max(1, int(width * scale)), max(1, int(height * scale))), Image.BILINEAR) if scale < 1 else gray
    a = np.asarray(work, dtype=np.float64)
    if a.shape[0] < 3 or a.shape[1] < 3:
        lap_var = 0.0
    else:
        lap = (-4 * a[1:-1, 1:-1] + a[:-2, 1:-1] + a[2:, 1:-1] + a[1:-1, :-2] + a[1:-1, 2:])
        lap_var = float(lap.var())
    full = np.asarray(gray, dtype=np.float64)
    brightness, contrast = float(full.mean()), float(full.std())

    log_sharp = np.log10(max(lap_var, 1e-6))
    scores = {
        "sharpness": _ramp(log_sharp, np.log10(SHARP_LO), np.log10(SHARP_HI)),
        "exposure": min(_ramp(brightness, 25, 70), 1.0 - _ramp(brightness, 215, 250)),
        "contrast": _ramp(contrast, 12, 35),
        "resolution": _ramp(min(width, height), 150, 400),
    }
    # Darkness, fading and tiny images also lower the blur metric, so when one of
    # them is a problem it is the cause to report, not "blurry".
    problems = [k for k in ("resolution", "exposure", "contrast", "sharpness") if scores[k] < QUALITY_OK]
    worst = problems[0] if problems else min(scores, key=scores.get)
    quality = round(min(scores.values()), 3)
    notes = {
        "sharpness": "Image too blurry. Please retake in better lighting or enter fields manually.",
        "exposure": ("Image too dark. Please retake in better lighting or enter fields manually." if brightness < 128
                     else "Image too bright or has glare. Please retake without flash or enter fields manually."),
        "contrast": "Image looks faded. Please retake on a plain background or enter fields manually.",
        "resolution": "Image resolution is too low. Please retake closer to the document or enter fields manually.",
    }
    ok = quality >= QUALITY_OK
    return {
        "quality": quality, "quality_ok": ok, "quality_note": None if ok else notes[worst],
        "main_issue": None if ok else worst,
        "metrics": {"laplacian_variance": round(lap_var, 1), "brightness": round(brightness, 1),
                    "contrast": round(contrast, 1), "width": width, "height": height,
                    "scores": {k: round(v, 3) for k, v in scores.items()}},
    }


# ---------------------------------------------------------------------------
# 2. OCR (optional)
# ---------------------------------------------------------------------------
def ocr_engine() -> Optional[str]:
    try:
        import pytesseract
        return f"tesseract-{pytesseract.get_tesseract_version()}"
    except Exception:
        return None


def run_ocr(img: Image.Image) -> Optional[str]:
    if not ocr_engine():
        return None
    import pytesseract
    try:
        return pytesseract.image_to_string(img.convert("L"), timeout=5)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 3. field extraction
# ---------------------------------------------------------------------------
_NAME_CHARS = r"[A-Za-z][A-Za-z .'\-]{1,60}"
_DATE = r"(\d{1,2}[./-]\d{1,2}[./-]\d{4}|\d{4}-\d{2}-\d{2})"


def _label(text: str, labels: str, value: str) -> Optional[re.Match]:
    return re.search(rf"(?:{labels})\s*[:\-]?\s*({value})", text, re.IGNORECASE)


def _clean_name(raw: str) -> str:
    raw = re.split(r"\s{2,}|\n", raw.strip())[0]
    return re.sub(r"\s+", " ", raw).strip(" .-").title()


def _norm_date(raw: str) -> Optional[str]:
    m = re.fullmatch(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})", raw)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", raw)
        if not m:
            return None
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if not (1 <= mo <= 12 and 1 <= d <= 31 and 1900 <= y <= 2030):
        return None
    return f"{y:04d}-{mo:02d}-{d:02d}"


def _money(raw: str) -> Optional[int]:
    digits = re.sub(r"[^\d]", "", raw)
    return int(digits) if digits else None


def extract_fields(text: str, doc_type: str) -> Dict[str, Dict[str, Any]]:
    text = text or ""
    lines = "\n".join(line.strip() for line in text.splitlines())
    out: Dict[str, Dict[str, Any]] = {}

    def put(name: str, value: Any, confidence: float) -> None:
        if value not in (None, ""):
            out[name] = {"value": value, "confidence": round(confidence, 2)}

    # Name: prefer the labelled line that is NOT the father/husband line.
    m = re.search(rf"(?<!father )(?<!husband )(?<!father's )\b(?:name|naam)\s*[:\-]\s*({_NAME_CHARS})", lines, re.I)
    if m:
        put("name", _clean_name(m.group(1)), 0.9)
    if doc_type == "id_card":
        m = _label(lines, r"father(?:'s)?\s+name|husband(?:'s)?\s+name|s/o|d/o|w/o", _NAME_CHARS)
        if m:
            put("father_name", _clean_name(m.group(1)), 0.85)
        m = re.search(r"\b(\d{5})-(\d{7})-(\d)\b", lines)
        if m:
            put("identity_number", m.group(0), 0.92)
        else:
            m = re.search(r"\b(MOCK-[A-Z0-9-]+)\b", lines, re.I)
            if m:
                put("identity_number", m.group(1).upper(), 0.9)
            else:
                m = re.search(r"\b(\d{13})\b", lines)
                if m:
                    d = m.group(1)
                    put("identity_number", f"{d[:5]}-{d[5:12]}-{d[12]}", 0.7)
        m = _label(lines, r"date\s+of\s+birth|d\.?o\.?b\.?|birth\s+date", _DATE)
        if m and _norm_date(m.group(1)):
            put("date_of_birth", _norm_date(m.group(1)), 0.88)
    elif doc_type == "income_proof":
        m = _label(lines, r"(?:net\s+|gross\s+)?(?:monthly\s+)?(?:income|salary|pay)", r"(?:rs\.?|pkr)?\s*[\d,]{3,}")
        if m and _money(m.group(1)):
            put("monthly_income", _money(m.group(1)), 0.85)
        m = _label(lines, r"employer|company|organi[sz]ation", r"[A-Za-z0-9][A-Za-z0-9 &.,'\-]{1,80}")
        if m:
            put("employer", m.group(1).split("\n")[0].strip(), 0.75)
    elif doc_type == "utility_bill":
        m = _label(lines, r"address", r"[^\n]{4,120}")
        if m:
            put("address", m.group(1).strip(), 0.75)
        m = _label(lines, r"amount\s+(?:due|payable)|total\s+(?:due|payable)|payable\s+amount", r"(?:rs\.?|pkr)?\s*[\d,]{2,}")
        if m and _money(m.group(1)):
            put("amount_due", _money(m.group(1)), 0.85)
        m = _label(lines, r"billing\s+month|bill\s+month|month", r"[A-Za-z]{3,9}[\s\-]\d{2,4}")
        if m:
            put("billing_month", m.group(1).strip(), 0.8)
    return out


# ---------------------------------------------------------------------------
# full analysis
# ---------------------------------------------------------------------------
def analyse(doc_type: Optional[str], image_bytes: Optional[bytes] = None, text: Optional[str] = None,
            reported_quality: Optional[float] = None, expected: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    ctype = canonical_type(doc_type)
    quality_info: Dict[str, Any]
    ocr_used = None
    if image_bytes is not None:
        try:
            img = load_image(image_bytes)
        except DocumentError:
            if reported_quality is None:
                raise
            img = None
        if img is not None:
            quality_info = {**image_quality(img), "quality_source": "image_analysis"}
            if text is None and quality_info["quality_ok"]:
                text = run_ocr(img)
                ocr_used = ocr_engine() if text is not None else None
        else:
            quality_info = _reported(reported_quality)
    elif reported_quality is not None:
        quality_info = _reported(reported_quality)
    elif text is not None:
        quality_info = {"quality": None, "quality_ok": None, "quality_note": None, "main_issue": None,
                        "quality_source": "not_assessed_text_only"}
    else:
        raise DocumentError("No document content was provided (send a file, content_base64, file_path or text).")

    fields: Dict[str, Dict[str, Any]] = extract_fields(text, ctype) if text else {}
    q = quality_info.get("quality")
    if q is not None and q < 0.85:  # a weaker image makes every read less certain
        for f in fields.values():
            f["confidence"] = round(f["confidence"] * (0.5 + 0.5 * q / 0.85), 2)
    unread_warning = ("Field unreadable — please enter manually" if text
                      else "Automatic text reading is not available — please enter manually")
    for name in FIELDS[ctype]:
        fields.setdefault(name, {"value": None, "confidence": 0.0, "warning": unread_warning})

    flags: List[str] = []
    if expected:
        flags = _inconsistencies(fields, expected)

    if quality_info.get("quality_ok") is False:
        action = quality_info["quality_note"]
    else:
        missing = [n for n, f in fields.items() if f["value"] is None]
        weak = [n for n, f in fields.items() if f["value"] is not None and f["confidence"] < 0.8]
        if flags:
            action = "Some details differ from your form. Please check them; an officer may review the difference."
        elif missing and len(missing) == len(fields):
            action = "Please type the details from your document into the form."
        elif missing:
            action = "Please type the missing fields: " + ", ".join(n.replace("_", " ") for n in missing) + "."
        elif weak:
            action = "Confirm the " + ", ".join(n.replace("_", " ") for n in weak) + " before submitting."
        else:
            action = "Check the extracted details and confirm before submitting."
    return {
        "document_type": doc_type or ctype, "document_kind": ctype,
        **{k: v for k, v in quality_info.items()},
        "extracted_fields": fields,
        "inconsistency_flags": flags,
        "suggested_action": action,
        "text_source": "caller_text" if text and not ocr_used else (ocr_used or None),
    }


def _reported(q: float) -> Dict[str, Any]:
    q = float(q)
    ok = q >= QUALITY_OK
    return {"quality": round(q, 3), "quality_ok": ok,
            "quality_note": None if ok else "Image quality reported as low. Please retake or enter fields manually.",
            "main_issue": None if ok else "reported_low_quality", "quality_source": "reported_by_caller"}


def _inconsistencies(fields: Dict[str, Dict[str, Any]], expected: Dict[str, Any]) -> List[str]:
    flags = []
    got_name = fields.get("name", {}).get("value")
    if got_name and expected.get("name"):
        v = match_names(got_name, expected["name"])["verdict"]
        if v == "mismatch":
            flags.append("name_differs_from_form")
        elif v == "uncertain":
            flags.append("name_partially_matches_form")
    got_id = fields.get("identity_number", {}).get("value")
    want_id = expected.get("identity_number") or expected.get("mock_identity_id") or expected.get("cnic")
    if got_id and want_id and re.sub(r"\W", "", str(got_id)).upper() != re.sub(r"\W", "", str(want_id)).upper():
        flags.append("identity_number_differs_from_form")
    got_dob, want_dob = fields.get("date_of_birth", {}).get("value"), expected.get("dob") or expected.get("date_of_birth")
    if got_dob and want_dob and got_dob != (_norm_date(str(want_dob)) or str(want_dob)):
        flags.append("date_of_birth_differs_from_form")
    got_inc, want_inc = fields.get("monthly_income", {}).get("value"), expected.get("monthly_income")
    if got_inc and want_inc and abs(float(got_inc) - float(want_inc)) > 0.1 * max(float(want_inc), 1.0):
        flags.append("income_differs_from_form")
    return flags
