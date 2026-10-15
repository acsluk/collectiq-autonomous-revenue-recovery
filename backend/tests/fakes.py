"""Explicit unit-test fixtures ONLY. Never imported by the application."""
import copy
from urllib.parse import parse_qs, urlsplit
from types import SimpleNamespace
from backend.integrations import IntegrationError
from backend.policy import canonical, digest


def settings():
    return SimpleNamespace(stripe_key='sk_test_unit_fixture', cognee_key='unit-test-memory-key',
                           cognee_tenant='test-tenant', cognee_url='https://unit.invalid',
                           dataset='unit-test', stripe_version='2025-06-30.basil', port=0)


class StripeTransportFixture:
    def __init__(self):
        self.calls, self.objects, self.idempotency = [], {}, {}
        self.decline = False
        self.fail_after_credit = False

    def request(self, service, method, url, headers, body=None, timeout=90):
        params = {k: v[0] for k, v in parse_qs((body or b'').decode()).items()}
        path = urlsplit(url).path.removeprefix('/v1')
        self.calls.append((method, path, params))
        receipt = {'http_status': 200, 'request_id': 'UNIT-TEST-FIXTURE', 'endpoint': path, 'checked_at': 'fixture'}
        idem = headers.get('Idempotency-Key')
        if method == 'POST' and idem in self.idempotency:
            return copy.deepcopy(self.idempotency[idem]), receipt
        if method == 'GET':
            if path == '/balance':
                obj = {'object': 'balance', 'livemode': False, 'available': []}
            elif path == '/invoices':
                obj = {'object': 'list', 'data': []}
            else:
                obj = self.objects[path.rsplit('/', 1)[-1]]
        else:
            obj = {'livemode': False}
            if path == '/customers':
                obj.update(id='cus_fixture', object='customer', metadata={'collectiq_case':params.get('metadata[collectiq_case]')})
            elif path.startswith('/customers/'):
                obj = self.objects[path.rsplit('/',1)[-1]]
            elif path == '/invoices':
                count=sum(o.get('object')=='invoice' for o in self.objects.values())
                invoice_id='in_fixture' if count==0 else f'in_fixture_{count+1}'
                metadata={k[9:-1]:v for k,v in params.items() if k.startswith('metadata[')}
                obj.update(id=invoice_id, object='invoice', status='draft', currency='gbp', total=0,
                           amount_due=0, amount_remaining=0, amount_paid=0, amount_overpaid=0,
                           customer=params['customer'], metadata=metadata,
                           auto_advance=False,collection_method='send_invoice',
                           pre_payment_credit_notes_amount=0, payments={'data': []})
            elif path == '/invoiceitems':
                invoice = self.objects[params['invoice']]
                invoice.update(total=int(params['amount']), amount_due=int(params['amount']), amount_remaining=int(params['amount']))
                obj.update(id='ii_fixture', object='invoiceitem', amount=int(params['amount']))
            elif path.endswith('/finalize'):
                obj = self.objects[path.split('/')[2]]
                obj['status'] = 'open'
            elif path.endswith('/void'):
                obj = self.objects[path.split('/')[2]]
                obj.update(status='void',amount_remaining=0)
            elif path == '/credit_notes':
                invoice = self.objects[params['invoice']]
                amount = int(params['amount'])
                invoice['amount_remaining'] -= amount
                invoice['pre_payment_credit_notes_amount'] += amount
                obj.update(id='cn_fixture', object='credit_note', status='issued', amount=amount,
                           pre_payment_amount=amount, post_payment_amount=0, invoice=invoice['id'])
            elif path == '/payment_intents':
                obj.update(id=f"pi_fixture_{params['metadata[instalment]']}", object='payment_intent', amount=int(params['amount']),
                           amount_received=0, currency=params['currency'], customer=params['customer'], status='requires_payment_method',
                           client_secret='NEVER_PERSIST_THIS_SECRET')
            elif path.endswith('/attach_payment'):
                invoice = self.objects[path.split('/')[2]]
                invoice['payments']['data'].append({'id':'inpay_fixture','payment':{'payment_intent':params['payment_intent']},
                                                    'status':'open','amount_paid':0})
                obj = invoice
            elif path.endswith('/confirm'):
                obj = self.objects[path.split('/')[2]]
                if self.decline:
                    obj['status'] = 'requires_payment_method'
                else:
                    obj.update(status='succeeded', amount_received=obj['amount'])
                    invoice = self.objects['in_fixture']
                    invoice['amount_paid'] += obj['amount']
                    invoice['amount_remaining'] -= obj['amount']
                    for p in invoice['payments']['data']:
                        if p['payment']['payment_intent'] == obj['id']:
                            p.update(status='paid', amount_paid=obj['amount'])
                    if invoice['amount_remaining'] == 0:
                        invoice['status'] = 'paid'
            else:
                raise AssertionError('Unhandled unit fixture path: '+path)
            self.objects[obj['id']] = obj
            if idem:
                self.idempotency[idem] = copy.deepcopy(obj)
        return copy.deepcopy(obj), receipt


class MemoryFixture:
    def __init__(self):
        self.documents, self.calls = [], []
        self.fail_add = False
        self.empty_evidence = False
        self.fail_after_confirm = False
        self.fail_cognify = False

    def verify(self):
        return {'status':'verified','fixture':True}

    def add(self, doc):
        self.calls.append(('add', doc))
        if self.fail_add:
            raise IntegrationError('Cognee', 'Intentional unit-test outage')
        if self.fail_after_confirm and doc.get('kind') == 'stripe_response' and str(doc.get('body',{}).get('action','')).startswith('confirm-payment'):
            self.fail_add = True
            raise IntegrationError('Cognee', 'Intentional unit-test outage after payment confirmation')
        self.documents.append(copy.deepcopy(doc))
        return {'fixture':True,'receipt':{'http_status':200,'request_id':'UNIT-TEST-FIXTURE'}}

    def cognify(self):
        if self.fail_cognify:
            raise IntegrationError('Cognee', 'Intentional index failure')
        return {'fixture':True,'receipt':{'http_status':200}}

    def search(self, query, mode='GRAPH_COMPLETION'):
        self.calls.append(('search', {'query':query,'mode':mode}))
        result = [] if self.empty_evidence else self.documents
        if mode != 'CHUNKS':
            result = ['UNIT TEST FIXTURE: evidence-aware strategy.']
        return {'results':copy.deepcopy(result),'mode':mode,'source':'UNIT TEST FIXTURE','receipt':{'http_status':200}}
