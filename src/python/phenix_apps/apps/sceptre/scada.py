"""Pre-start for the SCADA side: OPC, SCADA server, HMI, engineer, historian.

They share the OPC lookup: each host is configured against the OPC on its own
subnet, and the config objects pass down the chain from opcs() onward.
"""

import json
import shutil
from pathlib import Path
from typing import Any

from phenix_apps.apps.sceptre import scada_linux
from phenix_apps.apps.sceptre.configs import configs
from phenix_apps.apps.sceptre.hosts import (
    address,
    is_backup,
    is_linux_fuxa,
    non_mgmt,
    same_subnet,
)
from phenix_apps.apps.sceptre.metadata import (
    FUXA_PROJECT,
    INFLUX_BUCKET,
    INFLUX_ORG,
    INFLUX_PASSWORD,
    INFLUX_TOKEN,
    MEASUREMENT,
)
from phenix_apps.apps.sceptre.stages import PreStartState
from phenix_apps.common import utils
from phenix_apps.common.error import AppError
from phenix_apps.common.logger import logger


def opc_on_subnet(
    ip: str, *config_maps: dict[str, configs.OpcConfig]
) -> tuple[str, configs.OpcConfig | None]:
    """(opc ip, OpcConfig) for the OPC on ip's subnet, else ("", None)."""

    for configs_by_ip in config_maps:
        for opc_ip, config in configs_by_ip.items():
            if same_subnet(ip, opc_ip):
                return opc_ip, config
    return "", None


class Scada(PreStartState):
    """OPC, SCADA server, HMI, engineer workstation and historian handling."""

    def collect_ips(self) -> None:
        """Collect the non-mgmt IPs that the OPC, HMI and engineer handlers need.

        Writes: historian_hosts, historian_ips, scada_hosts, scada_ips
        """

        self.scada_hosts = self.hosts("scada-server")
        self.historian_hosts = self.hosts("historian")

        self.historian_ips = [
            i.address for h in self.historian_hosts for i in non_mgmt(h)
        ]
        self.scada_ips = [i.address for s in self.scada_hosts for i in non_mgmt(s)]

    def opcs(self) -> None:
        """Build an OpcConfig per OPC and render its config + TopServer script.

        Reads: fd_server_configs, historian_ips, scada_ips
        Writes: opc_bak_configs, opc_configs
        """

        # Keyed by OPC IP: historians use the one on their own subnet.
        self.opc_configs = {}
        self.opc_bak_configs = {}
        opcs = self.hosts("opc")

        for opc in opcs:
            rtus = opc.metadata.get("connected_rtus") if opc.metadata else None
            if rtus is None:
                logger.warning(
                    f"No rtus defined for {opc.hostname}. It will be configured to monitor all field devices"
                )
                opc_fd_configs = self.fd_server_configs
            else:
                opc_fd_configs = {
                    rtu: self.fd_server_configs[rtu]
                    for rtu in rtus
                    if rtu in self.fd_server_configs
                }

            opc_directory = self.host_dir(opc.hostname)

            primary_opc = False
            opc_ip = non_mgmt(opc)[0].address
            opc_config = configs.OpcConfig(opc_fd_configs, opc_ip)
            if not is_backup(opc.hostname):
                self.opc_configs[opc_ip] = opc_config
                primary_opc = True
            # Backups, for scada server/historian automation.
            else:
                self.opc_bak_configs[opc_ip] = opc_config

            if is_linux_fuxa(opc):
                self._linux_opc(opc, opc_directory, opc_config)
                continue

            self.render(
                "opc_template.mako",
                opc_directory / "opc.xml",
                opc_config=opc_config,
            )

            self.render(
                "topserver.mako",
                opc_directory / "topserver.ps1",
                scada_ips=self.scada_ips,
                historian_ips=self.historian_ips,
                opc_ip=opc_ip,
                primary_opc=primary_opc,
            )

    def scada_servers(self) -> None:
        """Render the SCADA project files and startup script.

        Reads: opc_bak_configs, opc_configs, scada_hosts
        """

        for scada_server in self.scada_hosts:
            scada_directory = self.host_dir(scada_server.hostname)

            if is_linux_fuxa(scada_server):
                self._linux_scada_server(scada_server, scada_directory)
            elif "project" in scada_server.metadata:
                self.render("scada.mako", scada_directory / "scada.ps1")
            else:
                opc_ip, opc_config = self._opc_for(scada_server)

                shutil.copytree(
                    Path(self.app.templates_dir) / "mydesigner",
                    scada_directory / "autoproject",
                    dirs_exist_ok=True,
                )
                self.render(
                    "scada_connectionsdef.mako",
                    scada_directory / "autoproject" / "connectionsdef.json",
                    opc_ip=opc_ip,
                )

                self.render(
                    "scada_table.mako",
                    scada_directory / "autoproject" / "Table.svg",
                    opc_config=opc_config,
                )

                self.render(
                    "scada_autoproject.mako", scada_directory / "scada_autoproject.ps1"
                )

    def _opc_for(self, scada_server: Any) -> tuple[str, configs.OpcConfig]:
        """The OPC on this server's own subnet, else a backup, else the first."""

        scada_ip = non_mgmt(scada_server)[0].address
        opc_ip, opc_config = opc_on_subnet(
            scada_ip, self.opc_configs, self.opc_bak_configs
        )
        if opc_config is not None:
            return opc_ip, opc_config

        if not self.opc_configs:
            raise AppError(
                f"{scada_server.hostname}: no OPC server to connect to; add a "
                "host with metadata.type opc"
            )
        opc_ip = next(iter(self.opc_configs))
        logger.warning(
            f"{scada_server.hostname}: no OPC server on subnet "
            f"{scada_ip}; falling back to {opc_ip}"
        )
        return opc_ip, self.opc_configs[opc_ip]

    def hmis(self) -> None:
        """Render each HMI's startup script.

        Reads: scada_hosts, scada_ips
        """

        hmis = self.hosts("hmi")
        by_hostname = {s.hostname: s for s in self.scada_hosts}

        for hmi in hmis:
            hmi_ip = address(hmi)
            # named scada servers, else whatever is on this HMI's subnet
            if "connected_scadas" in hmi.metadata:
                hmi_scada_ips = [
                    address(by_hostname[name])
                    for name in hmi.metadata.connected_scadas
                    if name in by_hostname
                ]
            elif len(self.scada_ips) == 1:
                hmi_scada_ips = self.scada_ips
            else:
                hmi_scada_ips = [
                    scada_ip
                    for scada_ip in self.scada_ips
                    if same_subnet(scada_ip, hmi_ip)
                ]

            hmi_directory = self.host_dir(hmi.hostname)

            if is_linux_fuxa(hmi):
                self._linux_hmi(hmi, hmi_directory, hmi_scada_ips)
                continue

            self.render(
                "hmi.mako",
                hmi_directory / "hmi.ps1",
                scada_ips=hmi_scada_ips,
                hmi_ip=hmi_ip,
            )

    def engineer_workstations(self) -> None:
        """Render the PuTTY and auto-connect scripts.

        The workstation connects to field devices, not to the SCADA server.
        """

        rtus = self.hosts("fd-server")
        engineer_workstations = self.hosts("engineer-workstation")
        by_hostname = {rtu.hostname: rtu for rtu in rtus}

        for engineer_workstation in engineer_workstations:
            # connected_rtus, or every fd-server when it is not set
            if "connected_rtus" in engineer_workstation.metadata:
                eng_fd = [
                    by_hostname[name]
                    for name in engineer_workstation.metadata.connected_rtus
                    if name in by_hostname
                ]
            else:
                eng_fd = list(rtus)

            engineer_directory = self.host_dir(engineer_workstation.hostname)

            if is_linux_fuxa(engineer_workstation):
                self._linux_engineer(engineer_workstation, engineer_directory)
                continue

            self.render(
                "putty.mako",
                engineer_directory / "putty.ps1",
                eng_fd=eng_fd,
            )

            if "connect_interval" in engineer_workstation.metadata:
                self.render(
                    "auto_winscp.mako",
                    engineer_directory / "auto_winscp.ps1",
                    eng_fd=eng_fd,
                    connect_interval=engineer_workstation.metadata.connect_interval,
                )

    def historians(self) -> None:
        """Render each historian's config and startup script.

        Reads: historian_hosts, opc_configs
        """

        secondary_historian_ips: dict[str, list[str]] = {"historian": []}

        for historian in self.historian_hosts:
            iface = non_mgmt(historian)[0]

            # No metadata at all makes a host a secondary of "historian".
            primary = (
                historian.metadata.get("primary") if historian.metadata else "historian"
            )
            if primary:
                secondary_historian_ips.setdefault(primary, []).append(iface.address)

        for historian in self.historian_hosts:
            historian_directory = self.host_dir(historian.hostname)
            hist_ip = non_mgmt(historian)[0].address

            if is_linux_fuxa(historian):
                self._linux_historian(historian, historian_directory, hist_ip)
                continue

            # The OPC on this historian's own subnet, if there is one. Without it
            # the historian has no address to collect from, so it gets no tags
            # either -- it used to inherit whichever config the OPC and SCADA loops
            # left behind, and silently list another OPC's devices.
            opc_config_ip, opc_config = opc_on_subnet(hist_ip, self.opc_configs)
            if not opc_config_ip:
                logger.warning(
                    f"{historian.hostname}: no OPC server on subnet {hist_ip}; "
                    "its historian config will have no tags"
                )

            # Backups replicate from the primary, so an empty config is enough.
            hist_config = configs.HistorianConfig()

            if not is_backup(historian.hostname):
                secondary_ips = secondary_historian_ips.get(historian.hostname, [])
                metadata = historian.metadata or {}
                # Field "types" to store; empty means every field OPC provides.
                hist_fields = metadata.get("fields", [])

                if metadata.get("connecttoscada"):
                    hist_config = configs.HistorianConfig(
                        None, "", secondary_ips, True, hist_fields
                    )
                else:
                    hist_config = configs.HistorianConfig(
                        opc_config, opc_config_ip, secondary_ips, False, hist_fields
                    )

            self.render(
                "historian_config.mako",
                historian_directory / "historian_config.txt",
                hist_config=hist_config,
                hist_name=historian.hostname,
            )

            self.render(
                "historian.mako",
                historian_directory / "historian.ps1",
                hist_config=hist_config,
                historian_name=historian.hostname.upper(),
            )

    # -- metadata.stack: linux_fuxa ----------------------------------------
    # The same OpcConfigs feed both stacks; only the files written differ.

    def _linux_opc(
        self, opc: Any, directory: Path, opc_config: configs.OpcConfig
    ) -> None:
        """Write the OPC UA gateway config in place of opc.xml and topserver.ps1."""

        (directory / "opc_gateway.json").write_text(
            json.dumps(scada_linux.gateway_config(opc_config), indent=2) + "\n"
        )
        logger.info(f"{opc.hostname}: wrote opc_gateway.json")

    def _linux_scada_server(self, scada_server: Any, directory: Path) -> None:
        """Write the FUXA project and the URL of the FUXA web UI."""

        opc_ip, opc_config = self._opc_for(scada_server)
        (directory / "fuxa_project.json").write_text(
            scada_linux.fuxa_project(
                scada_linux.opc_endpoint(opc_ip),
                scada_linux.points(opc_config),
                scada_server.metadata.get("fuxa_name", FUXA_PROJECT),
                scada_server.metadata.get("hmi_view"),
            )
        )
        (directory / "hmi_url").write_text(
            scada_linux.hmi_url(non_mgmt(scada_server)[0].address)
        )

    def _linux_hmi(self, hmi: Any, directory: Path, scada_ips: list[str]) -> None:
        """Write the FUXA URL of the HMI's SCADA server (the first, if several).

        AppError if there is none: the file is injected unconditionally.
        """

        if not scada_ips:
            raise AppError(
                f"{hmi.hostname}: no SCADA server found for this linux_fuxa HMI; "
                "set metadata.connected_scadas"
            )
        (directory / "hmi_url").write_text(scada_linux.hmi_url(scada_ips[0]))

    def _linux_engineer(self, engineer: Any, directory: Path) -> None:
        """Write the field devices the workstation connects to."""

        names = engineer.metadata.get("connected_rtus") or self.fd_server_configs
        rtu_ips = {
            name: self.fd_server_configs[name].ipaddr
            for name in names
            if name in self.fd_server_configs
        }
        (directory / "rtus.txt").write_text(scada_linux.rtus_txt(rtu_ips))

    def _linux_historian(self, historian: Any, directory: Path, hist_ip: str) -> None:
        """Write telegraf's config and the InfluxDB setup script."""

        opc_ip, opc_config = opc_on_subnet(hist_ip, self.opc_configs)
        if not opc_ip or opc_config is None:
            raise AppError(
                f"{historian.hostname}: no OPC server on subnet {hist_ip} for its "
                "telegraf to read; add a host with metadata.type opc on that subnet"
            )
        metadata = historian.metadata or {}
        influx = {
            "org": metadata.get("influx_org", INFLUX_ORG),
            "bucket": metadata.get("influx_bucket", INFLUX_BUCKET),
            "token": metadata.get("influx_token", INFLUX_TOKEN),
        }
        setup_only = {"password": metadata.get("influx_password", INFLUX_PASSWORD)}
        points = scada_linux.points(opc_config) if opc_config else []

        (directory / "telegraf.conf").write_text(
            scada_linux.telegraf_conf(
                opc_ip,
                points,
                **influx,
                measurement=metadata.get("measurement", MEASUREMENT),
            )
        )
        setup = directory / "influx-setup.sh"
        setup.write_text(scada_linux.influx_setup(**influx, **setup_only))
        utils.mark_executable(str(setup))
