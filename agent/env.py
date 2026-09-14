"""Load the provider API key from a .env file if it is not already in the shell.

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


# 模型前缀 -> (环境变量名, 密钥前缀, 申请地址)
PROVIDERS = {
    "deepseek": ("DEEPSEEK_API_KEY", "sk-", "https://platform.deepseek.com/api_keys"),
    "claude": ("ANTHROPIC_API_KEY", "sk-ant-", "https://console.anthropic.com/settings/keys"),
    "anthropic:": ("ANTHROPIC_API_KEY", "sk-ant-", "https://console.anthropic.com/settings/keys"),
}
DEFAULT_PROVIDER = PROVIDERS["claude"]


def provider_for(model: str | None = None) -> tuple[str, str, str]:
    """Which key does this model need?

    Read from LC_MODEL when no model is passed, so switching provider is a
    one-line change in .env rather than an edit here.
    """
    model = (model or os.environ.get("LC_MODEL", "")).lower()
    for prefix, spec in PROVIDERS.items():
        if model.startswith(prefix):
            return spec
    return DEFAULT_PROVIDER


def require_api_key(model: str | None = None) -> str:
    """Return the key this model needs, or explain exactly what to do."""
    load_env()
    env_name, expect, console = provider_for(model)
    key = os.environ.get(env_name, "").strip()
    if not key:
        raise SystemExit(
            f"\n未找到 {env_name}。两种设置方式，选一种：\n\n"
            "  1. 写进文件（推荐，只需一次）：\n"
            "     把 .env.example 复制成 .env，填上你的 key\n"
            f"     位置：{ENV_FILE}\n\n"
            "  2. 设环境变量（临时）：\n"
            f'     Mac/Linux:  export {env_name}="{expect}..."\n'
            f'     Windows:    setx {env_name} "{expect}..."\n\n'
            f"  申请地址：{console}\n"
            ".env 已在 .gitignore 里，不会被提交。\n"
        )
    if not key.startswith(expect):
        print(f"警告：key 以 {key[:7]!r} 开头，通常应为 {expect!r}。继续尝试。")
    return key
