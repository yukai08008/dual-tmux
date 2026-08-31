# v0.08 PRD — Local/Hub setup experience

> Parent: v0.07
> Drafted: 2026-08-31
> Type: Web/interaction (even)

## 0. Goal

Expose local-only initialization and later safe Hub attachment through clear CLI prompts, help, diagnostics, and bilingual documentation, then ship the combined v0.07/v0.08 capability.

## 1. Scope and invariants

- `dt config --init --local --client tm_<id>` creates local mode.
- Interactive setup asks local vs Hub and only asks Hub fields when selected.
- `dt config --server HOST --user USER` attaches or replaces a Hub safely.
- `dt config --local` safely detaches.
- `dt config` and `dt doctor` show the current mode.
- Explicit `push`/`pull` are rejected locally with an actionable command.
- Existing command examples remain valid.
- Runtime data is not tracked; new CLI behavior has automated coverage.

## 2. Compatibility

No flags are removed. Existing non-interactive `--init --client --server --user` retains its behavior. Config files do not require rewriting on upgrade.

## 3. Release criteria

- Full pytest and compile gates pass.
- sdist and wheel build.
- Isolated local initialization smoke test.
- Real existing tom7r configuration still passes doctor/sync.
- No P0/P1 risk remains.

## 4. Signature

Agent-PM-0.08
