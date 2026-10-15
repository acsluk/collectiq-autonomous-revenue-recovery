"""Loopback-only dashboard/API; secrets remain in the backend process."""
from concurrent.futures import ThreadPoolExecutor
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import secrets
import threading
from urllib.parse import urlsplit
from .config import ROOT, Settings
from .engine import Engine
from .core import CoreWorkflow
from .agents import AgentRunner
from .integrations import IntegrationError, redact
from .policy import PolicyError, require
from .policy import adjustment, demo_evidence, negotiate
from .store import Store, now


class Application:
    def __init__(self, engine):
        self.engine = engine
        self.token = secrets.token_urlsafe(32)
        self.jobs = {}
        self.jobs_lock = threading.Lock()
        self.executor = ThreadPoolExecutor(max_workers=1)

    def submit(self, fn):
        with self.jobs_lock:
            require(not any(j['status'] in ('queued', 'running') for j in self.jobs.values()), 'An operation is already running')
            job_id = secrets.token_hex(12)
            job = {'id': job_id, 'status': 'queued', 'created': now()}
            self.jobs[job_id] = job

        def work():
            job['status'] = 'running'
            try:
                with self.engine.lock:
                    job['result'] = fn()
                job['status'] = 'succeeded'
            except Exception as error:
                job.update(status='failed', error=redact(error, (self.engine.settings.stripe_key, self.engine.settings.cognee_key)),
                           http_status=getattr(error, 'status', None), request_id=getattr(error, 'request_id', None))
            job['finished'] = now()

        self.executor.submit(work)
        return dict(job)

    def handler(self):
        app = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                pass

            def send(self, status, value, mime='application/json; charset=utf-8'):
                body = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode()
                self.send_response(status)
                self.send_header('Content-Type', mime)
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'no-store')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.send_header('Referrer-Policy', 'no-referrer')
                self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
                self.end_headers()
                self.wfile.write(body)

            def host_allowed(self):
                port = self.server.server_address[1]
                return self.headers.get('Host') in (f'127.0.0.1:{port}', f'localhost:{port}')

            def do_GET(self):
                if not self.host_allowed():
                    return self.send(403, {'error': 'Loopback host required'})
                path = urlsplit(self.path).path
                try:
                    if path == '/api/session':
                        return self.send(200, {'token': app.token})
                    if path == '/api/state':
                        return self.send(200, app.engine.snapshot())
                    if path == '/api/scenario':
                        evidence = demo_evidence('preview-only')
                        return self.send(200, {'preview_only': True, 'financial_execution': False,
                                               'evidence': evidence, 'decision': adjustment(evidence, 'preview-only'),
                                               'negotiation': negotiate()})
                    if path.startswith('/api/jobs/'):
                        with app.jobs_lock:
                            job = app.jobs.get(path.rsplit('/', 1)[-1])
                            return self.send(200 if job else 404, dict(job) if job else {'error': 'Unknown job'})
                    if path.startswith('/api/audit/'):
                        case_id = path.rsplit('/', 1)[-1]
                        app.engine.case(case_id)
                        return self.send(200, {'events': app.engine.store.events(case_id),
                                               'hash_chain_valid': app.engine.store.integrity()})
                    if path == '/health':
                        return self.send(200, {'service': 'CollectIQ', 'status': 'serving', 'financial_mode': 'test'})
                    static = {'/': ('index.html', 'text/html; charset=utf-8'),
                              '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                              '/styles.css': ('styles.css', 'text/css; charset=utf-8'),
                              '/favicon.svg': ('favicon.svg', 'image/svg+xml')}
                    if path in static:
                        name, mime = static[path]
                        return self.send(200, (ROOT / 'frontend' / name).read_bytes(), mime)
                    return self.send(404, {'error': 'Not found'})
                except (ValueError, IntegrationError) as error:
                    return self.send(409, {'error': redact(error, (app.engine.settings.stripe_key, app.engine.settings.cognee_key))})

            def do_POST(self):
                port = self.server.server_address[1]
                allowed_origins = (f'http://127.0.0.1:{port}', f'http://localhost:{port}')
                if not self.host_allowed() or self.headers.get('Origin') not in allowed_origins:
                    return self.send(403, {'error': 'Same-origin loopback request required'})
                if not hmac.compare_digest(self.headers.get('X-CollectIQ-Token', ''), app.token):
                    return self.send(403, {'error': 'Session token required'})
                if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                    return self.send(415, {'error': 'Use application/json'})
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                    require(0 < length <= 16_384, 'Invalid request size')
                    data = json.loads(self.rfile.read(length))
                    require(type(data) is dict, 'JSON object required')
                    path = urlsplit(self.path).path
                    if path == '/api/verify':
                        return self.send(202, app.submit(app.engine.verification))
                    if path == '/api/agents/run':
                        name=data.get('scenario')
                        require(name in ('A','B','C','all'),'Choose scenario A, B, C or all')
                        def run_agents():
                            runner=AgentRunner(app.engine)
                            if name=='all':return {'workflows':[runner.run(n) for n in ('A','B','C')]}
                            return runner.run(name)
                        return self.send(202,app.submit(run_agents))
                    if path == '/api/agents/why':
                        workflow_id=data.get('workflow_id')
                        return self.send(202,app.submit(lambda:AgentRunner(app.engine).why(workflow_id)))
                    if path == '/api/cases':
                        with app.engine.lock:
                            case = app.engine.create_case(data.get('request_id'))
                        return self.send(201, case)
                    if path == '/api/memory/search':
                        query, mode = data.get('query'), data.get('mode', 'GRAPH_COMPLETION')
                        case = app.engine.case(data.get('case_id'))
                        client = app.engine.memory_for(case)
                        return self.send(202, app.submit(lambda: client.search(query, mode)))
                    if path == '/api/memory/sync':
                        def sync():
                            result = app.engine.sync_memory()
                            result['indexing'] = [app.engine.memory_for(c).cognify() for c in app.engine.store.cases()]
                            return result
                        return self.send(202, app.submit(sync))
                    parts = path.strip('/').split('/')
                    if len(parts) == 4 and parts[:2] == ['api', 'cases']:
                        case_id, action = parts[2:]
                        return self.send(202, app.submit(lambda: app.engine.execute(case_id, action)))
                    return self.send(404, {'error': 'Not found'})
                except (ValueError, IntegrationError) as error:
                    return self.send(409, {'error': redact(error, (app.engine.settings.stripe_key, app.engine.settings.cognee_key))})

        return Handler


def serve():
    settings = Settings()
    store = Store(ROOT / 'data' / 'collectiq.sqlite3')
    app = Application(CoreWorkflow(settings, store))
    server = ThreadingHTTPServer(('127.0.0.1', settings.port), app.handler())
    print(f'CollectIQ is serving at http://127.0.0.1:{settings.port}', flush=True)
    print('Stripe TEST MODE only. Configure local .env credentials, restart, then verify integrations.', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        app.executor.shutdown(wait=True)
        store.close()


if __name__ == '__main__':
    serve()
