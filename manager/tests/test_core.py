import json

import pytest
from lamp import LampError
from protocol import Action

from manager.core import Core


class FakeLamp:
    def __init__(self, ip, fail=False):
        self.ip = ip
        self.fail = fail
        self.calls = []

    def state(self):
        if self.fail:
            raise LampError("offline")
        return {"power": "on"}


@pytest.fixture
def core(tmp_path, monkeypatch):
    monkeypatch.setattr("manager.core.PACE_SECONDS", 0)
    data = tmp_path / "data"
    data.mkdir()
    (data / "bulbs.json").write_text(json.dumps(["10.0.0.1"]), encoding="utf-8")
    return Core(data_dir=data, lamp_factory=FakeLamp, discover_fn=lambda timeout: [])


def test_default_modes_created(core):
    assert core.dir.joinpath("modes.json").is_file()
    assert core.state().modes


def test_add_and_remove_lamp(core):
    core.add("10.0.0.2")
    assert "10.0.0.2" in [lamp.ip for lamp in core.state().lamps]
    core.remove("10.0.0.2")
    assert "10.0.0.2" not in [lamp.ip for lamp in core.state().lamps]


def test_add_rejects_bad_ip(core):
    with pytest.raises(ValueError):
        core.add("not-an-ip")


def test_handle_reports_error_without_raising(core):
    result = core.handle(Action(id=7, kind="remove", ip="10.9.9.9"))
    assert result.id == 7
    assert result.ok is False


def test_undo_without_history_fails(core):
    with pytest.raises(ValueError):
        core.undo("10.0.0.1")


def test_save_mode_validates_steps(core):
    with pytest.raises(ValueError):
        core.save_mode("Пусто", [], 1.0)
    with pytest.raises(ValueError):
        core.save_mode("Плохой/имя", [{"type": "turn_on"}], 1.0)


def test_save_and_delete_mode(core):
    core.save_mode("Тест", [{"type": "turn_on"}], 1.0)
    assert any(mode["name"] == "Тест" for mode in core.state().modes)
    core.delete_mode("Тест")
    assert not any(mode["name"] == "Тест" for mode in core.state().modes)


def test_start_unknown_mode_fails(core):
    with pytest.raises(ValueError):
        core.start_mode("нет такого", "10.0.0.1")
