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
            "fans": False,
            "mister": False,
            "time": 1000,
        }
        self.calls = []

    def status(self):
        return dict(self.state)

    def snapshot(self):
        return {
            "samples": [
                {"t": 1000, "in_t": 24.0, "in_h": 55, "out_t": 15.0, "out_h": 80},
                {"t": 1060, "in_t": None, "in_h": None, "out_t": 15.5, "out_h": 79},
            ],
            "events": [
                {
                    "t": 1000,
                    "src": "web",
                    "dev": "fans",
                    "act": "toggle",
                    "in_t": 24.0,
                    "in_h": 55,
                    "out_t": 15.0,
                    "out_h": 80,
                },
            ],
        }

    def window(self, a):
        self.calls.append(("window", a))
        self.state["window"] = "open" if self.state["window"] != "open" else "closed"
        return self.status()

    def fans(self, a):
        self.calls.append(("fans", a))
        self.state["fans"] = not self.state["fans"]
        return self.status()

    def mister(self, a):
        self.calls.append(("mister", a))
        self.state["mister"] = not self.state["mister"]
        return self.status()


def test_index_html():
    st, ct, body = W.route("GET", "/", FakeActions())
    assert st == 200 and ct == "text/html" and "Greenhouse" in body


def test_status_json():
    st, ct, body = W.route("GET", "/status", FakeActions())
    assert st == 200 and ct == "application/json"
    d = json.loads(body)
    assert d["temp"] == 24.0 and d["window"] == "closed"


def test_toggle_fans():
    a = FakeActions()
    st, ct, body = W.route("POST", "/fans", a)
    assert st == 200
    assert json.loads(body)["fans"] is True
    assert a.calls == [("fans", None)]


def test_explicit_action_param():
    a = FakeActions()
    W.route("POST", "/window?a=open", a)
    assert a.calls == [("window", "open")]


def test_data_snapshot():
    st, ct, body = W.route("GET", "/data", FakeActions())
    assert st == 200
    assert set(json.loads(body).keys()) == {"samples", "events"}


def test_samples_csv():
    st, ct, body = W.route("GET", "/data.csv", FakeActions())
    assert st == 200 and ct == "text/csv"
    lines = body.strip().split("\n")
    assert lines[0] == "t,in_t,in_h,out_t,out_h"
    assert lines[1] == "1000,24.0,55,15.0,80"
    assert lines[2] == "1060,,,15.5,79"  # None -> empty cells


def test_events_csv():
    st, ct, body = W.route("GET", "/events.csv", FakeActions())
    assert st == 200 and ct == "text/csv"
    lines = body.strip().split("\n")
    assert lines[0] == "t,src,dev,act,in_t,in_h,out_t,out_h"
    assert "web,fans,toggle" in lines[1]


def test_status_has_outdoor():
    st, ct, body = W.route("GET", "/status", FakeActions())
    d = json.loads(body)
    assert "out_temp" in d and "out_humid" in d


def test_unknown_404():
    st, ct, body = W.route("GET", "/nope", FakeActions())
    assert st == 404


def test_qs_parse():
    p, params = W._qs("/window?a=stop&x=1")
    assert p == "/window" and params["a"] == "stop" and params["x"] == "1"


def _run_all():
    fns = [v for k, v in globals().items() if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(fns)}/{len(fns)} passed")


if __name__ == "__main__":
    _run_all()
