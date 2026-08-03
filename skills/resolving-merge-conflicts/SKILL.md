---
name: resolving-merge-conflicts
description: "Resolve merge conflicts by tracing back to the intent of each side's changes. Reads commit history and PR context to decide which side wins. Use when user has merge conflicts and wants them resolved thoughtfully, not by 'accept both'. 适用于用户提到'冲突解决''merge conflict''合并冲突''rebase冲突'等场景。"
version: 1.0.0
user-invocable: true
command-dispatch: model
triggers:
  - "merge conflict"
  - "合并冲突"
  - "冲突解决"
  - "rebase 冲突"
  - "resolve conflicts"
---

# Resolving Merge Conflicts

Resolve merge conflicts by tracing back to the **intent** of each side's changes. Never "accept both" or "accept theirs/ours" blindly.

适配自 mattpocock/skills (保留 intent-tracing 方法论，适配为 Hermes)。

## Principle: Intent > text

A conflict marker shows two versions of text. The real question is: **what was each side trying to achieve?** Resolve the intent, not the text.

```
<<<<<<< HEAD
def get_user(id): return db.users.find(id)
=======
def get_user(id): return cache.get_or_set(f"user:{id}", lambda: db.users.find(id))
>>>>>>> feature/caching
```

Bad resolution: pick one text.
Good resolution: "HEAD wants basic lookup; feature/caching wants caching. Resolution: use cached version but verify cache invalidation strategy is in place."

## Process

### 1. Identify conflicted files
```bash
git diff --name-only --diff-filter=U
```

### 2. For each conflict, trace intent
For each conflicted hunk:
- **Our side (HEAD)**: `git log -p -1 HEAD -- <file>` — what commit introduced this change and why?
- **Their side (MERGE_HEAD)**: `git log -p -1 MERGE_HEAD -- <file>` — what commit and why?
- **PR context**: if the branch has a PR, read the PR description for intent

### 3. Classify the conflict

| Type | Resolution strategy |
|------|-------------------|
| **Independent additions** | Both changes are additive in different places → keep both |
| **Same purpose, different impl** | Both solve the same problem → pick the better one, cite why |
| **Conflicting purposes** | Changes serve different goals → reconcile or escalate to human |
| **One side stale** | One change was since superseded → keep the current one |
| **Formatting only** | Whitespace/imports → pick whichever, note it |

### 4. Resolve
Edit the file to reflect the **reconciled intent**. Add a comment if the resolution is non-obvious:

```python
# Resolved conflict: feature/caching adds cache layer (PR #42),
# HEAD's None-check is retained as cache.get_or_set handles None.
def get_user(id):
    return cache.get_or_set(
        f"user:{id}",
        lambda: db.users.find(id)
    )
```

### 5. Verify
```bash
git add <resolved-files>
# Run tests / type-check / lint to verify resolution doesn't break
ruff check <resolved-files>
mypy <resolved-files>
pytest tests/ -k <relevant>
```

### 6. Document the resolution
In the merge commit message (or PR comment):

```
Resolved N conflicts in <files>:

- <file>:<line> — kept cached version (PR #42 intent), retained None-check from HEAD
- <file>:<line> — independent additions, kept both
- <file>:<line> — formatting only, picked feature branch style
```

## Anti-patterns

- **"Accept both" / "Accept incoming"**: Blind acceptance ignores intent. Never do this.
- **Text-level merge**: Merging text without understanding why each side wrote it.
- **Skipping verification**: Resolved files must pass tests/type-check/lint before commit.
- **Silent resolution**: No documentation of what was resolved and why.

## When to escalate to human

- **Conflicting purposes** where neither side is clearly wrong
- **Large semantic conflicts** (>50 lines of meaningful diff per hunk)
- **Conflicts in security-sensitive paths** (auth/, payment/, security/)

## Completion criteria
- [ ] All conflicted files identified
- [ ] Each conflict's intent traced (commit message / PR context)
- [ ] Each conflict classified (independent/same-purpose/conflicting/stale/formatting)
- [ ] Resolution reflects reconciled intent (not blind acceptance)
- [ ] Tests / lint / type-check pass on resolved files
- [ ] Resolution documented in commit message or PR comment
