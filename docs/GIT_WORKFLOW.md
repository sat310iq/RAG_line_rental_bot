# Git Workflow

## Repository root

The Git repository root is this project directory (the path that contains this repo’s `README.md` and `.git`):

```text
rental_rag_poc/
```

Always run `git` from this directory unless you use the wrapper script below.

## Recommended Cursor setup

Open this folder directly in Cursor or VS Code:

```text
rental_rag_poc/
```

Do not open only the parent folder (for example `Assignment 3 - Solutions/`) unless you use a multi-root workspace and understand that `git` in the default terminal may run outside the repository.

## Basic workflow

```bash
git status --short
git diff --stat
git add -p
git commit -m "..."
```

## Commit unit rule (guideline)

Prefer small, reviewable commits, for example:

1. KB / fast path
2. LINE / deploy
3. evaluation
4. docs
5. data policy

## Git from a parent directory

If your shell’s current directory is *above* the repository root, use:

```bash
./path/to/rental_rag_poc/scripts/git_in_repo.sh status --short
```

This script `cd`s to the repository root, then runs `git` with the same arguments. It exits with an error if `.git` is missing (e.g. wrong path after a layout change). See [scripts/git_in_repo.sh](../scripts/git_in_repo.sh).

Local-only script overrides can live next to the repo with the pattern `scripts/*.local.sh` (ignored; see root `.gitignore`).
