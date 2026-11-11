#!/usr/bin/env python3
"""Rebuild the locked raw class directory without starting a Java process.

The reviewed lock binds the upstream module bytes and every selected class.
Extraction uses those entries directly so metadata preparation has no reflection
producer, archive execution, class discovery, or dependency download step.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import zipfile

LOCK = Path(__file__).with_name('jdk21.lock.json')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def prepare(jdk, destination):
    raw = LOCK.read_bytes()
    lock = json.loads(raw)
    jdk = Path(jdk)
    destination = Path(destination)
    if destination.exists():
        raise ValueError('metadata destination already exists')
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='java-metadata-', dir=destination.parent))
    try:
        if digest((jdk / 'release').read_bytes()) != lock['platform']['release_sha256']:
            raise ValueError('JDK release identity mismatch')
        for module in lock['modules']:
            path = jdk / 'jmods' / (module['name'] + '.jmod')
            if digest(path.read_bytes()) != module['sha256']:
                raise ValueError('JDK module identity mismatch: ' + module['name'])
            with zipfile.ZipFile(path) as archive:
                if len(archive.namelist()) != len(set(archive.namelist())):
                    raise ValueError('duplicate archive entry')
                for entry in lock['classes']:
                    if entry['module'] != module['name']:
                        continue
                    relative = 'classes/' + entry['name'].replace('.', '/') + '.class'
                    data = archive.read(relative)
                    if len(data) != entry['size'] or digest(data) != entry['sha256']:
                        raise ValueError('class identity mismatch: ' + entry['name'])
                    target = staging / entry['path']
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
        (staging / 'manifest.json').write_bytes(raw)
        staging.rename(destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return digest(raw)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--jdk', default=os.environ.get('JAVA_HOME'))
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if not args.jdk:
        parser.error('--jdk or JAVA_HOME is required')
    print(prepare(args.jdk, args.out))


if __name__ == '__main__':
    main()
