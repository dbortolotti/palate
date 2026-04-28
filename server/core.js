export function retrieveCandidates({ store, intent, extractedEntities = [] }) {
  if (extractedEntities.length > 0) {
    const optionNames = extractedEntities.map((item) => item.canonical_name ?? item.name ?? item);
    const { matched, unmatched } = store.matchEntitiesByNames(optionNames);
    return {
      candidates: filterByType(matched, intent.entity_type),
      unmatched_options: unmatched,
      constrained_to_options: true
    };
  }

  const typed = filterByType(store.listEntities(), intent.entity_type);
  const searched = applySearchText(typed, intent.search_text);
  return {
    candidates: searched,
    unmatched_options: [],
    constrained_to_options: false
  };
}

export function rankCandidates({ candidates, intent }) {
  const avoidBelow = intent.filters?.min_rating;
  const recommendedBy = intent.filters?.recommended_by;
  const required = intent.attributes ?? [];
  const context = intent.context ?? {};
  const searchText = intent.search_text ?? "";

  return candidates
    .map((entity) => {
      const facts = scoreEntity(entity, { required, context, avoidBelow, recommendedBy, searchText });
      return { entity, score: facts.total, facts };
    })
    .filter((result) => !result.facts.excluded)
    .sort((a, b) => b.score - a.score);
}

function scoreEntity(entity, { required, context, avoidBelow, recommendedBy, searchText }) {
  const facts = {
    preference: 0,
    attribute_match: 0,
    context_match: 0,
    search_match: 0,
    provenance: 0,
    familiarity: 0,
    penalties: 0,
    matched_attributes: [],
    negative_signals: [],
    signal_facts: [],
    excluded: false,
    total: 0
  };
  let matchedRecommendedBy = false;

  for (const signal of entity.signals ?? []) {
    if (signal.type === "rating") {
      const rating = Number(signal.value);
      if (Number.isFinite(rating)) {
        facts.preference = Math.max(facts.preference, (rating - 3) / 2);
        facts.signal_facts.push(`rating ${rating}/5`);
        if (avoidBelow && rating < avoidBelow) {
          facts.excluded = true;
          facts.negative_signals.push(`rating below ${avoidBelow}`);
        }
      }
    }
    if (signal.type === "dislike") {
      facts.penalties -= 1.5;
      facts.negative_signals.push(signal.value);
    }
    if (signal.type === "recommended_by") {
      const matchesRequestedPerson = recommendedBy && normalize(signal.value) === normalize(recommendedBy);
      matchedRecommendedBy = matchedRecommendedBy || matchesRequestedPerson;
      facts.provenance += matchesRequestedPerson ? 0.6 : 0.25;
      facts.signal_facts.push(`recommended by ${signal.value}`);
    }
    if (signal.type === "saved") {
      facts.familiarity += 0.15;
      facts.signal_facts.push("saved");
    }
    if (signal.type === "tried") {
      facts.familiarity += 0.1;
      facts.signal_facts.push("tried before");
    }
  }

  if (recommendedBy && !matchedRecommendedBy) {
    facts.excluded = true;
    facts.negative_signals.push(`not recommended by ${recommendedBy}`);
  }

  for (const attr of required) {
    const value = Number(entity.attributes?.[attr] ?? 0);
    if (value > 0) {
      facts.attribute_match += value;
      facts.matched_attributes.push(`${attr}: ${value.toFixed(2)}`);
    }
  }

  for (const [key, wanted] of Object.entries(context)) {
    if (wanted === true && Number(entity.attributes?.[key] ?? 0) > 0) {
      const value = Number(entity.attributes[key]);
      facts.context_match += value * 0.5;
      facts.matched_attributes.push(`context ${key}: ${value.toFixed(2)}`);
    }
  }

  facts.search_match = scoreTextMatch(entity, searchText);
  if (facts.search_match > 0) {
    facts.signal_facts.push(`matched memory text: ${facts.search_match.toFixed(2)}`);
  }

  facts.total = round(
    facts.preference * 1.4
    + facts.attribute_match
    + facts.context_match
    + facts.search_match
    + facts.provenance
    + facts.familiarity
    + facts.penalties
  );
  return facts;
}

export function buildGrounding(results) {
  return results.slice(0, 5).map((result) => ({
    id: result.entity.id,
    name: result.entity.canonical_name,
    type: result.entity.type,
    score: result.score,
    matched_attributes: result.facts.matched_attributes,
    signal_facts: result.facts.signal_facts,
    negative_signals: result.facts.negative_signals
  }));
}

function round(value) {
  return Math.round(value * 100) / 100;
}

function filterByType(entities, entityType) {
  if (!entityType) return entities;
  return entities.filter((entity) => entity.type === entityType);
}

function applySearchText(entities, searchText) {
  const tokens = tokenize(searchText);
  if (tokens.length === 0) return entities;

  const matches = entities.filter((entity) => scoreTextMatch(entity, searchText) > 0);
  return matches.length > 0 ? matches : entities;
}

function scoreTextMatch(entity, searchText) {
  const tokens = tokenize(searchText);
  if (tokens.length === 0) return 0;

  const haystack = normalize([
    entity.canonical_name,
    entity.source_text,
    entity.notes,
    Object.keys(entity.attributes ?? {}).filter((key) => Number(entity.attributes[key]) > 0.55).join(" "),
    ...(entity.signals ?? []).map((signal) => `${signal.type} ${signal.value} ${signal.provenance ?? ""}`)
  ].filter(Boolean).join(" "));
  const matched = tokens.filter((token) => haystack.includes(token));
  return matched.length / tokens.length;
}

function tokenize(value) {
  return normalize(value)
    .split(" ")
    .filter((token) => token.length > 2 && !STOP_WORDS.has(token));
}

function normalize(value) {
  return String(value ?? "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
}

const STOP_WORDS = new Set([
  "the",
  "and",
  "for",
  "with",
  "that",
  "this",
  "what",
  "which",
  "thing",
  "things",
  "place",
  "places",
  "something"
]);
