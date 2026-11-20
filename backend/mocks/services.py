# OWNER: Member 3
# Put your logic here (fake NADRA / Raast / SMS, agent, background jobs).
import json
from pathlib import Path

FAKE_DATA_FILE = Path(__file__).parent / "fake_data.json"


def load_people():
    with open(FAKE_DATA_FILE, encoding="utf-8") as f:
        return json.load(f)


def find_person(cnic: str):
    for person in load_people():
        if person["cnic"] == cnic:
            return person
    return None
