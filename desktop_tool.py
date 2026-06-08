from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import threading
import time
import webbrowser
from decimal import Decimal
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import yaml

from playwright.async_api import async_playwright

from main import build_dry_run, load_product_meta, money
from skills.erp_price import ERPPriceClient, load_config
from skills.pdd_listing import build_sku_specs, resolve_listing_template


ROOT = Path(__file__).resolve().parent
DEFAULT_PRODUCT_FOLDER = Path.home() / "Desktop" / "pdd_upload" / "测试商品001"
ATTRIBUTE_TEMPLATE = ROOT / "templates" / "category_attributes.yaml"
SESSION_PID_PATH = ROOT / ".tmp_tool" / "pdd_session.pid"
COMMAND_PATH = ROOT / ".tmp_tool" / "pdd_category_command.json"
COMMAND_STATUS_PATH = ROOT / ".tmp_tool" / "pdd_category_command_status.json"
PLUGIN_PRODUCT_STATUS_PATH = ROOT / ".tmp_tool" / "plugin_product_status.json"
MATERIAL_REQUEST_PATH = ROOT / ".tmp_tool" / "plugin_material_request.json"
MATERIAL_RESPONSE_PATH = ROOT / ".tmp_tool" / "plugin_material_response.json"
TITLE_CACHE_PATH = ROOT / ".tmp_tool" / "title_candidates.json"
PLUGIN_STATUS_LOCK = threading.Lock()
MATERIAL_OPTIONS = ("黄铜", "锌合金", "铝合金")

TITLE_CANDIDATE_PATTERNS = [
    "法式复古柜门拉手中古风抽屉衣柜橱柜现代简约轻奢柜子单孔小把手",
    "法式复古古铜色柜门拉手中古风抽屉衣柜橱柜现代简约轻奢单孔把手",
    "中古风柜门拉手抽屉衣柜橱柜法式复古现代简约轻奢柜子单孔把手",
    "现代极简柜门拉手法式复古中古风抽屉衣柜橱柜轻奢柜子单孔小把手",
    "新中式柜门拉手中古风法式复古抽屉衣柜橱柜现代简约轻奢单孔把手",
    "包豪斯柜门拉手中古风法式复古抽屉衣柜橱柜现代简约轻奢单孔把手",
]

BRASS_TITLE_CANDIDATE_PATTERNS = [
    "中古风黄铜柜门拉手抽屉现代简约法式复古轻奢衣橱柜门新中式把手",
    "法式复古黄铜柜门拉手中古风抽屉衣柜橱柜现代简约轻奢单孔小把手",
    "法式复古黄铜柜门拉手古铜色中古风抽屉衣柜橱柜简约轻奢单孔把手",
    "中古风黄铜柜门拉手法式复古抽屉衣柜橱柜现代简约轻奢单孔把手",
]


def json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Object is not JSON serializable: {type(value)!r}")


def natural_key(text: str) -> tuple[int, str]:
    match = re.search(r"\d+", text)
    stem = Path(text).stem
    if not match and stem in {"主图", "详情页"}:
        return (0, text.lower())
    return (int(match.group(0)) if match else 999999, text.lower())


def compact_name(text: str) -> str:
    stem = Path(text).stem
    return re.sub(r"[\s#/_\\\-.]+", "", stem).lower()


def is_process_running(pid: int) -> bool:
    if os.name == "nt":
        completed = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        return str(pid) in completed.stdout

    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def is_session_running() -> bool:
    if not SESSION_PID_PATH.exists():
        return False
    try:
        pid = int(SESSION_PID_PATH.read_text(encoding="utf-8").strip())
    except ValueError:
        return False
    running = is_process_running(pid)
    if not running:
        try:
            SESSION_PID_PATH.unlink()
        except FileNotFoundError:
            pass
    return running


def start_pdd_session() -> None:
    if is_session_running():
        return

    script = ROOT / "scripts" / "open_pdd_category.py"
    proc = subprocess.Popen(
        [sys.executable, str(script)],
        cwd=str(ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
    )
    SESSION_PID_PATH.parent.mkdir(parents=True, exist_ok=True)
    SESSION_PID_PATH.write_text(str(proc.pid), encoding="utf-8")
    time.sleep(2)


def send_session_command(action: str, payload: dict[str, Any] | None = None, timeout_s: int = 600) -> Any:
    start_pdd_session()
    command = {
        "id": str(int(time.time() * 1000)),
        "action": action,
        "payload": payload or {},
    }
    COMMAND_PATH.parent.mkdir(parents=True, exist_ok=True)
    COMMAND_PATH.write_text(json.dumps(command, ensure_ascii=False, indent=2), encoding="utf-8")

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if COMMAND_STATUS_PATH.exists():
            status = json.loads(COMMAND_STATUS_PATH.read_text(encoding="utf-8"))
            if str(status.get("id")) == command["id"]:
                if status.get("status") == "failed":
                    raise RuntimeError(str(status.get("error") or "拼多多会话命令失败"))
                if status.get("status") == "done":
                    return status.get("results")
        time.sleep(0.5)

    raise TimeoutError("等待拼多多会话执行命令超时")


def wait_session_command_status(command_id: str, timeout_s: int = 120) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if COMMAND_STATUS_PATH.exists():
            status = json.loads(COMMAND_STATUS_PATH.read_text(encoding="utf-8"))
            if str(status.get("id")) == command_id:
                return status
        time.sleep(0.5)
    raise TimeoutError("等待拼多多会话执行命令超时")


def default_price_multiplier(product_folder: str | Path = DEFAULT_PRODUCT_FOLDER) -> str:
    try:
        return str(load_product_meta(Path(product_folder)).price_multiplier)
    except Exception:
        return ""


def default_material(product_folder: str | Path = DEFAULT_PRODUCT_FOLDER) -> str:
    try:
        return str(load_product_meta(Path(product_folder)).material)
    except Exception:
        return MATERIAL_OPTIONS[0]


def update_product_material(product_folder: str, material: str) -> dict[str, Any]:
    selected = material.strip()
    if selected not in MATERIAL_OPTIONS:
        raise ValueError(f"材质只能选择：{'、'.join(MATERIAL_OPTIONS)}")

    folder = Path(product_folder).expanduser().resolve()
    meta_path = folder / "meta.yaml"
    if not meta_path.exists():
        raise FileNotFoundError(f"缺少 meta.yaml: {meta_path}")

    with meta_path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    raw["material"] = selected
    with meta_path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(raw, fh, allow_unicode=True, sort_keys=False)

    if TITLE_CACHE_PATH.exists():
        try:
            cached = json.loads(TITLE_CACHE_PATH.read_text(encoding="utf-8"))
            cached_folder = Path(str(cached.get("product_folder") or "")).expanduser()
            if cached_folder.resolve() == folder:
                TITLE_CACHE_PATH.unlink()
        except Exception:
            TITLE_CACHE_PATH.unlink(missing_ok=True)

    return {"product_folder": str(folder), "material": selected, "note": "材质已保存，标题候选会按新材质重新生成。"}


async def dry_run_payload(product_folder: str, price_multiplier: str | None = None) -> dict[str, Any]:
    folder = Path(product_folder).expanduser().resolve()
    multiplier = Decimal(str(price_multiplier)) if price_multiplier else None
    meta, main_images, detail_images, skus = await build_dry_run(folder, price_multiplier=multiplier)
    listing_template = resolve_listing_template(meta, ATTRIBUTE_TEMPLATE)
    return {
        "product_folder": str(folder),
        "meta": {
            "erp_model": meta.erp_model,
            "category_path": meta.category_path,
            "price_multiplier": str(meta.price_multiplier),
            "material": meta.material,
            "color": meta.color,
            "stock_per_sku": meta.stock_per_sku,
        },
        "listing_template": listing_template,
        "main_images": [image.name for image in main_images],
        "detail_images": [image.name for image in detail_images],
        "skus": [
            {
                "sku_name": sku.sku_name,
                "price_book_name": sku.price_book_name,
                "price_book_color": sku.price_book_color,
                "image": sku.image_path.name,
                "base_price": str(sku.base_price),
                "group_price": str(sku.group_price),
                "single_price": str(sku.single_price),
                "final_price": str(sku.group_price),
                "stock": sku.stock,
            }
            for sku in skus
        ],
    }


def read_material_plugin_request() -> dict[str, Any]:
    if MATERIAL_REQUEST_PATH.exists():
        try:
            return json.loads(MATERIAL_REQUEST_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def write_material_plugin_response(payload: dict[str, Any]) -> dict[str, Any]:
    MATERIAL_RESPONSE_PATH.parent.mkdir(parents=True, exist_ok=True)
    MATERIAL_RESPONSE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"code": 0, "msg": "ok", "data": payload}


async def material_payload(material_path: str) -> dict[str, Any]:
    request_id = int(time.time() * 1000)
    request = {
        "id": request_id,
        "path": material_path,
        "status": "pending",
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    MATERIAL_REQUEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MATERIAL_REQUEST_PATH.write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")
    MATERIAL_RESPONSE_PATH.unlink(missing_ok=True)

    webbrowser.open("https://mms.pinduoduo.com/material/upload")
    deadline = time.time() + 180
    while time.time() < deadline:
        if MATERIAL_RESPONSE_PATH.exists():
            try:
                response = json.loads(MATERIAL_RESPONSE_PATH.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                await asyncio.sleep(0.5)
                continue
            if int(response.get("id") or 0) != request_id:
                await asyncio.sleep(0.5)
                continue
            if response.get("error"):
                raise RuntimeError(str(response.get("error")))
            data = response.get("data")
            if isinstance(data, dict):
                request["status"] = "done"
                MATERIAL_REQUEST_PATH.write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")
                return data
        await asyncio.sleep(0.5)

    raise TimeoutError(
        "当前 Chrome 插件没有回传图片空间数据。请确认 PDD商品发布助手已重新加载，且当前 Chrome 已登录拼多多后台。"
    )


def find_child_files(material: dict[str, Any], folder_name: str) -> list[dict[str, Any]]:
    children = material.get("children") or {}
    if folder_name not in children:
        candidates = ", ".join(children.keys())
        raise FileNotFoundError(f"图片空间缺少 {folder_name} 文件夹；当前有: {candidates}")
    return list(children[folder_name])


def find_matching_file(files: list[dict[str, Any]], expected_name: str) -> dict[str, Any]:
    expected = compact_name(expected_name)
    for file in files:
        if compact_name(str(file.get("filename") or "")) == expected:
            return file

    for file in files:
        actual = compact_name(str(file.get("filename") or ""))
        if expected in actual or actual in expected:
            return file

    candidates = ", ".join(str(file.get("filename") or "") for file in files)
    raise FileNotFoundError(f"图片空间找不到匹配图片 {expected_name}; 当前候选: {candidates}")


def material_file_sku_name(file: dict[str, Any]) -> str:
    return Path(str(file.get("filename") or "")).stem.strip()


def material_sku_sort_key(file: dict[str, Any]) -> tuple[Any, ...]:
    return natural_key(str(file.get("filename") or ""))


def parse_material_sku_lookup(sku_name: str) -> tuple[str, str | None]:
    stem = Path(sku_name).stem.strip()
    parts = [part.strip() for part in re.split(r"[-_#\s]+", stem) if part.strip()]
    if len(parts) >= 3 and re.fullmatch(r"\d+[A-Za-z]*", parts[0]):
        tail = parts[-1]
        if re.fullmatch(r"\d+|单孔|吊坠|直径|\d+直径", tail):
            return f"{parts[0]}-{tail}", "-".join(parts[1:-1])
    return stem, None


def summarize_sku_models(sku_rows: list[dict[str, Any]], fallback: str) -> str:
    models: list[str] = []
    for row in sku_rows:
        match = re.match(r"\d+[A-Za-z]*", str(row.get("sku_name") or ""))
        if match and match.group(0) not in models:
            models.append(match.group(0))
    if not models:
        return fallback
    if len(models) == 1:
        return models[0]
    return f"{models[0]}-{models[-1]}"


async def material_sku_rows_from_image_space(
    product_folder: str,
    material_sku: list[dict[str, Any]],
    price_multiplier: str | None = None,
) -> list[dict[str, Any]]:
    folder = Path(product_folder).expanduser().resolve()
    meta = load_product_meta(folder)
    multiplier = Decimal(str(price_multiplier)) if price_multiplier else meta.price_multiplier
    config = load_config("config.yaml")
    rows: list[dict[str, Any]] = []

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            async with ERPPriceClient(browser, config) as erp:
                for image in sorted(material_sku, key=material_sku_sort_key):
                    sku_name = material_file_sku_name(image)
                    lookup_name, color = parse_material_sku_lookup(sku_name)
                    quote = await erp.get_price_quote(lookup_name, color=color)
                    group_price = money(quote.price * multiplier)
                    single_price = money(group_price + Decimal("1"))
                    rows.append(
                        {
                            "sku_name": sku_name,
                            "price_book_name": quote.product_name,
                            "price_book_color": quote.color_name,
                            "image": str(image.get("filename") or ""),
                            "base_price": str(quote.price),
                            "group_price": str(group_price),
                            "single_price": str(single_price),
                            "final_price": str(group_price),
                            "stock": meta.stock_per_sku,
                            "material_image": image,
                            "price_lookup_name": lookup_name,
                            "price_lookup_color": color or "",
                        }
                    )
        finally:
            await browser.close()

    return rows


async def upload_plan_payload(product_folder: str, material_path: str, price_multiplier: str | None = None) -> dict[str, Any]:
    write_plugin_status({"id": int(time.time()), "query_count": 0, "status": 0})
    if not str(price_multiplier or "").strip():
        raise ValueError("请先填写价格倍数")
    if not str(material_path or "").strip():
        raise ValueError("请先填写图片空间路径")
    dry = await dry_run_payload(product_folder, price_multiplier=price_multiplier)
    material = await material_payload(material_path)

    material_main = find_child_files(material, "主图")
    material_detail = find_child_files(material, "详情页")
    material_sku = find_child_files(material, "尺寸图")

    main_images = sorted(material_main, key=lambda item: natural_key(str(item.get("filename") or "")))
    detail_images = sorted(material_detail, key=lambda item: natural_key(str(item.get("filename") or "")))
    sku_rows = []
    sku_source = "local_product_folder"
    try:
        for sku in dry["skus"]:
            matched = find_matching_file(material_sku, str(sku["sku_name"]))
            sku_rows.append({**sku, "material_image": matched})
    except FileNotFoundError as exc:
        local_skus = [str(sku.get("sku_name") or "") for sku in dry["skus"]]
        material_skus = [material_file_sku_name(file) for file in sorted(material_sku, key=material_sku_sort_key)]
        if not material_skus:
            raise
        sku_rows = await material_sku_rows_from_image_space(
            product_folder,
            material_sku,
            price_multiplier=price_multiplier,
        )
        sku_source = "image_space_size_images"
        dry["sku_source_warning"] = (
            "本地商品文件夹的尺寸图和图片空间不一致，已改用图片空间“尺寸图”文件名生成 SKU。"
            f" 本地 SKU: {', '.join(local_skus[:8])}; 图片空间 SKU: {', '.join(material_skus[:8])}"
        )

    package_erp_model = summarize_sku_models(sku_rows, str(dry["meta"]["erp_model"])) if sku_source == "image_space_size_images" else str(dry["meta"]["erp_model"])
    if sku_source == "image_space_size_images":
        dry["meta"]["erp_model"] = package_erp_model
        listing_template = dry.get("listing_template") or {}
        listing = listing_template.get("template") or {}
        title_template = str(listing.get("title_template") or "")
        if title_template:
            listing["title_template"] = re.sub(r"\b\d+[A-Za-z]*(?:-\d+[A-Za-z]*)?\b", package_erp_model, title_template, count=1)
    sku_specs = build_sku_specs(sku_rows, erp_model=package_erp_model)
    package = {
        "product_folder": dry["product_folder"],
        "material_path": material_path,
        "erp_model": package_erp_model,
        "category_path": (dry.get("listing_template") or {}).get("matched_category_path") or dry["meta"]["category_path"],
        "category_keyword": "小拉手",
        "price_multiplier": dry["meta"]["price_multiplier"],
        "main_images": [
            {
                "index": index,
                "filename": str(image.get("filename") or ""),
                "url": str(image.get("url") or ""),
                "width": image.get("width"),
                "height": image.get("height"),
            }
            for index, image in enumerate(main_images, start=1)
        ],
        "detail_images": [
            {
                "index": index,
                "filename": str(image.get("filename") or ""),
                "url": str(image.get("url") or ""),
                "width": image.get("width"),
                "height": image.get("height"),
            }
            for index, image in enumerate(detail_images, start=1)
        ],
        "sku_specs": sku_specs,
        "checks": {
            "main_image_count": len(main_images),
            "detail_image_count": len(detail_images),
            "sku_count": len(sku_specs),
            "spec_type": "型号",
            "spec_code_rule": "价格册完整型号名称#颜色",
            "sku_source": sku_source,
        },
    }
    dry["meta"]["erp_model"] = package_erp_model
    listing_template = dry.get("listing_template") or {}
    listing = listing_template.get("template") or {}
    title_template = str(listing.get("title_template") or "")
    if title_template:
        listing["title_template"] = re.sub(r"\b\d+[A-Za-z]*(?:-\d+[A-Za-z]*)?\b", package_erp_model, title_template, count=1)
    package_path = ROOT / ".tmp_tool" / "listing_asset_package.json"
    package_path.parent.mkdir(parents=True, exist_ok=True)
    package_path.write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8")
    write_plugin_status({"id": int(time.time()), "query_count": 0, "status": 0})

    return {
        "product_folder": dry["product_folder"],
        "material_path": material_path,
        "meta": dry["meta"],
        "listing_template": dry["listing_template"],
        "main_images": main_images,
        "detail_images": detail_images,
        "skus": sku_rows,
        "package": package,
        "package_path": str(package_path),
        "sku_source": sku_source,
        "sku_source_warning": dry.get("sku_source_warning") or "",
        "source": {
            "local_main_images": dry["main_images"],
            "local_detail_images": dry["detail_images"],
            "material_dir_id": material["dir_id"],
        },
    }


async def prepare_listing_payload(
    product_folder: str,
    material_path: str,
    price_multiplier: str | None = None,
    material_choice: str | None = None,
) -> dict[str, Any]:
    write_plugin_status({"id": int(time.time()), "query_count": 0, "status": 0})
    if not str(material_choice or "").strip():
        raise ValueError("请先选择材质")
    update_product_material(product_folder, str(material_choice))
    return await upload_plan_payload(product_folder, material_path, price_multiplier=price_multiplier)


async def open_category_page_payload() -> dict[str, Any]:
    package_path = ROOT / ".tmp_tool" / "listing_asset_package.json"
    if not package_path.exists():
        raise FileNotFoundError("还没有上架包。请先点第 1 步“生成上架包”。")
    package = json.loads(package_path.read_text(encoding="utf-8"))
    folder = Path(str(package.get("product_folder") or DEFAULT_PRODUCT_FOLDER)).expanduser().resolve()
    if not cached_recommended_title(folder):
        generate_title_payload(str(folder))
    write_plugin_status({"id": int(time.time()), "query_count": 0, "status": 0})
    result = send_session_command("open_category", {}, timeout_s=60) or {}
    return {
        "title": result.get("title") or "发布新商品",
        "url": result.get("url") or "https://mms.pinduoduo.com/goods/category",
        "note": "已复用同一个拼多多会话浏览器。如果看到滑块验证，请先手动完成；完成后再继续下一步填充。",
    }


def category_snapshot_payload() -> dict[str, Any]:
    snapshot_path = ROOT / ".tmp_tool" / "pdd_category_snapshot.json"
    if not snapshot_path.exists():
        raise FileNotFoundError("还没有发布会话快照。请先点“打开发布页测试”。")
    return json.loads(snapshot_path.read_text(encoding="utf-8"))


def pdd_title_byte_length(title: str) -> int:
    return sum(1 if ord(ch) < 128 else 2 for ch in title)


def split_title_zones(title: str) -> dict[str, str]:
    zones: list[str] = []
    index = 0
    for _ in range(2):
        used = 0
        chars: list[str] = []
        while index < len(title):
            width = 1 if ord(title[index]) < 128 else 2
            if used + width > 20:
                break
            chars.append(title[index])
            used += width
            index += 1
        zones.append("".join(chars))
    zones.append(title[index:])
    return {"front": zones[0], "middle": zones[1], "back": zones[2]}


def collect_title_signals(folder: Path, package: dict[str, Any] | None = None) -> dict[str, Any]:
    meta = load_product_meta(folder)
    package = package or {}
    package_folder_raw = str(package.get("product_folder") or "").strip()
    package_matches_folder = False
    if package_folder_raw:
        try:
            package_matches_folder = Path(package_folder_raw).expanduser().resolve() == folder
        except OSError:
            package_matches_folder = False
    package_erp_model = str(package.get("erp_model") or "").strip() if package_matches_folder else ""
    sku_texts: list[str] = []
    if package_matches_folder:
        for spec in package.get("sku_specs") or []:
            for key in ("spec_name", "spec_code", "price_book_color", "material_image_filename"):
                value = str(spec.get(key) or "").strip()
                if value:
                    sku_texts.append(value)
    joined = " ".join([meta.color or "", meta.material or "", *sku_texts])
    colors = [word for word in ("古铜色", "铜本色", "铬色", "银色", "钛银色", "黑色", "金色") if word in joined]
    return {
        "erp_model": package_erp_model or meta.erp_model,
        "category_path": meta.category_path,
        "material": meta.material,
        "color": meta.color,
        "colors": colors,
        "has_brass": "黄铜" in joined,
        "has_ancient_copper": "古铜色" in joined,
    }


def title_candidate_reason(title: str, signals: dict[str, Any]) -> str:
    if "黄铜" in title:
        return "适合黄铜材质商品，前段保留黄铜和柜门拉手，兼顾中古风、法式复古等装修词。"
    if "古铜色" in title:
        return "适合有古铜色 SKU 的商品，前段放法式复古和古铜色，后段保留单孔把手。"
    if title.startswith("法式复古"):
        return "默认推荐，前段是法式复古+柜门拉手，兼顾中古风和现代简约。"
    if title.startswith("中古风"):
        return "偏中古风流量，适合主图视觉更复古的款。"
    if title.startswith("现代极简"):
        return "偏现代极简和轻奢，适合主图更干净简约的款。"
    if title.startswith("新中式"):
        return "偏新中式装修词，适合中式或宋式氛围图。"
    if title.startswith("包豪斯"):
        return "偏设计风格词，适合线条更利落的款。"
    return "按标题权重分前中后三段组合。"


def generate_title_payload(product_folder: str) -> dict[str, Any]:
    folder = Path(product_folder).expanduser().resolve()
    package_path = ROOT / ".tmp_tool" / "listing_asset_package.json"
    package = json.loads(package_path.read_text(encoding="utf-8")) if package_path.exists() else {}
    signals = collect_title_signals(folder, package)
    candidate_patterns = list(TITLE_CANDIDATE_PATTERNS)
    if signals["has_brass"]:
        candidate_patterns = BRASS_TITLE_CANDIDATE_PATTERNS + candidate_patterns

    candidates: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    for title in candidate_patterns:
        if title in seen_titles:
            continue
        seen_titles.add(title)
        if "古铜色" in title and not signals["has_ancient_copper"]:
            continue
        byte_length = pdd_title_byte_length(title)
        if byte_length > 60:
            continue
        zones = split_title_zones(title)
        candidates.append(
            {
                "title": title,
                "byte_length": byte_length,
                "char_units": byte_length / 2,
                "front": zones["front"],
                "middle": zones["middle"],
                "back": zones["back"],
                "reason": title_candidate_reason(title, signals),
            }
        )

    candidates.sort(
        key=lambda item: (
            0 if "黄铜" in item["title"] and signals["has_brass"] else 1,
            0 if "古铜色" in item["title"] and signals["has_ancient_copper"] else 1,
            -item["byte_length"],
        )
    )
    candidates = candidates[:6]
    recommended = candidates[0]["title"] if candidates else ""
    payload = {
        "product_folder": str(folder),
        "erp_model": signals["erp_model"],
        "material": signals["material"],
        "color": signals["color"],
        "colors": signals["colors"],
        "recommended_title": recommended,
        "candidates": candidates,
        "note": "只生成标题候选并缓存推荐标题；不会自动填写拼多多页面，也不会填写商品属性。",
    }
    TITLE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    TITLE_CACHE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def select_title_payload(product_folder: str, title: str) -> dict[str, Any]:
    folder = Path(product_folder).expanduser().resolve()
    selected = title.strip()
    if not selected:
        raise ValueError("标题不能为空")
    byte_length = pdd_title_byte_length(selected)
    if byte_length > 60:
        raise ValueError(f"标题超过 60 字节：当前 {byte_length} 字节")

    payload = generate_title_payload(str(folder))
    known_titles = {str(item.get("title") or "") for item in payload.get("candidates") or []}
    if selected not in known_titles:
        zones = split_title_zones(selected)
        payload.setdefault("candidates", []).insert(
            0,
            {
                "title": selected,
                "byte_length": byte_length,
                "char_units": byte_length / 2,
                "front": zones["front"],
                "middle": zones["middle"],
                "back": zones["back"],
                "reason": "手动选用标题。",
            },
        )

    payload["recommended_title"] = selected
    payload["selected_title"] = selected
    payload["selected_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    payload["note"] = "已选用该标题；后续自动上架读取商品数据时会优先使用它。"
    for item in payload.get("candidates") or []:
        item["selected"] = str(item.get("title") or "") == selected

    TITLE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    TITLE_CACHE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def cached_recommended_title(folder: Path) -> str:
    if not TITLE_CACHE_PATH.exists():
        return ""
    try:
        payload = json.loads(TITLE_CACHE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return ""
    cached_folder = Path(str(payload.get("product_folder") or "")).expanduser()
    try:
        if cached_folder.resolve() != folder.resolve():
            return ""
    except OSError:
        return ""
    return str(payload.get("recommended_title") or "")


async def fill_basic_info_payload(product_folder: str, price_multiplier: str | None = None) -> dict[str, Any]:
    folder = Path(product_folder).expanduser().resolve()
    meta = load_product_meta(folder)
    listing_template = resolve_listing_template(meta, ATTRIBUTE_TEMPLATE)
    listing = listing_template["template"]
    payload = {
        "title": cached_recommended_title(folder) or listing.get("title_template") or "",
        "attributes": listing.get("attributes") or {},
        "category": listing_template.get("matched_category_path") or meta.category_path,
        "category_keyword": "小拉手",
    }
    results = send_session_command("fill_basic_info", payload, timeout_s=180)
    return {
        "command": {"action": "fill_basic_info", "payload": payload},
        "status": {"status": "done", "results": results},
        "note": "已填标题和通用属性；不会保存草稿、不会提交上架。",
    }


def fill_specs_payload() -> dict[str, Any]:
    package_path = ROOT / ".tmp_tool" / "listing_asset_package.json"
    if not package_path.exists():
        raise FileNotFoundError("还没有图片和规格包。请先点“生成图片和规格包”，扫码读取图片空间并核对无误。")

    package = json.loads(package_path.read_text(encoding="utf-8"))
    payload = {"asset_package": package}
    results = send_session_command("fill_specs", payload, timeout_s=180)
    return {
        "command": {"action": "fill_specs", "payload": payload},
        "status": {"status": "done", "results": results},
        "package_path": str(package_path),
        "note": "已发送规格价格测试命令。若当前在选择分类页，会先选“小拉手”进入编辑页，再读取规格区域；不会保存草稿、不会提交上架。",
    }


async def auto_fill_listing_payload(product_folder: str) -> dict[str, Any]:
    snapshot_path = ROOT / ".tmp_tool" / "pdd_category_snapshot.json"
    current_url = ""
    if snapshot_path.exists():
        try:
            current_url = str(json.loads(snapshot_path.read_text(encoding="utf-8")).get("url") or "")
        except json.JSONDecodeError:
            current_url = ""

    opened: dict[str, Any] | None = None
    if "/goods/goods_add/" not in current_url:
        opened = await open_category_page_payload()

    basic = await fill_basic_info_payload(product_folder)

    def has_title_filled(result: dict[str, Any]) -> bool:
        rows = ((result.get("status") or {}).get("results") or [])
        return any(
            str(row.get("field") or "") == "商品标题"
            and str(row.get("status") or "") in {"filled", "cleaned", "already_ok"}
            for row in rows
            if isinstance(row, dict)
        )

    specs = fill_specs_payload()
    retry_basic: dict[str, Any] | None = None
    retry_specs: dict[str, Any] | None = None
    if not has_title_filled(basic):
        retry_basic = await fill_basic_info_payload(product_folder)
        retry_specs = fill_specs_payload()

    return {
        "opened": opened,
        "basic": basic,
        "retry_basic": retry_basic,
        "specs": specs,
        "retry_specs": retry_specs,
        "note": "已执行自动填充：类目/标题/属性/规格/价格。当前不会保存草稿，也不会提交上架。",
    }


async def plugin_queue_payload(product_folder: str) -> dict[str, Any]:
    package_path = ROOT / ".tmp_tool" / "listing_asset_package.json"
    if not package_path.exists():
        raise FileNotFoundError("还没有上架包。请先点第 1 步“生成上架包”。")

    package = json.loads(package_path.read_text(encoding="utf-8"))
    folder = Path(str(package.get("product_folder") or product_folder or DEFAULT_PRODUCT_FOLDER)).expanduser().resolve()
    if not cached_recommended_title(folder):
        generate_title_payload(str(folder))

    task_id = int(time.time())
    url = "https://mms.pinduoduo.com/goods/category"
    write_plugin_status({
        "id": task_id,
        "query_count": 1,
        "status": 0,
        "progress": {
            "stage": "queued",
            "message": "上架任务已排队，等待当前 Chrome 发布页插件接收",
            "page_type": "",
            "url": url,
            "ok": True,
            "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        },
    })
    webbrowser.open(url)
    return {
        "id": task_id,
        "url": url,
        "status": {"status": "queued", "query_count": 1},
        "note": "已切回插件模式：不会打开独立测试浏览器；请在你当前 Chrome 的拼多多页面中扫码/登录，插件会读取这条任务并填充商品。",
    }


def read_plugin_status() -> dict[str, Any]:
    default = {
        "id": int(time.time()),
        "query_count": 0,
        "status": 0,
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    if not PLUGIN_PRODUCT_STATUS_PATH.exists():
        return default
    with PLUGIN_STATUS_LOCK:
        text = PLUGIN_PRODUCT_STATUS_PATH.read_text(encoding="utf-8-sig").strip()
    if not text:
        return default
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        try:
            data, _ = json.JSONDecoder().raw_decode(text)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
    return default


def write_plugin_status(status: dict[str, Any]) -> None:
    status["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    PLUGIN_PRODUCT_STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = PLUGIN_PRODUCT_STATUS_PATH.with_suffix(".json.tmp")
    with PLUGIN_STATUS_LOCK:
        tmp_path.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(PLUGIN_PRODUCT_STATUS_PATH)


def update_plugin_progress(payload: dict[str, Any]) -> dict[str, Any]:
    status = read_plugin_status()
    progress = {
        "stage": str(payload.get("stage") or ""),
        "message": str(payload.get("message") or ""),
        "page_type": str(payload.get("page_type") or ""),
        "url": str(payload.get("url") or ""),
        "ok": bool(payload.get("ok", True)),
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    if "detail" in payload:
        progress["detail"] = payload.get("detail")
    status["progress"] = progress
    if progress["stage"] in {"done", "error", "queued"}:
        status["status_text"] = progress["stage"]
    write_plugin_status(status)
    return {"code": 0, "msg": "ok", "data": status}


def listing_attributes_array(attributes: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for name, value in attributes.items():
        if isinstance(value, list):
            shown = "/".join(str(item) for item in value if str(item).strip())
        else:
            shown = str(value).strip()
        if shown:
            rows.append({"name": str(name), "value": shown})
    return rows


def plugin_product_json(package: dict[str, Any]) -> dict[str, Any]:
    folder = Path(str(package.get("product_folder") or DEFAULT_PRODUCT_FOLDER)).expanduser().resolve()
    meta = load_product_meta(folder)
    listing_template = resolve_listing_template(meta, ATTRIBUTE_TEMPLATE)
    listing = listing_template["template"]
    generated_title = cached_recommended_title(folder) or str(listing.get("title_template") or "")
    category_path = str(package.get("category_path") or listing_template.get("matched_category_path") or meta.category_path)
    category_parts = [part.strip() for part in category_path.split(">") if part.strip()]
    category_parts += [""] * (4 - len(category_parts))

    main_images = {
        f"image{index}": item.get("url")
        for index, item in enumerate(package.get("main_images") or [], start=1)
        if item.get("url")
    }
    detail_images = [
        item.get("url")
        for item in package.get("detail_images") or []
        if item.get("url")
    ]
    sku_specs = list(package.get("sku_specs") or [])
    skus = [
        {
            "specs": [{"key": str(spec.get("spec_type") or "型号"), "value": str(spec.get("spec_name") or "")}],
            "stock": int(spec.get("stock") or 0),
            "price": str(spec.get("group_price") or ""),
            "marketPrice": str(spec.get("single_price") or ""),
            "productCode": str(spec.get("spec_code") or ""),
            "image": str(spec.get("material_image_url") or ""),
        }
        for spec in sku_specs
    ]

    return {
        "title": generated_title,
        "cat1Name": category_parts[0],
        "cat2Name": category_parts[1],
        "cat3Name": category_parts[2],
        "cat4Name": category_parts[3],
        "carouselImages": main_images,
        "detailImages": detail_images,
        "attributes": listing_attributes_array(dict(listing.get("attributes") or {})),
        "skuAxes": [
            {
                "typeName": "型号",
                "values": [str(spec.get("spec_name") or "") for spec in sku_specs],
            }
        ],
        "skus": skus,
        "marketPrice": max((Decimal(str(spec.get("single_price") or "0")) for spec in sku_specs), default=Decimal("0")),
        "batchDiscount": "9.5",
        "productCode": str(package.get("erp_model") or ""),
        "_localSafetyMode": True,
    }


def plugin_product_store_list() -> dict[str, Any]:
    package_path = ROOT / ".tmp_tool" / "listing_asset_package.json"
    if not package_path.exists():
        return {"code": 0, "msg": "ok", "data": {"list": [], "total": 0}}

    status = read_plugin_status()
    package = json.loads(package_path.read_text(encoding="utf-8"))
    product_data = plugin_product_json(package)
    item = {
        "id": int(status.get("id") or int(time.time())),
        "product_name": product_data.get("title") or str(package.get("erp_model") or "待上架商品"),
        "json_data": json.dumps(product_data, ensure_ascii=False, default=json_default),
        "query_count": int(status.get("query_count") or 0),
        "status": int(status.get("status") or 0),
        "data_source": "codex_local_workbench",
    }
    items = [item] if item["query_count"] > 0 else []
    return {"code": 0, "msg": "ok", "data": {"list": items, "total": len(items)}}


def plugin_product_store_update(payload: dict[str, Any]) -> dict[str, Any]:
    status = read_plugin_status()
    for key in ("id", "query_count", "status"):
        if key in payload:
            status[key] = payload[key]
    write_plugin_status(status)
    return {"code": 0, "msg": "ok", "data": status}


HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>拼多多自动上架工作台</title>
  <style>
    :root {
      --bg: #f6f7f9;
      --panel: #ffffff;
      --text: #17202a;
      --muted: #667085;
      --line: #d8dde6;
      --accent: #d93025;
      --accent-dark: #b9251d;
      --ok: #147a4d;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Microsoft YaHei", "Segoe UI", Arial, sans-serif;
      color: var(--text);
      background: var(--bg);
    }
    header {
      height: 58px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 24px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
    }
    h1 { font-size: 18px; margin: 0; font-weight: 650; }
    main {
      display: grid;
      grid-template-columns: 360px 1fr;
      gap: 20px;
      padding: 20px;
      min-height: calc(100vh - 58px);
    }
    section {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 18px;
    }
    h2 { font-size: 15px; margin: 0 0 14px; }
    label {
      display: block;
      font-size: 12px;
      color: var(--muted);
      margin: 14px 0 6px;
    }
    input, select {
      width: 100%;
      height: 38px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 0 10px;
      font-size: 13px;
      background: #fff;
    }
    button {
      height: 38px;
      border: 0;
      border-radius: 6px;
      padding: 0 14px;
      cursor: pointer;
      font-weight: 650;
    }
    .primary { background: var(--accent); color: white; }
    .primary:hover { background: var(--accent-dark); }
    .secondary { background: #edf0f5; color: #1f2937; }
    .actions { display: flex; gap: 10px; margin-top: 16px; }
    .workflow { display: grid; gap: 10px; margin-top: 16px; }
    .workflow button { width: 100%; height: auto; min-height: 46px; text-align: left; line-height: 1.35; }
    .workflow .primary { font-size: 15px; }
    .workflow small { display: block; margin-top: 2px; font-weight: 500; opacity: .82; }
    details { margin-top: 16px; border-top: 1px solid var(--line); padding-top: 12px; }
    summary { cursor: pointer; color: var(--muted); font-size: 13px; font-weight: 650; }
    .hint { color: var(--muted); font-size: 12px; line-height: 1.6; margin-top: 10px; }
    .status { font-size: 13px; color: var(--muted); }
    .grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
    .wide { grid-column: 1 / -1; }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th, td { border-bottom: 1px solid var(--line); padding: 9px 6px; text-align: left; vertical-align: top; }
    th { color: var(--muted); font-weight: 650; }
    ul { margin: 0; padding-left: 18px; }
    .result-title { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
    .pill { color: var(--ok); background: #e8f5ee; padding: 3px 8px; border-radius: 999px; font-size: 12px; }
    .log {
      white-space: pre-wrap;
      background: #111827;
      color: #d1d5db;
      border-radius: 6px;
      padding: 12px;
      min-height: 110px;
      font-family: Consolas, monospace;
      font-size: 12px;
    }
    .progress-box {
      margin-top: 14px;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px;
      background: #f8fafc;
      font-size: 12px;
      line-height: 1.55;
    }
    .progress-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      margin-bottom: 6px;
      font-weight: 650;
      color: #111827;
    }
    .progress-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: #98a2b3;
      display: inline-block;
      margin-right: 6px;
    }
    .progress-dot.running { background: #12b76a; box-shadow: 0 0 0 4px rgba(18, 183, 106, .12); }
    .progress-dot.stale { background: #f79009; box-shadow: 0 0 0 4px rgba(247, 144, 9, .12); }
    .progress-dot.error { background: #e02e24; box-shadow: 0 0 0 4px rgba(224, 46, 36, .12); }
    .progress-message { color: #344054; }
    .progress-meta { color: var(--muted); margin-top: 4px; word-break: break-all; }
    a { color: #0b61a4; word-break: break-all; }
  </style>
</head>
<body>
  <header>
    <h1>拼多多自动上架工作台</h1>
    <div class="status">每次任务扫码登录当前店铺，不绑定固定账号</div>
  </header>
  <main>
    <section>
      <h2>任务设置</h2>
      <label>本地商品文件夹</label>
      <input id="folder" />
      <label>价格倍数</label>
      <input id="priceMultiplier" inputmode="decimal" placeholder="例如 1.6" />
      <label>材质</label>
      <select id="materialSelect">
        <option value="">请选择材质</option>
        <option value="黄铜">黄铜</option>
        <option value="锌合金">锌合金</option>
        <option value="铝合金">铝合金</option>
      </select>
      <label>图片空间路径</label>
      <input id="materialPath" placeholder="例如 2026/8256-8257-8258-8259" />
      <div class="workflow">
        <button class="primary" id="planBtn">1 生成上架包<small>读取图片空间，匹配主图/详情页/尺寸图，计算规格价格</small></button>
        <button class="secondary" id="generateTitleBtn">2 生成/选择标题<small>生成 60 字节标题候选，点“选用”保存</small></button>
        <button class="secondary" id="categoryBtn">3 打开发布页开始填充<small>进入拼多多发布页后，本地助手读取上架包填图片、规格、价格和材质</small></button>
      </div>
      <div class="hint">正常上架只用上面 3 步。下面是排查问题时才用的工具。</div>
      <details>
        <summary>调试工具（平时不用）</summary>
        <div class="actions">
          <button class="secondary" id="dryRunBtn">核对商品</button>
          <button class="secondary" id="materialBtn">单独读取图片空间</button>
        </div>
        <div class="actions">
          <button class="secondary" id="readAttrsBtn">读取属性字段</button>
          <button class="secondary" id="fillBasicBtn">填标题和属性测试</button>
        </div>
        <div class="actions">
          <button class="secondary" id="fillSpecsBtn">填规格价格测试</button>
        </div>
      </details>
      <label>运行日志</label>
      <div class="log" id="log">等待开始。</div>
      <div class="progress-box">
        <div class="progress-head"><span><span class="progress-dot" id="progressDot"></span>自动填充进度</span><span id="progressAge">未开始</span></div>
        <div class="progress-message" id="progressMessage">还没有收到插件心跳。</div>
        <div class="progress-meta" id="progressMeta">开始第三步后，这里会显示当前执行到哪一步。</div>
      </div>
    </section>
    <section>
      <div class="result-title">
        <h2>核对结果</h2>
        <span class="pill" id="statePill">待运行</span>
      </div>
      <div id="results" class="grid"></div>
    </section>
  </main>
  <script>
    const folder = document.getElementById("folder");
    const priceMultiplier = document.getElementById("priceMultiplier");
    const materialSelect = document.getElementById("materialSelect");
    const materialPath = document.getElementById("materialPath");
    const log = document.getElementById("log");
    const results = document.getElementById("results");
    const pill = document.getElementById("statePill");
    const progressDot = document.getElementById("progressDot");
    const progressAge = document.getElementById("progressAge");
    const progressMessage = document.getElementById("progressMessage");
    const progressMeta = document.getElementById("progressMeta");

    function writeLog(text) { log.textContent = text; }
    function setState(text) { pill.textContent = text; }
    function parseLocalTime(text) {
      if (!text) return null;
      const match = String(text).match(/^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})$/);
      if (!match) return null;
      return new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]), Number(match[4]), Number(match[5]), Number(match[6]));
    }
    function setProgressView(progress) {
      progressDot.className = "progress-dot";
      if (!progress || !progress.stage) {
        progressAge.textContent = "未开始";
        progressMessage.textContent = "还没有收到插件心跳。";
        progressMeta.textContent = "开始第三步后，这里会显示当前执行到哪一步。";
        return;
      }
      const updated = parseLocalTime(progress.updated_at);
      const ageSec = updated ? Math.max(0, Math.round((Date.now() - updated.getTime()) / 1000)) : null;
      const stale = ageSec !== null && ageSec > 30 && progress.stage !== "done" && progress.stage !== "error";
      if (progress.stage === "error" || progress.ok === false) progressDot.classList.add("error");
      else if (stale) progressDot.classList.add("stale");
      else if (progress.stage === "done") progressDot.classList.add("running");
      else progressDot.classList.add("running");
      progressAge.textContent = ageSec === null ? "时间未知" : stale ? `${ageSec} 秒无更新，可能卡住` : `${ageSec} 秒前`;
      progressMessage.textContent = progress.message || progress.stage;
      const page = progress.page_type ? `页面：${progress.page_type}` : "";
      const stage = progress.stage ? `步骤：${progress.stage}` : "";
      const url = progress.url ? `地址：${progress.url}` : "";
      progressMeta.textContent = [stage, page, url].filter(Boolean).join(" ｜ ");
    }
    async function refreshProgress() {
      try {
        const response = await fetch("/api/plugin-progress");
        const data = await response.json();
        setProgressView((data.data || {}).progress || null);
      } catch (_) {
        progressDot.className = "progress-dot stale";
        progressAge.textContent = "读取失败";
        progressMessage.textContent = "工作台暂时读取不到插件进度。";
      }
    }
    function requireTaskInputs({needPath = false} = {}) {
      const missing = [];
      if (!priceMultiplier.value.trim()) missing.push("价格倍数");
      if (!materialSelect.value.trim()) missing.push("材质");
      if (needPath && !materialPath.value.trim()) missing.push("图片空间路径");
      if (missing.length) {
        throw new Error(`请先填写：${missing.join("、")}`);
      }
    }
    async function postJSON(url, body) {
      const response = await fetch(url, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
      const data = await response.json();
      if (!response.ok || data.error) throw new Error(data.error || "请求失败");
      return data;
    }
    function escapeHTML(text) {
      return String(text).replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
    }
    function renderDryRun(data) {
      results.innerHTML = `
        <section class="wide"><h2>商品</h2>
          <table><tbody>
            <tr><th>ERP 型号</th><td>${escapeHTML(pack.erp_model || data.meta.erp_model)}</td></tr>
            <tr><th>类目</th><td>${escapeHTML(data.meta.category_path)}</td></tr>
            <tr><th>材质</th><td>${escapeHTML(data.meta.material)}</td></tr>
            <tr><th>倍数</th><td>${escapeHTML(data.meta.price_multiplier)}</td></tr>
          </tbody></table>
        </section>
        <section><h2>主图顺序</h2><ul>${data.main_images.map(x => `<li>${escapeHTML(x)}</li>`).join("")}</ul></section>
        <section><h2>详情页顺序</h2><ul>${data.detail_images.map(x => `<li>${escapeHTML(x)}</li>`).join("")}</ul></section>
        <section class="wide"><h2>SKU 价格</h2>
          <table><thead><tr><th>SKU</th><th>优质价</th><th>拼单价</th><th>单买价</th><th>库存</th><th>规格编码</th><th>图</th></tr></thead>
          <tbody>${data.skus.map(s => `<tr><td>${escapeHTML(s.sku_name)}</td><td>${s.base_price}</td><td>${s.group_price}</td><td>${s.single_price}</td><td>${s.stock}</td><td>${escapeHTML(s.price_book_name)}#${escapeHTML(s.price_book_color)}</td><td>${escapeHTML(s.image)}</td></tr>`).join("")}</tbody></table>
        </section>`;
    }
    function renderMaterial(data) {
      const blocks = Object.entries(data.children).map(([name, files]) => `
        <section class="wide"><h2>${escapeHTML(name)}</h2>
          <table><thead><tr><th>文件名</th><th>尺寸</th><th>链接</th></tr></thead>
          <tbody>${files.map(f => `<tr><td>${escapeHTML(f.filename)}</td><td>${f.width || ""}x${f.height || ""}</td><td><a href="${f.url}" target="_blank">${f.url}</a></td></tr>`).join("")}</tbody></table>
        </section>`).join("");
      results.innerHTML = `<section class="wide"><h2>图片空间 ${escapeHTML(data.path)}</h2><div>目录 ID：${data.dir_id}</div></section>${blocks}`;
    }
    function renderPlan(data) {
      const template = data.listing_template || {};
      const listing = template.template || {};
      const pack = data.package || {};
      const attrRows = Object.entries(listing.attributes || {}).map(([key, value]) => {
        const shown = Array.isArray(value) ? value.join("、") : value;
        return `<tr><th>${escapeHTML(key)}</th><td>${escapeHTML(shown)}</td></tr>`;
      }).join("");
      const serviceRows = Object.entries(listing.services || {}).map(([key, value]) => {
        const shown = Array.isArray(value) ? value.join("、") : value;
        return `<tr><th>${escapeHTML(key)}</th><td>${escapeHTML(shown)}</td></tr>`;
      }).join("");
      const checkRows = Object.entries(pack.checks || {}).map(([key, value]) => `<tr><th>${escapeHTML(key)}</th><td>${escapeHTML(value)}</td></tr>`).join("");
      results.innerHTML = `
        <section class="wide"><h2>图片和规格包</h2>
          <table><tbody>
            <tr><th>商品文件夹</th><td>${escapeHTML(data.product_folder)}</td></tr>
            <tr><th>图片空间</th><td>${escapeHTML(data.material_path)}</td></tr>
            <tr><th>ERP 型号</th><td>${escapeHTML(data.meta.erp_model)}</td></tr>
            <tr><th>价格倍数</th><td>${escapeHTML(data.meta.price_multiplier)}</td></tr>
            <tr><th>SKU 来源</th><td>${escapeHTML(data.sku_source || (pack.checks || {}).sku_source || "")}</td></tr>
            <tr><th>提示</th><td>${escapeHTML(data.sku_source_warning || "")}</td></tr>
            <tr><th>素材包文件</th><td>${escapeHTML(data.package_path || "")}</td></tr>
          </tbody></table>
        </section>
        <section><h2>核对数量</h2>
          <table><tbody>${checkRows}</tbody></table>
        </section>
        <section><h2>规格规则</h2>
          <table><tbody>
            <tr><th>规格类型</th><td>${escapeHTML((pack.checks || {}).spec_type || "型号")}</td></tr>
            <tr><th>规格名称来源</th><td>尺寸图文件名去掉 ERP 型号前缀</td></tr>
            <tr><th>规格编码规则</th><td>${escapeHTML((pack.checks || {}).spec_code_rule || "价格册完整型号名称#颜色")}</td></tr>
          </tbody></table>
        </section>
        <section class="wide"><h2>主图链接顺序</h2>
          <table><thead><tr><th>#</th><th>文件名</th><th>尺寸</th><th>链接</th></tr></thead>
          <tbody>${(pack.main_images || []).map(f => `<tr><td>${f.index}</td><td>${escapeHTML(f.filename)}</td><td>${f.width || ""}x${f.height || ""}</td><td><a href="${f.url}" target="_blank">${f.url}</a></td></tr>`).join("")}</tbody></table>
        </section>
        <section class="wide"><h2>详情页链接顺序</h2>
          <table><thead><tr><th>#</th><th>文件名</th><th>尺寸</th><th>链接</th></tr></thead>
          <tbody>${(pack.detail_images || []).map(f => `<tr><td>${f.index}</td><td>${escapeHTML(f.filename)}</td><td>${f.width || ""}x${f.height || ""}</td><td><a href="${f.url}" target="_blank">${f.url}</a></td></tr>`).join("")}</tbody></table>
        </section>
        <section class="wide"><h2>规格名称、规格编码、尺寸图和价格</h2>
          <table><thead><tr><th>#</th><th>规格类型</th><th>规格名称</th><th>规格编码</th><th>价格册型号</th><th>优质价</th><th>拼单价</th><th>单买价</th><th>库存</th><th>尺寸图文件</th><th>链接</th></tr></thead>
          <tbody>${(pack.sku_specs || []).map(s => `<tr><td>${s.index}</td><td>${escapeHTML(s.spec_type)}</td><td>${escapeHTML(s.spec_name)}</td><td>${escapeHTML(s.spec_code)}</td><td>${escapeHTML(s.price_book_name)}</td><td>${s.base_price}</td><td>${s.group_price}</td><td>${s.single_price}</td><td>${s.stock}</td><td>${escapeHTML(s.material_image_filename)}</td><td><a href="${s.material_image_url}" target="_blank">${s.material_image_url}</a></td></tr>`).join("")}</tbody></table>
        </section>
        <section class="wide"><h2>标题和属性暂存</h2>
          <table><tbody>
            <tr><th>发布类目</th><td>${escapeHTML(template.matched_category_path || data.meta.category_path || "")}</td></tr>
            <tr><th>商品标题</th><td>${escapeHTML(listing.title_template || "")}</td></tr>
          </tbody></table>
        </section>
        <section><h2>商品属性</h2><table><tbody>${attrRows}</tbody></table></section>
        <section><h2>服务与承诺</h2><table><tbody>${serviceRows}</tbody></table></section>`;
    }
    function renderTitle(data) {
      const rows = (data.candidates || []).map((item, index) => `
        <tr>
          <td>${index + 1}</td>
          <td>${escapeHTML(item.title)}</td>
          <td>${item.byte_length}/60</td>
          <td>${escapeHTML(item.front)}</td>
          <td>${escapeHTML(item.middle)}</td>
          <td>${escapeHTML(item.back)}</td>
          <td>${escapeHTML(item.reason)}</td>
          <td><button class="secondary titleSelectBtn" data-title="${encodeURIComponent(item.title)}">${item.selected || item.title === data.recommended_title ? "已选用" : "选用"}</button></td>
        </tr>`).join("");
      results.innerHTML = `
        <section class="wide"><h2>标题候选</h2>
          <table><tbody>
            <tr><th>ERP 型号</th><td>${escapeHTML(data.erp_model || "")}</td></tr>
            <tr><th>材质</th><td>${escapeHTML(data.material || "")}</td></tr>
            <tr><th>颜色信号</th><td>${escapeHTML((data.colors || []).join("、") || data.color || "")}</td></tr>
            <tr><th>推荐标题</th><td>${escapeHTML(data.recommended_title || "")}</td></tr>
            <tr><th>提示</th><td>${escapeHTML(data.note || "")}</td></tr>
          </tbody></table>
        </section>
        <section class="wide"><h2>标题权重拆分</h2>
          <table><thead><tr><th>#</th><th>标题</th><th>字节</th><th>前段</th><th>中段</th><th>后段</th><th>原因</th><th>操作</th></tr></thead>
          <tbody>${rows}</tbody></table>
        </section>`;
      document.querySelectorAll(".titleSelectBtn").forEach(btn => {
        btn.onclick = async () => {
          try {
            setState("保存中");
            const selectedTitle = decodeURIComponent(btn.dataset.title || "");
            const selected = await postJSON("/api/select-title", {folder: folder.value, title: selectedTitle});
            renderTitle(selected);
            writeLog(`已选用标题：${selected.recommended_title}`);
            setState("已选用");
          } catch (err) {
            writeLog(err.message);
            setState("出错");
          }
        };
      });
    }
    async function loadDefaults() {
      const data = await fetch("/api/defaults").then(r => r.json());
      folder.value = data.default_product_folder;
      priceMultiplier.value = "";
      materialSelect.value = "";
      materialPath.value = "";
    }
    materialSelect.onchange = async () => {
      try {
        setState("保存中");
        const data = await postJSON("/api/material-choice", {folder: folder.value, material: materialSelect.value});
        writeLog(`材质已保存：${data.material}。后续标题和商品属性都会使用这个材质。`);
        setState("已保存");
      } catch (err) {
        writeLog(err.message);
        setState("出错");
      }
    };
    document.getElementById("dryRunBtn").onclick = async () => {
      try {
        setState("核对中");
        writeLog("正在核对本地图片顺序，并从 ERP 优质价读取 SKU 价格...");
        const data = await postJSON("/api/dry-run", {folder: folder.value, price_multiplier: priceMultiplier.value});
        renderDryRun(data);
        writeLog("商品核对完成。");
        setState("已完成");
      } catch (err) {
        writeLog(err.message);
        setState("出错");
      }
    };
    document.getElementById("materialBtn").onclick = async () => {
      try {
        setState("等待扫码");
        writeLog("正在把图片空间读取任务交给当前 Chrome 插件；不会打开独立测试浏览器。请确认当前 Chrome 已登录拼多多后台。");
        const data = await postJSON("/api/material", {path: materialPath.value});
        renderMaterial(data);
        writeLog("图片空间读取完成。");
        setState("已完成");
      } catch (err) {
        writeLog(err.message);
        setState("出错");
      }
    };
    document.getElementById("planBtn").onclick = async () => {
      try {
        requireTaskInputs({needPath: true});
        setState("等待扫码");
        writeLog("正在生成图片和规格包。会交给当前 Chrome 插件读取图片空间，不会打开独立测试浏览器；随后匹配主图、详情页、尺寸图和规格价格。");
        const data = await postJSON("/api/plan", {folder: folder.value, path: materialPath.value, price_multiplier: priceMultiplier.value, material: materialSelect.value});
        renderPlan(data);
        writeLog("图片和规格包生成完成。请重点检查主图顺序、详情页顺序、规格名称、尺寸图、价格和库存。");
        setState("已完成");
      } catch (err) {
        writeLog(err.message);
        setState("出错");
      }
    };
    document.getElementById("generateTitleBtn").onclick = async () => {
      try {
        requireTaskInputs();
        await postJSON("/api/material-choice", {folder: folder.value, material: materialSelect.value});
        setState("生成中");
        writeLog("正在按标题 skill 生成候选标题：会检查 60 字节限制，并拆成前段、中段、后段；不会填写页面。");
        const data = await postJSON("/api/generate-title", {folder: folder.value});
        renderTitle(data);
        writeLog("标题候选已生成，并已缓存推荐标题。下一次插件读取商品数据时会优先使用这个推荐标题。");
        setState("已完成");
      } catch (err) {
        writeLog(err.message);
        setState("出错");
      }
    };
    document.getElementById("categoryBtn").onclick = async () => {
      try {
        requireTaskInputs({needPath: true});
        setState("已排队");
        writeLog("正在把上架包交给当前 Chrome 插件；不会打开独立测试浏览器。请在打开的拼多多发布页里登录/过滑块。");
        const data = await postJSON("/api/plugin-queue", {folder: folder.value});
        refreshProgress();
        results.innerHTML = `<section class="wide"><h2>插件上架任务</h2><table><tbody>
          <tr><th>提示</th><td>${escapeHTML(data.note || "")}</td></tr>
          <tr><th>任务 ID</th><td>${escapeHTML(data.id || "")}</td></tr>
          <tr><th>发布页</th><td>${escapeHTML(data.url || "")}</td></tr>
          <tr><th>模式</th><td>当前 Chrome 插件填充，不启动测试浏览器</td></tr>
        </tbody></table></section>`;
        writeLog("任务已交给插件。若页面已打开，请等待插件提示并核对标题、属性、规格、价格和图片区域。");
        setState("已完成");
      } catch (err) {
        writeLog(err.message);
        setState("出错");
      }
    };
    document.getElementById("readAttrsBtn").onclick = async () => {
      try {
        setState("读取中");
        writeLog("正在读取发布会话当前页面的属性字段快照。");
        const data = await postJSON("/api/category-snapshot", {});
        const rows = (data.fields || []).map(f => `<tr><td>${f.index}</td><td>${escapeHTML(f.label || "")}</td><td>${escapeHTML(f.placeholder || "")}</td><td>${escapeHTML(f.tag || "")}</td><td>${f.required ? "是" : ""}</td><td>${escapeHTML(f.value || "")}</td></tr>`).join("");
        results.innerHTML = `<section class="wide"><h2>当前发布页快照</h2><table><tbody>
          <tr><th>更新时间</th><td>${escapeHTML(data.updated_at || "")}</td></tr>
          <tr><th>标题</th><td>${escapeHTML(data.title || "")}</td></tr>
          <tr><th>地址</th><td>${escapeHTML(data.url || "")}</td></tr>
        </tbody></table></section>
        <section class="wide"><h2>页面字段</h2>
          <table><thead><tr><th>#</th><th>字段</th><th>提示</th><th>控件</th><th>必填</th><th>当前值</th></tr></thead><tbody>${rows}</tbody></table>
        </section>
        <section class="wide"><h2>页面文本预览</h2><div class="log">${escapeHTML(data.body_preview || "")}</div></section>`;
        writeLog("属性字段读取完成。");
        setState("已完成");
      } catch (err) {
        writeLog(err.message);
        setState("出错");
      }
    };
    document.getElementById("fillBasicBtn").onclick = async () => {
      try {
        throw new Error("旧测试浏览器调试入口已禁用。请使用上面的第 3 步，通过当前 Chrome 插件自动填充。");
        setState("发送中");
        writeLog("正在发送测试命令：先自动选择“小拉手”类目，再填商品标题和属性；不保存草稿、不提交上架。");
        const data = await postJSON("/api/fill-basic", {folder: folder.value, price_multiplier: priceMultiplier.value});
        results.innerHTML = `<section class="wide"><h2>填标题和属性测试</h2><table><tbody>
          <tr><th>命令 ID</th><td>${escapeHTML(data.command.id)}</td></tr>
          <tr><th>商品标题</th><td>${escapeHTML(data.command.payload.title)}</td></tr>
          <tr><th>发布类目</th><td>${escapeHTML(data.command.payload.category)}</td></tr>
          <tr><th>提示</th><td>${escapeHTML(data.note)}</td></tr>
        </tbody></table></section>`;
        writeLog("命令已发送。分类确认进入编辑页后，再等 3 秒点“读取属性字段”，可以看到当前值和执行结果。");
        setState("已发送");
      } catch (err) {
        writeLog(err.message);
        setState("出错");
      }
    };
    document.getElementById("fillSpecsBtn").onclick = async () => {
      try {
        throw new Error("旧测试浏览器调试入口已禁用。请使用上面的第 3 步，通过当前 Chrome 插件自动填充。");
        setState("发送中");
        writeLog("正在发送规格价格测试命令。请先确保已经生成并核对图片和规格包；这一步不保存草稿、不提交上架。");
        const data = await postJSON("/api/fill-specs", {});
        const specs = ((data.command.payload.asset_package || {}).sku_specs || []);
        const runResults = ((data.status || {}).results || []);
        const statusRows = runResults.map(r => `<tr><td>${escapeHTML(r.field || "")}</td><td>${escapeHTML(r.status || "")}</td><td>${escapeHTML(r.message || r.value || "")}</td></tr>`).join("");
        results.innerHTML = `<section class="wide"><h2>填规格价格测试</h2><table><tbody>
          <tr><th>命令 ID</th><td>${escapeHTML(data.command.id)}</td></tr>
          <tr><th>素材包</th><td>${escapeHTML(data.package_path)}</td></tr>
          <tr><th>规格数量</th><td>${specs.length}</td></tr>
          <tr><th>执行状态</th><td>${escapeHTML((data.status || {}).status || "")}</td></tr>
          <tr><th>提示</th><td>${escapeHTML(data.note)}</td></tr>
        </tbody></table></section>
        <section class="wide"><h2>执行结果</h2>
          <table><thead><tr><th>项目</th><th>状态</th><th>说明</th></tr></thead><tbody>${statusRows}</tbody></table>
        </section>
        <section class="wide"><h2>将要填写的规格</h2>
          <table><thead><tr><th>#</th><th>规格类型</th><th>规格名</th><th>规格编码</th><th>拼单价</th><th>单买价</th><th>库存</th><th>尺寸图</th></tr></thead>
          <tbody>${specs.map(s => `<tr><td>${s.index}</td><td>${escapeHTML(s.spec_type)}</td><td>${escapeHTML(s.spec_name)}</td><td>${escapeHTML(s.spec_code)}</td><td>${s.group_price}</td><td>${s.single_price}</td><td>${s.stock}</td><td>${escapeHTML(s.material_image_filename)}</td></tr>`).join("")}</tbody></table>
        </section>`;
        writeLog("规格价格测试执行完成。请查看“执行结果”，如果规格类型已选中，我们继续接规格名称和价格库存。");
        setState("已完成");
      } catch (err) {
        writeLog(err.message);
        setState("出错");
      }
    };
    loadDefaults();
    refreshProgress();
    setInterval(refreshProgress, 2000);
  </script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/" or self.path.startswith("/?"):
            self._send_html(HTML)
            return
        if parsed.path == "/api/defaults":
            self._send_json({
                "default_product_folder": str(DEFAULT_PRODUCT_FOLDER),
                "default_price_multiplier": "",
                "default_material": "",
            })
            return
        if parsed.path == "/api/curd/product_json_store/list":
            self._send_json(plugin_product_store_list())
            return
        if parsed.path == "/api/material-read/request":
            self._send_json({"code": 0, "msg": "ok", "data": read_material_plugin_request()})
            return
        if parsed.path == "/api/current-product-json":
            package_path = ROOT / ".tmp_tool" / "listing_asset_package.json"
            if not package_path.exists():
                self._send_json({"code": 0, "msg": "ok", "data": None})
                return
            package = json.loads(package_path.read_text(encoding="utf-8"))
            self._send_json({"code": 0, "msg": "ok", "data": plugin_product_json(package)})
            return
        if parsed.path == "/api/plugin-progress":
            self._send_json({"code": 0, "msg": "ok", "data": read_plugin_status()})
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_POST(self) -> None:
        try:
            parsed = urlparse(self.path)
            _query = parse_qs(parsed.query)
            payload = self._read_json()
            if parsed.path == "/api/dry-run":
                data = asyncio.run(
                    dry_run_payload(
                        str(payload.get("folder") or DEFAULT_PRODUCT_FOLDER),
                        str(payload.get("price_multiplier") or "").strip() or None,
                    )
                )
                self._send_json(data)
                return
            if parsed.path == "/api/material":
                data = asyncio.run(material_payload(str(payload.get("path") or "2026/8250")))
                self._send_json(data)
                return
            if parsed.path == "/api/material-choice":
                data = update_product_material(
                    str(payload.get("folder") or DEFAULT_PRODUCT_FOLDER),
                    str(payload.get("material") or ""),
                )
                self._send_json(data)
                return
            if parsed.path == "/api/plan":
                data = asyncio.run(
                    prepare_listing_payload(
                        str(payload.get("folder") or DEFAULT_PRODUCT_FOLDER),
                        str(payload.get("path") or ""),
                        str(payload.get("price_multiplier") or "").strip() or None,
                        str(payload.get("material") or "").strip() or None,
                    )
                )
                self._send_json(data)
                return
            if parsed.path == "/api/generate-title":
                data = generate_title_payload(str(payload.get("folder") or DEFAULT_PRODUCT_FOLDER))
                self._send_json(data)
                return
            if parsed.path == "/api/select-title":
                data = select_title_payload(
                    str(payload.get("folder") or DEFAULT_PRODUCT_FOLDER),
                    str(payload.get("title") or ""),
                )
                self._send_json(data)
                return
            if parsed.path == "/api/open-category":
                data = asyncio.run(open_category_page_payload())
                self._send_json(data)
                return
            if parsed.path == "/api/auto-fill":
                data = asyncio.run(auto_fill_listing_payload(str(payload.get("folder") or DEFAULT_PRODUCT_FOLDER)))
                self._send_json(data)
                return
            if parsed.path == "/api/plugin-queue":
                data = asyncio.run(plugin_queue_payload(str(payload.get("folder") or DEFAULT_PRODUCT_FOLDER)))
                self._send_json(data)
                return
            if parsed.path == "/api/category-snapshot":
                data = category_snapshot_payload()
                self._send_json(data)
                return
            if parsed.path == "/api/fill-basic":
                data = asyncio.run(
                    fill_basic_info_payload(
                        str(payload.get("folder") or DEFAULT_PRODUCT_FOLDER),
                        str(payload.get("price_multiplier") or "").strip() or None,
                    )
                )
                self._send_json(data)
                return
            if parsed.path == "/api/fill-specs":
                data = fill_specs_payload()
                self._send_json(data)
                return
            if parsed.path == "/api/curd/product_json_store/update":
                data = plugin_product_store_update(payload)
                self._send_json(data)
                return
            if parsed.path == "/api/material-read/response":
                data = write_material_plugin_response(payload)
                self._send_json(data)
                return
            if parsed.path == "/api/plugin-progress":
                data = update_plugin_progress(payload)
                self._send_json(data)
                return
            self.send_error(HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=500)

    def _read_json(self) -> dict[str, Any]:
        size = int(self.headers.get("Content-Length") or 0)
        if size == 0:
            return {}
        return json.loads(self.rfile.read(size).decode("utf-8"))

    def _send_html(self, html: str) -> None:
        data = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, payload: Any, status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False, default=json_default).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: Any) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{args.port}"
    print(f"本地工作台已启动: {url}")
    if not args.no_open:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    server.serve_forever()


if __name__ == "__main__":
    main()
