from datetime import date
import copy
import json
import unittest
import tempfile
from pathlib import Path
from backend.core import CoreWorkflow, acme_facts, next_month, validate_settlement
from backend.integrations import Cognee
from backend.memory import CustomerMemory
from backend.policy import PolicyError, digest
from backend.tests.fakes import settings
from backend.tests.fakes import StripeTransportFixture,MemoryFixture
from backend.store import Store
from backend.integrations import Stripe


class CorePolicyTests(unittest.TestCase):
    def setUp(self):
        self.facts=acme_facts('customer-acme')
        self.proposal={'customer_id':'customer-acme','currency':'gbp','original':100_000,'adjustment':20_000,
                       'agreement_date':'2026-10-15','instalments':[{'amount':30_000,'due':'2026-10-15'},
                                                                {'amount':50_000,'due':'2026-11-15'}],
                       'evidence_hashes':{k:digest(v) for k,v in self.facts.items()}}

    def test_next_calendar_month_is_valid_even_when_31_days(self):
        self.assertTrue(validate_settlement(self.proposal,self.facts)['allowed'])

    def test_month_end_and_year_rollover(self):
        for before,after in [('2026-01-31','2026-02-28'),('2028-01-31','2028-02-29'),('2026-12-15','2027-01-15')]:
            self.assertEqual(next_month(date.fromisoformat(before)).isoformat(),after)

    def test_mixed_customers_are_rejected(self):
        self.facts['policy']['customer_id']='customer-other'
        self.proposal['evidence_hashes']={k:digest(v) for k,v in self.facts.items()}
        with self.assertRaisesRegex(PolicyError,'Mixed customer'):
            validate_settlement(self.proposal,self.facts)

    def test_changed_evidence_is_rejected(self):
        self.facts['promise']['message']='tampered'
        with self.assertRaisesRegex(PolicyError,'Evidence has changed'):
            validate_settlement(self.proposal,self.facts)

    def test_unsupported_adjustments_rejected(self):
        for amount in (20_001,20_000.0,True,0):
            with self.subTest(amount=amount),self.assertRaises(PolicyError):
                proposal=copy.deepcopy(self.proposal);proposal['adjustment']=amount
                validate_settlement(proposal,self.facts)

    def test_incomplete_deliverable_requires_acceptance_evidence(self):
        self.facts['dispute']['acceptance_record']['incomplete_deliverable']='service'
        self.proposal['evidence_hashes']={k:digest(v) for k,v in self.facts.items()}
        with self.assertRaisesRegex(PolicyError,'evidence is missing'):
            validate_settlement(self.proposal,self.facts)

    def test_schedule_must_equal_800(self):
        self.proposal['instalments'][1]['amount']=49_999
        with self.assertRaises(PolicyError):
            validate_settlement(self.proposal,self.facts)

    def test_second_due_date_is_next_month(self):
        self.proposal['instalments'][1]['due']='2026-10-29'
        with self.assertRaisesRegex(PolicyError,'next calendar month'):
            validate_settlement(self.proposal,self.facts)


class ScopedMemoryContractTests(unittest.TestCase):
    def setUp(self):
        class Capture:
            def __init__(self):self.calls=[];self.results=[]
            def request(self,service,method,url,headers,body=None,timeout=90):
                self.calls.append({'url':url,'payload':json.loads(body) if body else None})
                return self.results,{'http_status':200,'fixture':True}
        self.capture=Capture()
        self.root=Cognee(settings(),self.capture)
        self.root.schema={'paths':{'/api/v1/add_text':{},'/api/v1/search':{}}}

    def test_customer_datasets_and_sessions_differ(self):
        acme=CustomerMemory(self.root,'customer-acme');other=CustomerMemory(self.root,'customer-other')
        self.assertNotEqual(acme.dataset,other.dataset)
        acme.retrieve('contract');other.retrieve('contract')
        first,second=[c['payload'] for c in self.capture.calls]
        self.assertNotEqual(first['datasets'],second['datasets'])
        self.assertNotEqual(first['sessionId'],second['sessionId'])
        self.assertEqual(first['datasets'],[acme.dataset])

    def test_foreign_dataset_response_is_rejected(self):
        memory=CustomerMemory(self.root,'customer-acme')
        self.capture.results=[{'dataset_name':'customer-other','search_result':'foreign data'}]
        with self.assertRaisesRegex(PolicyError,'another customer'):
            memory.retrieve('contract')

    def test_contract_policy_history_and_decision_use_scoped_real_contract(self):
        memory=CustomerMemory(self.root,'customer-acme')
        memory.store_contract({'amount':100_000},'C1')
        memory.store_policy({'max_adjustment':20_000},'P1')
        memory.store_promise({'amount':30_000},'PR1')
        memory.store_dispute({'amount':20_000},'D1')
        memory.store_decision({'allow':True},'Contract supports the adjustment','S1')
        documents=[json.loads(c['payload']['textData'][0]) for c in self.capture.calls]
        self.assertEqual([d['kind'] for d in documents],['contract','policy','promise','dispute','decision'])
        self.assertTrue(all(d['customer_id']=='customer-acme' for d in documents))
        self.assertTrue(all(c['payload']['datasetName']==memory.dataset for c in self.capture.calls))


class ReplacementWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.temp.name)/'journal.sqlite3')
        cfg=settings();self.transport=StripeTransportFixture();self.memory=MemoryFixture()
        memory=self.memory
        class ScopedFixture:
            def store(self,*args):return {'fixture':True}
            def index(self):return memory.cognify()
        class WorkflowFixture(CoreWorkflow):
            def customer_memory(self,case):return ScopedFixture()
        self.engine=WorkflowFixture(cfg,self.store,Stripe(cfg,self.store,self.transport),self.memory)
        self.engine.verification()
        self.case=self.engine.create_case('replacement-unit-test-001')
        self.case=self.engine.execute(self.case['id'],'invoice')
        facts=acme_facts(self.case['customer_id'])
        today=date.today()
        self.case['facts']=facts
        self.case['proposal']={'customer_id':self.case['customer_id'],'original':100_000,'adjustment':20_000,'currency':'gbp',
                               'agreement_date':today.isoformat(),'instalments':[{'amount':30_000,'due':today.isoformat()},
                                                                              {'amount':50_000,'due':next_month(today).isoformat()}],
                               'evidence_hashes':{k:digest(v) for k,v in facts.items()}}
        self.store.put('cases',self.case['id'],self.case)

    def tearDown(self):
        self.store.close();self.temp.cleanup()

    def test_replacements_total_800_and_original_voids_before_finalising(self):
        result=self.engine.execute(self.case['id'],'core-replace')
        self.assertEqual(result['stage'],'replaced')
        self.assertEqual(result['invoice']['status'],'void')
        self.assertEqual([i['amount_remaining'] for i in result['replacements']],[30_000,50_000])
        self.assertTrue(all(i['status']=='open' and i['amount_paid']==0 for i in result['replacements']))
        paths=[p for m,p,_ in self.transport.calls if m=='POST']
        void=paths.index('/invoices/in_fixture/void')
        self.assertEqual(paths[:void].count('/invoices'),3)
        self.assertLess(void,paths.index('/invoices/in_fixture_2/finalize'))
        self.assertLess(void,paths.index('/invoices/in_fixture_3/finalize'))

    def test_second_execution_does_not_duplicate_invoices(self):
        self.engine.execute(self.case['id'],'core-replace')
        count=sum(m=='POST' for m,_,_ in self.transport.calls)
        self.engine.execute(self.case['id'],'core-replace')
        self.assertEqual(sum(m=='POST' for m,_,_ in self.transport.calls),count)

    def test_payment_on_original_blocks_void_and_finalisation(self):
        original=self.transport.objects['in_fixture'];original['amount_paid']=1;original['amount_remaining']=99_999
        with self.assertRaises(PolicyError):self.engine.execute(self.case['id'],'core-replace')
        self.assertFalse(any(p.endswith('/void') for _,p,_ in self.transport.calls))
        self.assertEqual(original['status'],'open')

    def test_external_payment_intent_blocks_void(self):
        self.transport.objects['in_fixture']['payments']['data']=[{'status':'open','amount_paid':None,'is_default':False}]
        with self.assertRaisesRegex(PolicyError,'externally attached'):self.engine.execute(self.case['id'],'core-replace')
        self.assertFalse(any(p.endswith('/void') for _,p,_ in self.transport.calls))

    def test_default_unpaid_invoice_payment_does_not_block(self):
        self.transport.objects['in_fixture']['payments']['data']=[{'status':'open','amount_paid':None,'is_default':True}]
        result=self.engine.execute(self.case['id'],'core-replace')
        self.assertEqual(result['stage'],'replaced')

    def test_automatic_advancement_change_blocks_void(self):
        self.transport.objects['in_fixture']['auto_advance']=True
        with self.assertRaisesRegex(PolicyError,'automatic collection'):self.engine.execute(self.case['id'],'core-replace')
        self.assertFalse(any(p.endswith('/void') for _,p,_ in self.transport.calls))

    def test_externally_void_original_cannot_be_reprocessed(self):
        self.transport.objects['in_fixture']['status']='void'
        with self.assertRaisesRegex(PolicyError,'voided outside this workflow'):
            self.engine.execute(self.case['id'],'core-replace')
        self.assertFalse(any(p.endswith('/void') for _,p,_ in self.transport.calls))
        self.assertFalse(any(p in ('/invoices/in_fixture_2/finalize','/invoices/in_fixture_3/finalize') for _,p,_ in self.transport.calls))


if __name__=='__main__':unittest.main()
