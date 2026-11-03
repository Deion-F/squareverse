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

## Sonnet helper subagents

The main thread (Opus) keeps physics design, debugging, tuning decisions and interpreting results. These Sonnet
subagents in `.claude/agents/` take narrow, well-specified jobs, and **may be used without the user asking**:

- `sim-experimenter`: runs headless experiments to a spec (scenario, what to measure, ticks, seeds, pass/fail) and
  returns raw numbers. Use it instead of writing and running measurement scripts in the main thread.
- `test-runner`: runs the suite or a subset and triages failures (actual vs expected, flaky or not, likely cause,
  stale `conftest.py` pin). Use it after changes rather than reading full pytest output in the main thread.
- `docs-sync`: brings the README / OPTIMIZATIONS.md in step with a change (names, values, keys, menu, presets). Use it
  after a change that touches anything the README quotes. It flags measured figures that may be stale; re-measure
  those with `sim-experimenter`, don't guess them.

Give each one exactly what it needs to work alone (it starts with no context). The same rules apply as for the
optimizer: if it reports the user's sim is running, ask the user (close and continue, or wait) and send the answer
back to that subagent; for runs over ~5 minutes, relay its progress updates. Check what they report before passing it
on.
