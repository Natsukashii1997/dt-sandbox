"""todo-lite 命令行入口。"""

from __future__ import annotations

import argparse
from typing import Sequence

from todo_lite import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="todo_lite", description="极简命令行待办清单")
    parser.add_argument("--version", action="version", version=__version__)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    parser.parse_args(argv)
    parser.print_help()
    return 0
