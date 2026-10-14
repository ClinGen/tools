# Project Instructions for AI Agents

This file provides instructions and context for AI coding agents working on this project.

<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:1105d646 -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/core-concepts/sync-concepts.md for details and anti-patterns.

## Agent Context Profiles

The managed Beads block is task-tracking guidance, not permission to override repository, user, or orchestrator instructions.

- **Conservative (default)**: Use `bd` for task tracking. Do not run git commits, git pushes, or Dolt remote sync unless explicitly asked. At handoff, report changed files, validation, and suggested next commands.
- **Minimal**: Keep tool instruction files as pointers to `bd prime`; use the same conservative git policy unless active instructions say otherwise.
- **Team-maintainer**: Only when the repository explicitly opts in, agents may close beads, run quality gates, commit, and push as part of session close. A current "do not commit" or "do not push" instruction still wins.

## Session Completion

This protocol applies when ending a Beads implementation workflow. It is subordinate to explicit user, repository, and orchestrator instructions.

1. **File issues for remaining work** - Create beads for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **Handle git/sync by active profile**:
   ```bash
   # Conservative/minimal/default: report status and proposed commands; wait for approval.
   git status

   # Team-maintainer opt-in only, unless current instructions forbid it:
   git pull --rebase
   git push
   git status
   ```
5. **Hand off** - Summarize changes, validation, issue status, and any blocked sync/commit/push step

**Critical rules:**
- Explicit user or orchestrator instructions override this Beads block.
- Do not commit or push without clear authority from the active profile or the current user request.
- If a required sync or push is blocked, stop and report the exact command and error.
<!-- END BEADS INTEGRATION -->

## Build & Test

We use `just` for common tasks. Run `just --list` to see every recipe.

```bash
just test-all          # Run all tests (uv run pytest -n auto)
just ci                # Run formatters, linters, type checks, Django checks, and tests
just django-runserver  # Run the development server
just django-migrate    # Apply migrations
```

## Architecture Overview

This project is one Django web application that houses the Stanford ClinGen team's
internal tools. Each tool is mounted under its own path on tools.clinicalgenome.org:

- `/as/`: the Affiliations Service (AS), the source of truth for ClinGen affiliations.
- `/css/`: the ClinVar Submission Service (CSS), which forwards submissions to ClinVar
  and tracks them.
- `/ets/`: the Email Transfer Service (ETS), which moves a GCI or VCI user's account
  from an old email to a new one.
- `/`: a landing page that links to each tool.

The AS and the CSS are ports of the standalone `affiliations-service` and
`clinvar-submission-service` repositories. Their designs carry over unless
`docs/design.md` says otherwise. The stack and conventions follow the HLA Curation
Interface (HCI). `docs/design.md` describes the design, including what the tools share
and what each one owns.

Code shared by more than one tool belongs in a shared app, not in one tool's app. A tool
must not import from another tool's app; if two tools need the same thing, move it into
a shared app.

In docs.json, we list important directories that have READMEs. Each README has a brief
overview of the directory followed by short descriptions of each non-ignored file in the
directory.

## Conventions & Patterns

- We strive for high test coverage, and when reasonable, we follow test-driven
  development.
- We use Google docstrings.
- We use American English.
- When writing Markdown, the text width is 88 characters.
- Don't use Markdown tables. Use a bulleted list instead, with one bullet per row.
- We call the tools by their abbreviations (AS, CSS, ETS) in prose. Because `as` is a
  Python keyword and `css` is easy to confuse with stylesheets, Django apps use
  descriptive names instead (see `docs/design.md`).

## Keeping Documentation Up-to-Date

Documentation changes are part of every code change, not a follow-up task. When you add,
remove, rename, or significantly change a file, update the README in its directory in
the same change. If you add a directory that belongs in docs.json, add it there and
scaffold its README with `uv run docs.py generate --directory <dir>`. If a change makes
anything in `docs/` inaccurate, update that too.

## Our Beads Workflow

Beads are the only place we plan and track work. Don't write plan or ticket files in
`docs/`, don't add open-questions or to-do sections to any doc, and don't use
`--spec-id`. Docs describe decisions that have been made; questions go in `decision`
beads.

1. `docs/prompts/04-break-down-into-beads.md` turns a description of work (a GitHub
   issue, notes, or a plan approved in plan mode) into an epic with child beads, or a
   single bead for small work.
2. `docs/prompts/05-work-beads.md` works through a single bead, or through an epic's
   beads until none are ready.

A bead has to stand on its own. Its description says what to change and why, and its
acceptance criteria name the tests to write. Put rationale shared by an epic's children
in the epic's `--design` field instead of repeating it. Record a decision in the bead it
affects, as a note or a close reason. For an open question, create a `decision` bead
labeled `needs-input` that blocks the work waiting on it, and write the question out in
full. Don't restate what the code already says; beads describe intent, not the code to
type.

Label each bead with the tool it affects (`as`, `css`, or `ets`), or `shared` if it
affects the shared apps, the landing page, or the infrastructure. An epic should touch
one tool, or the shared code, but not both, unless the work can't be split.

When working on a bead, follow its acceptance criteria and read its epic's design, if it
has one. File work you discover outside a bead's scope as a new bead instead of doing
it. After changing beads, run `bd export -o .beads/issues.jsonl` so the export in git
stays current. Don't commit, push, or run `bd dolt push` unless a prompt or I tell you
to.

## Pull Requests

Each pull request is one conceptual change. Aim for about 150 changed lines; that's a
guideline, not a hard rule. Split larger work into a stack of pull requests with
`gh stack` (https://gh.io/stacks): each branch is based on the one below it, the bottom
one targets `main`, and code in a branch may depend only on its own branch or lower
ones. An epic's child beads become one stack; see `docs/prompts/05-work-beads.md`.

To change a lower branch, such as after review, run `gh stack checkout <branch>`,
commit the fix, then `gh stack rebase` to cascade it up the stack. If
`.beads/issues.jsonl` conflicts, rerun `bd export -o .beads/issues.jsonl` and continue
with `gh stack rebase --continue`. Don't push or submit the stack unless I ask.

## Commit Messages

The first line of a commit message is a summary. On the web it's often styled as a
heading, and in email it's usually the subject. Capitalize it and omit trailing
punctuation. Aim for about 50 characters, or it may be truncated in some contexts. Write
it, and the rest of the message, in the imperative: "Fix bug," not "Fixed bug" or "Fixes
bug." Consistent wording makes a list of commits easier to read.

Often a subject by itself is enough. When it isn't, add a blank line, then one or more
paragraphs hard-wrapped to 72 characters. Git expects the author to supply line breaks;
without them, command-line tools show each paragraph as one long line.

Don't reference bead IDs, and don't add `Co-Authored-By` trailers or other AI
attribution lines. The same goes for pull request descriptions.
