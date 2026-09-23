# ADR-0015: Synthetic agent evaluation

- **Date:** 2026-09-23
- **Status:** Accepted
- **Deciders:** Workspace maintainer
- **Project:** workspace

## Context

Agent workflows need regression evidence across skill, policy, and tool changes. Invoking a
model or provider from public CI would be nondeterministic, may incur cost, and risks sending
private fixtures outside the workspace. A hypothetical response is not execution evidence.

## Decision

The framework provides `ws eval validate` for scenario structure and `ws eval compare` for
comparing separately recorded observations against expected skills, actions, and artifacts.
Scenario catalogs use synthetic requests and fixtures. Expected outcomes are kept in the
scoring record and are not required to be supplied to an evaluator during an external run.

The runner never invokes a model, provider, external tool, or product repository. It rejects
scenario and observation files located under `projects/`. Missing observations are reported as
`not-run`; missing expected skills, actions, or artifacts are `findings`; only complete matches
are `pass`.

## Consequences

- Public CI gets deterministic structural and replay comparison checks.
- Model execution remains an explicitly authorized, separately recorded operation.
- Evaluation fixtures can be shared publicly when they contain no client, project, credential,
  or operational identifiers.
- A passing comparison proves only that the recorded observation satisfied the declared
  expectations; it does not prove the model's runtime security or reproducibility.
