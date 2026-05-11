"""
Shared keyword taxonomy for Layer 3 (staleness) and Layer 6 R7 (routing).

KEYWORD_TO_DOMAIN
    Substring -> domain mapping used by mcp/temporal-staleness.py to infer a
    topic's domain from the prompt text. First match wins ordering does NOT
    apply here: the staleness module collects all matches and picks the one
    with the shortest half-life (see DOMAIN_HALF_LIFE there).

R7_TRIGGER_KEYWORDS
    Tuple of substrings that fire R7 in hooks/temporal-routing.py: if any
    appear in the user's prompt, the routing hook suggests calling
    temporal_staleness_audit-first. Curated more aggressively than
    KEYWORD_TO_DOMAIN: only topics where months-since-training-cutoff
    genuinely matters and where the model otherwise answers confidently
    from stale training data.

Why two lists, not one
    KEYWORD_TO_DOMAIN exists to map keyword -> volatility class.
    R7_TRIGGER_KEYWORDS exists to map keyword -> "should we even ask the
    staleness MCP?". Many KEYWORD_TO_DOMAIN entries (math/theorem/history)
    are ageless and would be noisy if they fired R7. A trigger set strictly
    smaller than the domain set keeps R7 high-signal.
"""


KEYWORD_TO_DOMAIN: list[tuple[str, str]] = [
    ("cve", "security"),
    ("vulnerab", "security"),
    ("exploit", "security"),
    ("zero-day", "security"),
    ("0day", "security"),

    ("price", "pricing"),
    ("pricing", "pricing"),
    ("cost", "pricing"),
    ("stock", "stocks"),
    ("market", "markets"),

    ("crypto", "crypto"),
    ("bitcoin", "crypto"),

    ("election", "politics"),
    ("news", "news"),

    ("law", "legal"),
    ("statute", "legal"),
    ("regulation", "regulation"),

    ("medical", "medical"),
    ("treatment", "medical"),
    ("diagnos", "medical"),
    ("drug", "medical"),

    ("gpt-", "ai"),
    ("claude", "ai"),
    ("llm", "llm"),
    ("model", "ai"),

    ("library", "libraries"),
    ("package", "libraries"),
    ("framework", "framework"),
    ("api", "api"),
    ("software", "software"),
    ("python", "software"),
    ("node", "software"),
    ("react", "framework"),

    ("history", "history"),
    ("theorem", "math"),
    ("proof", "math"),
    ("equation", "math"),
]


R7_TRIGGER_KEYWORDS: tuple[str, ...] = (
    "api", "library", "framework", "package", "sdk",
    "cve", "vulnerability", "vulnerab",
    "pricing", "price", "cost",
    "model version", "latest version", "release notes",
    "deprecat", "breaking change", "new in", "as of",
)


R8_TRIGGER_KEYWORDS: tuple[str, ...] = (
    # Forward-time language: when the user is anchoring on what's coming,
    # Layer 5 (temporal_future_query) should surface overdue/upcoming work
    # before the model answers generically.
    "deadline", "due", "overdue", "upcoming",
    "schedule", "scheduled", "next week", "this week",
    "before friday", "before monday", "before tuesday",
    "before wednesday", "before thursday", "before saturday",
    "before sunday",
    "tomorrow", "imorgon",
    "planera", "planering", "plan for",
    "what's left", "what is left", "what's coming",
    "remaining", "outstanding",
    "soon", "snart",
)
