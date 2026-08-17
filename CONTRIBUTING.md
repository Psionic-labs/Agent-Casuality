# Contributing

Use stacked pull requests for work that naturally depends on earlier work.
Each branch should contain one focused change, and each pull request should
target the branch immediately below it in the stack.

## What a stack looks like

```text
main
  └── phase1/events       PR 1 → main
        └── phase1/capture PR 2 → phase1/events
              └── phase1/tests   PR 3 → phase1/capture
```

Reviewers can review each change independently. The higher PRs include the
commits below them until those lower PRs merge.

## Create a stacked branch

Start from an up-to-date `main` branch:

```powershell
git switch main
git pull --ff-only origin main
git switch -c phase1/events
```

Make the first focused change, then commit and publish it:

```powershell
git add sdk/events.py storage/postgres.py
git commit -m "Add event model and storage contract"
git push --set-upstream origin phase1/events
```

Open PR 1 with `phase1/events` as the head and `main` as the base.

Create the next branch from the first branch—not from `main`:

```powershell
git switch phase1/events
git switch -c phase1/capture
```

Make the next change, commit it, and publish it:

```powershell
git add sdk/client.py sdk/tools.py sdk/memory.py
git commit -m "Capture model, tool, and memory events"
git push --set-upstream origin phase1/capture
```

Open PR 2 with `phase1/capture` as the head and `phase1/events` as the base.
Repeat the same pattern for further branches.

## After a lower PR merges

When PR 1 merges into `main`, retarget PR 2 from `phase1/events` to `main` in
the hosting service. Then rebase the branch locally so it contains only its
own commits on top of the new `main`:

```powershell
git fetch origin
git switch phase1/capture
git rebase --onto origin/main phase1/events phase1/capture
git push --force-with-lease origin phase1/capture
```

For the next branch, repeat the same operation using its previous base:

```powershell
git switch phase1/tests
git rebase --onto origin/main phase1/capture phase1/tests
git push --force-with-lease origin phase1/tests
```

Then retarget each open PR to the branch below it, or to `main` once that
branch has merged.

Use `--force-with-lease`, never plain `--force`. It refuses to overwrite
remote work that appeared after your last fetch.

## Resolve a rebase conflict

```powershell
git status
# edit the conflicted files
git add <resolved-file>
git rebase --continue
```

Repeat until the rebase completes, then publish the rewritten branch:

```powershell
git push --force-with-lease origin <branch-name>
```

To abandon the rebase and return to the previous state:

```powershell
git rebase --abort
```

## Contribution rules

- Keep each PR focused and independently understandable.
- Keep commits small enough to review; avoid unrelated formatting changes.
- Do not add merge commits to a stack. Rebase the stack instead.
- Do not rebase a shared branch without coordinating with its other authors.
- Run the project checks before opening or updating a PR:

  ```powershell
  .\scripts\check.ps1
  ```

- For database changes, also run the Neon-backed integration test:

  ```powershell
  uv run --env-file .env pytest tests/test_postgres_integration.py -m integration -q
  ```

## CI gate

Every push to `main` and every pull request runs the GitHub Actions workflow
in `.github/workflows/ci.yml`. It has two checks:

- `Tests, Ruff, and ty`
- `PostgreSQL integration`

Configure both checks as required status checks in the repository's branch
protection or ruleset for `main`. A pull request should not merge until both
checks pass.

## Useful inspection commands

```powershell
git log --oneline --graph --decorate --all
git diff origin/main...HEAD
git status
```

These make the current stack and the exact contents of the active PR easy to
inspect before pushing.
