"""Tests for vote CRUD, activity APIs, results endpoint, and issue persistence."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from app.models import Issue, User, Vote
from sqlalchemy import delete, select

if TYPE_CHECKING:
    import httpx
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

    from tests.conftest import _AuthOverrider

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_vote(
    client: AsyncClient,
    auth: _AuthOverrider,
    uid: int,
    issue_id: str,
    ranking: int,
) -> httpx.Response:
    with auth(uid, "contributor"):
        resp = await client.post(
            f"/api/users/{uid}/votes",
            json={"issue_id": issue_id, "ranking": ranking},
        )
    assert resp.status_code == 201
    return resp


# ---------------------------------------------------------------------------
# GET /api/votes/json (contributor+)
# ---------------------------------------------------------------------------


async def test_list_votes_empty(client: AsyncClient, seed_data: dict, auth: _AuthOverrider) -> None:
    with auth(seed_data["user_id"], "contributor"):
        resp = await client.get("/api/votes/json")
    assert resp.status_code == 200
    data = resp.json()
    assert data == {"items": [], "total": 0, "page": 1, "per_page": 20}


async def test_list_votes_returns_all(
    client: AsyncClient,
    seed_data: dict,
    auth: _AuthOverrider,
) -> None:
    uid = seed_data["user_id"]
    await _create_vote(client, auth, uid, seed_data["issue_id"], 2)
    await _create_vote(client, auth, uid, seed_data["issue_id_2"], -1)

    with auth(uid, "contributor"):
        resp = await client.get("/api/votes/json")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert len(data["items"]) == 2


async def test_list_votes_anonymous_unauthorized(client: AsyncClient) -> None:
    resp = await client.get("/api/votes/json")
    assert resp.status_code == 401


async def test_list_votes_filter_by_issue_id(
    client: AsyncClient,
    seed_data: dict,
    auth: _AuthOverrider,
) -> None:
    uid = seed_data["user_id"]
    await _create_vote(client, auth, uid, seed_data["issue_id"], 3)
    await _create_vote(client, auth, uid, seed_data["issue_id_2"], -1)

    with auth(uid, "contributor"):
        resp = await client.get("/api/votes/json", params={"issue_id": seed_data["issue_id"]})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["issue_id"] == seed_data["issue_id"]


async def test_list_votes_filter_by_org(
    client: AsyncClient,
    seed_data: dict,
    auth: _AuthOverrider,
) -> None:
    uid = seed_data["user_id"]
    await _create_vote(client, auth, uid, seed_data["issue_id"], 1)

    with auth(uid, "contributor"):
        resp = await client.get("/api/votes/json", params={"org": "acme"})
    assert resp.status_code == 200
    assert resp.json()["total"] == 1

    with auth(uid, "contributor"):
        resp = await client.get("/api/votes/json", params={"org": "nonexistent"})
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


async def test_list_votes_filter_by_repo(
    client: AsyncClient,
    seed_data: dict,
    auth: _AuthOverrider,
) -> None:
    uid = seed_data["user_id"]
    await _create_vote(client, auth, uid, seed_data["issue_id"], 1)
    await _create_vote(client, auth, uid, seed_data["issue_id_2"], -2)

    with auth(uid, "contributor"):
        resp = await client.get("/api/votes/json", params={"repo": "widgets"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["issue_id"] == seed_data["issue_id"]


async def test_list_votes_filter_by_user_id(
    client: AsyncClient,
    seed_data: dict,
    auth: _AuthOverrider,
) -> None:
    uid = seed_data["user_id"]
    await _create_vote(client, auth, uid, seed_data["issue_id"], 1)

    with auth(uid, "contributor"):
        resp = await client.get("/api/votes/json", params={"user_id": uid})
    assert resp.status_code == 200
    assert resp.json()["total"] == 1

    with auth(uid, "contributor"):
        resp = await client.get("/api/votes/json", params={"user_id": 99999})
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


async def test_list_votes_pagination(
    client: AsyncClient,
    seed_data: dict,
    auth: _AuthOverrider,
) -> None:
    uid = seed_data["user_id"]
    await _create_vote(client, auth, uid, seed_data["issue_id"], 2)
    await _create_vote(client, auth, uid, seed_data["issue_id_2"], -1)

    with auth(uid, "contributor"):
        resp = await client.get("/api/votes/json", params={"per_page": 1, "page": 1})
    data = resp.json()
    assert data["total"] == 2
    assert len(data["items"]) == 1
    assert data["page"] == 1
    assert data["per_page"] == 1

    with auth(uid, "contributor"):
        resp = await client.get("/api/votes/json", params={"per_page": 1, "page": 2})
    data = resp.json()
    assert data["total"] == 2
    assert len(data["items"]) == 1
    assert data["page"] == 2

    with auth(uid, "contributor"):
        resp = await client.get("/api/votes/json", params={"per_page": 1, "page": 3})
    data = resp.json()
    assert data["total"] == 2
    assert len(data["items"]) == 0


async def test_list_votes_pagination_with_filter(
    client: AsyncClient,
    seed_data: dict,
    auth: _AuthOverrider,
) -> None:
    uid = seed_data["user_id"]
    await _create_vote(client, auth, uid, seed_data["issue_id"], 3)
    await _create_vote(client, auth, uid, seed_data["issue_id_2"], -1)

    with auth(uid, "contributor"):
        resp = await client.get(
            "/api/votes/json",
            params={"org": "acme", "per_page": 1, "page": 1},
        )
    data = resp.json()
    assert data["total"] == 2
    assert len(data["items"]) == 1


# --- User votes (GET, contributor+ own / maintainer+ any) ---


async def test_get_user_votes_empty(
    client: AsyncClient,
    seed_data: dict,
    auth: _AuthOverrider,
) -> None:
    uid = seed_data["user_id"]
    with auth(uid, "contributor"):
        resp = await client.get(f"/api/users/{uid}/votes/json")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_get_user_votes_all(
    client: AsyncClient,
    seed_data: dict,
    auth: _AuthOverrider,
) -> None:
    uid = seed_data["user_id"]
    await _create_vote(client, auth, uid, seed_data["issue_id"], 3)
    await _create_vote(client, auth, uid, seed_data["issue_id_2"], -1)

    with auth(uid, "contributor"):
        resp = await client.get(f"/api/users/{uid}/votes/json")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


async def test_get_user_votes_filter_by_issue_id(
    client: AsyncClient,
    seed_data: dict,
    auth: _AuthOverrider,
) -> None:
    uid = seed_data["user_id"]
    await _create_vote(client, auth, uid, seed_data["issue_id"], 2)
    await _create_vote(client, auth, uid, seed_data["issue_id_2"], -3)

    with auth(uid, "contributor"):
        resp = await client.get(
            f"/api/users/{uid}/votes/json",
            params={"issue_id": seed_data["issue_id_2"]},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["issue_id"] == seed_data["issue_id_2"]
    assert data[0]["ranking"] == -3


async def test_get_user_votes_other_user_forbidden_for_contributor(
    client: AsyncClient,
    seed_data: dict,
    admin_user: dict,
    auth: _AuthOverrider,
) -> None:
    with auth(seed_data["user_id"], "contributor"):
        resp = await client.get(f"/api/users/{admin_user['user_id']}/votes/json")
    assert resp.status_code == 403


async def test_get_user_votes_other_user_allowed_for_maintainer(
    client: AsyncClient,
    seed_data: dict,
    maintainer_user: dict,
    auth: _AuthOverrider,
) -> None:
    with auth(maintainer_user["user_id"], "maintainer"):
        resp = await client.get(f"/api/users/{seed_data['user_id']}/votes/json")
    assert resp.status_code == 200


async def test_get_user_votes_anonymous_unauthorized(client: AsyncClient) -> None:
    resp = await client.get("/api/users/1/votes/json")
    assert resp.status_code == 401


# --- User votes (POST, contributor+ own only) ---


async def test_create_vote(
    client: AsyncClient,
    seed_data: dict,
    auth: _AuthOverrider,
) -> None:
    uid = seed_data["user_id"]
    with auth(uid, "contributor"):
        resp = await client.post(
            f"/api/users/{uid}/votes",
            json={"issue_id": seed_data["issue_id"], "ranking": 3},
        )
    assert resp.status_code == 201
    data = resp.json()
    assert data["user_id"] == uid
    assert data["issue_id"] == seed_data["issue_id"]
    assert data["ranking"] == 3
    assert "id" in data
    assert "created_at" in data


async def test_create_vote_null_ranking(
    client: AsyncClient,
    seed_data: dict,
    auth: _AuthOverrider,
) -> None:
    uid = seed_data["user_id"]
    with auth(uid, "contributor"):
        resp = await client.post(
            f"/api/users/{uid}/votes",
            json={"issue_id": seed_data["issue_id"]},
        )
    assert resp.status_code == 201
    assert resp.json()["ranking"] is None


async def test_create_vote_duplicate_409(
    client: AsyncClient,
    seed_data: dict,
    auth: _AuthOverrider,
) -> None:
    uid = seed_data["user_id"]
    await _create_vote(client, auth, uid, seed_data["issue_id"], 1)
    with auth(uid, "contributor"):
        resp = await client.post(
            f"/api/users/{uid}/votes",
            json={"issue_id": seed_data["issue_id"]},
        )
    assert resp.status_code == 409


async def test_create_vote_as_other_user_forbidden(
    client: AsyncClient,
    seed_data: dict,
    admin_user: dict,
    auth: _AuthOverrider,
) -> None:
    with auth(seed_data["user_id"], "contributor"):
        resp = await client.post(
            f"/api/users/{admin_user['user_id']}/votes",
            json={"issue_id": seed_data["issue_id"], "ranking": 1},
        )
    assert resp.status_code == 403


async def test_create_vote_anonymous_unauthorized(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/users/1/votes",
        json={"issue_id": "x/y/issue/1", "ranking": 1},
    )
    assert resp.status_code == 401


# --- User votes (PUT, contributor+ own only) ---


async def test_update_vote(
    client: AsyncClient,
    seed_data: dict,
    auth: _AuthOverrider,
) -> None:
    uid = seed_data["user_id"]
    await _create_vote(client, auth, uid, seed_data["issue_id"], 1)

    with auth(uid, "contributor"):
        resp = await client.put(
            f"/api/users/{uid}/votes",
            json={"issue_id": seed_data["issue_id"], "ranking": -2},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ranking"] == -2
    assert data["issue_id"] == seed_data["issue_id"]


async def test_update_vote_not_found(
    client: AsyncClient,
    seed_data: dict,
    auth: _AuthOverrider,
) -> None:
    uid = seed_data["user_id"]
    with auth(uid, "contributor"):
        resp = await client.put(
            f"/api/users/{uid}/votes",
            json={"issue_id": seed_data["issue_id"], "ranking": 1},
        )
    assert resp.status_code == 404


# --- User votes (DELETE, contributor+ own only) ---


async def test_delete_vote(
    client: AsyncClient,
    seed_data: dict,
    auth: _AuthOverrider,
) -> None:
    uid = seed_data["user_id"]
    create_resp = await _create_vote(client, auth, uid, seed_data["issue_id"], 2)
    vote_id = create_resp.json()["id"]

    with auth(uid, "contributor"):
        resp = await client.delete(f"/api/users/{uid}/votes/{vote_id}")
    assert resp.status_code == 204

    with auth(uid, "contributor"):
        get_resp = await client.get(f"/api/users/{uid}/votes/json")
    assert get_resp.json() == []


async def test_delete_vote_not_found(
    client: AsyncClient,
    seed_data: dict,
    auth: _AuthOverrider,
) -> None:
    uid = seed_data["user_id"]
    with auth(uid, "contributor"):
        resp = await client.delete(f"/api/users/{uid}/votes/99999")
    assert resp.status_code == 404


async def test_delete_vote_wrong_user(
    client: AsyncClient,
    seed_data: dict,
    auth: _AuthOverrider,
) -> None:
    uid = seed_data["user_id"]
    create_resp = await _create_vote(client, auth, uid, seed_data["issue_id"], 1)
    vote_id = create_resp.json()["id"]

    with auth(uid, "contributor"):
        resp = await client.delete(f"/api/users/99999/votes/{vote_id}")
    assert resp.status_code == 403


async def test_delete_vote_creates_audit_entry(
    client: AsyncClient,
    seed_data: dict,
    admin_user: dict,
    auth: _AuthOverrider,
) -> None:
    uid = seed_data["user_id"]
    create_resp = await _create_vote(client, auth, uid, seed_data["issue_id"], 3)
    vote_id = create_resp.json()["id"]

    with auth(uid, "contributor"):
        await client.delete(f"/api/users/{uid}/votes/{vote_id}")

    with auth(admin_user["user_id"], "admin"):
        activity_resp = await client.get("/api/activity/json", params={"user_id": uid})
    entries = activity_resp.json()["items"]
    delete_entries = [e for e in entries if e["action"]["type"] == "vote_delete"]
    assert len(delete_entries) == 1
    assert delete_entries[0]["action"]["issue_id"] == seed_data["issue_id"]
    assert delete_entries[0]["action"]["ranking"] == 3


# ---------------------------------------------------------------------------
# GET /api/me (contributor+)
# ---------------------------------------------------------------------------


async def test_get_me(
    client: AsyncClient,
    seed_data: dict,
    auth: _AuthOverrider,
) -> None:
    uid = seed_data["user_id"]
    with auth(uid, "contributor"):
        resp = await client.get("/api/me")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == uid
    assert data["username"] == "testuser"
    assert data["role"] == "contributor"


async def test_get_me_as_admin(
    client: AsyncClient,
    admin_user: dict,
    auth: _AuthOverrider,
) -> None:
    uid = admin_user["user_id"]
    with auth(uid, "admin"):
        resp = await client.get("/api/me")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == uid
    assert data["username"] == "adminuser"
    assert data["role"] == "admin"


async def test_get_me_anonymous_unauthorized(client: AsyncClient) -> None:
    resp = await client.get("/api/me")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Upsert vote via /api/me/votes (contributor+)
# ---------------------------------------------------------------------------


async def test_upsert_vote_creates_new(
    client: AsyncClient,
    seed_data: dict,
    auth: _AuthOverrider,
) -> None:
    uid = seed_data["user_id"]
    with auth(uid, "contributor"):
        resp = await client.put(
            "/api/me/votes",
            json={"issue_id": seed_data["issue_id"], "ranking": 3},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["user_id"] == uid
    assert data["issue_id"] == seed_data["issue_id"]
    assert data["ranking"] == 3


async def test_upsert_vote_updates_existing(
    client: AsyncClient,
    seed_data: dict,
    auth: _AuthOverrider,
) -> None:
    uid = seed_data["user_id"]
    with auth(uid, "contributor"):
        await client.put(
            "/api/me/votes",
            json={"issue_id": seed_data["issue_id"], "ranking": 1},
        )
    with auth(uid, "contributor"):
        resp = await client.put(
            "/api/me/votes",
            json={"issue_id": seed_data["issue_id"], "ranking": -2},
        )
    assert resp.status_code == 200
    assert resp.json()["ranking"] == -2


async def test_upsert_vote_creates_audit_log(
    client: AsyncClient,
    seed_data: dict,
    admin_user: dict,
    auth: _AuthOverrider,
) -> None:
    uid = seed_data["user_id"]
    with auth(uid, "contributor"):
        await client.put(
            "/api/me/votes",
            json={"issue_id": seed_data["issue_id"], "ranking": 2},
        )
    with auth(uid, "contributor"):
        await client.put(
            "/api/me/votes",
            json={"issue_id": seed_data["issue_id"], "ranking": -1},
        )

    with auth(admin_user["user_id"], "admin"):
        activity_resp = await client.get("/api/activity/json", params={"user_id": uid})
    entries = activity_resp.json()["items"]
    types = [e["action"]["type"] for e in entries]
    assert "vote_create" in types
    assert "vote_update" in types


async def test_upsert_vote_anonymous_unauthorized(client: AsyncClient) -> None:
    resp = await client.put(
        "/api/me/votes",
        json={"issue_id": "x/y/issue/1", "ranking": 1},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /api/me/votes/pick/json (contributor+)
# ---------------------------------------------------------------------------


async def test_pick_returns_issue_when_none_voted(
    client: AsyncClient,
    seed_data: dict,
    auth: _AuthOverrider,
) -> None:
    uid = seed_data["user_id"]
    with auth(uid, "contributor"):
        resp = await client.get("/api/me/votes/pick/json")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] in (seed_data["issue_id"], seed_data["issue_id_2"])


async def test_pick_excludes_already_voted_issue(
    client: AsyncClient,
    seed_data: dict,
    auth: _AuthOverrider,
) -> None:
    uid = seed_data["user_id"]
    with auth(uid, "contributor"):
        await client.put(
            "/api/me/votes",
            json={"issue_id": seed_data["issue_id"], "ranking": 2},
        )
    with auth(uid, "contributor"):
        resp = await client.get("/api/me/votes/pick/json")
    assert resp.status_code == 200
    assert resp.json()["id"] == seed_data["issue_id_2"]


async def test_pick_returns_204_when_all_voted(
    client: AsyncClient,
    seed_data: dict,
    auth: _AuthOverrider,
) -> None:
    uid = seed_data["user_id"]
    with auth(uid, "contributor"):
        await client.put(
            "/api/me/votes",
            json={"issue_id": seed_data["issue_id"], "ranking": 1},
        )
        await client.put(
            "/api/me/votes",
            json={"issue_id": seed_data["issue_id_2"], "ranking": -1},
        )
    with auth(uid, "contributor"):
        resp = await client.get("/api/me/votes/pick/json")
    assert resp.status_code == 204


async def test_pick_prefers_least_voted_issue(
    client: AsyncClient,
    seed_data: dict,
    auth: _AuthOverrider,
    session: AsyncSession,
) -> None:
    """Pick prefers the issue with fewer global votes.

    When another user has voted on issue_1 but not issue_2, the pick for a
    fresh user should prefer issue_2 (0 global votes) over issue_1 (1 vote).
    """
    other = User(username="other", role="contributor")
    session.add(other)
    await session.flush()
    session.add(Vote(user_id=other.id, issue_id=seed_data["issue_id"], ranking=1))
    await session.commit()

    uid = seed_data["user_id"]
    with auth(uid, "contributor"):
        resp = await client.get("/api/me/votes/pick/json")
    assert resp.status_code == 200
    assert resp.json()["id"] == seed_data["issue_id_2"]


async def test_pick_anonymous_unauthorized(client: AsyncClient) -> None:
    resp = await client.get("/api/me/votes/pick/json")
    assert resp.status_code == 401


async def test_pick_returns_204_when_no_issues_exist(
    client: AsyncClient,
    session: AsyncSession,
    auth: _AuthOverrider,
) -> None:
    user = User(username="lonely", role="contributor")
    session.add(user)
    await session.commit()

    with auth(user.id, "contributor"):
        resp = await client.get("/api/me/votes/pick/json")
    assert resp.status_code == 204


# ---------------------------------------------------------------------------
# GET /api/activity/json (maintainer+)
# ---------------------------------------------------------------------------


async def test_list_activity_empty(
    client: AsyncClient,
    admin_user: dict,
    auth: _AuthOverrider,
) -> None:
    with auth(admin_user["user_id"], "admin"):
        resp = await client.get("/api/activity/json")
    assert resp.status_code == 200
    data = resp.json()
    assert data == {"items": [], "total": 0, "page": 1, "per_page": 20}


async def test_activity_created_on_vote_create(
    client: AsyncClient,
    seed_data: dict,
    admin_user: dict,
    auth: _AuthOverrider,
) -> None:
    uid = seed_data["user_id"]
    await _create_vote(client, auth, uid, seed_data["issue_id"], 2)

    with auth(admin_user["user_id"], "admin"):
        resp = await client.get("/api/activity/json")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    entry = data["items"][0]
    assert entry["user_id"] == uid
    assert entry["action"]["type"] == "vote_create"
    assert entry["action"]["issue_id"] == seed_data["issue_id"]
    assert entry["action"]["ranking"] == 2
    assert "timestamp" in entry


async def test_activity_created_on_vote_update(
    client: AsyncClient,
    seed_data: dict,
    admin_user: dict,
    auth: _AuthOverrider,
) -> None:
    uid = seed_data["user_id"]
    await _create_vote(client, auth, uid, seed_data["issue_id"], 1)

    with auth(uid, "contributor"):
        await client.put(
            f"/api/users/{uid}/votes",
            json={"issue_id": seed_data["issue_id"], "ranking": -2},
        )

    with auth(admin_user["user_id"], "admin"):
        resp = await client.get("/api/activity/json", params={"user_id": uid})
    data = resp.json()
    assert data["total"] == 2
    update_entry = data["items"][0]
    assert update_entry["action"]["type"] == "vote_update"
    assert update_entry["action"]["old_ranking"] == 1
    assert update_entry["action"]["new_ranking"] == -2


async def test_list_activity_filter_by_user(
    client: AsyncClient,
    seed_data: dict,
    admin_user: dict,
    auth: _AuthOverrider,
) -> None:
    uid = seed_data["user_id"]
    await _create_vote(client, auth, uid, seed_data["issue_id"], 3)

    with auth(admin_user["user_id"], "admin"):
        resp = await client.get("/api/activity/json", params={"user_id": uid})
    assert resp.json()["total"] == 1

    with auth(admin_user["user_id"], "admin"):
        resp = await client.get("/api/activity/json", params={"user_id": 99999})
    assert resp.json()["total"] == 0


async def test_list_activity_pagination(
    client: AsyncClient,
    seed_data: dict,
    admin_user: dict,
    auth: _AuthOverrider,
) -> None:
    uid = seed_data["user_id"]
    await _create_vote(client, auth, uid, seed_data["issue_id"], 2)
    await _create_vote(client, auth, uid, seed_data["issue_id_2"], -1)

    with auth(admin_user["user_id"], "admin"):
        resp = await client.get("/api/activity/json", params={"per_page": 1, "page": 1})
    data = resp.json()
    assert data["total"] == 2
    assert len(data["items"]) == 1

    with auth(admin_user["user_id"], "admin"):
        resp = await client.get("/api/activity/json", params={"per_page": 1, "page": 2})
    data = resp.json()
    assert len(data["items"]) == 1

    with auth(admin_user["user_id"], "admin"):
        resp = await client.get("/api/activity/json", params={"per_page": 1, "page": 3})
    assert len(resp.json()["items"]) == 0


async def test_list_activity_anonymous_unauthorized(client: AsyncClient) -> None:
    resp = await client.get("/api/activity/json")
    assert resp.status_code == 401


async def test_list_activity_contributor_forbidden(
    client: AsyncClient,
    seed_data: dict,
    auth: _AuthOverrider,
) -> None:
    with auth(seed_data["user_id"], "contributor"):
        resp = await client.get("/api/activity/json")
    assert resp.status_code == 403


# --- User activity (GET, contributor+ own / maintainer+ any) ---


async def test_get_user_activity_empty(
    client: AsyncClient,
    seed_data: dict,
    auth: _AuthOverrider,
) -> None:
    uid = seed_data["user_id"]
    with auth(uid, "contributor"):
        resp = await client.get(f"/api/users/{uid}/activity/json")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_get_user_activity(
    client: AsyncClient,
    seed_data: dict,
    auth: _AuthOverrider,
) -> None:
    uid = seed_data["user_id"]
    await _create_vote(client, auth, uid, seed_data["issue_id"], 3)
    await _create_vote(client, auth, uid, seed_data["issue_id_2"], -1)

    with auth(uid, "contributor"):
        resp = await client.get(f"/api/users/{uid}/activity/json")
    assert resp.status_code == 200
    entries = resp.json()
    assert len(entries) == 2
    assert all(e["user_id"] == uid for e in entries)
    assert all(e["action"]["type"] == "vote_create" for e in entries)


async def test_get_user_activity_other_user_forbidden_for_contributor(
    client: AsyncClient,
    seed_data: dict,
    admin_user: dict,
    auth: _AuthOverrider,
) -> None:
    with auth(seed_data["user_id"], "contributor"):
        resp = await client.get(f"/api/users/{admin_user['user_id']}/activity/json")
    assert resp.status_code == 403


async def test_get_user_activity_other_user_allowed_for_maintainer(
    client: AsyncClient,
    seed_data: dict,
    maintainer_user: dict,
    auth: _AuthOverrider,
) -> None:
    with auth(maintainer_user["user_id"], "maintainer"):
        resp = await client.get(f"/api/users/{seed_data['user_id']}/activity/json")
    assert resp.status_code == 200


async def test_get_user_activity_anonymous_unauthorized(client: AsyncClient) -> None:
    resp = await client.get("/api/users/1/activity/json")
    assert resp.status_code == 401


# --- Results (public) ---


@pytest.mark.usefixtures("seed_data")
async def test_list_results_empty(client: AsyncClient) -> None:
    resp = await client.get("/api/results/json")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert all(r["vote_count"] == 0 for r in data["items"])


async def test_list_results_with_votes(
    client: AsyncClient,
    seed_data: dict,
    auth: _AuthOverrider,
) -> None:
    uid = seed_data["user_id"]
    await _create_vote(client, auth, uid, seed_data["issue_id"], 3)
    await _create_vote(client, auth, uid, seed_data["issue_id_2"], -1)

    resp = await client.get("/api/results/json")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    by_id = {r["issue_id"]: r for r in data["items"]}
    assert by_id[seed_data["issue_id"]]["avg_ranking"] == 3.0
    assert by_id[seed_data["issue_id"]]["median_ranking"] == 3.0
    assert by_id[seed_data["issue_id"]]["vote_count"] == 1
    assert by_id[seed_data["issue_id_2"]]["avg_ranking"] == -1.0
    assert by_id[seed_data["issue_id_2"]]["median_ranking"] == -1.0


async def test_list_results_anonymous(client: AsyncClient) -> None:
    """Results endpoint is public — no auth needed."""
    resp = await client.get("/api/results/json")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Vote persistence across issue deletion
# ---------------------------------------------------------------------------


async def test_vote_survives_issue_deletion(
    client: AsyncClient,
    session: AsyncSession,
    seed_data: dict,
    auth: _AuthOverrider,
) -> None:
    """Votes must persist when their referenced issue is deleted."""
    uid = seed_data["user_id"]
    issue_id = seed_data["issue_id"]
    await _create_vote(client, auth, uid, issue_id, 2)

    await session.execute(delete(Issue).where(Issue.id == issue_id))
    await session.commit()

    result = await session.execute(select(Vote).where(Vote.issue_id == issue_id))
    vote = result.scalar_one_or_none()
    assert vote is not None
    assert vote.ranking == 2
    assert vote.issue_id == issue_id


async def test_vote_reconnects_after_issue_recreated(
    client: AsyncClient,
    session: AsyncSession,
    seed_data: dict,
    auth: _AuthOverrider,
) -> None:
    """After an issue is deleted and re-added, its votes are still linked."""
    uid = seed_data["user_id"]
    issue_id = seed_data["issue_id"]
    await _create_vote(client, auth, uid, issue_id, 3)

    await session.execute(delete(Issue).where(Issue.id == issue_id))
    await session.commit()

    restored = Issue(
        id=issue_id,
        org="acme",
        repo="widgets",
        number=1,
        type="issue",
        title="Fix the widget (reopened)",
        body="Still broken.",
        url="https://github.com/acme/widgets/issues/1",
        labels=["bug"],
        state="open",
        fetched_at=datetime.now(UTC),
    )
    session.add(restored)
    await session.commit()

    with auth(uid, "contributor"):
        resp = await client.get(f"/api/users/{uid}/votes/json", params={"issue_id": issue_id})
    assert resp.status_code == 200
    votes = resp.json()
    assert len(votes) == 1
    assert votes[0]["ranking"] == 3
    assert votes[0]["issue_id"] == issue_id
