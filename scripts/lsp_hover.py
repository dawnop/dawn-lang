"""The code a `textDocument/hover` reply shows: one helper for every contract.

A Dawn hover is markdown: one ```dawn fence holding the type, value or
signature, and, when the declaration has a `##` doc, a `---` rule and the
doc's own markdown after it (docs/lsp-hover-design.md §A3). The contracts
here assert on the fence. They used to read the reply by deleting every
``` and comparing what was left, which held only while the fence was the
whole reply: a doc comment on the probed declaration would have turned a
right type into a failed contract, and a doc that happened to contain the
expected text into a passing one. Reading the first fence answers both.

Imported by path (`sys.path` gets this directory), so it is a module name
with an underscore, unlike the hyphenated scripts beside it.
"""

import re

_FENCE = re.compile(r"```dawn\n(.*?)\n```", re.S)


def hover_value(result):
    """The reply's markdown (or plain) text; "" for no hover."""
    if not isinstance(result, dict):
        return ""
    contents = result.get("contents")
    if isinstance(contents, dict):
        value = contents.get("value", "")
        return value if isinstance(value, str) else ""
    if isinstance(contents, str):
        return contents
    return ""


def hover_code(result):
    """The first ```dawn fence of a hover reply, without the fence lines.

    A reply with no such fence (a plain-text server, a fake) is returned
    whole, so a contract against one still reads what it was sent.
    """
    value = hover_value(result)
    m = _FENCE.search(value)
    return m.group(1) if m else value


def _selftest():
    plain = {"contents": {"kind": "markdown", "value": "```dawn\nfn f() -> Int\n```"}}
    assert hover_code(plain) == "fn f() -> Int"
    documented = {"contents": {"kind": "markdown", "value":
        "```dawn\nfn f() -> Int\n```\n\n---\n\nReturns `1`.\n\n```dawn\nf()\n```"}}
    assert hover_code(documented) == "fn f() -> Int"
    two_lines = {"contents": {"kind": "markdown", "value": "```dawn\nInt\n0xFF = 255\n```"}}
    assert hover_code(two_lines) == "Int\n0xFF = 255"
    assert hover_code({"contents": {"kind": "plaintext", "value": "Int"}}) == "Int"
    assert hover_code({"contents": "Int"}) == "Int"
    assert hover_code(None) == "" and hover_code({}) == ""


if __name__ == "__main__":
    _selftest()
    print("OK: lsp_hover (6 cases)")
