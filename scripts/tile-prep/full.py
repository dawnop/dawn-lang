#!/usr/bin/env python3
"""Build, bind and receive the tile execution closure."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess as sp
import sys
import tarfile
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
TEMP = Path(os.environ.get('RUNNER_TEMP', '/tmp'))
JDK_URL = 'https://github.com/graalvm/graalvm-ce-builds/releases/download/jdk-21.0.2/graalvm-community-jdk-21.0.2_linux-x64_bin.tar.gz'
JDK_SHA = 'b048069aaa3a99b84f5b957b162cc181a32a4330cbc35402766363c5be76ae48'
UPLOAD = 'ea165f8d65b6e75b540449e92b4886f43607fa02'
DOWNLOAD = 'd3f86a106a0bac45b974a628896c90dbdf5c8093'
CHECKOUT = '11d5960a326750d5838078e36cf38b85af677262'
CACHE = '0057852bfaa89a56745cba8c7296529d2fc39830'


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def output(command, **kwargs):
    kwargs.setdefault('cwd', ROOT)
    return sp.check_output(command, text=True, **kwargs).strip()


def emit(path, values):
    with Path(path).open('a') as stream:
        for key, value in values.items():
            stream.write(f'{key}={value}\n')


def identity():
    sp.run(['git', 'diff', '--quiet', 'HEAD'], cwd=ROOT, check=True)
    return dict(schema=1, repository=os.environ['GITHUB_REPOSITORY'],
                repository_id=os.environ['GITHUB_REPOSITORY_ID'],
                checkout=output(['git', 'rev-parse', 'HEAD']),
                tree=output(['git', 'rev-parse', 'HEAD^{tree}']),
                run=os.environ['GITHUB_RUN_ID'], system=output(['uname', '-sm']),
                libc=output(['getconf', 'GNU_LIBC_VERSION']),
                cc=output(['cc', '--version']).splitlines()[0],
                recipe=sha(__file__), upload_action=UPLOAD, download_action=DOWNLOAD,
                checkout_action=CHECKOUT, cache_action=CACHE,
                trust={p: sha(ROOT / p) for p in ['scripts/seed-release.txt',
                    'scripts/seed-checksums.txt', 'scripts/seed-std-checksums.txt',
                    'scripts/tile-golden/toolchain.txt', '.github/actions/dawn-toolchain/action.yml']})


def unpack(archive, dest, compressed=False):
    # One pass, with Python's data filter rejecting absolute paths, device files,
    # parent traversal and links escaping the fresh private extraction directory.
    dest.mkdir(parents=True, exist_ok=False)
    proc = sp.Popen(['zstd', '-dc', str(archive)], stdout=sp.PIPE) if compressed else None
    try:
        with tarfile.open(fileobj=proc.stdout, mode='r|') if proc else tarfile.open(archive, 'r:gz') as tar:
            tar.extractall(dest, filter='data')
    finally:
        if proc:
            proc.stdout.close()
            if proc.wait() != 0:
                raise RuntimeError('zstd extraction failed')


def native_identity():
    sp.run(['git', 'diff', '--quiet', 'HEAD'], cwd=ROOT, check=True)
    return dict(schema=1, tree=output(['git', 'rev-parse', 'HEAD^{tree}']),
        inputs=output(['python3', '-I', '-B', 'scripts/tile-gpu-diff/inputs.py']),
        runner=sha(ROOT / 'scripts/tile-golden/run.sh'),
        helper=sha(__file__), system=output(['uname', '-sm']),
        libc=output(['getconf', 'GNU_LIBC_VERSION']),
        cc=output([os.environ.get('CC') or 'cc', '--version']))


def native_seal(directory):
    started = time.monotonic()
    manifest = dict(identity=native_identity(), files={
        name: sha(directory / name) for name in ('dawn_rt.o', 'clean.bin')})
    (directory / 'native.json').write_text(json.dumps(manifest, sort_keys=True) + '\n')
    print('NATIVE_SEAL_METRIC ' + json.dumps(dict(seconds=time.monotonic()-started)), flush=True)


def native_verify(directory):
    started = time.monotonic()
    manifest = json.loads((directory / 'native.json').read_text())
    if manifest['identity'] != native_identity():
        raise RuntimeError('wrong native source, toolchain or platform identity')
    if set(manifest['files']) != {'dawn_rt.o', 'clean.bin'}:
        raise RuntimeError('wrong native closure')
    for name, digest in manifest['files'].items():
        if sha(directory / name) != digest:
            raise RuntimeError('altered native file: ' + name)
    print('NATIVE_VERIFY_METRIC ' + json.dumps(dict(seconds=time.monotonic()-started)), flush=True)


def download(url=JDK_URL, expected_sha=JDK_SHA, cache=None,
             speed_time=45, attempt_delay=10, stage_delay=15):
    cache = cache or TEMP / 'producer-deps'
    cache.mkdir(exist_ok=True)
    archive = cache / 'graalvm.tar.gz'
    if archive.exists():
        if sha(archive) == expected_sha:
            print('JDK_DEPENDENCY_CACHE verified hit', flush=True)
            return archive
        archive.unlink()
        print('JDK_DEPENDENCY_CACHE rejected corrupt candidate', flush=True)
    for stage in range(2):
        for attempt in range(3):
            candidate = archive.with_suffix('.partial')
            candidate.unlink(missing_ok=True)
            start = time.monotonic()
            result = sp.run(['curl', '--fail', '--location', '--show-error', '--silent',
                '--connect-timeout', '15', '--speed-limit', '1024', '--speed-time', str(speed_time),
                '--output', str(candidate), '--write-out',
                '%{http_code} %{time_connect} %{time_starttransfer} %{time_total} %{size_download}\n',
                url], capture_output=True, text=True)
            fields = result.stdout.split()
            status = int(fields[0]) if fields and fields[0].isdigit() else 0
            print('DOWNLOAD_METRIC ' + json.dumps(dict(stage=stage + 1,
                attempt=attempt + 1, elapsed=time.monotonic() - start,
                exit=result.returncode, timing=fields, error=result.stderr)), flush=True)
            if result.returncode == 0:
                if sha(candidate) != expected_sha:
                    candidate.unlink(missing_ok=True)
                    raise RuntimeError('JDK checksum mismatch')
                candidate.replace(archive)
                return archive
            candidate.unlink(missing_ok=True)
            # Permanent HTTP errors end this stage, preserving the original
            # outer recovery stage even when its first GET cannot be retried.
            if result.returncode == 22 and 400 <= status < 500 and status not in (408, 429):
                break
            if attempt < 2:
                time.sleep(attempt_delay)
        if stage == 0:
            print('::warning title=GraalVM setup retried::The first logical download stage failed; retrying after 15 seconds.', flush=True)
            time.sleep(stage_delay)
    raise RuntimeError('both GraalVM download stages failed')


def prepare():
    started = time.monotonic()
    archive = download()
    unpack(archive, TEMP / 'jdk-extracted')
    jdk, = (TEMP / 'jdk-extracted').iterdir()
    env = dict(os.environ, JAVA_HOME=str(jdk), GRAALVM_HOME=str(jdk),
               PATH=f'{jdk}/bin:' + os.environ['PATH'])
    # Dependencies may be cached, but every producer builds this run's compiler.
    for name in ('dawn-selfhost.jar', 'dawn-selfhost.stamp', 'dawn-selfhost.inputs'):
        (ROOT / 'build' / name).unlink(missing_ok=True)
    sp.run(['./bin/dawn', '--version'], cwd=ROOT, env=env, check=True)
    # A dependency cache contributes candidates, never trusted installed code.
    wheels = TEMP / 'tileiras-wheels'
    wheels.mkdir(exist_ok=True)
    for line in (ROOT / 'scripts/tile-golden/toolchain.txt').read_text().splitlines():
        if line.startswith('wheel '):
            _, spec, digest = line.split()
            name, version = spec.split('==')
            for candidate in wheels.glob(name.replace('-', '_') + '-' + version + '-*.whl'):
                if sha(candidate) != digest.removeprefix('sha256='):
                    candidate.unlink()
                    print('WHEEL_DEPENDENCY_CACHE rejected corrupt candidate: ' + spec, flush=True)
    tileiras = output(['./scripts/tile-golden/install-tileiras.sh',
                      str(TEMP / 'tileiras'), str(TEMP / 'tileiras-wheels')], env=env)
    stage = TEMP / 'execution-closure'
    stage.mkdir()
    sp.run(['./scripts/tile-golden/run.sh', '--prepare', str(stage / 'native')],
           cwd=ROOT, env=env, check=True)
    prepared = time.monotonic()
    # Keep the JVM implementation unchanged. Build tools, headers, sources and
    # native-image's static SDK are not read by the shard execution path.
    runtime = stage / 'jdk'
    runtime.mkdir()
    shutil.copytree(jdk / 'lib', runtime / 'lib', symlinks=True,
        ignore=shutil.ignore_patterns('src.zip', 'static', 'svm', 'ct.sym'))
    shutil.copytree(jdk / 'conf', runtime / 'conf', symlinks=True)
    shutil.copytree(jdk / 'legal', runtime / 'legal', symlinks=True)
    (runtime / 'bin').mkdir()
    shutil.copy2(jdk / 'bin/java', runtime / 'bin/java')
    shutil.copy2(jdk / 'release', runtime / 'release')
    repo = stage / 'repo'
    (repo / 'build').mkdir(parents=True)
    (repo / '.dawn').mkdir()
    shutil.copytree(ROOT / '.dawn/seeds', repo / '.dawn/seeds')
    for name in ('dawn-selfhost.jar', 'dawn-selfhost.stamp', 'dawn-selfhost.inputs'):
        shutil.copy2(ROOT / 'build' / name, repo / 'build' / name)
    # Dawn emits JVM class files itself; no javac, jmods, coursier cache,
    # wheel archive or Python environment is needed by the consumers.
    site, = (TEMP / 'tileiras/lib').glob('python*/site-packages')
    tools = stage / 'assembler'
    tools.mkdir()
    for name in ('bin/tileiras', 'bin/ptxas', 'bin/tileirdisasm', 'lib/libnvvm.so.4'):
        target = tools / 'nvidia/cu13' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(site / 'nvidia/cu13' / name, target)
    manifest_started = time.monotonic()
    manifest = dict(identity(), producer_attempt=os.environ['GITHUB_RUN_ATTEMPT'],
        producer_job=os.environ['GITHUB_JOB'], created=time.time(),
        inputs=native_identity()['inputs'], jdk_sha256=JDK_SHA,
        jdk_version='21.0.2', java=output([str(jdk / 'bin/java'), '--version']),
        tileiras=output([tileiras, '--version']), selfhost={
            name: sha(repo / 'build' / name) for name in
            ('dawn-selfhost.jar', 'dawn-selfhost.stamp', 'dawn-selfhost.inputs')})
    (stage / 'manifest.json').write_text(json.dumps(manifest, sort_keys=True) + '\n')
    manifest_seconds = time.monotonic() - manifest_started
    sizes = {p.name: sum(f.stat().st_size for f in p.rglob('*') if f.is_file())
             for p in stage.iterdir() if p.is_dir()}
    dest = TEMP / 'out-full'
    dest.mkdir()
    bundle = dest / 'prep.tar.zst'
    with bundle.open('wb') as stream:
        tar = sp.Popen(['tar', '-C', str(stage), '-cf', '-', '.'], stdout=sp.PIPE)
        result = sp.run(['zstd', '-T2', '-1', '-q'], stdin=tar.stdout, stdout=stream)
        tar.stdout.close()
        if tar.wait() or result.returncode:
            raise RuntimeError('packing failed')
    checksum_started = time.monotonic()
    digest = sha(bundle)
    manifest_digest = sha(stage / 'manifest.json')
    checksum_seconds = time.monotonic() - checksum_started
    pack_seconds = time.monotonic() - prepared
    emit(os.environ['GITHUB_OUTPUT'], dict(full_sha=digest,
        full_manifest=manifest_digest))
    print('PREP_METRIC ' + json.dumps(dict(bytes=bundle.stat().st_size,
        components=sizes, prepare_seconds=prepared-started,
        assembler_files=[str(p.relative_to(tools)) for p in tools.rglob('*') if p.is_file()],
        pack_seconds=pack_seconds,
        manifest_seconds=manifest_seconds, checksum_seconds=checksum_seconds,
        tar_sha256=digest, manifest_sha256=manifest_digest)), flush=True)


def check_manifest(manifest, expected):
    if any(manifest.get(k) != v for k, v in expected.items()):
        raise RuntimeError('wrong producer identity')
    if manifest['producer_attempt'] != os.environ['PRODUCER_ATTEMPT']:
        raise RuntimeError('wrong producer attempt')
    if not 0 <= time.time() - manifest['created'] < 3 * 86400:
        raise RuntimeError('expired package')
    if manifest['jdk_sha256'] != JDK_SHA or manifest['jdk_version'] != '21.0.2':
        raise RuntimeError('wrong JDK identity')
    if manifest['inputs'] != native_identity()['inputs']:
        raise RuntimeError('wrong GPU inputs')


def check_package(bundle, expected_sha):
    if sha(bundle) != expected_sha:
        raise RuntimeError('wrong or altered package')


def consume():
    started = time.monotonic()
    bundle = TEMP / 'received/prep.tar.zst'
    if not os.environ['ARTIFACT_ID'].isdigit():
        raise RuntimeError('missing exact artifact ID')
    check_package(bundle, os.environ['EXPECTED_SHA'])
    hashed = time.monotonic()
    dest = TEMP / 'execution-closure'
    unpack(bundle, dest, compressed=True)
    unpacked = time.monotonic()
    if sha(dest / 'manifest.json') != os.environ['EXPECTED_MANIFEST']:
        raise RuntimeError('altered manifest')
    manifest = json.loads((dest / 'manifest.json').read_text())
    expected = identity()
    check_manifest(manifest, expected)
    native_verify(dest / 'native')
    verified = time.monotonic()
    shutil.copytree(dest / 'repo', ROOT, dirs_exist_ok=True)
    jdk = dest / 'jdk'
    tileiras, = (dest / 'assembler').glob('nvidia/cu13/bin/tileiras')
    if output([str(jdk / 'bin/java'), '--version']) != manifest['java']:
        raise RuntimeError('wrong JVM version')
    if output([str(tileiras), '--version']) != manifest['tileiras']:
        raise RuntimeError('wrong assembler version')
    emit(os.environ['GITHUB_ENV'], dict(JAVA_HOME=jdk, GRAALVM_HOME=jdk,
        TILEIRAS=tileiras))
    with Path(os.environ['GITHUB_PATH']).open('a') as stream:
        stream.write(str(jdk / 'bin') + '\n')
    finished = time.monotonic()
    metric = dict(consumer=os.environ['GITHUB_JOB'],
        attempt=os.environ['GITHUB_RUN_ATTEMPT'], producer_attempt=manifest['producer_attempt'],
        artifact_id=os.environ['ARTIFACT_ID'], inputs=manifest['inputs'],
        download_seconds=time.time()-float(os.environ['RECEIVE_STARTED'])-(finished-started),
        checksum_seconds=hashed-started, unpack_seconds=unpacked-hashed,
        identity_seconds=verified-unpacked, activate_seconds=finished-verified,
        receive_verify_seconds=time.time()-float(os.environ['RECEIVE_STARTED']),
        bytes=bundle.stat().st_size)
    (TEMP / 'receipt.json').write_text(json.dumps(metric, indent=2) + '\n')
    print('RECEIVE_METRIC ' + json.dumps(metric), flush=True)


def identity_selftest():
    """Mutate fixed manifests, never rebuild a mutant in the push control path."""
    manifest = json.loads((TEMP / 'execution-closure/manifest.json').read_text())
    expected = identity()
    check_manifest(manifest, expected)
    tests = dict(tree='0'*40, recipe='0'*64, jdk_version='0',
                 created=time.time()-4*86400, producer_attempt='0', inputs='0'*12)
    for field, value in tests.items():
        candidate = dict(manifest, **{field: value})
        try:
            check_manifest(candidate, expected)
        except RuntimeError:
            print('PASS identity refusal: ' + field, flush=True)
        else:
            raise RuntimeError('accepted wrong ' + field)
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        fixture = directory / 'package'
        fixture.write_bytes(b'package one')
        digest = sha(fixture)
        check_package(fixture, digest)
        for name, value in [('wrong package', b'package two'), ('tampered package', b'package onE')]:
            fixture.write_bytes(value)
            try:
                check_package(fixture, digest)
            except RuntimeError:
                print('PASS identity refusal: ' + name, flush=True)
            else:
                raise RuntimeError('accepted ' + name)
        shutil.copytree(TEMP / 'execution-closure/native', directory / 'native')
        native_verify(directory / 'native')
        with (directory / 'native/clean.bin').open('ab') as stream:
            stream.write(b'altered')
        try:
            native_verify(directory / 'native')
        except RuntimeError:
            print('PASS identity refusal: altered clean native', flush=True)
        else:
            raise RuntimeError('accepted altered clean native')


if __name__ == '__main__':
    command = sys.argv[1]
    if command in ('native-seal', 'native-verify'):
        {'native-seal': native_seal, 'native-verify': native_verify}[command](Path(sys.argv[2]))
    else:
        {'prepare': prepare, 'consume': consume, 'identity-selftest': identity_selftest}[command]()
