"""Verified Acme workflow: prepare replacement drafts, safely retire original, finalise replacements."""
import calendar
from datetime import date, datetime, time as day_time, timezone
from .engine import Engine
from .memory import CustomerMemory
from .policy import canonical, digest, pennies, require
from .integrations import stripe_summary

CUSTOMER_MESSAGE = 'We dispute £200 because a deliverable was incomplete. We can pay £300 now and £500 next month.'


def next_month(day):
    month = day.month % 12 + 1
    year = day.year + (day.month == 12)
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def acme_facts(customer_id):
    facts = {
        'contract': {'reference':'ACME-CONTRACT-001','customer_id':customer_id,'synthetic':True,'currency':'gbp',
                     'total':100_000,'deliverables':[{'id':'service','amount':80_000},{'id':'report','amount':20_000}],
                     'adjustment_clause':'An incomplete deliverable may be removed at its contracted value, capped at 20%.'},
        'policy': {'reference':'ACME-POLICY-001','customer_id':customer_id,'synthetic':True,'currency':'gbp',
                   'max_adjustment_bps':2000,'instalments':[30_000,50_000],'maximum_days':45,
                   'replacement_safeguards':['test_mode','application_owned','unpaid','draft_replacements_first','no_auto_advance']},
        'dispute': {'reference':'ACME-DISPUTE-001','customer_id':customer_id,'synthetic':True,
                    'message':CUSTOMER_MESSAGE,'acceptance_record':{'reference':'ACME-ACCEPTANCE-001','incomplete_deliverable':'report'}},
        'promise': {'reference':'ACME-PROMISE-001','customer_id':customer_id,'synthetic':True,
                    'message':CUSTOMER_MESSAGE,'history':'Customer proposed £300 now and £500 next calendar month; not yet paid.'}
    }
    for kind, content in facts.items():
        content['money_unit'] = 'GBP pence; 100 pence = £1. All integer financial amounts use pence.'
        content['money_summary'] = 'Original £1,000 (100000 pence); incomplete report £200 (20000 pence); settlement £800 (80000 pence); instalments £300 (30000 pence) and £500 (50000 pence).'
    return facts


def validate_settlement(proposal, facts):
    require(proposal.get('currency') == 'gbp', 'Settlement must be GBP')
    require(type(proposal.get('original')) is int and proposal['original'] == 100_000, 'Original must be £1,000')
    require(type(proposal.get('adjustment')) is int and proposal['adjustment'] == 20_000, 'Adjustment must be £200')
    require(proposal.get('customer_id') == facts['contract']['customer_id'], 'Customer mismatch')
    require(all(v.get('customer_id') == proposal['customer_id'] for v in facts.values()), 'Mixed customer facts')
    contract, policy, dispute = facts['contract'], facts['policy'], facts['dispute']
    require(contract.get('synthetic') is True and policy.get('synthetic') is True, 'Only approved synthetic demo facts are permitted')
    require(contract.get('total') == 100_000 and contract.get('currency') == 'gbp', 'Contract value or currency changed')
    require(contract.get('reference') == 'ACME-CONTRACT-001' and policy.get('reference') == 'ACME-POLICY-001', 'Unknown contract or policy')
    require(policy.get('max_adjustment_bps') == 2000 and policy.get('maximum_days') == 45, 'Policy changed')
    require(proposal['adjustment'] * 10_000 <= proposal['original'] * policy['max_adjustment_bps'], 'Credit cap exceeded')
    require(dispute.get('acceptance_record') == {'reference':'ACME-ACCEPTANCE-001','incomplete_deliverable':'report'},
            'Incomplete-deliverable evidence is missing')
    require(contract.get('deliverables') == [{'id':'service','amount':80_000},{'id':'report','amount':20_000}], 'Deliverable values changed')
    require(proposal.get('evidence_hashes') == {k:digest(v) for k,v in facts.items()}, 'Evidence has changed')
    rows = proposal.get('instalments')
    require(type(rows) is list and len(rows) == 2, 'Exactly two replacement invoices are required')
    require([pennies(row.get('amount')) for row in rows] == [30_000,50_000], 'Approved schedule is £300 / £500')
    agreed = date.fromisoformat(proposal['agreement_date'])
    due = [date.fromisoformat(row['due']) for row in rows]
    require(due == [agreed,next_month(agreed)], 'Second payment must be next calendar month')
    require(0 < (due[1]-agreed).days <= policy['maximum_days'], 'Payment horizon exceeds policy')
    require(sum(row['amount'] for row in rows) == proposal['original']-proposal['adjustment'], 'Schedule does not reconcile')
    return {'allowed':True,'policy_version':'acme-replacement-v1','adjustment':20_000,'replacement_total':80_000,
            'checks':['GBP','customer isolation','contracted incomplete deliverable','20% cap','exact £300/£500 sum',
                      'next-calendar-month schedule','45-day maximum']}


class CoreWorkflow(Engine):
    def create_case(self, request_id, customer_name='Acme Solutions', workflow='replacement'):
        return super().create_case(request_id, customer_name, workflow)

    def customer_memory(self, case):
        self.memory_for(case)
        return self.scoped_memories[case['customer_id']]

    def prepare(self, case):
        self.require_ready()
        if case.get('stage')=='replaced':
            return self.core_reconcile(case)
        require(not case.get('replacements'), 'Replacement workflow already started; resume core-run instead')
        memory = self.customer_memory(case)
        facts = acme_facts(case['customer_id'])
        for kind, content in facts.items():
            receipt = memory.store(kind, content, content['reference'])
            self.audit(case['id'], 'customer_memory_stored', {'kind':kind,'document_hash':digest(content),'receipt':receipt})
        case['facts'] = facts
        case['customer_message'] = CUSTOMER_MESSAGE
        self.store.put('cases',case['id'],case)
        case = self.issue_invoice(case)
        # Retrieve both actual entities, rather than trusting create responses or local IDs.
        customer, customer_receipt = self.stripe.request('GET','/customers/'+case['stripe_customer'])
        require(customer.get('id') == case['stripe_customer'] and customer.get('metadata',{}).get('collectiq_case') == case['id'],
                'Stripe customer ownership does not match')
        invoice, invoice_receipt = self.read_invoice(case)
        require(invoice['status'] == 'open' and invoice['amount_remaining'] == 100_000, 'Original must be unpaid and open')
        self.audit(case['id'],'core_original_verified',{'customer':stripe_summary(customer),'customer_receipt':customer_receipt,
                                                      'invoice':stripe_summary(invoice),'invoice_receipt':invoice_receipt})
        case['invoice']=stripe_summary(invoice)
        self.store.put('cases',case['id'],case)
        return case

    def propose(self, case):
        self.require_ready()
        if case.get('proposal'):
            validate_settlement(case['proposal'],case['facts'])
            return case
        require(case.get('invoice') and case.get('facts'), 'Prepare the Acme customer, invoice and memories first')
        memory = self.customer_memory(case)
        memory.index()
        retrieval = memory.retrieve_evidence()
        facts = case['facts']
        # All authoritative documents must be retrieved. The local snapshots alone cannot pass this gate.
        for kind in ('contract','policy','dispute','promise'):
            require(digest(facts[kind]) in canonical(retrieval['results']), f'Cognee did not retrieve the exact {kind} evidence hash')
        invoice, receipt = self.read_invoice(case)
        require(invoice['status']=='open' and invoice['amount_paid']==0 and invoice['amount_remaining']==100_000
                and invoice.get('pre_payment_credit_notes_amount',0)==0, 'Original invoice changed before proposal')
        reasoning = memory.retrieve(
            'All integer monetary amounts in these documents are GBP PENCE, not pounds: 100000 pence = £1000, 20000 pence = £200, '
            '30000 pence = £300, 50000 pence = £500. Based only on this customer dataset, state whether ACME-CONTRACT-001, ACME-POLICY-001 and ACME-ACCEPTANCE-001 '
            'support removing the incomplete £200 report from the £1000 invoice and arranging £300 now and £500 next calendar month. '
            'Give a concise conclusion with document references; do not execute any actions.', 'GRAPH_COMPLETION')
        require(bool(reasoning['results']), 'Cognee returned no reasoning result')
        today = date.today()
        proposal = {'customer_id':case['customer_id'],'customer_name':'Acme Solutions','case_id':case['id'],
                    'original_invoice_id':invoice['id'],'original':100_000,'adjustment':20_000,'currency':'gbp',
                    'agreement_date':today.isoformat(),'instalments':[{'amount':30_000,'due':today.isoformat()},
                                                                  {'amount':50_000,'due':next_month(today).isoformat()}],
                    'evidence_hashes':{kind:digest(value) for kind,value in facts.items()},
                    'explanation':'The synthetic acceptance record confirms the £200 report is incomplete. The contract permits removing its contracted value. '
                                  '£300 now plus £500 next calendar month exactly settles the remaining £800 within 45 days.',
                    'strategy':'Prepare two drafts, verify original ownership and no payments, void only this workflow-created original, then finalise replacements.',
                    'status':'proposed'}
        validation = validate_settlement(proposal,facts)
        self.audit(case['id'],'settlement_proposed',{'proposal':proposal,'validation':validation,'retrieval':retrieval,
                                                   'reasoning':reasoning,'invoice_receipt':receipt})
        memory.store_decision(proposal,proposal['explanation'],'ACME-SETTLEMENT-'+case['id'])
        case.update(proposal=proposal,validation=validation,stage='proposed',reasoning=reasoning)
        self.store.put('cases',case['id'],case)
        return case

    def replacement_invoice(self, case, index):
        row=case['proposal']['instalments'][index]
        due=int(datetime.combine(date.fromisoformat(row['due']),day_time(23,59),timezone.utc).timestamp())
        invoice=self.stripe_write(case,f'replacement-{index}-create','/invoices',
                                  {'customer':case['stripe_customer'],'currency':'gbp','collection_method':'send_invoice',
                                   'due_date':due,'auto_advance':'false','pending_invoice_items_behavior':'exclude',
                                   'automatic_tax[enabled]':'false','metadata[collectiq_case]':case['id'],
                                   'metadata[replaces_invoice]':case['invoice']['id'],'metadata[settlement_hash]':digest(case['proposal']),
                                   'description':f'Acme settlement instalment {index+1} · replaces {case["invoice"]["id"]}'})
        self.stripe_write(case,f'replacement-{index}-line','/invoiceitems',
                          {'customer':case['stripe_customer'],'invoice':invoice['id'],'amount':row['amount'],'currency':'gbp',
                           'discountable':'false','description':f'Approved £800 settlement · instalment {index+1}'})
        actual,receipt=self.stripe.request('GET','/invoices/'+invoice['id'])
        self.check_replacement(case,actual,index)
        require(actual['status']=='draft','Replacement must remain a draft until original is safely retired')
        self.audit(case['id'],'replacement_draft_verified',{'invoice':stripe_summary(actual),'receipt':receipt})
        return stripe_summary(actual)

    def check_replacement(self,case,invoice,index):
        require(invoice.get('livemode') is False and invoice.get('customer')==case['stripe_customer'], 'Replacement customer or mode differs')
        require(invoice.get('currency')=='gbp' and invoice.get('total')==case['proposal']['instalments'][index]['amount'],
                'Replacement amount or currency differs')
        require(invoice.get('metadata',{}).get('collectiq_case')==case['id']
                and invoice.get('metadata',{}).get('replaces_invoice')==case['invoice']['id']
                and invoice.get('metadata',{}).get('settlement_hash')==digest(case['proposal']), 'Replacement ownership or settlement hash differs')

    def replace(self, case):
        self.require_ready()
        require(case.get('proposal'), 'Produce and validate a proposal before replacing invoices')
        validate_settlement(case['proposal'],case['facts'])
        self.sync_memory()
        require(self.store.integrity(),'Audit integrity check failed')
        case.setdefault('replacements',[])
        if case.get('stage')=='replaced':
            return self.core_reconcile(case)
        for index in range(2):
            if len(case['replacements'])<=index:
                case['replacements'].append(self.replacement_invoice(case,index))
                self.store.put('cases',case['id'],case)
        # Durable intent plus both drafts precede any change to an existing invoice.
        original,receipt=self.read_invoice(case)
        if original['status']!='void':
            creation = [self.store.get('operations',f'{self.stripe.scope}:{case["id"]}:{suffix}',{})
                        for suffix in ('create-invoice','create-invoice-email-validated-v2')]
            require(any(op.get('response',{}).get('id')==original['id'] for op in creation),
                    'Original has no verified application creation receipt')
            require(original['status']=='open' and original['amount_paid']==0 and original['amount_remaining']==100_000
                    and original.get('pre_payment_credit_notes_amount',0)==0, 'Original was paid, credited or modified; replacement is blocked')
            require(original.get('auto_advance') is False and original.get('collection_method')=='send_invoice',
                    'Original automatic collection settings changed')
            payments=original.get('payments',{}).get('data',[])
            require(not any((p.get('amount_paid') or 0)>0 or p.get('status')=='paid' or not p.get('is_default',False) for p in payments),
                    'Original has a payment or externally attached payment intent; replacement is blocked')
            for index,draft in enumerate(case['replacements']):
                obj,r=self.stripe.request('GET','/invoices/'+draft['id'])
                self.check_replacement(case,obj,index)
                require(obj['status']=='draft' and obj['amount_paid']==0,'Both replacements must be unpaid drafts before voiding original')
                require(obj.get('auto_advance') is False,'Replacement automatic advancement changed')
            self.audit(case['id'],'replacement_safeguards_passed',{'original':stripe_summary(original), 'receipt':receipt,
                       'draft_ids':[i['id'] for i in case['replacements']], 'proposal_hash':digest(case['proposal']),
                       'safeguards':['application-owned case metadata','GBP 1000 exact original','zero paid and zero credits',
                                     'two verified drafts totalling GBP 800','no attached external payment','auto_advance disabled']})
            self.stripe_write(case,'replacement-void-original','/invoices/'+original['id']+'/void',{})
        else:
            op=self.store.get('operations',f'{self.stripe.scope}:{case["id"]}:replacement-void-original')
            require(op is not None,'Original was voided outside this workflow; stop for review')
        original,receipt=self.read_invoice(case)
        require(original['status']=='void' and original['amount_paid']==0,'Stripe did not confirm safe retirement of original')
        case['invoice']=stripe_summary(original)
        case['stage']='original_retired'
        self.store.put('cases',case['id'],case)
        for index,draft in enumerate(case['replacements']):
            obj,r=self.stripe.request('GET','/invoices/'+draft['id'])
            self.check_replacement(case,obj,index)
            if obj['status']=='draft':
                self.stripe_write(case,f'replacement-{index}-finalize','/invoices/'+obj['id']+'/finalize',{'auto_advance':'false'})
            obj,r=self.stripe.request('GET','/invoices/'+draft['id'])
            self.check_replacement(case,obj,index)
            require(obj['status']=='open' and obj['amount_paid']==0 and obj['amount_remaining']==obj['total'], 'Replacement did not finalize as unpaid/open')
            case['replacements'][index]=stripe_summary(obj)
            self.store.put('cases',case['id'],case)
            self.audit(case['id'],'replacement_invoice_open',{'invoice':stripe_summary(obj),'receipt':r})
        result={'customer_id':case['customer_id'],'proposal':case['proposal'],'original':case['invoice'],'replacements':case['replacements'],
                'outstanding':sum(i['amount_remaining'] for i in case['replacements']),'cash_collected':0,
                'status':'replacement_invoices_created_not_paid'}
        require(result['outstanding']==80_000,'Replacement exposure does not equal £800')
        self.customer_memory(case).store('execution',result,'ACME-EXECUTION-'+case['id'])
        self.audit(case['id'],'replacement_workflow_complete',result)
        self.customer_memory(case).index()
        case['stage']='replaced'
        self.store.put('cases',case['id'],case)
        return case

    def core_reconcile(self,case):
        original,r=self.read_invoice(case)
        require(original['status']=='void','Original is no longer void')
        result=[]
        for index,row in enumerate(case['replacements']):
            obj,receipt=self.stripe.request('GET','/invoices/'+row['id'])
            self.check_replacement(case,obj,index)
            require(obj['status']=='open' and obj['amount_paid']==0,'Replacement is no longer unpaid/open; inspect actual payments')
            result.append(stripe_summary(obj))
        case['invoice']=stripe_summary(original)
        case['replacements']=result
        self.audit(case['id'],'core_reconciliation',{'original':case['invoice'],'replacements':result,'outstanding':sum(i['amount_remaining'] for i in result)})
        self.store.put('cases',case['id'],case)
        return case

    def core_run(self,case):
        if case.get('stage')=='replaced':
            return self.core_reconcile(case)
        if not case.get('proposal'):
            case=self.prepare(case)
            case=self.propose(case)
        return self.replace(case)

    def refresh_reasoning(self,case):
        self.require_ready()
        memory=self.customer_memory(case)
        correction={'customer_id':case['customer_id'],'reference':'ACME-CURRENCY-UNITS-001','synthetic':True,
                    'rule':'Every integer financial amount in ACME-CONTRACT-001 and ACME-POLICY-001 is GBP PENCE, never pounds.',
                    'original':'100000 pence = GBP 1000','adjustment':'20000 pence = GBP 200',
                    'instalments':['30000 pence = GBP 300','50000 pence = GBP 500'],
                    'explanation':'The policy instalment values [30000,50000] explicitly authorise GBP 300 and GBP 500, totalling GBP 800. '
                                  'The 20% cap on GBP 1000 is GBP 200. This clarifies units; it does not change the contract, approved proposal or Stripe objects.'}
        memory.store_policy(correction,correction['reference'])
        memory.index()
        reasoning=memory.retrieve(
            'Apply ACME-CURRENCY-UNITS-001. ALL integer money values are GBP PENCE, not pounds. '
            '100000 pence=GBP1000; 20000 pence=GBP200; 30000 pence=GBP300; 50000 pence=GBP500. '
            'State concisely whether the incomplete GBP200 report meets the 20% cap on GBP1000, and whether the policy instalments '
            '[30000,50000] pence authorise GBP300 now and GBP500 next calendar month, within its 45-day limit. '
            'Cite document references. Do not treat pence as pounds. Do not execute actions.', 'GRAPH_COMPLETION')
        self.audit(case['id'],'reasoning_currency_clarified',{'clarification':correction,'reasoning':reasoning,
                                                          'financial_proposal_unchanged':True})
        case['reasoning']=reasoning
        self.store.put('cases',case['id'],case)
        return case

    def execute(self,case_id,action):
        actions={'core-prepare':self.prepare,'core-propose':self.propose,'core-replace':self.replace,'core-run':self.core_run,
                 'core-reasoning':self.refresh_reasoning}
        if action not in actions:
            if self.case(case_id).get('workflow')=='replacement':
                require(action=='invoice' and self.case(case_id).get('stage')=='ready',
                        'Use the guarded core workflow for replacement cases')
            return super().execute(case_id,action)
        with self.lock:
            self.require_ready()
            try:
                return actions[action](self.case(case_id))
            except Exception as error:
                self.audit(case_id,'execution_stopped',{'action':action,'error':str(error)},required=False)
                raise
