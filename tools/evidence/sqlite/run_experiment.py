#!/usr/bin/env python3
"""EXPERIMENTAL / NON-PRODUCTION / NOT ANONYMOUS PHYSICAL SCHEMA.

Standard-library, synthetic SQLite capability probe. No dependencies or network.
All database files are created in an owned temporary directory, never in the repo.
Fixture representations, indexes, lifecycle labels and SQL are NOT design choices.
Run with an existing Python: python3 -B run_experiment.py --output NEW_RESULT.json
"""

import argparse
import concurrent.futures
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import platform
import shutil
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import threading
import time

try:
    import resource
except ImportError:  # Windows reruns retain engine checks, not Unix resource counters.
    resource = None

SCHEMA = """
CREATE TABLE fx_conversation(id TEXT PRIMARY KEY, position INTEGER NOT NULL DEFAULT 0,
 version INTEGER NOT NULL DEFAULT 0);
CREATE TABLE fx_message(id TEXT PRIMARY KEY, conversation TEXT NOT NULL REFERENCES fx_conversation(id),
 position INTEGER NOT NULL, instant TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('user','assistant')),
 body TEXT NOT NULL, run TEXT UNIQUE REFERENCES fx_run(id), UNIQUE(conversation,position),
 CHECK((kind='user' AND run IS NULL) OR (kind='assistant' AND run IS NOT NULL)));
CREATE TABLE fx_run(id TEXT PRIMARY KEY, conversation TEXT NOT NULL REFERENCES fx_conversation(id),
 source TEXT NOT NULL REFERENCES fx_message(id), state TEXT NOT NULL,
 model TEXT NOT NULL DEFAULT 'synthetic-model', runtime TEXT NOT NULL DEFAULT 'no-inference');
CREATE UNIQUE INDEX fx_admission ON fx_run(conversation)
 WHERE state IN ('pending','active','finalizing','uncertain');
CREATE TABLE fx_request(id TEXT PRIMARY KEY, conversation TEXT NOT NULL REFERENCES fx_conversation(id),
 body TEXT NOT NULL, source TEXT NOT NULL REFERENCES fx_message(id));
CREATE TABLE fx_provenance(run TEXT NOT NULL REFERENCES fx_run(id),
 source TEXT NOT NULL REFERENCES fx_message(id), PRIMARY KEY(run,source));
CREATE TABLE fx_frontier(id TEXT PRIMARY KEY, conversation TEXT NOT NULL REFERENCES fx_conversation(id),
 position INTEGER NOT NULL);
CREATE TABLE fx_access(id TEXT PRIMARY KEY, epoch INTEGER NOT NULL, denied INTEGER NOT NULL);
CREATE TABLE fx_metadata(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
"""


def require(condition, detail):
    if not condition:
        raise AssertionError(detail)


def instant():
    # Illustrative UTC text only: NOT a proposed production timestamp encoding.
    # Captured just before fixture COMMIT, not an engine-provided exact commit clock.
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def connect(path, timeout=1000):
    c = sqlite3.connect(str(path), isolation_level=None, timeout=timeout / 1000)
    c.execute('PRAGMA foreign_keys=ON')
    c.execute('PRAGMA synchronous=FULL')
    c.execute('PRAGMA wal_autocheckpoint=0')
    require(c.execute('PRAGMA foreign_keys').fetchone()[0] == 1, 'FK enable failed')
    return c


def initialize(path):
    c = connect(path)
    require(c.execute('PRAGMA journal_mode=WAL').fetchone()[0] == 'wal', 'WAL unavailable')
    c.executescript(SCHEMA)
    return c


def counts(c):
    return {t: c.execute('SELECT count(*) FROM ' + t).fetchone()[0] for t in tables(c)}


def tables(c):
    return [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]


def digest(c):
    data = {t: sorted(c.execute('SELECT * FROM ' + t).fetchall(), key=repr) for t in tables(c)}
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def sizes(path):
    return {suffix or 'db': Path(str(path) + suffix).stat().st_size
            if Path(str(path) + suffix).exists() else 0 for suffix in ('', '-wal', '-shm')}


def healthy(c):
    integrity = [r[0] for r in c.execute('PRAGMA integrity_check')]
    fk = c.execute('PRAGMA foreign_key_check').fetchall()
    require(integrity == ['ok'] and not fk, 'integrity check failed')
    return {'integrity_check': integrity, 'foreign_key_check': fk}


def error_info(e):
    return {'type': type(e).__name__, 'message': str(e),
            'sqlite_errorcode': getattr(e, 'sqlite_errorcode', None),
            'sqlite_errorname': getattr(e, 'sqlite_errorname', None)}


def admit(c, conv, req, body='synthetic request', fail=False, expected=None):
    c.execute('BEGIN IMMEDIATE')
    try:
        old = c.execute('SELECT conversation,body,source FROM fx_request WHERE id=?', (req,)).fetchone()
        if old:
            c.execute('ROLLBACK')
            return {'status': 'replay' if old[:2] == (conv, body) else 'conflicting_replay', 'source': old[2]}
        pos, version = c.execute('SELECT position,version FROM fx_conversation WHERE id=?', (conv,)).fetchone()
        if expected is not None and expected != version:
            c.execute('ROLLBACK')
            return {'status': 'stale'}
        if c.execute("SELECT 1 FROM fx_run WHERE conversation=? AND state IN ('pending','active','finalizing','uncertain')", (conv,)).fetchone():
            c.execute('ROLLBACK')
            return {'status': 'admission_closed'}
        source, run = req + ':user', req + ':run'
        c.execute('INSERT INTO fx_message VALUES(?,?,?,?,?,?,NULL)', (source, conv, pos + 1, instant(), 'user', body))
        if fail:
            raise RuntimeError('injected before admission commit')
        c.execute('INSERT INTO fx_request VALUES(?,?,?,?)', (req, conv, body, source))
        c.execute('INSERT INTO fx_run(id,conversation,source,state) VALUES(?,?,?,?)', (run, conv, source, 'pending'))
        c.execute('UPDATE fx_conversation SET position=position+1,version=version+1 WHERE id=?', (conv,))
        c.execute('COMMIT')
        return {'status': 'accepted', 'source': source, 'run': run}
    except BaseException:
        if c.in_transaction:
            c.execute('ROLLBACK')
        raise


def publish(c, run, observer=None, fail=False):
    c.execute('BEGIN IMMEDIATE')
    try:
        conv, source = c.execute('SELECT conversation,source FROM fx_run WHERE id=?', (run,)).fetchone()
        pos = c.execute('SELECT position FROM fx_conversation WHERE id=?', (conv,)).fetchone()[0] + 1
        c.execute("UPDATE fx_run SET state='finalizing' WHERE id=?", (run,))
        c.execute('INSERT INTO fx_message VALUES(?,?,?,?,?,?,?)', (run + ':assistant', conv, pos, instant(), 'assistant', 'synthetic response: exact saved bytes', run))
        if observer:
            require(observer.execute('SELECT count(*) FROM fx_message WHERE run=?', (run,)).fetchone()[0] == 0, 'partial publication exposed')
        if fail:
            raise RuntimeError('injected during response publication')
        c.execute('INSERT INTO fx_provenance VALUES(?,?)', (run, source))
        c.execute("UPDATE fx_run SET state='completed' WHERE id=?", (run,))
        c.execute('UPDATE fx_conversation SET position=position+1,version=version+1 WHERE id=?', (conv,))
        c.execute('COMMIT')
    except BaseException:
        if c.in_transaction:
            c.execute('ROLLBACK')
        raise


def environment():
    c = sqlite3.connect(':memory:')
    out = {'python': platform.python_version(), 'sqlite_library': sqlite3.sqlite_version,
           'sqlite_source_id': c.execute('SELECT sqlite_source_id()').fetchone()[0],
           'compile_options': [r[0] for r in c.execute('PRAGMA compile_options')],
           'python_threadsafety': sqlite3.threadsafety, 'backup_api': hasattr(c, 'backup'),
           'foreign_keys_default': c.execute('PRAGMA foreign_keys').fetchone()[0],
           'os': platform.system(), 'os_release': platform.release(), 'architecture': platform.machine()}
    c.close()
    return out


def latency(values):
    ordered = sorted(values)
    return {'repetitions': len(values), 'unit': 'ms', 'min': min(values),
            'median': statistics.median(values), 'p95_nearest_rank': ordered[math.ceil(.95 * len(values)) - 1],
            'max': max(values), 'samples_ms': values}


def measure(fn, n=200):
    values = []
    for i in range(n):
        start = time.perf_counter_ns()
        fn(i)
        values.append((time.perf_counter_ns() - start) / 1e6)
    return latency(values)


def parallel(functions):
    barrier = threading.Barrier(len(functions))
    def call(fn):
        barrier.wait(timeout=5)
        return fn()
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(functions)) as pool:
        futures = [pool.submit(call, fn) for fn in functions]
        return [f.result(timeout=8) for f in futures]


def timed_admit(path, conv, req):
    c = connect(path)
    start = time.perf_counter_ns()
    try:
        result = admit(c, conv, req)
        result['elapsed_ms'] = (time.perf_counter_ns() - start) / 1e6
        return result
    finally:
        c.close()


def logical_checks(path, c):
    out = {}
    for name in ('atomic', 'rollback', 'uncertain', 'race', 'duplicate', 'stale', 'clock'):
        c.execute('INSERT INTO fx_conversation(id) VALUES(?)', (name,))
    reader = connect(path)
    before = digest(reader)
    try:
        admit(c, 'rollback', 'rolled', fail=True)
        raise AssertionError('injection did not occur')
    except RuntimeError:
        pass
    require(digest(reader) == before, 'rollback changed committed state')
    accepted = admit(c, 'atomic', 'first')
    user_record = reader.execute("SELECT m.position,m.instant,r.state,q.source FROM fx_message m JOIN fx_run r ON r.source=m.id JOIN fx_request q ON q.source=m.id WHERE m.id='first:user'").fetchone()
    require(user_record[0] == 1 and datetime.fromisoformat(user_record[1]).utcoffset() == timedelta(0)
            and user_record[2:] == ('pending', 'first:user'), 'admission incomplete')
    c.execute("UPDATE fx_run SET state='active' WHERE id='first:run'")
    before = digest(reader)
    try:
        publish(c, 'first:run', observer=reader, fail=True)
        raise AssertionError('injection did not occur')
    except RuntimeError:
        pass
    require(digest(reader) == before, 'response rollback changed history')
    publish(c, 'first:run', observer=reader)
    published = reader.execute("SELECT m.kind,r.state,p.source,m.body FROM fx_message m JOIN fx_run r ON m.run=r.id JOIN fx_provenance p ON p.run=r.id WHERE r.id='first:run'").fetchone()
    require(published == ('assistant', 'completed', 'first:user', 'synthetic response: exact saved bytes'), 'publication incomplete')
    assistant_record = reader.execute("SELECT position,instant FROM fx_message WHERE run='first:run'").fetchone()
    require(assistant_record[0] == 2 and datetime.fromisoformat(assistant_record[1]).utcoffset() == timedelta(0), 'assistant order/instant missing')
    out['atomicity'] = {'admission': accepted, 'failed_admission_digest_unchanged': True,
                        'failed_publication_digest_unchanged': True, 'uncommitted_response_hidden': True,
                        'published_tuple': published, 'user_order_instant': user_record[:2],
                        'assistant_order_instant': assistant_record}
    original = digest(reader)
    replays = [admit(c, 'atomic', 'first') for _ in range(2)]
    require(all(r['status'] == 'replay' for r in replays) and digest(reader) == original, 'duplicate effect')
    conflict = admit(c, 'atomic', 'first', body='different synthetic content')
    retry_rollback = admit(c, 'rollback', 'rolled')
    admit(c, 'uncertain', 'unknown')
    c.execute("UPDATE fx_run SET state='uncertain' WHERE id='unknown:run'")
    original = digest(reader)
    uncertain = [admit(c, 'uncertain', 'unknown'), admit(c, 'uncertain', 'different')]
    require([r['status'] for r in uncertain] == ['replay', 'admission_closed'] and digest(reader) == original, 'uncertainty reopened admission')
    require(conflict['status'] == 'conflicting_replay' and retry_rollback['status'] == 'accepted', 'retry status wrong')
    out['idempotency'] = {'exact_duplicate_and_after_success': replays, 'conflicting_payload': conflict,
                          'after_rollback': retry_rollback, 'uncertain_original_then_new_intent': uncertain,
                          'effects_unchanged_on_replay': True, 'production_generation_retry_not_implemented': True}
    out['foreign_keys'] = []
    statements = [
        ("INSERT INTO fx_message VALUES('orphan','atomic',99,'2026-01-01T00:00:00Z','assistant','synthetic','missing')", ()),
        ("INSERT INTO fx_provenance VALUES('first:run','missing')", ()),
        ("INSERT INTO fx_run(id,conversation,source,state) VALUES('bad','missing','first:user','completed')", ()),
        ("UPDATE fx_message SET run='missing' WHERE run='first:run'", ()),
        ("DELETE FROM fx_run WHERE id='first:run'", ()),
        ("DELETE FROM fx_message WHERE id='first:user'", ())]
    for sql, args in statements:
        try:
            c.execute(sql, args)
            raise AssertionError('invalid relation accepted')
        except sqlite3.IntegrityError as e:
            out['foreign_keys'].append(error_info(e))
    out['fixture_constraints'] = []
    for sql in (
        "INSERT INTO fx_message VALUES('no-run','atomic',99,'2026-01-01T00:00:00Z','assistant','synthetic',NULL)",
        "INSERT INTO fx_message VALUES('duplicate-position','atomic',1,'2026-01-01T00:00:00Z','user','synthetic',NULL)",
        "INSERT INTO fx_message VALUES('duplicate-response','atomic',99,'2026-01-01T00:00:00Z','assistant','synthetic','first:run')"
    ):
        try:
            c.execute(sql)
            raise AssertionError('fixture constraint not enforced')
        except sqlite3.IntegrityError as e:
            out['fixture_constraints'].append(error_info(e))
    a, b = sqlite3.connect(':memory:'), sqlite3.connect(':memory:')
    defaults = [x.execute('PRAGMA foreign_keys').fetchone()[0] for x in (a, b)]
    a.execute('PRAGMA foreign_keys=ON')
    independent = [x.execute('PRAGMA foreign_keys').fetchone()[0] for x in (a, b)]
    b.execute('PRAGMA foreign_keys=ON')
    require(a.execute('PRAGMA foreign_keys').fetchone()[0] == b.execute('PRAGMA foreign_keys').fetchone()[0] == 1, 'FK enable')
    a.close(); b.close()
    out['foreign_key_connections'] = {'fresh_defaults': defaults, 'after_enabling_only_first': independent, 'both_explicitly_enabled': True}
    payload = {'label': 'fixture', 'nested': {'count': 7}, 'unrelated': ['α', 42, True]}
    c.execute('INSERT INTO fx_metadata VALUES(?,?)', ('json', json.dumps(payload)))
    extracted = c.execute("SELECT json_extract(payload,'$.label'),json_extract(payload,'$.nested.count') FROM fx_metadata WHERE json_extract(payload,'$.nested.count')=7").fetchone()
    c.execute("UPDATE fx_metadata SET payload=json_set(payload,'$.nested.count',8) WHERE id='json'")
    changed = json.loads(c.execute("SELECT payload FROM fx_metadata WHERE id='json'").fetchone()[0])
    require(extracted == ('fixture', 7) and changed['nested']['count'] == 8 and changed['unrelated'] == payload['unrelated'], 'JSON lost unrelated metadata')
    try:
        jsonb = c.execute("SELECT typeof(jsonb('{}'))").fetchone()[0]
    except sqlite3.DatabaseError as e:
        jsonb = error_info(e)
    out['json'] = {'scalar_and_nested_filter': extracted, 'after_update': changed,
                   'invalid_json_valid_result': c.execute("SELECT json_valid('{broken')").fetchone()[0], 'optional_jsonb_type': jsonb}
    for i in range(1, 9):
        ts = '2026-01-01T00:00:00+00:00' if i != 3 else '2025-12-31T23:00:00+00:00'
        c.execute('INSERT INTO fx_message VALUES(?,?,?,?,?,?,NULL)', ('clock:' + str(i), 'clock', i, ts, 'user', 'synthetic history'))
        c.execute("UPDATE fx_conversation SET position=?,version=? WHERE id='clock'", (i, i))
        if i == 4:
            c.execute("INSERT INTO fx_frontier VALUES('fixed','clock',4)")
    ordered = [r[0] for r in c.execute("SELECT id FROM fx_message WHERE conversation='clock' ORDER BY position")]
    time_sorted = [r[0] for r in c.execute("SELECT id FROM fx_message WHERE conversation='clock' ORDER BY instant,position")]
    frozen = [r[0] for r in c.execute("SELECT m.id FROM fx_message m JOIN fx_frontier f ON m.conversation=f.conversation WHERE f.id='fixed' AND m.position<=f.position ORDER BY m.position")]
    stored = c.execute("SELECT instant FROM fx_message WHERE id='clock:1'").fetchone()[0]
    before = digest(reader)
    formatted = {str(h): datetime.fromisoformat(stored).astimezone(timezone(timedelta(hours=h))).isoformat() for h in (-7, 0, 9)}
    require(digest(reader) == before and ordered == ['clock:' + str(i) for i in range(1, 9)] and frozen == ordered[:4] and time_sorted != ordered, 'clock/frontier semantics')
    out['timestamps_frontier'] = {'authoritative_order': ordered, 'timestamp_sort_differs': time_sorted,
                                 'equal_first_two_instants': True, 'third_commit_clock_earlier': True,
                                 'stored_instant': stored, 'presentation_only': formatted,
                                 'stored_digest_unchanged_by_formatting': True, 'frozen_prefix_after_append': frozen,
                                 'existing_commit_instants_not_edited': True}
    c.execute("INSERT INTO fx_access VALUES('synthetic-scope',0,0)")
    c.execute('BEGIN IMMEDIATE')
    c.execute("UPDATE fx_access SET epoch=1,denied=1 WHERE id='synthetic-scope'")
    c.execute('COMMIT')
    require(reader.execute('SELECT epoch,denied FROM fx_access').fetchone() == (1, 1), 'revocation fact not durable')
    out['access_fact'] = {'durable_epoch_and_denial': [1, 1], 'authorization_delivery_and_restore_antirollback': 'NOT_TESTED'}
    reader.close()
    return out


def concurrency_checks(path, c):
    out = {}
    old = c.execute("SELECT version FROM fx_conversation WHERE id='atomic'").fetchone()[0]
    c.execute('BEGIN IMMEDIATE')
    c.execute("UPDATE fx_conversation SET version=version+1 WHERE id='atomic'")
    def read():
        q = connect(path)
        start = time.perf_counter_ns()
        try:
            rows = [q.execute("SELECT version FROM fx_conversation WHERE id='atomic'").fetchone()[0] for _ in range(10)]
            return {'values': rows, 'elapsed_ms': (time.perf_counter_ns() - start) / 1e6}
        finally:
            q.close()
    out['four_readers_during_uncommitted_writer'] = parallel([read] * 4)
    require(all(r['values'] == [old] * 10 for r in out['four_readers_during_uncommitted_writer']), 'reader saw uncommitted write')
    c.execute('COMMIT')
    require(read()['values'] == [old + 1] * 10, 'reader missed commit')
    def contention(timeout, release_ms):
        c.execute('BEGIN IMMEDIATE')
        started = threading.Event()
        def worker():
            q = connect(path, timeout)
            start = time.perf_counter_ns()
            started.set()
            try:
                q.execute('BEGIN IMMEDIATE')
                acquired = time.perf_counter_ns()
                q.execute("UPDATE fx_conversation SET version=version+1 WHERE id='stale'")
                q.execute('COMMIT')
                return {'status': 'committed', 'begin_wait_ms': (acquired-start)/1e6, 'elapsed_ms': (time.perf_counter_ns()-start)/1e6}
            except sqlite3.OperationalError as e:
                return {'status': 'busy', 'error': error_info(e), 'elapsed_ms': (time.perf_counter_ns()-start)/1e6}
            finally:
                q.close()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            f = pool.submit(worker)
            require(started.wait(5), 'writer did not start')
            if release_ms is None:
                result = f.result(timeout=5)
                c.execute('COMMIT')
            else:
                time.sleep(release_ms / 1000)
                c.execute('COMMIT')
                result = f.result(timeout=5)
        result.update({'busy_timeout_ms': timeout, 'release_after_ms': release_ms})
        return result
    out['writer_contention'] = [contention(0, None), contention(150, None), contention(1000, 150)]
    require([r['status'] for r in out['writer_contention']] == ['busy', 'busy', 'committed'], 'unexpected contention')
    out['competing_admissions'] = parallel([lambda: timed_admit(path, 'race', 'race-a'), lambda: timed_admit(path, 'race', 'race-b')])
    require(sorted(r['status'] for r in out['competing_admissions']) == ['accepted', 'admission_closed'], 'two active generations')
    require(c.execute("SELECT count(*) FROM fx_message WHERE conversation='race'").fetchone()[0] == 1, 'busy send appended')
    source = c.execute("SELECT source FROM fx_run WHERE conversation='race'").fetchone()[0]
    try:
        c.execute("INSERT INTO fx_run(id,conversation,source,state) VALUES('bypass','race',?,'uncertain')", (source,))
        raise AssertionError('admission constraint bypassed')
    except sqlite3.IntegrityError as e:
        out['direct_second_active_rejected'] = error_info(e)
    out['concurrent_duplicate'] = parallel([lambda: timed_admit(path, 'duplicate', 'same'), lambda: timed_admit(path, 'duplicate', 'same')])
    require(sorted(r['status'] for r in out['concurrent_duplicate']) == ['accepted', 'replay'], 'concurrent duplicate')
    require(c.execute("SELECT count(*) FROM fx_message WHERE conversation='duplicate'").fetchone()[0] == 1, 'duplicate source')
    stale = admit(c, 'stale', 'stale-intent', expected=0)
    require(stale['status'] == 'stale', 'stale view accepted')
    out['stale_logical_version'] = stale
    # A reader pins a snapshot; PASSIVE may return busy=0 despite incomplete checkpoint.
    c.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    pinned = connect(path)
    pinned.execute('BEGIN')
    pinned.execute('SELECT * FROM fx_conversation').fetchall()
    for _ in range(10):
        c.execute("UPDATE fx_conversation SET version=version+1 WHERE id='stale'")
    out['wal_with_pinned_reader'] = {'files': sizes(path), 'passive_checkpoint': list(c.execute('PRAGMA wal_checkpoint(PASSIVE)').fetchone())}
    pinned.execute('COMMIT'); pinned.close()
    out['wal_after_reader_release'] = {'truncate_checkpoint': list(c.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()), 'files': sizes(path)}
    require(out['wal_with_pinned_reader']['files']['-wal'] > 0 and out['wal_after_reader_release']['files']['-wal'] == 0, 'WAL checkpoint')
    return out


def child_mode(root, mode):
    root = Path(root)
    require((root / 'owned-experiment-marker').read_text() == 'synthetic-only', 'unowned child directory')
    c = connect(root / 'process.db')
    if mode == 'uncommitted':
        c.execute('BEGIN IMMEDIATE')
        c.execute("UPDATE fx_access SET epoch=99,denied=1 WHERE id='baseline'")
        c.execute("INSERT INTO fx_conversation(id) VALUES('uncommitted')")
    else:
        c.execute("INSERT INTO fx_conversation(id) VALUES('interrupted')")
        admit(c, 'interrupted', 'interrupted-request')
        c.execute("UPDATE fx_run SET state='active' WHERE id='interrupted-request:run'")
    (root / 'child-ready').write_text(mode)
    # Parent kills ONLY this owned child, after observing readiness. Hard fallback bound.
    time.sleep(15)
    c.close()


def process_checks(root):
    path = root / 'process.db'
    c = initialize(path)
    c.execute("INSERT INTO fx_access VALUES('baseline',0,0)")
    c.execute("INSERT INTO fx_conversation(id) VALUES('preserved-history')")
    admit(c, 'preserved-history', 'preserved-request')
    publish(c, 'preserved-request:run')
    baseline = digest(c)
    c.close()
    out = {}
    (root / 'owned-experiment-marker').write_text('synthetic-only')
    for mode in ('uncommitted', 'active_committed'):
        ready = root / 'child-ready'
        if ready.exists(): ready.unlink()
        p = subprocess.Popen([sys.executable, '-B', str(Path(__file__).resolve()), '--child-root', str(root), '--child-mode', mode], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic() + 8
            while not ready.exists() and p.poll() is None and time.monotonic() < deadline:
                time.sleep(.01)
            require(ready.exists() and p.poll() is None, 'child readiness failed')
            p.kill()
            p.communicate(timeout=5)
        finally:
            if p.poll() is None:
                p.kill(); p.communicate(timeout=5)
        c = connect(path)
        if mode == 'uncommitted':
            require(digest(c) == baseline, 'uncommitted process state leaked')
            out[mode] = {'baseline_digest_preserved': True, 'uncommitted_aggregate_absent': c.execute("SELECT count(*) FROM fx_conversation WHERE id='uncommitted'").fetchone()[0] == 0, 'child_returncode': p.returncode, **healthy(c)}
        else:
            observed = c.execute("SELECT r.state,m.kind,(SELECT count(*) FROM fx_message WHERE run=r.id) FROM fx_run r JOIN fx_message m ON m.id=r.source WHERE r.id='interrupted-request:run'").fetchone()
            require(observed == ('active', 'user', 0), 'incomplete falsely completed')
            out[mode] = {'reopened_state': observed, 'interpretation': 'incomplete/uncertain; runtime outcome unknown', 'child_returncode': p.returncode, **healthy(c)}
        c.close()
    return out


def growth_and_measurements(root):
    path = root / 'growth.db'
    c = initialize(path)
    payload = 'synthetic payload ' + 'x' * 144
    start = time.perf_counter_ns()
    for conv in range(20):
        name = 'growth:' + str(conv)
        c.execute('INSERT INTO fx_conversation(id) VALUES(?)', (name,))
        for batch in range(5):
            c.execute('BEGIN IMMEDIATE')
            for index in range(batch * 50, (batch + 1) * 50):
                key = name + ':' + str(index)
                user, run = key + ':u', key + ':r'
                ts = instant()
                c.execute('INSERT INTO fx_message VALUES(?,?,?,?,?,?,NULL)', (user, name, index*2+1, ts, 'user', payload))
                c.execute('INSERT INTO fx_run(id,conversation,source,state) VALUES(?,?,?,?)', (run, name, user, 'completed'))
                c.execute('INSERT INTO fx_message VALUES(?,?,?,?,?,?,?)', (key+':a', name, index*2+2, ts, 'assistant', payload, run))
                c.execute('INSERT INTO fx_provenance VALUES(?,?)', (run, user))
                c.execute('INSERT INTO fx_request VALUES(?,?,?,?)', (key, name, payload, user))
            c.execute('UPDATE fx_conversation SET position=?,version=? WHERE id=?', ((batch+1)*100, (batch+1)*50, name))
            c.execute('COMMIT')
    insertion_ms = (time.perf_counter_ns()-start)/1e6
    before_checkpoint = sizes(path)
    checkpoint = list(c.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone())
    out = {'counts': counts(c), 'body_utf8_bytes_per_message': len(payload.encode()), 'insertion_ms': insertion_ms,
           'batch_size_messages': 100, 'message_batch_commits': 100,
           'before_checkpoint_bytes': before_checkpoint, 'checkpoint': checkpoint, 'after_checkpoint_bytes': sizes(path)}
    require(out['counts']['fx_message'] == 10000 and out['counts']['fx_run'] == 5000, 'growth size wrong')
    def recent(i):
        rows = c.execute('SELECT id,position,instant,body FROM fx_message WHERE conversation=? ORDER BY position DESC LIMIT 50', ('growth:'+str(i%20),)).fetchall()
        require(len(rows) == 50 and rows[0][1] == 500, 'recent history read')
    def association(i):
        run = 'growth:' + str(i % 20) + ':' + str(i % 250) + ':r'
        rows = c.execute('SELECT r.id,p.source,m.id FROM fx_run r JOIN fx_provenance p ON p.run=r.id JOIN fx_message m ON m.run=r.id WHERE r.id=?', (run,)).fetchall()
        require(len(rows) == 1, 'association lookup')
    out['recent_50_messages'] = measure(recent)
    out['run_provenance_lookup'] = measure(association)
    start = time.perf_counter_ns()
    out['integrity'] = healthy(c)
    out['integrity_ms'] = (time.perf_counter_ns()-start)/1e6
    # Separate small-write fixture so growth sizes/counts remain exactly reproducible.
    m = initialize(root / 'micro.db')
    m.execute("INSERT INTO fx_access VALUES('counter',0,0)")
    m.execute("INSERT INTO fx_conversation(id) VALUES('micro')")
    out['simple_autocommit_update'] = measure(lambda i: m.execute("UPDATE fx_access SET epoch=epoch+1 WHERE id='counter'"))
    admission_times = []
    for i in range(200):
        request = 'micro:' + str(i)
        start = time.perf_counter_ns()
        result = admit(m, 'micro', request)
        admission_times.append((time.perf_counter_ns() - start) / 1e6)
        require(result['status'] == 'accepted', 'micro admission')
        # Separate synthetic settlement is outside the admission timing.
        m.execute("UPDATE fx_run SET state='failed' WHERE id=?", (result['run'],))
    out['small_admission_transaction'] = latency(admission_times)
    out['micro_counts'] = counts(m)
    out['micro_files_bytes'] = sizes(root / 'micro.db')
    m.close()
    # Online backup of committed state while source remains open, with a different
    # connection holding an uncommitted write. WAL permits backup of committed data.
    expected = digest(c)
    writer = connect(path)
    writer.execute('BEGIN IMMEDIATE')
    writer.execute("UPDATE fx_message SET body='uncommitted synthetic change' WHERE id='growth:0:0:u'")
    backup_path = root / 'backup.db'
    dest = sqlite3.connect(str(backup_path))
    backup_start = time.perf_counter_ns()
    backup_deadline = time.monotonic() + 5
    def progress(status, remaining, total):
        require(time.monotonic() < backup_deadline, 'backup exceeded bounded deadline')
    c.backup(dest, pages=128, progress=progress, sleep=.01)
    backup_ms = (time.perf_counter_ns()-backup_start)/1e6
    require(digest(dest) == expected, 'backup included uncommitted change')
    dest.close()
    writer.execute('ROLLBACK'); writer.close()
    restored_path = root / 'restored.db'
    shutil.copyfile(backup_path, restored_path)
    restored = connect(restored_path)
    backup_result = {'online_backup_ms': backup_ms, 'source_open_with_uncommitted_other_writer': True,
                     'committed_source_sha256': expected, 'restored_sha256': digest(restored),
                     'restored_counts': counts(restored), 'integrity': healthy(restored), 'backup_bytes': backup_path.stat().st_size}
    require(backup_result['restored_sha256'] == expected, 'restore digest mismatch')
    restored.close()
    # Corrupt ONLY a copy of the owned closed backup. Never the live fixture.
    corrupt = root / 'corrupt-copy.db'
    shutil.copyfile(backup_path, corrupt)
    with corrupt.open('r+b') as f:
        f.write(b'CORRUPTEDFIXTURE!')  # Exactly 16 header bytes, offsets 0..15.
    broken = sqlite3.connect(str(corrupt))
    try:
        broken.execute('PRAGMA integrity_check').fetchall()
        raise AssertionError('header corruption not detected')
    except sqlite3.DatabaseError as e:
        backup_result['corrupt_copy'] = {'alteration': 'replace header bytes 0..15 with ASCII CORRUPTEDFIXTURE!', 'integrity_check_could_not_execute': error_info(e), 'automatic_repair_attempted': False}
    finally:
        broken.close()
    require(digest(c) == expected, 'source modified by backup experiment')
    c.close()
    return out, backup_result


def run(output):
    require(not output.exists(), 'output exists; choose a new result filename')
    start = time.perf_counter_ns()
    usage0 = resource.getrusage(resource.RUSAGE_SELF) if resource else None
    result = {'label': 'MAC_EXPERIMENT_EVIDENCE' if platform.system() == 'Darwin' else 'HOST_EXPERIMENT_EVIDENCE',
              'status': 'RUNNING', 'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'environment': environment(), 'started_utc': instant(),
              'configuration': {'journal': 'WAL', 'synchronous': 'FULL', 'wal_autocheckpoint': 0,
                                'foreign_keys_per_connection': True, 'busy_timeout_default_ms': 1000,
                                'physical_schema': False, 'real_inference': False}}
    cli = shutil.which('sqlite3')
    result['environment']['cli_version'] = subprocess.check_output([cli, '--version'], text=True, timeout=5).strip() if cli else None
    default_python = shutil.which('python3')
    if default_python:
        result['environment']['path_python_inventory'] = json.loads(subprocess.check_output([default_python, '-B', str(Path(__file__).resolve()), '--inventory'], text=True, timeout=5))
    with tempfile.TemporaryDirectory(prefix='anonymous-sqlite-experiment-') as directory:
        root = Path(directory)
        path = root / 'logical.db'
        c = initialize(path)
        result['observed_connection_pragmas'] = {name: c.execute('PRAGMA ' + name).fetchone()[0] for name in (
            'journal_mode', 'synchronous', 'foreign_keys', 'busy_timeout', 'wal_autocheckpoint',
            'page_size', 'fullfsync', 'checkpoint_fullfsync', 'locking_mode')}
        result['logical'] = logical_checks(path, c)
        result['concurrency'] = concurrency_checks(path, c)
        result['logical_integrity'] = healthy(c)
        logical_digest = digest(c)
        c.close()
        result['logical_after_last_connection_close'] = sizes(path)
        result['logical_sidecars_removed'] = all(not Path(str(path) + suffix).exists() for suffix in ('-wal', '-shm'))
        reopened = connect(path)
        require(digest(reopened) == logical_digest, 'logical facts changed on orderly reopen')
        result['logical_digest_preserved_after_reopen'] = True
        reopened.close()
        result['process_interruption'] = process_checks(root)
        result['growth'], result['backup_restore'] = growth_and_measurements(root)
        result['owned_files_bytes_before_cleanup'] = sum(p.stat().st_size for p in root.iterdir() if p.is_file())
    result['temporary_directory_removed'] = not root.exists()
    require(result['temporary_directory_removed'], 'temporary database cleanup failed')
    usage1 = resource.getrusage(resource.RUSAGE_SELF) if resource else None
    result['resources'] = {'wall_ms': (time.perf_counter_ns()-start)/1e6,
                           'current_rss_and_system_memory_pressure': 'NOT_MEASURED', 'device_disk_throughput': 'NOT_MEASURED',
                           'other_server_or_model_load': 'NOT_TESTED'}
    if usage0:
        result['resources'].update({'parent_user_cpu_s': usage1.ru_utime-usage0.ru_utime,
                                    'parent_system_cpu_s': usage1.ru_stime-usage0.ru_stime,
                                    'parent_maxrss_before': usage0.ru_maxrss, 'parent_maxrss_after': usage1.ru_maxrss,
                                    'maxrss_unit': 'bytes' if platform.system() == 'Darwin' else 'KiB (verify on host)',
                                    'parent_block_input_delta': usage1.ru_inblock-usage0.ru_inblock,
                                    'parent_block_output_delta': usage1.ru_oublock-usage0.ru_oublock,
                                    'block_counter_units': 'OS-accounted operations, not bytes; zero is not evidence of zero disk I/O'})
    result['status'] = 'PASS'
    result['completed_utc'] = instant()
    with output.open('x') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
        f.write('\n')
    print(json.dumps({'status': result['status'], 'wall_ms': result['resources']['wall_ms'], 'temporary_directory_removed': result['temporary_directory_removed']}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--inventory', action='store_true')
    parser.add_argument('--child-root', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--child-mode', choices=('uncommitted', 'active_committed'), help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.inventory:
        print(json.dumps(environment()))
    elif args.child_root and args.child_mode:
        child_mode(args.child_root, args.child_mode)
    elif args.output:
        run(args.output)
    else:
        parser.error('--output NEW_RESULT.json required')


if __name__ == '__main__':
    main()
