import OpenAI from "openai";
import { ATTRIBUTE_KEYS, ENTITY_TYPES, INTENTS } from "./schema.js";

const MODEL = process.env.PALATE_MODEL || "gpt-5.5";

function client() {
  if (!process.env.OPENAI_API_KEY) {
    throw new Error("OPENAI_API_KEY is required for this LLM-owned operation.");
  }
  return new OpenAI({ apiKey: process.env.OPENAI_API_KEY });
}

export async function parseIntent({ query, context = {} }) {
  return jsonResponse({
    name: "palate_intent",
    instructions: [
      "You translate ambiguous taste requests into Palate's fixed intent schema.",
      "Do not rank or recommend anything.",
      "Use only predefined attributes and entity types.",
      "If uncertain, leave fields empty or set intent to fuzzy_recall."
    ].join(" "),
    input: { query, context, allowed_attributes: ATTRIBUTE_KEYS, allowed_entity_types: ENTITY_TYPES, allowed_intents: INTENTS },
    schema: {
      type: "object",
      additionalProperties: false,
      required: ["intent", "attributes", "context", "filters", "entity_type", "search_text"],
      properties: {
        intent: { type: "string", enum: INTENTS },
        attributes: { type: "array", items: { type: "string", enum: ATTRIBUTE_KEYS } },
        context: {
          type: "object",
          additionalProperties: false,
          required: ATTRIBUTE_KEYS,
          properties: Object.fromEntries(ATTRIBUTE_KEYS.map((key) => [key, { type: "boolean" }]))
        },
        filters: {
          type: "object",
          additionalProperties: false,
          required: ["min_rating", "recommended_by"],
          properties: {
            min_rating: { type: ["number", "null"], minimum: 1, maximum: 5 },
            recommended_by: { type: ["string", "null"] }
          }
        },
        entity_type: { type: ["string", "null"], enum: [...ENTITY_TYPES, null] },
        search_text: { type: "string" }
      }
    }
  });
}

export async function extractEntities({ text, expectedType = null }) {
  return jsonResponse({
    name: "palate_entities",
    instructions: [
      "Extract canonical entities from an option set such as a wine list or restaurant shortlist.",
      "Do not evaluate or rank them.",
      "Return only entities present in the input."
    ].join(" "),
    input: { text, expected_type: expectedType, allowed_entity_types: ENTITY_TYPES },
    schema: {
      type: "object",
      additionalProperties: false,
      required: ["entities"],
      properties: {
        entities: {
          type: "array",
          items: {
            type: "object",
            additionalProperties: false,
            required: ["canonical_name", "type", "source_text"],
            properties: {
              canonical_name: { type: "string" },
              type: { type: "string", enum: ENTITY_TYPES },
              source_text: { type: "string" }
            }
          }
        }
      }
    }
  });
}

export async function normalizeEnrichment({ itemText, entityType }) {
  return jsonResponse({
    name: "palate_enrichment",
    instructions: [
      "Normalize noisy descriptive text into Palate's fixed attribute schema.",
      "Never invent new attribute keys.",
      "Each value must be in [0, 1]. Use 0 when not evidenced."
    ].join(" "),
    input: { item_text: itemText, entity_type: entityType, allowed_attributes: ATTRIBUTE_KEYS },
    schema: {
      type: "object",
      additionalProperties: false,
      required: ["attributes", "notes"],
      properties: {
        attributes: {
          type: "object",
          additionalProperties: false,
          required: ATTRIBUTE_KEYS,
          properties: Object.fromEntries(ATTRIBUTE_KEYS.map((key) => [key, { type: "number", minimum: 0, maximum: 1 }]))
        },
        notes: { type: "string" }
      }
    }
  });
}

export async function explainResults({ query, intent, grounding }) {
  const response = await client().responses.create({
    model: MODEL,
    input: [
      {
        role: "system",
        content: [
          "You write concise Palate explanations.",
          "Use only the provided grounding facts.",
          "Do not introduce new preferences, ratings, provenance, or tasting notes.",
          "Do not change the ranking order."
        ].join(" ")
      },
      {
        role: "user",
        content: JSON.stringify({ query, intent, ranked_results: grounding })
      }
    ],
    text: { verbosity: "low" }
  });
  return response.output_text.trim();
}

async function jsonResponse({ name, instructions, input, schema }) {
  const response = await client().responses.create({
    model: MODEL,
    input: [
      { role: "system", content: instructions },
      { role: "user", content: JSON.stringify(input) }
    ],
    text: {
      format: {
        type: "json_schema",
        name,
        strict: true,
        schema
      }
    }
  });
  return JSON.parse(response.output_text);
}
