import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = BASE_DIR / "xhs_xiaodouya_config.json"
POSTER_PATH = BASE_DIR / "xhs_xiaodouya_poster.py"


def load_default_config() -> dict:
    return json.loads(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))


def normalize_account(token: str) -> str:
    raw = token.strip().upper().replace(" ", "")
    if not raw:
        raise ValueError("账号不能为空")
    match = re.fullmatch(r"H?(\d{1,2})", raw)
    if not match:
        raise ValueError(f"账号格式不合法：{token}")
    value = int(match.group(1))
    if value <= 0 or value > 12:
        raise ValueError(f"账号超出范围：{token}")
    return f"H{value:02d}"


def parse_accounts(user_input: str, default_accounts: list[str]) -> list[str]:
    text = user_input.strip()
    if not text:
        return list(default_accounts)

    parts = [part for part in re.split(r"[,，\s]+", text) if part.strip()]
    if not parts:
        return list(default_accounts)

    seen: set[str] = set()
    accounts: list[str] = []
    for part in parts:
        account = normalize_account(part)
        if account in seen:
            continue
        seen.add(account)
        accounts.append(account)
    return accounts


def ask_accounts(default_accounts: list[str]) -> list[str]:
    default_text = ",".join(default_accounts)
    print("=" * 58)
    print("本次小红书发布账号顺序确认")
    print(f"默认顺序：{default_text}")
    print("直接回车：使用默认顺序")
    print("手动输入示例：H1,H2,H8 或 H01,H02,H08")
    print("=" * 58)

    while True:
        user_input = input("请输入本次账号顺序：")
        try:
            accounts = parse_accounts(user_input, default_accounts)
            print(f"本次将按以下顺序循环发布：{','.join(accounts)}")
            confirm = input("确认开始吗？(Y/n)：").strip().lower()
            if confirm in ("", "y", "yes"):
                return accounts
        except ValueError as exc:
            print(f"输入有误：{exc}")


def build_runtime_config(config: dict, accounts: list[str]) -> Path:
    runtime_config = dict(config)
    runtime_config["account_prefixes"] = accounts
    temp_dir = Path(tempfile.gettempdir())
    runtime_path = temp_dir / "xhs_xiaodouya_runtime_config.json"
    runtime_path.write_text(
        json.dumps(runtime_config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return runtime_path


def main() -> int:
    config = load_default_config()
    default_accounts = list(config.get("account_prefixes", []))
    if not default_accounts:
        print("默认配置中没有可用账号。")
        return 1

    accounts = ask_accounts(default_accounts)
    runtime_path = build_runtime_config(config, accounts)
    env = os.environ.copy()
    env["XHS_XIAODOUYA_CONFIG_PATH"] = str(runtime_path)

    try:
        result = subprocess.run([sys.executable, str(POSTER_PATH)], env=env, cwd=str(BASE_DIR))
        return result.returncode
    finally:
        try:
            runtime_path.unlink(missing_ok=True)
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
