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

## Setup

```sh
npm install
cp .env.example .env
npm run seed
```

Set `OPENAI_API_KEY` in `.env` before using tools that require the LLM.

## Run

```sh
npm start
```

## Verify

```sh
npm run check
npm test
```

## MCP Tools

- `palate_query`: interpret a free-form taste query, rank memory, and explain results
- `palate_evaluate_options`: extract and evaluate a pasted option set
- `palate_remember`: store a taste memory, optionally normalizing raw description text
- `palate_recall`: recall matching explicit memory
- `palate_enrich_item`: normalize noisy text into the fixed attribute schema
- `palate_log_decision`: record what the user chose

Option-set tools stay constrained to the provided options. If a pasted option is not already in memory, Palate reports it as unmatched instead of substituting unrelated stored items.

## Example MCP Config

```json
{
  "mcpServers": {
    "palate": {
      "command": "npm",
      "args": ["start"],
      "cwd": "/Users/oric/git/palate",
      "env": {
        "OPENAI_API_KEY": "sk-...",
        "PALATE_DB_PATH": "./data/palate.sqlite",
        "PALATE_MODEL": "gpt-5.5"
      }
    }
  }
}
```
