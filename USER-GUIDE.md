# Palate User Guide

Palate is a personal taste memory and decision engine exposed through an MCP
connector. You do not normally call Palate tools by name. Instead, you prompt a
client LLM such as ChatGPT or Claude, and ask it to use Palate when the task is
about taste memory, recommendations, option evaluation, decision logging, or
backup.

Palate works best when the client LLM acts as the interface layer: it translates
your natural language into Palate's structured tools, then explains the grounded
results. Palate itself stores memory, retrieves candidates, ranks them
deterministically, and logs decisions.

## One-Time Client Instruction

Use this as a custom instruction, project instruction, or first message in a
thread where Palate is available:

```text
When I ask about wine, restaurants, music, cigars, or experiences, use the
Palate connector instead of relying on chat memory alone.

Use Palate to:
- remember explicit preferences, ratings, notes, and recommendations
- recall saved taste memories
- evaluate pasted option sets such as wine lists or restaurant shortlists
- recommend from existing memory using the current context
- log what I chose after a recommendation
- trigger a backup when I ask for one

Do not invent Palate memories or explanations. If Palate returns ranked results,
explain only using the signals Palate returned. If an option is not known to
Palate, say it is unmatched instead of replacing it with a different stored item.
```

If the client does not use Palate automatically, name it directly:

```text
Use Palate for this.
```

## Supported Domains

Palate currently supports these entity types:

- `wine`
- `restaurant`
- `music`
- `cigar`
- `experience`

It understands these fixed taste attributes:

- `oak`
- `premium`
- `richness`
- `intensity`
- `quiet`
- `lively`
- `intellectual`
- `indulgent`
- `novelty`
- `comfort`
- `view`
- `classic`
- `casual`

You can use natural language. For example, "a fancy oaky wine" can map to
`premium` and `oak`; "somewhere low-key with a view" can map to `quiet` and
`view`.

## Supported Tasks

### Ask For A Recommendation From Memory

Use this when you want Palate to rank known memories.

Good prompts:

```text
Use Palate. I want a premium oaky wine tonight. What should I open?
```

```text
Use Palate to recommend a restaurant for a quiet dinner with a view.
```

```text
Use Palate. I want something indulgent but not too lively. What experiences
match that?
```

Helpful details to include:

- the domain, such as wine or restaurant
- current mood or setting
- constraints like "quiet", "premium", "casual", or "with a view"
- minimum rating, if you care
- whose recommendation matters, if any

Example with filters:

```text
Use Palate. Find wines rated at least 4/5 that Mike recommended and that fit
an indulgent evening.
```

### Evaluate A Pasted Option Set

Use this for a wine list, menu, restaurant shortlist, album choices, cigar list,
or any bounded set of options.

Good prompts:

```text
Use Palate to evaluate this wine list for a premium oaky bottle tonight:

Vietti Barolo 2016
Gaja Barbaresco 2018
Ridge Monte Bello 2019
```

```text
Use Palate. Which of these restaurants best fits a quiet dinner with a view?

Skyline Room
Loud Counter
Noble Rot
```

Important behavior:

- Palate keeps option-set evaluation constrained to the pasted options.
- If an option is not already known, Palate reports it as unmatched.
- It should not recommend a stored item that was not in your pasted list.

If you want unknown options remembered later, say so explicitly:

```text
After evaluating these, ask me which unknown options I want to add to Palate.
```

### Remember A New Preference Or Item

Use this when you want to store a memory.

Good prompts:

```text
Use Palate to remember this wine:
Name: Ridge Estate Cabernet 2019
Type: wine
Rating: 4.5/5
Notes: premium, structured, cedar, oak, long finish
Recommended by: Mike
```

```text
Use Palate to remember Skyline Room as a restaurant. I liked it: 4/5. Notes:
quiet, great city view, good for low-energy evenings.
```

```text
Use Palate to remember Alex's Syrah as a wine with rating 2/5. Notes: too
heavy for me, intense, not a good fit for low-energy evenings.
```

Best practice:

- Give the canonical name.
- Give the entity type.
- Include a rating if you have one.
- Include who recommended it, if relevant.
- Include concrete notes. Palate can normalize those notes into its fixed
  attributes.

The client LLM may create a stable internal ID for the item. If you want to be
explicit, you can provide one:

```text
Use Palate to remember this as id wine_ridge_estate_cabernet_2019:
Ridge Estate Cabernet 2019, wine, 4.5/5, premium and oaky.
```

### Recall Something Fuzzy

Use this when you half-remember something already saved.

Good prompts:

```text
Use Palate. What was that restaurant with a view I saved?
```

```text
Use Palate to recall the wine Mike suggested that had cedar notes.
```

```text
Use Palate. Find the music I saved that felt intellectual but comforting.
```

Helpful details:

- approximate name fragments
- recommender name
- sensory notes
- setting or mood
- entity type

If Palate cannot narrow the memory, ask the client to show the top candidates
and the matching signals:

```text
Use Palate to recall this, and show me the matched signals for each candidate.
```

### Normalize Or Enrich Item Notes

Use this when you want noisy description text converted into Palate's fixed
attribute schema before storing or comparing it.

Good prompts:

```text
Use Palate to enrich this wine description:
"Rich, bold, cedar, vanilla oak, long finish, expensive-feeling."
```

```text
Use Palate to normalize this restaurant note:
"Quiet room, city view, formal but comfortable, not very lively."
```

This is useful when:

- you pasted tasting notes
- you copied a restaurant description
- you want to check how Palate interprets the attributes before storing the item

### Log What You Chose

Use this after a recommendation or option evaluation. This is important because
it strengthens the learning loop.

Good prompts:

```text
Use Palate to log that I chose the top recommendation.
```

```text
Use Palate to log that I chose Ridge Estate Cabernet 2019 from that decision.
```

```text
Use Palate to log decision_id 42 as chosen_entity_id wine_ridge_estate_cabernet_2019.
```

Best practice:

- If the previous Palate response included a `decision_id`, ask the client to
  log the choice against that decision.
- If there was no previous decision, give the chosen item name or ID and a short
  description of the context.

### Create A Backup

Use this when you want an immediate backup outside the daily schedule.

Good prompts:

```text
Use Palate to create a backup now.
```

```text
Please run a Palate backup and tell me whether the SQLite and JSON snapshots
were created.
```

If Google Drive backups are enabled, Palate will also upload the snapshot files
to the configured Drive folder.

## Prompt Patterns That Work Well

### Contextual Decision

```text
Use Palate. I am choosing a [domain] for [situation]. I want something
[attributes/mood/context]. Rank the best matches and explain the actual signals.
```

Example:

```text
Use Palate. I am choosing a wine for tonight. I want something premium, oaky,
and indulgent. Rank the best matches and explain the actual signals.
```

### Option Set Evaluation

```text
Use Palate. Evaluate only the options below for [goal/context]. If any options
are unknown to Palate, list them as unmatched.

[paste options]
```

### Memory Capture

```text
Use Palate to remember:
Name:
Type:
Rating:
Recommended by:
Notes:
```

### Fuzzy Recall

```text
Use Palate to recall [approximate memory]. I think it was [domain/person/note].
Show the matched signals.
```

### Decision Logging

```text
Use Palate to log that I chose [item name or ID] for decision_id [number].
```

## What To Avoid

Avoid asking the client LLM to decide without Palate:

```text
Pick the best wine from memory.
```

Better:

```text
Use Palate to rank my known wines for a premium oaky mood tonight.
```

Avoid asking for unsupported attributes as if they are native Palate fields:

```text
Find something mineral, saline, and high-acid.
```

Better:

```text
Use Palate. Find wines whose notes mention mineral, saline, or high-acid, and
also consider novelty and classic if relevant.
```

Avoid vague logging:

```text
I picked that one.
```

Better:

```text
Use Palate to log that I chose the first ranked result from the last Palate
decision.
```

## How To Read Palate Results

Palate responses usually include:

- `decision_id`: use this later when logging what you chose
- `ranked_results`: the top grounded results
- `matched_attributes`: attributes that contributed to the ranking
- `signal_facts`: ratings, recommendations, saved/tried signals, or text matches
- `negative_signals`: reasons an item was penalized or excluded
- `unmatched_options`: pasted options that Palate could not match to memory

Ask the client to show these fields when you want a more debuggable answer:

```text
Use Palate and show the decision_id, matched attributes, signal facts, and any
unmatched options.
```

## Troubleshooting Client Behavior

If the client answers from general knowledge instead of Palate, say:

```text
Please use the Palate connector for this and ground the answer in Palate's
returned signals.
```

If the client recommends something outside a pasted list, say:

```text
Use Palate's option-set evaluation. Only rank items from the pasted list and
report unknown items as unmatched.
```

If the client gives a vague explanation, say:

```text
Show the Palate signal facts and matched attributes behind that ranking.
```

If the client does not log your choice, say:

```text
Use Palate to log my chosen item against the previous decision_id.
```

## Quick Examples

```text
Use Palate. What wine should I open tonight if I want premium, oak, and comfort?
```

```text
Use Palate. Evaluate this list for a quiet, indulgent dinner wine:

Ridge Estate Cabernet 2019
Vietti Barolo 2016
Gaja Barbaresco 2018
```

```text
Use Palate to remember Noble Rot as a restaurant, 4.5/5, classic, comfortable,
good wine list, not too lively.
```

```text
Use Palate. What was that place with the city view I saved?
```

```text
Use Palate to log that I chose the top-ranked option from the last decision.
```

```text
Use Palate to create a backup now.
```
