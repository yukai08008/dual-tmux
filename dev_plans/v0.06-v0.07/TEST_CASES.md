# v0.07 TEST_CASES — Local-first configuration

## 0. Invariant regression

| ID | Scope | Command |
|---|---|---|
| B-00 | Full Python regression | `uv run pytest` |
| B-01 | Syntax | `uv run python -m compileall -q src tests` |
| B-02 | Runtime data | `git ls-files data/` is empty |

## 1. Configuration

| ID | Case | Acceptance | Automated |
|---|---|---|---|
| B-10 | initialize with Client only | A-1 | yes |
| B-11 | parse old server/user file | A-2 | yes |
| B-12 | reject only server or only user | A-5 | yes |
| B-13 | atomic write has complete mode | A-1/A-5 | yes |

## 2. Migration

| ID | Case | Acceptance | Automated |
|---|---|---|---|
| B-20 | attach calls candidate sync before write | A-3 | yes |
| B-21 | replace syncs old then candidate | A-3 | yes |
| B-22 | detach syncs old before local write | A-3 | yes |
| B-23 | sync failure leaves old config bytes unchanged | A-3 | yes |

## 3. Mode behavior

| ID | Case | Acceptance | Automated |
|---|---|---|---|
| B-30 | local best-effort Hub helpers are no-op | A-4 | yes |
| B-31 | explicit push/pull in local mode explains how to attach | A-4 | yes |
| B-32 | local doctor has no required SSH check | A-4 | yes |

## 4. Deployment verification

| ID | Case | Expected |
|---|---|---|
| E-40 | isolated local setup and `dt doctor` | passes without SSH |
| E-41 | local → test Hub attach | both record sets converge |
| E-42 | upgrade an existing Hub config | unchanged sync behavior |
