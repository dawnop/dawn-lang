#!/usr/bin/env python3
"""Probe for-pattern queries and completion scope through the LSP server."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile


HEADER_OWNER = "for pattern headers expose binder and constructor queries"
HEADER_COMPLETION_OWNER = "for pattern completion suppresses values across the recursive header"
LATEST_FOR_OWNER = "incomplete pattern recovery selects the latest enclosing for"
NEWLINE_RECOVERY_OWNER = "incomplete pattern recovery does not cross an ordinary newline"
NESTED_DEPTH_OWNER = "incomplete pattern recovery preserves nested delimiter depth"
RECORD_DEPTH_OWNER = "incomplete pattern recovery preserves record delimiter depth"
TOP_LEVEL_IN_OWNER = "incomplete pattern recovery requires a top-level in delimiter"
PREVIOUS_PIPE_OWNER = "incomplete pattern recovery requires a preceding pipe"
BOUNDARY_OWNER = "incomplete pattern recovery requires a same-depth pattern boundary"
HEADER_INTERVAL_OWNER = "incomplete pattern recovery stays before in, outside source body and after"
SOURCE_CTOR_OWNER = "incomplete pattern recovery excludes rejected source constructors"
QUALIFIED_COMPLETION_OWNER = "for pattern qualified completion exposes only module constructors"
RANGE_COMPLETION_OWNER = "range upper-bound completion offers outer locals"
SCOPE_OWNER = "for completion does not leak pattern or body locals"

LIB_TEXT = "pub type Only = Only(value: Int)\npub fn exported_value() -> Int = 1\n"
TEXT = (
    "use qlib as q\n"
    "\n"
    "type Choice = Left(value: Int) | Right(value: Int)\n"
    "\n"
    "fn probe(source: List[q.Only], choices: List[Choice], outer: Int) -> Int = {\n"
    "  for q.Only(header_value) in source {\n"
    "    let _ = header_value\n"
    "    let body_local = header_value\n"
    "    let _ = body_local\n"
    "  }\n"
    "  for Left(shared) | Right(shared) in choices {\n"
    "    let _ = shared\n"
    "  }\n"
    "  for range_value in outer..outer {\n"
    "    let _ = range_value\n"
    "  }\n"
    "  outer\n"
    "}\n"
)
RECOVERY_TEXT = (
    "type RecoveryChoice = RecoveryLeft(value: Int) | RecoveryRight(value: Int)\n"
    "\n"
    "fn recovery_probe(recovery_choices: List[RecoveryChoice], recovery_outer: Int) -> Unit = {\n"
    "  for RecoveryLeft(recovered) |  in recovery_choices { () }\n"
    "  let _ = recovery_outer\n"
    "}\n"
)
LATEST_TEXT = (
    "type LatestChoice = LatestLeft(value: Int) | LatestRight(value: Int)\n"
    "fn latest_probe(xs: List[LatestChoice]) -> Unit = {\n"
    "  for item in xs { let _ = item }\n"
    "  for LatestLeft(value) |  in xs { () }\n"
    "}\n"
)
NEWLINE_TEXT = (
    "type NewlineChoice = NewlineLeft(value: Int) | NewlineRight(value: Int)\n"
    "fn newline_probe(xs: List[NewlineChoice]) -> Unit = {\n"
    "  for NewlineLeft(value)\n"
    "  stray |  in xs { () }\n"
    "}\n"
)
NESTED_TEXT = (
    "type NestedChoice = NestedLeft(value: Int) | NestedRight(value: Int)\n"
    "type NestedPair = NestedPair(left: NestedChoice, right: Int)\n"
    "fn nested_probe(xs: List[NestedPair]) -> Unit = {\n"
    "  for NestedPair(NestedLeft(value) |  , right) in xs { () }\n"
    "}\n"
)
RECORD_TEXT = (
    "type RecordChoice = RecordLeft(value: Int) | RecordRight(value: Int)\n"
    "type RecoveryRecord = { choice: RecordChoice, other: Int }\n"
    "fn record_probe(xs: List[RecoveryRecord]) -> Unit = {\n"
    "  for RecoveryRecord { choice: RecordLeft(value) |  , other } in xs { () }\n"
    "}\n"
)
TOP_LEVEL_IN_TEXT = (
    "type InChoice = InLeft(value: Int) | InRight(value: Int)\n"
    "type InWrap = InWrap(value: InChoice)\n"
    "fn in_probe(xs: List[InWrap]) -> Unit = {\n"
    "  for InWrap(InLeft(value) |  in) in xs { () }\n"
    "}\n"
)
NO_PIPE_TEXT = (
    "type PipeChoice = PipeLeft(value: Int) | PipeRight(value: Int)\n"
    "fn pipe_probe(xs: List[PipeChoice]) -> Unit = {\n"
    "  for PipeLeft(value)  in xs { () }\n"
    "}\n"
)
NONBOUNDARY_TEXT = (
    "type BoundaryChoice = BoundaryLeft(value: Int) | BoundaryRight(value: Int)\n"
    "fn boundary_probe(xs: List[BoundaryChoice]) -> Unit = {\n"
    "  for BoundaryLeft(value) |  + in xs { () }\n"
    "}\n"
)
INTERVAL_TEXT = (
    "type IntervalChoice = IntervalLeft(value: Int) | IntervalRight(value: Int)\n"
    "fn combine(a: Int, b: Int) -> Int = a + b\n"
    "fn interval_probe(xs: List[Int], outer: Int) -> Unit = {\n"
    "  for item in combine(outer |  , outer)..outer { () }\n"
    "  for item in xs { let _ = combine(outer |  , outer) }\n"
    "  let _ = combine(outer |  , outer)\n"
    "}\n"
)
INVALID_CTOR_TEXT = (
    "type SourceChoice = SourceLeft(value: Int) | SourceRight(value: Int)\n"
    "type AliasMistake = Int\n"
    "type SourceChoice = RejectedDuplicate\n"
    "fn source_ctor_probe(xs: List[SourceChoice]) -> Unit = {\n"
    "  for SourceLeft(value) |  in xs { () }\n"
    "}\n"
)
QUALIFIED_TEXT = (
    "use qlib as q\n"
    "type LocalChoice = LocalLeft(value: Int) | LocalRight(value: Int)\n"
    "fn qualified_full(xs: List[q.Only]) -> Unit = {\n"
    "  for q.Only(value) in xs { () }\n"
    "}\n"
    "fn qualified_incomplete(xs: List[LocalChoice]) -> Unit = {\n"
    "  for LocalLeft(value) | q. in xs { () }\n"
    "}\n"
    "fn ordinary_member(value: Int) -> Unit = { let _ = value. }\n"
)


def position(index: int, text: str = TEXT) -> dict[str, int]:
    return {
        "line": text.count("\n", 0, index),
        "character": index - (text.rfind("\n", 0, index) + 1),
    }


def frame(message: dict) -> bytes:
    body = json.dumps(message).encode()
    return b"Content-Length: %d\r\n\r\n%s" % (len(body), body)


def replies(raw: bytes) -> dict[int, object]:
    out = {}
    rest = raw
    while True:
        head = rest.find(b"\r\n\r\n")
        if head < 0:
            return out
        header = rest[:head].decode("ascii", "replace")
        length = 0
        for line in header.split("\r\n"):
            if line.lower().startswith("content-length:"):
                length = int(line.split(":", 1)[1].strip())
        body = rest[head + 4 : head + 4 + length]
        rest = rest[head + 4 + length :]
        try:
            message = json.loads(body)
        except ValueError:
            continue
        if isinstance(message, dict) and "id" in message and "result" in message:
            out[message["id"]] = message["result"]


def hover_text(result: object) -> str:
    if not isinstance(result, dict):
        return ""
    contents = result.get("contents")
    if isinstance(contents, dict):
        return contents.get("value", "")
    return contents if isinstance(contents, str) else ""


def range_start(result: object):
    if isinstance(result, list) and result:
        result = result[0]
    if not isinstance(result, dict):
        return None
    target = result.get("targetSelectionRange") or result.get("range")
    return target.get("start") if isinstance(target, dict) else None


def definition_uri(result: object):
    if isinstance(result, list) and result:
        result = result[0]
    if not isinstance(result, dict):
        return None
    return result.get("targetUri") or result.get("uri")


def completion_labels(result: object) -> list[str]:
    if isinstance(result, dict):
        result = result.get("items", [])
    if not isinstance(result, list):
        return []
    return [item.get("label") for item in result if isinstance(item, dict)]


def completion_items(result: object) -> list[dict]:
    if isinstance(result, dict):
        result = result.get("items", [])
    if not isinstance(result, list):
        return []
    return [item for item in result if isinstance(item, dict)]


def constructors_only(result: object, expected: tuple[str, ...]) -> bool:
    items = completion_items(result)
    labels = completion_labels(result)
    return (
        len(items) > 0
        and all(item.get("kind") == 20 for item in items)
        and all(labels.count(name) == 1 for name in expected)
    )


def general_completion(result: object) -> bool:
    items = completion_items(result)
    return "for" in completion_labels(result) and any(item.get("kind") != 20 for item in items)


def fail(owner: str) -> None:
    print("ASSERT: " + owner)


def main() -> int:
    java, jar, cwd = sys.argv[1:]
    ctor = TEXT.index("q.Only(header") + len("q.")
    header_bind = TEXT.index("header_value")
    nested_header_completion = header_bind + len("header")
    header_use = TEXT.index("header_value", header_bind + 1)
    header_start = TEXT.index("q.Only(header")
    source_use = TEXT.index("in source") + len("in ")
    range_upper = TEXT.index("..outer") + len("..")
    after = TEXT.rindex("outer")
    recovery_header = RECOVERY_TEXT.index("|  in") + len("| ")
    recovery_source = RECOVERY_TEXT.index("in recovery_choices") + len("in ")
    latest_header = LATEST_TEXT.index("|  in") + len("| ")
    newline_gap = NEWLINE_TEXT.index("|  in") + len("| ")
    nested_gap = NESTED_TEXT.index("|  ,") + len("| ")
    record_gap = RECORD_TEXT.index("|  ,") + len("| ")
    nested_in_gap = TOP_LEVEL_IN_TEXT.index("|  in)") + len("| ")
    no_pipe_gap = NO_PIPE_TEXT.index("  in") + 1
    nonboundary_gap = NONBOUNDARY_TEXT.index("|  +") + len("| ")
    interval_gaps = []
    interval_start = 0
    while True:
        interval_found = INTERVAL_TEXT.find("|  ,", interval_start)
        if interval_found < 0:
            break
        interval_gaps.append(interval_found + len("| "))
        interval_start = interval_found + 1
    invalid_ctor_gap = INVALID_CTOR_TEXT.index("|  in") + len("| ")
    qualified_full = QUALIFIED_TEXT.index("q.Only(value)") + len("q.O")
    qualified_incomplete = QUALIFIED_TEXT.index("| q. in") + len("| q.")
    ordinary_member = QUALIFIED_TEXT.index("value. }") + len("value.")
    shared_occurrences = []
    start = 0
    while True:
        found = TEXT.find("shared", start)
        if found < 0:
            break
        shared_occurrences.append(found)
        start = found + 1

    temp = tempfile.TemporaryDirectory(prefix="for-pattern-lsp-")
    project = Path(temp.name)
    source_dir = project / "src"
    source_dir.mkdir()
    (project / "dawn.toml").write_text(
        'schema = 1\nname = "for_pattern_lsp"\n', encoding="utf-8"
    )
    lib_path = source_dir / "qlib.dawn"
    main_path = source_dir / "main.dawn"
    recovery_path = source_dir / "recovery.dawn"
    latest_path = source_dir / "latest.dawn"
    newline_path = source_dir / "newline.dawn"
    nested_path = source_dir / "nested.dawn"
    record_path = source_dir / "record.dawn"
    top_level_in_path = source_dir / "top_level_in.dawn"
    no_pipe_path = source_dir / "no_pipe.dawn"
    nonboundary_path = source_dir / "nonboundary.dawn"
    interval_path = source_dir / "interval.dawn"
    invalid_ctor_path = source_dir / "invalid_ctor.dawn"
    qualified_path = source_dir / "qualified.dawn"
    lib_path.write_text(LIB_TEXT, encoding="utf-8")
    main_path.write_text(TEXT, encoding="utf-8")
    recovery_path.write_text(RECOVERY_TEXT, encoding="utf-8")
    latest_path.write_text(LATEST_TEXT, encoding="utf-8")
    newline_path.write_text(NEWLINE_TEXT, encoding="utf-8")
    nested_path.write_text(NESTED_TEXT, encoding="utf-8")
    record_path.write_text(RECORD_TEXT, encoding="utf-8")
    top_level_in_path.write_text(TOP_LEVEL_IN_TEXT, encoding="utf-8")
    no_pipe_path.write_text(NO_PIPE_TEXT, encoding="utf-8")
    nonboundary_path.write_text(NONBOUNDARY_TEXT, encoding="utf-8")
    interval_path.write_text(INTERVAL_TEXT, encoding="utf-8")
    invalid_ctor_path.write_text(INVALID_CTOR_TEXT, encoding="utf-8")
    qualified_path.write_text(QUALIFIED_TEXT, encoding="utf-8")
    lib_uri = lib_path.resolve().as_uri()
    uri = main_path.resolve().as_uri()
    recovery_uri = recovery_path.resolve().as_uri()
    latest_uri = latest_path.resolve().as_uri()
    newline_uri = newline_path.resolve().as_uri()
    nested_uri = nested_path.resolve().as_uri()
    record_uri = record_path.resolve().as_uri()
    top_level_in_uri = top_level_in_path.resolve().as_uri()
    no_pipe_uri = no_pipe_path.resolve().as_uri()
    nonboundary_uri = nonboundary_path.resolve().as_uri()
    interval_uri = interval_path.resolve().as_uri()
    invalid_ctor_uri = invalid_ctor_path.resolve().as_uri()
    qualified_uri = qualified_path.resolve().as_uri()

    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "processId": None, "rootUri": project.resolve().as_uri(), "capabilities": {}}},
        {"jsonrpc": "2.0", "method": "initialized", "params": {}},
        {"jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {
            "textDocument": {"uri": lib_uri, "languageId": "dawn", "version": 1,
                             "text": LIB_TEXT}}},
        {"jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {
            "textDocument": {"uri": uri, "languageId": "dawn", "version": 1,
                             "text": TEXT}}},
        {"jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {
            "textDocument": {"uri": recovery_uri, "languageId": "dawn", "version": 1,
                             "text": RECOVERY_TEXT}}},
        *({"jsonrpc": "2.0", "method": "textDocument/didOpen", "params": {
            "textDocument": {"uri": case_uri, "languageId": "dawn", "version": 1,
                             "text": case_text}}}
          for case_uri, case_text in (
              (latest_uri, LATEST_TEXT),
              (newline_uri, NEWLINE_TEXT),
              (nested_uri, NESTED_TEXT),
              (record_uri, RECORD_TEXT),
              (top_level_in_uri, TOP_LEVEL_IN_TEXT),
              (no_pipe_uri, NO_PIPE_TEXT),
              (nonboundary_uri, NONBOUNDARY_TEXT),
              (interval_uri, INTERVAL_TEXT),
              (invalid_ctor_uri, INVALID_CTOR_TEXT),
              (qualified_uri, QUALIFIED_TEXT),
          )),
        {"jsonrpc": "2.0", "id": 2, "method": "textDocument/hover", "params": {
            "textDocument": {"uri": uri}, "position": position(ctor)}},
        {"jsonrpc": "2.0", "id": 3, "method": "textDocument/definition", "params": {
            "textDocument": {"uri": uri}, "position": position(ctor)}},
        {"jsonrpc": "2.0", "id": 4, "method": "textDocument/hover", "params": {
            "textDocument": {"uri": uri}, "position": position(header_bind)}},
        {"jsonrpc": "2.0", "id": 5, "method": "textDocument/definition", "params": {
            "textDocument": {"uri": uri}, "position": position(header_use)}},
        {"jsonrpc": "2.0", "id": 6, "method": "textDocument/completion", "params": {
            "textDocument": {"uri": uri}, "position": position(source_use)}},
        {"jsonrpc": "2.0", "id": 7, "method": "textDocument/completion", "params": {
            "textDocument": {"uri": uri}, "position": position(header_use)}},
        {"jsonrpc": "2.0", "id": 8, "method": "textDocument/completion", "params": {
            "textDocument": {"uri": uri}, "position": position(after)}},
        {"jsonrpc": "2.0", "id": 9, "method": "textDocument/hover", "params": {
            "textDocument": {"uri": uri}, "position": position(shared_occurrences[1])}},
        {"jsonrpc": "2.0", "id": 10, "method": "textDocument/definition", "params": {
            "textDocument": {"uri": uri}, "position": position(shared_occurrences[1])}},
        {"jsonrpc": "2.0", "id": 11, "method": "textDocument/completion", "params": {
            "textDocument": {"uri": uri}, "position": position(shared_occurrences[2])}},
        {"jsonrpc": "2.0", "id": 12, "method": "textDocument/definition", "params": {
            "textDocument": {"uri": uri}, "position": position(header_bind)}},
        {"jsonrpc": "2.0", "id": 13, "method": "textDocument/completion", "params": {
            "textDocument": {"uri": uri}, "position": position(header_start)}},
        {"jsonrpc": "2.0", "id": 14, "method": "textDocument/completion", "params": {
            "textDocument": {"uri": uri}, "position": position(range_upper)}},
        {"jsonrpc": "2.0", "id": 15, "method": "textDocument/completion", "params": {
            "textDocument": {"uri": uri}, "position": position(nested_header_completion)}},
        {"jsonrpc": "2.0", "id": 16, "method": "textDocument/completion", "params": {
            "textDocument": {"uri": uri},
            "position": position(shared_occurrences[1] + len("sha"))}},
        {"jsonrpc": "2.0", "id": 17, "method": "textDocument/completion", "params": {
            "textDocument": {"uri": recovery_uri},
            "position": position(recovery_header, RECOVERY_TEXT)}},
        {"jsonrpc": "2.0", "id": 18, "method": "textDocument/completion", "params": {
            "textDocument": {"uri": recovery_uri},
            "position": position(recovery_source, RECOVERY_TEXT)}},
        {"jsonrpc": "2.0", "id": 19, "method": "textDocument/completion", "params": {
            "textDocument": {"uri": latest_uri}, "position": position(latest_header, LATEST_TEXT)}},
        {"jsonrpc": "2.0", "id": 20, "method": "textDocument/completion", "params": {
            "textDocument": {"uri": newline_uri}, "position": position(newline_gap, NEWLINE_TEXT)}},
        {"jsonrpc": "2.0", "id": 21, "method": "textDocument/completion", "params": {
            "textDocument": {"uri": nested_uri}, "position": position(nested_gap, NESTED_TEXT)}},
        {"jsonrpc": "2.0", "id": 22, "method": "textDocument/completion", "params": {
            "textDocument": {"uri": record_uri}, "position": position(record_gap, RECORD_TEXT)}},
        {"jsonrpc": "2.0", "id": 23, "method": "textDocument/completion", "params": {
            "textDocument": {"uri": top_level_in_uri},
            "position": position(nested_in_gap, TOP_LEVEL_IN_TEXT)}},
        {"jsonrpc": "2.0", "id": 24, "method": "textDocument/completion", "params": {
            "textDocument": {"uri": no_pipe_uri}, "position": position(no_pipe_gap, NO_PIPE_TEXT)}},
        {"jsonrpc": "2.0", "id": 25, "method": "textDocument/completion", "params": {
            "textDocument": {"uri": nonboundary_uri},
            "position": position(nonboundary_gap, NONBOUNDARY_TEXT)}},
        *({"jsonrpc": "2.0", "id": request_id, "method": "textDocument/completion", "params": {
            "textDocument": {"uri": interval_uri},
            "position": position(interval_gap, INTERVAL_TEXT)}}
          for request_id, interval_gap in zip((26, 27, 28), interval_gaps)),
        {"jsonrpc": "2.0", "id": 29, "method": "textDocument/completion", "params": {
            "textDocument": {"uri": invalid_ctor_uri},
            "position": position(invalid_ctor_gap, INVALID_CTOR_TEXT)}},
        {"jsonrpc": "2.0", "id": 30, "method": "textDocument/completion", "params": {
            "textDocument": {"uri": qualified_uri},
            "position": position(qualified_full, QUALIFIED_TEXT)}},
        {"jsonrpc": "2.0", "id": 31, "method": "textDocument/completion", "params": {
            "textDocument": {"uri": qualified_uri},
            "position": position(qualified_incomplete, QUALIFIED_TEXT)}},
        {"jsonrpc": "2.0", "id": 32, "method": "textDocument/completion", "params": {
            "textDocument": {"uri": qualified_uri},
            "position": position(ordinary_member, QUALIFIED_TEXT)}},
        {"jsonrpc": "2.0", "id": 33, "method": "shutdown", "params": {}},
        {"jsonrpc": "2.0", "method": "exit", "params": {}},
    ]
    done = subprocess.run(
        [java, "-Xss512m", "-Xmx2g", "-jar", jar, "lsp"],
        input=b"".join(frame(message) for message in messages),
        capture_output=True,
        cwd=cwd,
    )
    if done.returncode != 0:
        sys.stderr.write(done.stdout.decode("utf-8", "replace"))
        sys.stderr.write(done.stderr.decode("utf-8", "replace"))
        fail(HEADER_OWNER)
        fail(HEADER_COMPLETION_OWNER)
        fail(LATEST_FOR_OWNER)
        fail(NEWLINE_RECOVERY_OWNER)
        fail(NESTED_DEPTH_OWNER)
        fail(RECORD_DEPTH_OWNER)
        fail(TOP_LEVEL_IN_OWNER)
        fail(PREVIOUS_PIPE_OWNER)
        fail(BOUNDARY_OWNER)
        fail(HEADER_INTERVAL_OWNER)
        fail(SOURCE_CTOR_OWNER)
        fail(QUALIFIED_COMPLETION_OWNER)
        fail(RANGE_COMPLETION_OWNER)
        fail(SCOPE_OWNER)
        return 1

    got = replies(done.stdout)
    header_ok = True
    if "Only" not in hover_text(got.get(2)):
        header_ok = False
    if (definition_uri(got.get(3)) != lib_uri or
            range_start(got.get(3)) != position(LIB_TEXT.rindex("Only"), LIB_TEXT)):
        header_ok = False
    if "header_value: Int" not in hover_text(got.get(4)):
        header_ok = False
    if range_start(got.get(5)) != position(header_bind):
        header_ok = False
    if range_start(got.get(12)) != position(header_bind):
        header_ok = False
    if "shared: Int" not in hover_text(got.get(9)):
        header_ok = False
    if range_start(got.get(10)) != position(shared_occurrences[0]):
        header_ok = False

    source_labels = completion_labels(got.get(6))
    body_labels = completion_labels(got.get(7))
    after_labels = completion_labels(got.get(8))
    shared_labels = completion_labels(got.get(11))
    header_labels = completion_labels(got.get(13))
    range_upper_labels = completion_labels(got.get(14))
    nested_header_items = completion_items(got.get(15))
    alternative_header_items = completion_items(got.get(16))
    nested_header_labels = completion_labels(got.get(15))
    alternative_header_labels = completion_labels(got.get(16))
    recovery_header_items = completion_items(got.get(17))
    recovery_header_labels = completion_labels(got.get(17))
    recovery_source_labels = completion_labels(got.get(18))
    latest_for_ok = constructors_only(got.get(19), ("LatestLeft", "LatestRight"))
    newline_ok = general_completion(got.get(20))
    nested_depth_ok = constructors_only(got.get(21), ("NestedLeft", "NestedRight"))
    record_depth_ok = constructors_only(got.get(22), ("RecordLeft", "RecordRight"))
    top_level_in_ok = general_completion(got.get(23))
    previous_pipe_ok = general_completion(got.get(24))
    boundary_ok = general_completion(got.get(25))
    header_interval_ok = all(general_completion(got.get(request_id))
                             for request_id in (26, 27, 28))
    header_completion_ok = (
        header_labels == []
        and nested_header_labels.count("Left") == 1
        and nested_header_labels.count("Right") == 1
        and alternative_header_labels.count("Left") == 1
        and alternative_header_labels.count("Right") == 1
        and all(item.get("kind") == 20 for item in nested_header_items)
        and all(item.get("kind") == 20 for item in alternative_header_items)
        and not any(label in nested_header_labels for label in (
            "source", "choices", "outer", "header_value", "shared"))
        and not any(label in alternative_header_labels for label in (
            "source", "choices", "outer", "header_value", "shared"))
    )
    recovery_completion_ok = (
        len(recovery_header_items) > 0
        and all(item.get("kind") == 20 for item in recovery_header_items)
        and recovery_header_labels.count("RecoveryLeft") == 1
        and recovery_header_labels.count("RecoveryRight") == 1
        and not any(label in recovery_header_labels for label in (
            "recovery_choices", "recovery_outer", "recovered", "recovery_probe"))
        and recovery_source_labels.count("recovery_choices") == 1
        and recovery_source_labels.count("recovery_outer") == 1
        and "recovered" not in recovery_source_labels
    )
    source_ctor_items = completion_items(got.get(29))
    source_ctor_labels = completion_labels(got.get(29))
    source_ctor_ok = (
        recovery_completion_ok
        and constructors_only(got.get(29), ("SourceLeft", "SourceRight"))
        and "Int" not in source_ctor_labels
        and "RejectedDuplicate" not in source_ctor_labels
        and all(item.get("label") not in ("Int", "RejectedDuplicate")
                for item in source_ctor_items)
    )
    qualified_full_items = completion_items(got.get(30))
    qualified_incomplete_items = completion_items(got.get(31))
    qualified_completion_ok = (
        constructors_only(got.get(30), ("Only",))
        and constructors_only(got.get(31), ("Only",))
        and all(item.get("label") not in ("exported_value", "LocalChoice")
                for item in qualified_full_items + qualified_incomplete_items)
        and completion_items(got.get(32)) == []
    )
    range_completion_ok = range_upper_labels.count("outer") == 1
    scope_ok = (
        source_labels.count("source") == 1
        and source_labels.count("outer") == 1
        and "header_value" not in source_labels
        and "body_local" not in source_labels
        and body_labels.count("header_value") == 1
        and body_labels.count("outer") == 1
        and "body_local" not in body_labels
        and "range_value" not in range_upper_labels
        and "header_value" not in range_upper_labels
        and "body_local" not in range_upper_labels
        and "shared" not in range_upper_labels
        and "header_value" not in after_labels
        and "body_local" not in after_labels
        and "shared" not in after_labels
        and "range_value" not in after_labels
        and after_labels.count("outer") == 1
        and shared_labels.count("shared") == 1
        and shared_labels.count("outer") == 1
    )

    if not header_ok:
        fail(HEADER_OWNER)
    if not header_completion_ok:
        fail(HEADER_COMPLETION_OWNER)
    if not latest_for_ok:
        fail(LATEST_FOR_OWNER)
    if not newline_ok:
        fail(NEWLINE_RECOVERY_OWNER)
    if not nested_depth_ok:
        fail(NESTED_DEPTH_OWNER)
    if not record_depth_ok:
        fail(RECORD_DEPTH_OWNER)
    if not top_level_in_ok:
        fail(TOP_LEVEL_IN_OWNER)
    if not previous_pipe_ok:
        fail(PREVIOUS_PIPE_OWNER)
    if not boundary_ok:
        fail(BOUNDARY_OWNER)
    if not header_interval_ok:
        fail(HEADER_INTERVAL_OWNER)
    if not source_ctor_ok:
        fail(SOURCE_CTOR_OWNER)
    if not qualified_completion_ok:
        fail(QUALIFIED_COMPLETION_OWNER)
    if not range_completion_ok:
        fail(RANGE_COMPLETION_OWNER)
    if not scope_ok:
        fail(SCOPE_OWNER)
    if (not header_ok or not header_completion_ok or
            not latest_for_ok or not newline_ok or not nested_depth_ok or
            not record_depth_ok or not top_level_in_ok or not previous_pipe_ok or
            not boundary_ok or not header_interval_ok or not source_ctor_ok or
            not qualified_completion_ok or
            not range_completion_ok or not scope_ok):
        print(json.dumps(got, sort_keys=True), file=sys.stderr)
        return 1
    print("PASS  for-pattern header queries, recovery and completion scopes are exact")
    return 0


if __name__ == "__main__":
    sys.exit(main())
