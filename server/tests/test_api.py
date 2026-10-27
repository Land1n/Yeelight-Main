import pytest
from fastapi.testclient import TestClient

from server.app import create_app

KEY = "secret-key"
STATE = {"lamps": [{"ip": "10.0.0.1", "online": True, "last_seen": 1.0, "props": {}}],
         "modes": [], "log": []}


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(KEY, str(tmp_path / "t.db")))


def poll(client, key=KEY, results=None):
    return client.post(
        "/agent/poll",
        json={"state": STATE, "results": results or []},
        headers={"X-Access-Key": key},
    )


def test_create_app_requires_key(tmp_path):
    with pytest.raises(RuntimeError):
        create_app("", str(tmp_path / "t.db"))


def test_poll_rejects_wrong_key(client):
    assert poll(client, key="bad").status_code == 401
    assert client.post("/agent/poll", json={"state": STATE, "results": []}).status_code == 401


def test_action_flow(client):
    action_id = client.post("/api/actions", json={"kind": "command", "ip": "10.0.0.1",
                                                  "command": {"type": "turn_on"}}).json()["id"]
    assert client.get(f"/api/actions/{action_id}").json()["status"] == "pending"

    actions = poll(client).json()["actions"]
    assert actions[0]["id"] == action_id
    assert client.get(f"/api/actions/{action_id}").json()["status"] == "sent"
    assert poll(client).json()["actions"] == []

    poll(client, results=[{"id": action_id, "ok": True, "message": "готово"}])
    item = client.get(f"/api/actions/{action_id}").json()
    assert item["status"] == "done"
    assert item["result"]["message"] == "готово"


def test_state_reports_online(client):
    assert client.get("/api/state").json()["online"] is False
    poll(client)
    body = client.get("/api/state").json()
    assert body["online"] is True
    assert body["lamps"][0]["ip"] == "10.0.0.1"


def test_command_requires_payload(client):
    assert client.post("/api/actions", json={"kind": "command"}).status_code == 422


def test_unknown_action_returns_404(client):
    assert client.get("/api/actions/999").status_code == 404
