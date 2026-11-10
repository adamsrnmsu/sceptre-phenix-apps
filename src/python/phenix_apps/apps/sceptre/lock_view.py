"""Animated lock process view for FUXA 1.3.1 (items + SVG). build(tag_ids) -> {"items": {...}, "svg": "<svg ...>"}.

tag_ids maps "<rtu>.<point>" -> FUXA tag id ("t7"). Elements whose tag is absent are skipped, so a partial register map
still renders. Only FUXA's own item types are used: svg-ext-gauge_progress (water fill), svg-ext-shapes with actions
move / show / hide / blink + colour ranges, svg-ext-value (table). FUXA's `move` action is discrete (value in range ->
animate to absolute toX,toY), so continuous quantities are stepped (boat x every 5 m, boat y every 1.0 level unit).
"""

import html

SRC = "d_opc"
LVL_MAX = 20.0  # level range of the water heights
LOC_MAX = 300.0  # boat.location range (m); lower gate at 100, upper gate at 200
G1, G2 = 100.0, 200.0
X0, PXM = (
    60,
    2.6,
)  # location -> pixel: x = X0 + loc * PXM  (gates at 320 / 580, end at 840)
YB, PXL = 470, 12  # water bottom pixel / pixels per level unit (level 20 -> y 230)
TOP = YB - int(PXL * 20)  # 230
BW = 64  # boat width
LOC_STEP, LVL_STEP = 5, 0.5
EPS = 5e-4  # window gap: the boat held at a closed gate sits at G1 (lower side) or G1 + 1e-3 (chamber side)
# left-edge x limits of the boat in each body, so it never overlaps a gate leaf (lower gate x 316, upper gate x 574)
X_LIMITS = {"lower": (None, 316 - BW), "chamber": (326, 574 - BW), "upper": (584, None)}
# ms; move animation duration. FUXA runs SVG.adopt(el).animate(duration).move() on every value update and svg.js
# queues animations, so a duration at or above the 1 s OPC poll builds a backlog and the boat lags the water (ww-8ve).
DUR = 600
BIG = 1e6

# (title, level tag, x, width) of the three water bodies
BODIES = [
    ("lower", "rtu-1.lowerwater.height", 60, 260),
    ("chamber", "rtu-1.lock.height", 326, 248),
    ("upper", "rtu-2.upperwater.height", 584, 256),
]
TABLE = [
    "rtu-1.lowerwater.height",
    "rtu-1.lock.height",
    "rtu-2.lock.height",
    "rtu-2.upperwater.height",
    "rtu-1.lowergate.open",
    "rtu-2.uppergate.open",
    "rtu-1.lowervalve.open",
    "rtu-2.uppervalve.open",
    "rtu-1.boat.location",
    "rtu-1.boat.direction",
    "rtu-1.lowersensor.active",
    "rtu-1.locksensor.active",
    "rtu-2.uppersensor.active",
    "rtu-1.lowersensor.direction",
    "rtu-1.locksensor.direction",
    "rtu-2.uppersensor.direction",
]

DEFAULT_LEVEL = {"lower": 5, "chamber": 5, "upper": 15}
WATER, WATER_DK = "#4a90d9", "#2c5f94"
OPEN_C, SHUT_C = "#2e9e4f", "#d03a3a"


class View:
    def __init__(self, tag_ids):
        self.t, self.items, self.svg = tag_ids, {}, []

    def has(self, *names):
        return all(n in self.t for n in names)

    def _prop(self, var=None, actions=(), ranges=()):
        p = {
            "events": [],
            "actions": list(actions),
            "ranges": list(ranges),
            "alarmId": "",
            "alarmSrc": "",
            "alarm": "",
            "alarmColor": "",
        }
        if var:
            p.update(variable=var, variableId=self.t[var], variableSrc=SRC)
        return p

    def act(self, var, kind, lo, hi, **opts):
        a = {
            "variableId": self.t[var],
            "variableSrc": SRC,
            "bitmask": None,
            "range": {"min": lo, "max": hi},
            "type": kind,
        }
        a["options"] = opts
        return a

    def shape(
        self, iid, markup, actions=(), var=None, ranges=(), tag="g", style="", attrs=""
    ):
        """Add a svg-ext-shapes item wrapping `markup` in <tag id=iid>."""
        self.items[iid] = {
            "id": iid,
            "type": "svg-ext-shapes",
            "name": iid,
            "label": "Shapes",
            "property": self._prop(var, actions, ranges),
        }
        self.svg.append(
            f"<{tag} id='{iid}' type='svg-ext-shapes' style='{style}' {attrs}>{markup}</{tag}>"
        )

    def static(self, markup):
        self.svg.append(markup)

    def text(
        self, x, y, s, size=14, fill="#222", anchor="start", weight="normal", extra=""
    ):
        return (
            f"<text x='{x}' y='{y}' font-size='{size}' font-family='sans-serif' fill='{fill}' text-anchor='{anchor}' "
            f"font-weight='{weight}' {extra}>{html.escape(s)}</text>"
        )

    def table(self, names, x, ty, title, w=350):
        """A titled box of live values, one row per tag in names (skipping unknown tags), top-left at (x, ty - 24)."""
        names = [n for n in names if n in self.t]
        self.static(
            f"<rect x='{x}' y='{ty - 24}' width='{w}' height='{34 + 20 * len(names)}' rx='6' fill='#fff' stroke='#c6d0da'/>"
        )
        self.static(self.text(x + 12, ty - 6, title, 15, "#16324f", "start", "bold"))
        for row, n in enumerate(names):
            y = ty + 20 + row * 20
            iid = f"VAL_{n}"
            self.items[iid] = {
                "id": iid,
                "type": "svg-ext-value",
                "name": n,
                "label": "Value",
                "property": {
                    "events": [],
                    "variable": n,
                    "variableId": self.t[n],
                    "variableSrc": SRC,
                    "alarmId": "",
                    "alarmSrc": "",
                    "alarm": "",
                    "alarmColor": "",
                    "ranges": [{"type": "unit", "min": 0, "max": 1000000, "text": ""}],
                },
            }
            q = html.escape(n)
            self.static(self.text(x + 12, y, n, 13, "#3f4a55"))
            self.static(
                f"<g id='{html.escape(iid)}' type='svg-ext-value' text-anchor='end' font-family='sans-serif' font-size='13' fill='none' "
                f"stroke-width='0'><text id='VALT_{q}' x='{x + w - 14}' y='{y}' text-anchor='end' font-family='sans-serif' font-size='13' "
                f"fill='#000' stroke-width='0'>##.##</text></g>"
            )

    # ---- elements --------------------------------------------------------------------------------------------------
    def water(self, name, var, x, w):
        iid = f"GXP_{name}"
        self.items[iid] = {
            "id": iid,
            "type": "svg-ext-gauge_progress",
            "name": var,
            "label": "HtmlProgress",
            "property": {
                "events": [],
                "alarmId": "",
                "alarmSrc": "",
                "alarm": "",
                "alarmColor": "",
                "ranges": [
                    {
                        "type": "minmax",
                        "min": 0,
                        "max": str(int(LVL_MAX)),
                        "style": [True, True],
                        "color": WATER,
                    }
                ],
                "variable": var,
                "variableId": self.t[var],
                "variableSrc": SRC,
            },
        }
        top = YB - PXL * LVL_MAX
        h = YB - top
        self.svg.append(
            f"<g id='{iid}' type='svg-ext-gauge_progress' font-family='sans-serif' font-size='14' stroke='null'>"
            f"<rect id='A-{iid}' fill='#e9f1f8' x='{x}' y='{top}' width='{w}' height='{h}' stroke='null'/>"
            f"<rect id='B-{iid}' fill='{WATER}' x='{x}' y='{top + h / 2}' width='{w}' height='{h / 2}' stroke='null'/>"
            f"<foreignObject id='H-{iid}' font-size='14' x='{x}' y='{top}' width='{w}' height='{h}'/></g>"
        )

    def gate(self, name, var, x, label):
        """Gate leaf: closed spans TOP-10..YB, open -> sunk into the floor. Floor is drawn later, on top."""
        acts = [
            self.act(var, "move", 0.5, BIG, toX=x, toY=YB, duration=1200),
            self.act(var, "move", -BIG, 0.4999, toX=x, toY=TOP - 10, duration=1200),
        ]
        self.shape(
            f"GATE_{name}",
            f"<rect x='{x}' y='{TOP - 10}' width='10' height='{YB - TOP + 10}' fill='#8a5a2b' stroke='#222'/>",
            acts,
            tag="g",
        )
        # status labels
        cx = x + 5
        self.static(self.text(cx, TOP - 52, label, 13, "#222", "middle", "bold"))
        self.shape(
            f"GATEO_{name}",
            self.text(cx, TOP - 36, "OPEN", 13, OPEN_C, "middle", "bold"),
            [self.act(var, "show", 0.5, BIG), self.act(var, "hide", -BIG, 0.4999)],
            style="display:none",
        )
        self.shape(
            f"GATEC_{name}",
            self.text(cx, TOP - 36, "CLOSED", 13, SHUT_C, "middle", "bold"),
            [self.act(var, "show", -BIG, 0.4999), self.act(var, "hide", 0.5, BIG)],
        )

    def valve(self, name, var, x0, x1, label, lab_x):
        """Culvert under the floor between a pool and the chamber, with a bow-tie valve and flow arrows."""
        mx, y = (x0 + x1) // 2, YB + 42
        pipe = f"<rect x='{x0}' y='{y - 9}' width='{x1 - x0}' height='18'/>"  # fill comes from the g (FUXA range colour)

        def rng():
            return [
                {
                    "type": "range",
                    "min": -BIG,
                    "max": 0.4999,
                    "color": "#cfd8dc",
                    "stroke": "#222",
                },
                {
                    "type": "range",
                    "min": 0.5,
                    "max": BIG,
                    "color": WATER,
                    "stroke": "#222",
                },
            ]

        self.shape(
            f"PIPE_{name}",
            pipe,
            var=var,
            ranges=rng(),
            attrs="fill='#cfd8dc' stroke='#222'",
        )
        self.static(
            f"<rect x='{x0}' y='{YB}' width='10' height='{y - 9 - YB}' fill='#cfd8dc' stroke='#222'/>"
            f"<rect x='{x1 - 10}' y='{YB}' width='10' height='{y - 9 - YB}' fill='#cfd8dc' stroke='#222'/>"
        )
        bow = f"<polygon points='{mx - 12},{y - 12} {mx + 12},{y + 12} {mx + 12},{y - 12} {mx - 12},{y + 12}'/>"
        rngv = [
            {
                "type": "range",
                "min": -BIG,
                "max": 0.4999,
                "color": SHUT_C,
                "stroke": "#222",
            },
            {
                "type": "range",
                "min": 0.5,
                "max": BIG,
                "color": OPEN_C,
                "stroke": "#222",
            },
        ]
        self.shape(
            f"VALVE_{name}",
            bow,
            var=var,
            ranges=rngv,
            attrs=f"fill='{SHUT_C}' stroke='#222'",
        )
        # Water in a lock only ever runs downstream (right to left here): the upper valve fills the chamber
        # from the upper pool, the lower valve drains it into the lower pool. So the arrows point left.
        arrows = (
            f"<polygon points='{mx - 18},{y - 5} {x0 + 14},{y - 5} {x0 + 14},{y - 9} {x0 + 4},{y} {x0 + 14},{y + 9} "
            f"{x0 + 14},{y + 5} {mx - 18},{y + 5}' fill='#fff' stroke='none' opacity='0.9'/>"
            f"<polygon points='{x1 - 14},{y - 5} {mx + 18},{y - 5} {mx + 18},{y - 9} {mx + 8},{y} {mx + 18},{y + 9} "
            f"{mx + 18},{y + 5} {x1 - 14},{y + 5}' fill='#fff' stroke='none' opacity='0.9'/>"
        )
        self.shape(
            f"FLOW_{name}",
            arrows,
            [
                self.act(var, "show", 0.5, BIG),
                self.act(
                    var,
                    "blink",
                    0.5,
                    BIG,
                    fillA="#ffffff",
                    strokeA="none",
                    fillB="#8ec5ff",
                    strokeB="none",
                    interval=600,
                ),
                self.act(var, "hide", -BIG, 0.4999),
            ],
            style="display:none",
        )
        self.static(self.text(lab_x, YB + 90, label, 13, "#fff", "middle", "bold"))
        self.shape(
            f"VALO_{name}",
            self.text(lab_x, YB + 107, "OPEN", 13, "#7fe39c", "middle", "bold"),
            [self.act(var, "show", 0.5, BIG), self.act(var, "hide", -BIG, 0.4999)],
            style="display:none",
        )
        self.shape(
            f"VALC_{name}",
            self.text(lab_x, YB + 107, "CLOSED", 13, "#ff8a8a", "middle", "bold"),
            [self.act(var, "show", -BIG, 0.4999), self.act(var, "hide", 0.5, BIG)],
        )

    @staticmethod
    def clamp_x(name, x):
        lo, hi = X_LIMITS[name]
        if lo is not None:
            x = max(x, lo)
        if hi is not None:
            x = min(x, hi)
        return x

    def boat_xy(self, name, lo_m, hi_m, level_var):
        """One boat per water body: outer group steps in x with boat.location, inner group steps in y with that body's level.
        Visible only while the boat is inside the body (lower <=100 < chamber <=200 < upper)."""
        loc = "rtu-1.boat.location"
        hull = (
            "<polygon points='0,18 64,18 56,34 8,34' fill='#b23b2e' stroke='#222'/>"
            "<rect x='20' y='4' width='26' height='14' fill='#f2f2f2' stroke='#222'/>"
            "<rect x='24' y='8' width='6' height='6' fill='#4a90d9'/><rect x='34' y='8' width='6' height='6' fill='#4a90d9'/>"
            "<rect x='44' y='0' width='3' height='18' fill='#222'/>"
        )
        # y: top of boat = water top - 22 ; x: centre on location
        ylev = []
        n = int(LVL_MAX / LVL_STEP)
        for k in range(n + 1):
            lo = -BIG if k == 0 else k * LVL_STEP - LVL_STEP / 2
            hi = BIG if k == n else k * LVL_STEP + LVL_STEP / 2 - 1e-4
            ylev.append(
                self.act(
                    level_var,
                    "move",
                    lo,
                    hi,
                    toX=0,
                    toY=YB - PXL * k * LVL_STEP - 22,
                    duration=DUR,
                )
            )
        xloc = []
        a, b = int(lo_m), int(hi_m)
        for m in range(a, b + 1, LOC_STEP):
            lo = -BIG if m == a else m - LOC_STEP / 2
            hi = BIG if m + LOC_STEP > b else m + LOC_STEP / 2 - 1e-4
            xloc.append(
                self.act(
                    loc,
                    "move",
                    lo,
                    hi,
                    toX=self.clamp_x(name, round(X0 + m * PXM - BW / 2)),
                    toY=0,
                    duration=DUR,
                )
            )
        # show window per body (location ranges); gates themselves belong to the neighbouring pool
        # boundaries follow the sim's zones: a boat at exactly a gate is on the lower side (<= gate), and one held there
        # moving down is at gate + 1e-3 (chamber / upper side); exactly one body is shown for any location
        shows = {
            "lower": (-BIG, G1),
            "chamber": (G1 + EPS, G2),
            "upper": (G2 + EPS, BIG),
        }[name]
        hides = {
            "lower": [(G1 + EPS, BIG)],
            "chamber": [(-BIG, G1), (G2 + EPS, BIG)],
            "upper": [(-BIG, G2)],
        }[name]
        outer_acts = (
            [self.act(loc, "show", *shows)]
            + [self.act(loc, "hide", *h) for h in hides]
            + xloc
        )
        # FUXA's move() on a <g> rewrites its children's coordinates from the bbox, so two groups moving in x and y fight each
        # other. Nested <svg> viewports move by plain x/y attributes: outer.x follows location, inner.y follows the level.
        y0 = YB - round(PXL * DEFAULT_LEVEL[name]) - 22  # until the first level update
        inner = f"<svg id='BOATY_{name}' type='svg-ext-shapes' x='0' y='{y0}' width='{BW}' height='34' overflow='visible'>{hull}</svg>"
        self.items[f"BOATY_{name}"] = {
            "id": f"BOATY_{name}",
            "type": "svg-ext-shapes",
            "name": f"BOATY_{name}",
            "label": "Shapes",
            "property": self._prop(None, ylev),
        }
        self.items[f"BOATX_{name}"] = {
            "id": f"BOATX_{name}",
            "type": "svg-ext-shapes",
            "name": f"BOATX_{name}",
            "label": "Shapes",
            "property": self._prop(None, outer_acts),
        }
        style = "" if name == "lower" else "display:none"
        self.svg.append(
            f"<svg id='BOATX_{name}' type='svg-ext-shapes' x='0' y='0' width='{BW}' height='34' overflow='visible' "
            f"style='{style}'>{inner}</svg>"
        )


def build(tag_ids):
    v = View(tag_ids)
    s = v.static
    top = TOP
    # background + title
    s("<rect x='0' y='0' width='1280' height='720' fill='#f4f6f8'/>")
    s(
        v.text(
            40, 40, "Waterway Lock - live process view", 26, "#16324f", "start", "bold"
        )
    )
    s(v.text(40, 62, "OPC UA via scada-server (polled 1 s)", 13, "#5a6b7b"))
    # side basin walls (behind everything)
    s(
        f"<rect x='40' y='{top - 30}' width='20' height='{YB - top + 30}' fill='#6b6f73'/>"
        f"<rect x='840' y='{top - 30}' width='20' height='{YB - top + 30}' fill='#6b6f73'/>"
    )
    # level ruler
    for lv in (0, 5, 10, 15, 20):
        y = YB - PXL * lv
        s(
            f"<line x1='62' y1='{y}' x2='838' y2='{y}' stroke='#b9c4cf' stroke-dasharray='3 5'/>"
        )
        s(v.text(34, y + 4, str(lv), 11, "#5a6b7b", "end"))
    for name, var, x, w in BODIES:
        if var in tag_ids:
            v.water(name, var, x, w)
    # pool captions inside the water bodies
    for cap, cx in (("LOWER POOL", 190), ("LOCK CHAMBER", 450), ("UPPER POOL", 712)):
        s(v.text(cx, top + 22, cap, 15, "#16324f", "middle", "bold"))
    if v.has("rtu-1.lowergate.open"):
        v.gate("lower", "rtu-1.lowergate.open", 316, "LOWER GATE")
    if v.has("rtu-2.uppergate.open"):
        v.gate("upper", "rtu-2.uppergate.open", 574, "UPPER GATE")
    # gate guide posts
    for px in (310, 326, 568, 584):
        s(
            f"<rect x='{px}' y='{top - 30}' width='6' height='{YB - top + 30}' fill='#3d4348'/>"
        )
    # boats (above water + gates)
    if v.has("rtu-1.boat.location"):
        for (name, var, _x, _w), (lo, hi) in zip(
            BODIES, ((0, G1), (G1, G2), (G2, LOC_MAX)), strict=True
        ):
            if var in tag_ids:
                v.boat_xy(name, lo, hi, var)
    # floor + ground strip (hides the sunk gate leaves), culverts
    s(f"<rect x='40' y='{YB}' width='820' height='250' fill='#4b4f53'/>")
    if v.has("rtu-1.lowervalve.open"):
        v.valve("lower", "rtu-1.lowervalve.open", 250, 400, "LOWER VALVE", 325)
    if v.has("rtu-2.uppervalve.open"):
        v.valve("upper", "rtu-2.uppervalve.open", 500, 650, "UPPER VALVE", 575)
    ty = 100
    v.table(TABLE, 900, ty, "Telemetry")
    # legend (bottom strip, on the dark ground)
    ly = YB + 152
    s(
        f"<rect x='60' y='{ly - 11}' width='14' height='14' fill='{WATER}'/>"
        + v.text(80, ly, "water (fill = level 0-20)", 12, "#fff")
    )
    s(
        f"<rect x='260' y='{ly - 11}' width='10' height='14' fill='#8a5a2b'/>"
        + v.text(278, ly, "gate (up = closed, sunk = open)", 12, "#fff")
    )
    s(
        f"<polygon points='520,{ly - 11} 536,{ly + 3} 536,{ly - 11} 520,{ly + 3}' fill='{OPEN_C}'/>"
        + v.text(542, ly, "valve open", 12, "#fff")
        + f"<polygon points='620,{ly - 11} 636,{ly + 3} 636,{ly - 11} 620,{ly + 3}' fill='{SHUT_C}'/>"
        + v.text(642, ly, "closed", 12, "#fff")
    )
    s(
        f"<polygon points='700,{ly - 4} 720,{ly - 4} 716,{ly + 4} 704,{ly + 4}' fill='#b23b2e'/>"
        + v.text(726, ly, "boat (x = boat.location)", 12, "#fff")
    )
    return {
        "items": v.items,
        "svg": "<svg xmlns='http://www.w3.org/2000/svg' width='1280' height='720'>"
        + "".join(v.svg)
        + "</svg>",
        "width": 1280,
        "height": 720,
    }


ROWS, COL_W = 28, 400


def plain(tag_ids):
    """The default view: every tag's live value in a table, in columns of ROWS rows."""

    v = View(tag_ids)
    names = list(tag_ids)
    cols = max(1, -(-len(names) // ROWS))
    width = max(1280, 40 + cols * COL_W)
    v.static(f"<rect x='0' y='0' width='{width}' height='720' fill='#f4f6f8'/>")
    for c in range(cols):
        v.table(
            names[c * ROWS : (c + 1) * ROWS],
            40 + c * COL_W,
            60,
            "Tags" if c == 0 else "",
        )
    return {
        "items": v.items,
        "svg": f"<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='720'>"
        + "".join(v.svg)
        + "</svg>",
        "width": width,
        "height": 720,
    }


# metadata.hmi_view -> builder; unset means pick() decides
VIEWS = {"plain": plain, "waterway-lock": build}

# the nodes the animated lock cannot do without: a project with all of them gets it by default
LOCK_TAGS = [b[1] for b in BODIES] + [
    "rtu-1.lowergate.open",
    "rtu-2.uppergate.open",
    "rtu-1.boat.location",
]


def pick(hmi_view, names):
    """hmi_view when set, else waterway-lock if every LOCK_TAGS node is present, else plain."""
    if hmi_view:
        return hmi_view
    return "waterway-lock" if set(LOCK_TAGS) <= set(names) else "plain"
