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
When I ask about wine, restaurants, music, cigars, experiences, movies, or
series, use the Palate connector instead of relying on chat memory alone.

Use Palate to:
- remember explicit preferences, ratings, notes, and recommendations
- look up the computed Palate record without storing it when I explicitly say
  not to store it
- recall saved taste memories
- evaluate pasted option sets such as wine lists or restaurant shortlists
- recommend from existing memory using the current context
- log what I chose after a recommendation
- delete explicit memories by exact ID when I ask
- trigger a backup when I ask for one

Do not invent Palate memories or explanations. If Palate returns ranked results,
explain only using the signals Palate returned. If an option is not known to
Palate, say it is unmatched instead of replacing it with a different stored item.
When remembering an item and my experience or score is missing, ask one
follow-up: "How do you rate it from 1-10? Answer no if you have not tried it."
For movies and series, treat "tried it" as "watched it." Do not send manual
attributes; Palate derives attributes from the description.
Use lookup without storing only when I explicitly ask you not to store the item.
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
- `movie`
- `series`

It understands different fixed taste attributes for each entity type:

- `wine`: `premium`, `classic`, `body`, `tannin`, `acidity`, `oak`, plus
  level-1 wine aroma wheel terms: `fruity`, `floral`, `spicy`, `vegetative`,
  `nutty`, `caramelized`, `woody`, `earthy`, `chemical`, `pungent`,
  `oxidized`, `microbiological`
- `restaurant`: `premium`, `quiet`, `lively`, `indulgent`, `novelty`,
  `comfort`, `view`, `classic`, `casual`
- `music`: `quiet`, `lively`, `intellectual`, `comfort`, `classic`,
  `novelty`, `intensity`, `indulgent`
- `cigar`: `premium`, `richness`, `intensity`, `classic`, `indulgent`,
  `novelty`, `comfort`
- `experience`: `premium`, `intensity`, `quiet`, `lively`, `intellectual`,
  `indulgent`, `novelty`, `comfort`, `view`, `classic`, `casual`
- `movie`: `intense`, `suspenseful`, `cerebral`, `emotional`, `funny`,
  `dark`, `light`, `slow_burn`, `action`, `comfort`, `novelty`, `classic`
- `series`: `intense`, `suspenseful`, `cerebral`, `emotional`, `funny`,
  `dark`, `light`, `slow_burn`, `serialized`, `comfort`, `novelty`,
  `classic`

You can use natural language. For example, "a fancy full-bodied oaky wine with
firm tannin" can map to wine `premium`, `body`, `oak`, and `tannin`;
"somewhere low-key with a view" can map to restaurant `quiet` and `view`; "a
tense cerebral film" can map to movie `suspenseful` and `cerebral`.

Movies and series can also store structured metadata:

- synopsis
- main actors
- director
- country list
- language
- genre
- runtime in minutes
- season count for series
- watched status and watched date
- IMDb ID
- external IMDb and Rotten Tomatoes critic ratings from OMDb

Movie and series genres are normalized to this subset:

```text
action, adventure, animation, biography, comedy, crime, documentary, drama,
family, fantasy, history, horror, music, musical, mystery, romance, sci_fi,
sport, thriller, war, western
```

Music can also store structured metadata:

- artist
- album
- personnel
- genre

Music genres are normalized to this subset:

```text
ambient, blues, classical, country, dance, electronic, experimental, folk,
funk, hip_hop, jazz, latin, metal, pop, punk, r_and_b, reggae, rock, soul,
soundtrack, world
```

Your own 1-10 `rating` remains the personal taste signal. IMDb and Rotten
Tomatoes are stored as external reference data and only break ties between
otherwise similar Palate matches.

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
Use Palate. Find wines rated at least 8/10 that Mike recommended and that fit
a premium, full-bodied evening.
```

### Evaluate A Pasted Option Set

Use this for a wine list, menu, restaurant shortlist, album choices, movie or
series shortlist, cigar list, or any bounded set of options.

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

```text
Use Palate. Which of these movies best fits a slow-burn, cerebral evening?

Heat
Inception
Tinker Tailor Soldier Spy
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
Tried: true
Rating: 9/10
Notes: premium, structured, full-bodied, cedar, oak, long finish
Recommended by: Mike
```

```text
Use Palate to remember Skyline Room as a restaurant. Tried: true. I liked it:
8/10. Notes: quiet, great city view, good for low-energy evenings.
```

```text
Use Palate to remember Alex's Syrah as a wine. Tried: true. Rating: 4/10.
Notes: too full-bodied for me, spicy, not a good fit for low-energy evenings.
```

```text
Use Palate to remember this watched movie:
Name: Heat
Type: movie
Description: intense, precise, classic Los Angeles crime film
Rating: 10/10
Watched: true
Director: Michael Mann
Main actors: Al Pacino, Robert De Niro, Val Kilmer
Country: United States
Language: English, Spanish
Genre: crime, drama, thriller
Runtime: 170
IMDb ID: tt0113277
Notes: loved the structure and atmosphere.
```

```text
Use Palate to remember Severance as an unwatched series. Fetch IMDb and Rotten
Tomatoes ratings if available. Notes: quiet, intellectual, unsettling workplace
mystery.
```

```text
Use Palate to remember this music:
Name: Kind of Blue
Type: music
Description: spacious modal jazz album led by Miles Davis
Artist: Miles Davis
Album: Kind of Blue
Personnel: Miles Davis, John Coltrane, Cannonball Adderley, Bill Evans
Genre: jazz
Tried: true
Rating: 10/10
```

Best practice:

- Give the canonical name.
- Give the entity type.
- Give a description. Palate requires this for every new memory.
- Before calling `palate_remember`, ask one follow-up when experience or score
  is missing: "How do you rate it from 1-10? Answer no if you have not tried
  it." For movies and series, "tried it" means "watched it."
- If the user gives a number, include it as `rating`. Palate marks movies and
  series as watched and other record types as tried when a rating is present.
- If the user answers no, set `watched=false` for movies and series or
  `tried=false` for other record types, and do not include a personal rating.
- Include who recommended it, if relevant.
- Include concrete notes. When you can confidently map the item to Palate's
  fixed attribute schema, pass `attributes` and optional `attribute_intervals_95`
  directly. Palate validates allowed keys by entity type and stores only valid
  attributes. If you omit attributes, Palate uses its server LLM to derive them
  from the description.
- For movies and series, include watched status or watched date when known. If
  you provide your own rating, Palate marks the item as watched.
- For music, include artist, album, personnel, and genre when known.

The client LLM may create a stable internal ID for the item. If you want to be
explicit, you can provide one:

```text
Use Palate to remember this as id wine_ridge_estate_cabernet_2019:
Ridge Estate Cabernet 2019, wine, tried, 9/10, premium, full-bodied, and oaky.
```

### Lookup Without Storing

Use this when the user wants Palate to compute the normalized record, attributes,
metadata, signals, or external media ratings, but explicitly says not to store
the item. Do not use this as a default preview before remembering.

Good prompts:

```text
Use Palate to look this up but do not store it:
Name: Heat
Type: movie
Description: intense, precise, classic Los Angeles crime film
Rating: 10/10
Director: Michael Mann
IMDb ID: tt0113277
```

Best practice:

- Call `palate_lookup` only when the user explicitly says not to store the item.
- Set `do_not_store=true`.
- Follow the same rating and metadata guidance as `palate_remember`.
- Pass `attributes` and optional `attribute_intervals_95` when you can map them
  confidently; omit them when you want Palate's server LLM to enrich the item.

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

```text
Use Palate. What movie did I save with Robert De Niro and Michael Mann?
```

```text
Use Palate. Recall the British spy film I saved.
```

```text
Use Palate. Find series I saved in the mystery or sci-fi genre.
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
"Full-bodied, cedar, vanilla oak, long finish, expensive-feeling."
```

```text
Use Palate to normalize this restaurant note:
"Quiet room, city view, formal but comfortable, not very lively."
```

This is useful when:

- you pasted tasting notes
- you copied a restaurant description
- you want to check how Palate interprets the attributes and 95% intervals
  before storing the item

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

### Delete A Memory

Use this when you want to remove one saved Palate record. Deletion uses the
exact internal entity ID, not fuzzy title matching.

Good prompts:

```text
Use Palate to delete record wine_ridge_estate_cabernet_2019.
```

```text
Use Palate to delete the Palate record with id movie_heat_1995.
```

Best practice:

- Recall the item first if you do not know the exact ID.
- Create a backup first if the record matters and you may want to recover it.

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
Use Palate. I am choosing a wine for tonight. I want something premium,
full-bodied, oaky, and woody. Rank the best matches and explain the actual
signals.
```

Cost-aware client behavior:

- Prefer passing a parsed `intent` to `palate_query`, `palate_evaluate_options`,
  and `palate_recall` when the entity type, attributes, filters, and search text
  are clear. This avoids a server LLM intent-parsing call.
- Prefer passing `extracted_entities` to `palate_evaluate_options` when you can
  identify the option names from the pasted list. This avoids a server LLM
  entity-extraction call.
- Leave `explain=false` unless the user explicitly asks Palate itself to write
  the explanation. You can explain the returned grounded JSON in the client.
- For memory capture, pass valid `attributes` and `attribute_intervals_95` when
  confident. Omit them when server-side enrichment quality matters more than
  cost.
- Check `server_llm_used` in tool responses when auditing cost.

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
Description:
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

### Record Deletion

```text
Use Palate to delete record [exact entity ID].
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
Use Palate. Find wines with high acidity whose notes mention mineral or saline,
and also consider earthy and classic if relevant.
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
- `matched_attributes`: attributes that contributed to the ranking, including
  95% intervals
- `attribute_intervals_95` and `attribute_details`: interval and value detail
  for stored attributes
- `signal_facts`: ratings, recommendations, saved/tried signals, or text matches
- `memory_status`: whether this is something you wanted to try/watch, already
  tried/watched, liked, or disliked. Palate infers "want to try" from an item
  being stored without a rating or tried/watched signal.
- `metadata`: movie and series metadata, music artist/album/personnel/genre,
  and external ratings when stored
- `negative_signals`: reasons an item was penalized or excluded
- `unmatched_options`: pasted options that Palate could not match to memory

Ask the client to show these fields when you want a more debuggable answer:

```text
Use Palate and show the decision_id, matched attributes, signal facts, and any
unmatched options.
```

When evaluating a photo or pasted menu, always surface `memory_status` in the
client answer. In particular, call out:

- items already stored but not tried as "you wanted to try this"
- items with a good rating as "you tried this and liked it"
- items with a low rating or dislike signal as a caution

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
Use Palate. What wine should I open tonight if I want premium, body, oak, and
woody notes?
```

```text
Use Palate. Evaluate this list for a premium, full-bodied dinner wine:

Ridge Estate Cabernet 2019
Vietti Barolo 2016
Gaja Barbaresco 2018
```

```text
Use Palate to remember Noble Rot as a restaurant, tried, 9/10, classic,
comfortable, good wine list, not too lively.
```

```text
Use Palate. What was that place with the city view I saved?
```

```text
Use Palate. Evaluate this series shortlist for something slow-burn and cerebral:

Severance
Slow Horses
The Bear
```

```text
Use Palate to log that I chose the top-ranked option from the last decision.
```

```text
Use Palate to delete record movie_heat_1995.
```

```text
Use Palate to create a backup now.
```
