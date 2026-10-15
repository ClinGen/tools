I'm going to supply a bead ID to you. Let's call this ID `root` for now. It will be
either an epic with child beads or a single bead with no children. Please do the
following tasks, making sure to replace `root` with the ID I provide to you. You have my
permission to create branches and stacks and make local commits. Do not `git push`,
`gh stack push`, `gh stack submit`, or `gh stack sync`, and do not run `bd dolt push`.

Each bead becomes one pull request. An epic becomes a stack of pull requests made with
`gh stack`: one branch per child bead, each based on the one before it, so reviewers see
one bead's diff at a time. The bottom branch targets `main`. Code in a branch may depend
only on its own branch or the ones below it.

1. Run `bd prime` if you haven't already this session. Then run `bd show root`, and read
   its design if it has one. Note whether `root` has child beads.

2. Find your starting point:

   - If `root` has child beads and some are already closed, its stack may exist. Run
     `gh stack checkout <branch>` with the branch of a closed child, then
     `gh stack top`.
   - Otherwise, switch to `main`. If you have uncommitted changes, or you're on another
     branch with work that isn't on `main`, stop and ask me.

3. Work the beads:

   - If `root` has child beads, repeat the steps below until `bd ready --parent root`
     lists nothing, picking the highest-priority bead from that list each time.
   - If `root` has no child beads, do the steps below once, with `root` as the bead.

   The steps for each bead are:

   01. Create the bead's branch, named `<id>-<short-slug>`:
       - Single bead: `git switch -c <id>-<short-slug>`.
       - First bead of a new stack: `gh stack init <id>-<short-slug>`.
       - Later beads: `gh stack add <id>-<short-slug>`, from the top of the stack.
   02. Claim the bead with `bd update <id> --claim` and read it with `bd show <id>`,
       including its notes and the decisions recorded on its closed blockers. Check its
       label: work on the `as`, `css`, or `ets` app must not change another tool's app,
       and must change shared code only if the bead says to.
   03. Write the tests named in the acceptance criteria first and confirm they fail.
   04. Implement until the tests pass.
   05. Update any READMEs and `docs/` files affected by your changes. Scaffold READMEs
       for new files with `uv run docs.py generate --directory <dir>`.
   06. Run `just ci`, and `just infra-all` if you changed `infra/`. Fix anything that
       fails.
   07. Check the size of the change against the branch below it with
       `git diff --stat <parent-branch>`. Aim for one conceptual change of about 150
       changed lines. That's a guideline, not a hard limit, but if the bead has grown
       into two things, stop and split it: file the second part as a new bead blocked by
       this one, and leave it for its own branch.
   08. If you find work outside this bead's scope, file it instead of doing it:
       `bd create --deps discovered-from:<id> --title "..." --description "..."`. If
       `root` has child beads, add `--parent root`. Add blockers with `bd dep add` if
       needed.
   09. Close the bead: `bd close <id> --reason "..."`. Then run
       `bd export -o .beads/issues.jsonl`.
   10. Commit the code, docs, and `.beads/issues.jsonl` together on the bead's branch.
       Follow the commit message style in `AGENTS.md`.

4. Stop early and tell me if a bead is ambiguous, contradicts its epic or the code, or
   can't pass `just ci` after a reasonable effort. Leave that bead open with a note
   (`bd update <id> --notes "..."`) explaining where you got stuck.

5. If `root` has child beads, run `bd show root` when nothing is ready. If every child
   bead is closed, close `root` and commit the export on the top branch of the stack.

6. Summarize what you did: the beads you closed, the beads you filed, the beads still
   open or blocked, and your commits. For a stack, include the output of `gh stack view`
   and remind me that `gh stack submit` opens the pull requests.
