# Member 2: AI service (`backend/ai/`)

Prototype. Synthetic data only. Rule-based and explainable, with no external AI API and no downloads.

## Setup

```bash
pip install -r backend/requirements.txt      # adds rapidfuzz, pillow, numpy
```

Environment variables (please add them to `.env.example`, which is a shared file):

| Variable | Used for | Default |
|---|---|---|
| `INTERNAL_SERVICE_KEY` | header `X-Service-Key` (Member 3's agent) | none: calls refused |
| `AI_API_KEY` | header `X-API-Key` (Member 1's `ai_call`) | none: calls refused |
| `UPLOAD_DIR` | where uploaded documents live. Must match Member 1's `upload_dir` | `uploads` |
| `AI_DUPLICATES_STRICT` | `true`: return 503 if the case DB is unreachable. `false`: answer with `complete:false` | `true` |

If neither key is set, every internal route returns 403 (it fails closed).

## Routes

| Route | Auth | Required key in reply |
|---|---|---|
| `GET /api/ai/health` | none | |
| `POST /api/ai/decide` | none | `route` (AUTO/ASK_MORE/HUMAN), now runs the real pipeline |
| `GET /api/ai/metrics` | none | measured synthetic evaluation |
| `POST /internal/ai/scam-check` | key | `label`, `confidence`, `indicators` (M1) / `scam_flag` (M3) |
| `POST /internal/ai/match-identity` | key | `name_match_score` |
| `POST /internal/ai/extract-document` | key | `quality` |
| `POST /internal/ai/detect-duplicates` | key | `duplicate_flag` |
| `POST /internal/ai/evaluate` | key | contract fields + `missing_evidence`, `user_explanation_ur` |
| `POST /internal/ai/explain` | key | `user_explanation` (`language: "ur"` for Urdu) |
| `GET /internal/ai/metrics` | key | |

Errors use the team format: `{"error": {"code", "message", "retryable"}, "request_id"}`.
I return 4xx for bad input and 5xx when I cannot answer. I never return a fake "all clear".

## For Member 3 (agent): field names

- I accept all your field names as written in FOR_MEMBER_2.md. **No changes are needed on your side.**
- `scam-check` also accepts `text` (Member 1 sends that).
- `match-identity` also accepts `{submitted_name, mock_identity_id}`, and then I look the name up in your registry.
- **extract-document needs something to analyse.** In order, I use: `document.content_base64`, then
  `document.file_path` (must be inside `UPLOAD_DIR`), then a lookup of `document.id` in Member 1's
  `case_documents` table, then `document.quality` if you send it (marked `quality_source: reported_by_caller`).
  With none of these I return **422**, and you treat that as unavailable, which routes to human_review.
- `detect-duplicates` checks Member 1's `cases` table (read-only), plus claims I have already seen, plus
  your registry (the MOCK-200003/200004 pair is caught as `possible_duplicate_identity`).
- Flags I use: `identity_not_verified`, `low_name_match` (<0.70), `name_match_uncertain` (0.70–0.95),
  `name_match_unknown`, `document_missing`, `document_quality_low` (<0.80), `duplicate_claim`,
  `scam_suspected`, `income_above_limit`, `income_missing`.

## For Member 1 (platform)

- `ai_call('/internal/ai/scam-check', {'text': ...})` with `X-API-Key = AI_API_KEY` works, and the reply passes your validation.
- `evaluate` reads thresholds from your `rules` table (read-only): `clear_confidence_min`, `proof_confidence_min`,
  `max_monthly_income`, `critical_flags`. An integer `rule_version` (or `"rules-v2"`) loads **that** version even if it
  is no longer active, so old decisions keep their rules. Without a version, I use the active rule. If the
  table is unreachable, I use built-in defaults (0.95 / 0.70 / 50000), and `auditor_trace.thresholds_source` says which source was used.
- I echo `rule_version` exactly as sent. Your `Result` schema needs an int, so please send the int version.
- **Suggestion for `shared/db.py`:** the engine has no connect timeout. When Postgres is down, psycopg can hang
  forever on Windows. I guard against this in my code, but `create_engine(DATABASE_URL, connect_args={"connect_timeout": 5})`
  would protect everyone.

## Routing (Execution Plan §4)

`confidence = min(0.99, name_score × document_factor × identity_factor)`. A null value counts as unknown and is never treated as good.
1. Critical flag (identity not verified, duplicate, scam, name mismatch or unknown, or a policy critical flag) → `human_review`
2. Income above the limit → `human_review`
3. confidence < proof_min → `human_review`
4. confidence ≥ clear_min and nothing open → `cleared` (this means passed automated checks only; it never moves money)
5. Only missing or unclear proof → `needs_proof`
6. Anything else → `human_review`

## Measured results

Run `GET /api/ai/metrics`, or `python -m ai.evaluation` from `backend/`. The data is in `data/`.
The scam set has a **dev** split (used to build the rules) and a **holdout** split (written up front, not used for tuning).
The holdout is the honest estimate. The `disclosure` field records the one change made after the first holdout run.

## Optional OCR

Without Tesseract, document images are still quality-checked (blur, exposure, contrast, size), and the fields come
back empty with "please enter manually". To read text from images: `pip install pytesseract` and install the
Tesseract program. The code uses it automatically when it is present.

## Tests

```bash
cd backend
python -m pytest tests/test_ai.py tests/test_ai_agent_integration.py -v
```
`test_ai_agent_integration.py` runs Member 3's real agent with `AI_STUB` off against this service.
