# OWNER: Member 2
# Measured evaluation on synthetic labelled data. Numbers are computed live (and cached),
# never typed in by hand. Run directly to print the report:  python -m ai.evaluation  (from backend/)
import io
import json
import statistics
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from . import decision, documents, names, scam

DATA = Path(__file__).parent / "data"
_CACHE: Dict[str, Any] = {}
_LOCK = threading.Lock()


def _load(name: str) -> Any:
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def _timed(fn: Callable, items: List[Any]) -> Tuple[List[Any], float]:
    out, durations = [], []
    for item in items:
        t = time.perf_counter()
        out.append(fn(item))
        durations.append((time.perf_counter() - t) * 1000)
    return out, round(statistics.mean(durations), 3) if durations else 0.0


# ---------------------------------------------------------------------------
def _scam_split(rows: List[Dict[str, str]]) -> Dict[str, Any]:
    results, ms = _timed(lambda r: scam.classify(r["text"]), rows)
    tp = fp = tn = fn = unsure_scam = unsure_legit = 0
    errors = []
    for row, res in zip(rows, results):
        flagged = res["label"] == "likely_scam"
        if res["label"] == "uncertain":
            if row["label"] == "scam":
                unsure_scam += 1
            else:
                unsure_legit += 1
        if row["label"] == "scam":
            tp += flagged
            fn += not flagged
        else:
            fp += flagged
            tn += not flagged
        wrong = flagged != (row["label"] == "scam")
        if wrong or res["label"] == "uncertain":
            errors.append({"text": row["text"], "expected": row["label"], "got": res["label"], "score": res["score"]})
    scams, legit = tp + fn, fp + tn
    return {
        "test_cases": len(rows), "scam_messages": scams, "legit_messages": legit,
        "correct": tp + tn, "accuracy": round((tp + tn) / len(rows), 3),
        "false_alarm_rate": round(fp / legit, 3) if legit else None,
        "missed_scam_rate": round(fn / scams, 3) if scams else None,
        "precision": round(tp / (tp + fp), 3) if tp + fp else None,
        "recall": round(tp / scams, 3) if scams else None,
        "uncertain_on_scam": unsure_scam, "uncertain_on_legit": unsure_legit,
        # second operating point: the citizen sees a warning for 'likely_scam' OR 'uncertain'
        "scams_warned_rate": round((tp + unsure_scam) / scams, 3) if scams else None,
        "legit_warned_rate": round((fp + unsure_legit) / legit, 3) if legit else None,
        "avg_latency_ms": ms, "errors_and_uncertain": errors,
    }


def eval_scam() -> Dict[str, Any]:
    data = _load("scam_sms.json")
    dev, hold = _scam_split(data["dev"]), _scam_split(data["holdout"])
    combined = _scam_split(data["dev"] + data["holdout"])
    return {
        "rule": ("flagged (scam_flag=true) = label 'likely_scam' (score >= %.2f); 'uncertain' counts as NOT flagged "
                 "in the rates. scams_warned_rate / legit_warned_rate count 'uncertain' too (citizen sees a warning)."
                 % scam.LIKELY),
        "combined": {k: v for k, v in combined.items() if k != "errors_and_uncertain"},
        "dev": dev, "holdout": hold,
        "note": "Dev set was used to build the rules, so its numbers are optimistic. Holdout was written before "
                "testing and NOT used to tune rules: treat holdout as the honest estimate. Small synthetic sets: "
                "one message changes a rate by several points.",
        "disclosure": "One rule change was made after the first holdout run: the fee-request weight went from "
                      "0.55 to 0.60 so the team-contract example 'Send a processing fee to receive relief' is "
                      "flagged on its own. First holdout run (before the change): 17/24 correct, 0/12 false alarms, "
                      "7/12 scams only 'uncertain'.",
    }


def eval_names() -> Dict[str, Any]:
    pairs = _load("name_pairs.json")["pairs"]
    results, ms = _timed(lambda p: names.match_names(p[0], p[1]), pairs)
    false_match = false_non_match = 0
    rows = []
    for (a, b, expected), res in zip(pairs, results):
        auto = res["score"] >= names.CONFIRMED
        if expected == "match" and not auto:
            false_non_match += 1
        if expected != "match" and auto:
            false_match += 1
        rows.append({"a": a, "b": b, "expected": expected, "score": res["score"], "verdict": res["verdict"]})
    matches = sum(1 for p in pairs if p[2] == "match")
    others = len(pairs) - matches
    return {
        "test_cases": len(pairs), "correct": len(pairs) - false_match - false_non_match,
        "accuracy": round((len(pairs) - false_match - false_non_match) / len(pairs), 3),
        "false_auto_match_rate": round(false_match / others, 3),
        "missed_match_rate": round(false_non_match / matches, 3),
        "avg_latency_ms": ms, "pairs": rows,
        "note": "False auto-match (wrong person confirmed) is the dangerous error; a missed match only sends the case to an officer.",
    }


def eval_routing() -> Dict[str, Any]:
    cases = _load("routing_cases.json")["cases"]
    results, ms = _timed(
        lambda c: decision.evaluate(c["id"], "eval", c["input"], supplied_rules=c.get("rules") or dict(decision.DEFAULT_POLICY)),
        cases)
    wrong = [{"id": c["id"], "expected": c["expected"], "got": r["route"], "confidence": r["confidence"]}
             for c, r in zip(cases, results) if r["route"] != c["expected"]]
    unsafe = [w for w in wrong if w["got"] == "cleared"]
    return {
        "test_cases": len(cases), "correct_routes": len(cases) - len(wrong),
        "accuracy": round((len(cases) - len(wrong)) / len(cases), 3),
        "unsafe_auto_clears": len(unsafe), "errors": wrong, "avg_latency_ms": ms,
        "note": "Expected routes come from the written policy table, so this measures conformance to the spec.",
    }


def eval_extraction() -> Dict[str, Any]:
    samples = _load("document_texts.json")["samples"]
    total = correct = invented = 0
    errors = []
    t0 = time.perf_counter()
    for s in samples:
        fields = documents.extract_fields(s["text"], s["type"])
        for key, want in s["expected"].items():
            got = fields.get(key, {}).get("value")
            total += 1
            ok = (str(got).casefold() == str(want).casefold()) if want is not None else got is None
            correct += ok
            if want is None and got is not None:
                invented += 1
            if not ok:
                errors.append({"type": s["type"], "field": key, "expected": want, "got": got})
    return {
        "documents": len(samples), "fields_checked": total, "fields_correct": correct,
        "field_accuracy": round(correct / total, 3), "invented_values": invented, "errors": errors,
        "avg_latency_ms": round((time.perf_counter() - t0) * 1000 / len(samples), 3),
        "note": "Field reading from synthetic OCR text. Image OCR itself needs Tesseract (optional).",
    }


# ---------------------------------------------------------------------------
# synthetic ID cards for the image-quality check
# ---------------------------------------------------------------------------
def _font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def synthetic_card(name: str = "Muhammad Ali", ident: str = "MOCK-123456", size=(1000, 630)) -> Image.Image:
    img = Image.new("RGB", size, (232, 240, 228))
    d = ImageDraw.Draw(img)
    w, h = size
    d.rectangle([0, 0, w, int(h * 0.16)], fill=(24, 94, 60))
    d.text((int(w * 0.04), int(h * 0.04)), "SPECIMEN - SYNTHETIC ID (NOT REAL)", fill="white", font=_font(int(h * 0.06)))
    d.rectangle([int(w * 0.04), int(h * 0.24), int(w * 0.28), int(h * 0.80)], outline=(60, 60, 60), width=3, fill=(200, 205, 200))
    lines = [f"Name: {name}", "Father Name: Abdul Rahim", f"Identity Number: {ident}", "Date of Birth: 12.05.1990"]
    for i, line in enumerate(lines):
        d.text((int(w * 0.33), int(h * (0.26 + i * 0.13))), line, fill=(20, 20, 20), font=_font(int(h * 0.055)))
    return img


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def quality_cases() -> List[Tuple[str, Image.Image, bool]]:
    base = synthetic_card()
    return [
        ("sharp", base, True),
        ("sharp_phone_size", base.resize((1600, 1008)), True),
        ("sharp_small_but_ok", base.resize((640, 403)), True),
        ("very_slight_blur_r0.6", base.filter(ImageFilter.GaussianBlur(0.6)), True),
        ("slightly_dim", ImageEnhance.Brightness(base).enhance(0.75), True),
        ("jpeg_like_noise", base.filter(ImageFilter.SMOOTH), True),
        ("blur_r2", base.filter(ImageFilter.GaussianBlur(2)), False),
        ("blur_r3", base.filter(ImageFilter.GaussianBlur(3)), False),
        ("blur_r5", base.filter(ImageFilter.GaussianBlur(5)), False),
        ("blur_r8", base.filter(ImageFilter.GaussianBlur(8)), False),
        ("too_dark", ImageEnhance.Brightness(base).enhance(0.12), False),
        ("overexposed", ImageEnhance.Brightness(base).enhance(3.5), False),
        ("faded", ImageEnhance.Contrast(base).enhance(0.12), False),
        ("tiny", base.resize((180, 113)), False),
    ]


def eval_quality() -> Dict[str, Any]:
    cases = quality_cases()
    rows, durations = [], []
    for label, img, expected_ok in cases:
        t = time.perf_counter()
        q = documents.image_quality(documents.load_image(_png(img)))
        durations.append((time.perf_counter() - t) * 1000)
        rows.append({"case": label, "expected_ok": expected_ok, "quality": q["quality"], "quality_ok": q["quality_ok"],
                     "main_issue": q["main_issue"], "laplacian_variance": q["metrics"]["laplacian_variance"]})
    wrong = [r for r in rows if r["quality_ok"] != r["expected_ok"]]
    accepted_bad = [r for r in wrong if r["quality_ok"]]
    return {
        "test_cases": len(rows), "correct": len(rows) - len(wrong), "accuracy": round((len(rows) - len(wrong)) / len(rows), 3),
        "bad_images_accepted": len(accepted_bad), "good_images_rejected": len(wrong) - len(accepted_bad),
        "avg_latency_ms": round(statistics.mean(durations), 2), "cases": rows,
        "note": "Generated synthetic cards with controlled blur/exposure/contrast/size.",
    }


# ---------------------------------------------------------------------------
def run_all() -> Dict[str, Any]:
    t = time.perf_counter()
    s = eval_scam()
    report = {
        "model_version": decision.MODEL_VERSION,
        "evaluated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scam_detection": {**s["combined"],
                           "dev": {k: v for k, v in s["dev"].items() if k != "errors_and_uncertain"},
                           "holdout": {k: v for k, v in s["holdout"].items() if k != "errors_and_uncertain"},
                           "rule": s["rule"], "note": s["note"], "disclosure": s["disclosure"],
                           "errors_and_uncertain": s["dev"]["errors_and_uncertain"] + s["holdout"]["errors_and_uncertain"]},
        "name_matching": eval_names(),
        "routing": eval_routing(),
        "ocr": {"field_extraction": eval_extraction(), "image_quality": eval_quality(),
                "ocr_engine": documents.ocr_engine() or "not installed (fields from images need Tesseract)"},
        "note": "Evaluated on synthetic labelled datasets written by the team. Not a production guarantee.",
    }
    report["evaluation_seconds"] = round(time.perf_counter() - t, 2)
    return report


def scam_summary() -> Dict[str, Any]:
    """Cheap, cached scam-only numbers (used in every /scam-check reply)."""
    with _LOCK:
        if "scam" not in _CACHE:
            _CACHE["scam"] = eval_scam()["combined"]
        return _CACHE["scam"]


def metrics(refresh: bool = False) -> Dict[str, Any]:
    with _LOCK:
        if refresh or "report" not in _CACHE:
            _CACHE["report"] = run_all()
        return _CACHE["report"]


if __name__ == "__main__":  # pragma: no cover
    print(json.dumps(run_all(), indent=2, ensure_ascii=False))
