import "dotenv/config";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import { buildGrounding, rankCandidates, retrieveCandidates } from "./core.js";
import { explainResults, extractEntities, normalizeEnrichment, parseIntent } from "./llm.js";
import { ENTITY_TYPES } from "./schema.js";
import { openStore } from "./storage.js";

const store = openStore();

const server = new McpServer({
  name: "palate",
  version: "0.1.0"
});

server.registerTool(
  "palate_query",
  {
    title: "Query Palate",
    description: "Interpret a taste query with the LLM, rank matching memory deterministically, and return grounded explanations.",
    inputSchema: {
      query: z.string().min(1),
      context: z.record(z.unknown()).optional(),
      options_text: z.string().optional(),
      explain: z.boolean().default(true)
    }
  },
  async ({ query, context = {}, options_text, explain = true }) => {
    const intent = await parseIntent({ query, context });
    const extraction = options_text
      ? await extractEntities({ text: options_text, expectedType: intent.entity_type })
      : { entities: [] };

    const retrieval = retrieveCandidates({
      store,
      intent,
      extractedEntities: extraction.entities
    });
    const ranked = rankCandidates({ candidates: retrieval.candidates, intent });
    const grounding = buildGrounding(ranked);
    const explanation = explain
      ? await explainResults({ query, intent, grounding })
      : null;

    const decisionId = store.logDecision({
      query,
      context,
      options: extraction.entities,
      ranked: grounding
    });

    return json({
      decision_id: Number(decisionId),
      intent,
      extracted_entities: extraction.entities,
      retrieval: describeRetrieval(retrieval),
      ranked_results: grounding,
      explanation
    });
  }
);

server.registerTool(
  "palate_evaluate_options",
  {
    title: "Evaluate Options",
    description: "Extract entities from a pasted option set with the LLM, then rank known matching options deterministically.",
    inputSchema: {
      query: z.string().min(1),
      options_text: z.string().min(1),
      context: z.record(z.unknown()).optional()
    }
  },
  async ({ query, options_text, context = {} }) => {
    const intent = await parseIntent({ query, context });
    const extraction = await extractEntities({ text: options_text, expectedType: intent.entity_type });
    const retrieval = retrieveCandidates({ store, intent, extractedEntities: extraction.entities });
    const ranked = rankCandidates({ candidates: retrieval.candidates, intent });
    const grounding = buildGrounding(ranked);
    const explanation = await explainResults({ query, intent, grounding });

    const decisionId = store.logDecision({
      query,
      context,
      options: extraction.entities,
      ranked: grounding
    });

    return json({
      decision_id: Number(decisionId),
      intent,
      extracted_entities: extraction.entities,
      retrieval: describeRetrieval(retrieval),
      ranked_results: grounding,
      explanation
    });
  }
);

server.registerTool(
  "palate_remember",
  {
    title: "Remember Item",
    description: "Store an explicit Palate memory. If description text is provided, the LLM normalizes it into the fixed attribute schema.",
    inputSchema: {
      id: z.string().min(1),
      type: z.enum(ENTITY_TYPES),
      canonical_name: z.string().min(1),
      description: z.string().optional(),
      attributes: z.record(z.number().min(0).max(1)).optional(),
      rating: z.number().min(1).max(5).optional(),
      recommended_by: z.string().optional(),
      notes: z.string().optional()
    }
  },
  async ({ id, type, canonical_name, description, attributes = {}, rating, recommended_by, notes }) => {
    const enrichment = description
      ? await normalizeEnrichment({ itemText: description, entityType: type })
      : { attributes: {}, notes: "" };

    const signals = [];
    if (rating !== undefined) signals.push({ type: "rating", value: rating });
    if (recommended_by) signals.push({ type: "recommended_by", value: recommended_by });

    store.upsertEntity({
      id,
      type,
      canonical_name,
      source_text: description,
      notes: notes ?? enrichment.notes,
      attributes: { ...enrichment.attributes, ...attributes },
      signals
    });

    return json({
      stored: true,
      id,
      normalized_attributes: enrichment.attributes
    });
  }
);

server.registerTool(
  "palate_recall",
  {
    title: "Recall Memory",
    description: "Recall explicit Palate memory. The query is interpreted by the LLM, while retrieval/ranking remain deterministic.",
    inputSchema: {
      query: z.string().min(1),
      context: z.record(z.unknown()).optional()
    }
  },
  async ({ query, context = {} }) => {
    const intent = await parseIntent({ query, context });
    const retrieval = retrieveCandidates({ store, intent });
    const ranked = rankCandidates({ candidates: retrieval.candidates, intent });
    const grounding = buildGrounding(ranked);
    return json({ intent, retrieval: describeRetrieval(retrieval), results: grounding });
  }
);

server.registerTool(
  "palate_enrich_item",
  {
    title: "Enrich Item",
    description: "Use the LLM to normalize noisy item text into Palate's fixed attribute schema.",
    inputSchema: {
      item_text: z.string().min(1),
      entity_type: z.enum(ENTITY_TYPES)
    }
  },
  async ({ item_text, entity_type }) => {
    return json(await normalizeEnrichment({ itemText: item_text, entityType: entity_type }));
  }
);

server.registerTool(
  "palate_log_decision",
  {
    title: "Log Decision",
    description: "Record the user's chosen item after a recommendation or evaluation.",
    inputSchema: {
      decision_id: z.number().optional(),
      query: z.string().default(""),
      chosen_entity_id: z.string().min(1),
      context: z.record(z.unknown()).optional()
    }
  },
  async ({ decision_id, query = "", chosen_entity_id, context = {} }) => {
    let id = decision_id;
    let updated_existing_decision = false;

    if (decision_id !== undefined) {
      const changes = store.updateDecisionChoice(decision_id, chosen_entity_id);
      if (changes === 0) {
        return json({
          logged: false,
          error: `No decision found for decision_id ${decision_id}.`
        });
      }
      updated_existing_decision = true;
    } else {
      id = store.logDecision({
        query,
        context,
        options: [],
        ranked: [],
        chosen_entity_id
      });
    }

    store.addSignal(chosen_entity_id, "chosen", true);
    return json({
      logged: true,
      decision_id: Number(id),
      chosen_entity_id,
      updated_existing_decision
    });
  }
);

function json(value) {
  return {
    content: [
      {
        type: "text",
        text: JSON.stringify(value, null, 2)
      }
    ]
  };
}

function describeRetrieval(retrieval) {
  return {
    constrained_to_options: retrieval.constrained_to_options,
    unmatched_options: retrieval.unmatched_options,
    candidate_count: retrieval.candidates.length,
    matched_candidates: retrieval.candidates.map((entity) => ({
      id: entity.id,
      name: entity.canonical_name,
      type: entity.type
    }))
  };
}

const transport = new StdioServerTransport();
await server.connect(transport);
