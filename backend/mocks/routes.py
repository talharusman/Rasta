# OWNER: Member 3 (fake NADRA / Raast / SMS, agent, background jobs, deployment)
from fastapi import APIRouter
from pydantic import BaseModel

from . import services

router = APIRouter(prefix="/api/mock", tags=["mock"])


class NadraRequest(BaseModel):
    cnic: str


class PayRequest(BaseModel):
    cnic: str
    amount: int


class SmsRequest(BaseModel):
    phone: str
    message: str


@router.get("/health")
def health():
    return {"service": "mock", "status": "ok"}


@router.post("/nadra/verify")
def nadra_verify(body: NadraRequest):
    person = services.find_person(body.cnic)
    if person is None:
        return {"verified": False, "note": "FAKE NADRA: person not found"}
    return {"verified": True, "name": person["name"], "note": "FAKE NADRA"}


@router.post("/raast/pay")
def raast_pay(body: PayRequest):
    return {"status": "paid", "transaction_id": "FAKE-TXN-0001",
            "cnic": body.cnic, "amount": body.amount, "note": "FAKE RAAST"}


@router.post("/sms/send")
def sms_send(body: SmsRequest):
    return {"status": "sent", "to": body.phone, "message": body.message, "note": "FAKE SMS"}
