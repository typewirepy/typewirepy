---
name: release
description: Analyze commits and determine next version for PyPI release
user_invocable: true
---

# /release — Release Analysis Skill

Analyzes conventional commits since the last GitHub release and determines the next version to publish. Does NOT modify any files or create any commits.

Supports two modes:
- `/release` — standard release
- `/release dev` — dev pre-release

## Steps

### 1. Find the last GitHub release

Run:
```bash
gh release list --limit 1 --json tagName -q '.[0].tagName'
```

- If the command fails (non-zero exit), stop and tell the user to run `gh auth login`.
- If the output is empty (no releases exist), this is the **first release**:
  - Read `pyproject.toml` and extract the `version` value (e.g., `0.1.0`)
  - Skip commit analysis — use that version as-is
  - Jump to **Display summary** with bump type "initial"

### 2. List commits since last release

Run (replacing `<tag>` with the tag from step 1):
```bash
git log <tag>..HEAD --format='%s%n%b---'
```

- If no output (no commits since last release), stop and tell the user: "No commits since the last release. Nothing to release."

### 3. Parse conventional commits

For each commit, determine its bump level:

1. If the commit body contains `BREAKING CHANGE:` (literal text) OR the subject matches `<type>[(scope)]!:` (note the `!`) → **major**
2. If the subject starts with `feat:` or `feat(` → **minor**
3. All other commits → **patch** (including `fix`, `refactor`, `docs`, `chore`, `ci`, `test`, `perf`, `style`, `build`, and non-conventional formats)

The **highest bump wins** across all commits: major > minor > patch.

### 4. Calculate new version

Extract the base version from the last release tag (strip leading `v`). Apply the bump:
- **major**: increment major, reset minor and patch to 0
- **minor**: increment minor, reset patch to 0
- **patch**: increment patch

### 5. Display summary

Show the user:

```
## Release Summary

### Commits included
- <commit subject> → <bump level>
- ...

### Version
Bump type: <major|minor|patch|initial>
Version: <old> → <new>

### Publish command
gh workflow run publish.yml -f version=<new-version> -f dry-run=true

Change dry-run=false when ready to actually publish.
```

## Dev release flow (`/release dev`)

Same as above through step 4, then:

1. Determine the next version from conventional commits (same logic as standard flow)
2. Query PyPI for existing dev versions. Run:
   ```bash
   curl -s -o /tmp/pypi.json -w '%{http_code}' https://pypi.org/pypi/typewirepy/json
   ```
   - If HTTP status is `404` (project doesn't exist on PyPI yet), start at `.dev1`
   - If `200`, parse `/tmp/pypi.json`: extract all release keys matching `<next-version>.dev*`, parse the dev number as an **integer**, find the max, and increment by 1
   - Use **numeric comparison** (not lexicographic) for dev numbers
3. Version becomes `<next-version>.dev<N>` (e.g., `0.2.0.dev1`)
4. Display summary with the dev version and provide the dispatch command

## First release (no prior GitHub releases)

- Use the version from `pyproject.toml` directly (no bump)
- Provide the dispatch command for that version
