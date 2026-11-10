"""Golden tests for metadata.stack: linux_fuxa, on the waterway-arm64 range.

The input is the waterway scenario with its SCADA-side hosts on the Linux stack.
Two things are pinned:

* the SCADA configs against golden_linux_fuxa/, which are what the range's
  scada/gen_configs.py wrote for the same topology before the app generated
  them itself. They must agree except for the normalisations in `normalise`.
* every generated file's hash and every inject, like test_sceptre_golden.py.

Regenerate the hash golden after an intentional change:

    PHENIX_UPDATE_GOLDEN=1 pytest phenix_apps/apps/sceptre/tests/test_linux_fuxa_golden.py
"""

import json
import os
from pathlib import Path

import pytest
from box import Box

from phenix_apps.apps.sceptre.tests.test_sceptre_golden import _manifest, _run_stage

HERE = Path(__file__).parent
INPUT_FILE = HERE / "test_sceptre_input_linux_fuxa.yaml"
GOLDEN_FILE = HERE / "sceptre_linux_fuxa_golden.json"
REFERENCE = HERE / "golden_linux_fuxa"

# The generated file for each reference file, under sceptre/.
WHERE = {
    "opc_gateway.json": "opc",
    "fuxa_project.json": "scada-server",
    "telegraf.conf": "historian",
    "influx-setup.sh": "historian",
    "hmi_url": "hmi",
    "rtus.txt": "engineer-workstation",
}


def normalise(name: str, text: str) -> object:
    """What may differ between the app's file and the gen_configs.py reference.

    * fuxa_project.json: compared as parsed JSON. The reference went through
      jinja's `tojson`, which sorts keys and escapes < > ' as \\uXXXX.
    * telegraf.conf, influx-setup.sh: comment lines are dropped (the headers name
      the generator, which is now the app); a shebang is kept.
    * everything else is compared byte for byte.
    """

    if name == "fuxa_project.json":
        return json.loads(text)
    if name in ("telegraf.conf", "influx-setup.sh"):
        return [
            line
            for line in text.splitlines()
            if not line.startswith("#") or line.startswith("#!")
        ]
    return text


def _capture(monkeypatch, base_dir: Path) -> dict:
    configure_json = _run_stage(
        monkeypatch, INPUT_FILE.read_text(), "configure", base_dir
    )
    configure_files = _manifest(base_dir)
    pre_start_json = _run_stage(monkeypatch, configure_json, "pre-start", base_dir)

    return {
        "configure": {
            "experiment": json.loads(configure_json),
            "files": configure_files,
        },
        "pre_start": {
            "experiment": json.loads(pre_start_json),
            "files": _manifest(base_dir),
        },
    }


@pytest.mark.parametrize("name", sorted(WHERE))
def test_configs_match_gen_configs(monkeypatch, tmp_path, name):
    base_dir = tmp_path / "exp"
    configure_json = _run_stage(
        monkeypatch, INPUT_FILE.read_text(), "configure", base_dir
    )
    _run_stage(monkeypatch, configure_json, "pre-start", base_dir)

    generated = (base_dir / "sceptre" / WHERE[name] / name).read_text()
    reference = (REFERENCE / name).read_text()

    assert normalise(name, generated) == normalise(name, reference)


def test_no_windows_files_are_generated(monkeypatch, tmp_path):
    base_dir = tmp_path / "exp"
    configure_json = _run_stage(
        monkeypatch, INPUT_FILE.read_text(), "configure", base_dir
    )
    _run_stage(monkeypatch, configure_json, "pre-start", base_dir)

    scada_side = ("opc", "scada-server", "hmi", "historian", "engineer-workstation")
    for host in scada_side:
        names = {p.name for p in (base_dir / "sceptre" / host).iterdir()}
        assert not {n for n in names if n.endswith(".ps1") or n == "opc.xml"}, host


def test_injects_are_the_linux_ones(monkeypatch, tmp_path):
    base_dir = tmp_path / "exp"
    configure_json = _run_stage(
        monkeypatch, INPUT_FILE.read_text(), "configure", base_dir
    )

    experiment = Box(json.loads(configure_json))
    injects = {
        node.general.hostname: {i.dst for i in node.get("injections", [])}
        for node in experiment.spec.topology.nodes
    }

    assert {"/etc/sceptre/opc_gateway.json"} <= injects["opc"]
    assert {"/etc/sceptre/fuxa_project.json", "/etc/sceptre/hmi_url"} <= injects[
        "scada-server"
    ]
    assert {"/etc/sceptre/hmi_url"} <= injects["hmi"]
    assert {"/etc/sceptre/rtus.txt"} <= injects["engineer-workstation"]
    assert {
        "/etc/telegraf/telegraf.conf",
        "/etc/phenix/startup/influx-setup.sh",
    } <= injects["historian"]
    for host in ("opc", "scada-server", "hmi", "historian", "engineer-workstation"):
        assert not [d for d in injects[host] if "ps1" in d or d.endswith("opc.xml")]


def test_stages_match_golden(monkeypatch, tmp_path):
    base_dir = tmp_path / "exp"
    actual = _capture(monkeypatch, base_dir)

    blob = json.dumps(actual, indent=2, sort_keys=True).replace(
        str(base_dir), "{BASE_DIR}"
    )

    if os.getenv("PHENIX_UPDATE_GOLDEN"):
        GOLDEN_FILE.write_text(blob + "\n")
        pytest.skip(f"regenerated {GOLDEN_FILE.name}")

    assert GOLDEN_FILE.exists(), (
        f"{GOLDEN_FILE.name} is missing; regenerate with PHENIX_UPDATE_GOLDEN=1"
    )
    assert json.loads(blob) == json.loads(GOLDEN_FILE.read_text())
