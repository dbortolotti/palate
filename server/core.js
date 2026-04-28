export function retrieveCandidates({ store, intent, extractedEntities = [] }) {
  if (extractedEntities.length > 0) {
    const matched = store.findEntitiesByNames(extractedEntities.map((item) => item.canonical_name ?? item.name ?? item));
    if (matched.length > 0) return matched;
  }
  return store.listEntities().filter((entity) => {
    if (!intent.entity_type) return true;
    return entity.type === intent.entity_type;
  });
}

export function rankCandidates({ candidates, intent }) {
  const avoidBelow = intent.filters?.min_rating;
  const required = intent.attributes ?? [];
  const context = intent.context ?? {};

  return candidates
    .map((entity) => {
      const facts = scoreEntity(entity, { required, context, avoidBelow });
      return { entity, score: facts.total, facts };
    })
    .filter((result) => !result.facts.excluded)
    .sort((a, b) => b.score - a.score);
}

function scoreEntity(entity, { required, context, avoidBelow }) {
  const facts = {
    preference: 0,
    attribute_match: 0,
    context_match: 0,
    provenance: 0,
    familiarity: 0,
    penalties: 0,
    matched_attributes: [],
    negative_signals: [],
    signal_facts: [],
    excluded: false,
    total: 0
  };

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
      facts.provenance += 0.25;
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

  facts.total = round(
    facts.preference * 1.4
    + facts.attribute_match
    + facts.context_match
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
