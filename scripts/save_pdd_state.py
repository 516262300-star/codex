from __future__ import annotations

import argparse
import asyncio
import time
from pathlib import Path
from typing import Any

import yaml
from playwright.async_api import Page, async_playwright


LOGIN_MARKERS = (
    "login",
    "passport",
    "mobile-login",
)


def load_yaml(path: str | Path = "config.yaml") -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def find_shop(config: dict[str, Any], shop_name: str | None) -> dict[str, Any]:
    pdd = config.get("pdd") or {}
    shops = pdd.get("shops") or []
    target = shop_name or pdd.get("default_shop")

    for shop in shops:
        if shop.get("name") == target:
            return shop

    names = ", ".join(str(shop.get("name")) for shop in shops)
    raise SystemExit(f"找不到店铺配置: {target}. 已配置: {names}")


async def looks_logged_in(page: Page, home_url: str) -> bool:
    url = page.url.lower()
    if any(marker in url for marker in LOGIN_MARKERS):
        return False

    try:
        await page.goto(home_url, wait_until="domcontentloaded", timeout=15000)
    except Exception:
        return False

    url = page.url.lower()
    return not any(marker in url for marker in LOGIN_MARKERS)


async def main() -> None:
    parser = argparse.ArgumentParser(description="保存拼多多商家后台登录态")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--shop", default=None)
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()

    config = load_yaml(args.config)
    pdd = config.get("pdd") or {}
    shop = find_shop(config, args.shop)

    login_url = str(pdd.get("login_url") or "https://mms.pinduoduo.com/")
    home_url = str(pdd.get("home_url") or "https://mms.pinduoduo.com/home")
    timeout_ms = int(pdd.get("wait_login_timeout_ms") or 600000)
    state_path = Path(str(shop["storage_state"]))
    state_path.parent.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=args.headless)
        context = await browser.new_context()
        page = await context.new_page()

        print(f"正在打开拼多多商家后台: {login_url}")
        print("请在弹出的浏览器里完成登录。程序会自动等待并保存登录态。")
        await page.goto(login_url, wait_until="domcontentloaded")

        deadline = time.monotonic() + timeout_ms / 1000
        while time.monotonic() < deadline:
            if await looks_logged_in(page, home_url):
                await context.storage_state(path=str(state_path))
                print(f"登录态已保存: {state_path.resolve()}")
                await browser.close()
                return
            await page.wait_for_timeout(3000)

        await browser.close()
        raise SystemExit("等待登录超时，未保存登录态。请重新运行脚本。")


if __name__ == "__main__":
    asyncio.run(main())
