from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from skills.pdd_material import PDDMaterialClient


async def main() -> None:
    parser = argparse.ArgumentParser(description="列出拼多多图片空间文件夹内容")
    parser.add_argument("path", help="图片空间路径，例如 2026/8250")
    parser.add_argument("--state", default="states/shopA.json", help="拼多多登录态文件")
    args = parser.parse_args()

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            async with PDDMaterialClient(browser, Path(args.state)) as client:
                folder, child_folders, files = await client.list_folder_path(args.path)
                print(f"PATH {args.path}")
                print(f"DIR_ID {folder.id}")
                if child_folders:
                    print("FOLDERS")
                    for child in child_folders:
                        print(f"  {child.name}\t{child.id}")
                if files:
                    print("FILES")
                    for file in files:
                        print(f"  {file.filename}\t{file.width}x{file.height}\t{file.url}")
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
