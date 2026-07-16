"""memory/vault_manager.py — Obsidian-vault-backed replacement for
memory/preferences_manager.py + memory/memory_manager.py.

User state now lives as plain Markdown notes with YAML frontmatter in a
vault directory the user can open directly in the real Obsidian app:

    JarvisVault/
      Core/
        Identity.md      # always injected in full — name/city/job/etc.
        Preferences.md    # always injected, capped list — small stable prefs
        Settings.md        # NOT text-injected — read structurally
      Topics/<slug>.md      # one per followed topic — on-demand via search_memory
      People/<slug>.md      # one per relationship fact — on-demand
      Projects/<slug>.md    # one per project fact — on-demand
      Facts/<slug>.md       # wishes/notes-category facts — on-demand

Frontmatter fields (type/category/key/value/tags/updated/fields) are
machine-owned and get overwritten on every save; the note body is
user/Obsidian-owned and is preserved verbatim across rewrites.
"""
import json
import os
import re
import yaml
from datetime import datetime
from pathlib import Path
from threading import Lock

from memory.config_manager import BASE_DIR, CONFIG_DIR

VAULT_POINTER_FILE = CONFIG_DIR / "vault_path.json"
DEFAULT_VAULT_PATH = Path.home() / "Documents" / "JarvisVault"

MAX_VALUE_LENGTH = 380
_lock = Lock()

DEFAULT_SETTINGS = {
    "onboarded":         False,
    "startup_news":      True,
    "startup_weather":   False,
    "weather_city":      "",
    "followed_topics":   [],
    "topic_digest_last": "",
    "language":          "auto",
    "voice":             "Sadaltager",
    "accent":            "british",
    "style":             "newscaster",
    "pace":              "default",
}

CORE_CATEGORIES = {"identity", "preferences"}
# category -> on-demand folder + tag, for everything that isn't a small
# stable Core fact.
FOLDER_MAP = {"projects": "Projects", "relationships": "People", "wishes": "Facts", "notes": "Facts"}
TAG_MAP    = {"projects": "project",  "relationships": "person",  "wishes": "wish",  "notes": "note"}

CATEGORY_FOLDERS = {"topics": "Topics", "people": "People", "projects": "Projects", "facts": "Facts"}


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _slugify(key: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (key or "").strip().lower()).strip("-")
    return slug or "note"


# ── Vault location ────────────────────────────────────────────────────────

def get_vault_path() -> Path:
    try:
        data = json.loads(VAULT_POINTER_FILE.read_text(encoding="utf-8"))
        raw = data.get("vault_path")
        if raw:
            return Path(raw)
    except Exception:
        pass
    return DEFAULT_VAULT_PATH


def set_vault_path(path) -> None:
    """Repoints Jarvis at a different vault folder. MVP: pointer-only — does
    NOT move or copy any existing notes from the old location."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    VAULT_POINTER_FILE.write_text(
        json.dumps({"vault_path": str(path)}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _core_path(filename: str) -> Path:
    return get_vault_path() / "Core" / filename


# ── Note I/O (atomic, frontmatter + body) ───────────────────────────────────

def _read_note(path: Path) -> tuple[dict, str]:
    if not path.exists():
        return {}, ""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return {}, ""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    try:
        fm = yaml.safe_load(parts[1]) or {}
    except Exception:
        fm = {}
    body = parts[2].lstrip("\n")
    return (fm if isinstance(fm, dict) else {}), body


def _write_note(path: Path, frontmatter: dict, body: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fm_text = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).strip()
    content = f"---\n{fm_text}\n---\n{body}" if body else f"---\n{fm_text}\n---\n"
    with _lock:
        tmp = path.with_name(path.name + f".tmp{os.getpid()}")
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, path)


# ── Vault skeleton ───────────────────────────────────────────────────────────

def ensure_vault(path=None) -> Path:
    vault = Path(path) if path else get_vault_path()
    for sub in ("Core", "Topics", "People", "Projects", "Facts"):
        (vault / sub).mkdir(parents=True, exist_ok=True)

    identity_path = vault / "Core" / "Identity.md"
    if not identity_path.exists():
        _write_note(identity_path, {"type": "core", "category": "identity", "fields": {}, "updated": _today()})

    prefs_path = vault / "Core" / "Preferences.md"
    if not prefs_path.exists():
        _write_note(prefs_path, {"type": "core", "category": "preferences", "fields": {}, "updated": _today()})

    settings_path = vault / "Core" / "Settings.md"
    if not settings_path.exists():
        _write_note(settings_path, dict(DEFAULT_SETTINGS))

    return vault


# ── Settings (replaces load_preferences/save_preferences) ───────────────────

def get_settings() -> dict:
    ensure_vault()
    fm, _ = _read_note(_core_path("Settings.md"))
    merged = dict(DEFAULT_SETTINGS)
    if isinstance(fm, dict):
        merged.update(fm)
    return merged


def save_settings(update: dict) -> None:
    if not isinstance(update, dict) or not update:
        return
    settings = get_settings()
    settings.update(update)
    _, body = _read_note(_core_path("Settings.md"))
    _write_note(_core_path("Settings.md"), settings, body)


def complete_onboarding(update: dict) -> None:
    update = dict(update or {})
    topics = update.pop("followed_topics", None)
    if topics is not None:
        set_followed_topics(topics)
    update["onboarded"] = True
    save_settings(update)


def is_onboarded() -> bool:
    return bool(get_settings().get("onboarded", False))


def mark_topic_digest_sent(date_str: str | None = None) -> None:
    save_settings({"topic_digest_last": date_str or _today()})


# ── Followed topics (Settings.md list = source of truth, mirrored into
#    Topics/*.md notes so they're human-browsable and search_memory-able) ────

def list_followed_topics() -> list[str]:
    return list(get_settings().get("followed_topics", []) or [])


def set_followed_topics(names) -> None:
    clean = []
    for n in (names or []):
        n = str(n).strip()
        if n and n not in clean:
            clean.append(n)
    save_settings({"followed_topics": clean})

    vault      = get_vault_path()
    topics_dir = vault / "Topics"
    topics_dir.mkdir(parents=True, exist_ok=True)
    ts         = _today()
    keep_slugs = set()

    for name in clean:
        slug = _slugify(name)
        keep_slugs.add(slug)
        path = topics_dir / f"{slug}.md"
        fm, body = _read_note(path)
        fm.update({
            "type":     "topic",
            "category": "topics",
            "key":      slug,
            "tags":     ["followed"],
            "value":    name,
            "updated":  ts,
        })
        _write_note(path, fm, body)

    # No longer followed — drop the tag but keep the note (may hold
    # user-added body content in Obsidian).
    for path in topics_dir.glob("*.md"):
        if path.stem in keep_slugs:
            continue
        fm, body = _read_note(path)
        tags = fm.get("tags") or []
        if "followed" in tags:
            fm["tags"] = [t for t in tags if t != "followed"]
            _write_note(path, fm, body)


def follow_topic(name: str) -> str:
    """Conversational entry point for "keep me posted on X" — dedups
    case-insensitively against the existing list (compares slugs, not raw
    strings, so "SpaceX" and "spacex" don't both get added)."""
    name = (name or "").strip()
    if not name:
        return "Please give me a topic to follow."

    current = list_followed_topics()
    slug = _slugify(name)
    if any(_slugify(t) == slug for t in current):
        return f"Already following {name}."

    set_followed_topics(current + [name])
    return f"Now following {name}."


def unfollow_topic(name: str) -> str:
    """Matches by slug or display name — removal just strips the
    'followed' tag (via set_followed_topics), it never deletes the note."""
    name = (name or "").strip()
    if not name:
        return "Please tell me which topic to stop following."

    slug = _slugify(name)
    current = list_followed_topics()
    remaining = [t for t in current if _slugify(t) != slug]

    if len(remaining) == len(current):
        return f"I wasn't following {name}."

    set_followed_topics(remaining)
    return f"Stopped following {name}."


MAX_DIGEST_HISTORY = 14


def append_digest_history(topic: str, summary: str, date_str: str | None = None) -> None:
    """Records what was reported for a followed topic's digest, on
    Topics/<slug>.md's machine-owned frontmatter (body stays user-owned).
    Capped rolling window so slow-moving topics don't repeat the same
    update every day — _run_topic_digest() feeds this back in as
    "previously reported" context on the next run."""
    summary = (summary or "").strip()
    if not summary:
        return
    slug = _slugify(topic)
    path = get_vault_path() / "Topics" / f"{slug}.md"
    fm, body = _read_note(path)
    history = fm.get("digest_history") or []
    history.append({"date": date_str or _today(), "summary": summary})
    fm["digest_history"] = history[-MAX_DIGEST_HISTORY:]
    _write_note(path, fm, body)


def get_digest_history(topic: str, n: int = 5) -> list[dict]:
    slug = _slugify(topic)
    path = get_vault_path() / "Topics" / f"{slug}.md"
    fm, _ = _read_note(path)
    history = fm.get("digest_history") or []
    return history[-n:]


# ── Core prompt injection (replaces format_memory_for_prompt) ───────────────

def build_core_prompt_block() -> str:
    ensure_vault()
    identity_fields = (_read_note(_core_path("Identity.md"))[0] or {}).get("fields") or {}
    prefs_fields    = (_read_note(_core_path("Preferences.md"))[0] or {}).get("fields") or {}

    lines = []
    id_order = ["name", "age", "birthday", "city", "job", "language", "school", "nationality"]
    for field in id_order:
        entry = identity_fields.get(field)
        if entry:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"{field.title()}: {val}")
    for key, entry in identity_fields.items():
        if key in id_order:
            continue
        val = entry.get("value") if isinstance(entry, dict) else entry
        if val:
            lines.append(f"{key.replace('_', ' ').title()}: {val}")

    if prefs_fields:
        lines.append("")
        lines.append("Preferences:")
        ranked = sorted(
            prefs_fields.items(),
            key=lambda kv: (kv[1].get("updated", "") if isinstance(kv[1], dict) else ""),
            reverse=True,
        )
        for key, entry in ranked[:15]:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"  - {key.replace('_', ' ').title()}: {val}")

    if not lines:
        return ""

    header = "[WHAT YOU KNOW ABOUT THIS PERSON — use naturally, never recite like a list]\n"
    result = header + "\n".join(lines)
    if len(result) > 2000:
        result = result[:1997] + "…"
    return result + "\n"


def get_identity_field(key: str) -> str:
    """Single identity value (e.g. 'name', 'language') for callers that need
    just one field rather than the full rendered Core prompt block."""
    fields = (_read_note(_core_path("Identity.md"))[0] or {}).get("fields") or {}
    entry = fields.get(key)
    val = entry.get("value") if isinstance(entry, dict) else entry
    return str(val or "").strip()


def sync_city_from_weather_if_needed() -> None:
    """One-time nicety: if Identity has no city yet but the Preferences UI's
    weather_city is set, copy it into Identity so core.user_context's
    Identity-wins resolution picks it up without the user having to say
    their city conversationally. Idempotent — no-ops once Identity has a
    city. Does not delete weather_city; the Preferences UI still owns it."""
    if get_identity_field("city"):
        return
    weather_city = (get_settings().get("weather_city") or "").strip()
    if weather_city:
        save_fact("identity", "city", weather_city)


# ── Facts (replaces remember()/update_memory() and forget()) ────────────────

def save_fact(category: str, key: str, value: str, updated: str | None = None) -> str:
    if category not in CORE_CATEGORIES and category not in FOLDER_MAP:
        category = "notes"
    key   = (key or "").strip()
    value = str(value or "").strip()
    if not key or not value:
        return "Nothing to save."
    if len(value) > MAX_VALUE_LENGTH:
        value = value[:MAX_VALUE_LENGTH].rstrip() + "…"
    ts = updated or _today()

    if category in CORE_CATEGORIES:
        path = _core_path("Identity.md" if category == "identity" else "Preferences.md")
        fm, body = _read_note(path)
        fields = fm.get("fields") or {}
        fields[key] = {"value": value, "updated": ts}
        fm["fields"]  = fields
        fm["updated"] = ts
        _write_note(path, fm, body)
    else:
        folder = get_vault_path() / FOLDER_MAP[category]
        path   = folder / f"{_slugify(key)}.md"
        _fm, body = _read_note(path)
        fm = {
            "type":     "fact",
            "category": category,
            "key":      key,
            "tags":     [TAG_MAP[category]],
            "value":    value,
            "updated":  ts,
        }
        _write_note(path, fm, body)

    print(f"[Vault] 💾 Saved: {category}/{key} = {value}")
    return f"Remembered: {category}/{key} = {value}"


def forget_fact(key: str, category: str = "notes") -> str:
    key = (key or "").strip()
    if category in CORE_CATEGORIES:
        path = _core_path("Identity.md" if category == "identity" else "Preferences.md")
        fm, body = _read_note(path)
        fields = fm.get("fields") or {}
        if key in fields:
            del fields[key]
            fm["fields"] = fields
            _write_note(path, fm, body)
            return f"Forgotten: {category}/{key}"
        return f"Not found: {category}/{key}"

    folder = get_vault_path() / FOLDER_MAP.get(category, "Facts")
    path   = folder / f"{_slugify(key)}.md"
    if path.exists():
        path.unlink()
        return f"Forgotten: {category}/{key}"
    return f"Not found: {category}/{key}"


# ── Search (new — keyword/tag/filename match, no embeddings) ────────────────

def search_memory(query: str, category: str = "any", top_k: int = 5) -> str:
    query = (query or "").strip()
    if not query:
        return "Please provide a search term."

    category = (category or "any").strip().lower()
    vault    = get_vault_path()
    if category in ("", "any"):
        folders = [vault / name for name in CATEGORY_FOLDERS.values()]
    else:
        folder_name = CATEGORY_FOLDERS.get(category)
        folders = [vault / folder_name] if folder_name else []

    terms   = [t.lower() for t in query.split() if t]
    results = []
    for folder in folders:
        if not folder.exists():
            continue
        for path in folder.glob("*.md"):
            fm, body = _read_note(path)
            digest_summaries = " ".join(
                entry.get("summary", "") for entry in (fm.get("digest_history") or [])
            )
            haystack = " ".join([
                path.stem,
                str(fm.get("key", "")),
                str(fm.get("value", "")),
                " ".join(fm.get("tags") or []),
                body,
                digest_summaries,
            ]).lower()
            score = sum(haystack.count(t) for t in terms)
            if score > 0:
                results.append((score, folder.name, fm, path.stem))

    if not results:
        return f"No memory found matching: {query}"

    results.sort(key=lambda t: t[0], reverse=True)
    lines = [f"Memory search results for: {query}\n"]
    for i, (_score, folder_name, fm, stem) in enumerate(results[:top_k], 1):
        key = fm.get("key", stem)
        val = fm.get("value", "")
        lines.append(f"{i}. [{folder_name}] {key}: {val}")
    return "\n".join(lines).strip()


# ── One-time migration from the old JSON stores ──────────────────────────────

def migrate_if_needed() -> None:
    vault = get_vault_path()
    identity_path = vault / "Core" / "Identity.md"
    if identity_path.exists():
        return  # already migrated (or a fresh vault already initialised)

    ensure_vault(vault)

    old_prefs_path = CONFIG_DIR / "preferences.json"
    if old_prefs_path.exists():
        try:
            data = json.loads(old_prefs_path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[Vault] ⚠️ Failed to read preferences.json: {e}")
            data = {}
        topics = data.pop("followed_topics", None) or []
        if data:
            save_settings(data)
        if topics:
            set_followed_topics(topics)
        try:
            old_prefs_path.rename(old_prefs_path.with_name(old_prefs_path.name + ".bak"))
        except Exception as e:
            print(f"[Vault] ⚠️ Could not rename preferences.json: {e}")

    old_memory_path = BASE_DIR / "memory" / "long_term.json"
    if old_memory_path.exists():
        try:
            memory = json.loads(old_memory_path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[Vault] ⚠️ Failed to read long_term.json: {e}")
            memory = {}
        for cat, items in (memory or {}).items():
            if not isinstance(items, dict):
                continue
            for key, entry in items.items():
                value   = entry.get("value") if isinstance(entry, dict) else entry
                updated = entry.get("updated") if isinstance(entry, dict) else None
                if value:
                    save_fact(cat, key, str(value), updated=updated)
        try:
            old_memory_path.rename(old_memory_path.with_name(old_memory_path.name + ".bak"))
        except Exception as e:
            print(f"[Vault] ⚠️ Could not rename long_term.json: {e}")

    print(f"[Vault] ✅ Migration complete → {vault}")
