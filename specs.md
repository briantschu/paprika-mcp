# Specification for Paprika grocerylist and recipe MCP server

## Usages

This server is designed to be driven by a voice agent: the user speaks in natural language, the LLM picks the right MCP tool, and the server returns short, speakable results. Everything that takes a list or item identifier accepts either a name or a UID — the server resolves names case-insensitively and falls back to unambiguous substring matches. When a request is ambiguous, the server returns a structured error with the candidates so the LLM can ask the user to disambiguate rather than silently picking one.

**"Removing" a grocery item means marking it as purchased**, not deleting it. When a user says *"remove chocolate from my list"*, *"take the chicken off"*, or *"I bought the eggs"*, the intent is the same: the item should disappear from the active (unchecked) shopping view. The MCP server implements this by setting `purchased=true` on the item via Paprika's sync endpoint. The item stays in Paprika's history (visible under the checked-off section in the app) so the user can un-check or re-add it later. The server never permanently destroys grocery items.

The scenarios below show the expected flow: user utterance → tool call(s) the LLM should make → server response → spoken reply.

### Scenario 1 — Browsing grocery lists

> **User:** "Tell me which grocery lists I have."

- LLM calls `get_groceries` with no arguments.
- Server returns the unchecked items grouped by list (the response includes the list name/UID for each item).
- **Assistant:** "You have two lists: *Default* with 7 items, and *Costco run* with 3 items."

> **User:** "What's on the Costco list?"

- LLM calls `get_groceries` with `include_purchased=false` and filters the response to the *Costco run* list (or, if implemented, passes `list_name_or_id="Costco run"`).
- **Assistant:** "Olive oil, paper towels, and a rotisserie chicken."

### Scenario 2 — Adding an item

> **User:** "Add chocolate to my grocery list."

- LLM calls `add_grocery_item` with `name="chocolate"`, `ingredient="chocolate"` and no `list_name_or_id` (uses the default list).
- Server returns the created item's UID and the list it was added to.
- **Assistant:** "Added chocolate to your default list."

> **User:** "Actually make it 200 grams of dark chocolate, on the Costco list."

- LLM calls `remove_grocery_item` with `item_name_or_id="<uid from previous turn>"` to undo the first add.
- LLM calls `add_grocery_item` with `name="dark chocolate"`, `ingredient="dark chocolate"`, `quantity="200g"`, `list_name_or_id="Costco run"`.
- **Assistant:** "Done — 200 grams of dark chocolate is on the Costco list."

### Scenario 3 — Disambiguating a removal

> **User:** "Remove choco from my grocery list."

- LLM calls `remove_grocery_item` with `item_name_or_id="choco"`.
- Server finds no exact match for "choco" but sees "chocolate" and "chocolate chips" as substring candidates among the unpurchased items and returns an `AmbiguousMatchError` listing both with their UIDs and list names.
- **Assistant:** "There's no item called *choco*, but I see *chocolate* on your default list and *chocolate chips* on the Costco list. Which one should I check off?"

> **User:** "The plain chocolate one."

- LLM calls `remove_grocery_item` with the UID of the *chocolate* candidate from the previous response (preferring UID over name once disambiguated).
- Server marks the item `purchased=true`; it's no longer in the active list but remains in Paprika's checked-off history.
- **Assistant:** "Done — chocolate is checked off your default list."

### Scenario 4 — Single-match removal ("I bought it")

> **User:** "I picked up the rotisserie chicken."

- LLM calls `remove_grocery_item` with `item_name_or_id="rotisserie chicken"`.
- Server finds exactly one unambiguous match across the user's active lists and marks it purchased.
- **Assistant:** "Got it, rotisserie chicken is checked off."

> **User:** "Wait, I grabbed the wrong one, put it back."

- The MCP server has no "un-purchase" tool today; the LLM should tell the user to un-check it from the Paprika app, or (future enhancement) call a dedicated `restore_grocery_item` tool.
- **Assistant:** "I can't un-check items yet — open the Paprika app and tap *rotisserie chicken* in the purchased section to put it back on the active list."

### Scenario 5 — Browsing recipes

> **User:** "What chicken recipes do I have?"

- LLM calls `list_recipes` with `query="chicken"` and `names_only=true`.
- Server filters the cache for "chicken" in the recipe name or ingredients (case-insensitive substring) and returns only `[{uid, name}]` — no ingredients block, keeping the response compact.
- **Assistant:** "You have four: *Lemon roast chicken*, *Thai basil chicken*, *Chicken tikka masala*, and *Chicken noodle soup*."

> **User:** "Tell me more about the Thai basil chicken."

- LLM calls `list_recipes` with `query="Thai basil chicken"` and `names_only=false` (default).
- Server returns the full recipe including ingredients, description, notes, times, and servings.
- **Assistant:** "Thai basil chicken serves 4. Ingredients: …"

#### `list_recipes` tool contract

- **`query`** (optional, default `""`) — Case-insensitive substring filter applied to both `name` and `ingredients`. Returns all non-trashed recipes when omitted.
- **`names_only`** (optional, default `false`) — When `true`, each result contains only `uid` and `name`. Use this for browsing/searching where ingredients aren't needed. When `false`, the full recipe body is returned (ingredients, description, notes, times, servings).
- **`limit`** (optional, default `50`) — Maximum results after filtering.

### Scenario 6 — Cooking a recipe and stocking up

> **User:** "I want to make the Thai basil chicken tonight. Add what I'm missing to the grocery list."

- LLM calls `list_recipes` and locates *Thai basil chicken* (name match → UID + ingredients block).
- LLM compares the recipe's ingredients to the current pantry context the user has shared (or just asks the user which ones they're missing).
- For each missing ingredient the LLM calls `add_grocery_item` with `name`/`ingredient` set to the ingredient line and `list_name_or_id` left empty (default list).
- **Assistant:** "Added Thai basil, fish sauce, and bird's eye chillies to your default list."

### Scenario 7 — Saving a new recipe dictated by voice

> **User:** "Save a new recipe called *Quick weeknight pasta*. Ingredients: 200 grams spaghetti, two cloves of garlic, olive oil, chilli flakes, parsley. Directions: boil the pasta, sizzle the garlic and chilli in olive oil, toss together, finish with parsley."

- LLM calls `create_recipe` with `name="Quick weeknight pasta"`, `ingredients` as a newline-separated string, `directions` as the spoken instructions, and leaves the optional fields empty.
- Server returns the new UID; the recipe cache picks it up on the next `list_recipes` invocation via the index hash diff.
- **Assistant:** "Saved *Quick weeknight pasta* to your recipes."

### Scenario 8 — Editing an existing recipe

> **User:** "On the Thai basil chicken, change the prep time to 10 minutes and add a note that the kids prefer it without chillies."

- LLM calls `list_recipes` to resolve *Thai basil chicken* → UID.
- LLM calls `update_recipe_partial` with `uid=<that uid>`, `prep_time="10 mins"`, and `notes` set to the appended note text.
- **Assistant:** "Updated."

### Scenario 10 — Adding all recipe ingredients to the grocery list in one step

> **User:** "I'm making Thai basil chicken tomorrow. Add all the ingredients to my shopping list."

- LLM calls `add_recipes_to_grocery_list` with `recipes=["Thai basil chicken"]` (and optionally `list_name_or_id` if the user named a specific list).
- Server resolves the recipes by name from the cache, parses their `ingredients` fields line by line, and adds each non-empty line as a grocery item — all linked back to the recipe via Paprika's `recipe_uid` field so the Paprika app can group them under the recipe name in its shopping view.
- Server returns a summary: recipe names, number of items added, and the target list.
- **Assistant:** "Added 8 ingredients for Thai basil chicken to your default shopping list."

> **User:** "Actually, put them on the Costco list."

- LLM calls `add_recipes_to_grocery_list` with `recipes=["Thai basil chicken"]` and `list_name_or_id="Costco run"`.
- **Assistant:** "Done — 8 ingredients for Thai basil chicken are on your Costco list."

#### Tool contract

- **Name**: `add_recipes_to_grocery_list`
- **Parameters**:
  - `recipes` (required) — List of names or UIDs of the recipes to add. Resolved via the recipe cache.
  - `list_name_or_id` (optional) — Target grocery list. Defaults to the user's default list if omitted.
- **Returns**: Plain-text summary: recipe names, number of items added, list name.
- **Errors**: Uses the same error codes as other tools — `recipe_not_found` if the recipe cannot be resolved, `grocery_list_not_found` if the list name doesn't exist, plus the standard connectivity codes.
- **Recipe linking**: Every grocery item must have `recipe_uid` set to the recipe's UID, and `recipe` set to the recipe name. The Paprika app uses both to group the items under the recipe name in the shopping view.
- **Bulk POST**: All ingredients are sent in a **single POST** to `/sync/groceries/` as a JSON array (gzip-compressed multipart). This is more efficient than one call per item and matches how the official app adds a recipe to the shopping list.
- **`aisle` field**: Automatically assigned based on historical groceries in the user's account and keyword classification, falling back to `"Miscellaneous"` so items are never uncategorized.
- **`separate` field**: Set to `false` for all items (matches the official app behaviour; `true` would visually separate the item from others in the same aisle).
- **Ingredient parsing**: Each non-empty, non-whitespace line of the recipe's `ingredients` field becomes one grocery item. The full line is used as both `name` and `ingredient`; `quantity` is left empty (the quantity is embedded in the ingredient line as Paprika stores it).

> **API reference**: [`aarons22/paprika-tools` API_REFERENCE.md §Grocery](https://github.com/aarons22/paprika-tools/blob/main/API_REFERENCE.md) — community-maintained reference for the undocumented Paprika sync API.

### Scenario 9 — Errors the user should hear in plain language

The voice agent's worst failure mode is *"Sorry, something went wrong."* Every tool the server exposes must therefore return errors that (a) name **what** failed, (b) name **why** in one short clause, and (c) where useful, suggest **what to do next**. The server returns errors via the MCP `isError=true` flag with a `TextContent` body that is already phrased for TTS — no stack traces, no UIDs, no HTTP status codes in the user-visible text. Detailed diagnostics go to the server log only.

The categories below are the contract the LLM relies on. Each has a stable error code (returned in `structuredContent.code`) so the LLM can branch on category instead of pattern-matching prose.

#### 9a. Paprika unreachable (`paprika_unreachable`)

> **User:** "What's on my grocery list?"

- LLM calls `get_groceries`.
- Server cannot reach `paprikaapp.com` (DNS, TCP, TLS, or timeout).
- Tool returns `isError=true`, code `paprika_unreachable`, text *"I can't reach the Paprika service right now. Please try again in a moment."*
- **Assistant:** "I can't reach Paprika right now. Want me to try again in a minute?"

#### 9b. Authentication failed (`paprika_auth_failed`)

> **User:** "Add milk to the list."

- LLM calls `add_grocery_item`.
- Paprika rejects the credentials (HTTP 401/403 even after a re-login attempt).
- Tool returns code `paprika_auth_failed`, text *"Paprika rejected my login. The saved username or password is probably wrong."*
- **Assistant:** "Paprika won't accept my login. You'll need to update the credentials on the server."

#### 9c. Rate-limited (`paprika_rate_limited`)

> **User:** "List my recipes."

- LLM calls `list_recipes` while the recipe-cache warm-up is being throttled by Paprika (HTTP 429 or temporary IP block).
- If a populated cache exists, the server serves stale data and notes it ran without a refresh — **not** an error.
- If no cache exists yet, the tool returns code `paprika_rate_limited`, text *"Paprika is rate-limiting us. I'll have your recipes ready in a couple of minutes."*
- **Assistant:** "Paprika is throttling me — give it a minute or two and ask again."

#### 9d. Item not found (`grocery_not_found`)

> **User:** "Take the kale off the list."

- LLM calls `remove_grocery_item` with `item_name_or_id="kale"`.
- No active item matches `kale` — not even as a substring.
- Tool returns code `grocery_not_found`, text *"There's nothing called 'kale' on your active grocery lists."*
- **Assistant:** "I don't see kale on your list. Did you maybe already check it off?"

#### 9e. Ambiguous match (`grocery_ambiguous`)

Already shown in Scenario 3, but spelled out as a category: the tool returns `isError=true` (so the LLM treats it as a branch, not a success), code `grocery_ambiguous`, plus `structuredContent.candidates` containing `[{uid, name, list_name}, …]`. The text body lists the candidates by **name and list** only — never UIDs aloud.

- **Assistant (reading the candidates):** "I see two: *chocolate* on your default list and *chocolate chips* on the Costco list. Which one?"

#### 9f. List not found (`grocery_list_not_found`)

> **User:** "Add olives to the *Trader Joe's* list."

- LLM calls `add_grocery_item` with `list_name_or_id="Trader Joe's"`.
- The user has no list resembling that name (no exact, substring, or fuzzy match).
- Tool returns code `grocery_list_not_found`, text *"You don't have a grocery list called 'Trader Joe's'. Your lists are: Default, Costco run."*
- **Assistant:** "There's no Trader Joe's list. You have Default and Costco run — want me to add olives to one of those?"

#### 9g. Recipe not found (`recipe_not_found`)

> **User:** "Update the prep time on *Quick weeknigt pasta* to 15 minutes." *(typo)*

- LLM calls `list_recipes`, finds no match for *weeknigt*, and either (a) does the substring search itself and asks the user, or (b) calls `update_recipe_partial` with a guessed UID.
- If the call is made with a UID that doesn't exist, the tool returns code `recipe_not_found`, text *"I can't find a recipe with that ID. It may have been deleted."*
- **Assistant:** "I can't find that recipe — did you maybe mean *Quick weeknight pasta*?"

#### 9h. Missing or invalid argument (`invalid_argument`)

> **User:** "Save a new recipe." *(no name, no ingredients)*

- LLM calls `create_recipe` with empty `name`.
- The MCP SDK's input-schema validator fails the call before it reaches our code; it produces *"Input validation error: 'name' is a required property."*
- The server upgrades that to a friendlier message via the same code: *"I need a name and at least the ingredients to save a recipe."*
- **Assistant:** "I need a name for the recipe — what should I call it?"

#### 9i. Unexpected Paprika failure (`paprika_error`)

Catch-all for any other non-2xx Paprika response (e.g. 5xx, malformed JSON). The tool returns code `paprika_error`, text *"Paprika returned an unexpected error. I've logged the details."* The server logs the status code and response body for the operator. **Never** echo Paprika's raw response into the assistant message — voice users don't want HTML or JSON read aloud.

- **Assistant:** "Something went wrong on Paprika's side. Try again in a moment, and if it keeps happening, check the server log."

### Conventions the LLM should follow

- **Resolve once, act with UIDs.** When a follow-up turn references an item the LLM just looked up, pass the UID rather than re-sending the name — this avoids re-triggering the disambiguation path.
- **Never silently pick on ambiguity.** If the server returns an `AmbiguousMatchError`, surface the candidates to the user instead of guessing.
- **Default list is implicit.** Omit `list_name_or_id` unless the user names a specific list.
- **Purchased items are hidden by default.** Only pass `include_purchased=true` to `get_groceries` if the user explicitly asks about already-bought items. `remove_grocery_item` only matches against unpurchased items for the same reason.
- **Read errors as their category, not their prose.** Branch on `structuredContent.code` (see Scenario 9) rather than parsing the user-facing text. The text is for the user; the code is for the LLM. Never read UIDs, HTTP status codes, or stack traces aloud.
- **Bulk ingredient add.** When the user wants to plan a meal and add all its ingredients at once, prefer `add_recipes_to_grocery_list` over calling `add_grocery_item` in a loop. The single-call version is faster, keeps items grouped by recipe in the Paprika app, and avoids timeouts on large ingredient lists.
### Scenario 11 — Planning a recipe as dinner on a specific day

> **User:** "Plan the Thai basil chicken as dinner on Saturday."

- LLM resolves "Saturday" to the correct date (e.g. `2026-07-05`).
- LLM calls `plan_meals` with `meals=[{"recipe_name_or_id": "Thai basil chicken", "date": "2026-07-05", "meal_type": "dinner"}]`.
- Server resolves the recipe from cache, builds a meal object, and POSTs it to Paprika's `/sync/meals/` endpoint.
- **Assistant:** "Scheduled Thai basil chicken as dinner on Saturday the 5th."

> **User:** "Put the blueberry muffins on Sunday morning."

- LLM calls `plan_meals` with `meals=[{"recipe_name_or_id": "blueberry muffins", "date": "2026-07-06", "meal_type": "breakfast"}]`.
- **Assistant:** "Scheduled blueberry muffins as breakfast on Sunday the 6th."

#### Tool contract

- **Name**: `plan_meals`
- **Parameters**:
  - `meals` (required) — List of meals to schedule. Each meal requires:
    - `recipe_name_or_id` (required) — Name or UID of the recipe.
    - `date` (required) — Target date in `YYYY-MM-DD` format.
    - `meal_type` (optional, default `"dinner"`) — The name of one of the account's meal types: the built-in `breakfast`, `lunch`, `dinner`, `snack`, or a custom one (e.g. `make-ahead`). Matching ignores case, punctuation and a trailing "s" (`snack` matches *Snacks*); a renamed built-in type still matches its original slot name. An unknown name returns `invalid_argument` listing the account's meal types.
- **Returns**: Plain-text spoken confirmation: number of meals scheduled, and details per meal.
- **Errors**: `recipe_not_found` if any recipe cannot be resolved; `invalid_argument` if the date format or meal type is invalid; standard connectivity codes.
- **API**: POSTs a gzip-compressed JSON array to `POST /v2/sync/meals/`. There is no per-uid meals endpoint; all meal plan writes go to the array endpoint. `date` uses `"YYYY-MM-DD 00:00:00"` format.
- **Meal types (`type_uid`)**: Paprika decides a planned meal's category from `type_uid`, the `uid` of one of the account's meal types from `GET /v2/sync/mealtypes/` (`{uid, name, original_type, order_flag, color, export_time, export_all_day}`). An empty `type_uid` puts the meal in the wrong category. The server reads the meal types once per run (so changes in the app are picked up when the server restarts) and re-reads them once when a name doesn't match. It sets `type_uid` on every write.
- **Meal type integers (`type`)**: legacy field, kept in sync with the meal type's `original_type`: `breakfast=0`, `lunch=1`, `dinner=2`, `snack=3`. Custom types have no `original_type`; the server sends `3`, which is what the Paprika app stored for almost all entries of a custom type. `type` doesn't decide the category: real entries of one custom type carry both `0` and `3`.
- **Fallback**: if `/sync/mealtypes` returns nothing usable, the server falls back to the four built-in slots with an empty `type_uid` and logs a warning. Rate-limit, auth and connectivity errors are returned as usual.

### Scenario 12 — Reviewing past meals and upcoming meal plans

> **User:** "What have I eaten the past few days?"

- LLM calls `get_plan` with default arguments (or `days_back=7`, `days_ahead=0`).
- Server queries `GET /v2/sync/meals/`, filters by date range around today, and formats the meal list.
- **Assistant:** "Over the past few days you had: on Thursday Courgettesoep with salmon, on Friday Kip Kerrie, and on Saturday Thai basil chicken."

> **User:** "What's planned for dinner this week?"

- LLM calls `get_plan` with `days_back=0`, `days_ahead=7`.
- **Assistant:** "This week you have planned: on Monday Spaghetti Bolognese, and on Wednesday Mexicaanse wraps."

#### Tool contract

- **Name**: `get_plan`
- **Parameters**:
  - `days_back` (optional, default `30`, min `0`, max `365`) — Number of past days to look back for meals eaten.
  - `days_ahead` (optional, default `14`, min `0`, max `365`) — Number of future days to look ahead for planned meals.
- **Returns**: Plain-text overview split into past meals and upcoming meals, with day of the week, meal type, recipe names, and entry IDs (`[id: <uid>]`). The meal type is the name of the entry's `type_uid` meal type (e.g. `make-ahead`), falling back to the numeric `type` for entries without one; meals within a day are ordered by the meal types' `order_flag`.
- **Errors**: Standard connectivity codes.
- **API**: Queries `GET /v2/sync/meals/`.

### Scenario 13 — Deleting or moving a planned meal

> **User:** "Remove dinner on Friday."

- LLM calls `delete_planned_meal` with `date="2026-10-23"`, `meal_type="dinner"`.
- Server marks the matching meal entry as `deleted=true` and syncs.
- **Assistant:** "Deleted planned meal *Pasta* on Friday the 23rd."

> **User:** "Actually, move tonight's dinner to tomorrow."

- LLM calls `move_planned_meal` with `date="2026-10-22"`, `meal_type="dinner"`, `to_date="2026-10-23"`.
- Server updates the meal's `date` and syncs.
- **Assistant:** "Moved planned meal *Kipfilet* to tomorrow."

> **User:** "Saturday's casserole should be under make-ahead, not breakfast."

- LLM calls `move_planned_meal` with the entry's `entry_id` (from `get_plan`), the same `to_date`, and `to_meal_type="make-ahead"`.
- Server sets the entry's `type_uid` (and `type`) to the *Make-ahead* meal type and syncs. `meal_type`/`to_meal_type` in `delete_planned_meal` and `move_planned_meal` accept the same names as `plan_meals`, and matching uses `type_uid`.
- **Assistant:** "Moved the casserole to make-ahead on Saturday."

### Scenario 14 — Updating existing grocery items

> **User:** "Move the eggs into Dairy."

- LLM calls `update_grocery_item` with `item_name_or_id="eggs"`, `aisle="Dairy"`.
- Server strictly matches the item and syncs the updated aisle.
- **Assistant:** "Updated *eggs* to aisle *Dairy*."


## MCP Client Requirements & Transport Protocols

Leverage nginx for authorisation or https and reverse proxy where required.

This server speaks two transports: `stdio` (for clients that spawn it as a child process) and **Streamable HTTP** at a single `/mcp` endpoint (for network clients). Streamable HTTP is the current MCP standard and supersedes the legacy SSE transport — every supported client below now uses `/mcp`.

### 1. Claude Desktop
- **Transport**: `stdio` (native), or Streamable HTTP via a remote bridge.
- **Requirements**: Claude Desktop spawns the server as a local child process using `stdio`. To connect to a remote instance, point Claude Desktop at the `/mcp` URL (directly if the build supports remote MCP, or via a small bridge configured in `claude_desktop_config.json`).

### 2. Home Assistant
- **Transport**: Streamable HTTP at `/mcp`.
- **Requirements**: Home Assistant's *Model Context Protocol* integration connects over HTTP/HTTPS to the `/mcp` endpoint (e.g. `http://<lan-ip>:8001/mcp` on the server's unauthenticated LAN listener, `--lan-host`/`--lan-port`). Home Assistant asks for a fixed OAuth client ID and secret when a server requires login, while this server only supports dynamic client registration, so Home Assistant uses the LAN listener rather than the OAuth-protected public endpoint.

### 3. Google Antigravity
- **Transport**: `stdio` or Streamable HTTP.
- **Requirements**: Configure the local command for `stdio`, or the remote `/mcp` URL for network access.

### 4. Gemini CLI
- **Transport**: `stdio` or Streamable HTTP.
- **Requirements**: Use `command` for a local `stdio` subprocess, or `httpUrl` pointing at the remote `/mcp` endpoint.

### 5. VSCode GitHub Copilot
- **Transport**: `stdio` or Streamable HTTP.
- **Requirements**: The GitHub Copilot Chat extension supports MCP via `github.copilot.chat.mcpServers`. Local `stdio` subprocesses or a remote `/mcp` URL both work.

### 6. Claude.ai (Web)
- **Transport**: Streamable HTTP over HTTPS.
- **Requirements**: Web-based cloud models cannot spawn local subprocesses. Expose `/mcp` over HTTPS via a reverse proxy (Nginx, Cloudflare Tunnels, etc.) so Claude.ai can reach it.

### 7. Gemini (Web)
- **Transport**: Streamable HTTP over HTTPS.
- **Requirements**: Same as Claude Web — a publicly resolvable HTTPS `/mcp` URL.

## Recipe cache

`list_recipes` must return quickly enough for an interactive LLM tool call (well under 10 s, ideally <1 s after warm-up). The Paprika cloud API has no batch "fetch all recipes" endpoint: each recipe body must be retrieved with `GET /sync/recipe/{uid}/`. Doing this sequentially for a real library (40–500+ recipes) blows past any LLM tool-call timeout, and Paprika additionally applies aggressive per-IP rate limiting (multi-minute IP blocks for bursty traffic, as documented by the community in the [reverse-engineered API gist](https://gist.github.com/mattdsteele/7386ec363badfdeaad05a418b9a1f30a)).

The MCP server therefore maintains an in-memory recipe cache, persists it to disk between restarts, and only refetches what has actually changed.

### Data model (in-process state)

- `recipe_cache: dict[uid, recipe_dict]` — full recipe bodies as last seen.
- `recipe_index_fingerprint: str` — SHA-256 over the sorted list of `(uid, hash)` pairs returned by `/sync/recipes`. This is the cheap "did anything change" signal.
- `cache_ready: asyncio.Event` — set as soon as the warm-up starts (after loading the on-disk copy), so `list_recipes` never blocks a tool call for the minutes a paced first download can take.
- `cache_lock: asyncio.Lock` — serializes refresh so concurrent tool calls don't all stampede the Paprika API. While it is held, `list_recipes` serves the recipes cached so far instead of waiting.
- `refresh_progress: (downloaded, total)` — set while recipe bodies are downloading; the `list_recipes` tool prefixes its output with a "still downloading (N of M)" note so the LLM knows the list may be incomplete.
- `rate_limit_backoff: bool` — true while the warm-up is waiting out a 429; `list_recipes` then serves the cache without calling Paprika (or returns `paprika_rate_limited` if the cache is empty).

### Invalidation strategy

Each `list_recipes` invocation runs this minimal protocol:

1. `GET /sync/recipes` — one cheap call returning `[{uid, hash}, …]` for the entire library.
2. Compute the fingerprint over that list and compare to `recipe_index_fingerprint`.
   - If unchanged → return the cached recipe bodies. **Zero per-recipe calls.**
3. If changed, diff against the cache:
   - **drop** any uid no longer in the index (deleted on the server).
   - **stale** = uids whose hash differs from the cached hash, plus uids not yet in the cache.
4. Refetch only the stale recipes via `/sync/recipe/{uid}/`, **one at a time** with a minimum gap of `RECIPE_FETCH_INTERVAL_SECONDS` (0.5 s) between requests to stay under Paprika's rate limit.
5. **Stop at the first 429.** Every further request during a block only extends it, so the batch ends immediately: recipes fetched so far are kept (and saved), the fingerprint is *not* committed, and `PaprikaRateLimitedError` is raised so the caller can back off. The next refresh fetches only what is still missing.
6. Update the cache and the fingerprint, and save the cache to disk if anything changed.

This mirrors how the official Paprika app keeps in sync (small status check + selective per-recipe pull) and is the explicitly-recommended pattern from the community gist to avoid IP bans.

### Startup warm-up

On server startup the MCP server schedules a background warm-up task. It first loads the on-disk cache (see below), then runs a normal refresh, so after the first run only recipes that changed while the server was down are downloaded. The server itself becomes ready immediately so MCP clients can connect and use grocery tools without delay.

When the refresh hits a 429, the warm-up waits and resumes:

- wait `Retry-After` seconds if Paprika sent that header (delta-seconds form), otherwise `RATE_LIMIT_BACKOFF_SECONDS` (30 s) doubling per retry up to `RATE_LIMIT_BACKOFF_MAX_SECONDS` (300 s);
- the retry counter resets whenever a retry made progress;
- after `RATE_LIMIT_MAX_RETRIES` (5) consecutive retries without progress it gives up and logs; the next `list_recipes` call retries the missing recipes.

Other errors (network failure, bad credentials) are logged and end the warm-up; the cache keeps whatever was loaded.

During the very first download (no on-disk copy yet), `list_recipes` returns the recipes downloaded so far, and recipe lookups by name in other tools can miss recipes that haven't arrived yet.

### On-disk cache

- Location: `data/recipe_cache.json` (gitignored), overridable with the `PAPRIKA_RECIPE_CACHE_FILE` environment variable; an empty value disables persistence.
- Contents: format version, an owner tag (SHA-256 of the lower-cased Paprika username, so a file is never reused for another account), the committed index fingerprint, and the recipe bodies.
- Written atomically (temp file + rename) with mode `0600`, after every refresh that changed the cache and every 50 recipes during a long download, so an interrupted first download resumes where it stopped.
- A missing, corrupt, other-account or old-format file is ignored and the cache refills from Paprika.

### Trash and limits

- Recipes with `in_trash == True` are excluded from the returned list (they are still kept in the cache so a subsequent un-trash is detected via the hash diff).
- The `limit` argument to `list_recipes` only truncates the returned list; the cache always covers the whole library.

### Why not `/sync/status`

Paprika exposes `/api/v1/sync/status/` as an even cheaper "anything changed?" counter. The current implementation uses the fingerprint of `/sync/recipes` instead because (a) it costs one call either way once we already need the index for diffing, (b) it works regardless of how the v2 API behaves for `/sync/status`, and (c) it is robust against the counter being bumped by unrelated objects (groceries, meals, …) which would otherwise trigger needless full refetches.
