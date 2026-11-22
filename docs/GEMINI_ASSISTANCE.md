# Gemini and OpenRouter officer assistance

The selected provider can suggest fields from the approved synthetic evidence files and arrange
recorded facts into a short officer summary. The platform saves the official
rule-based outcome first. Suggestions appear in the authorized case
view under **Gemini officer assistance** or **OpenRouter officer assistance**. Officers can continue their review
while assistance is queued or unavailable.

## Enable it locally

Install the backend requirements after pulling the change. Set these values in
the root `.env` and restart the backend. Keep the rest of your existing settings.

```dotenv
AI_ASSIST_PROVIDER=gemini
GEMINI_API_KEY=<your Google Gemini key>
GEMINI_MODEL=gemini-3.5-flash-lite
AI_ASSIST_TIMEOUT_SECONDS=15
AI_STUB=false
AGENT_MODE=deterministic
RUN_JOB_WORKER=true
```

Run one worker. Keep `AI_BASE_URL` pointed at your own FastAPI backend. Only the
backend uses the Gemini key. Set `AI_ASSIST_PROVIDER=off` to return to the local workflow. An unset or blank
selector still honors the original `GEMINI_ENABLED` flag. The worker adds assistance only for new decisions in `DEMO_TENANT_ID`.
Deploy the `docs/gemini-fixtures/manifest.json` file with the backend. The
existing PostgreSQL schema suffices.

## Use OpenRouter instead

Set these in the server's root `.env` and restart the worker:

```dotenv
AI_ASSIST_PROVIDER=openrouter
OPENROUTER_API_KEY=<your OpenRouter key>
OPENROUTER_MODEL=openrouter/free
```

The same fixture allowlist and JSON validation apply. OpenRouter selects a free
model that supports the requested input and output format. The decision trace
records the model returned by OpenRouter for each call. If no compatible free
model is available or the request is limited, the officer can use the local
decision trace and notes. Gemini and OpenRouter are selected explicitly and
use separate credentials. [OpenRouter Free Models Router](https://openrouter.ai/openrouter/free)

## Manual checks

1. Submit a claim for Muhammad Ali (`MOCK-123456`, `MOCK-ACCOUNT-001`) with
   income of PKR 20,000 and processing consent. Upload the original
   [identity proof](gemini-fixtures/identity_proof.png) and
   [income proof](gemini-fixtures/income_proof.png). Compare the suggestions
   with the images and check the summary against the official decision trace.
2. Resize one sample, upload an unrelated image, and try a PDF. The changed
   images and PDF should skip Gemini vision and retain local evidence handling.
   The summary may still use the saved decision facts.
3. Submit a different declared income with the approved income image. The
   officer should see the suggested amount and a conflict marker. The declared
   amount and official decision remain those recorded by the platform.
4. Try a missing or invalid Gemini key. The claim should still finish with its
   local outcome and officer notes. Review the restricted decision trace for
   the fallback reason.
5. Withdraw consent, resubmit, or complete officer review while assistance is
   queued. Stale suggestions should be discarded. Confirm that citizen and
   helper sessions cannot retrieve the decision trace.
6. Repeat the clean scenario with Gemini disabled, using a fresh eligible case.
   Compare the local route, pinned policy, and simulated payout requirements.
   They should match. Only the officer assistance should differ.

For additional AI workflows and local setup, see [Member 2 integration](AI_INTEGRATION.md).
