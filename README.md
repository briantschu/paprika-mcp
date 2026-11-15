# Paprika MCP Python Server

A Model Context Protocol (MCP) server that integrates Paprika Recipe Manager with agents, enabling natural language recipe management through AI conversation.

Supported agents:
- Claude Desktop
- Claude Code (CLI)
- Home Assistant
- Google Antigravity
- Gemini CLI
- VS Code GitHub Copilot
- Claude.ai (web)
- Gemini (web)

## Features

- **Recipe Creation**: Create new recipes with natural language descriptions
- **Recipe Updates**: Full and partial recipe updates while preserving existing data
- **Recipe Listing**: Browse all recipes with complete ingredient lists and details
- **Grocery Management**: Add, remove, and list items on your Paprika grocery lists

## Demo

### Creating Recipes
![Creating a recipe with natural language](images/demo-create-recipe.png)

### Recipe Recommendations  
![Getting recipe recommendations](images/demo-list-recipes.png)

## Prerequisites

- [uv](https://docs.astral.sh/uv/) (installs Python 3.12 for you if needed)
- [Paprika Recipe Manager 3](https://www.paprikaapp.com/) with cloud sync enabled, and your Paprika account email and password
- An MCP client, e.g. Claude Desktop, Claude Code, VS Code (Copilot), Gemini CLI, Google Antigravity, or Home Assistant (see [Connect a client](#connect-a-client))
- Optional: [Node.js](https://nodejs.org/) for the MCP Inspector test in step 3

## Quick Start

### 1. Installation

```bash
# Clone the repository
git clone https://github.com/mspoorendonk/paprika-mcp.git
cd paprika-mcp

# Install uv (if you don't have it already)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create the virtual environment (Python 3.12) and install the locked dependencies
uv sync --extra dev
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

This also installs the `paprika-mcp` command at `.venv/bin/paprika-mcp`, which is what MCP clients launch.

### 2. Configuration

Copy the template and fill in your Paprika credentials:

```bash
cp .env.template .env
```

```env
PAPRIKA_USERNAME=your_email@example.com
PAPRIKA_PASSWORD=your_paprika_password
```

That is all a local (stdio) setup needs. The `OAUTH_*` / `GOOGLE_*` variables are only for running it as a network service (see [LAN Deployment](#lan-deployment-run-as-a-network-service)). The server finds `.env` next to the code no matter which directory a client starts it from, so client configs don't need to repeat your password.

### 3. Test the Server

Use the official [MCP Inspector](https://github.com/modelcontextprotocol/inspector) to start the server and call its tools from a browser UI:

```bash
npx @modelcontextprotocol/inspector .venv/bin/paprika-mcp
```

Click **Connect**, open **Tools**, and run `get_groceries`. On the first start the server downloads your recipes in the background (paced to stay under Paprika's rate limit), so `list_recipes` may report that it is still loading for a few minutes.

## Connect a client

There are two ways to connect:

- **Local (stdio):** the client starts `.venv/bin/paprika-mcp` on the same machine. Simplest; nothing listens on the network.
- **Remote (Streamable HTTP):** the server runs as a network service (see [LAN Deployment](#lan-deployment-run-as-a-network-service)) and clients connect to `https://<your-domain>/<prefix>/mcp`, logging in with Google via OAuth.

Replace `/path/to/paprika-mcp` with the absolute path to your clone.

### Claude Desktop

**Local:** Open the config file in one of two ways:

- **From the app:** click the **Claude** menu in your operating system's menu bar (macOS: top of the screen; not the settings inside the Claude window, which have no Developer tab), choose **Settings…**, open the **Developer** tab, and click **Edit Config**. This creates the file if it doesn't exist.
- **Directly:** macOS `~/Library/Application Support/Claude/claude_desktop_config.json`, Windows `%APPDATA%\Claude\claude_desktop_config.json`, Linux `~/.config/Claude/claude_desktop_config.json`. On macOS, open it in TextEdit with:

  ```bash
  open -e ~/Library/Application\ Support/Claude/claude_desktop_config.json
  ```

The file may already contain the app's own settings (e.g. a `preferences` block). Leave those alone and add `mcpServers` as another top-level key, or add `paprika` to it if `mcpServers` already exists:

```json
{
  "mcpServers": {
    "paprika": {
      "command": "/path/to/paprika-mcp/.venv/bin/paprika-mcp"
    }
  }
}
```

Fully quit Claude Desktop (not just close the window) and reopen it. To check that it loaded, click the **+** ("Add files, connectors, and more") button in the message box → **Connectors** → **Manage connectors** and look for `paprika`. If it's missing, check the logs in `~/Library/Logs/Claude/` (`mcp.log` and `mcp-server-paprika.log`).

**Remote:** Go to **Settings → Connectors → Add custom connector** and enter `https://<your-domain>/<prefix>/mcp`. Remote servers can't be added through the JSON file. Custom connectors are reached from Anthropic's cloud, not from your computer, so the URL must be publicly reachable over HTTPS.

### Claude Code (CLI)

```bash
# Local
claude mcp add paprika -- /path/to/paprika-mcp/.venv/bin/paprika-mcp

# Remote
claude mcp add --transport http paprika https://<your-domain>/<prefix>/mcp
```

For the remote server, run `/mcp` in Claude Code (or `claude mcp login paprika`) to complete the Google login in your browser.

### VS Code (GitHub Copilot)

Run **MCP: Add Server** from the Command Palette and follow the guided setup, or edit the config file by hand: `~/.copilot/mcp-config.json` for all projects, or `.mcp.json` in a workspace root:

```json
{
  "mcpServers": {
    "paprika-local": {
      "type": "stdio",
      "command": "/path/to/paprika-mcp/.venv/bin/paprika-mcp"
    },
    "paprika-remote": {
      "type": "http",
      "url": "https://<your-domain>/<prefix>/mcp"
    }
  }
}
```

The older `.vscode/mcp.json` file (with a `"servers"` key) still works but is deprecated, and the `github.copilot.chat.mcpServers` setting is no longer documented.

### Gemini CLI

```bash
# Local
gemini mcp add --scope user paprika /path/to/paprika-mcp/.venv/bin/paprika-mcp

# Remote
gemini mcp add --transport http --scope user paprika https://<your-domain>/<prefix>/mcp
```

Or edit `~/.gemini/settings.json` directly. Gemini CLI uses `httpUrl` for Streamable HTTP (`url` means SSE):

```json
{
  "mcpServers": {
    "paprika-local": {
      "command": "/path/to/paprika-mcp/.venv/bin/paprika-mcp"
    },
    "paprika-remote": {
      "httpUrl": "https://<your-domain>/<prefix>/mcp"
    }
  }
}
```

Gemini runs the OAuth flow and opens a browser for the Google login on first connect.

### Google Antigravity

Edit Antigravity's MCP config (from the agent panel's MCP server settings, or directly at `~/.gemini/config/mcp_config.json`; older versions use `~/.gemini/antigravity/mcp_config.json`). Remote servers use `serverUrl`, not the older `httpUrl`:

```json
{
  "mcpServers": {
    "paprika-local": {
      "command": "/path/to/paprika-mcp/.venv/bin/paprika-mcp"
    },
    "paprika-remote": {
      "serverUrl": "https://<your-domain>/<prefix>/mcp"
    }
  }
}
```

### Home Assistant

Home Assistant connects over the network, so run the server as a network service first (see below). In Home Assistant: **Settings → Devices & Services → Add Integration → "Model Context Protocol"**, and enter the server's `/mcp` URL.

Home Assistant's integration asks for a fixed OAuth client ID and secret when a server requires login, but this server only supports clients that register themselves automatically. So connect Home Assistant to the unauthenticated **LAN listener** instead: start the server with `--lan-host <lan-ip> --lan-port 8001` and enter `http://<lan-ip>:8001/mcp`. Keep that port off your public reverse proxy.

### Claude.ai and Gemini (web)

Web clients can't start local programs, so they need the remote server at a public HTTPS URL. In Claude.ai, add it under **Settings → Connectors → Add custom connector** and complete the Google login. For Gemini on the web, check Google's current documentation for custom MCP server support.

## LAN Deployment (Run as a Network Service)

To share one server between several clients and machines (e.g. Home Assistant and Claude Code), run it in HTTP mode. It exposes a single Streamable HTTP endpoint at `/mcp`.

### 1. Start the Server in HTTP Mode

```bash
# Keep this running, e.g. with systemd or tmux.
# Primary listener: OAuth-protected (put this one behind your HTTPS reverse proxy).
# LAN listener: no auth, for Home Assistant on your local network only.
.venv/bin/paprika-mcp --http --host 127.0.0.1 --port 8000 --lan-host <lan-ip> --lan-port 8001
```

The primary listener requires the OAuth configuration in [section 3](#3-authentication--oauth2-with-google-login). For a purely local network with no reverse proxy, `--no-auth` makes the primary listener unauthenticated too.

### 2. Reverse-Proxy Notes

When fronting the server with nginx (or similar):

- Strip the public prefix before forwarding (e.g. rewrite `^/paprika(/.*)$ $1`).
- Disable buffering for streaming: `proxy_buffering off; proxy_cache off; chunked_transfer_encoding off;` and a long `proxy_read_timeout`.
- Set `proxy_http_version 1.1` and `proxy_set_header Connection '';`.

### 3. Authentication — OAuth2 with Google login

Authentication is OAuth 2.0 — the server is its own Authorization Server and
brokers the human login to Google (OIDC), allow-listing by email. HTTP
Basic-Auth at nginx is **retired**; clients no longer need per-client
passwords. See [`src/oauth_app.py`](src/oauth_app.py) for the implementation.

Server-side config lives in `.env` (gitignored): `OAUTH_ISSUER_URL`,
`OAUTH_PATH_PREFIX`, the Google OAuth client credentials (`GOOGLE_CLIENT_ID`,
`GOOGLE_CLIENT_SECRET`), and the email allowlist (`OAUTH_ALLOWED_EMAILS`).
MCP clients only need the endpoint URL — they register themselves, run the
OAuth flow automatically, and log in with Google in the browser. Access is
revoked by removing an email from the allowlist.

## Usage Examples

Once configured, you can interact with your Paprika recipes through natural language in Claude:

### Create a New Recipe
```
Create a new recipe called "Spaghetti Carbonara" with these ingredients:
- 400g spaghetti
- 4 large eggs
- 100g pancetta
- 50g Parmesan cheese
- Black pepper and salt

Instructions:
1. Cook spaghetti according to package directions
2. Fry pancetta until crispy
3. Beat eggs with Parmesan
4. Combine hot pasta with pancetta
5. Add egg mixture and toss quickly
6. Season and serve immediately

Set servings to 4 people, prep time 10 minutes, cook time 15 minutes.
```

### List Your Recipes
```
Show me all my recipes from Paprika
```

### Update a Recipe
```
Update the Spaghetti Carbonara recipe to serve 6 people instead of 4, and add "Use room temperature eggs to prevent scrambling" to the notes.
```

### Partial Updates
```
For the recipe with UID [recipe-uid], just change the prep time to 15 minutes and add salt to the ingredients list.
```

### Manage Groceries
```
Add chocolate to my grocery list.

Remove choco from my grocery list.
```

## Available Tools

| Tool | Description |
|------|-------------|
| `create_recipe` | Create a new recipe with all details |
| `update_recipe` | Complete recipe update (all fields) |
| `update_recipe_partial` | Update only specified fields |
| `list_recipes` | List all recipes with ingredients and details. Served from a hash-validated in-memory cache so repeated calls are fast and stay under Paprika's per-IP rate limit (see `specs.md` → "Recipe cache"). The cache is warmed in the background at server startup, one recipe at a time, pausing automatically when Paprika rate-limits, and saved to `data/recipe_cache.json` so restarts only download recipes that changed. |
| `get_groceries` | List unchecked grocery items on the Paprika grocery list (set `include_purchased=true` to include checked items) |
| `add_grocery_item` | Add a new item to the Paprika grocery list. Automatically assigns an appropriate aisle/category (based on user history and keywords) so items are never uncategorized. |
| `update_grocery_item` | Update properties of an existing grocery item (aisle/category, name, quantity, instruction, list, or purchased status) |
| `update_grocery_items` | Bulk update multiple grocery items in a single request (e.g. batch re-assigning aisles) |
| `remove_grocery_item` | Remove an item from Paprika groceries. Searches all lists by default; strict matching (exact UID, exact name, or unambiguous substring). Returns the removed item's name, UID, and list UID. Ambiguous matches return an error listing candidates. |
| `add_recipes_to_grocery_list` | Add all ingredients from one or more recipes to the grocery list in a single bulk request, with automatic aisle assignment per ingredient |
| `plan_meals` | Schedule one or more recipes on the Paprika meal planner for specific dates and meal types, including custom meal types such as "Make-ahead" (uses strict matching to prevent scheduling incorrect recipes) |
| `get_plan` | View meals in the Paprika meal planner across past days (default 30 days back) and upcoming days (default 14 days ahead). Includes entry IDs (`[id: <uid>]`) for easy deletion or rescheduling. |
| `delete_planned_meal` | Remove a planned meal from the Paprika meal planner by entry ID or date (+ optional meal slot/recipe) |
| `move_planned_meal` | Move or reschedule a planned meal to another date or meal type (also how to change a meal's category) |
| `GetUsageStats` | Usage aggregates from the audit log: calls per client, per tool, per day, error rate, and last-seen per client |

### Error contract

Failures are surfaced via the MCP `isError=true` flag, with a stable category in `structuredContent.code` and a TTS-friendly message in the text content. The LLM should branch on the **code**, not parse the prose. See `specs.md` → "Scenario 9 — Errors the user should hear in plain language" for example dialogues.

| Code | When | Extra fields on `structuredContent` |
|------|------|--------------------------------------|
| `paprika_unreachable` | Network failure reaching paprikaapp.com (DNS, TCP, TLS, timeout). | – |
| `paprika_auth_failed` | Paprika rejected the saved credentials (HTTP 401/403). | – |
| `paprika_rate_limited` | Paprika is throttling us (HTTP 429/503). `list_recipes` falls back to stale cache when possible and does **not** error. | – |
| `paprika_error` | Any other unexpected non-2xx Paprika response. The raw body is logged but never returned to the user. | – |
| `invalid_argument` | Required argument missing or malformed. | `missing: [str]` |
| `grocery_not_found` | No active grocery item matches the query. | – |
| `grocery_ambiguous` | Multiple grocery items match. The LLM must ask the user to disambiguate. | `candidates: [{uid, name, list_uid, list_name}]` |
| `grocery_list_not_found` | The named grocery list doesn't exist. | `available_lists: [str]` |
| `recipe_not_found` | The given recipe UID doesn't exist (or has been deleted). | – |

User-visible messages never contain UIDs, HTTP status codes, or raw response bodies — those go to the server log only.

### Components

- **MCP Server** (`src/server.py`): Handles MCP protocol communication and tool routing
- **Paprika Client** (`src/paprika_client.py`): Manages Paprika API authentication and operations
- **Configuration** (`src/config.py`): Handles environment variables and CLI arguments

## Development

### Running Tests

```bash
# Install development dependencies
pip install pytest pytest-asyncio

# Run tests
pytest tests/ -v
```

#### Live (read-only) tests against the real Paprika cloud

`tests/test_paprika_live.py` exercises the real Paprika API using credentials
from `.env`. They are skipped by default and **strictly read-only** — they
only call `authenticate`, `list_recipes`, `get_groceries`, and
`get_grocery_lists`; they never create, update, or delete anything.

```bash
PAPRIKA_LIVE_TESTS=1 pytest tests/test_paprika_live.py -v
```

Note: Paprika applies aggressive per-IP rate limiting. Running the live suite
back-to-back may produce transient connection-reset errors; rerun individual
tests in isolation.

### Adding New Features

1. Create a feature branch: `git checkout -b feature/new-feature`
2. Add your changes with tests
3. Ensure all tests pass: `pytest`
4. Format code: `black src/ tests/`
5. Commit and push your changes

### Pre-commit secret scanning

The repo ships with a [pre-commit](https://pre-commit.com) config that runs
[gitleaks](https://github.com/gitleaks/gitleaks) on every commit. Custom
rules in `.gitleaks.toml` catch the patterns that have actually leaked from
this repo before — `Authorization: Basic <base64>` headers, URLs with
embedded `user:password@`, and hard-coded `PAPRIKA_*` / `MCPUSER_*` literal
values.

Set up once per clone:

```bash
pip install pre-commit       # or: uv tool install pre-commit
pre-commit install           # registers .git/hooks/pre-commit

# Optionally scan the existing tree and full history:
pre-commit run --all-files
gitleaks detect --source .
```

## Troubleshooting

### Common Issues

#### Authentication Failed
- Verify your Paprika credentials work at [paprikaapp.com](https://paprikaapp.com)
- Ensure cloud sync is enabled in your Paprika app
- Check that `PAPRIKA_USERNAME` and `PAPRIKA_PASSWORD` are set in `.env`

#### Client Can't Connect
- Point the client at the absolute path of `.venv/bin/paprika-mcp`; if that file is missing, run `uv sync --extra dev`
- Fully restart the client after changing its config
- Try the server on its own with the MCP Inspector (Quick Start step 3) to tell server problems from client problems

#### Import Errors (e.g. `No module named 'mcp.server.fastmcp'`)
- Reinstall from the lockfile: `uv sync --extra dev`. Don't use `uv pip install`, which ignores the lockfile and can pull an incompatible `mcp` 2.x
- Check that the venv uses Python 3.12 (`.venv/bin/python --version`)

## API Rate Limiting

The Paprika API enforces per-IP rate limiting (HTTP 429, with blocks that can last several minutes). Because Paprika has no "get all recipes" call, the server downloads recipes one by one when it starts:

- Requests are paced (one at a time, 0.5 s apart). A first download of a few hundred recipes takes a few minutes in the background; grocery and meal-plan tools work meanwhile, and `list_recipes` returns what has arrived so far with a "still downloading" note.
- On a 429 the download stops immediately, waits (Paprika's `Retry-After`, else 30 s doubling up to 5 min), and resumes with only the missing recipes.
- The cache is saved to `data/recipe_cache.json` (gitignored, mode `0600`), so a restart only downloads recipes that changed. Set `PAPRIKA_RECIPE_CACHE_FILE` to use another path, or to an empty value to turn persistence off.

If you were blocked, wait a few minutes before starting the server again; restarting repeatedly during a block extends it.

## Contributing

Contributions are welcome! Whether you want to report bugs, suggest new features, improve documentation, or submit code changes, your input helps make this project better. Feel free to open an issue for discussions or submit a pull request with your improvements.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- [Anthropic](https://www.anthropic.com/) for the Model Context Protocol
- [Paprika Recipe Manager](https://www.paprikaapp.com/) for the excellent recipe management app
- The MCP community for documentation and examples

## Changelog

### v1.3.0 (2026-10-03)
- **Home Assistant compatibility**: Added automatic JSON Schema definition inlining (`_inline_schema_defs`) across all FastMCP tools. Resolves Pydantic `$defs` / `$ref` structures into self-contained schemas, fixing the `ValueError: Invalid schema, missing type` crash during Home Assistant's `voluptuous-openapi` schema conversion on setup.
- **Meal history & planning (`get_plan`)**: Added `get_plan` tool to inspect the Paprika meal planner across past days (history of meals eaten, default 30 days back) and upcoming days (planned meals, default 14 days ahead), with voice-friendly date grouping.
- **Regression test suite**: Added `tests/test_homeassistant_compatibility.py` verifying all registered tool schemas convert cleanly with `voluptuous-openapi`, and `tests/test_get_plan.py` covering calendar date range filtering and formatting.
- **Client compatibility**: Restored `add_recipe_to_grocery_list` backwards-compatibility alias on `PaprikaClient` and updated documentation / repository clone URLs.

### v1.2.0 (2026-05-08)
- Voice-friendly error contract: typed exception hierarchy with stable `structuredContent.code` values (`paprika_unreachable`, `paprika_auth_failed`, `paprika_rate_limited`, `grocery_not_found`, `grocery_ambiguous`, `grocery_list_not_found`, `recipe_not_found`, `invalid_argument`, `paprika_error`) and TTS-friendly user-visible messages. See `specs.md` Scenario 9.
- Lazy authentication: a startup auth blip no longer kills the server; it surfaces as a friendly error on the first tool call.
- Removed legacy SSE transport. All clients (including Home Assistant) now connect to the single Streamable HTTP `/mcp` endpoint.

### v1.1.0 (2026-05-06)
- Added Streamable HTTP transport at `/mcp` (current MCP standard) for Claude Code, Gemini CLI, VS Code Copilot, Antigravity, and web clients
- Updated agent configuration examples for all supported clients

### v1.0.0 (2025-09-27)
- Initial release
- Recipe creation, updating, and listing functionality
- Full and partial update capabilities

---

**Note**: This is an unofficial integration and is not affiliated with or endorsed by Paprika Recipe Manager or Anthropic.
