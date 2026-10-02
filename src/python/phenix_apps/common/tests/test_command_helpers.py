"""
Tests for the shared command helpers: values spliced into raw minimega
commands must be single tokens, and run_command never goes through a shell.
"""

import pytest

from phenix_apps.common import utils
from phenix_apps.common.error import AppError


class TestValidateMmToken:
    @pytest.mark.parametrize("value", ["exp1", "node-2", "a.b_c"])
    def test_accepts(self, value):
        assert utils._validate_mm_token(value) == value

    @pytest.mark.parametrize(
        "value",
        ["", "two words", "new\nline", "tab\there", "quo'te", 'dou"ble'],
    )
    def test_rejects(self, value):
        with pytest.raises(AppError):
            utils._validate_mm_token(value)


class TestRunCommand:
    def test_string_form_is_shlex_split_not_shell(self):
        # A shell would expand the glob and the semicolon; argv exec must not.
        out = utils.run_command("echo 'a; touch /tmp/pwned' *")
        assert out.strip() == "a; touch /tmp/pwned *"

    def test_list_form_passthrough(self):
        assert utils.run_command(["echo", "hi"]).strip() == "hi"
