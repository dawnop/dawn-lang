"""Strict debug export decoder for round trip controls, never a preview input.

S1/O1 are explicit versioned exports. The in-process consumer uses public
TraceSnapshot values; this decoder keeps external text imports fail closed.
"""
from dataclasses import dataclass


def escape(value):
    for a, b in [('%', '%25'), ('\t', '%09'), ('\n', '%0A'), ('\r', '%0D'), ('\0', '%00')]:
        value = value.replace(a, b)
    return value


def unescape(value):
    out = []; i = 0
    codes = {'25': '%', '09': '\t', '0A': '\n', '0D': '\r', '00': '\0'}
    while i < len(value):
        c = value[i]
        if c == '%':
            code = value[i+1:i+3]
            if code not in codes: raise ValueError('invalid escape')
            c = codes[code]; i += 2
        out.append(c); i += 1
    return ''.join(out)


def integer(value):
    n = int(value)
    if str(n) != value or not -(1 << 63) <= n < 1 << 63: raise ValueError('noncanonical integer')
    return n


@dataclass(frozen=True)
class Frame:
    scope: int
    epoch: int
    instance: int
    parent: int
    state: int
    site_id: int
    site: tuple
    definition: tuple
    boundary: int

    @classmethod
    def parse(cls, line):
        f = line.split('\t')
        if len(f) < 10 or f[0] != 'F': raise ValueError('invalid record')
        scope, epoch, instance, parent, state, site_id = map(integer, f[1:7])
        boundary = integer(f[-1]); at = 7
        if scope <= 0 or epoch <= 0 or instance <= 0 or parent < 0 or not 0 <= state <= 4 or boundary not in [0, 1]:
            raise ValueError('invalid record fields')
        width = 8 if site_id else 1
        site = tuple(unescape(x) for x in f[at:at+width]); at += width
        definition = tuple(unescape(x) for x in f[at:-1])
        if len(site) != width or len(definition) not in [1, 6]: raise ValueError('invalid static fields')
        if not site_id and site != ('',) or len(definition) == 1 and definition != ('',): raise ValueError('invalid empty identity')
        if site_id < 0: raise ValueError('invalid Site ID')
        if site_id:
            for x in f[9:13]: integer(x)
        if len(definition) == 6:
            integer(definition[2]); integer(definition[3]); integer(definition[5])
        return cls(scope, epoch, instance, parent, state, site_id, site, definition, boundary)

    def render(self):
        return '\t'.join(['F', *map(str, (self.scope, self.epoch, self.instance, self.parent, self.state, self.site_id)),
                          *map(escape, self.site), *map(escape, self.definition), str(self.boundary)])


@dataclass(frozen=True)
class OriginText:
    site_id: int
    site: tuple
    completeness: int
    frames: tuple

    @classmethod
    def parse(cls, text):
        head, *rows = text.splitlines(); h = head.split('\t')
        if len(h) != 11 or h[0] != 'O1': raise ValueError('invalid Origin version or header')
        site_id, completeness = integer(h[1]), integer(h[-1])
        if site_id <= 0 or completeness not in [0, 1]: raise ValueError('invalid Origin header fields')
        site = tuple(unescape(x) for x in h[2:-1]); frames = tuple(Frame.parse(x) for x in rows)
        if not frames: raise ValueError('missing Origin chain')
        scope = frames[0].scope
        for i, row in enumerate(frames):
            if row.scope != scope or row.parent != (frames[i+1].instance if i+1 < len(frames) else 0):
                raise ValueError('invalid Origin parent chain')
        return cls(site_id, site, completeness, frames)

    def render(self):
        return '\t'.join(['O1', str(self.site_id), *map(escape, self.site), str(self.completeness)]) + '\n' + '\n'.join(r.render() for r in self.frames)


@dataclass(frozen=True)
class SnapshotText:
    scope: int
    epoch: int
    completeness: int
    frames: tuple
    notes: tuple

    @classmethod
    def parse(cls, text):
        first, *notes = text.split('\n\n'); head, *rows = first.splitlines(); h = head.split('\t')
        if len(h) != 4 or h[0] != 'S1': raise ValueError('invalid snapshot version or header')
        scope, epoch, completeness = map(integer, h[1:])
        if scope <= 0 or epoch <= 0 or completeness not in [0, 1]: raise ValueError('invalid snapshot header fields')
        frames = tuple(Frame.parse(x) for x in rows); seen = set()
        if not frames: raise ValueError('missing root')
        for i, row in enumerate(frames):
            if row.scope != scope or row.instance in seen: raise ValueError('invalid snapshot identity')
            if i == 0:
                if row.instance != 1 or row.parent != 0: raise ValueError('invalid root')
            elif row.parent not in seen: raise ValueError('missing or reordered parent')
            seen.add(row.instance)
        return cls(scope, epoch, completeness, frames, tuple(OriginText.parse(x) for x in notes))

    def render(self):
        value = f'S1\t{self.scope}\t{self.epoch}\t{self.completeness}\n' + '\n'.join(r.render() for r in self.frames)
        return value + ''.join('\n\n' + n.render() for n in self.notes)


def exports(output):
    """Extract each explicit export amid the fixture's human readable values."""
    lines = output.splitlines(); found = []
    for start, line in enumerate(lines):
        if not (line.startswith('S1\t') or line.startswith('O1\t')): continue
        end = start+1
        while end < len(lines):
            if lines[end].startswith('F\t'): end += 1
            elif line.startswith('S1\t') and lines[end] == '' and end+1 < len(lines) and lines[end+1].startswith('O1\t'):
                end += 2
            else: break
        raw = '\n'.join(lines[start:end]); value = SnapshotText.parse(raw) if line.startswith('S1\t') else OriginText.parse(raw)
        if value.render() != raw: raise AssertionError('round trip changed fields')
        found.append((raw, value))
    if not found: raise AssertionError('no explicit export')
    return found


def negative_controls(raw):
    lines = raw.splitlines()
    bad_header = list(lines); header = bad_header[0].split('\t'); header[-1] = '2'; bad_header[0] = '\t'.join(header)
    variants = [raw.replace('S1\t', 'S2\t', 1), '\n'.join(bad_header)]
    first = next(i for i,x in enumerate(lines) if x.startswith('F\t'))
    row = next((i for i,x in enumerate(lines) if x.startswith('F\t') and x.split('\t')[3] != '1'), first)
    for field, value in [(4, lines[row].split('\t')[3]), (5, '5'), (-1, '2')]:
        copy = list(lines); fields = copy[row].split('\t'); fields[field] = value; copy[row] = '\t'.join(fields); variants.append('\n'.join(copy))
    for bad in variants:
        if bad == raw: continue
        try: SnapshotText.parse(bad)
        except (ValueError, IndexError): pass
        else: raise AssertionError('malformed export accepted')
    return len(variants)
