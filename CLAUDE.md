# Squareverse

## Optimization subagent

The `sim-optimizer` subagent (`.claude/agents/sim-optimizer.md`) is in charge of performance, but it is slow and
thorough (a run takes half an hour or more), so it runs **only when the user types `/optimize`**
(`.claude/commands/optimize.md`). Don't start it on your own, not even after physics changes or when something
looks slow; you can suggest `/optimize` to the user instead.

When it runs, tell it what changed (files, functions or a diff range) and what the change is meant to do. Then pass
its before/after numbers and any trade-offs on to the user. If it reports that the user's sim is running, ask the
user whether it may close the sim and continue, or should wait until they close it and confirm. Send the answer
back to the same subagent (SendMessage) so it carries on where it stopped; it closes the sim only once told the user
agreed.
