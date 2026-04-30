ENTITY_TYPES = [
    "wine",
    "restaurant",
    "music",
    "cigar",
    "experience",
    "movie",
    "series",
]

ATTRIBUTE_KEYS_BY_TYPE = {
    "wine": [
        "oak",
        "premium",
        "richness",
        "intensity",
        "classic",
        "indulgent",
        "novelty",
        "comfort",
    ],
    "restaurant": [
        "premium",
        "quiet",
        "lively",
        "indulgent",
        "novelty",
        "comfort",
        "view",
        "classic",
        "casual",
    ],
    "music": [
        "quiet",
        "lively",
        "intellectual",
        "comfort",
        "classic",
        "novelty",
        "intensity",
        "indulgent",
    ],
    "cigar": [
        "premium",
        "richness",
        "intensity",
        "classic",
        "indulgent",
        "novelty",
        "comfort",
    ],
    "experience": [
        "premium",
        "intensity",
        "quiet",
        "lively",
        "intellectual",
        "indulgent",
        "novelty",
        "comfort",
        "view",
        "classic",
        "casual",
    ],
    "movie": [
        "intense",
        "suspenseful",
        "cerebral",
        "emotional",
        "funny",
        "dark",
        "light",
        "slow_burn",
        "action",
        "comfort",
        "novelty",
        "classic",
    ],
    "series": [
        "intense",
        "suspenseful",
        "cerebral",
        "emotional",
        "funny",
        "dark",
        "light",
        "slow_burn",
        "serialized",
        "comfort",
        "novelty",
        "classic",
    ],
}

ATTRIBUTE_KEYS = list(
    dict.fromkeys(
        key
        for entity_type in ENTITY_TYPES
        for key in ATTRIBUTE_KEYS_BY_TYPE[entity_type]
    )
)

INTENTS = [
    "contextual_decision",
    "option_set_evaluation",
    "memory_recall",
    "attribute_retrieval",
    "passive_recall",
    "social_context",
    "negative_filtering",
    "hybrid_query",
    "fuzzy_recall",
    "exploration",
]


def attribute_keys_for_type(entity_type: str | None) -> list[str]:
    return ATTRIBUTE_KEYS_BY_TYPE.get(entity_type or "", ATTRIBUTE_KEYS)


def invalid_attribute_keys(
    entity_type: str,
    attributes: dict[str, float] | None,
) -> list[str]:
    allowed = set(attribute_keys_for_type(entity_type))
    return sorted(key for key in (attributes or {}) if key not in allowed)
