"""Meal planner entries must point at the account's meal types via type_uid.

Paprika decides a planned meal's category from ``type_uid`` (one of the
account's meal types from /sync/mealtypes, including custom ones). Sending
only the legacy numeric ``type`` with an empty ``type_uid`` puts every meal in
the wrong category.
"""
import gzip
import json
from datetime import date
from unittest.mock import patch

import pytest

from src.paprika_client import (
    InvalidArgumentError,
    PaprikaClient,
    PaprikaRateLimitedError,
)
import src.server as server

# Shaped like a real account: built-in types with original_type, plus a custom one.
MEAL_TYPES = [
    {"uid": "MAKEAHEAD-UID", "name": "Make-ahead", "original_type": None, "order_flag": 4,
     "color": "#008080", "export_all_day": False, "export_time": 64800},
    {"uid": "DINNER-UID", "name": "Dinner", "original_type": 2, "order_flag": 2,
     "color": "#2161C9", "export_all_day": False, "export_time": 64800},
    {"uid": "LUNCH-UID", "name": "Lunch", "original_type": 1, "order_flag": 1,
     "color": "#377118", "export_all_day": False, "export_time": 43200},
    {"uid": "BREAKFAST-UID", "name": "Breakfast", "original_type": 0, "order_flag": 0,
     "color": "#E36C0C", "export_all_day": False, "export_time": 28800},
    {"uid": "SNACKS-UID", "name": "Snacks", "original_type": 3, "order_flag": 3,
     "color": "#711D75", "export_all_day": True, "export_time": 0},
]


class FakePaprika:
    def __init__(self, meals=None, meal_types=MEAL_TYPES):
        self.meals = meals or []
        self.meal_types = meal_types
        self.posted = []          # decoded meal arrays POSTed to /sync/meals
        self.mealtype_gets = 0

    async def __call__(self, method, endpoint, **kwargs):
        if method == "GET" and endpoint == "/sync/mealtypes":
            self.mealtype_gets += 1
            if isinstance(self.meal_types, Exception):
                raise self.meal_types
            return {"result": self.meal_types}
        if method == "GET" and endpoint == "/sync/meals":
            return {"result": self.meals}
        if method == "POST" and endpoint == "/sync/meals":
            form = kwargs["data"]
            payload = form._fields[0][2]
            self.posted.append(json.loads(gzip.decompress(payload)))
            return {"result": True}
        raise AssertionError(f"Unexpected: {method} {endpoint}")


@pytest.fixture
def client():
    c = PaprikaClient("test@example.com", "pass")
    c.token = "fake-token"
    c._recipe_cache = {
        "R1": {"uid": "R1", "name": "Breakfast Casserole", "in_trash": False},
        "R2": {"uid": "R2", "name": "Harira", "in_trash": False},
    }
    c._cache_ready.set()

    async def no_refresh(*a, **k):
        return 0

    c.refresh_recipe_cache = no_refresh
    return c


def _meal(uid, name, type_int, type_uid, day="2026-11-15"):
    return {"uid": uid, "recipe_uid": None, "name": name, "date": f"{day} 00:00:00",
            "type": type_int, "type_uid": type_uid, "order_flag": 0, "deleted": False}


# -- plan_meals ------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("requested, uid, type_int", [
    ("dinner", "DINNER-UID", 2),
    ("Breakfast", "BREAKFAST-UID", 0),
    ("snack", "SNACKS-UID", 3),        # singular matches "Snacks"
    ("make ahead", "MAKEAHEAD-UID", 3),  # custom type, punctuation ignored
    ("Make-Ahead", "MAKEAHEAD-UID", 3),
])
async def test_plan_meals_sets_type_uid(client, requested, uid, type_int):
    fake = FakePaprika()
    client._make_authenticated_request = fake

    res = await client.plan_meals([
        {"recipe_name_or_id": "Harira", "date": "2026-11-17", "meal_type": requested}
    ])

    sent = fake.posted[0][0]
    assert sent["type_uid"] == uid
    assert sent["type"] == type_int
    assert res[0]["meal_type"] == next(t["name"] for t in MEAL_TYPES if t["uid"] == uid).lower()


@pytest.mark.asyncio
async def test_plan_meals_defaults_to_dinner(client):
    fake = FakePaprika()
    client._make_authenticated_request = fake

    await client.plan_meals([{"recipe_name_or_id": "Harira", "date": "2026-11-17"}])

    assert fake.posted[0][0]["type_uid"] == "DINNER-UID"


@pytest.mark.asyncio
async def test_renamed_builtin_type_matches_by_slot(client):
    renamed = [dict(t, name="Supper") if t["uid"] == "DINNER-UID" else t for t in MEAL_TYPES]
    fake = FakePaprika(meal_types=renamed)
    client._make_authenticated_request = fake

    await client.plan_meals([
        {"recipe_name_or_id": "Harira", "date": "2026-11-17", "meal_type": "dinner"}
    ])

    assert fake.posted[0][0]["type_uid"] == "DINNER-UID"


@pytest.mark.asyncio
async def test_unknown_meal_type_lists_account_types(client):
    fake = FakePaprika()
    client._make_authenticated_request = fake

    with pytest.raises(InvalidArgumentError) as exc_info:
        await client.plan_meals([
            {"recipe_name_or_id": "Harira", "date": "2026-11-17", "meal_type": "brunch"}
        ])

    msg = str(exc_info.value)
    assert "brunch" in msg and "Make-ahead" in msg and "Snacks" in msg
    assert fake.posted == []
    assert fake.mealtype_gets == 2  # re-read once in case the type was just added


@pytest.mark.asyncio
async def test_meal_types_read_once_per_run(client):
    fake = FakePaprika()
    client._make_authenticated_request = fake

    for day in ("2026-11-17", "2026-11-18"):
        await client.plan_meals([
            {"recipe_name_or_id": "Harira", "date": day, "meal_type": "lunch"}
        ])
    await client.get_plan(days_back=1, days_ahead=1, reference_date=date(2026, 11, 15))

    assert fake.mealtype_gets == 1


@pytest.mark.asyncio
async def test_falls_back_to_legacy_slots_when_meal_types_unreadable(client):
    fake = FakePaprika(meal_types=[])
    client._make_authenticated_request = fake

    await client.plan_meals([
        {"recipe_name_or_id": "Harira", "date": "2026-11-17", "meal_type": "lunch"}
    ])

    sent = fake.posted[0][0]
    assert sent["type"] == 1
    assert sent["type_uid"] == ""

    # The fallback isn't kept: once Paprika answers, the real types are used.
    fake.meal_types = MEAL_TYPES
    await client.plan_meals([
        {"recipe_name_or_id": "Harira", "date": "2026-11-18", "meal_type": "lunch"}
    ])
    assert fake.posted[1][0]["type_uid"] == "LUNCH-UID"


@pytest.mark.asyncio
async def test_rate_limit_reading_meal_types_propagates(client):
    fake = FakePaprika(meal_types=PaprikaRateLimitedError("slow down"))
    client._make_authenticated_request = fake

    with pytest.raises(PaprikaRateLimitedError):
        await client.plan_meals([
            {"recipe_name_or_id": "Harira", "date": "2026-11-17"}
        ])
    assert fake.posted == []


# -- reading, deleting and moving ------------------------------------------------------

@pytest.mark.asyncio
async def test_get_plan_labels_by_type_uid(client):
    meals = [
        _meal("M1", "Harira", 2, "DINNER-UID"),
        # Real data: the number says breakfast/snack, the type_uid says Make-ahead.
        _meal("M2", "Breakfast Casserole", 0, "MAKEAHEAD-UID"),
        _meal("M3", "Nuts", 3, "MAKEAHEAD-UID"),
        _meal("M4", "Toast", 0, "BREAKFAST-UID"),
        # Legacy entry without type_uid falls back to the number.
        _meal("M5", "Soup", 1, ""),
    ]
    client._make_authenticated_request = FakePaprika(meals=meals)

    plan = await client.get_plan(days_back=1, days_ahead=1, reference_date=date(2026, 11, 15))

    labels = {m["uid"]: m["meal_type"] for m in plan}
    assert labels == {"M1": "dinner", "M2": "make-ahead", "M3": "make-ahead",
                      "M4": "breakfast", "M5": "lunch"}
    # Ordered like the planner: breakfast, lunch, dinner, ..., make-ahead.
    assert [m["uid"] for m in plan] == ["M4", "M5", "M1", "M2", "M3"]


@pytest.mark.asyncio
async def test_server_get_plan_shows_custom_type(client):
    today = date.today().isoformat()
    client._make_authenticated_request = FakePaprika(
        meals=[_meal("M1", "Breakfast Casserole", 3, "MAKEAHEAD-UID", day=today)]
    )

    with patch("src.server._client_or_raise", return_value=client):
        out = await server.get_plan(days_back=0, days_ahead=0)

    assert "make-ahead" in out and "Breakfast Casserole" in out


@pytest.mark.asyncio
async def test_move_planned_meal_changes_category(client):
    fake = FakePaprika(meals=[_meal("M1", "Harira", 3, "SNACKS-UID")])
    client._make_authenticated_request = fake

    res = await client.move_planned_meal(entry_id="M1", to_date="2026-11-15", to_meal_type="dinner")

    sent = fake.posted[0][0]
    assert sent["type_uid"] == "DINNER-UID"
    assert sent["type"] == 2
    assert sent["date"] == "2026-11-15 00:00:00"
    assert res["meal_type"] == "dinner"


@pytest.mark.asyncio
async def test_move_planned_meal_keeps_category_when_not_given(client):
    fake = FakePaprika(meals=[_meal("M1", "Casserole", 0, "MAKEAHEAD-UID")])
    client._make_authenticated_request = fake

    res = await client.move_planned_meal(entry_id="M1", to_date="2026-11-16")

    sent = fake.posted[0][0]
    assert sent["type_uid"] == "MAKEAHEAD-UID"
    assert res["meal_type"] == "make-ahead"


@pytest.mark.asyncio
async def test_delete_matches_meal_type_by_type_uid(client):
    meals = [
        _meal("M1", "Harira", 3, "DINNER-UID"),          # number disagrees with uid
        _meal("M2", "Casserole", 3, "MAKEAHEAD-UID"),
    ]
    fake = FakePaprika(meals=meals)
    client._make_authenticated_request = fake

    res = await client.delete_planned_meal(date="2026-11-15", meal_type="make-ahead")
    assert res["uid"] == "M2"
    assert res["meal_type"] == "make-ahead"

    res = await client.delete_planned_meal(date="2026-11-15", meal_type="dinner")
    assert res["uid"] == "M1"
