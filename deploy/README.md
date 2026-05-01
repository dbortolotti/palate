# Palate Deployment

This repo is configured for a macOS LaunchAgent plus Tailscale Funnel. The
recommended production layout keeps the live service under `/Users/oric/prod`
instead of running from the development checkout.

The service runs locally on:

```text
http://127.0.0.1:8787/mcp
```

Tailscale Funnel exposes the authenticated MCP endpoint publicly on:

```text
https://modal.tail63a6b7.ts.net/palate/mcp
```

## Production Layout

Production releases live at:

```text
/Users/oric/prod/palate/releases/<git-sha>
```

The live service runs through the symlink:

```text
/Users/oric/prod/palate/current
```

Mutable state is shared across releases:

```text
/Users/oric/prod/palate/shared/data/palate.sqlite
/Users/oric/prod/palate/shared/backups/
/Users/oric/prod/palate/shared/logs/
/Users/oric/prod/palate/shared/secrets/
/Users/oric/prod/palate/shared/.env
```

Deploy locally from a checked-out copy with:

```sh
./deploy/deploy-local.sh
```

The script builds an isolated release, installs dependencies, runs compile and
unit tests, backs up the current SQLite database, switches the `current`
symlink, restarts launchd, checks `/healthz`, and rolls back the symlink if the
health check fails.

## GitHub Actions Deployment

CI runs on GitHub-hosted runners. Deployment runs on this Mac through a
self-hosted runner labeled `palate-prod`.

Install or repair the local runner with:

```sh
./deploy/install-github-runner.sh
```

After the runner is online, every push to `main` runs:

```text
.github/workflows/deploy-local.yml
```

Only trusted `main` code should run on the self-hosted runner.

## Legacy Development LaunchAgent

The development launchd plist is:

```text
deploy/com.palate.mcp.plist
```

Install it with:

```sh
cp deploy/com.palate.mcp.plist ~/Library/LaunchAgents/com.palate.mcp.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.palate.mcp.plist
launchctl kickstart -k gui/$(id -u)/com.palate.mcp
```

Expose only Palate through Tailscale Funnel:

```sh
tailscale serve reset
tailscale funnel --bg --yes --set-path /palate http://127.0.0.1:8787
tailscale funnel --bg --yes --set-path /.well-known/oauth-protected-resource/palate/mcp http://127.0.0.1:8787/.well-known/oauth-protected-resource/palate/mcp
tailscale funnel --bg --yes --set-path /.well-known/oauth-authorization-server/palate http://127.0.0.1:8787/.well-known/oauth-authorization-server/palate
```

This intentionally removes unrelated Tailscale handlers before enabling Funnel.
The extra path-suffixed `/.well-known/oauth-*` routes are needed for OAuth
discovery for the `/palate/mcp` resource and the path-scoped authorization
server without claiming the whole well-known namespace. Funnel makes these
routes reachable from the public internet, so keep Palate auth enabled before
leaving it on.

Check status:

```sh
launchctl print gui/$(id -u)/com.palate.mcp
tailscale funnel status
```

Logs:

```text
logs/palate.out.log
logs/palate.err.log
```

Set `OPENAI_API_KEY` in `../.env` before using LLM-backed tools.

## MCP Auth

The LaunchAgent enables Palate OAuth for remote MCP clients:

```text
PALATE_AUTH_ENABLED=1
PALATE_PUBLIC_BASE_URL=https://modal.tail63a6b7.ts.net/palate
PALATE_AUTH_SCOPES=palate.access
```

The first ChatGPT connection opens a Palate login page. The password is stored
at:

```text
../secrets/palate-auth-password
```

OAuth client registrations and issued tokens are stored at:

```text
../secrets/palate-oauth.json
```

Backups run once daily while the server is running. By default they write:

```text
../backups/
```

Each run creates:

```text
palate-YYYYMMDD-HHMMSS.sqlite
palate-YYYYMMDD-HHMMSS.json
```

Backups older than 31 days are deleted automatically. If you use Google Drive
Desktop sync instead of the API integration below, set `PALATE_BACKUP_DIR` in
the LaunchAgent to a Drive-synced folder, then reload the LaunchAgent.

## Google Drive API Backups

Palate can upload backup snapshots directly through the Google Drive API,
without the Google Drive desktop sync client.

One-time Google setup:

1. Enable the Google Drive API in a Google Cloud project.
2. Create an OAuth Desktop app client.
3. Save the downloaded client JSON at:

```text
../secrets/google-oauth-client.json
```

4. Run:

```sh
python3 -m palate.google_drive
```

That opens a browser and writes:

```text
../secrets/google-token.json
```

To enable upload after authorization, change the LaunchAgent setting:

```text
PALATE_BACKUP_GOOGLE_DRIVE_ENABLED=1
```

then reload:

```sh
cp deploy/com.palate.mcp.plist ~/Library/LaunchAgents/com.palate.mcp.plist
launchctl bootout gui/$(id -u)/com.palate.mcp || true
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.palate.mcp.plist
launchctl kickstart -k gui/$(id -u)/com.palate.mcp
```

By default, Drive backups go to the folder path `backup/palate`. Drive-side
cleanup uses the same `PALATE_BACKUP_RETENTION_DAYS` value.

FastMCP validates Host headers to protect against DNS rebinding. The LaunchAgent allows:

```text
127.0.0.1
127.0.0.1:8787
localhost
localhost:8787
modal.tail63a6b7.ts.net
```
