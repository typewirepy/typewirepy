# Agent guidelines

- `docs/projects/` holds internal working briefs: never copy, quote or summarise them into public docs (`README.md`, `CHANGELOG.md`, `docs/*.md`, docstrings), and keep them out of the sdist (`[tool.hatch.build.targets.sdist]` in `pyproject.toml`).

<!-- soft-factorio:begin -->
## Software factory

How agents work in this repository. Skills are in `.agents/skills/` (copied
to `.claude/skills/`); guides are in `.agents/factory/guides/`. The
repository's own rules outside this block win over it.

- **Check intent before building.** When an ask is vague or would change what
  gets built, use `outcome-brief`: agree a product brief (value and behaviour)
  before touching code. Answers to your questions, or "you decide", aren't
  approval; a yes to the brief is. Small, clear asks: say the outcome in two
  lines, then work.
- **Prompt for outcomes.** When you hand work to another agent, state the
  value and the finish line, not the steps (`prompting-for-outcomes.md`).
- **Report in pages.** Answer a request for a report, a review, a status or a
  comparison with an HTML page made with `html-for-humans`, plus two lines in
  chat that point to it. Short factual answers stay in chat.
- **Ship for review.** Finished, committed work goes out as one pull request
  (`create-pr`).
- **Carry approved work to its finish line.** Once the person has agreed what
  to build and when it's done, keep going until it's done: commit, push your
  branch, open or update the pull request and start the next stage without
  asking. Stop only at checkpoints they named, for a choice that would change
  what gets built, or before sending anything outside the repository. If a
  step can't run, such as checks that need an install, say so and keep going:
  ship a draft that names what didn't run. Report progress as you go; don't
  ask leave to continue.
- **Test behaviour.** Tests prove what the code does for its users, fail when
  that breaks and survive a refactor. Never assert only that a field exists
  or a function was called.
- **Learn from corrections.** Each time the person corrects you, use `retro`:
  fix it and add a row to a Lessons table (their words, the cause, where the
  fix went: a test, a rule or a skill) in your reply and in the open pull
  request. When the task ends, end your reply with the whole table.
- **Offer lessons upstream only if opted in.** If `upstream` below is `yes`,
  offer every lesson that would hold in any repository with
  `contribute-upstream`, asking each time, including lessons the person gives
  after a retro. If it's `no`, never mention sending lessons anywhere.
- **Standing instructions go in this file.** When the person says how agents
  should always or never work here, add it as one short line outside this
  block, in their words, with no new heading (`rules-files.md`). Not in your
  tool's private memory: other agents and people never see that.
- **Keep rules lean.** This file holds only what an agent can't infer from
  the repository.

The block between the `soft-factorio` markers is installed by the factory
and updated by reapplying it. Edits inside it are kept on update and
reported. The settings below belong to this repository.
<!-- soft-factorio:end -->

### Factory settings

| Key | Value |
|---|---|
| `projects` | `docs/projects/` |
| `upstream` | `yes` |
| `pr_without_asking` | `yes` |
