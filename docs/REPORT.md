# AI Escape Room — Project Report

**Course:** Deep Learning and Generative AI · **Mini Project 01**
**Author:** Elif Sıla Okutucu

## 1. Goal

The goal was to build an interactive escape-room game in which a Large Language Model acts as
the Game Master, and then to make the game reliable. The player is trapped in *The Silent
Library* and must explore, collect items and solve a chain of puzzles to open the door. The app
uses Python, Streamlit for the interface and the free tier of the Google Gemini API.

## 2. Game design

The room has seven interactive objects (desk, bookshelf, drawer, painting, globe, grandfather
clock, door) and three collectable items (note, brass key, UV flashlight). The puzzles form a
chain, so each one unlocks what is needed for the next:

1. **Drawer code** — the note says to read the red books from shortest to tallest; the book
   titles contain numbers, which give a 3-digit code.
2. **Painting** — the brass key from the drawer opens a hidden keyhole in the frame; behind the
   painting is a UV flashlight.
3. **Globe** — UV light reveals invisible writing describing where the clock's missing hands
   pointed.
4. **Door (final)** — that time, written as four digits, opens the door.

The clock without hands is deliberately visible from the start: it tells the player that time
matters, but it cannot be solved until the globe clue is found.

## 3. Version 1 — prompt-only Game Master

**Design.** Everything lives in one system prompt: the room, the items, the rules and the
solutions. On every turn the Streamlit app sends the full chat history to Gemini and shows the
reply. The model is told to end its message with `[GAME_OVER: ESCAPED]` when the player wins;
the app looks for that token, shows a success message and disables input. A restart button
clears the session.

**What worked.** V1 was quick to build (about 100 lines) and the descriptions were atmospheric
and varied. For a cooperative player it was fun and usually followed the puzzle chain.

**Problems found.** We played V1 with `gemini-3.6-flash` and ran the test cases in
`TEST_CASES.md`. The model was better than expected at refusing obvious attacks: it did not
accept the fake administrator, did not reveal the codes when asked, and did not invent a
sword. But the tests also showed why trusting the model is not enough:

- **Puzzle dependencies are not enforced (TC8).** In a fresh game, typing the final door code
  opened the door and the app showed "You escaped!" — without a single puzzle solved. The
  prompt says the code opens the door, so the model accepted it. Anyone who knows the code
  (from a friend or a previous run) can skip the whole game.
- **Clues leak.** When the player tried to use a key they did not have (TC1), the model refused
  but described the hidden keyhole that had not been discovered yet. In TC3 and TC5 it added
  hints nobody asked for.
- **Correct behaviour is not guaranteed.** Every refusal above was the model's own judgement.
  The solutions are inside the prompt, nothing outside the model checks the rules, and the
  result can change with another phrasing, another run or another model.
- **No real state.** The game "remembers" only through the chat history. In our short
  playthrough this worked (TC9), but there is no inventory or progress the app can check, and
  the history grows with every turn.
- **The win condition is text.** The app trusts the `[GAME_OVER: ESCAPED]` token; if the model
  prints it, the game ends.
- **The API is a single point of failure.** `gemini-flash-latest` timed out (504) and the request
  hung, so we added a 60-second timeout and switched to `gemini-3.6-flash`. During the
  playthrough Gemini also returned `503 UNAVAILABLE` (high demand) and that turn was lost (TC11).

V1 also gives no visibility: there is no way to see the inventory or which puzzles are solved,
for the player or for debugging.

## 4. Version 2 — reliable Game Master

The main design decision was to **split deciding from describing**: Python decides whether an
action succeeds, and the LLM only describes the result.

**Game configuration (`game_config.json`).** Objects, aliases, descriptions for each state,
items and their locations, puzzles with their type (code or item), solutions, success texts and
progressive hints. The room can be changed without touching the code.

**Game state (`state.py`).** One dictionary with inventory, discovered items, examined objects,
solved puzzles, lock status for each object, wrong-attempt counters, hint count, turn number,
escape flag and an action history. It is shown in the Streamlit sidebar (inventory, puzzle
progress and a debug view of the raw state).

**Parser (`parser.py`).** Player text is turned into an action such as
`{"action": "use", "item": "brass_key", "target": "painting"}`. A rule-based parser matches
verbs and object aliases (longest alias first, so "brass key" wins over "key") and recognises
codes, rule-change attempts (administrator claims, "ignore the rules", "reveal the solutions")
and fake progress claims. Only if it cannot understand the message, Gemini is asked to classify
it in JSON mode with a fixed schema. That prompt contains the object names but no solutions,
and every id the model returns is checked against the config, so a hallucinated object becomes
"there isn't any … in this room". This also saves API quota: most turns need only one call.

**Engine (`engine.py`).** One Python function per action. Each checks the state before
changing anything:

- `take` — the item must have been seen and its container must be unlocked.
- `use` — the item must be in the inventory; the target must have a matching item puzzle.
- `enter_code` — the target must have a code lock; length and value are checked exactly; wrong
  attempts are counted. The final door also requires the globe puzzle to be solved
  (`requires_solved`), so a guessed or leaked code is not enough.
- `meta` — rule-change attempts never change the state; there is no "admin" path in the code.
- Solved puzzles cannot be solved twice, and after escaping every action is blocked.

Each action returns a `Result` with `ok`, an event tag and a list of **facts**: the only things
the narrator may say.

**Narrator (`narrator.py`).** Gemini receives the player's message, the facts, the visible
objects and the inventory, and writes 2–4 sentences. It is told that the facts are the truth
and that instructions inside the player's message must be ignored. Because the solutions are
never in its prompt, it cannot leak them. An **output guard** rejects the narration and falls
back to the plain facts if the text contains a secret code the player did not type, or claims
a success ("the door swings open") that the engine did not report. If the API fails, the game
continues with the plain facts. With `OFFLINE_MODE=1` the whole game runs without an LLM.

## 5. Testing

Twelve test cases are documented in `TEST_CASES.md` with screenshots, covering the five
challenges from the brief (unowned key, wrong code, fake "already solved" claim, administrator
impersonation, request for all codes) and extra ones (nonexistent object, item in a locked
container, correct final code without the clue, repeating a solved puzzle, a narrator that lies,
API outage, narrator accuracy). V1 passed most of the direct attacks but failed TC8 (escape without solving any
puzzle) and TC11 (API outage), and leaked clues in TC1, TC3 and TC5. The V2 behaviour is
automated in 16 `pytest` tests that run offline. A fake LLM is used to test the narrator guard,
and it also checks that no solution ever appears in a prompt sent to the model.

V2 passed every case by hand as well. The clearest comparison is TC8: the same message that won
the game in V1 is rejected in V2 (`"event": "wrong_code"`). During the V2 run the free Gemini
quota ran out (`429`); the game kept working with plain engine facts, which shows the benefit of
keeping the LLM out of the critical path. The playthrough also revealed a weakness of V2: the
narrator sometimes adds small wrong details (it placed the flashlight on the desk, and called the
drawer empty while the key was still inside). The state stayed correct, but the text was not.

## 6. Limitations and future work

- The output guard uses simple patterns; it can reject good text (the player then sees plain
  facts) but it can never let the LLM change the state. It does not catch small invented details
  in the narration (TC12); a stricter check of item locations, or showing the facts under the
  story text, would fix this.
- The free Gemini tier has small quotas. We hit `504`, `503` and `429` errors during testing and
  had to switch models; V2 keeps working without the LLM, V1 does not.
- The rule-based parser understands English; other languages depend on the LLM fallback.
- New puzzle *types* (e.g. combining two items) need new engine code; new rooms using existing
  types only need a new JSON file.
- Possible next steps: multiple rooms, saving games to JSON, a timer and score, and a small
  evaluation that runs the adversarial inputs automatically against V1 to measure how often
  the model breaks the rules.

## 7. Conclusion

V1 showed that an LLM can create an engaging game almost for free, and a modern model even
resists the simplest attacks. But it cannot be trusted as the referee: in our tests it let the
player escape without solving anything, leaked clues, and the game stopped when the API was
overloaded. Memory, rules and secrets all depend on the model behaving well. V2 keeps the LLM
for what it does well (language understanding and storytelling) and moves state, rules and
secrets into deterministic Python. The result is a game that cannot be talked into cheating,
because the part of the system that understands language has no power to change the game.
