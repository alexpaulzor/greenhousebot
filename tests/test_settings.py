"""Host tests for the pure settings store (firmware/settings.py).
python tests/test_settings.py"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "firmware"))

import settings as S  # noqa: E402


class FakeStore:
    """In-memory stand-in for FsAdapter: open(path, 'r'|'w') over a dict of files."""

    def __init__(self, files=None):
        self.files = dict(files or {})

    def open(self, path, mode):
        store = self

        class _F:
            def __init__(self, path, mode):
                self.path, self.mode = path, mode
                if "r" in mode:
                    if path not in store.files:
                        raise OSError("no such file")
                    self._buf = store.files[path]
                else:
                    self._buf = ""

            def read(self):
                return self._buf

            def write(self, s):
                self._buf += s

            def close(self):
                if "w" in self.mode:
                    store.files[self.path] = self._buf

        return _F(path, mode)

    def rename(self, src, dst):
        self.files[dst] = self.files.pop(src)


def test_defaults_match_source_modules():
    st = S.Settings()
    # sourced from control.GROWING / config, not duplicated literals
    import control as K
    import config as C

    assert st.get("growing_day_ceiling") == K.GROWING["day_ceiling"]
    assert st.get("rest_night_lo") == K.REST["night_lo"]
    assert st.get("mist_burst_s") == C.MIST_BURST_S
    assert st.get("temp_unit") == C.TEMP_UNIT


def test_specs_carry_current_value_in_order():
    st = S.Settings()
    specs = st.specs()
    assert specs[0]["key"] == "growing_day_ceiling"  # SPEC order preserved
    assert all("value" in s for s in specs)
    assert specs[0]["value"] == st.get("growing_day_ceiling")


def test_update_applies_known_keys():
    st = S.Settings()
    applied = st.update({"growing_day_ceiling": 25.5, "mist_burst_s": 8})
    assert applied == {"growing_day_ceiling": 25.5, "mist_burst_s": 8}
    assert st.get("growing_day_ceiling") == 25.5
    assert st.get("mist_burst_s") == 8


def test_update_coerces_strings():
    # web POST hands everything in as strings
    st = S.Settings()
    applied = st.update({"mist_gap_s": "45", "growing_humid_floor": "62"})
    assert applied["mist_gap_s"] == 45 and isinstance(applied["mist_gap_s"], int)
    assert applied["growing_humid_floor"] == 62


def test_update_clamps_out_of_range():
    st = S.Settings()
    applied = st.update({"heat_emergency": 999, "hard_freeze": -50})
    assert applied["heat_emergency"] == 40  # clamped to max
    assert applied["hard_freeze"] == 0  # clamped to min


def test_update_reports_only_changed_keys():
    # a no-op Save posts every field; nothing changed -> nothing applied (no flash write)
    st = S.Settings()
    same = st.as_dict()
    assert st.update(same) == {}
    # a partial edit reports only the key that actually moved
    applied = st.update({"mist_gap_s": st.get("mist_gap_s"), "mist_burst_s": 9})
    assert applied == {"mist_burst_s": 9}


def test_order_guard_reverts_inverted_day_night():
    # day_start >= night_start would make is_day() always false and disarm cooling
    st = S.Settings()
    applied = st.update({"day_start": 20, "night_start": 6})
    assert applied == {}  # both reverted
    assert st.get("day_start") == 7 and st.get("night_start") == 19
    # a change against an existing value that stays ordered is fine
    assert st.update({"day_start": 8}) == {"day_start": 8}
    # but pushing day_start past night_start snaps back, leaving the other put
    assert st.update({"day_start": 22}) == {}
    assert st.get("day_start") == 8


def test_order_guard_reverts_inverted_humidity_band():
    st = S.Settings()
    applied = st.update({"growing_humid_floor": 90, "growing_humid_ceiling": 50})
    assert applied == {}
    assert st.get("growing_humid_floor") == S.Settings().get("growing_humid_floor")


def test_update_rejects_unknown_and_junk():
    st = S.Settings()
    applied = st.update(
        {"bogus_key": 5, "mist_burst_s": "notanumber", "temp_unit": "K"}
    )
    assert applied == {}  # unknown key, bad number, bad choice all rejected
    assert st.get("temp_unit") == S.Settings().get("temp_unit")  # unchanged


def test_choice_setting():
    st = S.Settings()
    assert st.update({"temp_unit": "C"}) == {"temp_unit": "C"}
    assert st.get("temp_unit") == "C"


def test_save_then_load_round_trip():
    store = FakeStore()
    st = S.Settings()
    st.update({"growing_day_ceiling": 26.0, "temp_unit": "C"})
    st.save(store, "settings.json")

    fresh = S.Settings()
    assert fresh.get("growing_day_ceiling") != 26.0  # default first
    assert fresh.load(store, "settings.json") is True
    assert fresh.get("growing_day_ceiling") == 26.0
    assert fresh.get("temp_unit") == "C"
    # the persisted file is valid JSON of the full value set
    assert json.loads(store.files["settings.json"])["temp_unit"] == "C"


def test_save_is_atomic_via_temp_rename():
    store = FakeStore()
    st = S.Settings()
    st.update({"temp_unit": "C"})
    st.save(store, "settings.json")
    # committed to the real path, with no half-written temp file left behind
    assert "settings.json" in store.files
    assert "settings.json.tmp" not in store.files


def test_load_missing_file_keeps_defaults():
    st = S.Settings()
    assert st.load(FakeStore(), "nope.json") is False
    assert st.get("mist_burst_s") == S.Settings().get("mist_burst_s")


def test_load_corrupt_file_keeps_defaults():
    store = FakeStore({"settings.json": "{not valid json"})
    st = S.Settings()
    assert st.load(store, "settings.json") is False
    assert st.get("temp_unit") == S.Settings().get("temp_unit")


def test_load_ignores_stale_and_out_of_range_keys():
    # a settings.json written by an older/newer build, or hand-edited badly
    store = FakeStore(
        {"settings.json": json.dumps({"gone_key": 1, "mist_burst_s": 999})}
    )
    st = S.Settings()
    assert st.load(store, "settings.json") is True
    assert st.get("mist_burst_s") == 60  # clamped to max, stale key ignored


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"\n{len(fns)}/{len(fns)} passed")


if __name__ == "__main__":
    _run_all()
