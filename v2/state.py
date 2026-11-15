"""Structured game state for Version 2.

Everything the game needs to remember lives in one plain dict, so it can be
shown in the UI, saved as JSON and checked in tests. The LLM never edits it.
"""
import copy
import json
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "game_config.json"


def load_config(path=CONFIG_PATH):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def new_state(config):
    locked = {oid: True for oid, obj in config["objects"].items() if "lock" in obj}
    return {
        "inventory": [],            # item ids the player carries
        "discovered_items": [],     # items the player has seen (can be taken)
        "examined": [],             # object ids examined at least once
        "solved": [],               # puzzle ids solved, in order
        "locked": locked,           # object id -> bool
        "attempts": {oid: 0 for oid, obj in config["objects"].items()
                     if obj.get("lock", {}).get("type") == "code"},
        "hints_used": 0,
        "turn": 0,
        "escaped": False,
        "history": [],              # [{turn, input, action, ok}]
    }


def public_view(state):
    """The part of the state that is safe to show the player / the narrator."""
    view = copy.deepcopy(state)
    view.pop("history", None)
    return view
