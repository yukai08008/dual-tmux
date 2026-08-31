# Feishu control (v0.4.47 API)

v0.4.47 provides the local security and command API used by the v0.4.48 Web UI and tom7r event bridge. It does not yet make a phone reach a Client bound to `127.0.0.1`; that routing belongs to v0.4.48.

## Security model

- App Secret is accepted only through `DT_FEISHU_APP_SECRET` or a current-user-owned, non-symlink file with exact mode `0600`.
- OAuth access tokens are never persisted. Only stable `open_id`, `union_id`, and `user_id` bindings are saved locally under `~/.dual-tmux/feishu/`.
- Pairing state, `event_id`, and destructive confirmation tokens are stored as hashes, expire, and can be consumed only once.
- Feishu commands use the same `ControlService` as CLI and Web.
- `upgrade`, `hotfix`, cron installation, shell/SSH/config mutation, and arbitrary commands are not exposed.

The Feishu directory is Client-local. It is not inside `tunnels/` or `entries/`, so Hub synchronization does not copy secrets or operator bindings.

## Local API setup

```bash
install -m 600 /dev/null ~/.dual-tmux/feishu-app-secret
# Edit the file without placing the secret in shell history.

dt feishu configure \
  --app-id cli_xxx \
  --redirect-uri https://your-hub.example/feishu/callback \
  --secret-file ~/.dual-tmux/feishu-app-secret \
  --allow-id ou_xxx

dt feishu pair
dt feishu status
```

`dt feishu callback` and `dt feishu dispatch` are low-level bridge/testing commands. v0.4.48 will call the same Python API from the Web and tom7r bridge, so users will not need to copy callback codes manually.

## Supported commands

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

The first `drop` or `rm` request returns a short-lived confirmation token. The token is bound to that operator, action, and tunnel.
