"""Opt-in Stripe test execution for NEW authorised agent cases; never existing Acme invoices."""
from datetime import datetime, date, time, timezone
from .agent_policy import validate_offer
from .integrations import stripe_summary
from .policy import require,digest


def execute_new_test_case(engine,workflow_id,authorise_new_test_case=False):
    require(authorise_new_test_case is True,'Explicit --authorise-new-test-case is required; agents default to DRY_RUN')
    w=engine.store.get('workflows',workflow_id)
    require(w is not None and w.get('synthetic') is True,'Only seeded synthetic workflows can execute')
    require(w['customer_id'] in ('agent-demo-atlas','agent-demo-briar','agent-demo-cedar'),'Customer is outside the authorised hackathon allowlist')
    require(w['outcome']=='AGREED' and w.get('policy_validation',{}).get('allowed') is True,'Only a validated accepted agreement can execute')
    require(w['invoice'].get('stripe_invoice_id') is None and w['invoice']['source']=='scenario_input','Existing financial obligations cannot enter new-case execution')
    validate_offer(w['accepted_offer'],w['limits']['balance_pence'],w['adjustment_pence'],w['limits'],w['evidence_refs'],date.fromisoformat(w['agreement_date']))
    engine.require_ready()
    case_id='agentexec_'+workflow_id
    case=engine.store.get('cases',case_id)
    if case is None:
        case={'id':case_id,'customer_id':w['customer_id'],'customer_name':w['customer_name']+' · authorised new test case',
              'workflow':'agent-execution','stage':'authorised','invoice':None,'replacements':[], 'payments':[],
              'original_amount':w['invoice']['amount_pence'],'currency':'gbp','synthetic':True,'agent_workflow_id':workflow_id,
              'scenario':'Explicitly authorised new Stripe test obligation; no existing Acme invoice is reused.'}
        engine.store.put('cases',case_id,case)
    require(case['customer_id']==w['customer_id'] and case['agent_workflow_id']==workflow_id,'Execution case ownership changed')
    def save():engine.store.put('cases',case_id,case)
    def write(suffix,path,params):return engine.stripe_write(case,'agent-'+suffix,path,params)
    def read(invoice_id):return engine.stripe.request('GET','/invoices/'+invoice_id,{'expand[]':'payments'})
    def verify(obj,total):
        require(obj.get('livemode') is False and obj.get('customer')==case['stripe_customer'],'Wrong customer or Stripe mode')
        require(obj.get('currency')=='gbp' and obj.get('total')==total,'Invoice amount changed')
        require(obj.get('metadata',{}).get('collectiq_case')==case_id and obj['metadata'].get('agent_workflow')==workflow_id,
                'Invoice ownership failed')
        require(obj.get('auto_advance') is False,'Automatic collection must remain disabled')
    with engine.lock:
        engine.sync_memory()
        engine.audit(case_id,'agent_execution_explicitly_authorised',{'workflow_id':workflow_id,'new_test_case':True,
                     'accepted_offer_hash':digest(w['accepted_offer']),'protected_acme_untouched':True})
        if not case.get('stripe_customer'):
            customer=write('customer','/customers',{'name':case['customer_name'],'email':'collectiq-'+workflow_id+'@example.com',
                           'metadata[collectiq_case]':case_id,'metadata[agent_workflow]':workflow_id})
            case['stripe_customer']=customer['id'];save()
        def draft(suffix,amount,due=None,replaces=None):
            params={'customer':case['stripe_customer'],'currency':'gbp','collection_method':'send_invoice','auto_advance':'false',
                    'pending_invoice_items_behavior':'exclude','automatic_tax[enabled]':'false','metadata[collectiq_case]':case_id,
                    'metadata[agent_workflow]':workflow_id,'description':'CollectIQ explicitly authorised new Task 2 test case'}
            if due:
                params['due_date']=int(datetime.combine(date.fromisoformat(due),time(23,59),timezone.utc).timestamp())
            else:params['days_until_due']=14
            if replaces:params['metadata[replaces_invoice]']=replaces
            obj=write(suffix+'-create','/invoices',params)
            write(suffix+'-line','/invoiceitems',{'customer':case['stripe_customer'],'invoice':obj['id'],'currency':'gbp','amount':amount,
                  'discountable':'false','description':'Validated agent settlement in integer GBP pence'})
            actual,receipt=read(obj['id']);verify(actual,amount)
            return stripe_summary(actual)
        if not case.get('invoice'):
            original=draft('original',case['original_amount'])
            write('original-finalize','/invoices/'+original['id']+'/finalize',{'auto_advance':'false'})
            obj,receipt=read(original['id']);verify(obj,case['original_amount'])
            require(obj['status']=='open' and obj['amount_paid']==0,'New original must be open/unpaid')
            case['invoice']=stripe_summary(obj);save()
        for index,row in enumerate(w['accepted_offer']['instalments']):
            if len(case['replacements'])<=index:
                case['replacements'].append(draft(f'replacement-{index}',row['amount_pence'],row['due'],case['invoice']['id']));save()
        original,receipt=read(case['invoice']['id']);verify(original,case['original_amount'])
        if original['status']!='void':
            require(original['status']=='open' and original['amount_paid']==0
                    and original['amount_remaining']==case['original_amount'] and original.get('pre_payment_credit_notes_amount',0)==0,
                    'New original was externally changed; stop before replacement')
            require(not any((p.get('amount_paid') or 0)>0 or not p.get('is_default',False) for p in original.get('payments',{}).get('data',[])),
                    'Original has external or successful payments')
            for index,row in enumerate(case['replacements']):
                obj,r=read(row['id']);verify(obj,w['accepted_offer']['instalments'][index]['amount_pence'])
                require(obj['status']=='draft','Replacements must remain drafts before original retirement')
            engine.audit(case_id,'agent_replacement_safeguards_passed',{'original':stripe_summary(original),'receipt':receipt,
                          'replacement_ids':[i['id'] for i in case['replacements']],'policy_validation':w['policy_validation']})
            write('void-original','/invoices/'+original['id']+'/void',{})
        else:
            require(engine.store.get('operations',f'{engine.stripe.scope}:{case_id}:agent-void-original') is not None,
                    'Original was voided outside this workflow')
        original,receipt=read(original['id']);require(original['status']=='void','Original retirement not confirmed')
        case['invoice']=stripe_summary(original);save()
        for index,row in enumerate(case['replacements']):
            obj,r=read(row['id']);verify(obj,w['accepted_offer']['instalments'][index]['amount_pence'])
            if obj['status']=='draft':write(f'replacement-{index}-finalize','/invoices/'+obj['id']+'/finalize',{'auto_advance':'false'})
            obj,r=read(obj['id']);verify(obj,w['accepted_offer']['instalments'][index]['amount_pence'])
            require(obj['status']=='open' and obj['amount_paid']==0,'Replacement did not finalise unpaid/open')
            case['replacements'][index]=stripe_summary(obj);save()
        case['stage']='replaced';save()
        w['stripe_execution']={'status':'COMPLETED','mode':'STRIPE_TEST','case_id':case_id,'original':case['invoice'],
                               'replacements':case['replacements'],'cash_collected':0}
        engine.store.put('workflows',workflow_id,w)
        engine.customer_memory(w).store('execution',w['stripe_execution'],'EXECUTION-'+workflow_id)
        engine.audit(case_id,'agent_test_execution_completed',w['stripe_execution'])
        return w['stripe_execution']
