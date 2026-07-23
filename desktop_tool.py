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
from decimal import Decimal, ROUND_HALF_UP
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import yaml

from playwright.async_api import async_playwright

from main import ProductMeta, build_dry_run, load_product_meta, money
from skills.erp_price import ERPPriceClient, load_config
from skills.pdd_listing import build_sku_specs, resolve_listing_template


ROOT = Path(__file__).resolve().parent
DEFAULT_PRODUCT_FOLDER = Path.home() / "Desktop" / "pdd_upload" / "测试商品001"
DEFAULT_CATEGORY_PATH = "基础建材 > 家用五金 > 拉手 > 明装小拉手"
DEFAULT_STOCK_PER_SKU = 500
ATTRIBUTE_TEMPLATE = ROOT / "templates" / "category_attributes.yaml"
SESSION_PID_PATH = ROOT / ".tmp_tool" / "pdd_session.pid"
COMMAND_PATH = ROOT / ".tmp_tool" / "pdd_category_command.json"
COMMAND_STATUS_PATH = ROOT / ".tmp_tool" / "pdd_category_command_status.json"
PLUGIN_PRODUCT_STATUS_PATH = ROOT / ".tmp_tool" / "plugin_product_status.json"
BATCH_QUEUE_PATH = ROOT / ".tmp_tool" / "batch_listing_queue.json"
DRAFT_HISTORY_PATH = ROOT / ".tmp_tool" / "saved_draft_history.json"
MATERIAL_REQUEST_PATH = ROOT / ".tmp_tool" / "plugin_material_request.json"
MATERIAL_RESPONSE_PATH = ROOT / ".tmp_tool" / "plugin_material_response.json"
TITLE_CACHE_PATH = ROOT / ".tmp_tool" / "title_candidates.json"
PLUGIN_STATUS_LOCK = threading.Lock()
BATCH_QUEUE_LOCK = threading.RLock()
BATCH_WORKER_LOCK = threading.Lock()
BATCH_WORKER_THREAD: threading.Thread | None = None
BATCH_TASK_TIMEOUT_SECONDS = 45 * 60
MATERIAL_OPTIONS = ("黄铜", "锌合金", "铝合金")
IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
VIDEO_EXTENSIONS = {"mp4", "mov", "webm", "m4v"}

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


def model_size_key(lookup_name: str) -> tuple[int, str, int]:
    match = re.match(r"^(\d+)([A-Za-z]*)(?:-(\d+))?$", lookup_name.strip())
    if match:
        return (int(match.group(1)), match.group(2).lower(), int(match.group(3) or 999999))

    numbers = re.findall(r"\d+", lookup_name)
    model = int(numbers[0]) if numbers else 999999
    size = int(numbers[1]) if len(numbers) > 1 else 999999
    return (model, lookup_name.lower(), size)


def compact_name(text: str) -> str:
    stem = Path(text).stem
    return re.sub(r"[\s#/_\\\-.]+", "", stem).lower()


def product_key(product_folder: str | Path) -> str:
    return str(Path(product_folder).expanduser())


def infer_erp_model_from_material_path(material_path: str) -> str:
    parts = [part.strip() for part in re.split(r"[\\/]+", material_path) if part.strip()]
    if not parts:
        return ""
    return parts[-1]


def product_meta_from_inputs(
    product_folder: str | Path,
    material_path: str = "",
    price_multiplier: str | None = None,
    material_choice: str | None = None,
    package: dict[str, Any] | None = None,
) -> ProductMeta:
    package = package or {}
    package_meta = package.get("meta") if isinstance(package.get("meta"), dict) else {}

    try:
        meta = load_product_meta(Path(product_folder).expanduser().resolve())
    except Exception:
        meta = ProductMeta(
            erp_model=str(package.get("erp_model") or package_meta.get("erp_model") or infer_erp_model_from_material_path(material_path)),
            category_path=str(package.get("category_path") or package_meta.get("category_path") or DEFAULT_CATEGORY_PATH),
            price_multiplier=Decimal(str(package.get("price_multiplier") or package_meta.get("price_multiplier") or price_multiplier or "1")),
            material=str(package_meta.get("material") or material_choice or MATERIAL_OPTIONS[0]),
            color=str(package_meta.get("color") or ""),
            stock_per_sku=int(package_meta.get("stock_per_sku") or DEFAULT_STOCK_PER_SKU),
        )

    if price_multiplier is not None and str(price_multiplier).strip():
        meta = ProductMeta(
            erp_model=meta.erp_model,
            category_path=meta.category_path or DEFAULT_CATEGORY_PATH,
            price_multiplier=Decimal(str(price_multiplier)),
            material=meta.material,
            color=meta.color,
            stock_per_sku=meta.stock_per_sku,
        )
    if material_choice is not None and str(material_choice).strip():
        meta = ProductMeta(
            erp_model=meta.erp_model,
            category_path=meta.category_path or DEFAULT_CATEGORY_PATH,
            price_multiplier=meta.price_multiplier,
            material=str(material_choice).strip(),
            color=meta.color,
            stock_per_sku=meta.stock_per_sku,
        )
    return meta


def meta_json(meta: ProductMeta) -> dict[str, Any]:
    return {
        "erp_model": meta.erp_model,
        "category_path": meta.category_path,
        "price_multiplier": str(meta.price_multiplier),
        "material": meta.material,
        "color": meta.color,
        "stock_per_sku": meta.stock_per_sku,
    }


def money_with_cent_ending(value: Decimal, cent_ending: str | int | None = None) -> Decimal:
    rounded = money(value)
    if cent_ending is None or str(cent_ending).strip() == "":
        return rounded

    ending = int(str(cent_ending).strip())
    if ending not in {8, 9}:
        raise ValueError("价格尾数只能选择 8 或 9")

    cents = int((rounded * 100).to_integral_value(rounding=ROUND_HALF_UP))
    adjusted_cents = cents - (cents % 10) + ending
    return (Decimal(adjusted_cents) / Decimal("100")).quantize(Decimal("0.01"))


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

    folder = Path(product_folder).expanduser()
    meta_path = folder / "meta.yaml"
    if meta_path.exists():
        with meta_path.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        raw["material"] = selected
        with meta_path.open("w", encoding="utf-8") as fh:
            yaml.safe_dump(raw, fh, allow_unicode=True, sort_keys=False)

    if TITLE_CACHE_PATH.exists():
        try:
            cached = json.loads(TITLE_CACHE_PATH.read_text(encoding="utf-8"))
            if str(cached.get("product_folder") or "") == product_key(folder):
                TITLE_CACHE_PATH.unlink()
        except Exception:
            TITLE_CACHE_PATH.unlink(missing_ok=True)

    return {"product_folder": product_key(folder), "material": selected, "note": "材质已记录，标题候选会按新材质重新生成。"}


async def dry_run_payload(product_folder: str, price_multiplier: str | None = None) -> dict[str, Any]:
    folder = Path(product_folder).expanduser().resolve()
    multiplier = Decimal(str(price_multiplier)) if price_multiplier else None
    meta, main_images, detail_images, skus = await build_dry_run(folder, price_multiplier=multiplier)
    listing_template = resolve_listing_template(meta, ATTRIBUTE_TEMPLATE)
    return {
        "product_folder": str(folder),
        "meta": meta_json(meta),
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


def material_file_extension(file: dict[str, Any]) -> str:
    extension = str(file.get("extension") or "").strip().lower()
    if extension:
        return extension.lstrip(".")
    return Path(str(file.get("filename") or "")).suffix.lower().lstrip(".")


def is_material_image(file: dict[str, Any]) -> bool:
    return material_file_extension(file) in IMAGE_EXTENSIONS


def is_material_video(file: dict[str, Any]) -> bool:
    return material_file_extension(file) in VIDEO_EXTENSIONS


def material_sku_sort_key(file: dict[str, Any]) -> tuple[Any, ...]:
    filename = str(file.get("filename") or "")
    sku_name = material_file_sku_name(file)
    lookup_name, _color = parse_material_sku_lookup(sku_name)
    return (*model_size_key(lookup_name), natural_key(filename))


PRICE_BOOK_COLOR_WORDS = (
    "哑镍拉丝",
    "古铜色",
    "铜本色",
    "玫瑰金",
    "铜拉丝",
    "铬PVD",
    "亮金",
    "钛银",
    "亮镍",
    "哑镍",
    "铬色",
    "黑色",
    "金色",
    "银色",
    "铬",
)

PRICE_BOOK_COLOR_ALIASES = {
    "钛银": "亮镍",
    "亮金": "玫瑰金",
    "PVD金": "铬PVD",
    "pvd金": "铬PVD",
    "铬pvd": "铬PVD",
    "铬色": "铬",
}


def extract_price_book_color(text: str) -> str | None:
    compact = re.sub(r"[\s#/_\\\-.]+", "", text)
    for alias, price_book_color in PRICE_BOOK_COLOR_ALIASES.items():
        if alias in compact:
            return price_book_color
    for color in PRICE_BOOK_COLOR_WORDS:
        if color in compact:
            return color
    return None


def parse_material_sku_lookup(sku_name: str) -> tuple[str, str | None]:
    stem = Path(sku_name).stem.strip()
    parts = [part.strip() for part in re.split(r"[-_#\s]+", stem) if part.strip()]
    known_color = extract_price_book_color(stem)
    if len(parts) >= 2:
        base_match = re.match(r"^(\d+[A-Za-z]*)(.*)$", parts[0])
        install_match = re.search(r"单孔|吊坠", stem)
        size_index = -1
        size_value = ""
        for index, part in enumerate(parts[1:], start=1):
            if re.search(r"单孔|吊坠", part):
                continue
            size_match = re.match(r"^(\d+)(?:尺寸图|尺寸|直径|mm|MM)?$", part)
            if not size_match and known_color:
                inline_color_match = re.match(r"^(\d+)(?:尺寸图|尺寸|直径|mm|MM)?(.+)$", part)
                if inline_color_match and extract_price_book_color(inline_color_match.group(2)) == known_color:
                    size_match = inline_color_match
            if not size_match:
                size_match = re.search(r"[（(](\d+)(?:尺寸图|尺寸|直径|mm|MM)?[）)]", part)
            if size_match:
                size_index = index
                size_value = size_match.group(1)
                break
        if base_match and size_value:
            color_parts = []
            first_suffix = base_match.group(2).strip()
            if first_suffix:
                color_parts.append(first_suffix)
            color_parts.extend(parts[1:size_index])
            color = known_color or "-".join(part for part in color_parts if part).strip() or None
            return f"{base_match.group(1)}-{size_value}", color
        if base_match:
            non_model_text = "-".join([base_match.group(2).strip(), *parts[1:]]).strip("-")
            if install_match:
                install = install_match.group(0)
                color_text = re.sub(r"(单孔|吊坠|直径|尺寸图|尺寸|[（(]\d+(?:尺寸图|尺寸|直径|mm|MM)?[）)])", "", non_model_text).strip("-") or None
                return f"{base_match.group(1)}-{install}", known_color or color_text
            if known_color:
                return base_match.group(1), known_color
            if non_model_text and re.search(r"单孔|吊坠|直径", non_model_text):
                color = re.sub(r"(单孔|吊坠|直径|尺寸图|尺寸)$", "", non_model_text).strip("-") or None
                return base_match.group(1), color

    if len(parts) >= 3 and re.fullmatch(r"\d+[A-Za-z]*", parts[0]):
        tail = parts[-1]
        if re.fullmatch(r"\d+|\d+直径", tail):
            return f"{parts[0]}-{tail}", "-".join(parts[1:-1])
        if re.fullmatch(r"单孔|吊坠|直径", tail):
            if tail in {"单孔", "吊坠"}:
                return f"{parts[0]}-{tail}", known_color or "-".join(parts[1:-1])
            return parts[0], known_color or "-".join(parts[1:-1])
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


def infer_hole_distance_from_skus(sku_rows: list[dict[str, Any]]) -> str:
    """从尺寸图生成的 SKU 判断单个商品孔距，绝不拼接多个单选值。"""
    texts = [
        " ".join(
            str(row.get(key) or "")
            for key in (
                "sku_name",
                "price_book_name",
                "spec_name",
                "material_image_filename",
                "image",
            )
        )
        for row in sku_rows
    ]
    has_single_hole = any("单孔" in text for text in texts)
    if has_single_hole:
        return "单孔"

    distances: list[int] = []
    for row, text in zip(sku_rows, texts):
        price_book_name = str(row.get("price_book_name") or row.get("price_lookup_name") or "")
        matches = re.findall(r"-(\d+)(?:mm|MM|孔距|尺寸图|尺寸)?(?:\D|$)", price_book_name)
        if not matches:
            matches = re.findall(r"(?:^|[-_#\s])([1-9]\d{1,3})(?:mm|MM|孔距|尺寸图|尺寸)(?:\D|$)", text)
        for value in matches:
            distance = int(value)
            if distance not in distances:
                distances.append(distance)

    distances.sort()
    return f"{distances[0]}mm" if distances else ""


def apply_sku_derived_attributes(listing: dict[str, Any], sku_rows: list[dict[str, Any]]) -> str:
    attributes = dict(listing.get("attributes") or {})
    hole_distance = infer_hole_distance_from_skus(sku_rows)
    if hole_distance:
        attributes["孔距"] = hole_distance
        attributes["外形"] = "球形" if hole_distance == "单孔" else "条形"
    else:
        attributes.pop("孔距", None)
        attributes.pop("外形", None)
    listing["attributes"] = attributes
    return hole_distance


def choose_listing_videos(video_items: list[dict[str, Any]]) -> tuple[dict[str, Any] | str, dict[str, Any] | str, list[dict[str, Any]]]:
    if not video_items:
        return "", "", []

    def is_explain(item: dict[str, Any]) -> bool:
        name = str(item.get("filename") or item.get("name") or "").lower()
        return bool(re.search(r"(?:^|\D)9\s*[-_:x×]\s*16(?:\D|$)|讲解|竖屏", name))

    product = next((item for item in video_items if not is_explain(item)), video_items[0])
    explain = next((item for item in video_items if is_explain(item)), None)
    if explain is None:
        explain = next((item for item in video_items if item is not product), product)

    ordered = [product]
    ordered.extend(item for item in video_items if item is not product)
    return product, explain, ordered


def listing_reference_price(sku_specs: list[dict[str, Any]]) -> Decimal:
    highest_single_price = max(
        (Decimal(str(spec.get("single_price") or "0")) for spec in sku_specs),
        default=Decimal("0"),
    )
    return money(highest_single_price + Decimal("1")) if highest_single_price else Decimal("0")


async def material_sku_rows_from_image_space(
    material_sku: list[dict[str, Any]],
    meta: ProductMeta,
    price_multiplier: str | None = None,
    price_cent_ending: str | None = None,
) -> list[dict[str, Any]]:
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
                    group_price = money_with_cent_ending(quote.price * multiplier, price_cent_ending)
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


async def upload_plan_payload(
    product_folder: str,
    material_path: str,
    price_multiplier: str | None = None,
    material_choice: str | None = None,
    price_cent_ending: str | None = None,
) -> dict[str, Any]:
    write_plugin_status({"id": int(time.time()), "query_count": 0, "status": 0})
    if not str(price_multiplier or "").strip():
        raise ValueError("请先填写价格倍数")
    if not str(material_path or "").strip():
        raise ValueError("请先填写图片空间路径")
    if not str(material_choice or "").strip():
        raise ValueError("请先选择材质")
    if str(price_cent_ending or "").strip() not in {"8", "9"}:
        raise ValueError("请先选择价格尾数：8 或 9")

    folder_key = product_key(product_folder)
    meta = product_meta_from_inputs(
        product_folder,
        material_path=material_path,
        price_multiplier=price_multiplier,
        material_choice=material_choice,
    )
    listing_template = resolve_listing_template(meta, ATTRIBUTE_TEMPLATE)
    dry = {
        "product_folder": folder_key,
        "meta": meta_json(meta),
        "listing_template": listing_template,
        "main_images": [],
        "detail_images": [],
        "skus": [],
    }
    material = await material_payload(material_path)

    material_main = find_child_files(material, "主图")
    material_detail = find_child_files(material, "详情页")
    material_sku = find_child_files(material, "尺寸图")

    main_images = sorted([item for item in material_main if is_material_image(item)], key=lambda item: natural_key(str(item.get("filename") or "")))
    main_videos = sorted([item for item in material_main if is_material_video(item)], key=lambda item: natural_key(str(item.get("filename") or "")))
    detail_images = sorted([item for item in material_detail if is_material_image(item)], key=lambda item: natural_key(str(item.get("filename") or "")))
    material_sku_images = [item for item in material_sku if is_material_image(item)]
    if not material_sku_images:
        raise FileNotFoundError("图片空间“尺寸图”文件夹里没有图片，无法生成 SKU")
    sku_rows = await material_sku_rows_from_image_space(
        material_sku_images,
        meta,
        price_multiplier=price_multiplier,
        price_cent_ending=price_cent_ending,
    )
    sku_source = "image_space_size_images"

    package_erp_model = summarize_sku_models(sku_rows, str(dry["meta"]["erp_model"]))
    dry["meta"]["erp_model"] = package_erp_model
    listing_template = dry.get("listing_template") or {}
    listing = listing_template.get("template") or {}
    title_template = str(listing.get("title_template") or "")
    if title_template:
        listing["title_template"] = re.sub(r"\b\d+[A-Za-z]*(?:-\d+[A-Za-z]*)?\b", package_erp_model, title_template, count=1)
    sku_specs = build_sku_specs(sku_rows, erp_model=package_erp_model)
    hole_distance = apply_sku_derived_attributes(listing, sku_specs)
    package = {
        "product_folder": dry["product_folder"],
        "material_path": material_path,
        "erp_model": package_erp_model,
        "title": title_template,
        "category_path": (dry.get("listing_template") or {}).get("matched_category_path") or dry["meta"]["category_path"],
        "category_keyword": "小拉手",
        "price_multiplier": dry["meta"]["price_multiplier"],
        "price_cent_ending": str(price_cent_ending),
        "batchDiscount": "9.9",
        "productCode": str(dry["meta"]["price_multiplier"]),
        "meta": dry["meta"],
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
        "main_videos": [
            {
                "index": index,
                "filename": str(video.get("filename") or ""),
                "url": str(video.get("url") or ""),
                "size": video.get("size"),
                "material_path": str(material_path).rstrip("/\\") + "/主图",
            }
            for index, video in enumerate(main_videos, start=1)
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
        "derived_attributes": {
            name: listing["attributes"][name]
            for name in ("孔距", "外形")
            if name in listing["attributes"]
        },
        "checks": {
            "main_image_count": len(main_images),
            "main_video_count": len(main_videos),
            "detail_image_count": len(detail_images),
            "sku_count": len(sku_specs),
            "spec_type": "型号",
            "spec_code_rule": "价格册完整型号名称#颜色",
            "sku_source": sku_source,
        },
    }
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
        "sku_source_warning": "",
        "source": {
            "local_main_images": [],
            "local_detail_images": [],
            "material_dir_id": material["dir_id"],
        },
    }


async def prepare_listing_payload(
    product_folder: str,
    material_path: str,
    price_multiplier: str | None = None,
    material_choice: str | None = None,
    price_cent_ending: str | None = None,
) -> dict[str, Any]:
    write_plugin_status({"id": int(time.time()), "query_count": 0, "status": 0})
    if not str(material_choice or "").strip():
        raise ValueError("请先选择材质")
    update_product_material(product_folder, str(material_choice))
    return await upload_plan_payload(
        product_folder,
        material_path,
        price_multiplier=price_multiplier,
        material_choice=material_choice,
        price_cent_ending=price_cent_ending,
    )


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
    package = package or {}
    meta = product_meta_from_inputs(folder, package=package)
    package_folder_raw = str(package.get("product_folder") or "").strip()
    package_matches_folder = package_folder_raw == product_key(folder)
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
    folder = Path(product_folder).expanduser()
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
        "product_folder": product_key(folder),
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
    folder = Path(product_folder).expanduser()
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
    if str(payload.get("product_folder") or "") != product_key(folder):
        return ""
    return str(payload.get("recommended_title") or "")


async def fill_basic_info_payload(product_folder: str, price_multiplier: str | None = None) -> dict[str, Any]:
    folder = Path(product_folder).expanduser()
    package_path = ROOT / ".tmp_tool" / "listing_asset_package.json"
    package = json.loads(package_path.read_text(encoding="utf-8")) if package_path.exists() else {}
    meta = product_meta_from_inputs(folder, price_multiplier=price_multiplier, package=package)
    listing_template = resolve_listing_template(meta, ATTRIBUTE_TEMPLATE)
    listing = listing_template["template"]
    payload = {
        "title": cached_recommended_title(folder) or listing.get("title_template") or "",
        "attributes": listing.get("attributes") or {},
        "category": listing_template.get("matched_category_path") or meta.category_path,
        "category_keyword": "小拉手",
        "main_images": package.get("main_images") or [],
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


async def plugin_queue_payload(product_folder: str, task_id: int | None = None) -> dict[str, Any]:
    package_path = ROOT / ".tmp_tool" / "listing_asset_package.json"
    if not package_path.exists():
        raise FileNotFoundError("还没有上架包。请先点第 1 步“生成上架包”。")

    package = json.loads(package_path.read_text(encoding="utf-8"))
    folder = Path(str(package.get("product_folder") or product_folder or DEFAULT_PRODUCT_FOLDER)).expanduser().resolve()
    if not cached_recommended_title(folder):
        generate_title_payload(str(folder))

    task_id = task_id or int(time.time() * 1000)
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


def now_text() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def empty_batch_queue() -> dict[str, Any]:
    return {
        "version": 1,
        "batch_id": "",
        "state": "idle",
        "created_at": "",
        "updated_at": now_text(),
        "completed_at": "",
        "tasks": [],
    }


def _read_batch_queue_unlocked() -> dict[str, Any]:
    if not BATCH_QUEUE_PATH.exists():
        return empty_batch_queue()
    try:
        queue = json.loads(BATCH_QUEUE_PATH.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return empty_batch_queue()
    if not isinstance(queue, dict):
        return empty_batch_queue()
    if not isinstance(queue.get("tasks"), list):
        queue["tasks"] = []
    return queue


def read_batch_queue() -> dict[str, Any]:
    with BATCH_QUEUE_LOCK:
        return _read_batch_queue_unlocked()


def _write_batch_queue_unlocked(queue: dict[str, Any]) -> None:
    queue["updated_at"] = now_text()
    BATCH_QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = BATCH_QUEUE_PATH.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(BATCH_QUEUE_PATH)


def write_batch_queue(queue: dict[str, Any]) -> None:
    with BATCH_QUEUE_LOCK:
        _write_batch_queue_unlocked(queue)


def batch_queue_view(queue: dict[str, Any] | None = None) -> dict[str, Any]:
    queue = queue or read_batch_queue()
    tasks = [item for item in queue.get("tasks") or [] if isinstance(item, dict)]
    counts = {
        name: sum(1 for item in tasks if item.get("status") == name)
        for name in ("pending", "preparing", "queued", "running", "succeeded", "failed")
    }
    result = dict(queue)
    result["tasks"] = tasks
    result["summary"] = {
        "total": len(tasks),
        "completed": counts["succeeded"] + counts["failed"],
        "succeeded": counts["succeeded"],
        "failed": counts["failed"],
        "waiting": counts["pending"] + counts["preparing"] + counts["queued"] + counts["running"],
    }
    result["failed_tasks"] = [
        {
            "id": item.get("id"),
            "material_path": item.get("material_path"),
            "message": item.get("message") or "未知错误",
        }
        for item in tasks
        if item.get("status") == "failed"
    ]
    return result


def parse_batch_material_paths(value: Any) -> list[str]:
    if isinstance(value, list):
        raw_items = [str(item) for item in value]
    else:
        raw_items = re.split(r"[\r\n,，;；]+", str(value or ""))
    paths: list[str] = []
    seen: set[str] = set()
    for raw in raw_items:
        path = raw.strip().strip('"\'')
        if not path or path in seen:
            continue
        seen.add(path)
        paths.append(path)
    return paths


def update_batch_task(task_id: str, **changes: Any) -> dict[str, Any] | None:
    with BATCH_QUEUE_LOCK:
        queue = _read_batch_queue_unlocked()
        for task in queue.get("tasks") or []:
            if str(task.get("id")) != str(task_id):
                continue
            task.update(changes)
            _write_batch_queue_unlocked(queue)
            return dict(task)
    return None


def finish_batch_if_done() -> bool:
    with BATCH_QUEUE_LOCK:
        queue = _read_batch_queue_unlocked()
        tasks = queue.get("tasks") or []
        if any(task.get("status") not in {"succeeded", "failed"} for task in tasks):
            return False
        if tasks and queue.get("state") != "completed":
            queue["state"] = "completed"
            queue["completed_at"] = now_text()
            _write_batch_queue_unlocked(queue)
        return True


def plugin_task_result(status: dict[str, Any]) -> tuple[bool, bool, str]:
    progress = status.get("progress") if isinstance(status.get("progress"), dict) else {}
    stage = str(progress.get("stage") or "")
    message = str(progress.get("message") or stage or "等待插件执行")
    if stage == "error" or progress.get("ok") is False:
        return True, False, message
    if stage != "done":
        return False, False, message
    detail = progress.get("detail") if isinstance(progress.get("detail"), dict) else {}
    if detail.get("draftSaved") is True:
        return True, True, message
    return True, False, message or "自动填充结束，但草稿没有保存成功"


def wait_for_plugin_batch_task(task_id: str, plugin_task_id: int, timeout_s: int = BATCH_TASK_TIMEOUT_SECONDS) -> tuple[bool, str]:
    deadline = time.monotonic() + timeout_s
    marked_running = False
    while time.monotonic() < deadline:
        status = read_plugin_status()
        if str(status.get("id")) == str(plugin_task_id):
            done, succeeded, message = plugin_task_result(status)
            progress = status.get("progress") if isinstance(status.get("progress"), dict) else {}
            stage = str(progress.get("stage") or "")
            if not marked_running and stage not in {"", "queued"}:
                update_batch_task(task_id, status="running", message=message)
                marked_running = True
            if done:
                return succeeded, message
        time.sleep(1)
    return False, f"等待插件执行超过 {timeout_s // 60} 分钟，已跳过该任务"


def run_batch_task(task: dict[str, Any]) -> None:
    task_id = str(task["id"])
    update_batch_task(task_id, status="preparing", started_at=task.get("started_at") or now_text(), message="正在读取图片空间并查询 ERP 价格")
    try:
        asyncio.run(
            prepare_listing_payload(
                str(task.get("product_folder") or DEFAULT_PRODUCT_FOLDER),
                str(task.get("material_path") or ""),
                str(task.get("price_multiplier") or "").strip() or None,
                str(task.get("material") or "").strip() or None,
                str(task.get("price_ending") or "").strip() or None,
            )
        )
        custom_title = str(task.get("title") or "").strip()
        if custom_title:
            select_title_payload(str(task.get("product_folder") or DEFAULT_PRODUCT_FOLDER), custom_title)
        else:
            generate_title_payload(str(task.get("product_folder") or DEFAULT_PRODUCT_FOLDER))
        plugin_task_id = int(time.time() * 1000)
        update_batch_task(task_id, plugin_task_id=plugin_task_id, message="上架包已生成，正在打开发布页")
        asyncio.run(plugin_queue_payload(str(task.get("product_folder") or DEFAULT_PRODUCT_FOLDER), task_id=plugin_task_id))
        update_batch_task(task_id, status="queued", message="等待 Chrome 插件接收任务")
        succeeded, message = wait_for_plugin_batch_task(task_id, plugin_task_id)
        update_batch_task(
            task_id,
            status="succeeded" if succeeded else "failed",
            message=message if message else ("草稿已保存" if succeeded else "任务失败"),
            finished_at=now_text(),
        )
    except Exception as exc:
        update_batch_task(task_id, status="failed", message=str(exc), finished_at=now_text())


def batch_worker_loop() -> None:
    global BATCH_WORKER_THREAD
    try:
        while True:
            queue = read_batch_queue()
            tasks = [task for task in queue.get("tasks") or [] if isinstance(task, dict)]
            active = next((task for task in tasks if task.get("status") in {"queued", "running"}), None)
            if active and active.get("plugin_task_id"):
                succeeded, message = wait_for_plugin_batch_task(str(active["id"]), int(active["plugin_task_id"]))
                update_batch_task(
                    str(active["id"]),
                    status="succeeded" if succeeded else "failed",
                    message=message,
                    finished_at=now_text(),
                )
                continue
            task = next((item for item in tasks if item.get("status") in {"pending", "preparing"}), None)
            if not task:
                finish_batch_if_done()
                return
            run_batch_task(task)
    finally:
        with BATCH_WORKER_LOCK:
            BATCH_WORKER_THREAD = None
        # 如果提交请求恰好发生在线程退出瞬间，重新检查一次，避免新任务滞留。
        if any(task.get("status") not in {"succeeded", "failed"} for task in read_batch_queue().get("tasks") or []):
            ensure_batch_worker()


def ensure_batch_worker() -> None:
    global BATCH_WORKER_THREAD
    with BATCH_WORKER_LOCK:
        if BATCH_WORKER_THREAD and BATCH_WORKER_THREAD.is_alive():
            return
        queue = read_batch_queue()
        if not any(task.get("status") not in {"succeeded", "failed"} for task in queue.get("tasks") or []):
            return
        BATCH_WORKER_THREAD = threading.Thread(target=batch_worker_loop, name="pdd-batch-worker", daemon=True)
        BATCH_WORKER_THREAD.start()


def normalize_batch_task_inputs(payload: dict[str, Any]) -> list[dict[str, str]]:
    raw_tasks = payload.get("tasks")
    if isinstance(raw_tasks, list):
        candidates = [item for item in raw_tasks if isinstance(item, dict)]
    else:
        candidates = [
            {
                "path": path,
                "price_multiplier": payload.get("price_multiplier"),
                "price_ending": payload.get("price_ending"),
                "material": payload.get("material"),
                "title": payload.get("title"),
            }
            for path in parse_batch_material_paths(payload.get("paths") or payload.get("path"))
        ]
    if not candidates:
        raise ValueError("请至少填写一个图片空间路径；多个路径请每行填写一个")

    tasks: list[dict[str, str]] = []
    seen_paths: set[str] = set()
    for item in candidates:
        path = str(item.get("path") or item.get("material_path") or "").strip()
        if not path or path in seen_paths:
            continue
        price_multiplier = str(item.get("price_multiplier") or "").strip()
        material = str(item.get("material") or "").strip()
        price_ending = str(item.get("price_ending") or "").strip()
        title = str(item.get("title") or "").strip()
        if not price_multiplier:
            raise ValueError(f"任务 {path}：请填写价格倍数")
        try:
            if Decimal(price_multiplier) <= 0:
                raise ValueError
        except Exception as exc:
            raise ValueError(f"任务 {path}：价格倍数必须是大于 0 的数字") from exc
        if material not in MATERIAL_OPTIONS:
            raise ValueError(f"任务 {path}：请选择有效材质")
        if price_ending not in {"8", "9"}:
            raise ValueError(f"任务 {path}：请选择价格尾数 8 或 9")
        if title and pdd_title_byte_length(title) > 60:
            raise ValueError(f"任务 {path}：商品标题超过 60 字节，当前 {pdd_title_byte_length(title)} 字节")
        seen_paths.add(path)
        tasks.append({
            "path": path,
            "price_multiplier": price_multiplier,
            "price_ending": price_ending,
            "material": material,
            "title": title,
        })
    if not tasks:
        raise ValueError("没有可加入的有效任务")
    return tasks


def submit_batch_queue(payload: dict[str, Any]) -> dict[str, Any]:
    task_inputs = normalize_batch_task_inputs(payload)
    product_folder = str(payload.get("folder") or DEFAULT_PRODUCT_FOLDER)

    with BATCH_QUEUE_LOCK:
        queue = _read_batch_queue_unlocked()
        unfinished = any(task.get("status") not in {"succeeded", "failed"} for task in queue.get("tasks") or [])
        if not unfinished:
            batch_id = str(int(time.time() * 1000))
            queue = empty_batch_queue()
            queue.update({"batch_id": batch_id, "state": "running", "created_at": now_text(), "completed_at": ""})
        else:
            batch_id = str(queue.get("batch_id") or int(time.time() * 1000))
            queue["batch_id"] = batch_id
            queue["state"] = "running"
            queue["completed_at"] = ""

        existing_paths = {
            str(task.get("material_path") or "")
            for task in queue.get("tasks") or []
            if task.get("status") not in {"succeeded", "failed"}
        }
        next_index = max((int(task.get("index") or 0) for task in queue.get("tasks") or []), default=0) + 1
        added = 0
        for task_input in task_inputs:
            path = task_input["path"]
            if path in existing_paths:
                continue
            queue["tasks"].append({
                "id": f"{batch_id}-{next_index}",
                "index": next_index,
                "material_path": path,
                "product_folder": product_folder,
                "price_multiplier": task_input["price_multiplier"],
                "price_ending": task_input["price_ending"],
                "material": task_input["material"],
                "title": task_input["title"],
                "status": "pending",
                "message": "等待执行",
                "created_at": now_text(),
                "started_at": "",
                "finished_at": "",
            })
            existing_paths.add(path)
            next_index += 1
            added += 1
        if not added:
            raise ValueError("这些路径已在当前待执行队列中")
        _write_batch_queue_unlocked(queue)

    ensure_batch_worker()
    result = batch_queue_view()
    result["added"] = added
    return result


def read_saved_draft_history() -> dict[str, Any]:
    default = {"version": 1, "total": 0, "items": []}
    if not DRAFT_HISTORY_PATH.exists():
        return default
    try:
        data = json.loads(DRAFT_HISTORY_PATH.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return default
    if not isinstance(data, dict):
        return default
    items = data.get("items")
    if not isinstance(items, list):
        items = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if not item.get("goods_id") and item.get("url"):
            item["goods_id"] = parse_goods_id_from_url(str(item.get("url") or ""))
        record_key = draft_record_key(str(item.get("mall_id") or ""), str(item.get("goods_id") or ""))
        if record_key and not item.get("record_key"):
            item["record_key"] = record_key
    data["items"] = items
    data["total"] = len(items)
    data["version"] = int(data.get("version") or 1)
    return data


def write_saved_draft_history(history: dict[str, Any]) -> None:
    history["version"] = 1
    history["total"] = len(history.get("items") or [])
    DRAFT_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = DRAFT_HISTORY_PATH.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(DRAFT_HISTORY_PATH)


def parse_goods_id_from_url(url: str) -> str:
    try:
        query = parse_qs(urlparse(url).query)
        return str((query.get("goods_id") or [""])[0])
    except Exception:
        return ""


def draft_record_key(mall_id: str, goods_id: str) -> str:
    mall_id = str(mall_id or "").strip()
    goods_id = str(goods_id or "").strip()
    if mall_id and goods_id:
        return f"{mall_id}:{goods_id}"
    return ""


def append_saved_draft_history(status: dict[str, Any], progress: dict[str, Any]) -> dict[str, Any] | None:
    if progress.get("stage") != "draft_saved":
        return None
    detail = progress.get("detail") if isinstance(progress.get("detail"), dict) else {}
    task_id = str(status.get("id") or "")
    url = str(progress.get("url") or detail.get("url") or "")
    mall_id = str(detail.get("mall_id") or "")
    goods_id = str(detail.get("goods_id") or parse_goods_id_from_url(url))
    entry = {
        "saved_at": progress.get("updated_at") or time.strftime("%Y-%m-%d %H:%M:%S"),
        "task_id": task_id,
        "title": str(detail.get("title") or ""),
        "mall_name": str(detail.get("mall_name") or ""),
        "mall_id": mall_id,
        "url": url,
        "goods_id": goods_id,
        "record_key": draft_record_key(mall_id, goods_id),
        "product_folder": str(detail.get("product_folder") or ""),
        "material_path": str(detail.get("material_path") or ""),
        "erp_model": str(detail.get("erp_model") or ""),
        "category": str(detail.get("category") or ""),
        "product_code": str(detail.get("product_code") or ""),
        "sku_count": int(detail.get("sku_count") or 0),
        "main_image_count": int(detail.get("main_image_count") or 0),
        "detail_image_count": int(detail.get("detail_image_count") or 0),
    }

    history = read_saved_draft_history()
    items = history.get("items") or []
    for item in items:
        if task_id and str(item.get("task_id") or "") == task_id:
            item.update(entry)
            write_saved_draft_history(history)
            return entry
        if entry["record_key"] and str(item.get("record_key") or draft_record_key(item.get("mall_id", ""), item.get("goods_id", ""))) == entry["record_key"]:
            item.update(entry)
            write_saved_draft_history(history)
            return entry
        if url and str(item.get("url") or "") == url and str(item.get("title") or "") == entry["title"]:
            item.update(entry)
            write_saved_draft_history(history)
            return entry

    items.append(entry)
    history["items"] = items
    write_saved_draft_history(history)
    return entry


def enrich_latest_saved_draft(progress: dict[str, Any]) -> None:
    url = str(progress.get("url") or "")
    goods_id = parse_goods_id_from_url(url)
    if not url and not goods_id:
        return
    history = read_saved_draft_history()
    items = history.get("items") or []
    if not items:
        return
    latest = items[-1]
    changed = False
    if url and not str(latest.get("url") or "").startswith("https://mms.pinduoduo.com/goods/goods_add/success"):
        latest["url"] = url
        changed = True
    if goods_id and not latest.get("goods_id"):
        latest["goods_id"] = goods_id
        changed = True
    record_key = draft_record_key(str(latest.get("mall_id") or ""), str(latest.get("goods_id") or ""))
    if record_key and latest.get("record_key") != record_key:
        latest["record_key"] = record_key
        changed = True
    if changed:
        write_saved_draft_history(history)


def update_plugin_progress(payload: dict[str, Any]) -> dict[str, Any]:
    status = read_plugin_status()
    payload_task_id = str(payload.get("task_id") or "")
    if payload_task_id and payload_task_id != str(status.get("id") or ""):
        return {"code": 0, "msg": "ignored stale task progress", "data": status}
    progress = {
        "stage": str(payload.get("stage") or ""),
        "message": str(payload.get("message") or ""),
        "page_type": str(payload.get("page_type") or ""),
        "url": str(payload.get("url") or ""),
        "ok": bool(payload.get("ok", True)),
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    if payload_task_id:
        progress["task_id"] = payload_task_id
    if "detail" in payload:
        progress["detail"] = payload.get("detail")
    status["progress"] = progress
    saved_entry = append_saved_draft_history(status, progress)
    if saved_entry:
        status["last_saved_draft"] = saved_entry
    elif progress["stage"] in {"done", "page_changed"}:
        enrich_latest_saved_draft(progress)
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
    folder = Path(str(package.get("product_folder") or DEFAULT_PRODUCT_FOLDER)).expanduser()
    meta = product_meta_from_inputs(folder, package=package)
    listing_template = resolve_listing_template(meta, ATTRIBUTE_TEMPLATE)
    listing = listing_template["template"]
    generated_title = cached_recommended_title(folder) or str(listing.get("title_template") or "")
    category_path = str(package.get("category_path") or listing_template.get("matched_category_path") or meta.category_path)
    category_parts = [part.strip() for part in category_path.split(">") if part.strip()]
    category_parts += [""] * (4 - len(category_parts))

    main_image_urls = [
        str(item.get("url") or "")
        for item in package.get("main_images") or []
        if item.get("url")
    ]
    main_images = {
        f"image{index}": url
        for index, url in enumerate(main_image_urls, start=1)
        if url
    }
    detail_images = [
        item.get("url")
        for item in package.get("detail_images") or []
        if item.get("url")
    ]
    main_video_items = [
        {
            "url": str(item.get("url") or ""),
            "name": str(item.get("filename") or item.get("name") or f"主图视频{index}.mp4"),
            "filename": str(item.get("filename") or item.get("name") or f"主图视频{index}.mp4"),
            "materialPath": str(item.get("material_path") or ""),
            "useMaterialPicker": True,
        }
        for index, item in enumerate(package.get("main_videos") or [], start=1)
        if item.get("url")
    ]
    product_video, explain_video, main_video_items = choose_listing_videos(main_video_items)
    if not product_video and main_image_urls:
        product_video = {
            "url": main_image_urls[0],
            "name": "商品视频.webm",
            "makeVideoFromImage": True,
        }
        explain_video = {
            "url": main_image_urls[0],
            "name": "商品讲解视频.webm",
            "makeVideoFromImage": True,
        }
    sku_specs = list(package.get("sku_specs") or [])
    apply_sku_derived_attributes(listing, sku_specs)
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
        "mainVideos": main_video_items,
        "detailImages": detail_images,
        "productVideo": product_video,
        "explainVideo": explain_video,
        "attributes": listing_attributes_array(dict(listing.get("attributes") or {})),
        "serviceOptions": list(listing.get("service_options") or []),
        "skuAxes": [
            {
                "typeName": "型号",
                "values": [str(spec.get("spec_name") or "") for spec in sku_specs],
            }
        ],
        "skus": skus,
        "marketPrice": listing_reference_price(sku_specs),
        "batchDiscount": "9.9",
        "productCode": str(package.get("price_multiplier") or meta.price_multiplier),
        "_source": {
            "product_folder": str(package.get("product_folder") or ""),
            "material_path": str(package.get("material_path") or ""),
            "erp_model": str(package.get("erp_model") or meta.erp_model),
            "category_path": category_path,
            "main_image_count": len(package.get("main_images") or []),
            "detail_image_count": len(package.get("detail_images") or []),
        },
        "_localSafetyMode": True,
    }


def plugin_product_store_list() -> dict[str, Any]:
    package_path = ROOT / ".tmp_tool" / "listing_asset_package.json"
    if not package_path.exists():
        return {"code": 0, "msg": "ok", "data": {"list": [], "total": 0}}

    status = read_plugin_status()
    package = json.loads(package_path.read_text(encoding="utf-8"))
    product_data = plugin_product_json(package)
    product_data["_workbenchTaskId"] = int(status.get("id") or int(time.time() * 1000))
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
    input, select, textarea {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 9px 10px;
      font-size: 13px;
      background: #fff;
      font-family: inherit;
    }
    input, select { height: 38px; padding-top: 0; padding-bottom: 0; }
    textarea { min-height: 92px; resize: vertical; line-height: 1.5; }
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
    .draft-history-row { margin-top: 4px; }
    .draft-history-ids { color: #334155; font-family: Consolas, monospace; }
    .batch-list { margin-top: 8px; display: grid; gap: 6px; }
    .batch-item { border-top: 1px solid var(--line); padding-top: 6px; }
    .batch-item.failed { color: #b42318; }
    .batch-item.succeeded { color: var(--ok); }
    .batch-task-editor { display: grid; gap: 10px; margin-top: 12px; }
    .batch-task-card { border: 1px solid var(--line); border-radius: 7px; padding: 10px; background: #f8fafc; }
    .batch-task-path { font-size: 13px; font-weight: 650; word-break: break-all; margin-bottom: 8px; }
    .batch-task-fields { display: grid; grid-template-columns: .8fr 1.1fr 1.1fr; gap: 7px; }
    .batch-task-fields label { margin: 0; font-size: 11px; }
    .batch-task-fields input, .batch-task-fields select { margin-top: 4px; padding-left: 7px; padding-right: 7px; }
    .batch-task-title { margin: 9px 0 0; font-size: 11px; }
    .batch-task-title input { margin-top: 4px; }
    .batch-title-count { display: block; margin-top: 3px; color: var(--muted); text-align: right; }
    .batch-title-count.error { color: #b42318; }
    .batch-default-actions { margin-top: 8px; display: none; }
    .batch-default-actions.visible { display: block; }
    .batch-default-actions button { width: 100%; }
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
      <label>价格倍数（单任务值 / 批量默认值）</label>
      <input id="priceMultiplier" inputmode="decimal" placeholder="例如 1.6" />
      <label>价格尾数（单任务值 / 批量默认值）</label>
      <select id="priceEnding">
        <option value="8">小数第 2 位尾数 8</option>
        <option value="9">小数第 2 位尾数 9</option>
      </select>
      <label>材质（单任务值 / 批量默认值）</label>
      <select id="materialSelect">
        <option value="">请选择材质</option>
        <option value="黄铜">黄铜</option>
        <option value="锌合金">锌合金</option>
        <option value="铝合金">铝合金</option>
      </select>
      <label>图片空间路径（可填写多个，每行一个）</label>
      <textarea id="materialPath" placeholder="例如：&#10;2026/8256&#10;2026/8257&#10;2026/8258"></textarea>
      <div class="batch-task-editor" id="batchTaskEditor"></div>
      <div class="batch-default-actions" id="batchDefaultActions">
        <button class="secondary" id="applyBatchDefaultsBtn">把上面的默认值应用到全部任务</button>
      </div>
      <div class="workflow">
        <button class="primary" id="batchBtn">批量加入并自动执行<small>按顺序生成上架包、打开发布页并保存草稿；单项失败会自动继续</small></button>
        <button class="primary" id="planBtn">1 生成上架包<small>读取图片空间，匹配主图/详情页/尺寸图，计算规格价格</small></button>
        <button class="secondary" id="generateTitleBtn">2 生成/选择标题<small>生成 60 字节标题候选，点“选用”保存</small></button>
        <button class="secondary" id="categoryBtn">3 打开发布页开始填充<small>进入拼多多发布页后，本地助手读取上架包填图片、规格、价格和材质</small></button>
      </div>
      <div class="hint">批量任务可以逐条设置价格倍数、价格尾数和材质；顶部选项只作为新增任务的默认值。单个任务仍可使用下面 3 步手动核对。</div>
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
        <div class="progress-meta" id="draftHistory">累计保存草稿：读取中。</div>
      </div>
      <div class="progress-box">
        <div class="progress-head"><span>批量任务队列</span><span id="batchState">未开始</span></div>
        <div class="progress-message" id="batchSummary">可以一次填写多个图片空间路径。</div>
        <div class="batch-list" id="batchList"></div>
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
    const priceEnding = document.getElementById("priceEnding");
    const materialSelect = document.getElementById("materialSelect");
    const materialPath = document.getElementById("materialPath");
    const batchTaskEditor = document.getElementById("batchTaskEditor");
    const batchDefaultActions = document.getElementById("batchDefaultActions");
    const log = document.getElementById("log");
    const results = document.getElementById("results");
    const pill = document.getElementById("statePill");
    const progressDot = document.getElementById("progressDot");
    const progressAge = document.getElementById("progressAge");
    const progressMessage = document.getElementById("progressMessage");
    const progressMeta = document.getElementById("progressMeta");
    const draftHistory = document.getElementById("draftHistory");
    const batchState = document.getElementById("batchState");
    const batchSummary = document.getElementById("batchSummary");
    const batchList = document.getElementById("batchList");
    let lastBatchState = "";
    let batchTaskDrafts = new Map();

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
    function setDraftHistoryView(history) {
      const items = (history && history.items) || [];
      const total = history && typeof history.total === "number" ? history.total : items.length;
      const recent = items.slice(-5).reverse();
      if (!recent.length) {
        draftHistory.innerHTML = "累计保存草稿：0 条。";
        return;
      }
      const rows = recent.map(item => {
        const link = item.url ? `<a href="${escapeHTML(item.url)}" target="_blank">链接</a>` : "";
        const mallName = item.mall_name || "未知店铺";
        const mallId = item.mall_id || "未记录店铺ID";
        const goodsId = item.goods_id || "未记录商品ID";
        const recordKey = item.record_key || ((item.mall_id && item.goods_id) ? `${item.mall_id}:${item.goods_id}` : "");
        const title = item.title || "未记录标题";
        return `<div class="draft-history-row">
          <div>${escapeHTML(item.saved_at || "")}｜${escapeHTML(mallName)}｜${escapeHTML(title)} ${link}</div>
          <div class="draft-history-ids">店铺ID：${escapeHTML(mallId)}｜商品ID：${escapeHTML(goodsId)}${recordKey ? `｜记录：${escapeHTML(recordKey)}` : ""}</div>
        </div>`;
      }).join("");
      draftHistory.innerHTML = `<div>累计保存草稿：${total} 条</div>${rows}`;
    }
    async function refreshDraftHistory() {
      try {
        const response = await fetch("/api/draft-history");
        const data = await response.json();
        setDraftHistoryView(data.data || {});
      } catch (_) {
        draftHistory.textContent = "累计保存草稿：读取失败。";
      }
    }
    function materialPaths() {
      return [...new Set(materialPath.value.split(/[\r\n,，;；]+/).map(path => path.trim()).filter(Boolean))];
    }
    function pddTitleByteLength(text) {
      return Array.from(String(text || "")).reduce((total, ch) => total + (ch.charCodeAt(0) < 128 ? 1 : 2), 0);
    }
    function currentBatchDefaults() {
      return {
        price_multiplier: priceMultiplier.value.trim(),
        price_ending: priceEnding.value.trim(),
        material: materialSelect.value.trim()
      };
    }
    function syncBatchTaskEditor(applyDefaults = false) {
      const paths = materialPaths();
      const defaults = currentBatchDefaults();
      const nextDrafts = new Map();
      paths.forEach(path => {
        const existing = batchTaskDrafts.get(path);
        if (applyDefaults) nextDrafts.set(path, {...(existing || {title: ""}), ...defaults});
        else nextDrafts.set(path, existing || {...defaults, title: ""});
      });
      batchTaskDrafts = nextDrafts;
      batchDefaultActions.classList.toggle("visible", paths.length > 0);
      batchTaskEditor.innerHTML = paths.map((path, index) => {
        const task = batchTaskDrafts.get(path) || defaults;
        return `<div class="batch-task-card" data-index="${index}">
          <div class="batch-task-path">任务 ${index + 1}：${escapeHTML(path)}</div>
          <div class="batch-task-fields">
            <label>价格倍数<input class="task-price-multiplier" inputmode="decimal" value="${escapeHTML(task.price_multiplier || "")}" placeholder="如 1.8" /></label>
            <label>价格尾数<select class="task-price-ending">
              <option value="8"${task.price_ending === "8" ? " selected" : ""}>尾数 8</option>
              <option value="9"${task.price_ending === "9" ? " selected" : ""}>尾数 9</option>
            </select></label>
            <label>材质<select class="task-material">
              <option value=""${!task.material ? " selected" : ""}>请选择</option>
              <option value="黄铜"${task.material === "黄铜" ? " selected" : ""}>黄铜</option>
              <option value="锌合金"${task.material === "锌合金" ? " selected" : ""}>锌合金</option>
              <option value="铝合金"${task.material === "铝合金" ? " selected" : ""}>铝合金</option>
            </select></label>
          </div>
          <label class="batch-task-title">商品标题（留空则自动使用推荐标题）
            <input class="task-title" value="${escapeHTML(task.title || "")}" placeholder="可为这条任务单独填写标题" />
            <small class="batch-title-count${pddTitleByteLength(task.title) > 60 ? " error" : ""}">${pddTitleByteLength(task.title)} / 60 字节</small>
          </label>
        </div>`;
      }).join("");
      batchTaskEditor.querySelectorAll(".batch-task-card").forEach(card => {
        const path = paths[Number(card.dataset.index)];
        const task = batchTaskDrafts.get(path);
        card.querySelector(".task-price-multiplier").oninput = event => { task.price_multiplier = event.target.value.trim(); };
        card.querySelector(".task-price-ending").onchange = event => { task.price_ending = event.target.value; };
        card.querySelector(".task-material").onchange = event => { task.material = event.target.value; };
        card.querySelector(".task-title").oninput = event => {
          task.title = event.target.value.trim();
          const count = card.querySelector(".batch-title-count");
          const length = pddTitleByteLength(event.target.value);
          count.textContent = `${length} / 60 字节`;
          count.classList.toggle("error", length > 60);
        };
      });
    }
    function batchTaskPayloads() {
      syncBatchTaskEditor();
      const tasks = materialPaths().map(path => ({path, ...(batchTaskDrafts.get(path) || {})}));
      if (!tasks.length) throw new Error("请至少填写一个图片空间路径");
      tasks.forEach(task => {
        if (!task.price_multiplier) throw new Error(`任务 ${task.path}：请填写价格倍数`);
        if (!task.price_ending) throw new Error(`任务 ${task.path}：请选择价格尾数`);
        if (!task.material) throw new Error(`任务 ${task.path}：请选择材质`);
        if (task.title && pddTitleByteLength(task.title) > 60) throw new Error(`任务 ${task.path}：商品标题超过 60 字节`);
      });
      return tasks;
    }
    function singleMaterialPath() {
      const paths = materialPaths();
      if (paths.length !== 1) throw new Error("单任务操作只能填写一个图片空间路径；多个路径请点“批量加入并自动执行”");
      return paths[0];
    }
    function notifyBatchFinished(batch) {
      const summary = batch.summary || {};
      const failed = batch.failed_tasks || [];
      const storageKey = `pdd-batch-notified-${batch.batch_id || "unknown"}`;
      if (localStorage.getItem(storageKey)) return;
      localStorage.setItem(storageKey, "1");
      const failedText = failed.length
        ? `失败 ${summary.failed || failed.length} 个：${failed.map(item => item.material_path).join("、")}`
        : `全部 ${summary.succeeded || 0} 个任务均已完成`;
      if ("Notification" in window && Notification.permission === "granted") {
        new Notification("拼多多批量任务已完成", {body: failedText});
      } else if (failed.length) {
        window.alert(`拼多多批量任务已完成。${failedText}。请在批量任务队列查看失败原因。`);
      }
    }
    function setBatchView(batch) {
      const summary = batch.summary || {total: 0, completed: 0, succeeded: 0, failed: 0, waiting: 0};
      const stateNames = {idle: "未开始", running: "执行中", completed: "已完成"};
      const statusNames = {pending: "等待", preparing: "准备中", queued: "已排队", running: "填充中", succeeded: "成功", failed: "失败"};
      batchState.textContent = stateNames[batch.state] || batch.state || "未开始";
      batchSummary.textContent = summary.total
        ? `共 ${summary.total} 个｜已完成 ${summary.completed}｜成功 ${summary.succeeded}｜失败 ${summary.failed}｜待处理 ${summary.waiting}`
        : "可以一次填写多个图片空间路径。";
      const tasks = batch.tasks || [];
      batchList.innerHTML = tasks.map(item => `<div class="batch-item ${escapeHTML(item.status || "")}">
        <div>#${escapeHTML(item.index || "")}｜${escapeHTML(item.material_path || "")}｜${escapeHTML(statusNames[item.status] || item.status || "")}</div>
        <div class="progress-meta">倍数 ${escapeHTML(item.price_multiplier || "")}｜尾数 ${escapeHTML(item.price_ending || "")}｜材质 ${escapeHTML(item.material || "")}</div>
        <div class="progress-meta">标题：${escapeHTML(item.title || "自动推荐")}</div>
        <div class="progress-meta">${escapeHTML(item.message || "")}</div>
      </div>`).join("");
      if (batch.state === "completed" && lastBatchState !== "completed") notifyBatchFinished(batch);
      lastBatchState = batch.state || "";
    }
    async function refreshBatch() {
      try {
        const response = await fetch("/api/batch-queue");
        const data = await response.json();
        setBatchView(data.data || {});
      } catch (_) {
        batchState.textContent = "读取失败";
      }
    }
    materialPath.addEventListener("input", () => syncBatchTaskEditor());
    document.getElementById("applyBatchDefaultsBtn").onclick = () => {
      syncBatchTaskEditor(true);
      writeLog("已把顶部默认值应用到当前全部批量任务，你仍可逐条修改。");
    };
    function requireTaskInputs({needPath = false} = {}) {
      const missing = [];
      if (!priceMultiplier.value.trim()) missing.push("价格倍数");
      if (!priceEnding.value.trim()) missing.push("价格尾数");
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
            <tr><th>价格尾数</th><td>${escapeHTML(pack.price_cent_ending || "")}</td></tr>
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
      priceEnding.value = data.default_price_ending || "8";
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
    document.getElementById("batchBtn").onclick = async () => {
      try {
        const tasks = batchTaskPayloads();
        if ("Notification" in window && Notification.permission === "default") Notification.requestPermission().catch(() => {});
        setState("批量执行中");
        writeLog(`正在加入 ${tasks.length} 个批量任务，每项会使用各自的定价和材质。执行期间请保持 Chrome 已登录拼多多后台，单项失败会自动继续。`);
        const response = await postJSON("/api/batch-queue", {
          folder: folder.value,
          tasks
        });
        setBatchView(response.data || {});
        writeLog(`已加入 ${response.data.added || tasks.length} 个任务，程序会按各自设置顺序处理。全部结束后会汇总提醒失败项。`);
      } catch (err) {
        writeLog(err.message);
        setState("出错");
      }
    };
    document.getElementById("materialBtn").onclick = async () => {
      try {
        setState("等待扫码");
        writeLog("正在把图片空间读取任务交给当前 Chrome 插件；不会打开独立测试浏览器。请确认当前 Chrome 已登录拼多多后台。");
        const data = await postJSON("/api/material", {path: singleMaterialPath()});
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
        const data = await postJSON("/api/plan", {folder: folder.value, path: singleMaterialPath(), price_multiplier: priceMultiplier.value, price_ending: priceEnding.value, material: materialSelect.value});
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
        singleMaterialPath();
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
    refreshDraftHistory();
    refreshBatch();
    setInterval(refreshProgress, 2000);
    setInterval(refreshDraftHistory, 5000);
    setInterval(refreshBatch, 2000);
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
                "default_product_folder": "",
                "default_price_multiplier": "",
                "default_price_ending": "8",
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
            product_data = plugin_product_json(package)
            product_data["_workbenchTaskId"] = int(read_plugin_status().get("id") or int(time.time() * 1000))
            self._send_json({"code": 0, "msg": "ok", "data": product_data})
            return
        if parsed.path == "/api/plugin-progress":
            self._send_json({"code": 0, "msg": "ok", "data": read_plugin_status()})
            return
        if parsed.path == "/api/draft-history":
            self._send_json({"code": 0, "msg": "ok", "data": read_saved_draft_history()})
            return
        if parsed.path == "/api/batch-queue":
            self._send_json({"code": 0, "msg": "ok", "data": batch_queue_view()})
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
                        str(payload.get("price_ending") or "").strip() or None,
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
            if parsed.path == "/api/batch-queue":
                data = submit_batch_queue(payload)
                self._send_json({"code": 0, "msg": "ok", "data": data})
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
    ensure_batch_worker()
    url = f"http://{args.host}:{args.port}"
    print(f"本地工作台已启动: {url}")
    if not args.no_open:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    server.serve_forever()


if __name__ == "__main__":
    main()
