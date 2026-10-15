from datetime import date, datetime, timezone
import threading
import uuid
from .config import configured
from .integrations import Cognee, Stripe, IntegrationError, stripe_summary
from .policy import adjustment, canonical, demo_evidence, digest, negotiate, require, validate_plan
from .store import now
from .memory import CustomerMemory


class Engine:
    def __init__(self, settings, store, stripe=None, memory=None):
        self.settings, self.store = settings, store
        self.stripe = stripe or Stripe(settings, store)
        self.memory = memory or Cognee(settings)
        self.scoped_memories = {}
        # One execution lane for this single-process demo prevents concurrent overcollection.
        self.lock = threading.RLock()

    def verification(self):
        report = {'checked_at': now(), 'stripe': {'status': 'unverified'}, 'cognee': {'status': 'unverified'}}
        for name, client, key in [('stripe', self.stripe, self.settings.stripe_key), ('cognee', self.memory, self.settings.cognee_key)]:
            if not configured(key):
                report[name] = {'status': 'missing_credentials', 'error': f'{name.upper()} API credential is missing or a placeholder'}
                continue
            try:
                report[name] = client.verify()
            except (IntegrationError, ValueError) as error:
                report[name] = {'status': 'failed', 'error': str(error),
                                'http_status': getattr(error, 'status', None), 'request_id': getattr(error, 'request_id', None)}
        report['ready'] = all(report[name]['status'] == 'verified' for name in ('stripe', 'cognee'))
        self.store.put('settings', 'verification', report)
        self.store.put('settings', 'credential_binding', self.binding())
        return report

    def binding(self):
        return digest({'stripe': self.settings.stripe_key, 'cognee': self.settings.cognee_key,
                       'dataset': self.settings.dataset, 'base': self.settings.cognee_url,
                       'tenant': self.settings.cognee_tenant,
                       'version': self.settings.stripe_version})

    def require_ready(self):
        self.stripe.guard()
        report = self.store.get('settings', 'verification', {})
        require(report.get('ready') is True, 'Verify both integrations successfully before financial execution')
        require(self.store.get('settings', 'credential_binding') == self.binding(), 'Credentials changed. Verify integrations again.')
        checked = datetime.fromisoformat(report['checked_at'])
        require((datetime.now(timezone.utc) - checked).total_seconds() < 3600, 'Connectivity verification expired. Verify again.')
        require(self.store.integrity(), 'Audit journal hash chain failed verification')

    def sync_memory(self):
        receipts = []
        for event in self.store.events(pending=True):
            document = {k: event[k] for k in ('case_id', 'kind', 'created', 'body', 'previous_hash', 'hash')}
            document['audit_event_id'] = f"collectiq:{event['seq']}:{event['hash']}"
            case = self.store.get('cases', event['case_id'])
            if not case:
                case = self.store.get('workflows', event['case_id'])
            client = self.memory_for(case) if case else self.memory
            if case and case.get('customer_id'):
                document['customer_id'] = case['customer_id']
            receipt = client.add(document)
            self.store.ack(event['seq'], receipt)
            receipts.append(receipt)
        return {'stored': len(receipts), 'receipts': receipts}

    def audit(self, case_id, kind, body, required=True):
        seq = self.store.event(case_id, kind, body)
        if required:
            self.sync_memory()
        return seq

    def memory_for(self, case):
        if case.get('customer_id') and isinstance(self.memory, Cognee):
            if case['customer_id'] not in self.scoped_memories:
                self.scoped_memories[case['customer_id']] = CustomerMemory(self.memory, case['customer_id'])
            return self.scoped_memories[case['customer_id']].client
        return self.memory

    def create_case(self, request_id, customer_name='Northstar Studio', workflow='partial-payments'):
        require(type(request_id) is str and 8 <= len(request_id) <= 100 and all(c.isalnum() or c == '-' for c in request_id),
                'A stable alphanumeric request_id is required')
        case_id = 'cq_' + digest(request_id)[:20]
        existing = self.store.get('cases', case_id)
        if existing:
            return existing
        case = {'id': case_id, 'created': now(), 'customer_name': customer_name, 'currency': 'gbp',
                'customer_id': 'customer_' + digest({'name': customer_name, 'request_id': request_id})[:20], 'workflow': workflow,
                'original_amount': 100_000, 'stage': 'ready', 'invoice': None, 'credit_note': None,
                'negotiation': None, 'payments': [], 'scenario': 'Synthetic hackathon customer and SLA evidence',
                'execution_mode': 'Stripe test mode only'}
        case['evidence'] = demo_evidence(case_id)
        self.store.put('cases', case_id, case)
        self.audit(case_id, 'case_created', {'customer_name': case['customer_name'], 'evidence': case['evidence'],
                                           'evidence_hash': digest(case['evidence'])}, required=False)
        return case

    def case(self, case_id):
        case = self.store.get('cases', case_id)
        require(case is not None, 'Unknown case')
        return case

    def check_invoice(self, case, invoice):
        require(invoice.get('livemode') is False, 'Invoice must be in Stripe test mode')
        require(invoice.get('currency') == 'gbp' and invoice.get('total') == 100_000, 'Invoice currency or total changed')
        require(invoice.get('customer') == case['stripe_customer'], 'Invoice customer changed')
        require(invoice.get('metadata', {}).get('collectiq_case') == case['id'], 'Invoice is not owned by this case')
        require(invoice.get('amount_overpaid', 0) == 0, 'Invoice has an unexpected overpayment; reconcile manually')

    def read_invoice(self, case):
        require(case.get('invoice'), 'Create the Stripe invoice first')
        invoice, receipt = self.stripe.request('GET', '/invoices/' + case['invoice']['id'], {'expand[]': 'payments'})
        self.check_invoice(case, invoice)
        return invoice, receipt

    def execute(self, case_id, action):
        with self.lock:
            self.require_ready()
            self.sync_memory()
            try:
                handlers = {'invoice': self.issue_invoice, 'resolve': self.resolve, 'negotiate': self.negotiate,
                            'pay-first': lambda c: self.pay(c, 0), 'pay-second': lambda c: self.pay(c, 1),
                            'reconcile': self.reconcile, 'run': self.run}
                require(action in handlers, 'Unknown action')
                return handlers[action](self.case(case_id))
            except Exception as error:
                self.audit(case_id, 'execution_stopped', {'action': action, 'error': str(error)}, required=False)
                raise

    def stripe_write(self, case, suffix, path, params):
        self.audit(case['id'], 'financial_intent', {'action': suffix, 'endpoint': path, 'parameters': params,
                                                   'policy_version': 'collectiq-demo-v1', 'mode': 'test'})
        obj, receipt = self.stripe.request('POST', path, params, f"{case['id']}:{suffix}")
        self.audit(case['id'], 'stripe_response', {'action': suffix, 'object': stripe_summary(obj), 'receipt': receipt})
        return obj

    def issue_invoice(self, case):
        if case.get('invoice'):
            return self.reconcile(case)
        customer = self.stripe_write(case, 'create-customer', '/customers',
                                     {'name': case['customer_name'] + ' · CollectIQ synthetic demo',
                                      'metadata[collectiq_case]': case['id']})
        case['stripe_customer'] = customer['id']
        self.store.put('cases', case['id'], case)
        require(customer.get('metadata', {}).get('collectiq_case') == case['id'], 'Customer is not owned by this case')
        # Stripe requires email to finalise a send_invoice invoice. example.com is synthetic;
        # auto_advance=false and no /send call mean the application sends no email.
        self.stripe_write(case, 'prepare-customer-email', '/customers/' + customer['id'],
                          {'email': 'collectiq-' + case['id'] + '@example.com'})
        invoice_operation = 'create-invoice-email-validated-v2'
        legacy = self.store.get('operations', f"{self.stripe.scope}:{case['id']}:create-invoice")
        if legacy and legacy.get('response'):
            invoice_operation = 'create-invoice'
        elif legacy:
            # Stripe can retain the earlier HTTP 400 under its idempotency key. Change the
            # key only after proving that exact prerequisite failed and no invoice exists.
            known_email_failure = any(e['kind']=='execution_stopped' and 'customer needs a valid email' in e['body'].get('error','')
                                      for e in self.store.events(case['id']))
            require(known_email_failure, 'Uncertain legacy invoice creation needs manual reconciliation')
            existing, receipt = self.stripe.request('GET', '/invoices', {'customer':customer['id'], 'limit':100})
            require(not existing.get('has_more') and not any(i.get('metadata',{}).get('collectiq_case')==case['id'] for i in existing['data']),
                    'A case invoice exists; do not retry creation with a new idempotency key')
            self.audit(case['id'],'invoice_prerequisite_reconciled',{'reason':'Earlier email prerequisite error; customer email is now set',
                                                                   'no_existing_case_invoice':True,'receipt':receipt})
        invoice = self.stripe_write(case, invoice_operation, '/invoices',
                                    {'customer': customer['id'], 'currency': 'gbp', 'collection_method': 'send_invoice',
                                     'days_until_due': 14, 'auto_advance': 'false',
                                     'pending_invoice_items_behavior': 'exclude', 'automatic_tax[enabled]': 'false',
                                     'description': 'CollectIQ hackathon · £1,000 service invoice · synthetic demo',
                                     'metadata[collectiq_case]': case['id']})
        self.stripe_write(case, 'create-line', '/invoiceitems',
                          {'customer': customer['id'], 'invoice': invoice['id'], 'currency': 'gbp', 'amount': 100_000,
                           'discountable': 'false', 'description': 'Service agreement · synthetic hackathon fixture',
                           'metadata[collectiq_case]': case['id']})
        final = self.stripe_write(case, 'finalize-invoice', '/invoices/' + invoice['id'] + '/finalize', {'auto_advance': 'false'})
        self.check_invoice(case, final)
        require(final.get('status') == 'open' and final.get('amount_remaining') == 100_000 and final.get('amount_paid') == 0,
                'Finalized invoice does not match the £1,000 unpaid demo')
        case.update(invoice=stripe_summary(final), stage='invoiced')
        self.store.put('cases', case['id'], case)
        return case

    def resolve(self, case):
        require(case.get('invoice'), 'Create an invoice before resolving its dispute')
        if case.get('credit_note'):
            return self.reconcile(case)
        decision = adjustment(case['evidence'], case['id'])
        memory = self.memory_for(case)
        memory.cognify()
        retrieval = memory.search(f"Find evidence for case {case['id']} with evidence_hash {decision['evidence_hash']}", 'CHUNKS')
        require(decision['evidence_hash'] in canonical(retrieval['results']),
                'Cognee did not return the exact evidence hash. Wait for indexing and retry.')
        invoice, receipt = self.read_invoice(case)
        # A prior successful write may still need local reconciliation after an interruption.
        op_key = f"{self.stripe.scope}:{case['id']}:issue-credit"
        previous = self.store.get('operations', op_key, {})
        require(invoice['status'] == 'open' and invoice['amount_paid'] == 0, 'Adjustment requires an unpaid open invoice')
        if not previous or not previous.get('response'):
            require(invoice['amount_remaining'] == 100_000 and invoice.get('pre_payment_credit_notes_amount', 0) == 0,
                    'Invoice was adjusted externally or an uncertain credit needs manual reconciliation')
        self.audit(case['id'], 'dispute_decision', {'decision': decision, 'retrieval': retrieval, 'invoice_receipt': receipt})
        credit = self.stripe_write(case, 'issue-credit', '/credit_notes',
                                   {'invoice': invoice['id'], 'amount': decision['amount'], 'reason': decision['reason'],
                                    'memo': 'Synthetic SLA-4.2: two missed units × £100. Evidence ' + decision['evidence_hash'],
                                    'metadata[collectiq_case]': case['id'], 'metadata[evidence_hash]': decision['evidence_hash']})
        require(credit.get('amount') == 20_000 and credit.get('invoice') == invoice['id']
                and credit.get('status') == 'issued' and credit.get('pre_payment_amount') == 20_000
                and credit.get('post_payment_amount', 0) == 0, 'Stripe credit note does not match the policy decision')
        invoice, receipt = self.read_invoice(case)
        require(invoice['amount_remaining'] == 80_000 and invoice.get('pre_payment_credit_notes_amount') == 20_000,
                'Stripe did not confirm the £800 adjusted balance')
        case.update(credit_note=stripe_summary(credit), invoice=stripe_summary(invoice), stage='adjusted')
        self.store.put('cases', case['id'], case)
        return case

    def negotiate(self, case):
        require(case.get('credit_note'), 'Resolve the evidence-based adjustment before negotiation')
        if case.get('negotiation'):
            return case
        invoice, receipt = self.read_invoice(case)
        require(invoice['amount_remaining'] == 80_000 and invoice['status'] == 'open', 'Negotiation requires the adjusted unpaid balance')
        # Genuine cloud reasoning informs the strategy; deterministic code alone authorises the plan.
        reasoning = self.memory_for(case).search(
            f"For CollectIQ case {case['id']}, recommend a concise collection strategy based on the synthetic SLA evidence. "
            'The original amount is GBP 1000, the supported adjustment GBP 200, and the proposed instalments GBP 300 now and GBP 500 in 14 days. '
            'Use only retrieved facts, identify evidence references, and do not execute payments.', 'GRAPH_COMPLETION')
        require(bool(reasoning['results']), 'Cognee returned no collection strategy')
        protocol = negotiate()
        validate_plan(protocol['plan'])
        self.audit(case['id'], 'promise_agreed', {'negotiation': protocol, 'cognee_reasoning': reasoning,
                                                'invoice_receipt': receipt})
        case.update(negotiation=protocol, reasoning=reasoning, stage='promised')
        self.store.put('cases', case['id'], case)
        return case

    def pay(self, case, index):
        require(case.get('negotiation'), 'Agree a policy-compliant plan before collecting')
        # Validate dates against agreement day, so a persisted plan remains valid on its later due date.
        agreement_day = date.fromisoformat(case['negotiation']['plan'][0]['due'])
        validate_plan(case['negotiation']['plan'], today=agreement_day)
        require(index == 0 or len(case['payments']) >= 1, 'Collect the first instalment before the second')
        if len(case['payments']) > index:
            return self.reconcile(case)
        amount = case['negotiation']['plan'][index]['amount']
        expected_paid = 0 if index == 0 else 30_000
        invoice, receipt = self.read_invoice(case)
        require(invoice.get('pre_payment_credit_notes_amount') == 20_000, 'Approved adjustment no longer matches Stripe')
        op = f"{self.stripe.scope}:{case['id']}:attach-payment-{index}"
        prior_attachment = self.store.get('operations', op)
        # Replay only our own operation when Stripe completed an attachment before a local crash.
        if not prior_attachment:
            require(invoice['status'] == 'open' and invoice['amount_paid'] == expected_paid
                    and invoice['amount_remaining'] == 80_000 - expected_paid, 'Stripe balance differs from the agreed payment sequence')
        self.audit(case['id'], 'payment_policy_allowed', {'index': index, 'amount': amount, 'currency': 'gbp',
                                                        'invoice_receipt': receipt, 'early_payment': date.today().isoformat() < case['negotiation']['plan'][index]['due'],
                                                        'explanation': 'Explicit hackathon execution; second instalment may be collected early with a Stripe test payment method.'})
        # Create -> attach -> confirm is Stripe's real partial-payment lifecycle.
        intent = self.stripe_write(case, f'create-payment-{index}', '/payment_intents',
                                   {'amount': amount, 'currency': 'gbp', 'customer': case['stripe_customer'],
                                    'payment_method_types[]': 'card', 'metadata[collectiq_case]': case['id'],
                                    'metadata[instalment]': index + 1})
        require(intent.get('amount') == amount and intent.get('currency') == 'gbp'
                and intent.get('customer') == case['stripe_customer'], 'PaymentIntent differs from the approved plan')
        self.stripe_write(case, f'attach-payment-{index}', '/invoices/' + invoice['id'] + '/attach_payment',
                          {'payment_intent': intent['id']})
        confirmed = self.stripe_write(case, f'confirm-payment-{index}', '/payment_intents/' + intent['id'] + '/confirm',
                                      {'payment_method': 'pm_card_visa'})
        require(confirmed.get('status') == 'succeeded' and confirmed.get('amount_received') == amount,
                'Stripe payment has not succeeded; no settlement is recorded')
        fresh_intent, intent_receipt = self.stripe.request('GET', '/payment_intents/' + intent['id'])
        require(fresh_intent.get('status') == 'succeeded' and fresh_intent.get('amount_received') == amount,
                'Stripe did not confirm the received payment amount')
        invoice, invoice_receipt = self.read_invoice(case)
        require(invoice['amount_paid'] == expected_paid + amount and invoice['amount_remaining'] == 80_000 - expected_paid - amount,
                'Payment succeeded but invoice reconciliation differs; stop and inspect Stripe')
        expected_status = 'open' if index == 0 else 'paid'
        require(invoice['status'] == expected_status, 'Invoice status does not match the confirmed payment sequence')
        payment = stripe_summary(fresh_intent)
        self.audit(case['id'], 'instalment_received', {'index': index, 'payment': payment,
                                                    'payment_receipt': intent_receipt, 'invoice': stripe_summary(invoice),
                                                    'invoice_receipt': invoice_receipt})
        case['payments'].append(payment)
        case.update(invoice=stripe_summary(invoice), stage='part_paid' if index == 0 else 'settled')
        self.store.put('cases', case['id'], case)
        return case

    def reconcile(self, case):
        invoice, receipt = self.read_invoice(case)
        self.audit(case['id'], 'invoice_reconciled', {'invoice': stripe_summary(invoice), 'receipt': receipt})
        case['invoice'] = stripe_summary(invoice)
        # A balance of zero alone is insufficient: require our two actual successful receipts.
        if invoice['status'] == 'paid' and invoice['amount_remaining'] == 0:
            if invoice['amount_paid'] == 80_000 and invoice.get('pre_payment_credit_notes_amount') == 20_000 and len(case['payments']) == 2:
                case['stage'] = 'settled'
            else:
                case['stage'] = 'requires_review'
        elif invoice['status'] in ('void', 'uncollectible'):
            case['stage'] = 'requires_review'
        self.store.put('cases', case['id'], case)
        return case

    def run(self, case):
        case = self.issue_invoice(case)
        case = self.resolve(case)
        case = self.negotiate(case)
        case = self.pay(case, 0)
        case = self.pay(case, 1)
        self.memory_for(case).cognify()
        return self.reconcile(case)

    def snapshot(self):
        events = self.store.events()
        cases = self.store.cases()
        for case in cases:
            if isinstance(self.memory, Cognee) and case.get('customer_id'):
                case['memory_dataset'] = CustomerMemory(self.memory, case['customer_id']).dataset
        return {'cases': cases, 'workflows':self.store.workflows(), 'verification': self.store.get('settings', 'verification'),
                'configuration': {'stripe': configured(self.settings.stripe_key), 'cognee': configured(self.settings.cognee_key),
                                  'dataset': self.settings.dataset},
                'audit': {'events': len(events), 'pending': sum(e['memory_status'] == 'pending' for e in events),
                          'hash_chain_valid': self.store.integrity()}, 'mode': 'test', 'server_time': now()}
