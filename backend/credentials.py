"""Hidden-input credential setup: python -m backend.credentials cognee|stripe."""
import argparse
import getpass
import os
from .config import ROOT


def main():
    parser = argparse.ArgumentParser(description='Save a credential to the ignored local .env file using hidden input')
    parser.add_argument('service', choices=('cognee', 'stripe'))
    args = parser.parse_args()
    name = 'COGNEE_API_KEY' if args.service == 'cognee' else 'STRIPE_SECRET_KEY'
    value = getpass.getpass(f'{name} (hidden): ').strip()
    if not value or any(c in value for c in ('\n', '\r', '"', "'", ' ')):
        raise ValueError('Credential must be a single non-empty token')
    if args.service == 'stripe' and not value.startswith(('sk_test_', 'rk_test_')):
        raise ValueError('Only a Stripe test-mode key is accepted')
    path = ROOT / '.env'
    lines = path.read_text(encoding='utf-8').splitlines() if path.exists() else []
    lines = [line for line in lines if not line.strip().startswith(name + '=')]
    lines.append(name + '=' + value)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        stream.write('\n'.join(lines) + '\n')
    print(f'{name} saved to ignored local .env; credential not displayed. Restart a running server to load it.')


if __name__ == '__main__':
    main()
