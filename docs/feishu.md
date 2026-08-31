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

## v0.4.48 Web and tom7r bridge

Open `dt web` and choose **飞书**. The page can save non-secret App settings, generate a 10-minute QR code, show bound identities, sync the Hub mailbox, and unbind identities. The Web request schema rejects an `app_secret` field; place the secret in the environment or a strict local file before starting the process.

The public bridge is a separate process on tom7r:

```bash
export DUAL_TMUX_HOME=/home/<login>/<user>/dual-tmux
export DT_FEISHU_APP_SECRET=...          # preferably injected by service manager
export DT_FEISHU_VERIFICATION_TOKEN=...
dt feishu bridge --host 127.0.0.1 --port 8790
```

tom7r currently has Docker but only host Python 3.6, so the repository also includes a Python 3.12 container deployment under `deploy/feishu-bridge/`. Create `/root/andy/dual-tmux/feishu/config.json` using `dt feishu configure` semantics, copy `bridge.env.example` to `/root/andy/dual-tmux/feishu/bridge.env`, set mode `0600`, then run:

```bash
docker compose -f deploy/feishu-bridge/compose.yaml up -d --build
curl http://127.0.0.1:8790/health
```

The compose file publishes only on tom7r loopback, drops Linux capabilities, and mounts the existing `/root/andy/dual-tmux` tenant root as `/data`. It does not touch `tunnels/`, `entries/`, session data, or Client configuration.

Put Caddy or another TLS reverse proxy in front of these exact routes:

```text
GET  /health
GET  /feishu/callback
POST /feishu/events
```

Configure the Feishu App OAuth redirect as the public `/feishu/callback` URL and its event subscription as `/feishu/events`. Use unencrypted event delivery with a verification token for this release. Do not expose the local `dt web` port.

In Hub mode, QR creation registers only a hash of the one-time state on tom7r. The bridge exchanges the OAuth code, stores only hashed identity routes, and places an identity envelope in the target Client mailbox. Each `dt tick` (or the Web **立即同步事件桥** button) pulls pending callbacks/commands over SSH, validates them locally, calls `ControlService`, and writes response envelopes. Offline Clients therefore retain their inbox. Switching to local-only mode leaves local bindings intact and disables network polling; attaching a Hub again lets the Client register new pairing routes without modifying tunnels.

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
