"""Read real tenant API schema without exposing authentication headers."""
import json
from .config import ROOT, Settings
from .integrations import Cognee


def main():
    client = Cognee(Settings())
    schema, receipt = client.request('GET', '/openapi.json')
    path = ROOT / 'artifacts' / 'cognee-openapi.json'
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(schema, indent=2), encoding='utf-8')
    wanted = {}
    for endpoint, methods in schema.get('paths', {}).items():
        if any(word in endpoint.lower() for word in ('search', 'cognify', 'add', 'dataset', 'reason', 'memory')):
            wanted[endpoint] = {method: {'summary': info.get('summary'), 'requestBody': info.get('requestBody'),
                                         'parameters': info.get('parameters')} for method, info in methods.items() if isinstance(info, dict)}
    names = ('SearchType', 'SearchPayloadDTO', 'CognifyPayloadDTO')
    models = {name: model for name, model in schema.get('components', {}).get('schemas', {}).items()
              if name in names or 'add' in name.lower() or 'search' in name.lower()}
    print(json.dumps({'receipt':receipt,'endpoints':wanted,'models':models},indent=2))


if __name__ == '__main__':
    main()
