# What the Member 1 integration changes for users

RASTA now connects the claim form, automated checks, officer review, and simulated payment in one workflow. People can follow what actually happened to a claim and see what to do next.

## Citizens

- **Track a claim after submitting it.** A submitted claim is saved and picked up by the background worker. The case page updates as checks run and explains whether the claim passed the checks, needs more information, or is going to an officer for review.
- **Add proof and continue the same claim.** A citizen can upload identity and income documents. If more proof is needed, they can see what's requested and resubmit the existing claim. Retrying the same submission does not start another round of checks.
- **Control who can help.** Citizens can grant helpers permission to view, edit, upload, or submit a claim. Withdrawing a permission blocks future access covered by that permission. Withdrawing processing consent also stops pending automated checks.
- **See whether payment actually went through.** Passing the automated checks moves the claim to officer review. After an officer approves it, the case shows whether the simulated payment is queued, pending, confirmed, or failed. A transaction reference appears when the mock payment provider confirms it.
- **Receive case updates.** Case notices appear in the app. A claim with a synthetic phone number can also receive simulated SMS updates.

## Helpers and officers

- **Helpers can work on claims for citizens who authorized them.** The live workspace shows the citizens they can help, and the server checks permission again when they take an action.
- **Officers can take a case from the review queue.** After assigning a case to themselves, they can see its history and the notes explaining why it was referred. They can approve, decline, or request more evidence. If someone else updates the case first, the officer is prompted to review the latest version.
- **Approval starts one simulated payout.** Repeating the approval does not create another transfer. If the payment provider times out, RASTA checks what happened under the same payment reference before trying again.

## Admins and auditors

- **Admins can publish a new eligibility policy.** Subsequent checks use the new policy. Earlier decisions keep the version that was applied at the time.
- **Auditors can reconstruct a decision.** The case history and decision trace show what happened, which policy and model versions were used, and why the case was routed the way it was. Authorized admins can also inspect the job queue to see where work is waiting or has failed.

These features are for the synthetic RASTA demo. The live workflow requires the database migration, seeded mock fixtures, and one running worker. See [Setup and credentials](SETUP.md).
