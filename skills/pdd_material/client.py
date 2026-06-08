from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from playwright.async_api import Browser, BrowserContext, Page


MATERIAL_URL = "https://mms.pinduoduo.com/material/upload"
DIR_LIST_URL = "https://mms.pinduoduo.com/garner/mms/file/dir_list"


@dataclass(frozen=True)
class PDDMaterialFolder:
    id: int
    name: str
    parent_dir_id: int


@dataclass(frozen=True)
class PDDMaterialFile:
    id: int
    filename: str
    name: str
    extension: str
    url: str
    width: int | None
    height: int | None
    size: int | None


class PDDMaterialClient:
    def __init__(self, browser: Browser, storage_state: str | Path | None = None):
        self.browser = browser
        self.storage_state = str(storage_state) if storage_state else None
        self.context: BrowserContext | None = None
        self.page: Page | None = None

    async def __aenter__(self) -> "PDDMaterialClient":
        await self.start()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def start(self) -> None:
        context_kwargs: dict[str, Any] = {}
        if self.storage_state:
            context_kwargs["storage_state"] = self.storage_state
        self.context = await self.browser.new_context(**context_kwargs)
        self.page = await self.context.new_page()
        await self.page.goto(MATERIAL_URL, wait_until="domcontentloaded", timeout=60000)

    async def close(self) -> None:
        if self.context is not None:
            await self.context.close()
        self.context = None
        self.page = None

    async def list_dir(self, dir_id: int = 0, page: int = 1, page_size: int = 100) -> tuple[list[PDDMaterialFolder], list[PDDMaterialFile]]:
        if self.page is None:
            await self.start()
        assert self.page is not None

        response = await self.page.request.post(
            DIR_LIST_URL,
            data={
                "if_query_dir": True,
                "order_by": "create_time desc",
                "dir_id": dir_id,
                "page": page,
                "page_size": page_size,
                "file_param": {"file_type_desc": ""},
                "dir_param": {},
            },
            timeout=60000,
        )
        data = json.loads(await response.text())
        if not data.get("success"):
            raise RuntimeError(f"图片空间目录读取失败: {data.get('error_msg') or data}")

        result = data.get("result") or {}
        folders = [
            PDDMaterialFolder(
                id=int(item["id"]),
                name=str(item["name"]),
                parent_dir_id=int(item.get("parent_dir_id") or 0),
            )
            for item in result.get("dir_list") or []
        ]
        files = [self._parse_file(item) for item in result.get("file_list") or []]
        return folders, files

    async def find_folder(self, parent_dir_id: int, name: str) -> PDDMaterialFolder:
        folders, _ = await self.list_dir(parent_dir_id)
        for folder in folders:
            if folder.name == name:
                return folder

        candidates = ", ".join(folder.name for folder in folders[:20])
        raise FileNotFoundError(f"图片空间找不到文件夹 {name!r}; 当前候选: {candidates}")

    async def resolve_folder_path(self, path: str | list[str]) -> PDDMaterialFolder:
        parts = [part for part in (path if isinstance(path, list) else re.split(r"[\\/]+", path)) if part]
        parent_id = 0
        current: PDDMaterialFolder | None = None
        for part in parts:
            current = await self.find_folder(parent_id, part)
            parent_id = current.id
        if current is None:
            raise ValueError("图片空间路径不能为空")
        return current

    async def list_folder_path(self, path: str | list[str]) -> tuple[PDDMaterialFolder, list[PDDMaterialFolder], list[PDDMaterialFile]]:
        folder = await self.resolve_folder_path(path)
        child_folders, files = await self.list_dir(folder.id)
        return folder, child_folders, files

    def _parse_file(self, item: dict[str, Any]) -> PDDMaterialFile:
        name = str(item.get("name") or "")
        extension = str(item.get("extension") or "")
        filename = f"{name}.{extension}" if extension else name
        extra = item.get("extra_info") or {}
        return PDDMaterialFile(
            id=int(item["id"]),
            filename=filename,
            name=name,
            extension=extension,
            url=str(item.get("url") or ""),
            width=extra.get("width"),
            height=extra.get("height"),
            size=extra.get("size"),
        )
