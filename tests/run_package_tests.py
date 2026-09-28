#!/usr/bin/env python3
"""运行打包器单元测试和真实原生启动器编译测试；不安装任何包。"""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    for arguments in (
        ["-m", "unittest", "discover", "-s", "tests", "-p", "test_gx_*.py"],
        ["tests/gx_launcher.py"],
    ):
        result = subprocess.run([sys.executable, *arguments], cwd=ROOT, check=False)
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
