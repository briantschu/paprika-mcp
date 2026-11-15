"""Rate-limit backoff, pacing and on-disk persistence of the recipe cache."""
import json
import os
import stat
from unittest.mock import AsyncMock

import pytest

import src.paprika_client as pc
from src.paprika_client import PaprikaClient, PaprikaRateLimitedError


def _index(*pairs):
    return {"result": [{"uid": uid, "hash": h} for uid, h in pairs]}


def _recipe(uid, h="h"):
    return {"result": {"uid": uid, "name": f"Recipe {uid}", "hash": h, "in_trash": False}}


def _rate_limited(retry_after=None):
    return PaprikaRateLimitedError("Paprika is rate-limiting us.", retry_after=retry_after)


class FakePaprika:
    """Scripted Paprika: serves an index and recipe bodies, 429s on demand."""

    def __init__(self, recipes, limit_on=()):
        self.recipes = dict(recipes)          # uid -> hash
        self.limit_on = list(limit_on)        # uids that 429 (once each, in order)
        self.calls = []

    async def __call__(self, method, endpoint, **kwargs):
        self.calls.append(endpoint)
        if endpoint == "/sync/recipes":
            return _index(*self.recipes.items())
        uid = endpoint.split("/")[3]
        if self.limit_on and self.limit_on[0] == uid:
            self.limit_on.pop(0)
            raise _rate_limited()
        return _recipe(uid, self.recipes[uid])

    def recipe_calls(self):
        return [c for c in self.calls if c != "/sync/recipes"]


@pytest.fixture
def sleeps(monkeypatch):
    """Record asyncio.sleep delays without actually sleeping."""
    recorded = []

    async def fake_sleep(delay):
        recorded.append(delay)

    monkeypatch.setattr(pc.asyncio, "sleep", fake_sleep)
    return recorded


# -- pacing / stop on 429 -----------------------------------------------------

@pytest.mark.asyncio
async def test_refresh_stops_at_first_429_and_keeps_partial(sleeps):
    client = PaprikaClient("me@example.com", "pw")
    fake = FakePaprika({"a": "1", "b": "1", "c": "1", "d": "1"}, limit_on=["b"])
    client._make_authenticated_request = fake

    with pytest.raises(PaprikaRateLimitedError):
        await client.refresh_recipe_cache()

    # Fetched "a", hit 429 on "b", and sent nothing after that.
    assert fake.recipe_calls() == ["/sync/recipe/a/", "/sync/recipe/b/"]
    assert set(client._recipe_cache) == {"a"}
    # Fingerprint not committed, so the next refresh fetches the rest.
    assert client._recipe_index_fingerprint is None

    await client.refresh_recipe_cache()
    assert set(client._recipe_cache) == {"a", "b", "c", "d"}
    assert fake.recipe_calls()[2:] == [
        "/sync/recipe/b/", "/sync/recipe/c/", "/sync/recipe/d/",
    ]


@pytest.mark.asyncio
async def test_refresh_fetches_one_at_a_time_with_gap(sleeps, monkeypatch):
    monkeypatch.setattr(pc, "RECIPE_FETCH_INTERVAL_SECONDS", 0.5)
    client = PaprikaClient("me@example.com", "pw")
    client._make_authenticated_request = FakePaprika({"a": "1", "b": "1", "c": "1"})

    await client.refresh_recipe_cache()

    # A gap before every request except the first.
    assert sleeps == [0.5, 0.5]


# -- warm-up backoff ------------------------------------------------------------

@pytest.mark.asyncio
async def test_warm_up_backs_off_and_resumes(sleeps, monkeypatch):
    monkeypatch.setattr(pc, "RATE_LIMIT_BACKOFF_SECONDS", 30)
    monkeypatch.setattr(pc, "RATE_LIMIT_BACKOFF_MAX_SECONDS", 300)
    client = PaprikaClient("me@example.com", "pw")
    fake = FakePaprika({"a": "1", "b": "1", "c": "1"}, limit_on=["b"])
    client._make_authenticated_request = fake

    await client.warm_up_cache()

    assert set(client._recipe_cache) == {"a", "b", "c"}
    assert 30 in sleeps  # waited out the 429 before resuming
    # "a" was not fetched twice.
    assert fake.recipe_calls().count("/sync/recipe/a/") == 1
    assert client._cache_ready.is_set()
    assert client.recipe_download_paused is False


@pytest.mark.asyncio
async def test_warm_up_honours_retry_after(sleeps):
    client = PaprikaClient("me@example.com", "pw")
    calls = {"n": 0}

    async def fake(method, endpoint, **kwargs):
        if endpoint == "/sync/recipes":
            calls["n"] += 1
            if calls["n"] == 1:
                raise _rate_limited(retry_after=17)
            return _index(("a", "1"))
        return _recipe("a", "1")

    client._make_authenticated_request = fake
    await client.warm_up_cache()

    assert 17 in sleeps
    assert set(client._recipe_cache) == {"a"}


@pytest.mark.asyncio
async def test_warm_up_gives_up_after_max_retries(sleeps, monkeypatch):
    monkeypatch.setattr(pc, "RATE_LIMIT_BACKOFF_SECONDS", 30)
    monkeypatch.setattr(pc, "RATE_LIMIT_BACKOFF_MAX_SECONDS", 100)
    client = PaprikaClient("me@example.com", "pw")
    client._make_authenticated_request = AsyncMock(side_effect=_rate_limited())

    await client.warm_up_cache()  # must not raise or loop forever

    # Exponential, capped: 30, 60, 100, 100, 100.
    assert sleeps == [30, 60, 100, 100, 100]
    assert client._make_authenticated_request.call_count == pc.RATE_LIMIT_MAX_RETRIES + 1
    assert client._cache_ready.is_set()


# -- list_recipes while the download is paused --------------------------------------

@pytest.mark.asyncio
async def test_list_recipes_during_backoff_does_not_call_paprika():
    client = PaprikaClient("me@example.com", "pw")
    client._recipe_cache = {"a": _recipe("a")["result"]}
    client._cache_ready.set()
    client._rate_limit_backoff = True
    client._make_authenticated_request = AsyncMock()

    recipes = await client.list_recipes()

    assert [r["uid"] for r in recipes] == ["a"]
    client._make_authenticated_request.assert_not_called()


@pytest.mark.asyncio
async def test_list_recipes_during_backoff_with_empty_cache_is_rate_limited():
    client = PaprikaClient("me@example.com", "pw")
    client._cache_ready.set()
    client._rate_limit_backoff = True
    client._make_authenticated_request = AsyncMock()

    with pytest.raises(PaprikaRateLimitedError):
        await client.list_recipes()
    client._make_authenticated_request.assert_not_called()


@pytest.mark.asyncio
async def test_list_recipes_serves_partial_cache_while_refresh_runs():
    client = PaprikaClient("me@example.com", "pw")
    client._recipe_cache = {"a": _recipe("a")["result"]}
    client._cache_ready.set()
    client._make_authenticated_request = AsyncMock()

    async with client._cache_lock:  # simulate the warm-up holding the lock
        client._refresh_progress = (1, 10)
        assert client.recipe_loading_progress == (1, 10)
        recipes = await client.list_recipes()

    assert [r["uid"] for r in recipes] == ["a"]
    client._make_authenticated_request.assert_not_called()
    assert client.recipe_loading_progress is None


def test_loading_note():
    import src.server as server

    client = PaprikaClient("me@example.com", "pw")
    assert server._recipe_loading_note(client) == ""
    client._rate_limit_backoff = True
    assert "rate-limiting" in server._recipe_loading_note(client)


# -- on-disk cache ----------------------------------------------------------------

@pytest.mark.asyncio
async def test_disk_cache_round_trip_fetches_only_changes(tmp_path, sleeps):
    path = tmp_path / "data" / "recipe_cache.json"

    first = PaprikaClient("Me@Example.com", "pw", cache_file=path)
    first._make_authenticated_request = FakePaprika({"a": "1", "b": "1"})
    await first.warm_up_cache()

    assert path.exists()
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert not path.with_name(path.name + ".tmp").exists()

    # Restart: "b" changed on the server, "c" is new, "a" is untouched.
    second = PaprikaClient("me@example.com", "pw", cache_file=path)
    fake = FakePaprika({"a": "1", "b": "2", "c": "1"})
    second._make_authenticated_request = fake
    await second.warm_up_cache()

    assert sorted(fake.recipe_calls()) == ["/sync/recipe/b/", "/sync/recipe/c/"]
    assert second._recipe_cache["b"]["hash"] == "2"

    # Third start with nothing changed: zero recipe downloads.
    third = PaprikaClient("me@example.com", "pw", cache_file=path)
    fake3 = FakePaprika({"a": "1", "b": "2", "c": "1"})
    third._make_authenticated_request = fake3
    await third.warm_up_cache()
    assert fake3.recipe_calls() == []


@pytest.mark.asyncio
async def test_disk_cache_saves_partial_progress_on_429(tmp_path, sleeps):
    path = tmp_path / "recipe_cache.json"
    client = PaprikaClient("me@example.com", "pw", cache_file=path)
    client._make_authenticated_request = FakePaprika(
        {"a": "1", "b": "1"}, limit_on=["b"]
    )

    with pytest.raises(PaprikaRateLimitedError):
        await client.refresh_recipe_cache()

    saved = json.loads(path.read_text())
    assert set(saved["recipes"]) == {"a"}


@pytest.mark.asyncio
async def test_disk_cache_from_other_account_is_ignored(tmp_path, sleeps):
    path = tmp_path / "recipe_cache.json"
    other = PaprikaClient("someone-else@example.com", "pw", cache_file=path)
    other._make_authenticated_request = FakePaprika({"x": "1"})
    await other.warm_up_cache()

    me = PaprikaClient("me@example.com", "pw", cache_file=path)
    assert me._load_cache_from_disk() is False
    assert me._recipe_cache == {}


def test_corrupt_disk_cache_is_ignored(tmp_path):
    path = tmp_path / "recipe_cache.json"
    path.write_text("{not json")
    client = PaprikaClient("me@example.com", "pw", cache_file=path)
    assert client._load_cache_from_disk() is False
    assert client._recipe_cache == {}


def test_no_cache_file_means_no_disk_io(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = PaprikaClient("me@example.com", "pw")
    client._save_cache_to_disk()
    assert client._load_cache_from_disk() is False
    assert list(tmp_path.iterdir()) == []
