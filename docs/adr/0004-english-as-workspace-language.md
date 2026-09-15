# ADR-0004: English as the workspace language

- **Date:** 2026-09-12
- **Status:** Accepted
- **Project:** workspace

## Context

An engineering team writes in at least two registers: the language it speaks in the room,
and the language it types. Letting both into the repository produces predictable damage —
identifiers half-translated, a standard whose heading is in one language and whose body is
in another, and search that finds neither.

Three forces pull towards English regardless of where the team sits. Programming languages,
libraries, and their documentation are English. The AI agents that read this workspace are
strongest in English, and a mixed-language corpus measurably degrades their retrieval. And
a team that grows, or hands a project over, cannot assume the next reader shares its spoken
language.

The counter-force is real too: some domains carry **statutory or regulated vocabulary that
does not survive translation**. Translating a regulated artefact's name into an approximate
English phrase makes the code harder to check against the regulation it implements, which
is the opposite of clarity.

## Decision

**Everything written in this workspace is in English** — documentation, code, comments,
commit messages, identifiers, ADRs, memory, and run notes.

**Exception:** domain vocabulary that is statutory, regulated, or otherwise has no precise
English equivalent may be kept verbatim in identifiers, database columns, and API enums.

That exception is deliberately constrained:

- The terms must be **enumerated in a glossary**, and the list is closed. Adding to it is a
  decision, not a convenience.
- The glossary lives in the organisation's **context repository**
  (`context/skills/<domain>/SKILL.md`), never in the framework — a term specific to one
  country's regulation is not a rule for every organisation using this workspace.
- Everything with a normal English equivalent uses it. "No good translation" means no good
  translation, not "the English word feels unfamiliar".

## Consequences

### Positive
- One language to search, review, and hand over in.
- Agents read a consistent corpus.
- Regulated terms stay checkable against the regulation that defines them.

### Negative
- Developers who think in another language write a little slower at first. Accepted: reading
  happens far more often than writing, and there are more readers than writers.
- The glossary is a maintenance surface. Kept small by the closed-list rule.

### Neutral
- Spoken language in meetings is unaffected. This ADR governs what is written down.

## Alternatives considered

| Option | Why rejected |
|---|---|
| **The team's local language throughout** | Cuts the workspace off from libraries, upstream documentation, and any future contributor who does not speak it. |
| **Full English, no exceptions** | Translating a regulated artefact's name loses its legal meaning and makes the code harder to verify against the regulation. |
| **Bilingual documents** | Two copies of every rule, which diverge on the first edit. |
| **Local language in comments, English in code** | The seam falls exactly where a reader switches context most often. |

## Follow-up

- [x] Language policy stated at the top of `AGENTS.md`
- [x] Glossaries scoped to the context repository, not the framework
