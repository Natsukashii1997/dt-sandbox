import subprocess
import sys
from pathlib import Path

import pytest

from todo_lite import __version__
from todo_lite.cli import main

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_version_constant():
    assert __version__ == "0.1.0"


def test_main_version_flag(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == "0.1.0"


def test_python_m_version():
    result = subprocess.run(
        [sys.executable, "-m", "todo_lite", "--version"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "0.1.0"
