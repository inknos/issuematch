from __future__ import annotations

from unittest.mock import patch

from httpx import AsyncClient

# ---------------------------------------------------------------------------
# Index (/)
# ---------------------------------------------------------------------------


async def test_index_shows_login_when_anonymous(client: AsyncClient) -> None:
    resp = await client.get("/", follow_redirects=False)
    assert resp.status_code == 200
    assert "login" in resp.text.lower()


# ---------------------------------------------------------------------------
# /vote (GET) — redirect flow
# ---------------------------------------------------------------------------


async def test_vote_redirect_to_login_when_anonymous(client: AsyncClient) -> None:
    resp = await client.get("/vote", follow_redirects=False)
    assert resp.status_code == 303
    assert "/login" in resp.headers["location"]


async def test_vote_redirects_to_issue(client: AsyncClient, seed_data: dict) -> None:
    with patch("app.routes.current_user_id", return_value=seed_data["user_id"]):
        resp = await client.get("/vote", follow_redirects=False)
    assert resp.status_code == 303
    assert "/vote/" in resp.headers["location"]


async def test_vote_shows_done_when_no_issues(client: AsyncClient, seed_data: dict) -> None:
    uid = seed_data["user_id"]

    # Vote on all issues so none remain
    await client.post(
        f"/api/users/{uid}/votes",
        json={"issue_id": seed_data["issue_id"], "ranking": 1},
    )
    await client.post(
        f"/api/users/{uid}/votes",
        json={"issue_id": seed_data["issue_id_2"], "ranking": 2},
    )

    with patch("app.routes.current_user_id", return_value=uid):
        resp = await client.get("/vote", follow_redirects=False)
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# /vote/{org}/{repo}/{number} (GET) — vote page
# ---------------------------------------------------------------------------


async def test_vote_page_renders_issue(client: AsyncClient, seed_data: dict) -> None:
    with patch("app.routes.current_user_id", return_value=seed_data["user_id"]):
        resp = await client.get("/vote/acme/widgets/1")
    assert resp.status_code == 200
    assert "Fix the widget" in resp.text


async def test_vote_page_redirects_anonymous(client: AsyncClient) -> None:
    resp = await client.get("/vote/acme/widgets/1", follow_redirects=False)
    assert resp.status_code == 303
    assert "/login" in resp.headers["location"]


async def test_vote_page_404_for_missing_issue(client: AsyncClient, seed_data: dict) -> None:
    with patch("app.routes.current_user_id", return_value=seed_data["user_id"]):
        resp = await client.get("/vote/nope/missing/999")
    assert resp.status_code == 404


async def test_vote_page_shows_existing_ranking(client: AsyncClient, seed_data: dict) -> None:
    uid = seed_data["user_id"]
    await client.post(
        f"/api/users/{uid}/votes",
        json={"issue_id": seed_data["issue_id"], "ranking": 3},
    )

    with patch("app.routes.current_user_id", return_value=uid):
        resp = await client.get("/vote/acme/widgets/1")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# POST /vote — submit a vote
# ---------------------------------------------------------------------------


async def test_submit_vote_redirects_anonymous(client: AsyncClient) -> None:
    resp = await client.post(
        "/vote",
        data={"issue_id": "acme/widgets#1", "ranking": "2"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "/login" in resp.headers["location"]


async def test_submit_vote_creates_and_redirects(client: AsyncClient, seed_data: dict) -> None:
    uid = seed_data["user_id"]
    with patch("app.routes.current_user_id", return_value=uid):
        resp = await client.post(
            "/vote",
            data={"issue_id": seed_data["issue_id"], "ranking": "2"},
            follow_redirects=False,
        )
    assert resp.status_code == 303
    location = resp.headers["location"]
    assert "/vote/" in location or "/vote/done" in location


async def test_submit_vote_updates_existing(client: AsyncClient, seed_data: dict) -> None:
    uid = seed_data["user_id"]
    await client.post(
        f"/api/users/{uid}/votes",
        json={"issue_id": seed_data["issue_id"], "ranking": 1},
    )

    with patch("app.routes.current_user_id", return_value=uid):
        resp = await client.post(
            "/vote",
            data={"issue_id": seed_data["issue_id"], "ranking": "3"},
            follow_redirects=False,
        )
    assert resp.status_code == 303


async def test_submit_vote_done_when_all_voted(client: AsyncClient, seed_data: dict) -> None:
    uid = seed_data["user_id"]
    await client.post(
        f"/api/users/{uid}/votes",
        json={"issue_id": seed_data["issue_id"], "ranking": 1},
    )

    with patch("app.routes.current_user_id", return_value=uid):
        resp = await client.post(
            "/vote",
            data={"issue_id": seed_data["issue_id_2"], "ranking": "-1"},
            follow_redirects=False,
        )
    assert resp.status_code == 303
    assert "/vote/done" in resp.headers["location"]


# ---------------------------------------------------------------------------
# /vote/done (GET)
# ---------------------------------------------------------------------------


async def test_vote_done_renders(client: AsyncClient, seed_data: dict) -> None:
    with patch("app.routes.current_user_id", return_value=seed_data["user_id"]):
        resp = await client.get("/vote/done")
    assert resp.status_code == 200


async def test_vote_done_redirects_anonymous(client: AsyncClient) -> None:
    resp = await client.get("/vote/done", follow_redirects=False)
    assert resp.status_code == 303
    assert "/login" in resp.headers["location"]


# ---------------------------------------------------------------------------
# /votes (GET) — results page
# ---------------------------------------------------------------------------


async def test_results_page_redirects_anonymous(client: AsyncClient) -> None:
    resp = await client.get("/votes", follow_redirects=False)
    assert resp.status_code == 303
    assert "/login" in resp.headers["location"]


async def test_results_page_renders(client: AsyncClient, seed_data: dict) -> None:
    with patch("app.routes.current_user_id", return_value=seed_data["user_id"]):
        resp = await client.get("/votes")
    assert resp.status_code == 200


async def test_results_page_sort_asc(client: AsyncClient, seed_data: dict) -> None:
    with patch("app.routes.current_user_id", return_value=seed_data["user_id"]):
        resp = await client.get("/votes", params={"sort_by": "title", "order": "asc"})
    assert resp.status_code == 200


async def test_results_page_sort_vote_count(client: AsyncClient, seed_data: dict) -> None:
    with patch("app.routes.current_user_id", return_value=seed_data["user_id"]):
        resp = await client.get("/votes", params={"sort_by": "vote_count", "order": "desc"})
    assert resp.status_code == 200


async def test_results_page_unknown_sort_falls_back(client: AsyncClient, seed_data: dict) -> None:
    with patch("app.routes.current_user_id", return_value=seed_data["user_id"]):
        resp = await client.get("/votes", params={"sort_by": "nonexistent"})
    assert resp.status_code == 200
