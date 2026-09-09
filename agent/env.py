"""Load ANTHROPIC_API_KEY from a .env file if it is not already in the shell.

Kept dependency-free on purpose: no python-dotenv needed.
The .env file is listed in .gitignore and must never be committed.
"""
from __future__ import annotations

import os
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def load_env(path: Path = ENV_FILE) -> None:
    """Read KEY=VALUE lines into os.environ without overwriting real env vars."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:      # shell wins over the file
            os.environ[key] = value


def require_api_key() -> str:
    """Return the key, or explain exactly what to do if it is missing."""
    load_env()
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        raise SystemExit(
            "\n未找到 ANTHROPIC_API_KEY。两种设置方式，选一种：\n\n"
            f"  1. 写进文件（推荐，只需一次）：\n"
            f"     把 .env.example 复制成 .env，填上你的 key\n"
            f"     位置：{ENV_FILE}\n\n"
            "  2. 设环境变量（临时）：\n"
            '     Mac/Linux:  export ANTHROPIC_API_KEY="sk-ant-..."\n'
            '     Windows:    setx ANTHROPIC_API_KEY "sk-ant-..."\n\n"'
            ".env 已在 .gitignore 里，不会被提交。\n"
        )
    if not key.startswith("sk-ant-"):
        print(f"警告：key 以 {key[:7]!r} 开头，通常应为 'sk-ant-'。继续尝试。")
    return key
