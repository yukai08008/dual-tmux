# Feishu scan-to-create and WebSocket service

dual-tmux uses Feishu's official PersonalAgent Device Registration flow. A user does not create an App or provide an App ID, App Secret, verification token, or public callback URL.

## User flow

1. Install and start the persistent service once: `dt daemon --install`.
2. Start `dt web`, open **Feishu**, and click **Generate QR code**.
3. Scan with the Feishu mobile app and approve creation of the PersonalAgent.
4. The server polls Feishu, receives the generated credentials, encrypts the secret immediately, and the daemon starts the outbound WebSocket connection.
5. Send `/dt ls` to the new Bot.

Closing `dt web` does not stop the Bot. `dt web` owns only the UI; `dt daemon` owns the connector lifecycle.

One dual-tmux deployment has one PersonalAgent. Every Client and every `dt web` connected to the same Hub manages that shared Bot; opening another Web page does not start another WebSocket. When an installation already exists, scan-to-create is disabled until the operator explicitly unlinks the existing Bot.

## Security boundary

- Device Registration uses `POST https://accounts.feishu.cn/oauth/v1/app/registration` with the RFC 8628 begin/poll contract.
- The Device Code remains server-side and expires after ten minutes.
- The generated App Secret is encrypted with an automatically generated Fernet/AEAD key.
- `credential.key` and `installation.json` are current-user-owned, non-symlink files with mode `0600` under `~/.dual-tmux/feishu/`.
- App Secret never enters Web responses, QR data, tunnel JSON, Hub tunnel sync, or audit logs.
- Operator bindings, event IDs, and destructive confirmation tokens remain fail-closed and one-time.
- Feishu cannot invoke `upgrade`, `hotfix`, cron installation, arbitrary shell, SSH, or config mutation.

## Persistent service

```bash
dt daemon --install   # macOS launchd / Linux systemd --user
dt daemon --status
dt daemon --remove
dt daemon             # foreground diagnostics
```

The daemon restores active installations after restart, supervises the blocking official `lark-oapi` WebSocket client in a child process, and restarts failures with bounded 5/15/30/60/120-second backoff. Unbinding removes the encrypted installation and terminates its connector.

In Hub mode, the tom7r daemon owns the in-memory WebSocket and durable inbox/outbox. A lightweight Client daemon probes only its own mailbox every five seconds and opens rsync transfers only when work exists. The existing one-minute `dt tick` is a fallback, not the primary response path. A filesystem lock serializes daemon, tick and manual `dt feishu sync`. Command parsing and ControlService execution are deterministic; no model is used unless `/dt send` deliberately forwards text into a trigger or bullet Agent.

The WS topology is separate from the tunnel data mode:

- local standalone: a local-only Client daemon holds the WS; sleep pauses connectivity and wake reconnects it.
- Hub persistent (default for Hub mode): tom7r owns the WS; Client sleep does not affect message reception, and commands wait in the mailbox.
- Client failover (advanced): multiple Client daemons may be candidates, but a tom7r atomic lease and monotonically increasing generation allow only one active WS.

The same lock file coordinates Hub containers and failover Clients. Every daemon instance has a unique owner identity, renews its heartbeat, and stops its connector when it loses ownership. A recovered stale generation stays standby; `event_id` replay protection remains the final duplicate-execution barrier.

## Commands

```text
/dt ls
/dt show <name>
/dt send <name> <text>
/dt health <name>
/dt freeze <name>
/dt resume <name>
/dt recover <name>
/dt drop <name> [confirm-token]
/dt rm <name> [confirm-token]
```

The first `drop` or `rm` request returns a short-lived confirmation token bound to the operator, action, and tunnel.
