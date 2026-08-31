# Network jitter and disconnect can strand bullet

## Symptom

A remote bullet pane may remain on stale output or fall back to a shell after SSH, container, or Agent failure. A static pane alone cannot distinguish normal idle work from a dead path.

## Risk

Blind restarts can duplicate Agents on two Clients, target the wrong container, or lose the recorded session workpoint.

## Reproduction dimensions

- transient packet loss;
- SSH process exit;
- recorded container stopped or missing;
- recorded directory removed;
- Agent exited;
- OpenCode session missing from the target database.
