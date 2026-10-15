"""Financial/protocol unit fixtures. Real Cognee scenarios are run by agent_cli separately."""
from datetime import date
import copy
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
import threading
from backend.agents import AgentRunner,parse_completion
from backend.agent_policy import scenario,terms,validate_offer,validate_route,supported_adjustment,SPECIALISTS
from backend.agent_execution import execute_new_test_case
from backend.core import next_month
from backend.integrations import IntegrationError
from backend.policy import PolicyError
from backend.store import Store


def offer(initial=25_000,total=80_000,action='COUNTEROFFER',adjustment=0,refs=None):
    today=date.today()
    return {'action':action,'currency':'gbp','adjustment_pence':adjustment,
            'instalments':([{'amount_pence':initial,'due':today.isoformat()},
                           {'amount_pence':total-initial,'due':next_month(today).isoformat()}] if action not in ('REJECT','REVIEW') else []),
            'reasoning':'UNIT TEST FIXTURE','evidence_refs':refs or ['POLICY-A-001','HISTORY-A-001']}


class AgentPolicyTests(unittest.TestCase):
    def setUp(self):
        self.s=scenario('A');self.refs=[v['reference'] for v in self.s['facts'].values()]
        self.limits=terms(self.s['facts'],80_000)

    def test_minimum_upfront_is_240_and_preferred_is_250(self):
        self.assertEqual(self.limits['minimum_upfront_pence'],24_000)
        self.assertEqual(self.limits['preferred_upfront_pence'],25_000)

    def test_history_materially_changes_the_same_decision(self):
        alternative=offer()
        self.assertTrue(validate_offer(alternative,80_000,0,self.limits,self.refs)['allowed'])
        changed=copy.deepcopy(self.s['facts']);changed['history']['promises'][0]['status']='broken'
        strict=terms(changed,80_000)
        self.assertEqual(strict['minimum_upfront_pence'],80_000)
        with self.assertRaisesRegex(PolicyError,'below policy minimum'):
            validate_offer(alternative,80_000,0,strict,self.refs)

    def test_initial_200_is_rejected_as_seller_plan(self):
        with self.assertRaisesRegex(PolicyError,'below policy minimum'):
            validate_offer(offer(20_000),80_000,0,self.limits,self.refs)

    def test_250_550_agreement_passes(self):
        self.assertTrue(validate_offer(offer(),80_000,0,self.limits,self.refs)['allowed'])

    def test_no_extra_discount(self):
        value=offer();value['instalments'][1]['amount_pence']-=1
        with self.assertRaisesRegex(PolicyError,'exactly equal'):validate_offer(value,80_000,0,self.limits,self.refs)

    def test_agent_cannot_change_fixed_adjustment(self):
        with self.assertRaisesRegex(PolicyError,'authorised adjustment'):
            validate_offer(offer(adjustment=1000),80_000,0,self.limits,self.refs)

    def test_boolean_float_and_string_money_are_rejected(self):
        for amount in (True,25_000.0,'25000'):
            value=offer();value['instalments'][0]['amount_pence']=amount
            with self.subTest(amount=amount),self.assertRaises(PolicyError):validate_offer(value,80_000,0,self.limits,self.refs)

    def test_buyer_cannot_exceed_private_budget(self):
        with self.assertRaisesRegex(PolicyError,'budget authority'):
            validate_offer(offer(30_000),80_000,0,self.limits,self.refs,buyer=self.s['buyer_authority'])

    def test_foreign_customer_reference_rejected(self):
        with self.assertRaisesRegex(PolicyError,'retrieved customer'):
            validate_offer(offer(refs=['POLICY-B-001']),80_000,0,self.limits,self.refs)

    def test_dispute_is_150_on_750_and_balance_600(self):
        s=scenario('C');adjust=supported_adjustment(s['facts'],s['disputed_line_id'])
        self.assertEqual(adjust,15_000);self.assertEqual(s['invoice']['amount_pence']-adjust,60_000)

    def test_missing_delivery_evidence_requires_review(self):
        s=scenario('C');del s['facts']['delivery']
        with self.assertRaisesRegex(PolicyError,'Missing delivery'):supported_adjustment(s['facts'],'report')

    def test_contradictory_delivery_evidence_rejected(self):
        s=scenario('C');s['facts']['delivery']['line_items'][1]['status']='delivered'
        with self.assertRaisesRegex(PolicyError,'contradicts'):supported_adjustment(s['facts'],'report')

    def test_adjustment_above_twenty_percent_rejected(self):
        s=scenario('C');s['facts']['contract']['line_items'][1]['amount_pence']=15_001
        with self.assertRaisesRegex(PolicyError,'cap'):supported_adjustment(s['facts'],'report')

    def test_all_six_routes_have_validated_specialist_assignment(self):
        for classification,specialist in SPECIALISTS.items():
            value={'classification':classification,'specialist':specialist,'action':'Investigate','reasoning':'Evidence-led',
                   'confidence':0.9,'risk':'MEDIUM','evidence_refs':['POLICY-A-001']}
            self.assertEqual(validate_route(value,self.refs)['specialist'],specialist)

    def test_wrong_specialist_or_unknown_classification_rejected(self):
        for classification,specialist in [('BILLING_DISPUTE','PromisePay'),('INVENTED','HumanReview')]:
            with self.subTest(classification=classification),self.assertRaises(PolicyError):
                validate_route({'classification':classification,'specialist':specialist},self.refs)

    def test_dry_run_scenario_is_not_a_fake_stripe_response(self):
        self.assertEqual(self.s['execution_mode'],'DRY_RUN')
        self.assertIsNone(self.s['invoice']['stripe_invoice_id'])
        self.assertEqual(self.s['invoice']['status'],'UNBILLED_DRY_RUN')
        self.assertNotIn('livemode',self.s['invoice'])

    def test_model_prose_or_non_object_is_not_silently_replaced(self):
        for text in ('I think you should accept.','[]','{"action": "ACCEPT"} trailing text'):
            with self.subTest(text=text),self.assertRaises(PolicyError):
                parse_completion({'results':[{'search_result':[text]}]})

    def test_explicit_execution_authorisation_is_required(self):
        with self.assertRaisesRegex(PolicyError,'authorise-new-test-case'):
            execute_new_test_case(None,'ai_example',False)

    def test_existing_acme_is_outside_execution_allowlist(self):
        class StoreFixture:
            def get(self,*args):return {'synthetic':True,'customer_id':'customer_5120099684f1de60c372'}
        with self.assertRaisesRegex(PolicyError,'allowlist'):
            execute_new_test_case(SimpleNamespace(store=StoreFixture()),'acme',True)


class ProtocolFixtureTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(Path(self.temp.name)/'unit.sqlite3')
        class EngineFixture:
            def __init__(self,store):self.store=store
            def audit(self,*args):pass
        self.engine=EngineFixture(self.store)
        self.w={**scenario('A'),'id':'unit-ai-A','agreement_date':date.today().isoformat(),'adjustment_pence':0,
                'evidence_refs':['POLICY-A-001','HISTORY-A-001'],'conversation':[]}
        self.w['limits']=terms(self.w['facts'],80_000)

    def tearDown(self):self.store.close();self.temp.cleanup()

    def test_three_round_limit_is_enforced(self):
        class NeverAccept(AgentRunner):
            def model(self,w,role,call_id,instruction,schema,context,validator):
                value=offer(25_000 if role=='Seller' else 20_000,action='COUNTEROFFER' if role=='Seller' else 'OFFER')
                validator(value);return value
        NeverAccept(self.engine).negotiate(self.w)
        self.assertEqual(self.w['rounds'],3)
        self.assertEqual(self.w['outcome'],'REQUIRES_REVIEW')
        self.assertEqual(len(self.w['conversation']),7)

    def test_replayed_accepted_conversation_uses_persisted_events(self):
        class Accept(AgentRunner):
            calls=0
            def model(self,w,role,call_id,instruction,schema,context,validator):
                self.calls+=1
                if call_id=='initial':value=offer(20_000,action='OFFER')
                elif role=='Seller':value=offer()
                else:value=offer(action='ACCEPT')
                validator(value);return value
        runner=Accept(self.engine);runner.negotiate(self.w)
        self.assertEqual(self.w['outcome'],'AGREED');self.assertEqual(runner.calls,3)
        before=copy.deepcopy(self.w['conversation']);self.w.pop('outcome');self.w.pop('accepted_offer')
        runner.negotiate(self.w)
        self.assertEqual(runner.calls,3);self.assertEqual(self.w['conversation'],before)
        self.assertEqual(self.w['outcome'],'AGREED')

    def test_invalid_seller_offer_never_becomes_agreement(self):
        class Invalid(AgentRunner):
            def model(self,w,role,call_id,instruction,schema,context,validator):
                value=offer(20_000,action='OFFER');validator(value);return value
        with self.assertRaisesRegex(PolicyError,'below policy minimum'):Invalid(self.engine).negotiate(self.w)
        self.assertNotIn('accepted_offer',self.w)


class FailureStateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Store(Path(self.temp.name)/'unit.sqlite3')
        class EngineFixture:
            def __init__(self,store):self.store=store;self.lock=threading.RLock()
            def require_ready(self):pass
            def sync_memory(self):pass
            def audit(self,*args):pass
        self.engine=EngineFixture(self.store)

    def tearDown(self):self.store.close();self.temp.cleanup()

    def test_failed_cognee_recall_blocks_without_financial_execution(self):
        class Outage(AgentRunner):
            def recall(self,w):raise IntegrationError('Cognee','UNIT TEST intentional outage')
        result=Outage(self.engine).run('A','outage-fixture')
        self.assertEqual(result['state'],'BLOCKED')
        self.assertEqual(result['stripe_execution']['status'],'NOT_REQUESTED')
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM operations').fetchone()[0],0)

    def test_failed_reasoning_request_blocks_without_fabricated_result(self):
        class Outage(AgentRunner):
            def recall(self,w):w['evidence_refs']=['POLICY-A-001']
            def route(self,w):raise IntegrationError('Cognee','UNIT TEST reasoning unavailable')
        result=Outage(self.engine).run('A','reasoning-outage-fixture')
        self.assertEqual(result['state'],'BLOCKED')
        self.assertNotIn('routing',result)
        self.assertEqual(result['conversation'],[])


if __name__=='__main__':unittest.main()
