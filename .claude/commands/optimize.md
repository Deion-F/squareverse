---
description: Run the sim-optimizer subagent on recent changes (slow and thorough; only on request)
argument-hint: "[what to optimize: files, functions or a commit range; default: changes since the last optimizer run]"
---

Run the Squareverse `sim-optimizer` subagent (`.claude/agents/sim-optimizer.md`; Agent tool, `subagent_type:
"sim-optimizer"`). If that agent type isn't available in this session, start a general-purpose agent and tell it to
read that file first and follow it exactly.

What to hand it: $ARGUMENTS

If that is empty, hand it the changes since the optimizer last ran (check `git log` and `OPTIMIZATIONS.md`), or the
uncommitted changes, and say what each change is meant to do. Include any timings you already have.

While it runs:

- Ask it in the spawn prompt to send a short progress report to "main" about every 5 minutes, and set up the
  5-minute check-in (see memory: request subagent updates every 5 min). Relay each update to the user in a couple of
  lines.
- If it reports that the user's sim is running, ask the user whether it may close the sim and continue, or should
  wait until they close it and confirm, and send the answer back to it (SendMessage).

When it finishes, pass on its before/after table, what it changed (file:line), the test results and any risks. It
doesn't commit; leave committing to the user.
