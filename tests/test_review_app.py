import pytest
from fastapi.testclient import TestClient

from notam_gold.review.app import create_app
from tests.factories import effect, extraction


@pytest.fixture
def silver():
    return extraction(effect("28L", "full"))


@pytest.fixture
def client(gold_db, silver):
    key = gold_db.add_notam("A1/2026")
    gold_db.add_silver(key, silver)
    gold_db.connection.commit()
    return TestClient(create_app(gold_db.path, "Tester"))


def review(client, status, value=None, note=None):
    return client.post("/api/review", json={"key": "KSFO A1/2026", "status": status, "extraction": value, "note": note})


def test_saving_records_whether_the_silver_label_was_edited(client, silver):
    assert review(client, "edited", silver).json() == {"status": "accepted", "edited": False}
    assert review(client, "accepted", extraction(effect("10R", "full"))).json() == {"status": "edited", "edited": True}
    current = client.get("/api/notam", params={"key": "KSFO A1/2026"}).json()["review"]
    assert (current["status"], current["reviewer"]) == ("edited", "Tester")


def test_rejects_invalid_labels_but_keeps_ambiguous_ones(client):
    invalid = extraction(effect("28L", "none"))
    response = review(client, "accepted", invalid)
    assert response.status_code == 422
    assert response.json()["detail"]["problems"][0]["path"] == "effects[0]"
    assert review(client, "ambiguous", invalid, note="Can't tell").json()["status"] == "ambiguous"


def test_pages_and_scripts_are_revalidated_on_every_load(client):
    for path in ("/", "/static/app.js", "/api/progress"):
        assert client.get(path).headers["cache-control"] == "no-cache"


def test_a_placeholder_review_leaves_its_notam_in_the_unreviewed_queue(client, gold_db, silver):
    gold_db.add_review("KSFO A1/2026", "accepted", silver, reviewer="Unreviewed: run A silver label")
    gold_db.connection.commit()
    assert [item["status"] for item in client.get("/api/queue").json()["items"]] == ["unreviewed"]
    review(client, "accepted", silver)
    assert [item["status"] for item in client.get("/api/queue").json()["items"]] == ["accepted"]
