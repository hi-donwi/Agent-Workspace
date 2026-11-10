# ADR-0026: Source-linked localization

- **Date:** 2026-11-09
- **Status:** Partially superseded by [ADR-0027](0027-language-default-not-mandate.md); source,
  freshness, and access-boundary safeguards remain in force for derived translations.
- **Decider:** Workspace owner
- **Partially supersedes:** [ADR-0004](0004-english-as-workspace-language.md)

## Context

English remains useful for consistent engineering work and a searchable canonical corpus.
Some readers need an interface or explanatory material in another language. ADR-0004
prohibits those localized assets, even when they are explicitly derived and cannot replace
the authoritative source. Unlabeled duplicate decisions would create a real divergence risk.

## Decision

Keep English for engineering sources, canonical documents and commit messages. Permit
localized user-facing interface text and clearly labeled, source-linked derived translations
in the languages their readers need. Engineering identifiers, comments, tests, agent rules,
canonical specifications and decisions remain English. Technical identifiers and the
meaning of status and approval must not change in translation.

An owner must identify the authoritative source, source version or equivalent freshness
evidence, translation status and responsible privacy boundary. If the source changes or
freshness cannot be established, the translation must not be silently represented as current.
The original remains available and authoritative. Project-specific translations follow the
source project's access rules; private content never belongs in this public framework.
Translation does not authorize external processing or publication.

## Consequences

### Positive

- Readers can use localized interfaces and explanations without changing canonical facts.
- Source, approval status and freshness remain explicit for people and agents.

### Negative

- Owners must maintain and review translations and surface stale or missing versions.
- Search across languages requires additional design; a translation is not a guaranteed match.

### Neutral

- Language selection, document mapping and machine-translation providers remain separate
  product decisions; this policy alone does not implement them.

## Alternatives considered

| Option | Reason not chosen |
|---|---|
| English only for every artifact | Does not meet readers' legitimate language needs. |
| Independently authoritative versions | Multiplies decision sources and permits silent contradictions. |
| Unreviewed automatic cloud translation | Risks private-data disclosure and inaccurate business or security semantics. |

## Follow-up

- [x] Update the canonical and mirrored hard rules.
- [x] Align the private visual-guide skill and local user preference with the exception.
- [ ] Product owners specify and implement locale selection, freshness, fallback and tests.
- [ ] Teams review and maintain any localized material under the correct access boundary.
