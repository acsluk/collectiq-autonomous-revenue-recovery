"""Verify the real loopback service boundary without financial writes."""
import json
import urllib.error
import urllib.request
from .config import Settings
from .policy import require


def main():
    settings=Settings()
    base=f'http://127.0.0.1:{settings.port}'
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def call(path,method='GET',headers=None,body=None):
        req=urllib.request.Request(base+path,data=body,method=method,headers=headers or {})
        try:
            with opener.open(req,timeout=10) as response:return response.status,response.read()
        except urllib.error.HTTPError as e:return e.code,e.read()
    state_status,raw=call('/api/state')
    require(state_status==200,'State API is not serving')
    state=json.loads(raw)
    require(all(secret.encode() not in raw for secret in (settings.stripe_key,settings.cognee_key) if secret), 'API exposed a credential')
    static_status,_=call('/')
    secret_status,_=call('/.env')
    _,session_raw=call('/api/session')
    token=json.loads(session_raw)['token']
    missing_token,_=call('/api/cases','POST',{'Origin':base,'Content-Type':'application/json'},b'{}')
    cross_origin,_=call('/api/cases','POST',{'Origin':'https://untrusted.invalid','Content-Type':'application/json','X-CollectIQ-Token':token},b'{}')
    require(static_status==200 and secret_status==404,'Static boundary check failed')
    require(missing_token==403 and cross_origin==403,'Mutation origin/token protection failed')
    print(json.dumps({'status':'verified','dashboard':static_status,'state':state_status,'env_file':secret_status,
                      'missing_session_token':missing_token,'cross_origin':cross_origin,'credentials_exposed':False,
                      'case_count':len(state['cases'])},indent=2))


if __name__=='__main__':main()
