# v0.08 TEST_CASES — Local/Hub setup experience

## 0. Invariant regression

| ID | Scope | Command |
|---|---|---|
| B-00 | Full Python regression | `uv run pytest` |
| B-01 | Build artifacts | `uv build` |
| B-02 | Runtime data | `git ls-files data/` is empty |

## 1. CLI experience

| ID | Case | Acceptance | Automated |
|---|---|---|---|
| W-10 | help contains `--local` | W-1 | yes |
| W-11 | local config output says local-only | W-2 | yes |
| W-12 | Hub config output names server and user | W-2 | yes |
| W-13 | attach/detach reports merge-before-switch | W-3 | yes |

## 2. Documentation

| ID | Case | Acceptance | Automated |
|---|---|---|---|
| W-20 | English local/attach examples | W-4 | review |
| W-21 | Chinese local/attach examples | W-4 | review |

## 3. Release verification

| ID | Case | Expected |
|---|---|---|
| E-30 | install from GitHub release and run local init | no SSH required |
| E-31 | upgrade current installation | new version active |
| E-32 | current tom7r sync | succeeds and preserves record hashes |
