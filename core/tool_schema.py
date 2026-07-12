"""
core/tool_schema.py — Tool-declaration schema converters for the voice backends.

main.py's TOOL_DECLARATIONS is written in Gemini's function-declaration schema
(uppercase JSON-Schema type strings: "OBJECT", "STRING", "ARRAY", "INTEGER",
"NUMBER", "BOOLEAN"). That list stays the single source of truth — this module
converts it into the OpenAI Realtime API's function-tool shape on the fly so
we never maintain two parallel tool declaration lists.
"""
from __future__ import annotations

_TYPE_MAP = {
    "OBJECT":  "object",
    "STRING":  "string",
    "ARRAY":   "array",
    "INTEGER": "integer",
    "NUMBER":  "number",
    "BOOLEAN": "boolean",
}


def _convert_schema_node(node: dict) -> dict:
    """Recursively lowercase Gemini-style uppercase 'type' values and descend
    into 'properties' (OBJECT) / 'items' (ARRAY)."""
    out: dict = {}
    for key, value in node.items():
        if key == "type" and isinstance(value, str):
            out["type"] = _TYPE_MAP.get(value.upper(), value.lower())
        elif key == "properties" and isinstance(value, dict):
            out["properties"] = {
                prop_name: _convert_schema_node(prop_schema)
                for prop_name, prop_schema in value.items()
            }
        elif key == "items" and isinstance(value, dict):
            out["items"] = _convert_schema_node(value)
        else:
            out[key] = value
    return out


def gemini_tool_to_openai_realtime(tool: dict) -> dict:
    """Converts one Gemini-schema tool declaration (as used in
    main.py's TOOL_DECLARATIONS) into the OpenAI Realtime API's function-tool
    shape: {"type": "function", "name", "description", "parameters"}."""
    return {
        "type": "function",
        "name": tool["name"],
        "description": tool.get("description", ""),
        "parameters": _convert_schema_node(tool.get("parameters", {"type": "OBJECT", "properties": {}})),
    }


def gemini_tools_to_openai_realtime(tool_declarations: list[dict]) -> list[dict]:
    """Converts the full TOOL_DECLARATIONS list. See gemini_tool_to_openai_realtime."""
    return [gemini_tool_to_openai_realtime(t) for t in tool_declarations]
