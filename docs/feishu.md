# Feishu scan-to-create and WebSocket service

dual-tmux uses Feishu's official PersonalAgent Device Registration flow. A user does not create an App or provide an App ID, App Secret, verification token, or public callback URL.

## User flow

1. Install and start the persistent service once: `dt daemon --install`.
2. Start `dt web`, open **Feishu**, and click **Generate QR code**.
3. Scan with the Feishu mobile app and approve creation of the PersonalAgent.
4. The server polls Feishu, receives the generated credentials, encrypts the secret immediately, and the daemon starts the outbound WebSocket connection.
5. Send `/dt ls` to the new Bot.

Closing `dt web` does not stop the Bot. `dt web` owns only the UI; `dt daemon` owns the connector lifecycle.

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

In Hub mode, a short central lease prevents two Clients from consuming the same Bot concurrently. The existing mailbox remains the transport for work that must wait for an offline Client. Full tom7r-owned WS deployment is a release gate: Device Registration and the daemon must run on tom7r so generated credentials never need to be copied from a Client.

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
