"""Deterministic tests with explicit fixtures, not evidence of live integration success."""
from datetime import date, timedelta
import json
import tempfile
import threading
import unittest
from urllib.parse import parse_qs
from pathlib import Path
from backend.engine import Engine
from backend.integrations import Cognee, IntegrationError, Stripe, redact
from backend.policy import PolicyError, adjustment, demo_evidence, digest, negotiate, pennies, validate_plan
from backend.store import Store
from backend.tests.fakes import settings, StripeTransportFixture, MemoryFixture


class PolicyTests(unittest.TestCase):
    def test_adjustment_is_exactly_twenty_percent(self):
        evidence = demo_evidence('case')
        result = adjustment(evidence, 'case')
        self.assertEqual(result['amount'], 20_000)
        self.assertEqual(result['evidence_hash'], digest(evidence))

    def test_evidence_cannot_authorise_another_case(self):
        with self.assertRaises(PolicyError):
            adjustment(demo_evidence('other'), 'case')

    def test_tampered_evidence_is_rejected(self):
        for field, value in [('missed_units', 3), ('missed_units', True), ('missed_units', 2.0)]:
            with self.subTest(value=value):
                evidence = demo_evidence('case')
                evidence['service_log'][field] = value
                with self.assertRaises(PolicyError):
                    adjustment(evidence, 'case')

    def test_invalid_money_never_coerces(self):
        for value in (True, 300.0, '30000', 0, -1, 100_001, None):
            with self.subTest(value=value), self.assertRaises(PolicyError):
                pennies(value)

    def test_negotiation_rejects_45_days_and_accepts_14(self):
        today = date(2026, 10, 15)
        protocol = negotiate(today)
        self.assertTrue(protocol['simulated'])
        self.assertEqual(protocol['rounds'][2]['type'], 'reject')
        self.assertEqual(protocol['plan'][1]['due'], '2026-10-29')
        self.assertTrue(validate_plan(protocol['plan'], today=today)['allowed'])
        with self.assertRaises(PolicyError):
            validate_plan(protocol['rounds'][1]['proposal'], today=today)

    def test_plan_cannot_discount_change_currency_amounts_or_dates(self):
        today=date(2026,10,15)
        for amounts in ([30_000,40_000],[50_000,30_000],[30_000.0,50_000],[True,79_999]):
            with self.subTest(amounts=amounts), self.assertRaises(PolicyError):
                validate_plan([{'amount':amounts[0],'due':'2026-10-15'},{'amount':amounts[1],'due':'2026-10-29'}],today=today)
        for due in ('2026-10-14','2026-11-30','not-a-date'):
            with self.subTest(due=due), self.assertRaises(PolicyError):
                validate_plan([{'amount':30_000,'due':'2026-10-15'},{'amount':50_000,'due':due}],today=today)


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / 'journal.sqlite3')
        self.settings = settings()
        self.transport = StripeTransportFixture()
        self.stripe = Stripe(self.settings, self.store, self.transport)
        self.memory = MemoryFixture()
        self.engine = Engine(self.settings, self.store, self.stripe, self.memory)
        self.engine.verification()
        self.case = self.engine.create_case('unit-test-case-001')

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def do(self, action):
        self.case = self.engine.execute(self.case['id'], action)
        return self.case

    def test_full_settlement_contract(self):
        result = self.do('run')
        self.assertEqual(result['stage'],'settled')
        self.assertEqual(result['invoice']['total'],100_000)
        self.assertEqual(result['credit_note']['amount'],20_000)
        self.assertEqual([p['amount_received'] for p in result['payments']],[30_000,50_000])
        self.assertEqual(result['invoice']['amount_paid'],80_000)
        self.assertEqual(result['invoice']['amount_remaining'],0)
        self.assertEqual(result['invoice']['status'],'paid')
        self.assertTrue(self.store.integrity())
        self.assertTrue(all(e['memory_status']=='stored' for e in self.store.events()))
        paths = [path for method,path,_ in self.transport.calls if method=='POST']
        self.assertEqual(paths.count('/invoices'),1)
        self.assertEqual(paths.count('/credit_notes'),1)
        self.assertEqual(paths.count('/payment_intents'),2)
        for n in (1,2):
            confirm = paths.index(f'/payment_intents/pi_fixture_{n}/confirm')
            self.assertLess(paths.index('/invoices/in_fixture/attach_payment',0 if n==1 else paths.index('/payment_intents/pi_fixture_1/confirm')),confirm)

    def test_repeat_run_has_no_additional_financial_requests(self):
        self.do('run')
        count = sum(m=='POST' for m,_,_ in self.transport.calls)
        self.do('run')
        self.assertEqual(sum(m=='POST' for m,_,_ in self.transport.calls),count)
        self.assertEqual(len(self.case['payments']),2)

    def test_case_creation_is_idempotent(self):
        same=self.engine.create_case('unit-test-case-001')
        self.assertEqual(same['id'],self.case['id'])
        self.assertEqual(len(self.store.cases()),1)

    def test_cloud_outage_blocks_every_financial_write(self):
        self.memory.fail_add=True
        with self.assertRaises(IntegrationError):
            self.do('invoice')
        self.assertFalse(any(m=='POST' for m,_,_ in self.transport.calls))
        self.assertTrue(self.store.events(pending=True))

    def test_missing_evidence_retrieval_blocks_credit(self):
        self.do('invoice')
        self.memory.empty_evidence=True
        with self.assertRaises(PolicyError):
            self.do('resolve')
        self.assertFalse(any(p=='/credit_notes' for _,p,_ in self.transport.calls))

    def test_external_balance_change_blocks_credit(self):
        self.do('invoice')
        self.transport.objects['in_fixture']['amount_remaining']=90_000
        with self.assertRaises(PolicyError):
            self.do('resolve')
        self.assertFalse(any(p=='/credit_notes' for _,p,_ in self.transport.calls))

    def test_wrong_customer_is_rejected_before_credit(self):
        self.do('invoice')
        self.transport.objects['in_fixture']['customer']='cus_intruder'
        with self.assertRaises(PolicyError):
            self.do('resolve')

    def test_declined_payment_cannot_be_recorded_as_settlement(self):
        self.do('invoice');self.do('resolve');self.do('negotiate')
        self.transport.decline=True
        with self.assertRaises(PolicyError):
            self.do('pay-first')
        c=self.engine.case(self.case['id'])
        self.assertEqual(c['stage'],'promised')
        self.assertEqual(c['payments'],[])
        self.assertEqual(self.transport.objects['in_fixture']['amount_paid'],0)

    def test_second_payment_cannot_skip_first(self):
        self.do('invoice');self.do('resolve');self.do('negotiate')
        with self.assertRaises(PolicyError):
            self.do('pay-second')
        self.assertFalse(any(p=='/payment_intents' for _,p,_ in self.transport.calls))

    def test_resume_after_cloud_failure_following_successful_payment(self):
        self.do('invoice');self.do('resolve');self.do('negotiate')
        self.memory.fail_after_confirm=True
        with self.assertRaises(IntegrationError):
            self.do('pay-first')
        self.assertEqual(self.transport.objects['in_fixture']['amount_paid'],30_000)
        self.assertEqual(len(self.engine.case(self.case['id'])['payments']),0)
        self.memory.fail_add=False;self.memory.fail_after_confirm=False
        self.do('pay-first')
        self.assertEqual(self.case['stage'],'part_paid')
        self.assertEqual(len(self.case['payments']),1)
        self.assertEqual(self.transport.objects['in_fixture']['amount_paid'],30_000)
        self.assertEqual(sum(p.endswith('/confirm') for _,p,_ in self.transport.calls),1)

    def test_secrets_are_not_persisted(self):
        self.do('run')
        body=json.dumps(self.store.events())+json.dumps(self.store.cases())
        rows=self.store.db.execute('SELECT body FROM operations').fetchall()
        body+=''.join(r['body'] for r in rows)
        for secret in (self.settings.stripe_key,self.settings.cognee_key,'NEVER_PERSIST_THIS_SECRET','client_secret'):
            self.assertNotIn(secret,body)

    def test_changed_credentials_require_new_verification(self):
        self.settings.cognee_key='changed'
        with self.assertRaisesRegex(PolicyError,'Credentials changed'):
            self.do('invoice')

    def test_zero_balance_without_receipts_does_not_mean_settled(self):
        self.do('invoice')
        invoice=self.transport.objects['in_fixture']
        invoice.update(status='paid',amount_remaining=0,amount_paid=100_000)
        self.do('reconcile')
        self.assertEqual(self.case['stage'],'requires_review')

    def test_hash_chain_detects_tampering(self):
        self.store.db.execute("UPDATE events SET body='{}' WHERE seq=1")
        self.store.db.commit()
        self.assertFalse(self.store.integrity())
        with self.assertRaisesRegex(PolicyError,'hash chain'):
            self.do('invoice')

    def test_live_key_rejected_before_any_network_call(self):
        self.settings.stripe_key='sk_live_unit_test'
        count=len(self.transport.calls)
        with self.assertRaisesRegex(PolicyError,'test-mode'):
            self.stripe.request('GET','/invoices')
        self.assertEqual(len(self.transport.calls),count)

    def test_live_response_rejected(self):
        self.do('invoice')
        self.transport.objects['in_fixture']['livemode']=True
        with self.assertRaisesRegex(PolicyError,'livemode=false'):
            self.do('reconcile')

    def test_idempotency_key_cannot_change_parameters(self):
        self.stripe.request('POST','/customers',{'name':'one'},'stable-operation')
        with self.assertRaisesRegex(PolicyError,'different request'):
            self.stripe.request('POST','/customers',{'name':'two'},'stable-operation')

    def test_uncertain_old_operation_is_not_recreated(self):
        import time
        payload={'name':'test'}
        key=f'{self.stripe.scope}:old-operation'
        self.store.put('operations',key,{'fingerprint':digest({'path':'/customers','payload':payload}),
                                         'started':time.time()-24*3600,'path':'/customers'})
        with self.assertRaisesRegex(PolicyError,'23 hours'):
            self.stripe.request('POST','/customers',payload,'old-operation')

    def test_two_concurrent_retries_collect_only_once(self):
        self.do('invoice');self.do('resolve');self.do('negotiate')
        errors=[]
        def pay():
            try:self.engine.execute(self.case['id'],'pay-first')
            except Exception as e:errors.append(e)
        threads=[threading.Thread(target=pay) for _ in range(2)]
        for thread in threads:thread.start()
        for thread in threads:thread.join()
        self.assertEqual(errors,[])
        self.assertEqual(self.transport.objects['in_fixture']['amount_paid'],30_000)
        self.assertEqual(len(self.engine.case(self.case['id'])['payments']),1)


class CogneeContractTests(unittest.TestCase):
    def test_tenant_header_and_correct_form_contract(self):
        class Capture:
            def request(self,*args,**kwargs):
                self.args=args
                return {'status':'completed'}, {'http_status':200}
        capture=Capture();cfg=settings();client=Cognee(cfg,capture)
        client.schema = {'paths': {}}
        client.add({'evidence':'test'})
        _,method,url,headers,body=capture.args
        self.assertEqual(headers['X-Tenant-Id'],'test-tenant')
        self.assertEqual(headers['X-Api-Key'],cfg.cognee_key)
        self.assertTrue(url.endswith('/api/v1/add'))
        form=parse_qs(body.decode())
        self.assertEqual(form['datasetName'],['unit-test'])
        self.assertEqual(json.loads(form['raw_data'][0]),{'evidence':'test'})

    def test_pipeline_failure_inside_http_200_is_rejected(self):
        for value in ({'status':'DATASET_PROCESSING_ERROR'},{'nested':{'status':'failed'}},[{'error':'LLM missing'}]):
            with self.subTest(value=value), self.assertRaises(IntegrationError):
                Cognee.check_pipeline(value)

    def test_placeholder_key_is_not_sent(self):
        cfg=settings();cfg.cognee_key='<your-api-key>'
        class Never:
            def request(self,*a,**kw):raise AssertionError('Must not make network request')
        with self.assertRaises(PolicyError):
            Cognee(cfg,Never()).search('test')

    def test_secret_redaction(self):
        self.assertNotIn('sk_test_secret',redact('key=sk_test_secret'))
        self.assertNotIn('exact-key',redact('value=exact-key',('exact-key',)))


if __name__=='__main__':
    unittest.main()
