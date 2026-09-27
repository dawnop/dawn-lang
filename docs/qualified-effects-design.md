# Module-qualified effects

> Status: current. Implementation and validation for issue #145.

## Problem and decision

An aliased module already exports effect identities, but `!dep.Ask` stops at
the dot. Merely accepting that dot is insufficient: row resolution treats every
dotted name as an associated projection, declaration validation mistakes a
lowercase qualifier for an effect variable, and handlers and ground bindings
have separate bare-name lookups.

Accept `alias.Effect` wherever a declared effect can be referenced. The alias
must denote a whole-module import and the member must be a public effect.
`T.E` remains an associated projection; `e` remains an effect variable.
An unresolved qualified name never introduces a variable.

## Implementation

- Centralize effect-name classification without migrating the entire AST.
- Resolve qualified declarations through `ModExports.effects`, retaining the
  provider's ID and canonical label. Do not introduce unqualified imports.
- Use this lookup for rows, handler selectors, and associated-effect ground
  defaults/bindings. A qualified declaration still occupies one evidence slot;
  variables, projections, and unions remain forbidden in ground bindings.
- Record successful and failed qualified queries and diagnostic answers for
  incremental revalidation. Compare incremental analysis with cold analysis.
  （2026-09-27：读取日志与候选重验已随增量切片拆除，这一条只剩历史意义；见
  [incremental-semantics-removal.md](incremental-semantics-removal.md)。）
- Cover formatting, effect-position completion, editor tokenization, grammar,
  and both specification files. Public additions are in English.
- Verify the existing JVM/native and Core golden contracts; no runtime ABI or
  evidence-model change is intended. No performance improvement is claimed.

## Acceptance

Same-provider aliases and selective imports must resolve to the same identity;
different providers' same-named effects must remain distinct. Tests cover all
reference positions, visibility and wrong-kind errors, alias retargeting,
declaration removal, and operation-signature changes. Existing associated
projections and effect-variable binding rules must remain unchanged.

## Not doing (and why)

- Multi-segment paths and module-qualified associated projections: unnecessary
  for parity with current module-qualified types and a separate language choice.
- Effect re-exports, effect type parameters, or new binding forms: these change
  the effect system rather than how an existing declaration is named.
- Whole-AST span migration or a general namespace rewrite: the existing export
  tables and effect identity model already provide the required semantics.
- General effect-annotation hover/definition indexing: row atoms currently
  carry strings without individual source spans. This change supplies qualified
  completion and highlighting, not a new reference-index representation.
- Automatic golden acceptance: output changes must first be inspected.
