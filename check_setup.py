"""Pre-flight check: run this before anything else.

Says exactly what is missing and what to do about it, instead of letting you
find out one traceback at a time.

    python check_setup.py
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OK, WARN, BAD = "  [OK]  ", "  [!]   ", "  [X]   "


def check_python() -> bool:
    v = sys.version_info
    if v >= (3, 10):
        print(f"{OK}Python {v.major}.{v.minor}.{v.micro}")
        return True
    print(f"{BAD}Python {v.major}.{v.minor} 过低，需要 3.10 以上"
          "（代码用了 `str | None` 这类新写法）")
    return False


def check_package(name: str, install: str, *, required: bool) -> bool:
    if importlib.util.find_spec(name) is not None:
        print(f"{OK}{name}")
        return True
    mark = BAD if required else WARN
    tail = "" if required else "（只有要用 LangChain 版才需要）"
    print(f"{mark}{name} 未安装 -> pip install {install}{tail}")
    return not required


def _key_line() -> int:
    """模板里 ANTHROPIC_API_KEY 在第几行——不写死，免得改模板后提示错行。"""
    template = ROOT / ".env.example"
    if template.exists():
        for i, line in enumerate(template.read_text(encoding="utf-8").splitlines(), 1):
            if line.startswith("ANTHROPIC_API_KEY"):
                return i
    return 1


def check_key() -> bool:
    from agent.env import ENV_FILE, load_env

    load_env()
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        print(f"{WARN}未找到 ANTHROPIC_API_KEY")
        print("         确定性部分仍可运行；要用 Agent 请填密钥：")
        print("         1. cp .env.example .env    (Windows: copy .env.example .env)")
        print(f"         2. 编辑 {ENV_FILE} 第 {_key_line()} 行")
        return False
    if not key.startswith("sk-ant-"):
        print(f"{WARN}密钥以 {key[:7]!r} 开头，通常应为 'sk-ant-'")
        return True
    print(f"{OK}ANTHROPIC_API_KEY 已配置（{len(key)} 字符）")
    return True


def check_data() -> bool:
    f = ROOT / "samples" / "hour_2026-08-30T15.json"
    if f.exists():
        print(f"{OK}样本数据 {f.name}")
        return True
    print(f"{BAD}缺少样本数据 -> python samples/seed_hour.py")
    return False


def check_pipeline() -> bool:
    """确定性层能否真的算出数来——比检查文件存在更有说服力。"""
    try:
        from core import flow
        r = flow.energy_flow("2026-08-30T15:00:00+08:00")
        kwh = r["stages"][0]["kwh"]
        print(f"{OK}确定性流水线可运行（本小时 {kwh} kWh）")
        return True
    except Exception as exc:
        print(f"{BAD}确定性流水线失败：{type(exc).__name__}: {exc}")
        return False


def main() -> int:
    print("能碳监测平台 · 环境自检\n")
    sys.path.insert(0, str(ROOT))

    hard = [check_python(),
            check_package("anthropic", "-r requirements.txt", required=True),
            check_data(),
            check_pipeline()]
    check_package("langchain", "-r requirements-langchain.txt", required=False)
    check_package("pytest", "-r requirements-dev.txt", required=False)
    has_key = check_key()

    print()
    if not all(hard):
        print("有必须项未通过，先按上面的提示处理。")
        return 1
    if has_key:
        print("一切就绪。试试： python demo/run_one_agent.py 3")
    else:
        print("确定性部分就绪，可以先跑： python demo/run_hour.py")
        print("填好密钥后再跑：         python demo/run_one_agent.py 3")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
