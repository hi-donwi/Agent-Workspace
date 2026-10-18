# Definition of Done - ops

An ops project is recurring or operational work: administration, maintenance, an account, a
checklist that repeats. It is done for a run when the system is left in a known state and the
next run can start from the record. This replaces the code bar for projects of kind `ops`.

## For every ops run

- [ ] What was done is listed, in the order it was done, with the result of each step
- [ ] The state afterwards is stated: what is now true that was not before
- [ ] Anything that could not be completed has a reason and an owner
- [ ] Steps that will repeat are written as a checklist in the project's `project.md`
- [ ] Deadlines and renewals found along the way are tasks or reminders, not memory
- [ ] No credentials, account numbers, or personal data are recorded; they stay in `.local/`
      or the system that owns them
- [ ] The run's `handoff.md` is updated

## Not done

| Claim | Why it is not done |
|---|---|
| "Handled" | Say what was done and how it was verified |
| "I will remember the renewal" | Put it in `ws remind` |
| "Same as last time" | Then last time's checklist exists; if not, write it now |
