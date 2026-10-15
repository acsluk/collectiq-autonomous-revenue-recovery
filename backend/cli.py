"""python -m backend.cli verify | demo | state | sync"""
import argparse
import json
from pathlib import Path
import sys
from .config import ROOT, Settings
from .engine import Engine
from .core import CoreWorkflow
from .integrations import IntegrationError
from .store import Store


def main():
    parser = argparse.ArgumentParser(description='CollectIQ real integration verification and test settlement')
    parser.add_argument('command', choices=('verify', 'demo', 'core', 'core-prepare', 'core-propose', 'core-replace', 'core-reasoning', 'state', 'sync'))
    parser.add_argument('--request-id', default='hackathon-settlement-001', help='Stable ID: reusing it resumes the same case')
    parser.add_argument('--output', help='Optional sanitized JSON evidence report (never includes API keys)')
    args = parser.parse_args()
    store = Store(ROOT / 'data' / 'collectiq.sqlite3')
    engine = CoreWorkflow(Settings(), store) if args.command.startswith('core') else Engine(Settings(), store)
    code = 0
    try:
        if args.command == 'verify':
            result = engine.verification()
            if not result['ready']:
                code = 2
        elif args.command.startswith('core'):
            engine.require_ready()
            case = engine.create_case('acme-' + args.request_id)
            result = engine.execute(case['id'], 'core-run' if args.command == 'core' else args.command)
        elif args.command == 'demo':
            engine.require_ready()
            case = engine.create_case(args.request_id)
            result = engine.execute(case['id'], 'run')
        elif args.command == 'sync':
            result = engine.sync_memory()
            result['indexing'] = engine.memory.cognify()
        else:
            result = engine.snapshot()
        # ASCII escaping keeps Windows terminals reliable, independent of code page.
        text = json.dumps(result, indent=2, ensure_ascii=True)
        if args.output and args.command.startswith('core'):
            print(json.dumps({'case_id':result['id'],'stage':result['stage'],
                              'original_invoice':result.get('invoice'), 'replacements':result.get('replacements',[]),
                              'report':args.output},indent=2,ensure_ascii=True))
        else:
            print(text)
        if args.output:
            path = Path(args.output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text + '\n', encoding='utf-8')
    except (ValueError, IntegrationError) as error:
        print(json.dumps({'status': 'blocked', 'error': str(error)}, ensure_ascii=True))
        code = 2
    finally:
        store.close()
    return code


if __name__ == '__main__':
    sys.exit(main())
