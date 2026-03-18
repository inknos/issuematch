from __future__ import annotations

import pytest
from httpx import AsyncClient


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_vote(client: AsyncClient, uid: int, issue_id: str, ranking: int):
    resp = await client.post(
        f"/api/users/{uid}/votes",
        json={"issue_id": issue_id, "ranking": ranking},
    )
    assert resp.status_code == 201
    return resp


# ---------------------------------------------------------------------------
# GET /api/votes  (paginated envelope)
# ---------------------------------------------------------------------------


async def test_list_votes_empty(client: AsyncClient):
    resp = await client.get("/api/votes")
    assert resp.status_code == 200
    data = resp.json()
    assert data == {"items": [], "total": 0, "page": 1, "per_page": 20}


async def test_list_votes_returns_all(client: AsyncClient, seed_data: dict):
    uid = seed_data["user_id"]
    await _create_vote(client, uid, seed_data["issue_id"], 2)
    await _create_vote(client, uid, seed_data["issue_id_2"], -1)

    resp = await client.get("/api/votes")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    assert len(data["items"]) == 2


async def test_list_votes_filter_by_issue_id(client: AsyncClient, seed_data: dict):
    uid = seed_data["user_id"]
    await _create_vote(client, uid, seed_data["issue_id"], 3)
    await _create_vote(client, uid, seed_data["issue_id_2"], -1)

    resp = await client.get("/api/votes", params={"issue_id": seed_data["issue_id"]})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["issue_id"] == seed_data["issue_id"]


async def test_list_votes_filter_by_org(client: AsyncClient, seed_data: dict):
    uid = seed_data["user_id"]
    await _create_vote(client, uid, seed_data["issue_id"], 1)

    resp = await client.get("/api/votes", params={"org": "acme"})
    assert resp.status_code == 200
    assert resp.json()["total"] == 1

    resp = await client.get("/api/votes", params={"org": "nonexistent"})
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


async def test_list_votes_filter_by_repo(client: AsyncClient, seed_data: dict):
    uid = seed_data["user_id"]
    await _create_vote(client, uid, seed_data["issue_id"], 1)
    await _create_vote(client, uid, seed_data["issue_id_2"], -2)

    resp = await client.get("/api/votes", params={"repo": "widgets"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["issue_id"] == seed_data["issue_id"]


async def test_list_votes_filter_by_user_id(client: AsyncClient, seed_data: dict):
    uid = seed_data["user_id"]
    await _create_vote(client, uid, seed_data["issue_id"], 1)

    resp = await client.get("/api/votes", params={"user_id": uid})
    assert resp.status_code == 200
    assert resp.json()["total"] == 1

    resp = await client.get("/api/votes", params={"user_id": 99999})
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


async def test_list_votes_pagination(client: AsyncClient, seed_data: dict):
    uid = seed_data["user_id"]
    await _create_vote(client, uid, seed_data["issue_id"], 2)
    await _create_vote(client, uid, seed_data["issue_id_2"], -1)

    resp = await client.get("/api/votes", params={"per_page": 1, "page": 1})
    data = resp.json()
    assert data["total"] == 2
    assert len(data["items"]) == 1
    assert data["page"] == 1
    assert data["per_page"] == 1

    resp = await client.get("/api/votes", params={"per_page": 1, "page": 2})
    data = resp.json()
    assert data["total"] == 2
    assert len(data["items"]) == 1
    assert data["page"] == 2

    resp = await client.get("/api/votes", params={"per_page": 1, "page": 3})
    data = resp.json()
    assert data["total"] == 2
    assert len(data["items"]) == 0


async def test_list_votes_pagination_with_filter(client: AsyncClient, seed_data: dict):
    uid = seed_data["user_id"]
    await _create_vote(client, uid, seed_data["issue_id"], 3)
    await _create_vote(client, uid, seed_data["issue_id_2"], -1)

    resp = await client.get("/api/votes", params={"org": "acme", "per_page": 1, "page": 1})
    data = resp.json()
    assert data["total"] == 2
    assert len(data["items"]) == 1


# ---------------------------------------------------------------------------
# GET /api/users/{user_id}/votes
# ---------------------------------------------------------------------------


async def test_get_user_votes_empty(client: AsyncClient, seed_data: dict):
    uid = seed_data["user_id"]
    resp = await client.get(f"/api/users/{uid}/votes")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_get_user_votes_all(client: AsyncClient, seed_data: dict):
    uid = seed_data["user_id"]
    await _create_vote(client, uid, seed_data["issue_id"], 3)
    await _create_vote(client, uid, seed_data["issue_id_2"], -1)

    resp = await client.get(f"/api/users/{uid}/votes")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


async def test_get_user_votes_filter_by_issue_id(client: AsyncClient, seed_data: dict):
    uid = seed_data["user_id"]
    await _create_vote(client, uid, seed_data["issue_id"], 2)
    await _create_vote(client, uid, seed_data["issue_id_2"], -3)

    resp = await client.get(
        f"/api/users/{uid}/votes",
        params={"issue_id": seed_data["issue_id_2"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["issue_id"] == seed_data["issue_id_2"]
    assert data[0]["ranking"] == -3


# ---------------------------------------------------------------------------
# POST /api/users/{user_id}/votes
# ---------------------------------------------------------------------------


async def test_create_vote(client: AsyncClient, seed_data: dict):
    uid = seed_data["user_id"]
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


async def test_create_vote_null_ranking(client: AsyncClient, seed_data: dict):
    uid = seed_data["user_id"]
    resp = await client.post(
        f"/api/users/{uid}/votes",
        json={"issue_id": seed_data["issue_id"]},
    )
    assert resp.status_code == 201
    assert resp.json()["ranking"] is None


async def test_create_vote_duplicate_409(client: AsyncClient, seed_data: dict):
    uid = seed_data["user_id"]
    await _create_vote(client, uid, seed_data["issue_id"], 1)
    resp = await client.post(
        f"/api/users/{uid}/votes",
        json={"issue_id": seed_data["issue_id"]},
    )
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# PUT /api/users/{user_id}/votes
# ---------------------------------------------------------------------------


async def test_update_vote(client: AsyncClient, seed_data: dict):
    uid = seed_data["user_id"]
    await _create_vote(client, uid, seed_data["issue_id"], 1)

    resp = await client.put(
        f"/api/users/{uid}/votes",
        json={"issue_id": seed_data["issue_id"], "ranking": -2},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ranking"] == -2
    assert data["issue_id"] == seed_data["issue_id"]


async def test_update_vote_not_found(client: AsyncClient, seed_data: dict):
    uid = seed_data["user_id"]
    resp = await client.put(
        f"/api/users/{uid}/votes",
        json={"issue_id": seed_data["issue_id"], "ranking": 1},
    )
    assert resp.status_code == 404
