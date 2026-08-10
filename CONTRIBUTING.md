# How work gets done in this repository

*[中文版](CONTRIBUTING.zh-CN.md)*

This file covers one thing: **how a feature travels from an idea to code**.

Commit format, running the tests, code style: a generic template already has all
of that, and CI holds it anyway (`./bin/dawn test selfhost`,
`./bin/dawn test compiler-plan`,
`./bin/dawn fmt compiler-plan std site selfhost packages examples --check`, the
golden differentials), so writing it down changes nothing. What follows is the
part no machine holds and that is still worth writing down. It is not theory. It
is what eight design documents under `docs/` actually did.

## 1. Before writing code, write `docs/<feature>-design.md`

Not a ritual. **Writing a plan down kills some of them**, and killing a plan in
the editor is far cheaper than killing it after a 4,000-line diff. A draft
declares its own status at the top so a reader does not have to guess:

> 动码前的**调研与方案**，不是设计定稿。
>
> (Investigation and proposal, before any code. Not a settled design.)

A draft looks roughly like this (see
[`docs/unwrap-design.md`](docs/unwrap-design.md)):

| Section | What goes in it |
|---|---|
| Problem | Where it hurts **today**, concretely. Real code, not adjectives |
| Post-mortem of the previous plan | Why the last idea does not work, **measured if at all possible** |
| Plan | The one you are going to do |
| Why X was not fixed along the way | Draw the boundary. This is what stops scope creep |
| Syntax and conflict analysis | Where new syntax collides with what is already there |
| Landing points | Which files move, which tests are added |
| **Not doing (with reasons)** | See below. The easiest section to skip and the one to skip least |

## 2. Investigation may overturn its own premise, and that is a success

[`docs/seq6-research.md`](docs/seq6-research.md) is the most valuable thing this
process has produced. It was sent to do "value-type specialization" and found,
by measuring, that **the retro's description of the problem and the state of the
code were materially different**: what hurt was materialization, not boxing, and
the original plan saved nothing at all in the main scenario. Sequence 6 was
shelved, and what that bought was several thousand lines nobody had to write.

So: **every number in a draft names its source**. "The body of one article is a
million boxed `Int`s" sounds convincing; measured, it does not hold in ASCII at
all (`Long.valueOf` caches `-128..127`). An unmeasured performance claim does not
go into a draft, and certainly not into the README: `README:99` carried the
sentence "the native binary starts in about 7ms" with no harness behind it,
until `seq6-research.md` caught it in passing.

## 3. "Not doing (with reasons)"

Every draft ends with this section. Its job is to **stop you from having the
same idea again in three months**, which matters most when the idea looks
obvious and the reason it was rejected does not. "Why the `Option` wrapper stays
(and was not removed along the way)" in `unwrap-design.md` is one of these.

## 4. When it is implemented, write back

A draft is not something you write and throw away. Once it lands:

- A large change gets a `docs/history/m<N>-progress.md`: one line of status per
  item, **with the commit hashes filled in**, and a note saying it exists to be
  picked up after an interruption (see
  [`docs/history/m7-progress.md`](docs/history/m7-progress.md)). Cross-repository
  work records both hashes: the language itself is in `dawn-lang/`, the backend
  in `dawnop-site/backend-dawn/`.
- **Go back and fix the draft** wherever reality overturned one of its premises.
  Leaving it is leaving a lie.
- A finished milestone gets a `docs/history/m<N>-retro.md`: a post-mortem plus a
  priority table for the next batch of fixes. The table in
  [`docs/history/m6-retro.md`](docs/history/m6-retro.md) became sequences 1 to 6
  of M7 directly.

> Historical hashes expire. This repository rewrote its history once to strip
> trailers, and a commit afterwards went back and repaired the 11 references in
> the documentation that this had invalidated. Keep that in mind when filling
> hashes in.

## 5. Commit messages

One line, English, imperative, no `type(scope):` prefix. The code, the comments
and the commit messages in this repository are English; `docs/` is Chinese. The
body carries **what reading the diff will not tell you**: the root cause, the
plan that got overturned, the measurements, how it was verified. Not "what
changed", which is what the diff is.

When you **change the toolchain's output** (emitted bytecode, C text, CLI text,
formatting results, LSP responses), the body carries **one line per check label
you moved**: `Emit-Change(<label>): <what and why>`. The label is the check name
the differential scripts print (`emit selfhost`, `emit packages/json`,
`run calc (args)`, `fmt`, `lsp`) and it must appear verbatim in
[`scripts/emit-labels.txt`](scripts/emit-labels.txt).
`selfhost-prev-diff.sh` / `run-diff` / `fmt-diff` / `lsp-diff` compare HEAD
against the previous tag, and **a difference with no matching declaration is a
red build** (REL-02, `scripts/emitchange.sh`).

> **Wildcards are not accepted, and neither is a bare `Emit-Change:`** (#124).
> `emit *` exempts **labels that do not exist yet**, so one commit message goes
> on permitting more and more as the corpus grows; and the commonest historical
> spelling of a bare `Emit-Change:` was `Emit-Change: none`, where the author
> meant "nothing changed" and the effect was to permit **every** label of
> **every** differential. If the change really moved six corpora, write six
> lines: the v0.48.0 class-file version change did exactly that, and six lines
> was the whole price. A declaration that will not parse, and a label
> `emit-labels.txt` does not know, are errors rather than rules that can never
> match.
>
> One trap has not changed: the script reads the declarations across the
> **whole span from the last tag to HEAD**, not per commit. So one declaration
> in that span shields every later difference carrying the same label.
> **Run the gate first, write the line second**, or the green you are looking at
> is somebody else's declaration. #124 closed the half where a label nobody had
> ever seen got exempted; the other half, a difference under an existing label
> growing, can only be closed by putting golden snapshots in the repository. It
> is recorded as REL-02 in `docs/codebase-audit.md` and it is not done.

**Never add a Claude attribution** (no `Co-Authored-By`, no `Claude-Session`).
This project is held to open-source standards.

## 6. Contracts: do not change them unilaterally

The production service of the [`dawnop-site`](https://github.com/dawnop/dawnop-site)
backend runs on code this compiler produced. It pins a release through
`.dawn-version`, so:

- a breaking language change ships as a tag first, and that repository then
  raises `.dawn-version` in a commit of its own;
- while both sides are being changed together it may write `main` into
  `.dawn-version` and compile from source, but **it must not sit on main for
  long**: there is no reproducibility during that window.

Releasing: change `VERSION` in `selfhost/src/version.dawn` **and `std/VERSION`**
(the release stamp the `std` directory puts on itself, which is how the compiler
recognizes "this std is not the one I shipped with"; see `driver/stdlib.load_std`.
When the two disagree, the `std/ stamps itself with this toolchain's version`
test in `driver/stdlib` goes red) → commit → `git push origin main` and wait for
main CI → `git tag v0.9.0` → `git push origin refs/tags/v0.9.0`. Never
`git push --tags`; it publishes unrelated tags along with it. `release.yml`
checks the tag against the version, runs the full test suite, and uploads
`dawn-selfhost.jar` and the native assets to the Release. Only once all four
assets are published, run `./scripts/advance-seed.sh v0.9.0`. It validates the
GitHub Release JAR and the std in the remote tag archive, then advances the three
seed files in order (digest manifest, std manifest, pointer); hand-editing
`seed-release.txt` alone is not allowed (the full protocol is in
docs/bootstrap.md). `doc-check.py` also holds every place in the documentation
that claims "the current toolchain is N" against `version.dawn`, so the CI run
after a `VERSION` change names the lines that did not keep up. The sentence in
README was once 38 minor versions behind, and a human found it.

## 7. Name families: the admission test for `std`

An audit (`docs/audit/re-audit-2026-07-30.md`, RD-06) counted four names for
length, an emptiness test that existed in exactly one module with no callers,
and five naming conventions for conversion. What follows is the **admission
test** that cleanup left behind. It is not a historical record: check a new
`pub` name in `std` or in a package against it.

- **One concept, one name.** Length is `len`, emptiness is `is_empty`, and
  `str`/`list`/`map`/`set`/`bytes` spell both identically. There are exactly two
  named exceptions, both on `Buf` and both for the same reason (Dawn has no
  overloading, and the `Bytes` side got the right name first):
  `bytes.size(b: Buf)` yields to `bytes.len(b: Bytes)`, and
  `bytes.buf_at(b: Buf, i)` yields to `bytes.at(b: Bytes, i)`. An exception
  **says why in the code**, or the next person copies it as a convention. Which
  side yields is part of the test too: **moving the right name out of the way to
  make room for the wrong one is backwards**. `bytes.at` is already correctly
  named under the three criteria below, so the side that got renamed was `Buf`.
- **A name says what happens when you go out of bounds (spec §4.8, three
  criteria).** This was the sole basis for the v0.54.0 / v0.55.0 renames, and it
  puts `at`, `get` and the range functions each in one bucket:
  - **Criterion 1 (assertion, panics)** is spelled `at` and `[]`: the argument
    is a **position**, the caller asserts it exists, and out of bounds is a bug.
    `str.at`, `bytes.at`, `pvec.index` / `nth`.
  - **Criterion 2 (question, `Option` / `Bool`)** is spelled `get`: out of
    bounds or absent is a normal branch the caller handles. `list.get`,
    `map.get`, the `index_of` family.
  - **Criterion 3 (clamping, never panics)** is the range functions: `slice`,
    `take`, `drop`, `seek`. The argument is a **range or a landing point**, it
    asks for "whatever part of this stretch exists", and it asserts nothing
    about the endpoints.

  One name **cannot carry two policies**. `cursor.at` used to clamp while
  `str.at` panicked, so the meaning of one word depended on which module the
  reader was in; that is not a tradeoff but a defect, and the fix is a rename
  (`cursor.at` → `cursor.seek`) rather than unifying the two under one policy,
  because each of the two was right on its own. `bytes.get(b: Buf, i)` is the
  same defect from the other side: it panics, under a criterion 2 word.
- **A breaking rename goes through a one-generation forwarder.** The new name
  and the old ship together, the old demoted to a one-line forwarder whose doc
  comment says "removed in the next version"; the next release is when the old
  name goes and the call sites move. The reason is mechanical: stage 1 of
  `bin/dawn` compiles today's `selfhost/src` with **the std the seed carries**
  (see the comment in the script), so selfhost call sites **must** be one
  generation late. A rename done in one go is red at the first step of the
  bootstrap. Precedents: RD-06's `of_array`, and this batch's `str.slice` /
  `cursor.seek` / `bytes.buf_at`.
- **Conversions are `to_X` / `from_X`.** `to_hex`/`from_hex`,
  `to_base64`/`from_base64`, `to_array`/`from_array`, `to_list`. A domain verb
  survives only where **the name itself carries the meaning**: `bytes.freeze` is
  "end the extension contract of a `Buf`", not "convert to Bytes", and
  `bytes.utf8` names an encoding rather than a target type. The test is "does
  rewriting it as `to_X` lose a sentence?" If it does, keep the verb.
- **Insert and remove are spelled per container kind.** Keyed containers get
  `insert` / `remove` (`map`, `set`); constructors that only append at the end
  get `put` / `push` (`bytes.Buf`, `Array`). Not both in one module.
- **A representation is an internal module.** `std/hamt` and `std/pvec` hold the
  representation of `Map`/`Set`/`List`, and a `use` of them from outside `std` is
  a compile error (`checker.internal_std_modules`). The test is "would replacing
  this implementation break somebody's program?" If it would, it should not have
  been public. The same test is harder inside a package, where a `pub` name is
  backed by a version number (RD-12).

## 8. Outward-facing copy: English first

The code, the comments, the diagnostics and the commit messages in this
repository are English, and `docs/` is Chinese. Neither of those has changed.
What changed is the **outward layer**:

- **`README.md` is the original**, in English. `README.zh-CN.md` is its
  translation.
- **This file is the original**, in English. `CONTRIBUTING.zh-CN.md` is its
  translation. It joined the outward layer late, and the reason it was missed is
  worth naming: the scope used to be drawn as "everything the website renders",
  which is a good proxy for "documents a stranger reads" everywhere except here.
  GitHub renders this file to every would-be contributor, and it was the one
  document where the proxy and the thing it stood for disagreed.
- **The site serves English at `/`** (`site/pages/home.md`) and Chinese at
  `/zh/` (`home.zh.md`).
- **The tutorial and the standard library introduction** are likewise English
  originals with Chinese translations.
- **The specification and the design notes run the other way**: Chinese is the
  original, English the translation (`spec.en.md` / `design.en.md`). They are
  living documents, edited in Chinese by every change to the language, and
  making English the original would require writing each language change in
  English first. A rule that expensive gets skipped, and once it is skipped the
  rot is back on the side nobody looks at.
- The rest of `docs/` (design proposals, plans, landing logs) is **Chinese only
  and not translated**. Every face of the site says so on its front page.

**When you change outward-facing copy, change the English first, then the
Chinese translation.** A translation carries
`<!-- doc-check: translation-of <original> @ <digest> -->` at its head;
`scripts/doc-check.py` computes the original's digest and compares. The English
moving without the Chinese following is a red build. The registry is
`TRANSLATIONS` in that script, and **a missing digest is not an absent check**:
deleting the marker is red as well.

Why the outward layer runs in this direction: the derived copy is the one that
rots, and most readers of the outward layer do not read Chinese. Making English
the derived copy would hide the rot on the side that is read the most and
proofread the least. The other way round the rot lands on the Chinese, whose
reader is the author. The only cost is that the author thinks in Chinese, which
is why this rule does not rely on memory but on the gate above. **The
specification and the design notes are precisely the pair where that cost
outweighs the benefit, so their original stays Chinese, and the gate watches
both ends either way.**

What the digest counts and what it does not (re-wrapping a paragraph is not a
change, a code block counts line by line, version numbers do not count, because
`check_version` already holds both sides independently) is written in the
comments on `translation_digest`. **There is no "the translation is behind"
exemption**: an exemption that can stay open forever is the same as no gate.
