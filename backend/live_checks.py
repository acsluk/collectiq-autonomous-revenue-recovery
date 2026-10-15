"""Actual API acceptance checks. No mocks, fixtures, or fabricated success responses."""
import argparse
import json
from .config import ROOT, Settings
from .core import CoreWorkflow
from .integrations import stripe_summary
from .store import Store, now
from .policy import require, canonical


def main():
    parser=argparse.ArgumentParser(description='CollectIQ real API checks')
    parser.add_argument('--phase',choices=('inspect','acceptance','isolation'),default='inspect')
    args=parser.parse_args()
    store=Store(ROOT/'data'/'collectiq.sqlite3')
    engine=CoreWorkflow(Settings(),store)
    case=engine.create_case('acme-hackathon-settlement-001')
    report={'checked_at':now(),'phase':args.phase,'case_id':case['id']}
    try:
        if args.phase=='inspect':
            customer,receipt=engine.stripe.request('GET','/customers/'+case['stripe_customer'])
            invoices,r=engine.stripe.request('GET','/invoices',{'customer':case['stripe_customer'],'limit':100})
            report.update(customer={'id':customer['id'],'email_configured':bool(customer.get('email')),
                                    'metadata':customer.get('metadata'),'livemode':customer.get('livemode'),'receipt':receipt},
                          invoices=[stripe_summary(i) for i in invoices['data']],invoices_receipt=r)
        elif args.phase=='acceptance':
            engine.require_ready()
            require(case['stage']=='replaced','Finish core workflow before acceptance verification')
            before=store.db.execute('SELECT count(*) FROM operations').fetchone()[0]
            original,receipt=engine.read_invoice(case)
            require(original['status']=='void' and original['amount_paid']==0,'Original was not retired without payment')
            checked=[]
            for index,row in enumerate(case['replacements']):
                obj,r=engine.stripe.request('GET','/invoices/'+row['id'])
                engine.check_replacement(case,obj,index)
                require(obj['status']=='open' and obj['amount_paid']==0,'Replacement must be unpaid/open')
                checked.append({'invoice':stripe_summary(obj),'receipt':r})
            all_invoices,r=engine.stripe.request('GET','/invoices',{'customer':case['stripe_customer'],'limit':100})
            owned=[i for i in all_invoices['data'] if i.get('metadata',{}).get('collectiq_case')==case['id']]
            require(len(owned)==3,'Unexpected duplicate or missing invoices for Acme case')
            memory=engine.customer_memory(case)
            retrieval=memory.retrieve(f"Find ACME-EXECUTION-{case['id']} with Stripe invoice IDs {' '.join(i['invoice']['id'] for i in checked)}",'CHUNKS')
            text=canonical(retrieval['results'])
            require(all(i['invoice']['id'] in text for i in checked),'Cognee did not retrieve the actual Stripe replacement IDs')
            engine.execute(case['id'],'core-run')
            after=store.db.execute('SELECT count(*) FROM operations').fetchone()[0]
            require(before==after,'Retry unexpectedly created a financial operation')
            report.update(status='verified',original={'invoice':stripe_summary(original),'receipt':receipt},replacements=checked,
                          invoice_count=len(owned),idempotent_retry=True,new_financial_operations_on_retry=after-before,
                          outstanding=sum(i['invoice']['amount_remaining'] for i in checked),cash_collected=0,
                          memory_retrieval=retrieval,audit_hash_chain_valid=store.integrity())
        else:
            memory=engine.customer_memory(case)
            other=engine.customer_memory({'customer_id':'collectiq-isolation-control-customer'})
            marker='OTHER_CUSTOMER_ISOLATION_CONTROL_9b6ba819'
            other.store_contract({'synthetic':True,'isolation_probe':marker},'ISOLATION-CONTROL')
            other.index()
            positive=other.retrieve(marker,'CHUNKS')
            require(marker in canonical(positive['results']),'Control marker was not retrievable in its own dataset')
            negative=memory.retrieve(marker,'CHUNKS')
            require(marker not in canonical(negative['results']),'Another customer memory leaked into Acme retrieval')
            report.update(status='verified',customer_dataset=memory.dataset,control_dataset=other.dataset,
                          positive_control=positive,negative_control=negative,cross_customer_leak_detected=False)
        path=ROOT/'artifacts'/f'live-{args.phase}.json'
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(report if args.phase=='inspect' else {k:v for k,v in report.items() if k not in ('memory_retrieval','positive_control','negative_control')},indent=2))
    finally:
        store.close()


if __name__=='__main__':main()
