# Named traversal contract

**Recorded:** 2026-08-25
**Status:** experimental boundary

## Property

A named traversal is a versioned, bounded and deterministic graph-context
procedure. Agents, UI and tests can refer to a stable identity such as
prepare_topic_edit@2 and receive a graph-version-bound execution receipt.

Named traversal does not decide what a question means and does not call a
model. An agent may also author an ephemeral traversal for a one-off task.

## Separation

1. Orientation is advisory: where an agent might begin.
2. Traversal is deterministic selection: what graph context is returned.
3. Workflow is authority: when a fresh receipt is required before another
   harness action.

A receipt proves only that the declared program ran against the named graph
version. It cannot prove the host read or obeyed natural-language instructions.

## Recipe identity

A recipe declares:

- stable name and monotonic version
- purpose and typed parameters
- deterministic steps and collection rules
- execution limits and empty-result meaning
- output projection
- fixtures

The fingerprint binds canonical recipe bytes, graph binding and the primitive
contract version. The current graph-local graph.md loader remains a
compatibility storage seam for recipes; it is not a domain-format product
model. Recipe storage should move only after two unrelated workbook-built
graphs prove the protocol.

## Portable operations

- starts: lookup, search, select_landmarks
- movement: expand, traverse, shortest_path, find_paths, walk_sequence
- sets: union, difference, intersection
- shaping: filter, sort, limit, project

Every operation is explicitly bounded. Search never silently replaces an exact
miss. Breadth-first traversal is the default for context gathering; depth-first
must be requested explicitly.

| op | principal arguments |
|---|---|
| lookup | references |
| search | query, limit |
| select_landmarks | roles, include_pinned, limit |
| expand / traverse | from, predicates or SST types, direction, depth, bounds |
| paths | from, to, max_hops, direction, exclusions |
| walk_sequence | from, ordered predicates or SST types, cycle policy |
| union | of, optionally with |
| difference | of, minus |
| intersection | of, with |
| filter / sort / limit | of plus operation fields |
| project | from |

Every step may assign a variable; later steps refer to it as $name. Domain
predicates are data supplied by the graph, not a bundled vocabulary.

## Deterministic conditions

A bounded branch may depend only on visible execution metadata: empty/non-empty,
result count, truncation, exact misses, path found, or presence of a declared
kind or predicate. Portable recipes exclude LLM judgement, network calls,
mutation, free-form code and unbounded loops.

The agent can write arbitrary code around traversal. The recipe itself remains
restricted because that is what makes it reusable, inspectable and safe to run
inside the host.

## Result semantics

Every result distinguishes:

- exact miss
- ranked candidates
- bounded completed empty
- truncated or timed-out execution
- invalid parameter or recipe

A receipt records canonical parameters, recipe and graph fingerprints, limits,
executed steps, branch decisions, truncation and result fingerprint. The same
recipe, parameters and graph version must produce the same structural result.

## Fixtures and change

A named recipe is accepted only with fixtures that demonstrate a useful result,
a meaningful empty result and relevant bounds. A recipe version may be
optimized without semantic change only when fixtures and canonical receipts
remain equivalent. Otherwise it receives a new version.

## Non-goals

- a general programming language
- hidden semantic widening
- model calls inside traversal
- mutation or publication
- proof that retrieved context is sufficient or true
