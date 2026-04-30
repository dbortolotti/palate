# Palate

Personal taste memory and decision engine.

Current shape: MCP-first backend. There is no web frontend. Slack can be added later as an adapter over the same service.

## Boundary

The LLM is used for:

- intent parsing
- entity extraction
- enrichment normalization
- grounded explanation wording

The core system owns:

- explicit memory
- retrieval
- deterministic ranking
- negative filtering
- decision logging

Movie and series memories can store structured metadata plus OMDb-backed IMDb
and Rotten Tomatoes critic ratings. External ratings are stored as reference
metadata only; the personal 1-5 `rating` signal remains the taste score.

## Setup

```sh
python3 -m pip install -r requirements.txt
cp .env.example .env
python3 -m palate.seed
```

Set `OPENAI_API_KEY` in `.env` before using tools that require the LLM.
Set `OMDB_API_KEY` to fetch external movie and series ratings when remembering
media items.

## Run

```sh
python3 -m palate.server
```

For HTTP deployment behind Tailscale:

```sh
PALATE_TRANSPORT=streamable-http PALATE_HOST=127.0.0.1 PALATE_PORT=8787 python3 -m palate.server
```

## Verify

```sh
python3 -m compileall palate tests
python3 -m unittest discover -s tests
```

## MCP Tools

- `palate_query`: interpret a free-form taste query, rank memory, and explain results
- `palate_evaluate_options`: extract and evaluate a pasted option set
- `palate_remember`: store a taste memory, optionally normalizing raw description text and fetching movie or series ratings from OMDb
- `palate_recall`: recall matching explicit memory
- `palate_delete_record`: delete one explicit memory by exact entity ID
- `palate_enrich_item`: normalize noisy text into the fixed attribute schema
- `palate_log_decision`: record what the user chose
- `palate_backup_now`: create an immediate SQLite and JSON backup
- `palate_how_to`: return the user guide and prompt patterns for client LLMs

The same guide is also exposed as the MCP resource `palate://how-to`.

Option-set tools stay constrained to the provided options. If a pasted option is not already in memory, Palate reports it as unmatched instead of substituting unrelated stored items.

## Deployment

This repo includes a macOS LaunchAgent template and Tailscale Funnel notes in [deploy/README.md](/Users/oric/git/palate/deploy/README.md).

## MCP Auth

When `PALATE_AUTH_ENABLED=1`, Palate exposes an OAuth 2.1 flow for remote MCP
clients such as ChatGPT. The public connector URL is:

```text
https://modal.tail63a6b7.ts.net/palate/mcp
```

The first connection opens a Palate login page. The password is read from:

```text
/Users/oric/git/palate/secrets/palate-auth-password
```

OAuth client registrations and issued tokens are stored in:

```text
/Users/oric/git/palate/secrets/palate-oauth.json
```

Both files are under `secrets/`, which is ignored by git.

## Backups

The server can create a SQLite snapshot and a JSON export once per day while
running. Configure:

```sh
PALATE_BACKUP_ENABLED=1
PALATE_BACKUP_DIR=./backups
PALATE_BACKUP_RETENTION_DAYS=31
PALATE_BACKUP_INTERVAL_SECONDS=86400
```

If you use Google Drive Desktop sync instead of the API integration below,
point `PALATE_BACKUP_DIR` at a Drive-synced folder. Keep the live SQLite
database outside Google Drive; only sync timestamped snapshots.

### Google Drive API Backups

Palate can also upload the timestamped `.sqlite` and `.json` backup files
directly through the Google Drive API.

One-time setup:

1. Create or choose a Google Cloud project.
2. Enable the Google Drive API.
3. Create an OAuth client for a Desktop app.
4. Save the downloaded client JSON as:

```text
/Users/oric/git/palate/secrets/google-oauth-client.json
```

5. Authorize once from a normal user session:

```sh
python3 -m palate.google_drive
```

This opens a browser, stores a refresh token in:

```text
/Users/oric/git/palate/secrets/google-token.json
```

and creates or reuses the Drive folder path `backup/palate`.

Then enable Drive upload in the LaunchAgent by setting:

```text
PALATE_BACKUP_GOOGLE_DRIVE_ENABLED=1
```

and restart the service.

The Google Drive integration uses the limited `drive.file` OAuth scope, so it
only manages files/folders created by this app or explicitly selected for it.

## Example MCP Config

```json
{
  "mcpServers": {
    "palate": {
      "command": "python3",
      "args": ["-m", "palate.server"],
      "cwd": "/Users/oric/git/palate",
      "env": {
        "OPENAI_API_KEY": "your-openai-api-key",
        "OMDB_API_KEY": "your-omdb-api-key",
        "PALATE_DB_PATH": "./data/palate.sqlite",
        "PALATE_MODEL": "gpt-5.4-nano"
      }
    }
  }
}
```
