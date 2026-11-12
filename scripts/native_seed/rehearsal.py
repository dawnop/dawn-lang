"""Temporary transaction rehearsal. These locks are never accepted as product seeds."""

import copy
import fcntl
import os
from pathlib import Path
import re
import tempfile

from native_seed import contract as c

KIND = 'native-seed-transaction-rehearsal'


def version(tag):
    c.require(type(tag) is str and re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+', tag),
              'transaction-version', 'explicit simulated release version required')
    return tuple(map(int, tag[1:].split('.')))


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def blob(directory, data):
    key = c.digest(data)
    path = directory / 'objects' / key
    if path.exists():
        c.require(c.regular_bytes(path) == data, 'transaction-object', 'immutable object changed')
    else:
        path.parent.mkdir(exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix='pending-', delete=False) as output:
                temporary = Path(output.name)
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            os.link(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        sync_directory(path.parent)
    return key


def object_bytes(directory, key):
    c.sha(key, 'transaction object')
    data = c.regular_bytes(directory / 'objects' / key)
    c.require(c.digest(data) == key, 'transaction-object', 'immutable object digest differs')
    return data


def read(directory):
    directory = Path(directory)
    state = c.read_json(directory / 'lock.json')
    c.fields(state, 'schema kind sequence high_water active revoked events', 'rehearsal lock')
    c.require(type(state['schema']) is int and state['schema'] == 1 and state['kind'] == KIND,
              'transaction-kind', 'only a rehearsal lock is accepted')
    c.require(type(state['sequence']) is int and state['sequence'] >= 0 and
              type(state['events']) is list and len(state['events']) == state['sequence'] + 1,
              'transaction-lineage', 'sequence or event coverage differs')
    version(state['high_water'])
    c.require(type(state['revoked']) is list and state['revoked'] == sorted(set(state['revoked'])),
              'transaction-lineage', 'invalid revocation set')
    for key in state['revoked']:
        c.sha(key, 'revoked identity')
    active = state['active']
    c.fields(active, 'simulated_tag artifact_sha256 evidence_sha256', 'active identity')
    c.require(version(active['simulated_tag']) <= version(state['high_water']),
              'transaction-version', 'active version exceeds high water')
    object_bytes(directory, active['artifact_sha256'])
    object_bytes(directory, active['evidence_sha256'])
    c.require(active['artifact_sha256'] not in state['revoked'],
              'transaction-revoked', 'active seed identity is revoked')
    for index, event in enumerate(state['events']):
        c.fields(event, 'sequence operation parent_lock_sha256 from to reason evidence_sha256 simulated_tag subject_sha256', 'event')
        c.require(event['sequence'] == index and event['operation'] in
                  ('initialize', 'advance', 'rollback', 'revoke') and
                  type(event['reason']) is str and bool(event['reason'].strip()),
                  'transaction-lineage', 'invalid event')
        object_bytes(directory, event['evidence_sha256'])
        object_bytes(directory, event['subject_sha256'])
        version(event['simulated_tag'])
        if index == 0:
            c.require(event['operation'] == 'initialize' and event['parent_lock_sha256'] is None and
                      event['from'] is None, 'transaction-lineage', 'invalid initial event')
            expected_active = {'simulated_tag': event['simulated_tag'],
                               'artifact_sha256': event['subject_sha256'],
                               'evidence_sha256': event['evidence_sha256']}
            expected_revoked, expected_water = [], event['simulated_tag']
        else:
            parent = c.read_json(directory / 'objects' / event['parent_lock_sha256'])
            c.require(c.digest(c.canonical(parent)) == event['parent_lock_sha256'] and
                      parent['sequence'] == index - 1 and parent['events'] == state['events'][:index] and
                      parent['active']['artifact_sha256'] == event['from'],
                      'transaction-lineage', 'parent lock or receipt edge differs')
            c.require(parent['active'] == expected_active and parent['revoked'] == expected_revoked and
                      parent['high_water'] == expected_water, 'transaction-lineage', 'historical state differs')
            key = event['subject_sha256']
            c.require(key not in expected_revoked, 'transaction-revoked', 'revoked identity in lineage')
            if event['operation'] == 'advance':
                c.require(version(event['simulated_tag']) > version(expected_water),
                          'transaction-version', 'historical advancement is not monotonic')
                expected_water = event['simulated_tag']
            elif event['operation'] == 'rollback':
                proof = c.read_json(directory / 'objects' / event['evidence_sha256'])
                c.require(any(e['subject_sha256'] == key and e['simulated_tag'] == event['simulated_tag']
                              and e['operation'] != 'revoke' for e in state['events'][:index]) and
                          version(event['simulated_tag']) < version(expected_active['simulated_tag']) and
                          proof.get('compatible_artifact_sha256') == key,
                          'transaction-compatibility', 'rollback lineage lacks its compatible retained identity')
                c.oid(proof.get('source_commit'), 'rollback source')
            elif event['operation'] == 'revoke':
                c.require(key != expected_active['artifact_sha256'],
                          'transaction-revocation', 'active identity was revoked')
                expected_revoked = sorted([*expected_revoked, key])
            else:
                raise c.Rejected('transaction-lineage: initialization repeated')
            if event['operation'] != 'revoke':
                expected_active = {'simulated_tag': event['simulated_tag'], 'artifact_sha256': key,
                                   'evidence_sha256': event['evidence_sha256']}
        c.require(event['to'] == expected_active['artifact_sha256'],
                  'transaction-lineage', 'event destination differs')
    c.require(state['events'][-1]['to'] == active['artifact_sha256'],
              'transaction-lineage', 'active identity differs from last event')
    c.require(active == expected_active and state['revoked'] == expected_revoked and
              state['high_water'] == expected_water, 'transaction-lineage', 'state does not replay from its lineage')
    return state


def initialize(directory, data, evidence, simulated_tag):
    directory = c.safe_destination(directory)
    c.require(not directory.exists(), 'destination', 'new rehearsal directory required')
    version(simulated_tag)
    directory.mkdir(parents=True)
    artifact = blob(directory, data)
    proof = blob(directory, c.canonical(evidence))
    state = {'schema': 1, 'kind': KIND, 'sequence': 0, 'high_water': simulated_tag,
             'active': {'simulated_tag': simulated_tag, 'artifact_sha256': artifact,
                        'evidence_sha256': proof}, 'revoked': [],
             'events': [{'sequence': 0, 'operation': 'initialize', 'parent_lock_sha256': None,
                         'from': None, 'to': artifact, 'reason': 'isolated rehearsal initialization',
                         'evidence_sha256': proof, 'simulated_tag': simulated_tag, 'subject_sha256': artifact}]}
    c.atomic_json(directory / 'lock.json', state)
    return read(directory)


def transition(directory, parent_sha, operation, data, evidence, simulated_tag, reason, checkpoint=None):
    """Serialize writers; persist objects before the single atomic lock commit point."""
    directory = c.safe_destination(directory)
    with (directory / 'writer.lock').open('a+b') as writer:
        fcntl.flock(writer, fcntl.LOCK_EX)
        old = read(directory)
        c.require(c.digest(c.canonical(old)) == parent_sha,
                  'transaction-parent', 'stale parent; reread and explicitly retry')
        c.require(operation in ('advance', 'rollback', 'revoke') and type(reason) is str and reason.strip(),
                  'transaction-reason', 'explicit operation and nonempty review reason required')
        version(simulated_tag)
        key = c.digest(data)
        c.require(key not in old['revoked'], 'transaction-revoked', 'seed identity is revoked')
        state = copy.deepcopy(old)
        proof = blob(directory, c.canonical(evidence))
        blob(directory, data)
        if checkpoint:
            checkpoint('after-objects')
        if operation == 'advance':
            c.require(version(simulated_tag) > version(old['high_water']),
                      'transaction-version', 'normal advancement must exceed the high water version')
            state['high_water'] = simulated_tag
        elif operation == 'rollback':
            c.require(any(e['subject_sha256'] == key and e['simulated_tag'] == simulated_tag and
                          e['operation'] != 'revoke' for e in old['events']) and
                      version(simulated_tag) < version(old['active']['simulated_tag']),
                      'transaction-rollback', 'rollback requires an earlier retained identity')
            c.require(evidence.get('compatible_artifact_sha256') == key and
                      type(evidence.get('source_commit')) is str,
                      'transaction-compatibility', 'current source compatibility evidence required')
            c.oid(evidence['source_commit'], 'rollback source')
        else:
            c.require(key != old['active']['artifact_sha256'] and
                      any(e['to'] == key for e in old['events']),
                      'transaction-revocation', 'rollback before revoking an active retained identity')
            state['revoked'] = sorted([*old['revoked'], key])
        if operation != 'revoke':
            state['active'] = {'simulated_tag': simulated_tag, 'artifact_sha256': key,
                               'evidence_sha256': proof}
        state['sequence'] += 1
        blob(directory, c.canonical(old))
        state['events'].append({'sequence': state['sequence'], 'operation': operation,
                                'parent_lock_sha256': parent_sha,
                                'from': old['active']['artifact_sha256'],
                                'to': state['active']['artifact_sha256'], 'reason': reason,
                                'evidence_sha256': proof, 'simulated_tag': simulated_tag, 'subject_sha256': key})
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=directory, prefix='pending-', delete=False) as output:
                temporary = Path(output.name)
                output.write(c.canonical(state))
                output.flush()
                os.fsync(output.fileno())
            if checkpoint:
                checkpoint('before-commit')
            os.replace(temporary, directory / 'lock.json')
            sync_directory(directory)
            if checkpoint:
                checkpoint('after-commit')
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return read(directory)


def select(directory, artifact_sha):
    state = read(directory)
    c.require(artifact_sha not in state['revoked'], 'transaction-revoked', 'seed identity is revoked')
    c.require(artifact_sha == state['active']['artifact_sha256'],
              'transaction-active', 'only the explicit active identity may be selected')
    return object_bytes(Path(directory), artifact_sha)
