"""Host tests for the pure web router (webapp.route). python tests/test_webapp.py"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "firmware"))

import webapp as W  # noqa: E402


class FakeActions:
    def __init__(self):
        self.state = {
            "temp": 24.0,
            "humid": 55.0,
            "out_temp": 15.0,
            "out_humid": 80.0,
            "window": "closed",
            "vent": False,
            "circ": False,
            "mister": False,
            "win_mode": "AUTO",
            "fan_mode": "AUTO",
            "mis_mode": "AUTO",
            "mis_left": None,
            "auto": False,
            "unit": "F",
            "time": 1000,
        }
        self.calls = []

    def status(self):
        return dict(self.state)

    def snapshot(self):
        return {
            "samples": [
                {
                    "t": 1000,
                    "in_t": 24.0,
                    "in_h": 55,
                    "out_t": 15.0,
                    "out_h": 80,
                    "vent": 1,
                    "circ": 0,
                    "mist": 0,
                    "win": 1,
                },
                {
                    "t": 1060,
                    "in_t": None,
                    "in_h": None,
                    "out_t": 15.5,
                    "out_h": 79,
                    "vent": 0,
                    "circ": 0,
                    "mist": 0,
                    "win": 0,
                },
            ],
            "events": [
                {
                    "t": 1000,
                    "src": "web",
                    "dev": "fans",
                    "act": "OFF",
                    "in_t": 24.0,
                    "in_h": 55,
                    "out_t": 15.0,
                    "out_h": 80,
                },
            ],
        }

    def window(self, a):
        self.calls.append(("window", a))
        self.state["win_mode"] = a or "OFF"
        return self.status()

    def fans(self, a):
        self.calls.append(("fans", a))
        self.state["fan_mode"] = a or "OFF"  # a bare cycle lands on OFF from AUTO
        return self.status()

    def mister(self, a):
        self.calls.append(("mister", a))
        self.state["mis_mode"] = a or "OFF"
        return self.status()

    def auto(self, a):
        self.calls.append(("auto", a))
        self.state["auto"] = not self.state["auto"]
        return self.status()

    def get_settings(self):
        return {
            "specs": [
                {
                    "key": "mist_burst_s",
                    "group": "Misting",
                    "label": "Burst on (s)",
                    "type": "int",
                    "min": 1,
                    "max": 60,
                    "step": 1,
                    "value": 5,
                }
            ]
        }

    def set_settings(self, incoming):
        self.calls.append(("settings", dict(incoming)))
        out = self.get_settings()
        out["applied"] = {k: v for k, v in incoming.items() if k == "mist_burst_s"}
        return out


def test_index_html():
    st, ct, body = W.route("GET", "/", FakeActions())
    assert st == 200 and ct == "text/html" and "Greenhouse" in body


def test_status_json():
    st, ct, body = W.route("GET", "/status", FakeActions())
    assert st == 200 and ct == "application/json"
    d = json.loads(body)
    assert d["temp"] == 24.0 and d["window"] == "closed"


def test_cycle_fans_mode():
    a = FakeActions()
    st, ct, body = W.route("POST", "/fans", a)
    assert st == 200
    assert json.loads(body)["fan_mode"] == "OFF"
    assert a.calls == [("fans", None)]


def test_explicit_action_param():
    a = FakeActions()
    W.route("POST", "/window?a=OPN", a)
    assert a.calls == [("window", "OPN")]


def test_data_snapshot():
    st, ct, body = W.route("GET", "/data", FakeActions())
    assert st == 200
    assert set(json.loads(body).keys()) == {"samples", "events"}


def test_samples_csv():
    st, ct, body = W.route("GET", "/data.csv", FakeActions())
    assert st == 200 and ct == "text/csv"
    lines = body.strip().split("\n")
    assert lines[0] == "t,in_t,in_h,out_t,out_h,vent,circ,mist,win"
    assert lines[1] == "1000,24.0,55,15.0,80,1,0,0,1"
    assert lines[2] == "1060,,,15.5,79,0,0,0,0"  # None sensor -> empty cells


def test_events_csv():
    st, ct, body = W.route("GET", "/events.csv", FakeActions())
    assert st == 200 and ct == "text/csv"
    lines = body.strip().split("\n")
    assert lines[0] == "t,src,dev,act,in_t,in_h,out_t,out_h"
    assert "web,fans,OFF" in lines[1]


def test_status_has_outdoor_and_auto():
    st, ct, body = W.route("GET", "/status", FakeActions())
    d = json.loads(body)
    assert "out_temp" in d and "out_humid" in d and "auto" in d


def test_status_carries_unit_but_temp_stays_celsius():
    # /status advertises the display unit; the temp VALUE stays canonical Celsius
    # (client converts). CSV/JSON data stay Celsius too.
    st, ct, body = W.route("GET", "/status", FakeActions())
    d = json.loads(body)
    assert d["unit"] == "F"
    assert d["temp"] == 24.0  # still Celsius; not 75.2
    _, _, csv = W.route("GET", "/data.csv", FakeActions())
    assert "24.0" in csv.split("\n")[1]  # sample in_t stays Celsius


def test_auto_toggle():
    a = FakeActions()
    st, ct, body = W.route("POST", "/auto", a)
    assert st == 200
    assert json.loads(body)["auto"] is True
    assert a.calls == [("auto", None)]


def test_unknown_404():
    st, ct, body = W.route("GET", "/nope", FakeActions())
    assert st == 404


def test_settings_get():
    st, ct, body = W.route("GET", "/settings", FakeActions())
    assert st == 200 and ct == "application/json"
    d = json.loads(body)
    assert d["specs"][0]["key"] == "mist_burst_s"
    assert d["specs"][0]["value"] == 5


def test_settings_post_applies_and_reports():
    a = FakeActions()
    st, ct, body = W.route("POST", "/settings?mist_burst_s=8&bogus=1", a)
    assert st == 200
    d = json.loads(body)
    assert a.calls == [("settings", {"mist_burst_s": "8", "bogus": "1"})]
    assert d["applied"] == {"mist_burst_s": "8"}  # only known key reported applied


def test_qs_parse():
    p, params = W._qs("/window?a=stop&x=1")
    assert p == "/window" and params["a"] == "stop" and params["x"] == "1"


def test_qs_percent_decodes_values():
    _, params = W._qs("/settings?label=a%20b&sign=%2B&plus=a+b")
    assert params["label"] == "a b"  # %20 -> space
    assert params["sign"] == "+"  # %2B -> literal plus
    assert params["plus"] == "a b"  # '+' -> space


def _run_all():
    fns = [v for k, v in globals().items() if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(fns)}/{len(fns)} passed")


if __name__ == "__main__":
    _run_all()
