"""The lock view's boat sits on the water of the body it is in, never over a gate (ww-cq0)."""

import re

import pytest

from phenix_apps.apps.sceptre import lock_view as lv

NAMES = [
    "rtu-1.lowerwater.height",
    "rtu-1.lock.height",
    "rtu-2.lock.height",
    "rtu-2.upperwater.height",
    "rtu-1.lowergate.open",
    "rtu-2.uppergate.open",
    "rtu-1.boat.location",
]
IDS = {n: f"t{i}" for i, n in enumerate(NAMES)}
LOC = IDS["rtu-1.boat.location"]
GATES = {"lower": (316, 326), "upper": (574, 584)}  # gate leaf x extents
BODY_LEVEL = {
    "lower": "rtu-1.lowerwater.height",
    "chamber": "rtu-1.lock.height",
    "upper": "rtu-2.upperwater.height",
}


def _hit(actions, var, value, kind):
    """The FUXA action of this kind whose range holds value (None if none)."""

    hits = [
        a
        for a in actions
        if a["variableId"] == var
        and a["type"] == kind
        and a["range"]["min"] <= value <= a["range"]["max"]
    ]
    return hits[-1] if hits else None


def _boat(items, loc, levels):
    """Where FUXA would draw each shown boat body: {name: (left_x, hull_bottom_y)}."""

    shown = {}
    for name in BODY_LEVEL:
        acts = items[f"BOATX_{name}"]["property"]["actions"]
        visible = name == "lower"  # initial style
        for kind in ("show", "hide"):
            if _hit(acts, LOC, loc, kind):
                visible = kind == "show"
        if not visible:
            continue
        x = _hit(acts, LOC, loc, "move")["options"]["toX"]
        y_acts = items[f"BOATY_{name}"]["property"]["actions"]
        top = _hit(y_acts, IDS[BODY_LEVEL[name]], levels[name], "move")["options"][
            "toY"
        ]
        shown[name] = (x, top + 34)
    return shown


# around and exactly on both gates, plus the sim's held positions (100, 100.001, 200, 200.001)
LOCS = [0, 50, 99.9, 100, 100.001, 102.998, 114, 150, 199.9, 200, 200.001, 250, 300]
# lower/chamber/upper heights: the screenshot's, then a filling, an emptying and a full lock
LEVELS = [
    (4.99, 5.447, 15),
    (5, 5, 15),
    (5, 10.3, 15),
    (5, 14.9, 15),
    (5, 15, 15),
    (5.2, 7.7, 14.6),
]


@pytest.mark.parametrize("levels", LEVELS)
@pytest.mark.parametrize("loc", LOCS)
def test_boat_on_water_not_over_gate(loc, levels):
    items = lv.build(IDS)["items"]
    lev = dict(zip(BODY_LEVEL, levels, strict=True))
    shown = _boat(items, loc, lev)
    assert len(shown) == 1, (loc, shown)  # exactly one body at any location
    ((name, (x, bottom)),) = shown.items()
    surface = lv.YB - lv.PXL * lev[name]
    # the hull is in the water, within a level step (plus the draft) of the surface
    assert surface <= bottom <= surface + lv.PXL * lv.LVL_STEP + 12, (
        loc,
        name,
        bottom,
        surface,
    )
    # sim zones: <=100 lower, <=200 chamber; held-moving-down positions are just past the gate
    want = "lower" if loc <= 100 else "chamber" if loc <= 200 else "upper"
    assert name == want or loc in (100.001, 200.001)
    for g0, g1 in GATES.values():
        assert x + lv.BW <= g0 or x >= g1, (loc, name, x)  # never over a gate leaf


def test_missing_tags_still_build():
    assert lv.build({})["items"] == {}


def test_valve_flow_arrows_point_downstream():
    """Water runs from the upper pool to the lower pool, so every flow arrow head is left of its tail."""
    names = [*NAMES, "rtu-1.lowervalve.open", "rtu-2.uppervalve.open"]
    svg = lv.build({n: f"t{i}" for i, n in enumerate(names)})["svg"]
    flows = re.findall(r"id='FLOW_[^']*'.*?</g>", svg)
    assert len(flows) == 2
    for flow in flows:
        polys = re.findall(r"points='([^']*)'", flow)
        assert len(polys) == 2
        for pts in polys:
            xs = [float(p.split(",")[0]) for p in pts.split()]
            tail, head = xs[0], xs[3]
            assert head < tail
