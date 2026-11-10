"""Pre-start for hosts with metadata.stack: linux_fuxa.

Each role writes its own files and none of the Windows ones; a Windows host in
the same experiment keeps its files.
"""

import json
from types import SimpleNamespace

import pytest

from phenix_apps.apps.sceptre.app import Sceptre
from phenix_apps.apps.sceptre.prestart import PreStart
from phenix_apps.apps.sceptre.tests.conftest import iface, node
from phenix_apps.common.error import AppError

pytestmark = pytest.mark.app_class(cls=Sceptre, name="sceptre")

FUXA = {"stack": "linux_fuxa"}


def reg(dev, field, regtype, addr):
    return SimpleNamespace(devname=dev, field=field, regtype=regtype, addr=addr)


def fake_opc_config():
    """One modbus RTU with a gate (input + holding) and a level."""

    device = SimpleNamespace(
        fd_name="rtu-1",
        fd_ip="10.1.1.101",
        range=(0, 1000),
        tags=[
            reg("lock", "height", "input-register", 30000),
            reg("lowergate", "open", "input-register", 30001),
            reg("lowergate", "open", "holding-register", 40000),
        ],
    )
    return SimpleNamespace(
        channel_list=[SimpleNamespace(protocol="modbus", devices=[device])]
    )


@pytest.fixture
def ctx(sceptre_app):
    return PreStart(sceptre_app)


def files(path):
    return sorted(p.name for p in path.iterdir())


def lan(address):
    return [
        iface("IF0", "172.16.0.9", vlan="MGMT"),
        iface("IF1", address, vlan="scada"),
    ]


class TestOpc:
    def test_linux_opc_writes_only_the_gateway_config(self, ctx, sceptre_app):
        sceptre_app.extract_nodes_type.return_value = [
            node("opc", {"type": "opc", **FUXA}, interfaces=lan("10.1.2.50"))
        ]
        ctx.fd_server_configs = {}

        ctx.opcs()

        assert files(ctx.app.host_dir("opc")) == ["opc_gateway.json"]
        sceptre_app.render.assert_not_called()

    def test_the_opc_config_is_still_registered_for_the_hosts_that_use_it(
        self, ctx, sceptre_app
    ):
        sceptre_app.extract_nodes_type.return_value = [
            node("opc", {"type": "opc", **FUXA}, interfaces=lan("10.1.2.50"))
        ]
        ctx.fd_server_configs = {}

        ctx.opcs()

        assert list(ctx.opc_configs) == ["10.1.2.50"]

    def test_a_windows_opc_still_renders_its_windows_files(self, ctx, sceptre_app):
        sceptre_app.extract_nodes_type.return_value = [
            node("opc", {"type": "opc"}, os_type="windows", interfaces=lan("10.1.2.50"))
        ]
        ctx.fd_server_configs = {}

        ctx.opcs()

        assert [c.args[0] for c in sceptre_app.render.call_args_list] == [
            "opc_template.mako",
            "topserver.mako",
        ]
        assert files(ctx.app.host_dir("opc")) == []


class TestScadaServer:
    def test_writes_the_fuxa_project_and_url(self, ctx, sceptre_app):
        ctx.opc_configs = {"10.1.2.50": fake_opc_config()}
        ctx.scada_hosts = [
            node("scada", {"type": "scada-server", **FUXA}, interfaces=lan("10.1.2.71"))
        ]

        ctx.scada_servers()

        directory = ctx.app.host_dir("scada")
        assert files(directory) == ["fuxa_project.json", "hmi_url"]
        project = json.loads((directory / "fuxa_project.json").read_text())
        assert project["devices"]["d_opc"]["property"]["address"] == (
            "opc.tcp://10.1.2.50:4840"
        )
        assert [t["name"] for t in project["devices"]["d_opc"]["tags"].values()] == [
            "rtu-1.lock.height",
            "rtu-1.lowergate.open",
        ]
        assert (directory / "hmi_url").read_text() == "http://10.1.2.71:1881/\n"
        sceptre_app.render.assert_not_called()

    def test_no_opc_at_all_is_an_error(self, ctx):
        ctx.opc_configs = {}
        ctx.scada_hosts = [
            node("scada", {"type": "scada-server", **FUXA}, interfaces=lan("10.1.2.71"))
        ]

        with pytest.raises(AppError, match="no OPC server to connect to"):
            ctx.scada_servers()

    def test_hmi_view_and_project_name_metadata(self, ctx):
        ctx.opc_configs = {"10.1.2.50": fake_opc_config()}
        ctx.scada_hosts = [
            node(
                "scada",
                {
                    "type": "scada-server",
                    "hmi_view": "waterway-lock",
                    "fuxa_name": "plant",
                    **FUXA,
                },
                interfaces=lan("10.1.2.71"),
            )
        ]

        ctx.scada_servers()

        project = json.loads(
            (ctx.app.host_dir("scada") / "fuxa_project.json").read_text()
        )
        assert project["name"] == "plant"
        assert project["hmi"]["views"][0]["name"] == "Lock"


class TestHmi:
    def test_points_at_its_scada_servers_fuxa(self, ctx, sceptre_app):
        scada = node("scada", {"type": "scada-server"}, interfaces=lan("10.1.2.71"))
        ctx.scada_hosts = [scada]
        ctx.scada_ips = ["10.1.2.71"]
        sceptre_app.extract_nodes_type.return_value = [
            node("hmi", {"type": "hmi", **FUXA}, interfaces=lan("10.1.2.80"))
        ]

        ctx.hmis()

        directory = ctx.app.host_dir("hmi")
        assert files(directory) == ["hmi_url"]
        assert (directory / "hmi_url").read_text() == "http://10.1.2.71:1881/\n"

    def test_no_scada_server_is_an_error(self, ctx, sceptre_app):
        sceptre_app.extract_nodes_type.return_value = [
            node("hmi", {"type": "hmi", **FUXA}, interfaces=lan("10.1.2.80"))
        ]

        with pytest.raises(AppError, match="no SCADA server"):
            ctx.hmis()


class TestEngineer:
    def test_lists_the_rtus_it_connects_to(self, ctx, sceptre_app):
        ctx.fd_server_configs = {
            "rtu-2": SimpleNamespace(ipaddr="10.1.1.102"),
            "rtu-1": SimpleNamespace(ipaddr="10.1.1.101"),
            "rtu-3": SimpleNamespace(ipaddr="10.1.1.103"),
        }
        sceptre_app.extract_nodes_type.side_effect = lambda t: {
            "fd-server": [],
            "engineer-workstation": [
                node(
                    "eng",
                    {
                        "type": "engineer-workstation",
                        "connected_rtus": ["rtu-2", "rtu-1"],
                        **FUXA,
                    },
                    interfaces=lan("10.1.2.90"),
                )
            ],
        }[t]

        ctx.engineer_workstations()

        directory = ctx.app.host_dir("eng")
        assert files(directory) == ["rtus.txt"]
        assert (directory / "rtus.txt").read_text() == (
            "rtu-1 10.1.1.101\nrtu-2 10.1.1.102\n"
        )

    def test_every_rtu_when_none_are_named(self, ctx, sceptre_app):
        ctx.fd_server_configs = {"rtu-1": SimpleNamespace(ipaddr="10.1.1.101")}
        sceptre_app.extract_nodes_type.side_effect = lambda t: {
            "fd-server": [],
            "engineer-workstation": [
                node(
                    "eng",
                    {"type": "engineer-workstation", **FUXA},
                    interfaces=lan("10.1.2.90"),
                )
            ],
        }[t]

        ctx.engineer_workstations()

        assert (
            ctx.app.host_dir("eng") / "rtus.txt"
        ).read_text() == "rtu-1 10.1.1.101\n"


class TestHistorian:
    def hist(self, **metadata):
        return node(
            "hist",
            {"type": "historian", **FUXA, **metadata},
            interfaces=lan("10.1.2.60"),
        )

    def test_writes_telegraf_and_the_influx_script(self, ctx):
        ctx.opc_configs = {"10.1.2.50": fake_opc_config()}
        ctx.historian_hosts = [self.hist()]

        ctx.historians()

        directory = ctx.app.host_dir("hist")
        assert files(directory) == ["influx-setup.sh", "telegraf.conf"]
        assert (
            'endpoint = "opc.tcp://10.1.2.50:4840"'
            in (directory / "telegraf.conf").read_text()
        )
        assert (directory / "influx-setup.sh").stat().st_mode & 0o100

    def test_influx_metadata_overrides_the_defaults(self, ctx):
        ctx.opc_configs = {"10.1.2.50": fake_opc_config()}
        ctx.historian_hosts = [self.hist(influx_bucket="plant")]

        ctx.historians()

        directory = ctx.app.host_dir("hist")
        assert 'bucket = "plant"' in (directory / "telegraf.conf").read_text()
        assert "INFLUX_BUCKET=plant\n" in (directory / "influx-setup.sh").read_text()

    def test_defaults_are_generic(self, ctx):
        ctx.opc_configs = {"10.1.2.50": fake_opc_config()}
        ctx.historian_hosts = [self.hist()]

        ctx.historians()

        directory = ctx.app.host_dir("hist")
        conf = (directory / "telegraf.conf").read_text()
        setup = (directory / "influx-setup.sh").read_text()
        assert 'name = "sceptre"' in conf
        assert 'bucket = "sceptre"' in conf
        assert "INFLUX_PASS=sceptre-admin-pass " in setup
        assert "waterway" not in conf + setup

    def test_password_and_measurement_metadata(self, ctx):
        ctx.opc_configs = {"10.1.2.50": fake_opc_config()}
        ctx.historian_hosts = [self.hist(influx_password="p w", measurement="plant")]

        ctx.historians()

        directory = ctx.app.host_dir("hist")
        assert 'name = "plant"' in (directory / "telegraf.conf").read_text()
        assert "INFLUX_PASS='p w' " in (directory / "influx-setup.sh").read_text()

    def test_no_opc_on_the_subnet_is_an_error(self, ctx):
        ctx.opc_configs = {"10.9.9.50": fake_opc_config()}
        ctx.historian_hosts = [self.hist()]

        with pytest.raises(AppError, match="no OPC server on subnet"):
            ctx.historians()
