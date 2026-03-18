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
cp .env.example .env

# 3. Fetch issues from a GitHub repo
uv run python fetch_issues.py --org myorg --repo myrepo

# 4. Run the app
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

## Creating a GitHub personal access token (for fetching issues)

The `fetch_issues.py` CLI script needs a token to read issues from the GitHub API.

1. Go to **[GitHub Settings > Tokens](https://github.com/settings/tokens)**
2. Click **Generate new token (classic)**
3. Select the `repo` scope (or just `public_repo` for public repos)
4. Copy the token and put it in your `.env` as `GITHUB_TOKEN`

## Environment variables

Copy `.env.example` to `.env` and fill in the values:

| Variable | Purpose | How to get it |
|---|---|---|
| `GITHUB_CLIENT_ID` | OAuth App client ID | GitHub OAuth App settings (see above) |
| `GITHUB_CLIENT_SECRET` | OAuth App client secret | GitHub OAuth App settings (see above) |
| `GITHUB_TOKEN` | Personal access token for fetching issues | GitHub token settings (see above) |
| `SESSION_SECRET` | Secret for signing session cookies | Generate with: `python -c "import secrets; print(secrets.token_hex(32))"` |
| `DATABASE_URL` | SQLite connection string | Default: `sqlite+aiosqlite:///./issuematch.db` |
| `BASE_URL` | App base URL (must match GitHub OAuth App) | Default: `http://localhost:8000` |

## Usage

### Fetching issues

```bash
# Fetch all open issues
uv run python fetch_issues.py --org myorg --repo myrepo

# Fetch only issues with specific labels
uv run python fetch_issues.py --org myorg --repo myrepo --labels "bug,help wanted"

# Fetch closed issues
uv run python fetch_issues.py --org myorg --repo myrepo --state closed

# Fetch all issues regardless of state
uv run python fetch_issues.py --org myorg --repo myrepo --state all
```

Re-running the command updates existing issues and adds new ones.

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
| `GET` | `/users/{user_id}/votes/{issue_id}/json` | Get a single vote |
| `PUT` | `/users/{user_id}/votes/{issue_id}` | Update a vote's ranking |
| `POST` | `/users/{user_id}/votes/{issue_id}` | Create an empty vote (ranking = null) |
| `GET` | `/votes/{issue_id}/json` | Get all votes for an issue |
| `GET` | `/results/json` | Get aggregated results for all issues |

Interactive API docs are available at http://localhost:8000/docs (Swagger UI).
