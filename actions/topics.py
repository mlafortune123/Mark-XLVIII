"""
actions/topics.py — conversational follow/unfollow for the vault's followed
topics list (memory/vault_manager.py), previously reachable only from the
Preferences UI (ui.py's OnboardingOverlay). One tool, not three, to keep
TOOL_DECLARATIONS small — action selects follow/unfollow/list.
"""
from memory import vault_manager
from core.tool_registry import ToolSpec


def manage_topics(parameters: dict, player=None) -> str:
    params = parameters or {}
    action = (params.get("action") or "").strip().lower()
    topic  = (params.get("topic")  or "").strip()

    if action == "follow":
        result = vault_manager.follow_topic(topic)
    elif action == "unfollow":
        result = vault_manager.unfollow_topic(topic)
    elif action == "list":
        topics = vault_manager.list_followed_topics()
        result = f"You're following: {', '.join(topics)}" if topics else "You're not following any topics yet."
    else:
        result = f"Unknown manage_topics action: '{action}'. Use follow, unfollow, or list."

    if player:
        player.write_log(f"[Topics] {action}: {topic or '(list)'}")
    return result


def _handle(args: dict, ctx) -> str:
    r = manage_topics(parameters=args, player=ctx.ui)
    return r or "Done."


TOOLS = [
    ToolSpec(
        name="manage_topics",
        declaration={
            "name": "manage_topics",
            "description": (
                "Follow, unfollow, or list the topics the user wants proactive updates on "
                "(e.g. 'keep me posted on the F1 season', 'stop following SpaceX', "
                "'what am I following'). Do NOT use save_memory for this."
            ),
            "parameters": {
                "type": "OBJECT",
                "properties": {
                    "action": {"type": "STRING", "description": "follow | unfollow | list"},
                    "topic":  {"type": "STRING", "description": "Topic name. Required unless action='list'."},
                },
                "required": ["action"]
            }
        },
        routing_hint=(
            "keep me posted on / follow / stop following / what do I follow → manage_topics. "
            "Do NOT use save_memory for topic following."
        ),
        handler=_handle,
    )
]
