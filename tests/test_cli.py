"""The command line: argument rules, the disabled --cred/--login, and the missing-cookies exit.

The script is copied into a scratch directory and run there, because it looks for cookies.json and
writes Books/ and its log next to itself. Every case exits before any request is made, so there is
no network and no session involved.
"""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "safaribooks.py"


@pytest.fixture
def sandbox(tmp_path):
    shutil.copy(SCRIPT, tmp_path / "safaribooks.py")
    return tmp_path


def run_cli(sandbox, *args):
    return subprocess.run([sys.executable, str(sandbox / "safaribooks.py"), *args],
                          cwd=sandbox, capture_output=True, text=True, timeout=60)


def test_help_lists_every_option_the_readme_documents(sandbox):
    result = run_cli(sandbox, "--help")

    assert result.returncode == 0
    for flag in ("--cred", "--login", "--no-cookies", "--kindle", "--preserve-log",
                 "--no-optimize-images", "--no-optimize-css", "<BOOK ID>"):
        assert flag in result.stdout


def test_a_book_id_is_required(sandbox):
    result = run_cli(sandbox)

    assert result.returncode == 2
    assert "BOOK ID" in result.stderr


def test_cred_and_login_cannot_be_combined(sandbox):
    result = run_cli(sandbox, "--cred", "a@b.c:pw", "--login", "123")

    assert result.returncode == 2
    assert "not allowed with" in result.stderr


def test_no_cookies_is_rejected_without_cred(sandbox):
    result = run_cli(sandbox, "--no-cookies", "123")

    assert result.returncode == 2
    assert "--no-cookies" in result.stderr and "--cred" in result.stderr


@pytest.mark.parametrize("args", [("--cred", "a@b.c:pw"), ("--login",)])
def test_cred_and_login_are_disabled_and_point_to_cookies_json(sandbox, args):
    result = run_cli(sandbox, *args, "123")

    assert result.returncode == 0
    assert "temporarily disabled" in result.stdout
    assert "cookies.json" in result.stdout
    # nothing else happened: no session, no output directory, no cookies written
    assert not (sandbox / "Books").exists()
    assert not (sandbox / "cookies.json").exists()


def test_missing_cookies_json_aborts_with_a_clear_message_and_makes_nothing(sandbox):
    result = run_cli(sandbox, "123")

    assert result.returncode == 1
    assert "unable to find `cookies.json`" in result.stdout
    assert "Aborting" in result.stdout
    # a deliberate exit, not a crash that happens to end the same way
    assert "Unhandled Exception" not in result.stdout
    assert "FileNotFoundError" not in result.stdout + result.stderr
    assert not (sandbox / "Books").exists()
    assert not (sandbox / "cookies.json").exists()
