from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

if TYPE_CHECKING:
    from httpx import AsyncClient
    from tests.conftest import _AuthOverrider

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


async def test_vote_shows_done_when_db_empty(client: AsyncClient) -> None:
    """Done page is shown only when there are zero issues in the database."""
    with patch("app.routes.current_user_id", return_value=1):
        resp = await client.get("/vote", follow_redirects=False)
    assert resp.status_code == 200


async def test_vote_redirects_to_least_voted_issue(
    client: AsyncClient,
    seed_data: dict,
    auth: _AuthOverrider,
) -> None:
    """After all issues have votes, /vote still redirects to the least-voted one."""
    uid = seed_data["user_id"]

    with auth(uid, "contributor"):
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
    assert resp.status_code == 303
    assert "/vote/" in resp.headers["location"]


# ---------------------------------------------------------------------------
# /vote/{org}/{repo}/{type}/{number} (GET) — vote page
# ---------------------------------------------------------------------------


async def test_vote_page_renders_issue(client: AsyncClient, seed_data: dict) -> None:
    with patch("app.routes.current_user_id", return_value=seed_data["user_id"]):
        resp = await client.get("/vote/acme/widgets/issue/1")
    assert resp.status_code == 200
    assert "Fix the widget" in resp.text


async def test_vote_page_redirects_anonymous(client: AsyncClient) -> None:
    resp = await client.get("/vote/acme/widgets/issue/1", follow_redirects=False)
    assert resp.status_code == 303
    assert "/login" in resp.headers["location"]


async def test_vote_page_404_for_missing_issue(client: AsyncClient, seed_data: dict) -> None:
    with patch("app.routes.current_user_id", return_value=seed_data["user_id"]):
        resp = await client.get("/vote/nope/missing/issue/999")
    assert resp.status_code == 404


async def test_vote_page_shows_existing_ranking(
    client: AsyncClient,
    seed_data: dict,
    auth: _AuthOverrider,
) -> None:
    uid = seed_data["user_id"]
    with auth(uid, "contributor"):
        await client.post(
            f"/api/users/{uid}/votes",
            json={"issue_id": seed_data["issue_id"], "ranking": 3},
        )

    with patch("app.routes.current_user_id", return_value=uid):
        resp = await client.get("/vote/acme/widgets/issue/1")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# POST /vote — submit a vote
# ---------------------------------------------------------------------------


async def test_submit_vote_redirects_anonymous(client: AsyncClient) -> None:
    resp = await client.post(
        "/vote",
        data={"issue_id": "acme/widgets/issue/1", "ranking": "2"},
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


async def test_submit_vote_updates_existing(
    client: AsyncClient,
    seed_data: dict,
    auth: _AuthOverrider,
) -> None:
    uid = seed_data["user_id"]
    with auth(uid, "contributor"):
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


async def test_submit_vote_redirects_to_least_voted(
    client: AsyncClient,
    seed_data: dict,
    auth: _AuthOverrider,
) -> None:
    """After voting on every issue, submit still redirects to a (least-voted) issue."""
    uid = seed_data["user_id"]
    with auth(uid, "contributor"):
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
    assert "/vote/" in resp.headers["location"]


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


async def test_results_page_sort_median(client: AsyncClient, seed_data: dict) -> None:
    with patch("app.routes.current_user_id", return_value=seed_data["user_id"]):
        resp = await client.get("/votes", params={"sort_by": "median_ranking", "order": "desc"})
    assert resp.status_code == 200


async def test_results_page_unknown_sort_falls_back(client: AsyncClient, seed_data: dict) -> None:
    with patch("app.routes.current_user_id", return_value=seed_data["user_id"]):
        resp = await client.get("/votes", params={"sort_by": "nonexistent"})
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# /activity (GET) — activity log page
# ---------------------------------------------------------------------------


async def test_activity_page_redirects_anonymous(client: AsyncClient) -> None:
    resp = await client.get("/activity", follow_redirects=False)
    assert resp.status_code == 303
    assert "/login" in resp.headers["location"]


async def test_activity_page_renders_empty(client: AsyncClient, seed_data: dict) -> None:
    with patch("app.routes.current_user_id", return_value=seed_data["user_id"]):
        resp = await client.get("/activity")
    assert resp.status_code == 200
    assert "No activity yet" in resp.text


async def test_activity_page_shows_entries(
    client: AsyncClient,
    seed_data: dict,
    auth: _AuthOverrider,
) -> None:
    uid = seed_data["user_id"]
    with auth(uid, "contributor"):
        await client.post(
            f"/api/users/{uid}/votes",
            json={"issue_id": seed_data["issue_id"], "ranking": 2},
        )

    with patch("app.routes.current_user_id", return_value=uid):
        resp = await client.get("/activity")
    assert resp.status_code == 200
    assert "Voted" in resp.text
    assert seed_data["issue_id"] in resp.text


async def test_activity_page_shows_vote_update(
    client: AsyncClient,
    seed_data: dict,
    auth: _AuthOverrider,
) -> None:
    uid = seed_data["user_id"]
    with auth(uid, "contributor"):
        await client.post(
            f"/api/users/{uid}/votes",
            json={"issue_id": seed_data["issue_id"], "ranking": 1},
        )
        await client.put(
            f"/api/users/{uid}/votes",
            json={"issue_id": seed_data["issue_id"], "ranking": -2},
        )

    with patch("app.routes.current_user_id", return_value=uid):
        resp = await client.get("/activity")
    assert resp.status_code == 200
    assert "Vote Updated" in resp.text


# ---------------------------------------------------------------------------
# /votes (GET) — delete button presence
# ---------------------------------------------------------------------------


async def test_results_page_shows_delete_button_for_voted_issue(
    client: AsyncClient,
    seed_data: dict,
    auth: _AuthOverrider,
) -> None:
    uid = seed_data["user_id"]
    with auth(uid, "contributor"):
        create_resp = await client.post(
            f"/api/users/{uid}/votes",
            json={"issue_id": seed_data["issue_id"], "ranking": 2},
        )
    vote_id = create_resp.json()["id"]

    with patch("app.routes.current_user_id", return_value=uid):
        resp = await client.get("/votes")
    assert resp.status_code == 200
    assert "btn-delete-vote" in resp.text
    assert f'data-vote-id="{vote_id}"' in resp.text


async def test_results_page_no_delete_button_when_not_voted(
    client: AsyncClient,
    seed_data: dict,
) -> None:
    uid = seed_data["user_id"]

    with patch("app.routes.current_user_id", return_value=uid):
        resp = await client.get("/votes")
    assert resp.status_code == 200
    assert 'data-vote-id="' not in resp.text
