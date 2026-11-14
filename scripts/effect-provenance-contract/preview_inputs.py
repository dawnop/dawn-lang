#!/usr/bin/env python3
"""Prepare an authoritative parser index, never event counts or parent trees.

The parser dump and source revision are frozen build inputs. Both consumers
load the same declarations and syntax ranges before serving a preview.
"""
import argparse
import hashlib
from pathlib import Path
import re


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--parser-index', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--program-c', type=Path)
    parser.add_argument('--api-header', type=Path)
    args = parser.parse_args()
    declarations, ast = args.parser_index.read_text().split('@@ast\n', 1)
    decls = sorted(tuple(line.split('\t')) for line in declarations.splitlines())
    assert len({d[0] for d in decls}) == len(decls)
    spans = sorted(set((int(a), int(b)) for a, b in re.findall(r'(?<!name)@([0-9]+)\.\.([0-9]+)', ast)))
    revision = hashlib.sha256(args.source.read_bytes()).hexdigest()
    args.out.write_text('revision\t'+revision+'\n'+
        ''.join('declaration\t'+'\t'.join(d)+'\n' for d in decls)+
        ''.join(f'span\t{a}\t{b}\n' for a,b in spans))
    if args.program_c or args.api_header:
        assert args.program_c and args.api_header, 'both C program and API output are required'
        names = ('main__(?:select_1case|record_1case|preview_1program|encode_1program|'
                 'operation_1count|snapshot_1text)|std_2provenance__(?:snapshot_1info|'
                 'static_1table|record_1at|site_1at|definition_1at|note_1at|'
                 'find_1instance|scope|epoch|instance|origin_1boundary|origin_1completeness|records|'
                 'record_1(?:count|scope|exists|epoch|instance|parent|state|site|definition|boundary)|'
                 'index_1(?:present|value))')
        declarations = [line for line in args.program_c.read_text().splitlines()
                        if line.endswith(';') and re.match(
                            r'^[A-Za-z_][A-Za-z0-9_* ]* dawn_(?:'+names+r')\(', line)]
        assert len(declarations) == 31, 'missing or duplicate public consumer entry'
        args.api_header.write_text('/* Public compiled Dawn entry declarations for the host consumer. */\n'
                                   '#include "dawn_rt.h"\n'+'\n'.join(declarations)+'\n')


if __name__ == '__main__':
    main()
