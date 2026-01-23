# Agent Instructions

This project uses **bd** (beads) for issue tracking. Run `bd onboard` to get started.

## Task Management

This project uses Beads (`bd`) for task tracking. Use `bd` commands to:

- Create and track tasks
- Manage dependencies between tasks
- View ready-to-work tasks with `bd ready`
- Get workflow context with `bd prime`

## Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --status in_progress  # Claim work
bd close <id>         # Complete work
bd sync               # Sync with git
bd prime              # Get workflow context (~1-2k tokens)
bd create "Title" -p 0  # Create a P0 task
bd dep add <child> <parent>  # Link tasks (child depends on parent)
```

## Workflow

1. Check ready tasks: `bd ready`
2. Create new tasks: `bd create "Description" -p <priority>`
3. Link dependencies: `bd dep add <child> <parent>`
4. View task details: `bd show <id>`
5. Claim work: `bd update <id> --status=in_progress`
6. Complete work: `bd close <id>`

## Landing the Plane (Session Completion)

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   bd sync
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds

