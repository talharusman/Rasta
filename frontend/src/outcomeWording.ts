// Central mapping and helper for citizen-facing case status and AI-route wording.
// Hard rule: Citizens and helpers must never see raw internal values such as AUTO_CLEAR, AUTO_APPROVE, HUMAN, needs_proof, or "Route: ...".

export function getCitizenOutcomeMessage(status?: string, aiRoute?: string, backendStatus?: string): string {
  const s = (status || "").toLowerCase().trim();
  const b = (backendStatus || "").toLowerCase().trim();
  const r = (aiRoute || "").toUpperCase().trim();

  // 1. Rejected
  if (s === "rejected" || b === "rejected") {
    return "❌ Your application could not be approved. See officer notes below.";
  }

  // 2. Verified / AUTO_CLEAR / AUTO_APPROVE / cleared / approved
  if (
    s === "verified" ||
    b === "approved" ||
    b === "cleared" ||
    r === "AUTO_CLEAR" ||
    r === "AUTO_APPROVE"
  ) {
    return "✅ Your details passed the automated checks. Your application is moving forward.";
  }

  // 3. More information / needs_proof
  if (s === "more information" || b === "needs_proof") {
    return "We need a clearer document or additional information.";
  }

  // 4. Needs review / HUMAN / human_review
  if (s === "needs review" || b === "human_review" || r === "HUMAN") {
    return "We cannot verify this confidently. An officer will review it.";
  }

  // 5. Submitted / Processing / Draft (default)
  return "⏳ Your application has been received and is being processed.";
}

export function getCitizenFriendlyStatus(status?: string, backendStatus?: string): string {
  const s = (status || "").toLowerCase().trim();
  const b = (backendStatus || "").toLowerCase().trim();

  if (s === "verified" || b === "approved" || b === "cleared") {
    return "Verified";
  }
  if (s === "needs review" || b === "human_review") {
    return "Under Review";
  }
  if (s === "more information" || b === "needs_proof") {
    return "More Information Needed";
  }
  if (s === "rejected" || b === "rejected") {
    return "Not Approved";
  }
  if (s === "checks passed") {
    return "Checks Passed";
  }
  if (s === "submitted" || b === "submitted") {
    return "Submitted";
  }
  if (s === "closed" || b === "closed") {
    return "Closed";
  }
  return "Processing";
}

export function getCitizenFriendlyRoute(aiRoute?: string): string {
  const r = (aiRoute || "").toUpperCase().trim();
  if (r === "AUTO_CLEAR" || r === "AUTO_APPROVE") {
    return "Automated Verification";
  }
  if (r === "HUMAN") {
    return "Officer Review";
  }
  return "Standard Verification";
}
