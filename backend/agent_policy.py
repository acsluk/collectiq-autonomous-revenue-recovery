"""Task 2 financial authority. Reasoning output is a proposal, never execution authority."""
from datetime import date
from .core import next_month
from .policy import require, digest

CLASSIFICATIONS={'PAYMENT_DIFFICULTY','BILLING_DISPUTE','MISSING_DOCUMENTATION','PAYMENT_PROMISE','READY_TO_SETTLE','REQUIRES_HUMAN_REVIEW'}
SPECIALISTS={'PAYMENT_DIFFICULTY':'PromisePay','BILLING_DISPUTE':'Dispute2Cash','MISSING_DOCUMENTATION':'Dispute2Cash',
             'PAYMENT_PROMISE':'PromisePay','READY_TO_SETTLE':'Agent2Agent','REQUIRES_HUMAN_REVIEW':'HumanReview'}
STATES={'RECEIVED','INVESTIGATING','NEGOTIATING','VALIDATING','EXECUTING','COMPLETED','BLOCKED','REQUIRES_REVIEW','FAILED'}


def integer(value,label,minimum=0,maximum=10_000_000):
    require(type(value) is int and minimum<=value<=maximum,f'{label} must be integer pence in [{minimum},{maximum}]')
    return value


def scenario(name):
    require(name in ('A','B','C'),'Choose scenario A, B or C')
    disputed=name=='C'
    original=75_000 if disputed else 80_000
    adjustment=15_000 if disputed else 0
    customer_id={'A':'agent-demo-atlas','B':'agent-demo-briar','C':'agent-demo-cedar'}[name]
    facts={
        'contract':{'reference':f'CONTRACT-{name}-001','customer_id':customer_id,'synthetic':True,
                    'original_pence':original,'currency':'gbp','line_items':
                    ([{'id':'service','amount_pence':60_000},{'id':'report','amount_pence':15_000}] if disputed else [{'id':'service','amount_pence':80_000}]),
                    'adjustment_clause':'Only the contracted value of a documented undelivered line may be removed, capped at 20%.'},
        'policy':{'reference':f'POLICY-{name}-001','customer_id':customer_id,'synthetic':True,'currency':'gbp',
                  'minimum_upfront_bps':3000,'broken_promise_minimum_upfront_bps':10_000,
                  'maximum_adjustment_bps':2000,'maximum_days':45,'preferred_rounding_pence':5000},
        'history':{'reference':f'HISTORY-{name}-001','customer_id':customer_id,'synthetic':True,
                   'promises':[{'id':f'PROMISE-{name}-PREVIOUS','status':'broken' if name=='B' else 'kept',
                                'amount_pence':30_000,'due':'2026-09-15',
                                'explanation':'Synthetic prior commitment was missed' if name=='B' else 'Synthetic previous commitment kept'}]},
        'preferences':{'reference':f'PREFERENCES-{name}-001','customer_id':customer_id,'synthetic':True,
                       'preference':'Two instalments; prefers next-calendar-month payment for the balance.'}
    }
    if disputed:
        facts['delivery']={'reference':'DELIVERY-C-001','customer_id':customer_id,'synthetic':True,
                           'line_items':[{'id':'service','status':'delivered'},{'id':'report','status':'not_delivered'}],
                           'acceptance_record':'The final report is documented as not delivered.'}
    for value in facts.values():
        value['money_unit']='All monetary integers are GBP pence. 100 pence = GBP 1.'
    balance=original-adjustment
    upfront=15_000 if disputed else 20_000
    return {'scenario':name,'customer_id':customer_id,'customer_name':{'A':'Atlas Digital','B':'Briar Commerce','C':'Cedar Labs'}[name],
            'synthetic':True,'execution_mode':'DRY_RUN','invoice':{'source':'scenario_input','stripe_invoice_id':None,
                'currency':'gbp','amount_pence':original,'status':'UNBILLED_DRY_RUN'},
            'message':('We dispute £150 because the final report was not delivered. We can pay £150 now and the rest next month.' if disputed
                       else 'I can pay £200 now and £600 next month.'),
            'facts':facts,'buyer_authority':{'simulated':True,'maximum_upfront_pence':25_000,'maximum_total_pence':balance,
                                           'maximum_days':45,'initial_upfront_pence':upfront},
            'disputed_line_id':'report' if disputed else None}


def validate_refs(refs,allowed):
    require(type(refs) is list and len(refs)>0 and all(type(r) is str and r in allowed for r in refs),
            'Evidence references must cite retrieved customer documents')
    return refs


def validate_route(result,allowed):
    require(type(result) is dict,'Routing output must be an object')
    require(result.get('classification') in CLASSIFICATIONS,'Unknown classification')
    require(result.get('specialist')==SPECIALISTS[result['classification']],'Specialist does not match classification')
    require(type(result.get('confidence')) in (int,float) and 0<=result['confidence']<=1,'Confidence must be between zero and one')
    require(result.get('risk') in ('LOW','MEDIUM','HIGH'),'Invalid financial risk classification')
    require(type(result.get('reasoning')) is str and 1<=len(result['reasoning'])<=3000,'Missing reasoning summary')
    require(type(result.get('action')) is str and 1<=len(result['action'])<=1000,'Missing selected action')
    validate_refs(result.get('evidence_refs'),allowed)
    return result


def supported_adjustment(facts,line_id):
    if line_id is None:return 0
    require('delivery' in facts,'Missing delivery evidence requires human review')
    contract=facts['contract'];policy=facts['policy']
    lines=[row for row in contract['line_items'] if row['id']==line_id]
    proof=[row for row in facts['delivery']['line_items'] if row['id']==line_id]
    require(len(lines)==1 and len(proof)==1,'Missing or ambiguous disputed line evidence')
    require(proof[0]['status']=='not_delivered','Delivery evidence contradicts the adjustment')
    amount=integer(lines[0]['amount_pence'],'Supported adjustment',1)
    require(amount*10_000<=contract['original_pence']*policy['maximum_adjustment_bps'],'Adjustment exceeds the policy cap')
    return amount


def terms(facts,balance):
    integer(balance,'Balance',1)
    broken=[p for p in facts['history']['promises'] if p['status']=='broken']
    policy=facts['policy']
    bps=policy['broken_promise_minimum_upfront_bps'] if broken else policy['minimum_upfront_bps']
    minimum=(balance*bps+9999)//10_000
    rounding=policy['preferred_rounding_pence']
    preferred=min(balance,((minimum+rounding-1)//rounding)*rounding)
    return {'minimum_upfront_pence':minimum,'preferred_upfront_pence':preferred,'balance_pence':balance,
            'broken_promises':[p['id'] for p in broken],'upfront_bps':bps,'maximum_days':policy['maximum_days'],
            'policy_reference':policy['reference'],'history_reference':facts['history']['reference']}


def validate_offer(offer,balance,adjustment,limits,allowed,today=None,buyer=None):
    require(type(offer) is dict,'Offer must be an object')
    require(offer.get('action') in ('OFFER','COUNTEROFFER','ACCEPT','REJECT','REVIEW'),'Invalid offer action')
    require(offer.get('currency')=='gbp','Only GBP offers are permitted')
    require(integer(offer.get('adjustment_pence'),'Adjustment')==adjustment,'Agent changed the authorised adjustment')
    require(type(offer.get('reasoning')) is str and 0<len(offer['reasoning'])<=4000,'Offer requires an explanation')
    validate_refs(offer.get('evidence_refs'),allowed)
    if offer['action'] in ('REJECT','REVIEW'):
        require(offer.get('instalments')==[],'Rejection must not contain a payment plan')
        return {'allowed':False,'action':offer['action'],'reason':offer['reasoning']}
    rows=offer.get('instalments')
    require(type(rows) is list and 1<=len(rows)<=2,'Offer requires one or two instalments')
    amounts=[integer(row.get('amount_pence'),'Instalment',1) for row in rows]
    require(sum(amounts)==balance,'Offer must exactly equal validated outstanding balance; no additional discount')
    today=today or date.today()
    dates=[date.fromisoformat(row['due']) for row in rows]
    require(dates[0]==today,'First instalment must be due today')
    if len(rows)==2:
        require(dates[0]<dates[1]<=next_month(today),'Second instalment must be no later than next calendar month')
    require((dates[-1]-today).days<=limits['maximum_days'],'Repayment horizon exceeds policy')
    if buyer:
        require(amounts[0]<=buyer['maximum_upfront_pence'] and sum(amounts)<=buyer['maximum_total_pence'], 'Buyer exceeded its predefined budget authority')
    else:
        require(amounts[0]>=limits['minimum_upfront_pence'],'Upfront instalment is below policy minimum')
    return {'allowed':True,'balance_pence':balance,'adjustment_pence':adjustment,'minimum_upfront_pence':limits['minimum_upfront_pence'],
            'instalments':rows,'policy_reference':limits['policy_reference'],'history_reference':limits['history_reference']}
