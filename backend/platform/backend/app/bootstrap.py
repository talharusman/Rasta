"""Bind existing Supabase Auth users to synthetic local profiles. Does not create Auth users."""
import argparse
import json
import uuid
from sqlalchemy import select
from .models import User, Citizen, Rule
from .platform import factory

DEFAULT_POLICY = {'max_monthly_income':40000,'required_documents':['identity_proof','income_proof'],'clear_confidence_min':0.95,'proof_confidence_min':0.70,'critical_flags':['identity_mismatch','potential_duplicate','fraud_indicator','identity_service_unavailable']}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--accounts',required=True,help='JSON file containing tenant_id and existing Supabase user IDs')
    args=parser.parse_args()
    data=json.loads(open(args.accounts).read())
    tenant=uuid.UUID(data['tenant_id'])
    allowed={'citizen','helper','officer','admin','auditor'}
    with factory()() as session:
        for account in data['users']:
            identifier=uuid.UUID(account['id'])
            if account['role'] not in allowed: raise ValueError('Invalid role')
            existing=session.get(User,identifier)
            if existing:
                if existing.tenant_id!=tenant: raise ValueError('User belongs to another tenant')
                continue
            session.add(User(id=identifier,tenant_id=tenant,name=account['name'],role=account['role']))
            session.flush()
            if account['role']=='citizen':
                session.add(Citizen(tenant_id=tenant,user_id=identifier,name=account['name'],mock_identity_id='MOCK-'+identifier.hex[:12]))
        if not session.scalar(select(Rule).where(Rule.tenant_id==tenant,Rule.active.is_(True))):
            session.add(Rule(tenant_id=tenant,policy_id=uuid.uuid4(),rule_name='Synthetic relief eligibility',version=1,conditions_json=DEFAULT_POLICY))
        session.commit()
    print('Synthetic profiles and initial policy provisioned. Auth passwords were not changed.')

if __name__=='__main__': main()
