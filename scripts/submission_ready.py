"""Submission-only read checks and credential-safe GitHub publication; no billing writes."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.error
import urllib.request

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from backend.config import Settings
from backend.core import CoreWorkflow
from backend.integrations import Transport
from backend.store import Store,now
from backend.agent_policy import scenario,terms,validate_offer

def git(*args,**kwargs):
    result=subprocess.run(['git',*args],cwd=ROOT,capture_output=True,text=True,timeout=kwargs.pop('timeout',20),**kwargs)
    if result.returncode:raise RuntimeError('Git operation failed: '+result.stderr[:250])
    return result.stdout

def checks():
    cfg=Settings();store=Store(ROOT/'data'/'collectiq.sqlite3');engine=CoreWorkflow(cfg,store)
    class FastTransport(Transport):
        def request(self,*args,**kwargs):
            kwargs['timeout']=20
            return super().request(*args,**kwargs)
    transport=FastTransport((cfg.stripe_key,cfg.cognee_key))
    engine.stripe.transport=transport;engine.memory.transport=transport
    report={'checked_at':now(),'financial_writes':0,'test_key_only':cfg.stripe_key.startswith(('sk_test_','rk_test_'))}
    try:
        report['stripe']=engine.stripe.verify()
        engine.memory.discover()
        _,r=engine.memory.request('GET','/api/v1/datasets')
        report['cognee_authentication']=r
        acme=store.get('cases','cq_1f246066264227319912')
        invoices=[]
        for row in [acme['invoice'],*acme['replacements']]:
            obj,receipt=engine.stripe.request('GET','/invoices/'+row['id'])
            invoices.append({k:obj[k] for k in ('id','status','total','amount_paid','amount_remaining','livemode')})
        assert [i['status'] for i in invoices]==['void','open','open']
        assert [i['amount_paid'] for i in invoices]==[0,0,0]
        report['acme']=invoices
        recalled=engine.customer_memory(acme).retrieve('Retrieve ACME-EXECUTION-cq_1f246066264227319912 and its actual replacement Stripe invoice IDs.','CHUNKS')
        raw=json.dumps(recalled)
        report['actual_invoice_ids_retrieved']=all(row['id'] in raw for row in acme['replacements'])
        report['retrieval_receipt']=recalled['receipt']
        report['scenarios']=[{'scenario':w['scenario'],'state':w['state'],'outcome':w.get('outcome'),'routing':w.get('routing',{}).get('specialist'),
                              'evidence_references':w.get('evidence_refs',[]),'error':w.get('error')} for w in store.workflows()]
        prior=json.loads((ROOT/'artifacts'/'live-acceptance.json').read_text())
        isolation=json.loads((ROOT/'artifacts'/'live-isolation.json').read_text())
        report['previously_verified_idempotency']=prior.get('idempotent_retry') is True
        report['previously_verified_customer_isolation']=isolation.get('status')=='verified' and isolation.get('cross_customer_leak_detected') is False
        report['audit_hash_chain_valid']=store.integrity()
        report['policy_minimum_on_800_pence']=terms(scenario('A')['facts'],80_000)['minimum_upfront_pence']
        report['status']='verified_core_submission_ready_with_disclosed_agent_limitations'
    except Exception as e:
        report['error']=str(e);report['status']='incomplete'
    finally:store.close()
    (ROOT/'submission').mkdir(exist_ok=True)
    (ROOT/'submission'/'READINESS.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))

def publish():
    cfg=Settings()
    entries=['.gitignore','.env.example','README.md','TASK2_REPORT.md','SUBMISSION.md','DEMO_PLAN.md','backend','frontend','scripts','submission','collectiq.ps1','run.ps1','package.json']
    files=[]
    for entry in entries:
        p=ROOT/entry
        files.extend([f for f in p.rglob('*') if f.is_file() and '__pycache__' not in f.parts and f.suffix!='.pyc'] if p.is_dir() else [p])
    for p in files:
        content=p.read_bytes()
        for secret in (cfg.stripe_key,cfg.cognee_key):
            if secret and secret.encode() in content:raise RuntimeError('Publication stopped: a credential was found in '+p.name)
    env={**os.environ,'GIT_TERMINAL_PROMPT':'0','GCM_INTERACTIVE':'never'}
    credential=subprocess.run(['git','credential','fill'],input='protocol=https\nhost=github.com\n\n',capture_output=True,text=True,env=env,timeout=8)
    values=dict(line.split('=',1) for line in credential.stdout.splitlines() if '=' in line)
    token=os.getenv('GH_TOKEN') or os.getenv('GITHUB_TOKEN') or values.get('password')
    if not token:raise RuntimeError('No authenticated GitHub credential is available. Source is ready locally; GitHub sign-in is required.')
    def api(method,path,data=None):
        req=urllib.request.Request('https://api.github.com'+path,method=method,
            data=json.dumps(data).encode() if data else None,
            headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json','User-Agent':'CollectIQ-submission','Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=15) as r:return json.load(r)
    user=api('GET','/user');name='collectiq-autonomous-revenue-recovery'
    repo=api('POST','/user/repos',{'name':name,'private':False,'description':'CollectIQ — Autonomous Revenue Recovery | Briefcase × Stripe Hackathon | Agents That Collect'})
    git('add','--',*entries)
    staged=git('diff','--cached','--name-only').splitlines()
    if any(p=='.env' or p.startswith('data/') or p.startswith('artifacts/') for p in staged):raise RuntimeError('Unsafe staged file selection')
    git('commit','-m','Prepare CollectIQ hackathon MVP and submission evidence')
    git('remote','add','origin',repo['clone_url'])
    git('push','-u','origin','HEAD:main',env=env,timeout=45)
    print(json.dumps({'repository_url':repo['html_url'],'public':not repo['private'],'pushed':True,'owner':user['login']}))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=('check','publish'));args=parser.parse_args()
    try:checks() if args.command=='check' else publish()
    except Exception as e:
        # Never print subprocess credential output or HTTP Authorization headers.
        print(json.dumps({'status':'blocked','error':str(e)}));sys.exit(2)
