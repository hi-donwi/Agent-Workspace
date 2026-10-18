# Definition of Done - research

A research project is done when someone who was not there can read the result and know how
far to trust it. This replaces the code bar in `../definition-of-done.md` for projects of
kind `research`; the architecture-decision and secrets rules there still apply.

## For every research run

- [ ] The question is written down, with what would change as a result of the answer
- [ ] The method is stated: what was searched, read, run, or measured, and what was left out
- [ ] Every claim that matters names its source, with a date or version where it can change
- [ ] Findings separate what was observed from what was inferred
- [ ] Each conclusion carries a confidence (high, medium, low) and the reason for it
- [ ] Contradicting evidence is reported, not dropped
- [ ] Open questions and known gaps are listed
- [ ] The result ends in a recommendation, a decision needed, or an explicit "no conclusion"
- [ ] No secrets, personal data, or client documents are quoted; raw material stays in `.local/`
- [ ] The run's `handoff.md` is updated and the headline finding is in the project's `active.md`

## Not done

| Claim | Why it is not done |
|---|---|
| "I read a lot about it" | Reading is not a finding; the finding and its source are |
| "The top search results agree" | Agreement among copies of one source is one source |
| "It seems to work" | State the test and the result, or the confidence is low |
| "More research is needed" | Say which question, and what it would cost to answer |
