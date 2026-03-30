# IssueMatch

Gamify your issue backlog review. Each team member votes on issues (-3 to +3) one at a time, and the results are aggregated into a leaderboard.

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

## Quick start

```bash
# 1. Install dependencies
uv sync            # or: pip install -e .

# 2. Set up environment variables (see below)
#    Create a .env file with the required variables

# 3. Run the app
uv run uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000 and sign in with GitHub.

## Setting up GitHub OAuth (required for sign-in)

1. Go to **[GitHub Developer Settings > OAuth Apps](https://github.com/settings/developers)**
   (for an org: Settings > Developer settings > OAuth Apps)
2. Click **New OAuth App** and fill in:
   - **Application name**: `IssueMatch` (or anything you like)
   - **Homepage URL**: `http://localhost:8000`
   - **Authorization callback URL**: `http://localhost:8000/auth/callback`
3. Click **Register application**
4. On the app page, copy the **Client ID**
5. Click **Generate a new client secret** and copy it

Put both values in your `.env` file as `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET`.

## Environment variables

Create a `.env` file in the project root with the following variables:

| Variable | Purpose | How to get it |
|---|---|---|
| `GITHUB_CLIENT_ID` | OAuth App client ID | GitHub OAuth App settings (see above) |
| `GITHUB_CLIENT_SECRET` | OAuth App client secret | GitHub OAuth App settings (see above) |
| `SESSION_SECRET` | Secret for signing session cookies | Generate with: `python -c "import secrets; print(secrets.token_hex(32))"` |
| `BASE_URL` | App base URL (must match GitHub OAuth App) | Default: `http://localhost:8000` |
| `DB_HOST` | PostgreSQL host | Default: `localhost` |
| `DB_PORT` | PostgreSQL port | Default: `5432` |
| `DB_USER` | PostgreSQL user | Default: `issuematch` |
| `DB_PASSWORD` | PostgreSQL password | Required |
| `DB_NAME` | PostgreSQL database name | Default: `issuematch` |

## Usage

### Fetching issues

Issue fetching is done from the **Admin panel** in the web UI. Admin users can:

1. Navigate to the **Admin** page
2. Set a **GitHub personal access token** (stored encrypted, never retrievable)
3. Use the **Fetch** form to pull issues or pull requests from any GitHub repository by specifying the org, repo, type, and optional label filters

### Voting

1. Open http://localhost:8000
2. Sign in with your GitHub account
3. A random issue is shown as a card — vote -3 to +3, or skip
4. Each vote loads the next unvoted issue automatically (no page reload)
5. Once you've voted on everything, you'll see an "All done" message

### Results

Visit http://localhost:8000/results to see all issues ranked by average score.

## JSON API

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/admin` | Get admin status (token set, etc.) |
| `PUT` | `/api/admin` | Set GitHub API token |
| `POST` | `/api/admin/fetch` | Fetch issues/PRs from GitHub |
| `GET` | `/api/admin/users` | List all users (admin only) |
| `PATCH` | `/api/admin/users/{user_id}/role` | Change a user's role |
| `GET` | `/api/votes` | List votes (filterable) |
| `GET` | `/api/activity` | List activity log |

Interactive API docs are available at http://localhost:8000/docs (Swagger UI).
