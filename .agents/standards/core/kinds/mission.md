# Definition of Done - mission

A mission is a long-running outcome that spans runs and sometimes other projects. It is
done when its outcome is met or deliberately stopped, and every run along the way is done
when it moves a milestone. This replaces the code bar for projects of kind `mission`.

## For the mission

- [ ] The outcome is written so a stranger could tell whether it was reached
- [ ] Milestones exist as tasks of kind `milestone` (`ws task add ... --kind milestone`)
- [ ] Each milestone has a measure or an observable condition, and an owner
- [ ] A review rhythm is set (weekly, monthly) with `ws remind ... --recur`
- [ ] Related projects are named in `project.md` so work done elsewhere is not lost
- [ ] Stopping criteria are written: what would make the mission not worth continuing
- [ ] On closing: the outcome, what was learned, and what stays running are recorded

## For every run

- [ ] It names the milestone it serves
- [ ] The milestone's progress is updated, not only the run's `handoff.md`
- [ ] Decisions that change the mission's scope go in `decisions.md`

## Not done

| Claim | Why it is not done |
|---|---|
| "We are making progress" | Say which milestone moved and by how much |
| "It is on track" | Name the measure and its current value |
| "It is ongoing" | A mission with no review date is abandoned |
