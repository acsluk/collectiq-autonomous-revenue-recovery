"""Task 2 executable demos: python -m backend.agent_cli run --scenario all."""
import argparse
import json
import sys
from .agents import AgentRunner
from .config import ROOT, Settings
from .core import CoreWorkflow
from .policy import require
from .store import Store, now


def protected_acme(engine):
    case=engine.store.get('cases','cq_1f246066264227319912')
    require(case is not None,'Verified Acme case is missing')
    result=[]
    for row in [case['invoice'],*case['replacements']]:
        obj,receipt=engine.stripe.request('GET','/invoices/'+row['id'])
        result.append({k:obj[k] for k in ('id','status','livemode','currency','customer','total','amount_paid','amount_remaining')})
    return result


def main():
    parser=argparse.ArgumentParser(description='CollectIQ real Cognee coordinated-agent demonstrations')
    parser.add_argument('command',choices=('run','why','state','verify','execute','model-info'))
    parser.add_argument('--scenario',choices=('A','B','C','all'),default='all')
    parser.add_argument('--request-id')
    parser.add_argument('--workflow-id')
    parser.add_argument('--authorise-new-test-case',action='store_true')
    parser.add_argument('--output',default='artifacts/task2-scenarios.json')
    args=parser.parse_args()
    store=Store(ROOT/'data'/'collectiq.sqlite3')
    engine=CoreWorkflow(Settings(),store);runner=AgentRunner(engine)
    code=0
    try:
        if args.command=='state':result={'workflows':store.workflows()}
        elif args.command=='model-info':
            usage,receipt=engine.memory.request('GET','/api/v1/sessions/cost-by-model?range=24h')
            names=set()
            def models(value):
                if isinstance(value,dict):
                    for key,child in value.items():
                        if key.lower() in ('model','model_name','modelname','llm_model','llmmodel') and isinstance(child,str):names.add(child)
                        else:models(child)
                elif isinstance(value,list):
                    for child in value:models(child)
            models(usage)
            result={'reasoning_api':'POST /api/v1/search','mode':'GRAPH_COMPLETION','reported_model_names':sorted(names),
                    'usage_receipt':receipt,'usage_response':usage,
                    'attribution':'Tenant session model usage; completion responses do not expose a per-call model identifier.'}
        elif args.command=='execute':
            from .agent_execution import execute_new_test_case
            require(args.workflow_id,'--workflow-id is required')
            result=execute_new_test_case(engine,args.workflow_id,args.authorise_new_test_case)
        elif args.command=='why':
            require(args.workflow_id,'--workflow-id is required')
            result=runner.why(args.workflow_id)
        elif args.command=='verify':
            baseline=json.loads((ROOT/'artifacts'/'task2-acme-baseline.json').read_text(encoding='utf-8'))
            actual=protected_acme(engine)
            require(actual==baseline,'Existing Acme invoice financial states changed')
            workflows=[w for w in store.workflows() if w['state']=='COMPLETED']
            require({w['scenario'] for w in workflows}>={'A','B','C'},'All three scenarios must complete')
            by={}
            for w in workflows:by.setdefault(w['scenario'],w)
            for w in by.values():
                require(w['conversation'][0]['offer']['action']=='OFFER','Buyer opening turn must be a genuine offer')
            require(by['A']['outcome']=='AGREED' and by['B']['outcome']=='REJECTED' and by['C']['outcome']=='AGREED','Unexpected scenario outcomes')
            require(all(w.get('rounds',0)<=3 for w in workflows),'Negotiation exceeded three rounds')
            require(by['C']['adjustment_pence']==15_000,'Dispute adjustment differs from GBP150')
            before=store.db.execute('SELECT count(*) FROM operations').fetchone()[0]
            replay=runner.run('A')
            require(replay['id']==by['A']['id'],'Replay created a different workflow')
            after=store.db.execute('SELECT count(*) FROM operations').fetchone()[0]
            require(before==after,'Agent replay created a Stripe financial operation')
            result={'status':'verified','checked_at':now(),'acme_unchanged':actual,'scenario_outcomes':{n:by[n]['outcome'] for n in ('A','B','C')},
                    'maximum_rounds':max(w.get('rounds',0) for w in workflows),'replay_new_stripe_operations':after-before,
                    'memory_informed_rejection':{'normal_minimum_pence':24_000,'with_broken_promise_pence':by['B']['limits']['minimum_upfront_pence'],
                                                'broken_promise_ids':by['B']['limits']['broken_promises']},'audit_hash_chain_valid':store.integrity()}
        else:
            engine.require_ready()
            baseline_path=ROOT/'artifacts'/'task2-acme-baseline.json'
            if not baseline_path.exists():
                baseline_path.parent.mkdir(exist_ok=True)
                baseline_path.write_text(json.dumps(protected_acme(engine),indent=2),encoding='utf-8')
            names=('A','B','C') if args.scenario=='all' else (args.scenario,)
            results=[]
            for name in names:
                print(f'Running scenario {name}: real Cognee recall and model-generated roles; DRY_RUN financial execution.',flush=True)
                w=runner.run(name,args.request_id)
                results.append(w)
                print(json.dumps({'scenario':name,'workflow_id':w['id'],'state':w['state'],'outcome':w.get('outcome'),
                                  'error':w.get('error'),'rounds':w.get('rounds'),'model_calls':len(w.get('model_calls',[]))}),flush=True)
                if w['state']!='COMPLETED':code=2
            result={'checked_at':now(),'workflows':results}
        path=ROOT/args.output
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(result,indent=2,ensure_ascii=True),encoding='utf-8')
        if args.command!='run':print(json.dumps(result,indent=2,ensure_ascii=True))
        print(f'Sanitized evidence saved to {args.output}',flush=True)
    finally:store.close()
    return code


if __name__=='__main__':sys.exit(main())
