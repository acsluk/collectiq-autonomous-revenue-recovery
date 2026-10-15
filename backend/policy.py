"""No model output, text evidence or client input can authorise money directly."""
from datetime import date, timedelta
import hashlib
import json


class PolicyError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise PolicyError(message)


def pennies(value):
    require(type(value) is int and 0 < value <= 100_000, 'Amount must be integer pence in (0, 100000]')
    return value


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def demo_evidence(case_id):
    # Explicit synthetic fixture, never represented as real customer documentation.
    return {
        'id': 'EV-SLA-001', 'case_id': case_id, 'source': 'Synthetic hackathon SLA and service log',
        'synthetic': True, 'type': 'service_level_credit', 'currency': 'gbp',
        'contract': {'reference': 'SLA-4.2', 'credit_per_unit_pence': 10_000, 'max_units': 2},
        'service_log': {'reference': 'LOG-002', 'missed_units': 2},
        'description': 'Two documented missed service units at £100 credit each under SLA 4.2.'
    }


def adjustment(evidence, case_id, original=100_000):
    require(original == 100_000, 'Demo policy is limited to the £1,000 invoice')
    require(evidence.get('case_id') == case_id, 'Evidence belongs to another case')
    require(evidence.get('id') == 'EV-SLA-001' and evidence.get('synthetic') is True,
            'Only the explicitly synthetic demo evidence is approved')
    require(evidence.get('currency') == 'gbp', 'Only GBP evidence is allowed')
    contract, log = evidence.get('contract', {}), evidence.get('service_log', {})
    require(contract.get('reference') == 'SLA-4.2' and log.get('reference') == 'LOG-002', 'Evidence references do not match')
    unit, count, maximum = contract.get('credit_per_unit_pence'), log.get('missed_units'), contract.get('max_units')
    require(type(unit) is int and type(count) is int and type(maximum) is int, 'Evidence amounts must be integers')
    require(unit == 10_000 and count == 2 and maximum == 2, 'Evidence differs from the approved demo fixture')
    credit = pennies(unit * min(count, maximum))
    require(credit * 100 <= original * 20, 'Adjustment exceeds the 20% cap')
    return {'allowed': True, 'policy_version': 'collectiq-demo-v1', 'amount': credit,
            'reason': 'product_unsatisfactory', 'evidence_id': evidence['id'],
            'evidence_hash': digest(evidence), 'explanation': evidence['description']}


def validate_plan(plan, balance=80_000, today=None):
    today = today or date.today()
    require(type(plan) is list and len(plan) == 2, 'Exactly two instalments are required')
    amounts, due = [], []
    for row in plan:
        amounts.append(pennies(row.get('amount')))
        try:
            due.append(date.fromisoformat(row['due']))
        except (ValueError, KeyError, TypeError):
            raise PolicyError('Invalid instalment due date') from None
    require(amounts == [30_000, 50_000], 'Only the £300 / £500 arrangement is approved')
    require(sum(amounts) == balance, 'Instalments must exactly equal the adjusted balance')
    require(today <= due[0] < due[1] <= today + timedelta(days=30), 'Plan must finish within 30 days')
    return {'allowed': True, 'policy_version': 'collectiq-demo-v1', 'balance': balance, 'instalments': plan}


def negotiate(today=None):
    """Bounded agent-to-agent protocol simulation; no LLM or financial success claimed."""
    today = today or date.today()
    plan = [{'amount': 30_000, 'due': today.isoformat()},
            {'amount': 50_000, 'due': (today + timedelta(days=14)).isoformat()}]
    return {
        'simulated': True, 'protocol': 'collectiq-a2a/1', 'rounds': [
            {'agent': 'CollectIQ creditor', 'type': 'offer', 'text': 'SLA evidence supports £200 credit. The remaining £800 is due.'},
            {'agent': 'Buyer treasury · simulated', 'type': 'counteroffer', 'text': 'Cash-flow constraint: £300 now and £500 in 45 days.',
             'proposal': [{'amount': 30_000, 'due': today.isoformat()}, {'amount': 50_000, 'due': (today + timedelta(days=45)).isoformat()}]},
            {'agent': 'Deterministic policy', 'type': 'reject', 'text': '45 days exceeds the maximum 30-day settlement window.'},
            {'agent': 'PromisePay', 'type': 'counteroffer', 'text': '£300 now; £500 in 14 days. No additional discount.', 'proposal': plan},
            {'agent': 'Buyer treasury · simulated', 'type': 'accept', 'text': 'Accept the £300 / £500 arrangement.', 'proposal': plan}
        ], 'plan': plan, 'policy': validate_plan(plan, today=today)
    }
