#!/usr/bin/env python3
"""Judge measured ELF artifacts before consulting timing thresholds.

Only nonallocated STT_FILE strings may be normalized. All allocated sections,
program headers and PT_LOAD bytes must match without normalization, including
relocations, unwind tables, TLS and zero-fill sizes. Inputs are never rewritten.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct


def digest(data):
    return hashlib.sha256(data).hexdigest()


def elf(path):
    data = path.read_bytes()
    if data[:6] != b'\x7fELF\x02\x01':
        raise ValueError('expected a little-endian ELF64 artifact')
    header = struct.unpack_from('<16sHHIQQQIHHHHHH', data)
    _, _, _, _, _, phoff, shoff, _, _, phsize, phnum, shsize, shnum, shstr = header
    sections = [struct.unpack_from('<IIQQQQIIQQ', data, shoff+i*shsize) for i in range(shnum)]
    strings = sections[shstr]
    names = data[strings[4]:strings[4]+strings[5]]

    def string(table, offset):
        return table[offset:table.index(b'\0', offset)].decode()

    rows = []
    normalized = bytearray(data)
    files = []
    for section in sections:
        name, kind, flags, address, offset, size, link, info, alignment, entry = section
        payload = b'' if kind == 8 else data[offset:offset+size]
        rows.append(dict(name=string(names, name), type=kind, flags=flags,
                         address=address, offset=offset, size=size, link=link,
                         info=info, alignment=alignment, entry_size=entry,
                         sha256=digest(payload), zero_fill=kind == 8))
        if kind != 2:
            continue
        table = sections[link]
        if table[2] & 2:
            raise ValueError('refusing to normalize an allocated symbol string table')
        text = data[table[4]:table[4]+table[5]]
        for pos in range(offset, offset+size, entry):
            stname, stinfo, _, _, _, _ = struct.unpack_from('<IBBHQQ', data, pos)
            if stinfo & 15 == 4:
                filename = string(text, stname)
                start = table[4]+stname
                normalized[start:start+len(filename)] = b'\0'*len(filename)
                files.append(dict(name=filename, offset=start, size=len(filename)))
    segments = []
    for i in range(phnum):
        kind, flags, offset, vaddr, paddr, size, memsize, alignment = struct.unpack_from(
            '<IIQQQQQQ', data, phoff+i*phsize)
        segments.append(dict(type=kind, flags=flags, offset=offset, address=vaddr,
                             physical_address=paddr, size=size, memory_size=memsize,
                             alignment=alignment,
                             sha256=digest(data[offset:offset+size])))
    return dict(sha256=digest(data), bytes=len(data), sections=rows,
                segments=segments, file_symbols=files,
                normalized_sha256=digest(normalized)), data


def compare(a, b):
    left, adata = elf(a)
    right, bdata = elf(b)
    if len(adata) != len(bdata):
        raise ValueError('different artifact sizes require an explicit investigation')
    differing = [i for i, (x, y) in enumerate(zip(adata, bdata)) if x != y]
    changed_sections = []
    if len(left['sections']) != len(right['sections']):
        raise ValueError('different section counts require an explicit investigation')
    for x, y in zip(left['sections'], right['sections']):
        if x != y:
            changed_sections.append(dict(A=x, B=y))
    allocated_a = [s for s in left['sections'] if s['flags'] & 2]
    allocated_b = [s for s in right['sections'] if s['flags'] & 2]
    load_a = [s for s in left['segments'] if s['type'] == 1]
    load_b = [s for s in right['segments'] if s['type'] == 1]
    same = (allocated_a == allocated_b and left['segments'] == right['segments']
            and load_a == load_b and left['normalized_sha256'] == right['normalized_sha256'])
    return dict(A=left, B=right, differing_offsets=differing,
                changed_sections=changed_sections,
                allocated_sections_identical=allocated_a == allocated_b,
                program_segments_identical=left['segments'] == right['segments'],
                load_segments_identical=load_a == load_b,
                normalized_files_identical=left['normalized_sha256'] == right['normalized_sha256'],
                normalization='zero only nonallocated STT_FILE string bytes',
                verdict='structurally-identical' if same else 'investigate-difference')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('a', type=Path)
    parser.add_argument('b', type=Path)
    args = parser.parse_args()
    result = compare(args.a, args.b)
    print(json.dumps(result, indent=2))
    if result['verdict'] != 'structurally-identical':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
