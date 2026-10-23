#!/usr/bin/env python3
"""Delete after knife 4: review parser-owned separators, then edit source spans.

Source edits and decoded embedded candidates are deliberately different records.
Only source records can be applied: a decoded string offset does not identify a
host-language source offset, and prose can quote another language's syntax.
"""

import argparse
import ast
import base64
from collections import Counter, defaultdict
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent


def run(*args, **kwargs):
    return subprocess.run(args, check=True, text=True, capture_output=True, **kwargs).stdout


def tracked(root):
    return [root / name for name in run("git", "ls-files", "-z", cwd=root).split("\0") if name
            if (root / name).is_file()]


def read_source(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return stream.read()


def write_source(path, text):
    with path.open("w", encoding="utf-8", newline="") as stream:
        stream.write(text)


def apply(source, hits):
    """Python string indexes and compiler spans both count Unicode code points."""
    for offset in sorted({hit["offset"] for hit in hits}, reverse=True):
        if source[offset] != ":":
            raise ValueError(f"source changed at code point {offset}")
        source = source[:offset] + "=" + source[offset + 1:]
    return source


def probe(java, jar, work, sources, fragments=False):
    if any("\n" in str(path) for path in sources):
        raise ValueError("newline in source path cannot be represented in the probe manifest")
    manifest = work / "files.list"
    manifest.write_text("".join(str(path) + "\n" for path in sources))
    output = run(java, "-Xss64m", "-Xmx2g", "-cp", f"{work}{os.pathsep}{jar}",
                 "SpanProbe", str(manifest), *( ["fragments"] if fragments else []))
    return [line.split("\t") for line in output.splitlines()]


def snippets(path, text):
    """Extract review candidates only; regex never identifies an edit token."""
    if path.suffix == ".md":
        mask = list(text)
        for match in re.finditer(r"^```([^\n]*)\n(.*?)^```[^\n]*$", text, re.M | re.S):
            language = match[1].split()
            if not language or language[0] == "dawn":
                yield "markdown-fence", match.start(2), match[2]
            mask[match.start():match.end()] = " " * len(match[0])
        for match in re.finditer(r"(?<!`)`([^`\n]+)`(?!`)", "".join(mask)):
            yield "markdown-inline", match.start(1), match[1]
    elif path.suffix == ".py":
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                yield "python-string", f"{node.lineno}:{node.col_offset}", node.value
    elif path.suffix == ".sh":
        for match in re.finditer(r"<<-?\s*['\"]?([A-Za-z_][A-Za-z_0-9]*)['\"]?[^\n]*\n(.*?)^\1\s*$",
                                 text, re.M | re.S):
            yield "shell-heredoc", match.start(2), match[2]
    elif path.suffix == ".json" and path.name != "package-lock.json":
        try:
            data = json.loads(text)
        except (ValueError, RecursionError):
            return

        def strings(value, key):
            if isinstance(value, str):
                yield "json-string", key, value
            elif isinstance(value, list):
                for index, item in enumerate(value):
                    yield from strings(item, f"{key}/{index}")
            elif isinstance(value, dict):
                for name, item in value.items():
                    yield from strings(item, f"{key}/{name}")
        yield from strings(data, "")
    elif path.suffix in (".expected", ".expect", ".expect-stderr") or path.name.startswith("expected"):
        yield "golden", 0, text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=HERE.parents[1])
    parser.add_argument("--jar", type=Path, required=True)
    parser.add_argument("--java", default="java")
    parser.add_argument("--javac", default="javac")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--write", action="store_true", help="apply source records only")
    parser.add_argument("--source-only", action="store_true", help="omit host snippet review")
    args = parser.parse_args()
    root, jar = args.root.resolve(), args.jar.resolve()
    files = tracked(root)
    sources = [path for path in files if path.suffix == ".dawn"]
    source_hits = defaultdict(dict)
    embedded = []
    diagnostics = {}
    with tempfile.TemporaryDirectory(prefix="named-arg-migrate-") as temporary:
        work = Path(temporary)
        run(args.javac, "-cp", str(jar), "-d", str(work), str(HERE / "SpanProbe.java"))
        for row in probe(args.java, jar, work, sources):
            tag, index, *rest = row
            path = sources[int(index)].relative_to(root).as_posix()
            if tag == "D":
                if int(rest[0]):
                    diagnostics[path] = int(rest[0])
            elif tag in ("H", "R"):
                kind, offset = rest
                source_hits[path][int(offset)] = {
                    "kind": kind, "offset": int(offset), "recovered": tag == "R"}
            elif tag == "S":
                string_index, kind, offset, encoded = rest
                embedded.append({"path": path, "category": "dawn-string",
                                 "location": int(string_index), "kind": kind, "offset": int(offset),
                                 "text": base64.b64decode(encoded).decode()})
        if not args.source_only:
            fragments, metadata = [], []
            for path in files:
                if path.suffix == ".dawn":
                    continue
                try:
                    text = path.read_text()
                except UnicodeError:
                    continue
                for category, location, text in snippets(path, text):
                    if ":" not in text:
                        continue
                    fragment = work / f"fragment-{len(fragments)}.dawn"
                    fragment.write_text(text)
                    fragments.append(fragment)
                    metadata.append({"path": path.relative_to(root).as_posix(), "category": category,
                                     "location": location, "text": text})
            for _, index, kind, offset in probe(args.java, jar, work, fragments, True):
                embedded.append({**metadata[int(index)], "kind": kind, "offset": int(offset)})
    modules = defaultdict(lambda: {"counts": Counter(), "files": 0})
    source = []
    for path, offsets in sorted(source_hits.items()):
        text = read_source(root / path)
        hits = sorted(offsets.values(), key=lambda hit: hit["offset"])
        module = "scripts/grammar-corpus" if path.startswith("scripts/grammar-corpus/") else path.split("/")[0]
        modules[module]["counts"].update(hit["kind"] for hit in hits)
        modules[module]["files"] += 1
        for hit in hits:
            offset = hit["offset"]
            hit["line"] = text.count("\n", 0, offset) + 1
            hit["column"] = offset - text.rfind("\n", 0, offset)
            hit["excerpt"] = text[text.rfind("\n", 0, offset) + 1:text.find("\n", offset) if "\n" in text[offset:] else len(text)]
        source.append({"path": path, "module": module, "hits": hits})
        if args.write:
            write_source(root / path, apply(text, hits))
    counts = Counter(hit["kind"] for entry in source for hit in entry["hits"])
    report = {"schema": "named-arg-migrate-v1", "offset_unit": "unicode-code-point",
              "source_counts": counts, "source_files": len(source), "modules": dict(sorted(modules.items())),
              "source": source, "embedded_review": embedded, "parse_diagnostics": diagnostics}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"source_counts": counts, "source_files": len(source), "modules": report["modules"],
                      "embedded_counts": dict(Counter(item["category"] for item in embedded)),
                      "recovered": sum(hit["recovered"] for entry in source for hit in entry["hits"])}, sort_keys=True))


if __name__ == "__main__":
    main()
