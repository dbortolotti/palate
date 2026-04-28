import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { buildGrounding, rankCandidates, retrieveCandidates } from "./core.js";
import { openStore } from "./storage.js";

test("option-set retrieval stays constrained to provided options", () => {
  const { store, cleanup } = makeStore();
  try {
    seedStore(store);
    const intent = baseIntent({ entity_type: "wine", attributes: ["oak"] });
    const retrieval = retrieveCandidates({
      store,
      intent,
      extractedEntities: [{ canonical_name: "Unknown Cellar Cabernet", type: "wine" }]
    });

    assert.equal(retrieval.constrained_to_options, true);
    assert.deepEqual(retrieval.unmatched_options, ["Unknown Cellar Cabernet"]);
    assert.equal(retrieval.candidates.length, 0);
  } finally {
    cleanup();
  }
});

test("upserted signals are idempotent", () => {
  const { store, cleanup } = makeStore();
  try {
    seedStore(store);
    seedStore(store);

    const wine = store.listEntities().find((entity) => entity.id === "wine_mike");
    assert.equal(wine.signals.length, 2);
  } finally {
    cleanup();
  }
});

test("recommended_by filters rankings to the requested person", () => {
  const { store, cleanup } = makeStore();
  try {
    seedStore(store);
    const intent = baseIntent({
      entity_type: "wine",
      filters: { min_rating: null, recommended_by: "Mike" }
    });
    const retrieval = retrieveCandidates({ store, intent });
    const ranked = buildGrounding(rankCandidates({ candidates: retrieval.candidates, intent }));

    assert.deepEqual(ranked.map((result) => result.id), ["wine_mike"]);
  } finally {
    cleanup();
  }
});

test("search_text narrows fuzzy recall candidates", () => {
  const { store, cleanup } = makeStore();
  try {
    seedStore(store);
    const intent = baseIntent({
      entity_type: "restaurant",
      search_text: "that place with a view"
    });
    const retrieval = retrieveCandidates({ store, intent });
    const ranked = buildGrounding(rankCandidates({ candidates: retrieval.candidates, intent }));

    assert.deepEqual(ranked.map((result) => result.id), ["restaurant_view"]);
  } finally {
    cleanup();
  }
});

test("decision choices update existing decision rows", () => {
  const { store, cleanup } = makeStore();
  try {
    seedStore(store);
    const decisionId = store.logDecision({
      query: "which wine",
      context: {},
      options: [],
      ranked: []
    });

    assert.equal(store.updateDecisionChoice(decisionId, "wine_mike"), 1);
    assert.equal(store.updateDecisionChoice(999999, "wine_mike"), 0);
  } finally {
    cleanup();
  }
});

function makeStore() {
  const dir = mkdtempSync(join(tmpdir(), "palate-"));
  const store = openStore(join(dir, "test.sqlite"));
  return {
    store,
    cleanup: () => rmSync(dir, { recursive: true, force: true })
  };
}

function seedStore(store) {
  store.upsertEntity({
    id: "wine_mike",
    type: "wine",
    canonical_name: "Mike's Cabernet",
    notes: "Cedar, oak, and premium structure.",
    attributes: { oak: 0.8, premium: 0.7 },
    signals: [
      { type: "rating", value: 4 },
      { type: "recommended_by", value: "Mike" }
    ]
  });
  store.upsertEntity({
    id: "wine_alex",
    type: "wine",
    canonical_name: "Alex's Syrah",
    notes: "Rich and intense.",
    attributes: { richness: 0.85, intensity: 0.8 },
    signals: [
      { type: "rating", value: 5 },
      { type: "recommended_by", value: "Alex" }
    ]
  });
  store.upsertEntity({
    id: "restaurant_view",
    type: "restaurant",
    canonical_name: "Skyline Room",
    notes: "Quiet place with a city view.",
    attributes: { view: 0.95, quiet: 0.6 },
    signals: [{ type: "rating", value: 4 }]
  });
  store.upsertEntity({
    id: "restaurant_loud",
    type: "restaurant",
    canonical_name: "Loud Counter",
    notes: "Lively casual dinner.",
    attributes: { lively: 0.9, casual: 0.7 },
    signals: [{ type: "rating", value: 5 }]
  });
}

function baseIntent(overrides = {}) {
  return {
    intent: "contextual_decision",
    attributes: [],
    context: {},
    filters: { min_rating: null, recommended_by: null },
    entity_type: null,
    search_text: "",
    ...overrides
  };
}
