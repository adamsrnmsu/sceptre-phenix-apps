"""The injected /etc/phenix/startup/90-sandcat-agent.sh must not hold boot.

phenix-start.sh runs the startup scripts one after another, each to completion, in name
order, so a foreground wait for the Caldera server in 90-sandcat-agent.sh keeps every later
script (sceptre-start.sh, which starts the field device and its :502) from running until
the server answers.
"""

import contextlib
import os
import signal
import subprocess
import time
from pathlib import Path

from phenix_apps.apps import caldera
from phenix_apps.common import utils

TEMPLATES = Path(caldera.__file__).parent / "templates"


def reap(proc):
    """Kill what the script left running (the retry loop); the group may be gone."""
    with contextlib.suppress(OSError):
        os.killpg(proc.pid, signal.SIGKILL)


def render(tmp_path: Path) -> Path:
    script = tmp_path / "90-sandcat-agent.sh"
    with script.open("w") as f:
        utils.mako_serve_template("linux_agent.mako", TEMPLATES, f, addr="10.1.1.210")
    return script


def test_agent_script_returns_while_the_server_is_down(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    curl = bindir / "curl"
    curl.write_text("#!/bin/sh\nexit 7\n")  # the server never answers
    curl.chmod(0o755)
    sleep = bindir / "sleep"
    sleep.write_text("#!/bin/sh\nexec /bin/sleep 0.05\n")  # keep the retry loop quick
    sleep.chmod(0o755)
    script = render(tmp_path)
    env = {"PATH": f"{bindir}:/usr/bin:/bin"}

    start = time.monotonic()
    proc = subprocess.Popen(
        ["/bin/sh", str(script)],
        cwd=tmp_path,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        proc.wait(timeout=5)  # unfixed, this blocks forever in the until loop
        assert time.monotonic() - start < 2
    finally:
        reap(proc)


def test_agent_still_downloads_and_starts_once_the_server_answers(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    curl = bindir / "curl"
    curl.write_text(
        "#!/bin/sh\n"
        'case "$1" in -svkOJ)\n'
        '  printf "#!/bin/sh\\ntouch ran\\n" > agent\n'
        '  echo "< Content-Disposition: attachment; filename=\\"agent\\"" >&2;;\n'
        "esac\n"
    )
    curl.chmod(0o755)
    script = render(tmp_path)

    proc = subprocess.Popen(
        ["/bin/sh", str(script)],
        cwd=tmp_path,
        env={"PATH": f"{bindir}:/usr/bin:/bin"},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 5
        while not (tmp_path / "ran").exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert (tmp_path / "ran").exists()
    finally:
        reap(proc)


def test_windows_agent_loop_is_detached(tmp_path):
    """No pwsh to run it here: check the retry loop only runs in a detached powershell."""
    script = tmp_path / "90-sandcat-agent.ps1"
    with script.open("w") as f:
        utils.mako_serve_template("windows_agent.mako", TEMPLATES, f, addr="10.1.1.210")
    text = script.read_text()
    head, _, rest = text.partition("$loop = @'\n")
    loop, _, tail = rest.partition("\n'@\n")
    assert "do {" not in head  # nothing loops in the foreground
    assert "do {" not in tail
    assert "http://10.1.1.210:8888" in loop
    assert "while ($true)" in loop
    assert "Start-Process powershell" in tail
    assert "-EncodedCommand" in tail
