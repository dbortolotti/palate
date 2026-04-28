# Palate Deployment

This repo is currently configured for a macOS LaunchAgent plus Tailscale Serve.

The service runs locally on:

```text
http://127.0.0.1:8787/mcp
```

Tailscale Serve can expose that to the tailnet on:

```text
https://modal.tail63a6b7.ts.net/palate/mcp
```

The launchd plist is:

```text
deploy/com.palate.mcp.plist
```

Install it with:

```sh
cp deploy/com.palate.mcp.plist ~/Library/LaunchAgents/com.palate.mcp.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.palate.mcp.plist
launchctl kickstart -k gui/$(id -u)/com.palate.mcp
```

Expose it through Tailscale Serve:

```sh
tailscale serve --bg --set-path /palate http://127.0.0.1:8787
```

Check status:

```sh
launchctl print gui/$(id -u)/com.palate.mcp
tailscale serve status
```

Logs:

```text
logs/palate.out.log
logs/palate.err.log
```

Set `OPENAI_API_KEY` in `/Users/oric/git/palate/.env` before using LLM-backed tools.

FastMCP validates Host headers to protect against DNS rebinding. The LaunchAgent allows:

```text
127.0.0.1
127.0.0.1:8787
localhost
localhost:8787
modal.tail63a6b7.ts.net
```
