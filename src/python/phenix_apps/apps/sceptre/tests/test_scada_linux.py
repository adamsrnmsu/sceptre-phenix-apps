"""Tests for the Linux (linux_fuxa) config generators."""

import json
import tomllib
from types import SimpleNamespace

import pytest

from phenix_apps.apps.sceptre import lock_view as lv
from phenix_apps.apps.sceptre import scada_linux
from phenix_apps.common.error import AppError


def reg(dev, field, regtype, addr):
    return SimpleNamespace(devname=dev, field=field, regtype=regtype, addr=addr)


def opc(*devices, protocol="modbus"):
    """A stand-in for configs.OpcConfig: one channel holding these devices."""

    channel = SimpleNamespace(protocol=protocol, devices=list(devices))
    return SimpleNamespace(channel_list=[channel])


def rtu(name, ip, tags, range_=(0, 1000)):
    return SimpleNamespace(fd_name=name, fd_ip=ip, range=range_, tags=tags)


@pytest.fixture
def waterway():
    return opc(
        rtu(
            "rtu-2",
            "10.1.1.102",
            [reg("uppergate", "open", "holding-register", 40000)],
        ),
        rtu(
            "rtu-1",
            "10.1.1.101",
            [
                reg("lock", "height", "input-register", 30001),
                reg("lowergate", "open", "input-register", 30002),
                reg("lowergate", "open", "holding-register", 40000),
                reg("boat", "location", "input-register", 30003),
            ],
        ),
    )


class TestGatewayConfig:
    def test_top_level_keys(self, waterway):
        gw = scada_linux.gateway_config(waterway)

        assert gw["opc_endpoint"] == "opc.tcp://0.0.0.0:4840"
        assert gw["poll_interval"] == 1.0
        assert gw["scale"] == [0, 1000]

    def test_rtus_and_points_are_sorted(self, waterway):
        gw = scada_linux.gateway_config(waterway)

        assert [r["name"] for r in gw["rtus"]] == ["rtu-1", "rtu-2"]
        assert [p["node"] for p in gw["rtus"][0]["points"]] == [
            "rtu-1.boat.location",
            "rtu-1.lock.height",
            "rtu-1.lowergate.open",
        ]
        assert gw["rtus"][0]["host"] == "10.1.1.101"

    def test_input_and_holding_registers_merge_into_one_node(self, waterway):
        points = scada_linux.gateway_config(waterway)["rtus"][0]["points"]
        gate = next(p for p in points if p["node"] == "rtu-1.lowergate.open")

        assert gate["read"] == {"type": "input-register", "address": 30002}
        assert gate["write"] == {"type": "holding-register", "address": 40000}

    def test_read_only_point_has_no_write(self, waterway):
        points = scada_linux.gateway_config(waterway)["rtus"][0]["points"]

        assert (
            next(p for p in points if p["node"].endswith("boat.location"))["write"]
            is None
        )

    def test_holding_only_point_reads_back_from_the_holding_register(self, waterway):
        pt = scada_linux.gateway_config(waterway)["rtus"][1]["points"][0]

        assert (
            pt["read"] == pt["write"] == {"type": "holding-register", "address": 40000}
        )

    def test_points_match_the_gateway_nodes(self, waterway):
        assert [p.node for p in scada_linux.points(waterway)] == [
            "rtu-1.boat.location",
            "rtu-1.lock.height",
            "rtu-1.lowergate.open",
            "rtu-2.uppergate.open",
        ]
        assert scada_linux.points(waterway)[1].device == "lock"

    @pytest.mark.parametrize("regtype", ["discrete-input", "coil"])
    def test_unsupported_register_type_is_an_error(self, regtype):
        config = opc(rtu("rtu-1", "10.1.1.101", [reg("d", "f", regtype, 1)]))

        with pytest.raises(AppError, match=regtype):
            scada_linux.gateway_config(config)

    def test_non_modbus_protocol_is_an_error(self):
        config = opc(rtu("rtu-1", "10.1.1.101", []), protocol="dnp3")

        with pytest.raises(AppError, match="dnp3"):
            scada_linux.gateway_config(config)

    def test_differing_ranges_are_an_error(self):
        config = opc(
            rtu("rtu-1", "10.1.1.101", [], (0, 1000)),
            rtu("rtu-2", "10.1.1.102", [], (0, 1)),
        )

        with pytest.raises(AppError, match="one scale"):
            scada_linux.gateway_config(config)


POINTS = [
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
]


def project(names, hmi_view="waterway-lock", name="sceptre"):
    pts = [scada_linux.Point(*n.split(".")) for n in names]
    ids = {n: f"t{i}" for i, n in enumerate(names, 1)}
    text = scada_linux.fuxa_project("opc.tcp://10.1.2.50:4840", pts, name, hmi_view)
    return json.loads(text), ids


class TestFuxaProject:
    """Ported from the range's scada/test_fuxa_project.py."""

    def test_opc_device_and_tags(self):
        p, _ = project(POINTS)
        device = p["devices"]["d_opc"]

        assert device["type"] == "OPCUA"
        assert device["property"]["address"] == "opc.tcp://10.1.2.50:4840"
        assert device["tags"]["t1"]["address"] == "ns=2;s=rtu-1.lowerwater.height"
        assert device["tags"]["t1"]["name"] == "rtu-1.lowerwater.height"

    def test_view_items_reference_real_tags_and_svg_ids(self):
        p, _ = project(POINTS)
        tags = p["devices"]["d_opc"]["tags"]
        view = p["hmi"]["views"][0]

        for key, item in view["items"].items():
            assert f"id='{key}'" in view["svgcontent"], key
            refs = [item["property"].get("variableId")] + [
                a["variableId"] for a in item["property"].get("actions", [])
            ]
            for ref in filter(None, refs):
                assert ref in tags, (key, ref)

    def test_animated_items_exist(self):
        p, _ = project(POINTS)

        assert {
            "GXP_lower",
            "GXP_chamber",
            "GXP_upper",
            "GATE_lower",
            "GATE_upper",
            "VALVE_lower",
            "VALVE_upper",
            "BOATX_lower",
            "BOATX_chamber",
            "BOATX_upper",
            "BOATY_chamber",
        } <= set(p["hmi"]["views"][0]["items"])

    def test_boat_follows_location_and_level(self):
        p, ids = project(POINTS)
        items = p["hmi"]["views"][0]["items"]

        bx = items["BOATX_chamber"]["property"]["actions"]
        assert {a["variableId"] for a in bx} == {ids["rtu-1.boat.location"]}
        by = items["BOATY_chamber"]["property"]["actions"]
        assert {a["variableId"] for a in by} == {ids["rtu-1.lock.height"]}
        xs = [a["options"]["toX"] for a in bx if a["type"] == "move"]
        assert xs == sorted(xs)

    def test_unset_view_picks_the_lock_when_its_tags_exist(self):
        p, _ = project(POINTS, hmi_view=None)
        view = p["hmi"]["views"][0]

        assert view["name"] == "Lock"
        assert any(k.startswith("BOAT") for k in view["items"])

    def test_unset_view_is_plain_when_a_lock_tag_is_missing(self):
        for missing in lv.LOCK_TAGS:
            names = [n for n in POINTS if n != missing]
            p, _ = project(names, hmi_view=None)
            view = p["hmi"]["views"][0]

            assert view["name"] == "Tags", missing
            assert not any(k.startswith(("BOAT", "GATE")) for k in view["items"])

    def test_plain_forces_a_plain_table_of_every_tag(self):
        p, _ = project(POINTS, hmi_view="plain")
        view = p["hmi"]["views"][0]

        assert set(view["items"]) == {f"VAL_{n}" for n in POINTS}
        assert not any(k.startswith(("BOAT", "GATE")) for k in view["items"])
        assert "Waterway" not in view["svgcontent"]
        assert p["name"] == "sceptre"

    def test_plain_view_widens_for_many_tags(self):
        names = [f"rtu-1.d{i}.f" for i in range(100)]
        p, _ = project(names, hmi_view=None)

        assert len(p["hmi"]["views"][0]["items"]) == 100
        assert p["hmi"]["views"][0]["profile"]["width"] > 1280

    def test_unknown_view_is_an_error(self):
        with pytest.raises(AppError, match="unknown hmi_view"):
            project(POINTS, hmi_view="nope")

    @pytest.mark.parametrize("view", [None, "waterway-lock"])
    def test_quote_and_backslash_in_names_stay_valid_json(self, view):
        node = 'rtu-1.dev"ice.fi\\eld'
        p, _ = project([node], hmi_view=view, name='pro"j\\x')

        assert p["name"] == 'pro"j\\x'
        assert p["devices"]["d_opc"]["tags"]["t1"]["name"] == node
        assert p["devices"]["d_opc"]["tags"]["t1"]["address"] == f"ns=2;s={node}"

    def test_endpoint_is_escaped(self):
        pts = [scada_linux.Point("rtu-1", "d", "f")]
        text = scada_linux.fuxa_project('opc.tcp://a"b\\c:4840', pts)

        assert json.loads(text)["devices"]["d_opc"]["property"]["address"] == (
            'opc.tcp://a"b\\c:4840'
        )

    def test_no_boat_tags_means_no_boat_items(self):
        p, _ = project([n for n in POINTS if ".boat." not in n])

        assert not any(k.startswith("BOAT") for k in p["hmi"]["views"][0]["items"])

    def test_no_points_still_renders(self):
        p, _ = project([])

        assert p["devices"]["d_opc"]["tags"] == {}


TELEGRAF_PTS = [
    scada_linux.Point("rtu-1", "boat", "location"),
    scada_linux.Point("rtu-2", "uppergate", "open"),
]


class TestHistorianAndEngineer:
    def test_telegraf_reads_every_node_from_the_gateway(self):
        conf = tomllib.loads(scada_linux.telegraf_conf("10.1.2.50", TELEGRAF_PTS))
        opcua = conf["inputs"]["opcua"][0]

        assert opcua["endpoint"] == "opc.tcp://10.1.2.50:4840"
        assert [n["identifier"] for n in opcua["nodes"]] == [
            "rtu-1.boat.location",
            "rtu-2.uppergate.open",
        ]
        assert opcua["nodes"][0]["default_tags"] == {
            "rtu": "rtu-1",
            "device": "boat",
            "field": "location",
        }
        assert conf["outputs"]["influxdb_v2"][0] == {
            "urls": ["http://127.0.0.1:8086"],
            "token": "sceptre-historian-token",
            "organization": "sceptre",
            "bucket": "sceptre",
        }

    def test_influx_setup_and_telegraf_agree_on_the_defaults(self):
        script = scada_linux.influx_setup()
        out = tomllib.loads(scada_linux.telegraf_conf("10.1.2.50", TELEGRAF_PTS))[
            "outputs"
        ]["influxdb_v2"][0]

        assert f"INFLUX_ORG={out['organization']}\n" in script
        assert f"INFLUX_BUCKET={out['bucket']}\n" in script
        assert f"INFLUX_TOKEN={out['token']}\n" in script

    def test_custom_influx_values_reach_both_files(self):
        script = scada_linux.influx_setup("lab", "plant", "tok en")
        conf = scada_linux.telegraf_conf("10.1.2.50", [], "lab", "plant", 'tok"en')

        assert "INFLUX_TOKEN='tok en'\n" in script
        assert tomllib.loads(conf)["outputs"]["influxdb_v2"][0]["token"] == 'tok"en'

    def test_hmi_url_and_rtus(self):
        assert scada_linux.hmi_url("10.1.2.71") == "http://10.1.2.71:1881/\n"
        assert (
            scada_linux.rtus_txt({"rtu-2": "10.1.1.102", "rtu-1": "10.1.1.101"})
            == "rtu-1 10.1.1.101\nrtu-2 10.1.1.102\n"
        )


def test_influx_setup_keeps_its_line_continuation():
    """A trailing backslash in the template is a mako continuation, not output."""

    script = scada_linux.influx_setup()

    assert '--password "$INFLUX_PASS" \\\n     --org "$INFLUX_ORG"' in script
