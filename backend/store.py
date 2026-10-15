"""Operational journal and Cognee outbox; NOT a replacement for AI retrieval."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import sqlite3
import threading
from pathlib import Path
from .policy import canonical, digest


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS cases(id TEXT PRIMARY KEY, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS operations(key TEXT PRIMARY KEY, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id TEXT NOT NULL, kind TEXT NOT NULL, created TEXT NOT NULL,
                body TEXT NOT NULL, previous_hash TEXT NOT NULL, hash TEXT NOT NULL,
                memory_status TEXT NOT NULL DEFAULT 'pending', memory_receipt TEXT);
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS workflows(id TEXT PRIMARY KEY, body TEXT NOT NULL);
        ''')

    def close(self):
        self.db.close()

    def put(self, table, key, value):
        if table not in ('cases', 'operations', 'settings', 'workflows'):
            raise ValueError('Unknown journal table')
        col = 'id' if table in ('cases', 'workflows') else 'key'
        with self.lock, self.db:
            self.db.execute(f'INSERT INTO {table}({col},body) VALUES (?,?) ON CONFLICT({col}) DO UPDATE SET body=excluded.body',
                            (key, canonical(value)))

    def get(self, table, key, default=None):
        if table not in ('cases', 'operations', 'settings', 'workflows'):
            raise ValueError('Unknown journal table')
        col = 'id' if table in ('cases', 'workflows') else 'key'
        with self.lock:
            row = self.db.execute(f'SELECT body FROM {table} WHERE {col}=?', (key,)).fetchone()
        return json.loads(row['body']) if row else default

    def cases(self):
        with self.lock:
            return [json.loads(r['body']) for r in self.db.execute('SELECT body FROM cases ORDER BY rowid DESC')]

    def workflows(self):
        with self.lock:
            return [json.loads(r['body']) for r in self.db.execute('SELECT body FROM workflows ORDER BY rowid DESC')]

    def event(self, case_id, kind, body):
        with self.lock, self.db:
            prev = self.db.execute('SELECT hash FROM events ORDER BY seq DESC LIMIT 1').fetchone()
            event = {'case_id': case_id, 'kind': kind, 'created': now(), 'body': body,
                     'previous_hash': prev['hash'] if prev else '0' * 64}
            event['hash'] = digest(event)
            cur = self.db.execute('INSERT INTO events(case_id,kind,created,body,previous_hash,hash) VALUES (?,?,?,?,?,?)',
                                  (case_id, kind, event['created'], canonical(body), event['previous_hash'], event['hash']))
            return cur.lastrowid

    def events(self, case_id=None, pending=False):
        query, args = 'SELECT * FROM events', []
        if case_id is not None:
            query += ' WHERE case_id=?'
            args.append(case_id)
        if pending:
            query += (' AND ' if args else ' WHERE ') + "memory_status='pending'"
        with self.lock:
            rows = self.db.execute(query + ' ORDER BY seq', args).fetchall()
            return [{**dict(r), 'body': json.loads(r['body']),
                     'memory_receipt': json.loads(r['memory_receipt']) if r['memory_receipt'] else None} for r in rows]

    def ack(self, seq, receipt):
        with self.lock, self.db:
            self.db.execute("UPDATE events SET memory_status='stored',memory_receipt=? WHERE seq=?", (canonical(receipt), seq))

    def integrity(self):
        previous = '0' * 64
        for e in self.events():
            content = {k: e[k] for k in ('case_id', 'kind', 'created', 'body', 'previous_hash')}
            if e['previous_hash'] != previous or digest(content) != e['hash']:
                return False
            previous = e['hash']
        return True
