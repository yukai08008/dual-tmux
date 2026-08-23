# Skills

| | Path | Who |
|--|------|-----|
| **Catalog (all)** | `~/.dual-tmux/skills/<name>/SKILL.md` | source of truth |
| **Trigger subset** | `~/.dual-tmux/skills.json` → `trigger` | copied into `ops/<op_*>/.opencode/skills/` on `prepare` |
| **Bullet subset** | `skills.json` → `bullet` | taught into `run_*` via send-keys; not auto-installed in the container |
| **Usage log** | `~/.dual-tmux/skill-usage.jsonl` | time, skill, dt, ok/fail |

Packaged copies of `dual-tmux` and `tmux-trigger` seed the catalog if missing. Core trigger skills cannot be disabled.

## Commands

```sh
dt skill ls
dt skill import ~/path/to/my-skill     # folder, SKILL.md, or .zip
dt skill enable my-skill trigger
dt skill enable my-skill bullet
dt skill disable my-skill bullet
dt skill teach dt-msg mermaid-arch     # enable on bullet + send-keys
dt skill used dt-msg dual-tmux --ok --detail 'dispatched rebuild'
dt skill used dt-msg tmux-trigger --fail --detail 'pane down'
dt skill log -n 40
dt skill log --name dual-tmux --status no
```

Trigger OpenCode should log after using a skill (`AGENTS.md` says so). Web/CLI do not infer success from pane text.

After changing the trigger subset, run `dt enter <dt>` (or resume) so `prepare` recopies skills into that `op_*` launch dir.
