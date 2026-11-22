type Outcome = "draft" | "submitted" | "processing" | "cleared" | "needs_proof"
  | "human_review" | "approved" | "rejected" | "closed";

const messages: Record<Outcome, string> = {
  draft: "Your application is a draft. Submit it when you’re ready.",
  submitted: "Your application was received and is waiting for checks.",
  processing: "Your application is being checked.",
  cleared: "Your application passed the automated checks. An officer will review it.",
  needs_proof: "We need a clearer document or additional information.",
  human_review: "An officer will review your application.",
  approved: "An officer approved your application. Check the payment status for updates.",
  rejected: "Your application could not be approved. See the officer’s notes.",
  closed: "This application is closed. See the case history for the outcome.",
};

const labels: Record<Outcome, string> = {
  draft: "Draft", submitted: "Submitted", processing: "Processing", cleared: "Checks Passed",
  needs_proof: "More Information Needed", human_review: "Under Review",
  approved: "Approved", rejected: "Not Approved", closed: "Closed",
};

const demoOutcomes: Record<string, Outcome> = {
  draft: "draft", submitted: "submitted", processing: "processing", "checks passed": "cleared",
  verified: "cleared", "more information": "needs_proof", "needs review": "human_review",
  approved: "approved", rejected: "rejected", closed: "closed",
};

function isOutcome(status: string): status is Outcome {
  return Object.prototype.hasOwnProperty.call(messages, status);
}

function outcome(status?: string, backendStatus?: string, aiRoute?: string): Outcome {
  if (backendStatus && isOutcome(backendStatus)) return backendStatus;
  const display = status?.trim().toLowerCase();
  if (display && Object.prototype.hasOwnProperty.call(demoOutcomes, display)) return demoOutcomes[display];
  if (aiRoute === "AUTO_CLEAR" || aiRoute === "AUTO_APPROVE") return "cleared";
  if (aiRoute === "HUMAN") return "human_review";
  return "processing";
}

export function getCitizenOutcomeMessage(status?: string, aiRoute?: string, backendStatus?: string): string {
  return messages[outcome(status, backendStatus, aiRoute)];
}

export function getCitizenFriendlyStatus(status?: string, backendStatus?: string): string {
  return labels[outcome(status, backendStatus)];
}

export function getCitizenFriendlyRoute(aiRoute?: string): string {
  if (aiRoute === "AUTO_CLEAR" || aiRoute === "AUTO_APPROVE" || aiRoute === "cleared") return "Checks Passed";
  if (aiRoute === "HUMAN" || aiRoute === "human_review") return "Officer Review";
  if (aiRoute === "needs_proof") return "More Information Needed";
  return "Standard Verification";
}
