"""Bash-free checks for the provider-neutral `--model` head flag
(lib/launch.py): parse, mapping, the models allowlist and the refusal
grammar — including the CLI-declared allowlist no shipped CLI uses yet.

    python3 tests/py/model_checks.py            (any OS; no bash, no network)

Prints one `ok <name>` / `FAIL <name>: <why>` line per check and exits 1 when
any check failed, so a scope folds the lines in and Windows CI runs it
natively.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "lib"))

import launch                       # noqa: E402
from common import AkError          # noqa: E402

RESULTS = []


def check(name, fn):
    try:
        fn()
        RESULTS.append(("ok %s" % name, True))
    except AssertionError as exc:
        RESULTS.append(("FAIL %s: %s" % (name, exc), False))
    except AkError as exc:
        RESULTS.append(("FAIL %s: raised %s" % (name, exc), False))


def cli(**extra):
    base = {"executable": "fake", "session": {}}
    base.update(extra)
    return base


def parses_model():
    head = launch.parse_head(cli(), ["--model", "sonnet"], {})
    assert head.model == "sonnet", head.model
    assert head.rest == [], head.rest


def model_needs_a_value():
    try:
        launch.parse_head(cli(), ["--model"], {})
    except AkError:
        return
    raise AssertionError("bare --model accepted")


def dash_leading_value_refused():
    try:
        launch.parse_head(cli(), ["--model", "-p"], {})
    except AkError:
        return
    raise AssertionError("dash-leading model accepted")


def model_twice_refused():
    try:
        launch.parse_head(cli(), ["--model", "a", "--model", "b"], {})
    except AkError:
        return
    raise AssertionError("double --model accepted")


def after_passthrough_untouched():
    # After `--` the CLI reads its own arguments: ak stops parsing the head.
    head = launch.parse_head(cli(), ["--", "--model", "x"], {})
    assert head.model is None, head.model
    assert head.rest == ["--model", "x"], head.rest


def allowlist_accepts_and_refuses():
    # No shipped CLI declares `models` yet; the mechanism must still work the
    # day one does — accept a listed value, refuse anything else.
    c = cli(model_flag="-m", models=["gpt-x", "gpt-y"])
    head = launch.parse_head(c, ["--model", "gpt-x"], {})
    assert head.model == "gpt-x", head.model
    try:
        launch.parse_head(c, ["--model", "gpt-z"], {})
    except AkError:
        return
    raise AssertionError("unlisted model accepted under a models allowlist")


check("model: the head flag parses with its value", parses_model)
check("model: a bare --model is refused", model_needs_a_value)
check("model: a dash-leading value is refused", dash_leading_value_refused)
check("model: --model twice is refused", model_twice_refused)
check("model: after -- the CLI's own arguments are untouched", after_passthrough_untouched)
check("model: a models allowlist accepts its values and refuses the rest", allowlist_accepts_and_refuses)

for line, _ in RESULTS:
    print(line)
sys.exit(0 if all(ok for _, ok in RESULTS) else 1)
