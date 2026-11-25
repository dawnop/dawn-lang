#!/usr/bin/env python3
"""Exercise the nine-asset protocol with an explicitly synthetic chain record.

The JAR emission contract builds one native executable, not a native seed
chain. This test-only adapter keeps that fact visible and out of the release
producer's command-line options. release.yml never invokes this file.
"""

import argparse
from pathlib import Path

import native_release as nr
from native_seed import builder, contract as c, lockchain, test_support


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('lock', 'native', 'builder', 'jdk21-jar', 'jdk26-jar', 'pub-api', 'pub-api-diff', 'out'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--skip-smoke', action='store_true')
    args = parser.parse_args()
    args.expect_tag = None
    record = test_support.chain_record(nr.ROOT, lockchain.release_lock(args.lock),
                                       Path(args.builder).absolute(), Path(args.native).absolute())
    args.chain_receipt = str(Path(args.out).parent / 'synthetic-chain-receipt.json')
    c.atomic_json(args.chain_receipt, record)
    # This adapter exercises assets, not an actual hosted execution. Production
    # enters through produce(), which also requires the current hosted run.
    checked = builder.verify_receipt(args.chain_receipt, nr.ROOT, lockchain.release_lock(args.lock),
                                      Path(args.native).absolute(), Path(args.builder).absolute())
    nr._produce(args, checked)


if __name__ == '__main__':
    main()
