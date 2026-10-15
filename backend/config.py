import os
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent


def load_env(path=None):
    """Small literal .env reader: no evaluation, expansion, or secret logging."""
    source = Path(path or ROOT / '.env')
    if source.exists():
        for line in source.read_text(encoding='utf-8-sig').splitlines():
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, value = line.removeprefix('export ').split('=', 1)
            key, value = key.strip(), value.strip()
            if key.replace('_', '').isalnum():
                if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                    value = value[1:-1]
                os.environ.setdefault(key, value)


class Settings:
    def __init__(self):
        load_env()
        self.stripe_key = os.getenv('STRIPE_SECRET_KEY', '')
        self.cognee_key = os.getenv('COGNEE_API_KEY', '')
        self.cognee_tenant = os.getenv('COGNEE_TENANT_ID', '')
        self.cognee_url = os.getenv('COGNEE_BASE_URL', 'https://api.cognee.ai').rstrip('/')
        url = urlsplit(self.cognee_url)
        if url.scheme != 'https' or not url.hostname or url.username or url.query or url.fragment:
            raise ValueError('COGNEE_BASE_URL must be an HTTPS URL without credentials, query or fragment')
        self.dataset = os.getenv('COGNEE_DATASET', 'collectiq_hackathon')
        self.stripe_version = os.getenv('STRIPE_API_VERSION', '2025-06-30.basil')
        self.port = int(os.getenv('PORT', '8080'))


def configured(value):
    return bool(value) and not any(marker in value.lower() for marker in ('replace_me', 'your-api-key', 'your_api_key'))
