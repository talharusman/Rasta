# OWNER: Member 3
# One async handler per job kind: handler(payload, job). Raise to retry; raise
# JobFailedPermanently to fail at once. Money rules (M3_CONTEXT.md safety rule 3):
# the only place a payment is started is PaymentProvider.disburse, which pays approved
# cases only, always with key "disburse-<case_id>", and is never blindly retried:
# after any unknown outcome we reconcile (look up) first.
import asyncio
import logging
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple

from app.agent import orchestrator, platform_bridge
from app.integrations.providers import registry
from app.integrations.providers.base import AccountStatus, NotificationStatus, PaymentResult, PaymentStatus

from .queue import JobFailedPermanently, aenqueue, merge_payload

logger = logging.getLogger("m3.jobs.handlers")

CHECK_DELIVERY_DELAY = 10.0  # seconds after sending before we look at delivery
RECONCILE_DELAY = 30.0  # seconds before the first payment reconcile
MAX_RESENDS = 1

PAYMENT_SENT_MESSAGE = "Your relief payment has been sent. (Prototype: simulated payment)"


async def _bridge(fn, *args):
    return await asyncio.to_thread(fn, *args)


async def _audit(action: str, resource: str, metadata: Dict[str, Any]) -> None:
    try:
        await _bridge(platform_bridge.log_audit, "system", "job_worker", action, resource, metadata)
    except Exception:  # auditing must never turn a finished step into a failure
        logger.exception("audit failed for %s", action)


# ---------------------------------------------------------------------------
async def process_case(payload: Dict[str, Any], job: Dict[str, Any]) -> Dict[str, Any]:
    run = await orchestrator.process_case(payload["case_id"], triggered_by="job")
    # The agent never raises and always leaves the case somewhere safe, so even a
    # "failed" run is a finished job (re-running would just be skipped).
    return {"run_id": run["id"], "run_status": run["status"]}


# ---------------------------------------------------------------------------
async def send_notification(payload: Dict[str, Any], job: Dict[str, Any]) -> Dict[str, Any]:
    case_id, recipient, message = payload["case_id"], payload["recipient"], payload["message"]
    notification_id = payload.get("notification_id")
    if notification_id is None:
        notification_id = await _bridge(platform_bridge.create_notification, case_id, recipient, message)
        if notification_id is not None:  # remember it so a retry does not create a second one
            await asyncio.to_thread(merge_payload, job["id"], {"notification_id": notification_id})

    sent = await registry.get_notification_provider().send(recipient, message, case_id)
    if sent.status != NotificationStatus.sent or not sent.message_id:
        raise RuntimeError(f"SMS not sent ({sent.status.value}): {sent.error}")
    if notification_id is not None:
        await _bridge(platform_bridge.update_notification_state, notification_id, "sent", sent.message_id)
    await aenqueue(
        "check_delivery",
        {"notification_id": notification_id, "message_id": sent.message_id, "case_id": case_id,
         "recipient": recipient, "message": message, "resends": 0},
        delay_seconds=CHECK_DELIVERY_DELAY, dedupe_key=f"check-{notification_id or job['id']}-{sent.message_id}")
    return {"message_id": sent.message_id}


async def check_delivery(payload: Dict[str, Any], job: Dict[str, Any]) -> Dict[str, Any]:
    nid, message_id, case_id = payload.get("notification_id"), payload["message_id"], payload["case_id"]
    provider = registry.get_notification_provider()
    result = await provider.status(message_id)

    async def set_state(state: str, mid: Optional[str] = None) -> None:
        if nid is not None:
            await _bridge(platform_bridge.update_notification_state, nid, state, mid)

    if result.status == NotificationStatus.delivered:
        await set_state("delivered", message_id)
        return {"state": "delivered"}
    if result.status != NotificationStatus.failed:
        # still "sent" (not delivered yet) or the gateway is unreachable: look again later
        raise RuntimeError(f"delivery not confirmed ({result.status.value}): {result.error}")

    if payload.get("resends", 0) < MAX_RESENDS:  # undeliverable: send ONE more time
        again = await provider.send(payload["recipient"], payload["message"], case_id)
        if again.status != NotificationStatus.sent or not again.message_id:
            raise RuntimeError(f"re-send failed ({again.status.value}): {again.error}")
        await set_state("resent", again.message_id)
        await aenqueue(
            "check_delivery", {**payload, "message_id": again.message_id, "resends": payload.get("resends", 0) + 1},
            delay_seconds=CHECK_DELIVERY_DELAY, dedupe_key=f"check-{nid or job['id']}-{again.message_id}")
        return {"state": "resent", "message_id": again.message_id}

    await set_state("failed", message_id)  # recorded, not lost
    await _audit("notification_failed", f"case:{case_id}",
                 {"notification_id": nid, "message_id": message_id, "resends": payload.get("resends", 0)})
    return {"state": "failed"}


# ---------------------------------------------------------------------------
async def _payment_details(case_id: str) -> Tuple[Any, str]:
    """Amount and account from the case, falling back to the active rules."""
    case = await _bridge(platform_bridge.get_case, case_id)
    rules = await _bridge(platform_bridge.get_active_rules)
    amount = next((case[k] for k in ("approved_amount", "amount") if case.get(k) not in (None, "")), None)
    if amount is None:
        amount = (rules or {}).get("payout_amount")
    account = case.get("account_id")
    if amount is None or not account:
        raise JobFailedPermanently(
            f"cannot pay case {case_id}: missing {'amount' if amount is None else 'account_id'}")
    return amount, account


class AccountValidationUnavailable(RuntimeError):
    """Raast could not be asked who owns the account. Nothing was sent to it."""


async def _prepare_payment(case_id: str) -> Tuple[Any, str]:
    """Amount and account for an approved case, after checking that the account holder
    matches the beneficiary (spec scenario 14: payment-account mismatch). An account that
    does not match is never paid: the job fails without retry, it is audited, and the case
    goes back to an officer. A case that is not approved is left for the payment adapter
    to reject (it audits that itself)."""
    amount, account = await _payment_details(case_id)
    case = await _bridge(platform_bridge.get_case, case_id)
    if str(case.get("status", "")).strip().lower() != "approved":
        return amount, account
    name = case.get("applicant_name") or case.get("name")
    if not name:
        raise JobFailedPermanently("cannot validate the payment account: the case has no beneficiary name")
    check = await registry.get_payment_provider().validate_account(account, name, case_id)
    if check.status == AccountStatus.matched:
        return amount, account
    if check.status == AccountStatus.unavailable:
        raise AccountValidationUnavailable(f"account validation unavailable: {check.error}")
    await _audit("disburse_blocked_account_mismatch", f"case:{case_id}",
                 {"account_id": account, "account_check": check.status.value, "holder_name": check.holder_name})
    try:  # more review is always the safe direction; if Member 1 forbids the move, the audit still stands
        await _bridge(platform_bridge.transition_case, case_id, "human_review", "system",
                      f"Payment blocked: account {account} is not held by the beneficiary "
                      f"({check.status.value}, holder on record: {check.holder_name!r}).")
    except Exception:
        logger.exception("could not move case %s back to human_review", case_id)
    raise JobFailedPermanently(f"payment account does not match the beneficiary ({check.status.value})")


async def _payment_succeeded(case_id: str, result: PaymentResult) -> Dict[str, Any]:
    await _audit("payment_sent", f"case:{case_id}",
                 {"transaction_id": result.transaction_id, "idempotency_key": result.idempotency_key})
    case = await _bridge(platform_bridge.get_case, case_id)
    recipient = case.get("citizen_phone") or case.get("phone") or str(case.get("citizen_id"))
    await aenqueue("send_notification",
                   {"case_id": case_id, "recipient": recipient, "message": PAYMENT_SENT_MESSAGE},
                   dedupe_key=f"notify-payment-{case_id}")
    return {"payment": "success", "transaction_id": result.transaction_id}


async def _handle_payment_result(case_id: str, result: PaymentResult, from_reconcile: bool) -> Dict[str, Any]:
    status = result.status
    if status == PaymentStatus.success:
        return await _payment_succeeded(case_id, result)
    if status == PaymentStatus.rejected_not_approved:
        await _audit("disburse_job_rejected_not_approved", f"case:{case_id}", {"error": result.error})
        raise JobFailedPermanently(f"case is not approved: {result.error}")
    if status == PaymentStatus.failed:
        await _audit("disburse_job_failed", f"case:{case_id}", {"error": result.error})
        raise JobFailedPermanently(f"payment failed: {result.error}")
    # unavailable / unknown / pending: the outcome is not settled
    if from_reconcile:
        raise RuntimeError(f"payment not settled ({status.value}): {result.error}")
    await aenqueue("reconcile_payment", {"case_id": case_id}, delay_seconds=RECONCILE_DELAY,
                   dedupe_key=f"reconcile-{case_id}")
    return {"payment": status.value, "reconcile": "scheduled"}


async def disburse_case(payload: Dict[str, Any], job: Dict[str, Any]) -> Dict[str, Any]:
    case_id = payload["case_id"]
    try:
        amount, account = await _prepare_payment(case_id)  # raising here (e.g. M1 down) just retries
    except AccountValidationUnavailable:
        # Nothing was sent. Same safe path as an unknown payment: look again later (reconcile).
        await aenqueue("reconcile_payment", {"case_id": case_id}, delay_seconds=RECONCILE_DELAY,
                       dedupe_key=f"reconcile-{case_id}")
        return {"payment": "not_attempted", "reconcile": "scheduled"}
    result = await registry.get_payment_provider().disburse(case_id, amount, account)
    return await _handle_payment_result(case_id, result, from_reconcile=False)


async def reconcile_payment(payload: Dict[str, Any], job: Dict[str, Any]) -> Dict[str, Any]:
    case_id = payload["case_id"]
    provider = registry.get_payment_provider()
    result = await provider.reconcile_unknown(case_id)  # lookup only
    if result.status == PaymentStatus.failed and result.no_transaction_found:
        # Raast has nothing under our key: pay ONCE more, with the same key.
        amount, account = await _prepare_payment(case_id)  # same account check before the one re-pay
        again = await provider.disburse(case_id, amount, account)
        return await _handle_payment_result(case_id, again, from_reconcile=True)
    return await _handle_payment_result(case_id, result, from_reconcile=True)


Handler = Callable[[Dict[str, Any], Dict[str, Any]], Awaitable[Optional[Dict[str, Any]]]]

HANDLERS: Dict[str, Handler] = {
    "process_case": process_case,
    "send_notification": send_notification,
    "check_delivery": check_delivery,
    "disburse_case": disburse_case,
    "reconcile_payment": reconcile_payment,
}
