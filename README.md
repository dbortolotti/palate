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
- deterministic ranking, including uncertainty discounts from 95% attribute intervals
- negative filtering
- decision logging and lightweight revealed-preference feedback
- structured application event logging for future ranking and enrichment evals

Movie and series memories can store structured metadata plus OMDb-backed IMDb
and Rotten Tomatoes critic ratings. External ratings are stored as reference
metadata only; the personal 1-10 `rating` signal remains the taste score.
OMDb also fills country list, language, runtime, and series season count when available.
Music memories can store artist, album, personnel, and genre metadata.
Restaurant memories can store cuisine as scored metadata `cuisine`, with
`other` used when no cuisine category reaches the 40% match threshold. Cuisine
can be multi-label, so a restaurant can be both `italian` and
`vegetarian_vegan` with separate confidence intervals.
Unknown restaurant enrichment uses Responses web search to ground cuisine,
menu, price tier, ambiance, and setting before scoring attributes. Lookup and
describe responses return any consulted web `sources`; stored memory keeps the
normalized Palate record rather than source URLs.

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

- `palate_query`: rank memory from a free-form taste query; pass parsed intent from the client to avoid server LLM parsing
- `palate_evaluate_options`: evaluate a pasted option set; pass extracted entities from the client to avoid server LLM extraction
- `palate_remember`: store a taste memory with required description text, optional watched/tried status, personal rating, client-supplied or server-derived attributes, and optional OMDb movie or series ratings
- `palate_lookup`: compute the Palate record, attributes, metadata, and signals without storing; use only when the user explicitly says not to store
- `palate_describe_item`: read-only item description; returns existing memory when found, otherwise fills missing fields/enriches the item and returns a suggested `palate_remember` payload without storing
- `palate_recall`: recall matching explicit memory
- `palate_delete_record`: delete one explicit memory by exact entity ID
- `palate_log_decision`: record what the user chose
- `palate_backup_now`: create an immediate SQLite and JSON backup
- `palate_how_to`: return the user guide and prompt patterns for client LLMs

The same guide is also exposed as the MCP resource `palate://how-to`.

Option-set tools stay constrained to the provided options. If a pasted option is not already in memory, Palate reports it as unmatched instead of substituting unrelated stored items.

Server LLM calls are optional on the common path. Query, option evaluation, and
recall tools accept client-supplied `intent`; option tools accept
`extracted_entities`; memory tools accept validated `attributes` and
`attribute_intervals_95`. Explanations default to off so the client can explain
grounded JSON without a paid server call. Responses include `server_llm_used`
for cost auditing.

Ranked results include `memory_status` so menu/photo evaluations can distinguish
"you wanted to try this" from "you tried this and liked it." The wanted-to-try
state is inferred from a stored item that has no rating or tried/watched signal.
Option matching returns transient `option_matches` confidence metadata:
confident matches are 85% or higher, 50-85% matches are returned in
`needs_confirmation`, and matches below 50% are discarded as unmatched.

## Application Log

Palate writes structured tool-call events to the SQLite `application_events`
table. Each event records the tool name, success/error status, duration,
input JSON, output JSON, error JSON, metadata, and timestamp. This is intended
for future evals and tuning: ranking calls include parsed intent, retrieval,
ranked results, match confidence, and server LLM usage; enrichment and remember
calls include normalized attributes and intervals. `palate_how_to` logs only
content metadata, not the full guide text.

## Ranking Eval

Ranking changes can be checked with a deterministic eval set. Cases provide a
parsed intent, so the harness does not call the LLM.

```json
[
  {
    "name": "oaky wine",
    "query": "oaky wine",
    "intent": {
      "attributes": ["oak"],
      "context": {},
      "filters": {"min_rating": null, "recommended_by": null, "cuisine": []},
      "entity_type": "wine",
      "search_text": ""
    },
    "expected_top_3": ["wine_mike", "wine_alex"]
  }
]
```

Run:

```sh
python3 -m palate.eval eval-cases.json --db ./data/palate.sqlite
python3 -m palate.eval eval-cases.json --db ./data/palate.sqlite --sweep
# or, after package install:
palate-eval eval-cases.json --db ./data/palate.sqlite --sweep
```

The report includes mean NDCG@3, top-3 overlap, and per-case actual versus
expected rankings. The sweep grids over the main ranking weights and prints the
best configurations first.

## Deployment

This repo includes a macOS LaunchAgent template and Tailscale Funnel notes in [deploy/README.md](deploy/README.md).

## MCP Auth

When `PALATE_AUTH_ENABLED=1`, Palate exposes an OAuth 2.1 flow for remote MCP
clients such as ChatGPT. The public connector URL is:

```text
https://modal.tail63a6b7.ts.net/palate/mcp
```

The first connection opens a Palate login page. The password is read from:

```text
secrets/palate-auth-password
```

OAuth client registrations and issued tokens are stored in:

```text
secrets/palate-oauth.json
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
secrets/google-oauth-client.json
```

5. Authorize once from a normal user session:

```sh
python3 -m palate.google_drive
```

This opens a browser, stores a refresh token in:

```text
secrets/google-token.json
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
      "cwd": ".",
      "env": {
        "OPENAI_API_KEY": "your-openai-api-key",
        "OMDB_API_KEY": "your-omdb-api-key",
        "PALATE_DB_PATH": "./data/palate.sqlite",
        "PALATE_MODEL": "gpt-5.4-mini"
      }
    }
  }
}
```
