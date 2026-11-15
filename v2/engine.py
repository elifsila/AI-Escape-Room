"""Game engine for Version 2 — Python decides, the LLM only describes.

`apply_action(state, action, config)` validates a parsed action against the
current state and the rules in game_config.json, updates the state if the
action is allowed, and returns a Result with the *facts* the narrator may use.
"""
from dataclasses import dataclass, field

# ---------------------------------------------------------------- result type


@dataclass
class Result:
    ok: bool                       # did the action succeed / was it valid?
    facts: list = field(default_factory=list)  # ground truth for the narrator
    event: str = ""                # short machine-readable tag (for logs/tests)
    escaped: bool = False


# ------------------------------------------------------------------- helpers


def _obj(config, oid):
    return config["objects"].get(oid)


def _item(config, iid):
    return config["items"].get(iid)


def _puzzle_for(config, target, ptype):
    for pid, p in config["puzzles"].items():
        if p["target"] == target and p["type"] == ptype:
            return pid, p
    return None, None


def _container_accessible(state, config, oid):
    """Items inside a locked object are not reachable."""
    obj = _obj(config, oid)
    if obj is None:
        return False
    return not state["locked"].get(oid, False)


def _item_available(state, config, iid):
    item = _item(config, iid)
    return (
        iid not in state["inventory"]
        and iid in state["discovered_items"]
        and _container_accessible(state, config, item["location"])
    )


def _discover_contents(state, config, oid):
    """Reveal the items inside an accessible object. Returns the newly seen items."""
    new = []
    if not _container_accessible(state, config, oid):
        return new
    for iid in _obj(config, oid).get("items", []):
        if iid not in state["inventory"] and iid not in state["discovered_items"]:
            state["discovered_items"].append(iid)
            new.append(iid)
    return new


def _solve(state, config, pid):
    p = config["puzzles"][pid]
    state["solved"].append(pid)
    target = p["target"]
    if target in state["locked"]:
        state["locked"][target] = False
    _discover_contents(state, config, target)
    if pid == config.get("final_puzzle", "door_code"):
        state["escaped"] = True


def _describe_object(state, config, oid):
    obj = _obj(config, oid)
    if oid in state["locked"]:
        if state["locked"][oid]:
            text = obj.get("description_locked", obj.get("description"))
        else:
            text = obj.get("description_open") or obj.get("description_revealed") or obj["description"]
    else:
        text = obj["description"]
    facts = [text]
    if _container_accessible(state, config, oid):
        visible = [config["items"][i]["name"] for i in obj.get("items", [])
                   if i not in state["inventory"]]
        if visible:
            facts.append("Inside/on it you can see: " + ", ".join(visible) + ".")
        elif obj.get("items"):
            facts.append("There is nothing else here.")
    return facts


# ------------------------------------------------------------------ handlers


def _look(state, config, a):
    facts = [config["room_description"]]
    if state["inventory"]:
        facts.append("You are carrying: " + ", ".join(config["items"][i]["name"] for i in state["inventory"]) + ".")
    return Result(True, facts, "look")


def _examine(state, config, a):
    target = a.get("target") or a.get("item")
    if not target:
        return _nonexistent(a) if a.get("raw_target") else _look(state, config, a)

    if target in config["objects"]:
        if target not in state["examined"]:
            state["examined"].append(target)
        _discover_contents(state, config, target)
        return Result(True, _describe_object(state, config, target), f"examine:{target}")

    if target in config["items"]:
        if target in state["inventory"] or _item_available(state, config, target):
            return Result(True, [config["items"][target]["description"]], f"examine:{target}")
        return Result(False, [f"You don't see any {config['items'][target]['name']} here."], "not_visible")

    return _nonexistent(a)


def _take(state, config, a):
    target = a.get("item") or a.get("target")
    if target in config["objects"]:
        return Result(False, [f"The {config['objects'][target]['name']} is far too big to carry."], "cannot_take")
    if target not in config["items"]:
        return _nonexistent(a)
    item = config["items"][target]
    if target in state["inventory"]:
        return Result(False, [f"You already have the {item['name']}."], "already_have")
    if not _item_available(state, config, target):
        return Result(False, [f"You don't see any {item['name']} you could take."], "not_visible")
    state["inventory"].append(target)
    state["discovered_items"].remove(target)
    return Result(True, [f"You take the {item['name']}. It is now in your inventory."], f"take:{target}")


def _use(state, config, a):
    iid, oid = a.get("item"), a.get("target")
    if iid not in config["items"]:
        return _nonexistent(a)
    item = config["items"][iid]
    if iid not in state["inventory"]:
        return Result(False, [f"You don't have a {item['name']}. You can only use items you have collected."],
                      "item_not_in_inventory")
    if not oid:
        return Result(False, [f"What do you want to use the {item['name']} on?"], "need_target")
    if oid not in config["objects"]:
        return _nonexistent({"raw_target": a.get("raw_target") or oid})

    pid, puzzle = _puzzle_for(config, oid, "item")
    obj = config["objects"][oid]
    if puzzle and puzzle["requires"] == iid:
        if pid in state["solved"]:
            return Result(False, [f"You already did that. The {obj['name']} has no more secrets for the {item['name']}."],
                          "already_solved")
        _solve(state, config, pid)
        return Result(True, [puzzle["success"]], f"solve:{pid}")

    if obj.get("lock", {}).get("type") == "code":
        return Result(False, [f"The {item['name']} doesn't help here. The {obj['name']} needs a numeric code."],
                      "wrong_item")
    return Result(False, [f"You try the {item['name']} on the {obj['name']}, but nothing happens."], "wrong_item")


def _enter_code(state, config, a):
    code = (a.get("code") or "").strip()
    oid = a.get("target")
    code_locks = {o: config["puzzles"][ob["lock"]["puzzle"]] for o, ob in config["objects"].items()
                  if ob.get("lock", {}).get("type") == "code"}

    if not code.isdigit():
        return Result(False, ["Codes must be numbers."], "bad_code_format")

    if oid is None:  # infer the lock from the number of digits
        matches = [o for o, p in code_locks.items() if len(p["solution"]) == len(code)]
        if len(matches) != 1:
            return Result(False, [f"There is no lock here that takes a {len(code)}-digit code."], "no_matching_lock")
        oid = matches[0]

    if oid not in config["objects"]:
        return _nonexistent({"raw_target": a.get("raw_target") or oid})
    if oid not in code_locks:
        return Result(False, [f"The {config['objects'][oid]['name']} has no keypad or combination lock."], "no_code_lock")

    puzzle = code_locks[oid]
    pid = config["objects"][oid]["lock"]["puzzle"]
    name = config["objects"][oid]["name"]
    if pid in state["solved"]:
        return Result(False, [f"The {name} is already unlocked."], "already_solved")
    if len(code) != len(puzzle["solution"]):
        return Result(False, [f"The {name} lock takes exactly {len(puzzle['solution'])} digits."], "wrong_length")

    state["attempts"][oid] += 1
    prerequisites_ok = all(p in state["solved"] for p in puzzle.get("requires_solved", []))
    if code == puzzle["solution"] and prerequisites_ok:
        _solve(state, config, pid)
        return Result(True, [puzzle["success"]], f"solve:{pid}", escaped=state["escaped"])
    return Result(False, [f"You enter {code}. The {name} lock does not open. The code is wrong."], "wrong_code")


def _open(state, config, a):
    oid = a.get("target")
    if oid in config["items"]:
        return Result(False, [f"The {config['items'][oid]['name']} cannot be opened."], "cannot_open")
    if oid not in config["objects"]:
        return _nonexistent(a)
    obj = config["objects"][oid]
    if "lock" not in obj:
        return Result(True, _describe_object(state, config, oid), f"examine:{oid}")
    if state["locked"][oid]:
        return Result(False, [obj.get("description_locked", obj["description"]), "It won't open."], "locked")
    _discover_contents(state, config, oid)
    return Result(True, _describe_object(state, config, oid), f"open:{oid}")


def _inventory(state, config, a):
    if not state["inventory"]:
        return Result(True, ["Your pockets are empty."], "inventory")
    names = [config["items"][i]["name"] for i in state["inventory"]]
    return Result(True, ["You are carrying: " + ", ".join(names) + "."], "inventory")


def _hint(state, config, a):
    for h in config["hints"]:
        if h["until"] not in state["solved"]:
            state["hints_used"] += 1
            return Result(True, ["Hint: " + h["text"]], "hint")
    return Result(True, ["You have already solved everything."], "hint")


def _meta(state, config, a):
    """Anything that tries to change the rules from outside the game world."""
    facts = ["Nothing in the room changes. The rules of the room cannot be changed by words alone — only by "
             "actions inside the game."]
    if "claim" in a.get("flags", []):
        open_locks = [config["objects"][o]["name"] for o, v in state["locked"].items() if v]
        if open_locks:
            facts.append("Still locked: " + ", ".join(open_locks) + ".")
    return Result(False, facts, "meta_rejected")


def _nonexistent(a):
    raw = a.get("raw_target")
    what = f"any {raw}" if raw else "anything like that"
    return Result(False, [f"There isn't {what} in this room."], "nonexistent")


def _unknown(state, config, a):
    return Result(False, ["That doesn't seem possible here. Try to examine, take, use or open something, "
                          "or enter a code."], "unknown")


HANDLERS = {
    "look": _look,
    "examine": _examine,
    "take": _take,
    "use": _use,
    "enter_code": _enter_code,
    "open": _open,
    "inventory": _inventory,
    "hint": _hint,
    "meta": _meta,
    "unknown": _unknown,
}


def apply_action(state, action, config, player_input=""):
    """Validate + apply one action. Mutates `state`, returns Result."""
    if state["escaped"]:
        return Result(False, ["You have already escaped. Restart to play again."], "game_over", escaped=True)
    state["turn"] += 1
    handler = HANDLERS.get(action.get("action"), _unknown)
    result = handler(state, config, action)
    result.escaped = state["escaped"]
    state["history"].append({
        "turn": state["turn"],
        "input": player_input,
        "action": action,
        "ok": result.ok,
        "event": result.event,
    })
    return result
