"""Qualification evidence assembly, separate from product seed promotion and release metadata."""

from pathlib import Path
import shutil
import subprocess

from native_seed import cold, contract as c, qualification as q, rehearsal

REPLAY_SENTENCES = (b'OK: fixed point', b'OK: standalone closure',
                    b'OK: converges to the current compiler byte-for-byte', b'replay complete:')


def jvm_chain(repo, destination, java21, java26, seed_cache, commit):
    """Use the unchanged JVM builders in fresh checkouts of the exact qualification commit."""
    destination = cold.new_directory(destination)
    seed_tag = (Path(repo) / 'scripts/seed-release.txt').read_text().strip()
    cache = cold.new_directory(destination / 'seed-cache')
    (cache / seed_tag).mkdir()
    shutil.copyfile(Path(seed_cache) / seed_tag / 'seed.jar', cache / seed_tag / 'seed.jar')
    coursier = destination / 'coursier'
    shutil.copytree(Path(seed_cache).parent / 'coursier', coursier)
    commands = []
    for label, java in (('21', java21), ('26', java26)):
        work = destination / ('source-' + label)
        clone = subprocess.run(['git', 'clone', '--shared', '--no-checkout', str(repo), str(work)],
                               capture_output=True)
        c.require(clone.returncode == 0, 'jvm-source', 'fresh checkout clone failed')
        checkout = subprocess.run(['git', '-C', str(work), 'checkout', '--detach', commit], capture_output=True)
        c.require(checkout.returncode == 0 and c.git(work, 'rev-parse', 'HEAD').decode().strip() == commit,
                  'jvm-source', 'qualification source checkout differs')
        home, tmp = cold.new_directory(destination / ('home-' + label)), cold.new_directory(destination / ('tmp-' + label))
        env = {'PATH': str(Path(java).parent) + ':/usr/bin:/bin', 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8',
               'TZ': 'UTC', 'JAVA_HOME': str(Path(java).parent.parent), 'HOME': str(home), 'TMPDIR': str(tmp),
               'DAWN_SEED_CACHE': str(cache), 'COURSIER_CACHE': str(coursier)}
        probe = q.command(destination, 'java-' + label, [java, '-version'], work, env)
        c.require(probe['exit_code'] == 0 and ('version "' + label + '.').encode() in
                  (destination / ('java-' + label + '.stderr')).read_bytes(), 'jvm-version', 'wrong JDK arm')
        jar = destination / ('jdk-' + label + '.jar')
        build = q.command(destination, 'build-' + label,
                          [work / 'scripts/build-release-jar.sh', '-o', jar], work, env)
        c.require(build['exit_code'] == 0 and b'B == C' in
                  (destination / ('build-' + label + '.stdout')).read_bytes(), 'jvm-build', 'JVM fixed point failed')
        commands.append({'jdk': label, 'java': str(java), 'java_sha256': c.digest(Path(java).read_bytes()),
                         'probe': probe, 'build': build, 'jar_sha256': c.digest(jar.read_bytes())})
        if label == '21':
            # The historical script still owns embedded seed std, standalone closure and HEAD convergence.
            # A tag argument requires the existing downloader's checksum check, without an escape hatch.
            seed_tag = (work / 'scripts/seed-release.txt').read_text().strip()
            replay = q.command(destination, 'replay', [work / 'scripts/replay-bootstrap.sh', seed_tag], work, env)
            transcript = (destination / 'replay.stdout').read_bytes()
            c.require(replay['exit_code'] == 0 and all(s in transcript for s in REPLAY_SENTENCES),
                      'jvm-replay', 'historical replay or its owned assertions failed')
    c.require(commands[0]['jar_sha256'] == commands[1]['jar_sha256'],
              'jvm-jdk-diff', 'JDK 21 and 26 release JARs differ')
    result = {'schema': 1, 'kind': 'jvm-qualification-reference', 'source_commit': commit,
              'arms': commands, 'replay': replay,
              'scripts': {p: c.digest((Path(repo) / p).read_bytes()) for p in
                          ('scripts/build-release-jar.sh', 'scripts/replay-bootstrap.sh',
                           'scripts/bootstrap-guards/replay-contract.sh', '.github/workflows/release.yml')}}
    c.atomic_json(destination / 'summary.json', result)
    return result


def check_transcript(directory, name, row):
    c.require(type(row['exit_code']) is int, 'package-transcript', 'invalid exit status')
    for stream in ('stdout', 'stderr'):
        c.require(c.digest(c.regular_bytes(directory / (name + '.' + stream))) == row[stream + '_sha256'],
                  'package-transcript', 'transcript identity differs: ' + name)
    c.require(c.read_json(directory / (name + '.json')) == row,
              'package-transcript', 'command record differs: ' + name)


def inspect(repo, directory):
    """Recompute identities, coverage, lineage and differential observations from saved evidence."""
    directory = Path(directory).absolute()
    chain = cold.verify(repo, directory / 'cold')
    implementation_paths = ('scripts/native-seed-k4-test.py', 'scripts/native_seed/qualification.py',
                            'scripts/native_seed/rehearsal.py', 'scripts/native_seed/package.py')
    captured = {row['path']: row['sha256'] for row in c.read_json(directory / 'cold/inputs.json')['source']['inventory']}
    implementations = {path: c.digest(c.regular_bytes(Path(repo) / path)) for path in implementation_paths}
    c.require(all(captured.get(path) == sha for path, sha in implementations.items()),
              'package-input', 'qualification implementation differs from the captured commit')
    controls = c.read_json(directory / 'real/results.json')
    c.fields(controls, 'schema kind cold_receipt_sha256 controls', 'real controls')
    c.require(controls['schema'] == 1 and controls['kind'] == 'native-real-controls' and
              controls['cold_receipt_sha256'] == c.digest(c.canonical(chain)),
              'package-input', 'real controls refer to another cold chain')
    coverage = {row['q'] for row in controls['controls']}
    c.require(coverage == {'Q1', 'Q2', 'Q3', 'Q4', 'Q6', 'Q7', 'Q8', 'Q9'} and
              {row['name'] for row in controls['controls']} == set(q.REAL_EXPECTED) and
              len({row['name'] for row in controls['controls']}) == len(controls['controls']),
              'package-coverage', 'real control coverage is incomplete or duplicated')
    for row in controls['controls']:
        c.require((row['q'], row.get('expected')) == q.REAL_EXPECTED[row['name']],
                  'package-verdict', 'control ID or owned rejection rule differs')
        if 'expected' in row:
            c.require(row['actual'].startswith(row['expected'] + ':'),
                      'package-verdict', 'wrong negative verdict')
    fixtures = c.read_json(directory / 'fixtures/results.json')
    c.require(fixtures['kind'] == 'native-verifier-fixtures' and
              any(row['name'] == 'removed-rule-is-detected' and row['actual'].startswith('control-missed:')
                  for row in fixtures['controls']) and
              any(row['name'] == 'removed-java-rule-is-detected' and row['actual'].startswith('control-missed:')
                  for row in fixtures['controls']), 'package-coverage', 'Q5 observer sensitivity is missing')
    for row in fixtures['controls']:
        c.require(row['actual'].startswith(row['expected'] + ':'), 'package-verdict', 'wrong fixture verdict')
    transactions = c.read_json(directory / 'transactions/results.json')
    c.require(transactions['kind'] == 'native-transaction-controls' and transactions['simulated_versions'] is True and
              transactions['source_commit'] == chain['source_commit'], 'package-input', 'transaction source differs')
    lineages = {}
    for phase in ('after-objects', 'before-commit', 'after-commit'):
        for fault in ('exception', 'SIGTERM', 'SIGKILL'):
            name = phase + '-' + fault
            store = directory / 'transactions' / name
            state = rehearsal.read(store)
            record = next((row for row in transactions['controls'] if row['name'] == name), None)
            c.require(record and c.digest(c.canonical(state)) == record['lineage_sha256'] and
                      state['sequence'] == 3 and state['revoked'] == [record['revoked_sha256']] and
                      state['active']['artifact_sha256'] == record['active_sha256'],
                      'package-lineage', 'transaction recovery/rollback/revocation record differs')
            evidence = c.read_json(store / 'objects' / state['events'][0]['evidence_sha256'])
            c.require(evidence['cold_receipt_sha256'] == c.digest(c.canonical(chain)) and
                      record['active_sha256'] == c.read_lock(directory / 'cold/seed-lock.json')['seed']['sha256'] and
                      record['revoked_sha256'] == chain['roots']['root-1']['stages']['B']['elf_sha256'],
                      'package-lineage', 'transaction artifacts differ from the real chain')
            lineages[name] = record['lineage_sha256']
    jvm = c.read_json(directory / 'jvm/summary.json')
    c.require(jvm['kind'] == 'jvm-qualification-reference' and jvm['source_commit'] == chain['source_commit'] and
              [row['jdk'] for row in jvm['arms']] == ['21', '26'], 'package-input', 'JVM source or JDK coverage differs')
    c.require(set(jvm['scripts']) == {'scripts/build-release-jar.sh', 'scripts/replay-bootstrap.sh',
                                     'scripts/bootstrap-guards/replay-contract.sh', '.github/workflows/release.yml'},
              'package-input', 'JVM responsibility identities are missing')
    for path, sha in jvm['scripts'].items():
        c.require(c.digest(c.regular_bytes(Path(repo) / c.logical(path))) == sha,
                  'package-input', 'JVM replay or dual JDK responsibility changed')
    for arm in jvm['arms']:
        c.require(c.git(directory / ('jvm/source-' + arm['jdk']), 'rev-parse', 'HEAD').decode().strip() ==
                  chain['source_commit'], 'package-input', 'actual JVM checkout differs')
        for prefix in ('java', 'build'):
            check_transcript(directory / 'jvm', prefix + '-' + arm['jdk'], arm['probe' if prefix == 'java' else 'build'])
        c.require(arm['build']['exit_code'] == 0 and
                  b'B == C' in (directory / ('jvm/build-' + arm['jdk'] + '.stdout')).read_bytes() and
                  ('version "' + arm['jdk'] + '.').encode() in
                  (directory / ('jvm/java-' + arm['jdk'] + '.stderr')).read_bytes() and
                  c.digest(c.regular_bytes(directory / ('jvm/jdk-' + arm['jdk'] + '.jar'))) == arm['jar_sha256'],
                  'package-jvm', 'JVM build output differs')
    c.require(jvm['arms'][0]['jar_sha256'] == jvm['arms'][1]['jar_sha256'],
              'package-jvm', 'JDK outputs differ')
    check_transcript(directory / 'jvm', 'replay', jvm['replay'])
    c.require(jvm['replay']['exit_code'] == 0 and all(s in (directory / 'jvm/replay.stdout').read_bytes()
                                                  for s in REPLAY_SENTENCES), 'package-jvm', 'replay assertions missing')
    dual = c.read_json(directory / 'dual/summary.json')
    c.require(dual['kind'] == 'native-jvm-qualification-diff' and
              dual['cold_receipt_sha256'] == c.digest(c.canonical(chain)) and
              dual['jar_sha256'] == jvm['arms'][0]['jar_sha256'] and
              dual['native_sha256'] == chain['roots']['root-1']['stages']['B']['elf_sha256'],
              'package-input', 'dual comparison uses a different compiler')
    emit = directory / 'dual/jvm-emission'
    for name, key in (('whole.c', 'whole_sha256'), ('info.c', 'info_sha256')):
        c.require(c.digest(c.regular_bytes(emit / name)) == chain['roots']['root-1']['stages']['B'][key],
                  'package-diff', 'JVM emission differs')
    c.require(c.inventory(c.scan(emit / 'units')) == chain['roots']['root-1']['stages']['B']['units'],
              'package-diff', 'JVM split units differ')
    c.require([row['name'] for row in dual['cases']] == ['standalone', 'stdlib', 'package', 'diagnostic', 'format'],
              'package-coverage', 'functional cases missing or reordered')
    for case in dual['cases']:
        name = case['name']
        for backend in ('jvm', 'native'):
            check_transcript(directory / 'dual', name + '-' + backend, case[backend])
        c.require(case['jvm']['exit_code'] == case['native']['exit_code'] and
                  case['jvm']['stdout_sha256'] == case['native']['stdout_sha256'] and
                  case['jvm']['stderr_sha256'] == case['native']['stderr_sha256'],
                  'package-diff', 'functional transcript differs')
    return {'schema': 1, 'kind': 'native-qualification-package', 'source_commit': chain['source_commit'],
            'source_tree': chain['source_tree'], 'cold_receipt_sha256': c.digest(c.canonical(chain)),
            'seed_lock_sha256': chain['seed_lock_sha256'], 'coverage': ['Q' + str(i) for i in range(1, 11)],
            'implementations': implementations,
            'components': {name: c.digest(c.regular_bytes(directory / path)) for name, path in
                           (('real', 'real/results.json'), ('fixtures', 'fixtures/results.json'),
                            ('transactions', 'transactions/results.json'), ('jvm', 'jvm/summary.json'),
                            ('dual', 'dual/summary.json'))}, 'lineage': lineages}


def seal(repo, directory):
    value = inspect(repo, directory)
    c.atomic_json(Path(directory) / 'receipt.json', value)
    return value


def verify(repo, directory):
    value = inspect(repo, directory)
    c.require(c.read_json(Path(directory) / 'receipt.json') == value,
              'package-identity', 'qualification receipt differs from independently recomputed evidence')
    return value
