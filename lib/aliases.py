"""Shell aliases for ak: custom ones and the `classic` preset (off by default)."""

import json
import os

import common

CLASSIC = [("claudex", "claude"), ("codexx", "codex"), ("cursorx", "cursor"), ("opencodex", "opencode"),
           ("pix", "pi"), ("clinex", "cline"), ("grokx", "grok")]


def config_file():
    return os.path.join(os.path.dirname(common.env_file()), "aliases.json")


def load():
    """{"classic": bool, "custom": [{"name", "kind", "profile", "auto"}]}; a
    missing or unreadable file is the default state."""
    try:
        with open(config_file()) as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {"classic": False, "custom": []}
    if not isinstance(data, dict):
        return {"classic": False, "custom": []}
    custom = [a for a in data.get("custom", []) if isinstance(a, dict) and a.get("name") and a.get("kind")]
    return {"classic": data.get("classic") is True, "custom": custom}
