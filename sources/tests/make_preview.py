"""Builds a preview of the dashboard from sample data: python3 tests/make_preview.py OUTPUT_DIR"""

from __future__ import annotations

import os
import random
import shutil
import sys
from datetime import timedelta
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

from fakes import NOW, FakeSource, sample_directory, sample_repos  # noqa: E402
from plugindash import config  # noqa: E402
from plugindash.history import History  # noqa: E402
from plugindash.output import prometheus, write_atomic, write_json  # noqa: E402
from plugindash.runner import collect  # noqa: E402


def main(out: str) -> None:
    www = os.path.join(out, "www")
    data = os.path.join(out, "data")
    shutil.rmtree(out, ignore_errors=True)
    shutil.copytree(os.path.join(os.path.dirname(HERE), "www"), www)
    cfg = config.normalise({"github_token": "x", "www_dir": www, "data_dir": data, "extensions_dir": "/nonexistent",
                            "timezone": "Australia/Brisbane"})
    status = collect(cfg, sources=[FakeSource(sample_repos())], directory=sample_directory(), now=NOW)
    status["run"]["api_calls"] = 412
    status["run"]["duration_s"] = 48.3

    # Fake 30 days of history so the strips have something to show.
    rng = random.Random(7)
    history = History(os.path.join(data, "history.sqlite"))
    for back in range(29, 0, -1):
        day = NOW - timedelta(days=back)
        statuses = {}
        for repo in status["repos"]:
            current = repo["status"]
            if current == "grey":
                value = "green" if back > 12 else "grey"
            elif current == "red":
                value = current if back < rng.randint(2, 9) else ("amber" if rng.random() < 0.3 else "green")
            elif current == "amber":
                value = current if back < rng.randint(4, 20) else "green"
            else:
                value = "amber" if rng.random() < 0.08 else "green"
            statuses[repo["full_name"]] = (value, "")
        history.record(day, day, True, None, statuses)
    history.record(NOW, NOW, True, None, {r["full_name"]: (r["status"], r["summary"]) for r in status["repos"]})

    import plugindash.history as hist_mod
    real_now = hist_mod.datetime

    class Frozen(real_now):
        @classmethod
        def now(cls, tz=None):
            return NOW

    hist_mod.datetime = Frozen
    write_json(os.path.join(www, "history.json"), history.recent(30, ZoneInfo("Australia/Brisbane")))
    hist_mod.datetime = real_now
    write_json(os.path.join(www, "status.json"), status)
    write_atomic(os.path.join(www, "metrics"), prometheus(status))
    history.close()
    print(www)


if __name__ == "__main__":
    main(sys.argv[1])
