"""Config generators for the Linux SCADA stack (metadata.stack: linux_fuxa).

FUXA, the OPC UA gateway, telegraf and InfluxDB come with the VM image; the app
only writes their configs. Everything here is a pure function of the OpcConfig
the Windows stack already builds, so both stacks share one register map.

The OPC UA node id of a register is `ns=2;s=<rtu>.<device>.<field>`. A device
field with both an input and a holding register (a gate's `open`) is one node:
it reads from the input register and writes to the holding register.
"""

import io
import json
import shlex
from pathlib import Path
from typing import Any, Final, NamedTuple

from phenix_apps.apps.sceptre import lock_view
from phenix_apps.apps.sceptre.configs.configs import OpcConfig
from phenix_apps.apps.sceptre.metadata import (
    FUXA_PORT,
    FUXA_PROJECT,
    INFLUX_BUCKET,
    INFLUX_ORG,
    INFLUX_PASSWORD,
    INFLUX_TOKEN,
    MEASUREMENT,
    OPC_UA_PORT,
)
from phenix_apps.common import utils
from phenix_apps.common.error import AppError

MODBUS_PORT: Final[int] = 502
MODBUS_UNIT: Final[int] = 1
POLL_INTERVAL: Final[float] = 1.0
OPC_NAMESPACE: Final[int] = 2
REGISTER_TYPES: Final[tuple[str, ...]] = ("input-register", "holding-register")


TEMPLATES: Final[Path] = Path(__file__).parent / "templates"


def _render(template: str, **kwargs: Any) -> str:
    """Render a mako template to a string. Templates end without a newline: the
    renderer adds exactly one."""

    out = io.StringIO()
    utils.mako_serve_template(template, TEMPLATES, out, **kwargs)
    return out.getvalue()


class Point(NamedTuple):
    """One OPC UA node: <rtu>.<device>.<field>."""

    rtu: str
    device: str
    field: str

    @property
    def node(self) -> str:
        return ".".join(self)


def _rtus(opc_config: OpcConfig) -> list[dict[str, Any]]:
    """The gateway's rtu list, sorted by name, points sorted by (device, field)."""

    rtus: dict[str, dict[str, Any]] = {}
    for channel in opc_config.channel_list:
        for device in channel.devices:
            if channel.protocol != "modbus":
                raise AppError(
                    f"{device.fd_name}: protocol '{channel.protocol}' is not "
                    "supported by the linux_fuxa OPC UA gateway (modbus only)"
                )
            rtu = rtus.setdefault(
                device.fd_name,
                {
                    "name": device.fd_name,
                    "host": device.fd_ip,
                    "port": MODBUS_PORT,
                    "unit": MODBUS_UNIT,
                    "pts": {},
                },
            )
            for tag in device.tags:
                if tag.regtype not in REGISTER_TYPES:
                    raise AppError(
                        f"{device.fd_name}: register type '{tag.regtype}' is not "
                        "supported by the linux_fuxa OPC UA gateway "
                        "(input and holding registers only)"
                    )
                pt = rtu["pts"].setdefault((tag.devname, tag.field), {})
                side = "write" if tag.regtype == "holding-register" else "read"
                pt[side] = {"type": tag.regtype, "address": tag.addr}

    out = []
    for name in sorted(rtus):
        rtu = rtus[name]
        points = []
        for (dev, field), pt in sorted(rtu.pop("pts").items()):
            # A holding-only point is read back from its holding register.
            read = pt.get("read", pt.get("write"))
            points.append(
                {
                    "node": f"{name}.{dev}.{field}",
                    "read": read,
                    "write": pt.get("write"),
                }
            )
        out.append({**rtu, "points": points})
    return out


def points(opc_config: OpcConfig) -> list[Point]:
    """Every OPC UA node the gateway serves, in gateway order."""

    return [
        Point(*p["node"].split(".", 2))
        for rtu in _rtus(opc_config)
        for p in rtu["points"]
    ]


def scale(opc_config: OpcConfig) -> list[float]:
    """The one [min, max] the gateway scales every register over.

    AppError if the RTUs disagree: the gateway has a single scale, so picking
    one would silently misreport the others.
    """

    ranges = {
        tuple(device.range)
        for channel in opc_config.channel_list
        for device in channel.devices
    }
    if len(ranges) > 1:
        raise AppError(
            "linux_fuxa OPC UA gateway has one scale, but the RTUs use "
            f"different ranges: {sorted(ranges)}"
        )
    return list(ranges.pop()) if ranges else [0, 1]


def gateway_config(opc_config: OpcConfig) -> dict[str, Any]:
    """The OPC UA gateway's /etc/sceptre/opc_gateway.json."""

    return {
        "opc_endpoint": f"opc.tcp://0.0.0.0:{OPC_UA_PORT}",
        "poll_interval": POLL_INTERVAL,
        "scale": scale(opc_config),
        "rtus": _rtus(opc_config),
    }


def fuxa_project(
    opc_endpoint: str,
    pts: list[Point],
    name: str = FUXA_PROJECT,
    hmi_view: str | None = None,
) -> str:
    """The FUXA project: one OPC UA device, a tag per node and a process view.

    hmi_view names a view in lock_view.VIEWS; unset, the animated lock is used
    when the project has every tag it needs, else a plain table of every tag.
    AppError for an unknown name.
    """

    if hmi_view and hmi_view not in lock_view.VIEWS:
        raise AppError(
            f"unknown hmi_view '{hmi_view}'; one of: {', '.join(lock_view.VIEWS)}"
        )
    picked = lock_view.pick(hmi_view, [p.node for p in pts])
    view = lock_view.VIEWS[picked]({p.node: f"t{i}" for i, p in enumerate(pts, 1)})
    text = _render(
        "fuxa_project.mako",
        opc_endpoint=opc_endpoint,
        view_name=json.dumps("Tags" if picked == "plain" else "Lock"),
        project_name=json.dumps(name),
        view_w=view["width"],
        view_h=view["height"],
        points=pts,
        ns=OPC_NAMESPACE,
        view_items=json.dumps(view["items"]),
        view_svg=json.dumps(view["svg"]),
    )
    json.loads(text)  # fail in pre-start, not at FUXA import
    return text


def _toml(value: str) -> str:
    """Escape for inside a TOML basic string (JSON string escapes are a subset)."""

    return json.dumps(value)[1:-1]


def opc_endpoint(opc_ip: str) -> str:
    """Where FUXA and telegraf reach the OPC UA gateway."""

    return f"opc.tcp://{opc_ip}:{OPC_UA_PORT}"


def telegraf_conf(
    opc_ip: str,
    pts: list[Point],
    org: str = INFLUX_ORG,
    bucket: str = INFLUX_BUCKET,
    token: str = INFLUX_TOKEN,
    measurement: str = MEASUREMENT,
) -> str:
    """The historian's /etc/telegraf/telegraf.conf: OPC UA in, InfluxDB out."""

    return _render(
        "telegraf.mako",
        opc_endpoint=opc_endpoint(opc_ip),
        points=pts,
        ns=OPC_NAMESPACE,
        influx_org=_toml(org),
        influx_bucket=_toml(bucket),
        influx_token=_toml(token),
        measurement=_toml(measurement),
    )


def influx_setup(
    org: str = INFLUX_ORG,
    bucket: str = INFLUX_BUCKET,
    token: str = INFLUX_TOKEN,
    password: str = INFLUX_PASSWORD,
) -> str:
    """The historian's startup script: create the org, bucket and token once."""

    return _render(
        "influx_setup.mako",
        backslash="\\",  # a literal backslash at a line end would be a mako continuation
        influx_org=shlex.quote(org),
        influx_bucket=shlex.quote(bucket),
        influx_token=shlex.quote(token),
        influx_pass=shlex.quote(password),
    )


def hmi_url(scada_ip: str) -> str:
    """The FUXA web UI an HMI opens."""

    return f"http://{scada_ip}:{FUXA_PORT}/\n"


def rtus_txt(rtu_ips: dict[str, str]) -> str:
    """The engineer workstation's RTU list, one "<hostname> <ip>" per line."""

    return "".join(f"{name} {ip}\n" for name, ip in sorted(rtu_ips.items()))
