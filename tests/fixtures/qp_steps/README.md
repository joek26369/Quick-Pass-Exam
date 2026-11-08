# qp-steps shared conformance corpus (v1)

These are **handwritten synthetic examples**, not generated-note/BYOK acceptance.
No loops, conditionals over numeric values, assignment solver, or new expression
syntax were added. Three method families use the original design format unchanged.

## Runner contract (A2 / Skill)

- `valid-*.json` / `invalid-*.json` contain `{description, block, expected}`.
  Validate `block`, **not** the fixture envelope. `expected.valid` is mandatory.
- A valid fixture has `expected.runs[] = {inputs, choices, steps}`. Evaluate each
  run and project each returned step to `{id, value, verdicts, show?}`. Compare
  full sequence order, nulls, matched verdict texts, matrices and highlights.
  Numeric tolerance: `abs(a-b) <= max(1e-12, 1e-12*abs(b))`; never compare NaN.
- An invalid fixture has `expected.error_code`. Python emits `CATEGORY: detail`;
  JS must reject it too (matching the category is recommended, prose is not a
  compatibility contract). JSON Schema alone cannot reject semantic failures.
- `basis-hash.json` is a separate hash-vector envelope: each `cases[]` contains
  `web.{method,formulas_section}`, `skill.{title,formula}`, and `expected` hash.
  Both pairs are **plain text**, not Markdown parsing instructions.

Python API: `validate(block) -> (bool, list[str])`,
`evaluate(block, inputs=None, choices=None) -> list[dict]`,
`basis_hash(method, formulas_section) -> str`. Runtime failures raise
`QPStepsError(ValueError)`. Python module is a **standalone stdlib-only file**:
no resource lookup, repository path or JSON Schema library. JSON Schema is kept
separately for JS/external tooling. Install only pytest to run the main tests;
one optional external-schema test additionally uses jsonschema when available.

## Deterministic semantics

- Numeric values are finite IEEE-754 binary64, never booleans/strings. Decimal
  literals support `.5`, `2.`, `1e-3`. No implicit multiplication or coercion.
- Grammar: sum -> product -> unary -> power -> primary. Power is right-associative;
  `-2^2 = -4`, `2^-2 = .25`. Whitespace may separate tokens, not split a token.
- Calls: sqrt/abs/ceil/floor/ln take one argument; min/max take one or more;
  `round(x,n)` takes exactly two. Its precision is an integer in [-308,308],
  scaled ties round toward +infinity (NOT Python bankers rounding). Reject any
  intermediate/final overflow/domain error, including a non-finite scaled round.
- `digits` is display-only (0..15, default 2), never rounds the calculation chain.
- All ids use the design's 24-character ASCII pattern. Also reject Object.prototype
  names (constructor, prototype, __proto__, toString, valueOf, etc.). Input and
  step namespaces are shared; choice ids cannot collide with either namespace.
- A `when` object is a conjunction of choice-id/option-id pairs. Duplicate step
  ids need pairwise contradictory shared choice keys. Validate **every Cartesian
  combination**, not just defaults or one option at a time. Missing definitions
  along a selected path are errors. Guard: >4096 combinations fail closed as
  `SIZE` (explicit CPU bound, no silent sampling).
- `evaluate` first validates the whole block, then the requested run. Missing
  inputs/choices default to examples/defaults. Reject unknown/inactive ids,
  illegal choices, non-finite numbers, and out-of-bound inputs. An active inline
  step input uses its **step id** as the caller's input key (`ETC` in the example).
- `trace` rejects inputs different from its fixed examples; it is NOT a solver.
  A pure explanation step has `expr: ""`, returns `value: null`, and does not
  define a numeric variable. It cannot have numeric verdicts. `show.table` is a
  rectangular numeric matrix; **every string cell is an expression**, not a label.
  A table is evaluated after the current step, so it may use that step's value.
  Highlight pairs are zero-based `[row,column]` within the table.
- Returned steps retain metadata and add `value`, default `digits`, and replace
  `verdicts` with an array of **all matching text strings**, in declaration order.
  Table expression strings become numbers. Evaluation does not mutate the block.
- `verdicts.test`: one of `< <= > >= =` followed immediately by a finite signed
  decimal/scientific constant. No variable references, `==`, boolean operators,
  or embedded spaces. Verdicts do not change later computation.
- Size is <=65536 bytes of UTF-8 compact JSON (`ensure_ascii=False`, separators
  `,`/`:`), <=40 input ids (top-level plus unique inline step inputs), <=80 steps.
  Ingestion must additionally bound
  raw text before JSON parsing; this API receives already-decoded objects.
- Provenance requires generator webapp/skill, source_questions[], ISO timestamp
  with timezone, lowercase 64-hex basis_hash. `validate` checks shape, not freshness:
  caller compares `basis_hash` to the current source text before publication/use.
- Hash: normalize each text's ECMAScript whitespace runs to one ASCII space,
  trim resulting spaces, join **method + LF + formula text**, UTF-8, SHA-256.
  No heading removal, Markdown/LaTeX rewriting or Unicode normalization happens
  inside this function. Thus Web section body and Skill formula hash identically
  when their plain text is the same. `abc` + LF + `def` has pinned test coverage.

## Teaching cases

1. `valid-earned-value`: CV/SV/CPI/SPI, four ETC assumptions (typical, atypical,
   CPI*SPI, reestimate via inline input), then EAC; includes edited-input run.
2. `valid-pert`: weighted expected duration, standard deviation, variance; two runs.
3. `valid-static-payback`: `N-1+abs(PREV)/CF`; two runs. `N` is the **known first
   nonnegative cumulative-cashflow year**, PREV the previous year's cumulative
   amount, CF that year's cash flow. Finding that year from an arbitrary series
   remains the user's preparation step, not a numeric branch hidden in the DSL.
4. `valid-hungarian-trace`: fixed 3x3 costs, row/column reductions, two-line zero
   cover, uncovered minimum adjustment, independent zeros and original cost 5.
   The test independently enumerates all assignments to verify the minimum.
5. `valid-expr-*`: precedence, scientific literals, function whitelist, round ties
   and large integer precision. These are conformance vectors, not extra methods.

Invalid cases cover undefined/forward references (including tables), unknown
functions, prototype/constructor ids and references, long expr, divide-by-zero
(including nondefault branch), invalid verdict/when, overlapping/missing branch
definitions, negative sqrt, overflow, 41 inputs, 81 steps and >64KB.

Run: `bash run.sh -m pytest -q tests/test_qp_steps.py`.
