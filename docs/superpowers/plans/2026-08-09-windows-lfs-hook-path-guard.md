# Windows LFS Hook-Path Guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent Git LFS hook-path misuse from silently leaving a root `dev/null/` artifact on Windows.

**Architecture:** A concise agent instruction prevents the unsafe command, while a pytest repository-hygiene test detects the specific `dev/null/` artifact before integration. The existing generated directory is removed only after the test proves it detects the condition.

**Tech Stack:** Markdown, pytest, pathlib, Git.

## Global Constraints

- Do not ignore `/dev/`; detection must remain visible.
- Preserve the Makefile's parallel pytest-worker default.
- Remove only the verified generated root `dev/` directory.

---

### Task 1: Encode and test the guard

**Files:**
- Modify: `AGENTS.md`
- Create: `tests/test_repository_hygiene.py`

**Interfaces:**
- Consumes: repository root resolved from the test file path.
- Produces: a pytest failure whenever `ROOT / "dev" / "null"` exists.

- [ ] **Step 1: Write the failing repository-hygiene test**

```python
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_root_has_no_generated_lfs_hook_directory():
    assert not (ROOT / "dev" / "null").exists(), (
        "remove generated dev/null Git LFS hooks"
    )
```

- [ ] **Step 2: Run the test to verify it fails against the existing artifact**

Run: `make test ARGS="tests/test_repository_hygiene.py -v"`

Expected: FAIL because the root `dev/null/` directory exists.

- [ ] **Step 3: Add the agent instruction**

Add an `AGENTS.md` section that prohibits `git -c core.hooksPath=/dev/null` on
Windows, explains that Git LFS resolves it as `dev/null/`, and directs explicitly
authorized hook bypasses to `git commit --no-verify` or `git push --no-verify`.

- [ ] **Step 4: Re-run the failing test**

Run: `make test ARGS="tests/test_repository_hygiene.py -v"`

Expected: still FAIL until cleanup; documentation alone must not hide the artifact.

### Task 2: Remove the generated artifact and verify

**Files:**
- Delete: root `dev/` directory containing only the four duplicate Git LFS hooks.
- Test: `tests/test_repository_hygiene.py`

**Interfaces:**
- Consumes: Task 1's existence assertion.
- Produces: a clean worktree with no root `dev/` artifact.

- [ ] **Step 1: Verify the deletion target**

Run: `Get-ChildItem -LiteralPath C:\\Users\\lukas\\git\\timetracker\\dev -Recurse`

Expected: only `null/pre-push`, `null/post-checkout`, `null/post-commit`, and
`null/post-merge`, each duplicating `.git/hooks` Git LFS hook content.

- [ ] **Step 2: Remove the verified directory**

Run: `Remove-Item -LiteralPath C:\\Users\\lukas\\git\\timetracker\\dev -Recurse`

- [ ] **Step 3: Run the regression test**

Run: `make test ARGS="tests/test_repository_hygiene.py -v"`

Expected: PASS.

- [ ] **Step 4: Run the fast aggregate with default parallel workers**

Run: `make check-fast`

Expected: PASS with the Makefile-selected worker count; do not set
`PYTEST_WORKERS=0`.

- [ ] **Step 5: Commit**

```bash
git add AGENTS.md tests/test_repository_hygiene.py \
    docs/superpowers/specs/2026-08-09-windows-lfs-hook-path-guard-design.md \
    docs/superpowers/plans/2026-08-09-windows-lfs-hook-path-guard.md
git commit -m "test: guard against generated LFS hook paths"
```
