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
from app.integrations.providers.base import NotificationStatus, PaymentResult, PaymentStatus

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
    run = await orchestrator.process_case(payload["case_id"], triggered_by="job", generation=payload.get("generation"))
    if platform_bridge.is_live():
        if run["status"] == "running":
            raise RuntimeError("An earlier agent run is still finishing")
        if run["status"] == "failed":
            case = await _bridge(platform_bridge.get_case, payload["case_id"])
            if case["status"] in ("submitted", "processing") and case["submission_count"] == payload.get("generation"):
                raise RuntimeError("Could not persist the processing outcome")
        await asyncio.to_thread(merge_payload, job["id"], {"agent_run_id": run["id"]})
    return {"run_id": run["id"], "run_status": run["status"]}


# ---------------------------------------------------------------------------
async def send_notification(payload: Dict[str, Any], job: Dict[str, Any]) -> Dict[str, Any]:
    case_id, recipient, message = payload["case_id"], payload["recipient"], payload["message"]
    notification_id = payload.get("notification_id")
    if notification_id is None:
        if platform_bridge.is_live():
            notification_id = await _bridge(platform_bridge.create_notification, case_id, recipient, message,
                                            f"notify-job-{job['id']}")
        else:
            notification_id = await _bridge(platform_bridge.create_notification, case_id, recipient, message)
        if notification_id is not None:  # remember it so a retry does not create a second one
            await asyncio.to_thread(merge_payload, job["id"], {"notification_id": notification_id})

    dedupe = {"idempotency_key": f"sms-{job['id']}"} if platform_bridge.is_live() else {}
    sent = await registry.get_notification_provider().send(recipient, message, case_id, **dedupe)
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
        dedupe = {"idempotency_key": f"sms-resend-{job['id']}"} if platform_bridge.is_live() else {}
        again = await provider.send(payload["recipient"], payload["message"], case_id, **dedupe)
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
    amount = next((case[k] for k in ("approved_amount", "amount") if case.get(k) not in (None, "")), None)
    if amount is None and not platform_bridge.is_live():
        rules = await _bridge(platform_bridge.get_active_rules)
        amount = (rules or {}).get("payout_amount")
    account = case.get("account_id")
    if amount is None or not account:
        raise JobFailedPermanently(
            f"cannot pay case {case_id}: missing {'amount' if amount is None else 'account_id'}")
    return amount, account


async def _payment_succeeded(case_id: str, result: PaymentResult) -> Dict[str, Any]:
    await _audit("payment_sent", f"case:{case_id}",
                 {"transaction_id": result.transaction_id, "idempotency_key": result.idempotency_key})
    case = await _bridge(platform_bridge.get_case, case_id)
    recipient = case.get("citizen_phone") or case.get("phone")
    if platform_bridge.is_live() and not recipient:
        await _bridge(platform_bridge.create_notification, case_id, str(case["citizen_id"]),
                      PAYMENT_SENT_MESSAGE, f"notify-payment-{case_id}")
        return {"payment": "success", "transaction_id": result.transaction_id}
    recipient = recipient or str(case.get("citizen_id"))
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
    amount, account = await _payment_details(case_id)  # raising here (e.g. M1 down) just retries
    result = await registry.get_payment_provider().disburse(case_id, amount, account)
    return await _handle_payment_result(case_id, result, from_reconcile=False)


async def reconcile_payment(payload: Dict[str, Any], job: Dict[str, Any]) -> Dict[str, Any]:
    case_id = payload["case_id"]
    provider = registry.get_payment_provider()
    result = await provider.reconcile_unknown(case_id)  # lookup only
    if result.status == PaymentStatus.failed and result.no_transaction_found:
        # Raast has nothing under our key: pay ONCE more, with the same key.
        amount, account = await _payment_details(case_id)
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
