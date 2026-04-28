import { mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { DatabaseSync } from "node:sqlite";

const DEFAULT_DB_PATH = "./data/palate.sqlite";

export function openStore(dbPath = process.env.PALATE_DB_PATH || DEFAULT_DB_PATH) {
  const resolved = resolve(dbPath);
  mkdirSync(dirname(resolved), { recursive: true });
  const db = new DatabaseSync(resolved);
  db.exec("PRAGMA foreign_keys = ON");
  migrate(db);
  return new PalateStore(db);
}

function migrate(db) {
  db.exec(`
    CREATE TABLE IF NOT EXISTS entities (
      id TEXT PRIMARY KEY,
      type TEXT NOT NULL,
      canonical_name TEXT NOT NULL,
      source_text TEXT,
      notes TEXT,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS attributes (
      entity_id TEXT NOT NULL,
      key TEXT NOT NULL,
      value REAL NOT NULL CHECK (value >= 0 AND value <= 1),
      PRIMARY KEY (entity_id, key),
      FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS signals (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      entity_id TEXT NOT NULL,
      type TEXT NOT NULL,
      value TEXT NOT NULL,
      provenance TEXT,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS decisions (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      query TEXT NOT NULL,
      context_json TEXT NOT NULL,
      options_json TEXT NOT NULL,
      ranked_json TEXT NOT NULL,
      chosen_entity_id TEXT,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
  `);
}

export class PalateStore {
  constructor(db) {
    this.db = db;
  }

  upsertEntity(entity) {
    this.db.prepare(`
      INSERT INTO entities (id, type, canonical_name, source_text, notes)
      VALUES (?, ?, ?, ?, ?)
      ON CONFLICT(id) DO UPDATE SET
        type = excluded.type,
        canonical_name = excluded.canonical_name,
        source_text = excluded.source_text,
        notes = excluded.notes
    `).run(entity.id, entity.type, entity.canonical_name, entity.source_text ?? null, entity.notes ?? null);

    if (entity.attributes) {
      for (const [key, value] of Object.entries(entity.attributes)) {
        this.setAttribute(entity.id, key, value);
      }
    }

    if (entity.signals) {
      for (const signal of entity.signals) {
        this.addSignal(entity.id, signal.type, signal.value, signal.provenance);
      }
    }
  }

  setAttribute(entityId, key, value) {
    this.db.prepare(`
      INSERT INTO attributes (entity_id, key, value)
      VALUES (?, ?, ?)
      ON CONFLICT(entity_id, key) DO UPDATE SET value = excluded.value
    `).run(entityId, key, clamp01(value));
  }

  addSignal(entityId, type, value, provenance = null) {
    this.db.prepare(`
      INSERT INTO signals (entity_id, type, value, provenance)
      VALUES (?, ?, ?, ?)
    `).run(entityId, type, String(value), provenance);
  }

  listEntities() {
    const entities = this.db.prepare("SELECT * FROM entities ORDER BY canonical_name").all();
    const attrs = this.db.prepare("SELECT key, value FROM attributes WHERE entity_id = ?");
    const signals = this.db.prepare("SELECT type, value, provenance, created_at FROM signals WHERE entity_id = ? ORDER BY id DESC");

    return entities.map((entity) => ({
      ...entity,
      attributes: Object.fromEntries(attrs.all(entity.id).map((row) => [row.key, row.value])),
      signals: signals.all(entity.id)
    }));
  }

  findEntitiesByNames(names) {
    const all = this.listEntities();
    return names.map((name) => {
      const normalized = normalize(name);
      return all.find((entity) => normalize(entity.canonical_name) === normalized)
        ?? all.find((entity) => normalize(entity.canonical_name).includes(normalized) || normalized.includes(normalize(entity.canonical_name)));
    }).filter(Boolean);
  }

  logDecision({ query, context, options, ranked, chosen_entity_id = null }) {
    const result = this.db.prepare(`
      INSERT INTO decisions (query, context_json, options_json, ranked_json, chosen_entity_id)
      VALUES (?, ?, ?, ?, ?)
    `).run(
      query,
      JSON.stringify(context ?? {}),
      JSON.stringify(options ?? []),
      JSON.stringify(ranked ?? []),
      chosen_entity_id
    );
    return result.lastInsertRowid;
  }
}

function normalize(value) {
  return String(value).toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
}

function clamp01(value) {
  return Math.max(0, Math.min(1, Number(value)));
}
