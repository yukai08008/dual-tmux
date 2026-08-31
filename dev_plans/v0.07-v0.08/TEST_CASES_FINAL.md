# v0.08 验收报告

## 验收摘要

| 维度 | 数量 | 通过 | 失败 |
|---|---:|---:|---:|
| CLI experience | 4 | 4 | 0 |
| Documentation | 2 | 2 | 0 |
| Release gates | 3 | 3 | 0 |

## 逐条结果

| ID | 用例 | 结果 | 备注 |
|---|---|---|---|
| B-00 | Full Python regression | PASS | 78 passed |
| B-01 | sdist/wheel | PASS | package 0.4.39 built |
| B-02 | runtime data | PASS | `git ls-files data/` empty |
| W-10 | `--local` discoverability | PASS | parser/help and prompt |
| W-11 | local config display | PASS | shows `mode local` |
| W-12 | Hub config display | PASS | server/user/roots shown |
| W-13 | attach/detach result | PASS | reports merged switch |
| W-20 | English docs | PASS | local and later attach examples |
| W-21 | Chinese docs | PASS | local and later attach examples |
| E-30 | isolated switch smoke | PASS | local → tom7r → local, 6 records |
| E-31 | GitHub upgrade | PASS | installed CLI upgraded 0.4.38 → 0.4.39 |
| E-32 | tom7r sync | PASS | tunnel SHA-256 sets identical |
| E-33 | browser DOM E2E | PASS | local init and Hub attach commands visible; no console errors |

## 遗留问题

- No P0/P1 issue remains.
