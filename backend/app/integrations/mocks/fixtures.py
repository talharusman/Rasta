# OWNER: Member 3
# Seed data for the mocks. ALL people below are fictional.
# CLI (run from backend/):  python -m app.integrations.mocks.fixtures --reset
import argparse
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from .models import (
    MOCK_MODELS,
    MockAccount,
    MockFixtureState,
    MockIdentityRecord,
    MockSmsMessage,
    MockTransaction,
)

# (cit_id, full_nm, father_nm, birth_dt, gndr, dist, rec_status, acct, account holder)
# holder None -> same as full_nm; acct None -> identity has no account.
DEMO = [
    ("MOCK-123456", "Muhammad Ali", "Abdul Rahim", "1990-05-12", "M", "Lahore", "ACTIVE", "MOCK-ACCOUNT-001", None),
    ("MOCK-200001", "Zenab Bibi", "Ghulam Nabi", "1988-11-02", "F", "Multan", "ACTIVE", "MOCK-ACCOUNT-002", None),
    # No birth date on record.
    ("MOCK-200002", "Rashid Khan", "Sher Khan", None, "M", "Peshawar", "ACTIVE", "MOCK-ACCOUNT-003", None),
    # Near-duplicate names, same birth date.
    ("MOCK-200003", "Mohammad Ali", "Abdul Karim", "1985-03-14", "M", "Karachi", "ACTIVE", "MOCK-ACCOUNT-004", None),
    ("MOCK-200004", "Muhammad Ali", "Abdul Kareem", "1985-03-14", "M", "Karachi", "ACTIVE", "MOCK-ACCOUNT-005", None),
    # Blocked record.
    ("MOCK-200005", "Fatima Noor", "Noor Ahmed", "1992-07-21", "F", "Quetta", "BLOCKED", "MOCK-ACCOUNT-007", None),
    # Account holder name does not match the citizen name.
    ("MOCK-200006", "Ayesha Siddiqui", "Siddique Ahmed", "1995-01-30", "F", "Islamabad", "ACTIVE", "MOCK-ACCOUNT-006", "A. Siddiqi Traders"),
    # Special behaviours are triggered by the id itself (see nadra.py).
    ("MOCK-TIMEOUT-01", "Timeout Test", "Test Father", "1980-01-01", "M", "Lahore", "ACTIVE", None, None),
    ("MOCK-MALFORMED-01", "Malformed Test", "Test Father", "1980-01-01", "M", "Lahore", "ACTIVE", None, None),
]

ORDINARY_NAMES = [
    ("Hamza Qureshi", "M"), ("Sana Malik", "F"), ("Bilal Ahmed", "M"), ("Maryam Javed", "F"),
    ("Usman Tariq", "M"), ("Hina Parveen", "F"), ("Imran Shah", "M"), ("Nadia Hussain", "F"),
    ("Kamran Aslam", "M"), ("Saima Iqbal", "F"), ("Faisal Mehmood", "M"), ("Rukhsana Bibi", "F"),
    ("Adeel Raza", "M"), ("Samina Kausar", "F"), ("Tariq Mahmood", "M"), ("Shazia Perveen", "F"),
    ("Naveed Akhtar", "M"), ("Bushra Anwar", "F"), ("Zahid Hussain", "M"), ("Lubna Farooq", "F"),
]
DISTRICTS = ["Lahore", "Karachi", "Faisalabad", "Rawalpindi", "Multan", "Hyderabad", "Sialkot"]
FATHERS = ["Muhammad Aslam", "Abdul Majeed", "Ghulam Rasool", "Muhammad Yousaf", "Allah Ditta"]


def _ordinary_rows() -> List[tuple]:
    rows = []
    for i, (name, gender) in enumerate(ORDINARY_NAMES, start=1):
        rows.append((
            f"MOCK-1{i:05d}", name, FATHERS[i % len(FATHERS)],
            f"{1970 + (i * 3) % 35}-{1 + i % 12:02d}-{1 + (i * 7) % 28:02d}",
            gender, DISTRICTS[i % len(DISTRICTS)], "ACTIVE", f"MOCK-ACCOUNT-{100 + i}", None,
        ))
    return rows


def all_rows() -> List[tuple]:
    return DEMO + _ordinary_rows()


def seed_mocks(reset: bool = False, db: Optional[Session] = None) -> Dict[str, int]:
    """Seed identities and accounts. reset=True first wipes ALL mock tables
    (identities, accounts, transactions, sms, switches). Safe to call twice."""
    own = db is None
    if own:
        from shared import db as shared_db

        db = shared_db.SessionLocal()
    try:
        if reset:
            for model in (MockTransaction, MockSmsMessage, MockAccount, MockIdentityRecord, MockFixtureState):
                db.query(model).delete()
        identities = accounts = 0
        for cit, name, father, dob, gndr, dist, status, acct, holder in all_rows():
            db.merge(MockIdentityRecord(
                cit_id=cit, full_nm=name, father_nm=father, birth_dt=dob,
                gndr=gndr, dist=dist, rec_status=status,
            ))
            identities += 1
            if acct:
                db.merge(MockAccount(acct=acct, holder_nm=holder or name, cit_id=cit))
                accounts += 1
        db.commit()
        return {"identities": identities, "accounts": accounts}
    finally:
        if own:
            db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the mock services (fictional data).")
    parser.add_argument("--reset", action="store_true", help="wipe all mock tables first")
    parser.add_argument(
        "--create-tables", action="store_true",
        help="dev only: create the mock tables if no migration has yet (skip once Alembic has them)",
    )
    args = parser.parse_args()
    from shared.db import Base, engine

    if args.create_tables:
        Base.metadata.create_all(engine, tables=[m.__table__ for m in MOCK_MODELS])
    print(seed_mocks(reset=args.reset))


if __name__ == "__main__":
    main()
