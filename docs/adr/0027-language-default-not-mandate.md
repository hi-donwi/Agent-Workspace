# ADR-0027: English as a default, not a requirement

- **Date:** 2026-11-09
- **Status:** Accepted
- **Decider:** Workspace owner
- **Supersedes:** The mandatory-English portions of [ADR-0004](0004-english-as-workspace-language.md)
  and [ADR-0026](0026-source-linked-localization.md)

## Context

English remains useful for shared engineering work and is a practical default when no
language has been selected. A mandatory-English rule, however, prevents a project owner from
choosing the language that best serves its readers. Source-linked translation safeguards
remain useful when a translation is derived from a separate authoritative document, but they
should not force every project to maintain English as its canonical source.

## Decision

English is the default for engineering sources, canonical documents, and commit messages only
when the user or project owner has not specified another language. An explicit choice may make
another language the canonical language for the relevant repository and its documents.

Preserve code identifiers, API names, exact quoted source labels, and other technical literals
unless the project explicitly controls them. When a document is a derived translation of a
separate authoritative source, identify the source, source version or freshness, translation
status, and access boundary. A document written directly in the selected project language is
not required to carry a duplicate English version.

This policy does not permit private project content to enter the public framework, authorize
external translation services, or make a draft schedule or translation an approved decision.

## Consequences

### Positive

- Projects can choose a language that serves their actual readers.
- English remains a consistent starting point when no language preference exists.
- Derived translations retain provenance and privacy controls without requiring duplicate
  authoritative documents.

### Negative

- Cross-project searches may span more than one language.
- A project that chooses a non-English canonical language must maintain its own terminology
  and ensure agents have clear language instructions.

### Neutral

- Code symbols, API contracts, proper names, and source-system labels may remain in their
  original form where translation would damage precision.

## Alternatives considered

| Option | Reason not chosen |
|---|---|
| Mandatory English for every written artifact | Prevents project owners from serving their readers in the selected language. |
| Require bilingual copies for every project | Duplicates authoritative content and increases drift without a demonstrated need. |
| Translate private content through an external service by default | Risks privacy breaches and semantic errors; external processing requires separate authorization. |

## Follow-up

- [x] Update canonical and mirrored workspace language rules.
- [x] Record the policy in workspace project memory.
- [ ] Projects selecting a non-English language state it in their own context instructions.
