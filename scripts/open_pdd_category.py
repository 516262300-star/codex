from __future__ import annotations

import asyncio
import json
import sys
import time
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from playwright.async_api import Page, async_playwright


ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_PATH = ROOT / ".tmp_tool" / "pdd_category_snapshot.json"
COMMAND_PATH = ROOT / ".tmp_tool" / "pdd_category_command.json"
COMMAND_STATUS_PATH = ROOT / ".tmp_tool" / "pdd_category_command_status.json"
PDD_PROFILE_DIR = ROOT / ".pdd_browser_profile"
MATERIAL_URL = "https://mms.pinduoduo.com/material/upload"
DIR_LIST_URL = "https://mms.pinduoduo.com/garner/mms/file/dir_list"
IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
VIDEO_EXTENSIONS = {"mp4", "mov", "webm", "m4v"}
MEDIA_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS


ATTRIBUTE_ALIASES = {
    "材质": ["材质", "*材质"],
    "拉手类型": ["拉手类型", "重要拉手类型"],
    "使用对象": ["使用对象", "重要使用对象"],
    "风格": ["风格"],
    "外形": ["外形", "重要外形"],
    "孔距": ["孔距", "重要孔距"],
    "表面工艺": ["表面工艺", "重要表面工艺"],
    "安装方式": ["安装方式"],
    "产地": ["产地", "重要产地"],
}

ATTRIBUTE_VALUE_ALIASES = {
    "黄铜": ["黄铜", "铜", "纯铜", "全铜"],
    "锌合金": ["锌合金", "合金"],
    "铝合金": ["铝合金", "铝"],
    "柜门": ["柜门", "柜子门", "衣柜门"],
    "抽屉": ["抽屉"],
    "中古风": ["中古风", "复古", "现代简约"],
}


@dataclass(frozen=True)
class MaterialFolder:
    id: int
    name: str
    parent_dir_id: int


def natural_key(text: str) -> tuple[int, str]:
    match = re.search(r"\d+", text)
    stem = Path(text).stem
    if not match and stem in {"主图", "详情页"}:
        return (0, text.lower())
    return (int(match.group(0)) if match else 999999, text.lower())


def leaf_category(category_path: str) -> str:
    parts = [part.strip() for part in category_path.split(">") if part.strip()]
    return parts[-1] if parts else category_path.strip()


async def wait_for_material_login(page: Page, timeout_ms: int = 600000) -> None:
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        try:
            await page.goto(MATERIAL_URL, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)
            title = await page.title()
            text = await page.locator("body").inner_text(timeout=10000)
            if "图片空间" in title or "图片空间" in text:
                return
        except Exception:
            await page.wait_for_timeout(2000)
    raise TimeoutError("等待拼多多扫码登录超时")


async def list_material_dir(page: Page, dir_id: int = 0, page_no: int = 1, page_size: int = 100) -> tuple[list[MaterialFolder], list[dict[str, Any]]]:
    response = await page.request.post(
        DIR_LIST_URL,
        data={
            "if_query_dir": True,
            "order_by": "create_time desc",
            "dir_id": dir_id,
            "page": page_no,
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
        MaterialFolder(
            id=int(item["id"]),
            name=str(item["name"]),
            parent_dir_id=int(item.get("parent_dir_id") or 0),
        )
        for item in result.get("dir_list") or []
    ]
    files = []
    for item in result.get("file_list") or []:
        name = str(item.get("name") or "")
        extension = str(item.get("extension") or "")
        extra = item.get("extra_info") or {}
        files.append(
            {
                "id": int(item["id"]),
                "filename": f"{name}.{extension}" if extension else name,
                "name": name,
                "extension": extension,
                "url": str(item.get("url") or ""),
                "width": extra.get("width"),
                "height": extra.get("height"),
                "size": extra.get("size"),
            }
        )
    return folders, files


async def find_material_folder(page: Page, parent_dir_id: int, name: str) -> MaterialFolder:
    folders, _ = await list_material_dir(page, parent_dir_id)
    for folder in folders:
        if folder.name == name:
            return folder

    candidates = ", ".join(folder.name for folder in folders[:20])
    raise FileNotFoundError(f"图片空间找不到文件夹 {name!r}; 当前候选: {candidates}")


async def resolve_material_path(page: Page, path: str) -> MaterialFolder:
    parts = [part for part in re.split(r"[\\/]+", path) if part]
    parent_id = 0
    current: MaterialFolder | None = None
    for part in parts:
        current = await find_material_folder(page, parent_id, part)
        parent_id = current.id
    if current is None:
        raise ValueError("图片空间路径不能为空")
    return current


async def read_material_payload(page: Page, material_path: str) -> dict[str, Any]:
    await wait_for_material_login(page)
    folder = await resolve_material_path(page, material_path)
    child_folders, files = await list_material_dir(page, folder.id)
    children: dict[str, Any] = {}
    for child in child_folders:
        _, child_files = await list_material_dir(page, child.id, page_size=200)
        media_files = [
            file
            for file in child_files
            if str(file.get("extension") or "").lower() in MEDIA_EXTENSIONS
        ]
        children[child.name] = sorted(media_files, key=lambda f: natural_key(str(f.get("filename") or "")))

    return {
        "path": material_path,
        "dir_id": folder.id,
        "child_folders": [asdict(folder) for folder in child_folders],
        "files": sorted(files, key=lambda f: natural_key(str(f.get("filename") or ""))),
        "children": children,
    }


async def collect_fields(page: Page) -> list[dict[str, Any]]:
    return await page.evaluate(
        """
        () => {
          const labelNear = (el) => {
            const labelledBy = el.getAttribute('aria-labelledby');
            if (labelledBy) {
              const label = document.getElementById(labelledBy);
              if (label && label.innerText.trim()) return label.innerText.trim();
            }
            const id = el.id;
            if (id) {
              const label = document.querySelector(`label[for="${CSS.escape(id)}"]`);
              if (label && label.innerText.trim()) return label.innerText.trim();
            }
            let cur = el;
            for (let depth = 0; depth < 6 && cur; depth++, cur = cur.parentElement) {
              const texts = Array.from(cur.querySelectorAll('label, .label, [class*="label"], [class*="Label"], [class*="title"], [class*="Title"]'))
                .map(x => (x.innerText || x.textContent || '').trim())
                .filter(Boolean)
                .filter(x => x.length <= 40);
              if (texts.length) return texts[0];
            }
            return '';
          };
          return Array.from(document.querySelectorAll('input, textarea, select, [contenteditable="true"]'))
            .filter(el => {
              const style = getComputedStyle(el);
              const rect = el.getBoundingClientRect();
              return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
            })
            .map((el, index) => ({
              index,
              tag: el.tagName,
              type: el.getAttribute('type') || '',
              label: labelNear(el),
              placeholder: el.getAttribute('placeholder') || '',
              value: el.value || el.innerText || '',
              required: !!el.required || /必填|请选择|请输入/.test(labelNear(el) + ' ' + (el.getAttribute('placeholder') || '')),
              name: el.getAttribute('name') || '',
              id: el.id || '',
            }))
            .filter(x => x.label || x.placeholder || x.value || x.name || x.id);
        }
        """
    )


async def write_snapshot(page: Page, status: str) -> None:
    body_text = ""
    fields: list[dict[str, Any]] = []
    try:
        body_text = await page.locator("body").inner_text(timeout=5000)
        fields = await collect_fields(page)
    except Exception as exc:
        body_text = f"snapshot failed: {exc}"

    payload = {
        "status": status,
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "title": await page.title(),
        "url": page.url,
        "body_preview": body_text[:3000],
        "fields": fields,
    }
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_command_status(payload: dict[str, Any]) -> None:
    COMMAND_STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    COMMAND_STATUS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


async def fill_title(page: Page, title: str) -> dict[str, Any]:
    title_input = page.locator('input[placeholder*="商品标题组成"]')
    count = await title_input.count()
    if count != 1:
        return {"field": "商品标题", "status": "failed", "message": f"标题输入框数量异常: {count}"}

    await title_input.fill(title)
    return {"field": "商品标题", "status": "filled", "value": title}


async def clear_page_selection(page: Page) -> None:
    try:
        await page.evaluate(
            """
            () => {
              const selection = window.getSelection && window.getSelection();
              if (selection) selection.removeAllRanges();
            }
            """
        )
    except Exception:
        pass


async def visible_text_click_point(page: Page, text: str) -> dict[str, Any] | None:
    return await page.evaluate(
        """
        ({ text }) => {
          const clean = (value) => (value || '').replace(/\\s+/g, '');
          const wanted = clean(text);
          const visible = (el) => {
            const style = getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
          };
          const candidates = Array.from(document.querySelectorAll('button, li, div, span, a'))
            .filter(visible)
            .filter(el => {
              const actual = clean(el.innerText || el.textContent || '');
              return actual === wanted;
            })
            .map(el => {
              const rect = el.getBoundingClientRect();
              return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2, area: rect.width * rect.height };
            })
            .filter(item => item.area > 0)
            .sort((a, b) => a.area - b.area);
          return candidates[0] || null;
        }
        """,
        {"text": text},
    )


async def click_visible_text(page: Page, text: str) -> bool:
    point = await visible_text_click_point(page, text)
    if not point:
        return False
    await page.mouse.click(float(point["x"]), float(point["y"]))
    await page.wait_for_timeout(600)
    return True


async def visible_text_contains_click_point(page: Page, text: str) -> dict[str, Any] | None:
    return await page.evaluate(
        """
        ({ text }) => {
          const visible = (el) => {
            const style = getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
          };
          const clean = (value) => (value || '').replace(/\\s+/g, '');
          const wanted = clean(text);
          const candidates = Array.from(document.querySelectorAll('button, span, div, a'))
            .filter(visible)
            .filter(el => clean(el.innerText || el.textContent || '').includes(wanted))
            .map(el => {
              const rect = el.getBoundingClientRect();
              return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2, area: rect.width * rect.height };
            })
            .filter(item => item.area > 0)
            .sort((a, b) => a.area - b.area);
          return candidates[0] || null;
        }
        """,
        {"text": text},
    )


async def click_visible_text_contains(page: Page, text: str) -> bool:
    point = await visible_text_contains_click_point(page, text)
    if not point:
        return False
    await page.mouse.click(float(point["x"]), float(point["y"]))
    await page.wait_for_timeout(600)
    return True


async def small_text_contains_click_point(page: Page, text: str) -> dict[str, Any] | None:
    return await page.evaluate(
        """
        ({ text }) => {
          const visible = (el) => {
            const style = getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
          };
          const clean = (value) => (value || '').replace(/\\s+/g, '');
          const wanted = clean(text);
          const nodes = Array.from(document.querySelectorAll('button, [role="button"], a, span, div'))
            .filter(visible)
            .map(el => {
              const rect = el.getBoundingClientRect();
              const actual = clean(el.innerText || el.textContent || '');
              return { el, actual, x: rect.left + rect.width / 2, y: rect.top + rect.height / 2, area: rect.width * rect.height, width: rect.width, height: rect.height };
            })
            .filter(item => item.actual.includes(wanted) && item.area > 0 && item.area < 50000 && item.width < 480 && item.height < 100)
            .sort((a, b) => a.area - b.area);
          return nodes[0] ? { x: nodes[0].x, y: nodes[0].y } : null;
        }
        """,
        {"text": text},
    )


async def click_small_text_contains(page: Page, text: str) -> bool:
    point = await small_text_contains_click_point(page, text)
    if not point:
        return False
    await page.mouse.click(float(point["x"]), float(point["y"]))
    await page.wait_for_timeout(600)
    return True


async def scroll_text_into_view(page: Page, text: str) -> bool:
    return bool(
        await page.evaluate(
            """
            ({ text }) => {
              const visible = (el) => {
                const style = getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
              };
              const clean = (value) => (value || '').replace(/\\s+/g, '');
              const wanted = clean(text);
              const nodes = Array.from(document.querySelectorAll('button, span, div, p, label, h1, h2, h3'))
                .filter(visible)
                .filter(el => clean(el.innerText || el.textContent || '').includes(wanted))
                .map(el => {
                  const rect = el.getBoundingClientRect();
                  return { el, area: rect.width * rect.height };
                })
                .filter(item => item.area > 0)
                .sort((a, b) => a.area - b.area);
              if (!nodes.length) return false;
              nodes[0].el.scrollIntoView({ block: 'center', inline: 'nearest' });
              return true;
            }
            """,
            {"text": text},
        )
    )


async def confirm_category(page: Page) -> dict[str, Any]:
    button = page.get_by_text("确认发布该类商品", exact=True)
    count = await button.count()
    if count != 1:
        return {"field": "商品分类", "status": "failed", "message": f"确认按钮数量异常: {count}"}

    await button.click()
    await page.wait_for_url("**/goods/goods_add/**", timeout=30000)
    await page.wait_for_timeout(1200)
    return {"field": "商品分类", "status": "confirmed", "url": page.url}


async def select_category_by_search(page: Page, category_path: str, keyword: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    search_input = page.locator('input[placeholder*="关键词搜索分类"]')
    count = await search_input.count()
    if count != 1:
        return [{"field": "商品分类", "status": "search_unavailable", "message": f"搜索框数量异常: {count}"}]

    await search_input.fill(keyword)
    await search_input.press("Enter")
    await page.wait_for_timeout(1200)
    results.append({"field": "商品分类搜索", "status": "filled", "value": keyword})

    leaf = leaf_category(category_path)
    if await click_visible_text(page, leaf):
        results.append({"field": "商品分类", "status": "selected_by_search", "value": leaf})
        results.append(await confirm_category(page))
        return results

    short_leaf = leaf.replace("明装", "").replace("暗装", "")
    if short_leaf and short_leaf != leaf and await click_visible_text(page, short_leaf):
        results.append({"field": "商品分类", "status": "selected_by_search", "value": short_leaf})
        results.append(await confirm_category(page))
        return results

    results.append({"field": "商品分类", "status": "search_no_leaf", "message": f"搜索结果没有找到 {leaf}"})
    return results


async def select_category_by_path(page: Page, category_path: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    parts = [part.strip() for part in category_path.split(">") if part.strip()]
    for part in parts:
        if not await click_visible_text(page, part):
            results.append({"field": "商品分类", "status": "failed", "message": f"找不到类目: {part}"})
            return results
        results.append({"field": "商品分类", "status": "clicked", "value": part})

    results.append(await confirm_category(page))
    return results


def main_image_urls_from_payload(payload: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for item in payload.get("main_images") or []:
        if isinstance(item, dict):
            url = str(item.get("url") or "").strip()
        else:
            url = str(item or "").strip()
        if url:
            urls.append(url)
    return urls


async def category_prefill_state(page: Page) -> dict[str, Any]:
    return await page.evaluate(
        """
        () => {
          const body = document.body.innerText || '';
          const hasPreflight =
            body.includes('商品主图') &&
            body.includes('商品标题') &&
            (body.includes('下一步') || body.includes('完善商品信息'));
          const hasCategory = body.includes('商品分类');
          const titleInput =
            document.querySelector('#goodsNameId input[type="text"]') ||
            document.querySelector('#goods_name input[type="text"]') ||
            Array.from(document.querySelectorAll('input')).find(input => (input.getAttribute('placeholder') || '').includes('商品标题'));
          const uploadMatch = body.match(/上传图片\\s*\\((\\d+)\\s*\\/\\s*\\d+\\)/);
          let imageCount = uploadMatch ? Number(uploadMatch[1]) : 0;
          if (!imageCount) {
            const carousel = document.querySelector('#goodsCarousel') || document.body;
            imageCount = Array.from(carousel.querySelectorAll('img'))
              .filter(img => {
                const rect = img.getBoundingClientRect();
                return rect.width >= 24 && rect.height >= 24;
              }).length;
          }
          return {
            is_preflight: hasPreflight,
            title: titleInput ? titleInput.value || '' : '',
            image_count: imageCount,
            has_category: hasCategory,
            has_next: body.includes('下一步') || body.includes('完善商品信息'),
          };
        }
        """
    )


async def fill_category_prefill_title(page: Page, title: str) -> dict[str, Any]:
    title = title.strip()
    if not title:
        return {"field": "发布前商品标题", "status": "skipped", "message": "标题为空"}

    filled = await page.evaluate(
        """
        ({ title }) => {
          const visible = (el) => {
            const style = getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
          };
          const input =
            document.querySelector('#goodsNameId input[type="text"]') ||
            document.querySelector('#goods_name input[type="text"]') ||
            Array.from(document.querySelectorAll('input')).find(input => visible(input) && (input.getAttribute('placeholder') || '').includes('商品标题'));
          if (!input) return false;
          input.focus();
          const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
          if (setter) setter.call(input, title);
          else input.value = title;
          input.dispatchEvent(new Event('input', { bubbles: true }));
          input.dispatchEvent(new Event('change', { bubbles: true }));
          input.dispatchEvent(new Event('blur', { bubbles: true }));
          input.blur();
          return true;
        }
        """,
        {"title": title},
    )
    await page.wait_for_timeout(2000)
    if not filled:
        return {"field": "发布前商品标题", "status": "failed", "message": "找不到标题输入框"}
    return {"field": "发布前商品标题", "status": "filled", "value": title}


async def upload_category_prefill_main_images(page: Page, urls: list[str]) -> dict[str, Any]:
    if not urls:
        return {"field": "发布前商品主图", "status": "skipped", "message": "没有主图链接"}

    input_count = await page.locator('input[type="file"]').count()
    if input_count < 1:
        return {"field": "发布前商品主图", "status": "failed", "message": "找不到图片上传 input"}

    upload_dir = ROOT / ".tmp_tool" / "category_preflight_uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    paths: list[str] = []
    for index, url in enumerate(urls[:10], start=1):
        response = await page.request.get(url, timeout=60000)
        if not response.ok:
            return {"field": "发布前商品主图", "status": "failed", "message": f"主图下载失败: HTTP {response.status}"}
        content_type = response.headers.get("content-type", "")
        suffix = ".jpg"
        if "png" in content_type:
            suffix = ".png"
        elif "webp" in content_type:
            suffix = ".webp"
        elif "jpeg" in content_type or "jpg" in content_type:
            suffix = ".jpg"
        path = upload_dir / f"main_{index}{suffix}"
        path.write_bytes(await response.body())
        paths.append(str(path))

    await page.locator('input[type="file"]').first.set_input_files(paths)
    await page.wait_for_timeout(3500)
    return {"field": "发布前商品主图", "status": "uploaded", "count": len(paths)}


async def select_category_on_prefill_page(page: Page, category_path: str) -> dict[str, Any]:
    leaf = leaf_category(category_path)
    short_leaf = leaf.replace("明装", "").replace("暗装", "")
    for value in (category_path, leaf, short_leaf):
        if value and await click_visible_text_contains(page, value):
            return {"field": "发布前商品分类", "status": "selected", "value": value}
    return {"field": "发布前商品分类", "status": "failed", "message": f"找不到推荐分类: {category_path}"}


async def complete_category_prefill_page(page: Page, payload: dict[str, Any], state: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    state = state or await category_prefill_state(page)
    results.append({"field": "发布前信息页", "status": "detected", "image_count": state.get("image_count"), "title": state.get("title")})

    image_count = int(state.get("image_count") or 0)
    if image_count <= 0:
        upload_result = await upload_category_prefill_main_images(page, main_image_urls_from_payload(payload))
        results.append(upload_result)
        state = await category_prefill_state(page)
        image_count = int(state.get("image_count") or 0)
    else:
        results.append({"field": "发布前商品主图", "status": "already_ok", "count": image_count})

    title = str(payload.get("title") or "").strip()
    if title and str(state.get("title") or "").strip() != title:
        results.append(await fill_category_prefill_title(page, title))
    else:
        results.append({"field": "发布前商品标题", "status": "already_ok", "value": state.get("title") or title})

    category_path = str(payload.get("category") or "").strip()
    if category_path and state.get("has_category"):
        results.append(await select_category_on_prefill_page(page, category_path))
    elif category_path:
        results.append({"field": "发布前商品分类", "status": "skipped", "message": "当前发布前信息页没有商品分类区域"})

    if await click_visible_text_contains(page, "下一步"):
        try:
            await page.wait_for_url("**/goods/goods_add/**", timeout=30000)
            await page.wait_for_timeout(1200)
            results.append({"field": "发布前下一步", "status": "clicked", "url": page.url})
        except Exception:
            results.append({"field": "发布前下一步", "status": "clicked_wait_timeout", "url": page.url})
    else:
        results.append({"field": "发布前下一步", "status": "failed", "message": "找不到下一步按钮"})
    return results


async def ensure_category_page_selected(page: Page, payload: dict[str, Any]) -> list[dict[str, Any]]:
    if "/goods/goods_add/" in page.url:
        return [{"field": "商品分类", "status": "already_on_edit_page", "url": page.url}]

    body_text = await page.locator("body").inner_text(timeout=5000)
    if "请向右滑块完成拼图" in body_text or ("滑块" in body_text and "拼图" in body_text):
        return [{"field": "商品分类", "status": "captcha_required", "message": "拼多多出现滑块验证，请先在浏览器里手动完成验证，然后再点第三步继续填充"}]
    prefill_state = await category_prefill_state(page)
    if prefill_state.get("is_preflight"):
        return await complete_category_prefill_page(page, payload, prefill_state)
    if "选择分类" not in body_text:
        return [{"field": "商品分类", "status": "skipped", "message": "当前不是选择分类页"}]

    category_path = str(payload.get("category") or "").strip()
    if not category_path:
        return [{"field": "商品分类", "status": "failed", "message": "缺少 category"}]

    keyword = str(payload.get("category_keyword") or "").strip() or leaf_category(category_path).replace("明装", "")
    results = await select_category_by_search(page, category_path, keyword)
    if any(item.get("status") == "confirmed" for item in results):
        return results

    results.append({"field": "商品分类", "status": "fallback_to_path"})
    await page.goto("https://mms.pinduoduo.com/goods/category", wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(1200)
    results.extend(await select_category_by_path(page, category_path))
    return results


async def field_click_point(page: Page, labels: list[str]) -> dict[str, Any] | None:
    return await page.evaluate(
        """
        ({ labels }) => {
          const visible = (el) => {
            const style = getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
          };
          const clean = (text) => (text || '').replace(/\\s+/g, '').replace(/^\\*/, '');
          const wanted = labels.map(clean);
          const labelNodes = Array.from(document.querySelectorAll('label, span, div, p'))
            .filter(el => {
              if (!visible(el)) return false;
              const text = clean(el.innerText || el.textContent || '');
              return wanted.some(label => text === label || text.endsWith(label));
            });

          for (const label of labelNodes) {
            let cur = label;
            for (let depth = 0; depth < 8 && cur; depth++, cur = cur.parentElement) {
              const candidates = Array.from(cur.querySelectorAll('input[placeholder="请选择"], .ant-select-selector, [class*="select"][class*="selector"], [class*="Select"][class*="selector"]'))
                .filter(visible)
                .filter(el => {
                  const rect = el.getBoundingClientRect();
                  const labelRect = label.getBoundingClientRect();
                  return Math.abs(rect.top - labelRect.top) < 80 || Math.abs(rect.bottom - labelRect.bottom) < 80;
                });
              if (candidates.length) {
                const target = candidates[candidates.length - 1];
                const rect = target.getBoundingClientRect();
                const text = target.value || target.innerText || '';
                return {
                  x: rect.left + Math.min(rect.width - 8, Math.max(8, rect.width / 2)),
                  y: rect.top + rect.height / 2,
                  currentText: text.trim(),
                };
              }
            }
          }
          return null;
        }
        """,
        {"labels": labels},
    )


async def option_click_point(page: Page, value: str) -> dict[str, Any] | None:
    return await page.evaluate(
        """
        ({ value }) => {
          const visible = (el) => {
            const style = getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
          };
          const clean = (text) => (text || '').replace(/\\s+/g, '');
          const wanted = clean(value);
          const nodes = Array.from(document.querySelectorAll('[role="option"], .ant-select-item-option, .ant-select-item-option-content, li, div, span'))
            .filter(visible)
            .map(el => {
              const text = clean(el.innerText || el.textContent || '');
              let score = 999;
              if (text === wanted) score = 0;
              else if (text && (text.includes(wanted) || wanted.includes(text))) score = 1;
              return { el, text, score };
            })
            .filter(item => item.score < 999)
            .sort((a, b) => {
              const ar = a.el.getBoundingClientRect();
              const br = b.el.getBoundingClientRect();
              const aOption = a.el.matches('[role="option"], .ant-select-item-option') ? 0 : 1;
              const bOption = b.el.matches('[role="option"], .ant-select-item-option') ? 0 : 1;
              return a.score - b.score || aOption - bOption || (br.width * br.height) - (ar.width * ar.height);
            });
          if (!nodes.length) return null;
          const rect = nodes[0].el.getBoundingClientRect();
          return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2, text: nodes[0].text };
        }
        """,
        {"value": value},
    )


async def select_attribute_value(page: Page, name: str, value: str) -> dict[str, Any]:
    labels = ATTRIBUTE_ALIASES.get(name, [name])
    field_point = await field_click_point(page, labels)
    if not field_point:
        return {"field": name, "status": "failed", "message": f"找不到属性字段: {name}"}

    current_text = str(field_point.get("currentText") or "").strip()
    if current_text == value or (value and value in current_text):
        return {"field": name, "status": "already_ok", "value": value}

    await page.mouse.click(float(field_point["x"]), float(field_point["y"]))
    await page.wait_for_timeout(300)

    aliases = ATTRIBUTE_VALUE_ALIASES.get(value, [value])
    option_point = None
    matched_value = value
    for alias in aliases:
        option_point = await option_click_point(page, alias)
        if option_point:
            matched_value = alias
            break
    if not option_point:
        return {"field": name, "status": "failed", "message": f"找不到选项: {value}"}

    await page.mouse.click(float(option_point["x"]), float(option_point["y"]))
    await page.wait_for_timeout(300)
    return {"field": name, "status": "selected", "value": value, "matched": option_point.get("text") or matched_value}


async def select_checkbox_option(page: Page, field_name: str, value: str) -> dict[str, Any]:
    labels = ATTRIBUTE_ALIASES.get(field_name, [field_name])
    field_point = await field_click_point(page, labels)
    if not field_point:
        return {"field": field_name, "status": "failed", "message": f"找不到属性字段: {field_name}"}

    current_text = str(field_point.get("currentText") or "").strip()
    if value and value in current_text:
        return {"field": field_name, "status": "already_ok", "value": value}

    await page.mouse.click(float(field_point["x"]), float(field_point["y"]))
    await page.wait_for_timeout(400)

    aliases = ATTRIBUTE_VALUE_ALIASES.get(value, [value])
    async def checkbox_option_point(alias: str) -> dict[str, Any] | None:
        return await page.evaluate(
            """
            ({ value }) => {
              const clean = (text) => (text || '').replace(/\\s+/g, '');
              const wanted = clean(value);
              const visible = (el) => {
                const style = getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
              };
              const rows = Array.from(document.querySelectorAll('[role="option"], .ant-select-item-option, li, div'))
                .filter(visible)
                .map(el => {
                  const rect = el.getBoundingClientRect();
                  const text = clean(el.innerText || el.textContent || '');
                  return { el, text, rect, area: rect.width * rect.height };
                })
                .filter(item => item.text === wanted || (item.text && item.text.includes(wanted)))
                .sort((a, b) => {
                  const aOption = a.el.matches('[role="option"], .ant-select-item-option, li') ? 0 : 1;
                  const bOption = b.el.matches('[role="option"], .ant-select-item-option, li') ? 0 : 1;
                  return aOption - bOption || a.area - b.area;
                });
              if (!rows.length) return null;
              const row = rows[0];
              const checkbox = row.el.querySelector('input[type="checkbox"], .ant-checkbox-input, [class*="checkbox"]');
              if (checkbox && visible(checkbox)) {
                const rect = checkbox.getBoundingClientRect();
                return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2, text: row.text };
              }
              return { x: row.rect.left + Math.min(28, Math.max(12, row.rect.width * 0.12)), y: row.rect.top + row.rect.height / 2, text: row.text };
            }
            """,
            {"value": alias},
        )

    for alias in aliases:
        point = await checkbox_option_point(alias)
        if point:
            await page.mouse.click(float(point["x"]), float(point["y"]))
            await page.wait_for_timeout(350)
            return {"field": field_name, "status": "selected", "value": value, "matched": point.get("text") or alias}

    try:
        await page.keyboard.type(value)
        await page.wait_for_timeout(500)
    except Exception:
        pass

    for alias in aliases:
        point = await checkbox_option_point(alias)
        if point:
            await page.mouse.click(float(point["x"]), float(point["y"]))
            await page.wait_for_timeout(350)
            return {"field": field_name, "status": "selected", "value": value, "matched": point.get("text") or alias}

    return {"field": field_name, "status": "failed", "message": f"找不到选项: {value}"}


async def read_title(page: Page) -> str:
    title_input = page.locator('input[placeholder*="商品标题组成"]')
    count = await title_input.count()
    if count != 1:
        return ""
    return await title_input.input_value()


async def clean_title_if_needed(page: Page, title: str) -> dict[str, Any] | None:
    current = await read_title(page)
    if not current or current == title:
        return None

    pieces = []
    for text in ATTRIBUTE_ALIASES:
        pieces.append(text)
    for text in ("梵居匠", "锌合金", "黄铜", "明装拉手", "抽屉", "柜门", "中古风", "球形", "单孔", "拉丝", "打孔", "中国大陆"):
        if text not in pieces:
            pieces.append(text)

    if len(current) > len(title) + 6 or sum(1 for piece in pieces if piece and piece in current) >= 6:
        await fill_title(page, title)
        return {"field": "商品标题", "status": "cleaned", "oldValue": current, "value": title}
    return None


async def select_attribute_values(page: Page, name: str, value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        results = []
        for item in value:
            item_text = str(item or "").strip()
            if item_text:
                if name == "使用对象":
                    results.append(await select_checkbox_option(page, name, item_text))
                else:
                    results.append(await select_attribute_value(page, name, item_text))
        return results

    value_text = str(value or "").strip()
    if not value_text:
        return []
    return [await select_attribute_value(page, name, value_text)]


async def field_values_snapshot(page: Page) -> dict[str, str]:
    return await page.evaluate(
        """
        () => {
          const inputs = Array.from(document.querySelectorAll('input, textarea, select, [contenteditable="true"]'))
            .filter(el => {
              const style = getComputedStyle(el);
              const rect = el.getBoundingClientRect();
              return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
            })
            .map(el => el.value || el.innerText || '');
          return {
            title: inputs[1] || '',
            brand: inputs[2] || '',
            material: inputs[3] || '',
            type: inputs[4] || '',
            object: inputs[5] || '',
            style: inputs[6] || '',
            shape: inputs[7] || '',
            holeDistance: inputs[8] || '',
            surface: inputs[9] || '',
            install: inputs[10] || '',
            origin: inputs[11] || '',
          }
        }
        """,
    )


async def fill_basic_info(page: Page, payload: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    results.extend(await ensure_category_page_selected(page, payload))

    title = str(payload.get("title") or "").strip()
    if title:
        results.append(await fill_title(page, title))

    attributes = payload.get("attributes") or {}
    cleaned = await clean_title_if_needed(page, title)
    if cleaned:
        results.append(cleaned)

    await scroll_text_into_view(page, "商品属性")
    await page.wait_for_timeout(600)

    for name, value in attributes.items():
        if name == "品牌":
            continue
        results.extend(await select_attribute_values(page, name, value))

    results.append({"field": "当前字段快照", "status": "read", "values": await field_values_snapshot(page)})

    return results


async def collect_specs_area(page: Page) -> dict[str, Any]:
    return await page.evaluate(
        """
        () => {
          const visible = (el) => {
            const style = getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
          };
          const allText = (el) => (el.innerText || el.textContent || '').trim();
          const inputs = Array.from(document.querySelectorAll('input, textarea, select, [contenteditable="true"]'))
            .filter(visible)
            .map((el, index) => {
              const rect = el.getBoundingClientRect();
              return {
                index,
                placeholder: el.getAttribute('placeholder') || '',
                value: el.value || el.innerText || '',
                type: el.getAttribute('type') || '',
                x: Math.round(rect.left),
                y: Math.round(rect.top),
                width: Math.round(rect.width),
                height: Math.round(rect.height),
              };
            });
          const buttons = Array.from(document.querySelectorAll('button, span, div, a'))
            .filter(visible)
            .map((el) => {
              const rect = el.getBoundingClientRect();
              return {
                text: allText(el),
                x: Math.round(rect.left),
                y: Math.round(rect.top),
                width: Math.round(rect.width),
                height: Math.round(rect.height),
              };
            })
            .filter(item => /规格|库存|价格|全屏|添加|AI|图片/.test(item.text))
            .slice(0, 80);
          const body = document.body.innerText || '';
          const specStart = body.indexOf('2规格与库存');
          const serviceStart = body.indexOf('3服务与承诺');
          return {
            url: location.href,
            buttons,
            inputs,
            spec_text: specStart >= 0 ? body.slice(specStart, serviceStart > specStart ? serviceStart : specStart + 2500) : '',
          };
        }
        """
    )


async def fill_specs(page: Page, payload: dict[str, Any]) -> list[dict[str, Any]]:
    package = payload.get("asset_package") or {}
    results: list[dict[str, Any]] = [
        {
            "field": "素材包",
            "status": "loaded",
            "sku_count": len(package.get("sku_specs") or []),
            "main_image_count": len(package.get("main_images") or []),
            "detail_image_count": len(package.get("detail_images") or []),
        }
    ]
    if "/goods/goods_add/" not in page.url:
        results.extend(
            await ensure_category_page_selected(
                page,
                {
                    "category": package.get("category_path") or "基础建材 > 家用五金 > 拉手 > 明装小拉手",
                    "category_keyword": package.get("category_keyword") or "小拉手",
                    "title": package.get("title") or "",
                    "main_images": package.get("main_images") or [],
                },
            )
        )

    if "/goods/goods_add/" not in page.url:
        results.append({"field": "发布页", "status": "failed", "message": "当前还没有进入商品编辑页，请先选择类目并确认发布该类商品"})
        return results

    await scroll_text_into_view(page, "2规格与库存")
    await page.wait_for_timeout(700)

    spec_type = str(((package.get("checks") or {}).get("spec_type")) or "型号")
    specs = list(package.get("sku_specs") or [])
    spec_type_result = await select_spec_type(page, spec_type)
    results.append(spec_type_result)
    if spec_type_result.get("status") in {"selected", "already_ok"}:
        results.extend(await fill_spec_names(page, specs))
        await scroll_text_into_view(page, "价格及库存")
        await page.wait_for_timeout(800)
        results.extend(await fill_price_rows(page, specs))
        results.extend(await fill_listing_extra_fields(page, package))
    results.append({"field": "规格区域快照", "status": "read", "values": await collect_specs_area(page)})
    return results


async def spec_type_click_point(page: Page) -> dict[str, Any] | None:
    return await page.evaluate(
        """
        () => {
          const visible = (el) => {
            const style = getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
          };
          const textTop = (needle) => {
            const nodes = Array.from(document.querySelectorAll('div, span, p, label'))
              .filter(visible)
              .map(el => {
                const rect = el.getBoundingClientRect();
                return { el, text: (el.innerText || el.textContent || '').replace(/\\s+/g, ''), area: rect.width * rect.height, top: rect.top };
              })
              .filter(item => item.text.includes(needle) && item.area > 0 && item.area < 30000)
              .sort((a, b) => a.area - b.area || a.top - b.top);
            if (!nodes.length) return null;
            return nodes[0].top;
          };
          const specTop = textTop('商品规格') ?? 0;
          const priceTop = textTop('价格及库存') ?? 99999;
          const inputs = Array.from(document.querySelectorAll('input[placeholder*="规格类型"], .ant-select-selector, input[placeholder="请选择"]'))
            .filter(visible)
            .map(el => {
              const rect = el.getBoundingClientRect();
              const input = el.matches('input') ? el : el.querySelector('input');
              const text = (input && input.value) || el.innerText || '';
              const placeholder = (input && input.getAttribute('placeholder')) || el.getAttribute('placeholder') || '';
              return {
                x: rect.left + rect.width / 2,
                y: rect.top + rect.height / 2,
                top: rect.top,
                left: rect.left,
                text: text.trim(),
                placeholder,
              };
            })
            .filter(item => item.top > specTop && item.top < priceTop)
            .sort((a, b) => {
              const aScore = a.placeholder.includes('规格类型') ? 0 : 1;
              const bScore = b.placeholder.includes('规格类型') ? 0 : 1;
              return aScore - bScore || a.top - b.top || a.left - b.left;
            });
          if (!inputs.length) return null;
          return inputs[0];
        }
        """
    )


async def add_spec_type_button_point(page: Page) -> dict[str, Any] | None:
    return await page.evaluate(
        """
        () => {
          const visible = (el) => {
            const style = getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
          };
          const clean = (text) => (text || '').replace(/\\s+/g, '');
          const exactTextNodes = Array.from(document.querySelectorAll('button, [role="button"], a, span, div'))
            .filter(visible)
            .map(el => {
              const rect = el.getBoundingClientRect();
              const text = clean(el.innerText || el.textContent || '');
              return { text, left: rect.left, top: rect.top, width: rect.width, height: rect.height, area: rect.width * rect.height };
            })
            .filter(item => /^\\+?添加规格类型\\(\\d\\/2\\)$/.test(item.text) && item.area > 0)
            .sort((a, b) => a.area - b.area);
          if (exactTextNodes[0]) {
            const item = exactTextNodes[0];
            return { x: item.left + item.width / 2, y: item.top + item.height / 2 };
          }

          const candidates = Array.from(document.querySelectorAll('button, [role="button"], a, div, span'))
            .filter(visible)
            .map(el => {
              const text = clean(el.innerText || el.textContent || '');
              let target = null;
              let cur = el;
              for (let depth = 0; depth < 5 && cur; depth++, cur = cur.parentElement) {
                if (/button/i.test(cur.tagName) || cur.getAttribute('role') === 'button') {
                  target = cur;
                  break;
                }
              }
              target = target || el;
              const rect = target.getBoundingClientRect();
              const targetText = clean(target.innerText || target.textContent || text);
              return { el: target, text: targetText, x: rect.left + rect.width / 2, y: rect.top + rect.height / 2, area: rect.width * rect.height, width: rect.width, height: rect.height };
            })
            .filter(item => item.text.includes('添加规格类型') && item.area > 0 && item.area < 60000 && item.width < 420 && item.height < 90)
            .sort((a, b) => a.area - b.area);
          if (candidates[0]) return { x: candidates[0].x, y: candidates[0].y };

          const rowFallbacks = Array.from(document.querySelectorAll('div, span'))
            .filter(visible)
            .map(el => {
              const rect = el.getBoundingClientRect();
              const text = clean(el.innerText || el.textContent || '');
              return { text, left: rect.left, top: rect.top, width: rect.width, height: rect.height, area: rect.width * rect.height };
            })
            .filter(item => item.text.includes('添加规格类型') && item.area > 0 && item.area < 120000 && item.width < 1200 && item.height < 120)
            .sort((a, b) => a.area - b.area);
          if (!rowFallbacks.length) return null;
          const row = rowFallbacks[0];
          return { x: row.left + Math.min(160, Math.max(80, row.width * 0.12)), y: row.top + row.height / 2 };
        }
        """
    )


async def choose_spec_type_from_open_dropdown(page: Page, spec_type: str) -> bool:
    option_point = await option_click_point(page, spec_type)
    if option_point:
        await page.mouse.click(float(option_point["x"]), float(option_point["y"]))
        await page.wait_for_timeout(1000)
        return True

    await page.keyboard.type(spec_type)
    await page.wait_for_timeout(400)
    option_point = await option_click_point(page, spec_type)
    if option_point:
        await page.mouse.click(float(option_point["x"]), float(option_point["y"]))
        await page.wait_for_timeout(1000)
        return True

    await page.keyboard.press("Enter")
    await page.wait_for_timeout(1000)
    return False


async def choose_spec_type_by_input_placeholder(page: Page, spec_type: str) -> bool:
    locator = page.locator('input[placeholder^="规格类型"]').first
    try:
        count = await page.locator('input[placeholder^="规格类型"]').count()
    except Exception:
        count = 0
    if count <= 0:
        return False

    input_box = page.locator('input[placeholder^="规格类型"]').first
    try:
        await input_box.scroll_into_view_if_needed(timeout=5000)
        await page.wait_for_timeout(500)
        current = (await input_box.input_value(timeout=3000)).strip()
        if current == spec_type:
            return True
        await input_box.click(timeout=5000)
        await page.wait_for_timeout(300)
        await input_box.fill(spec_type)
        await page.wait_for_timeout(500)
        if await choose_spec_type_from_open_dropdown(page, spec_type):
            return True
        await input_box.press("Enter")
        await page.wait_for_timeout(1000)
        try:
            current = (await input_box.input_value(timeout=3000)).strip()
            if current == spec_type:
                return True
        except Exception:
            pass
    except Exception:
        return False
    return await spec_type_is_selected(page, spec_type)


async def spec_type_is_selected(page: Page, spec_type: str) -> bool:
    if await has_spec_name_input(page):
        return True
    next_point = await spec_type_click_point(page)
    selected_text = str((next_point or {}).get("text") or "").strip()
    text = await page.locator("body").inner_text(timeout=5000)
    if selected_text and (spec_type in selected_text or selected_text in spec_type):
        return True
    if f"商品规格\n{spec_type}" in text or f"商品规格 {spec_type}" in text:
        return True
    return spec_type in text and "添加规格类型(0/2)" not in text


async def select_spec_type(page: Page, spec_type: str) -> dict[str, Any]:
    if await has_spec_name_input(page):
        return {"field": "规格类型", "status": "already_ok", "value": spec_type}

    text = await page.locator("body").inner_text(timeout=5000)
    if f"商品规格\n{spec_type}" in text or f"商品规格 {spec_type}" in text:
        return {"field": "规格类型", "status": "already_ok", "value": spec_type}

    if await choose_spec_type_by_input_placeholder(page, spec_type):
        return {"field": "规格类型", "status": "selected", "value": spec_type}

    point = await spec_type_click_point(page)
    if point:
        current = str(point.get("text") or "").strip()
        if current == spec_type:
            return {"field": "规格类型", "status": "already_ok", "value": spec_type}

        await page.mouse.click(float(point["x"]), float(point["y"]))
        await page.wait_for_timeout(400)
        await choose_spec_type_from_open_dropdown(page, spec_type)
        if await spec_type_is_selected(page, spec_type):
            return {"field": "规格类型", "status": "selected", "value": spec_type}

    add_point = await add_spec_type_button_point(page)
    if add_point:
        await page.mouse.click(float(add_point["x"]), float(add_point["y"]))
        await page.wait_for_timeout(500)
        if await spec_type_is_selected(page, spec_type):
            return {"field": "规格类型", "status": "selected", "value": spec_type}
        if await choose_spec_type_by_input_placeholder(page, spec_type):
            return {"field": "规格类型", "status": "selected", "value": spec_type}
        if await choose_spec_type_from_open_dropdown(page, spec_type):
            if await spec_type_is_selected(page, spec_type):
                return {"field": "规格类型", "status": "selected", "value": spec_type}

        point = await spec_type_click_point(page)
        if point:
            await page.mouse.click(float(point["x"]), float(point["y"]))
            await page.wait_for_timeout(400)
            await choose_spec_type_from_open_dropdown(page, spec_type)
            if await spec_type_is_selected(page, spec_type):
                return {"field": "规格类型", "status": "selected", "value": spec_type}

    return {
        "field": "规格类型",
        "status": "failed",
        "message": f"规格类型未选中: 目标 {spec_type}；请确认页面上方“规格类型1”下拉框可点击",
    }


async def has_spec_name_input(page: Page) -> bool:
    return bool(
        await page.evaluate(
            """
            () => {
              const visible = (el) => {
                const style = getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
              };
              return Array.from(document.querySelectorAll('input, textarea, [contenteditable="true"]'))
                .filter(visible)
                .some(el => ((el.getAttribute('placeholder') || '') + ' ' + (el.value || el.innerText || '')).includes('规格名称'));
            }
            """
        )
    )


async def fill_input_at_point(page: Page, point: dict[str, Any], value: Any) -> None:
    await page.mouse.click(float(point["x"]), float(point["y"]))
    focused = await page.evaluate(
        """
        () => {
          const el = document.activeElement;
          if (!el) return false;
          const tag = (el.tagName || '').toLowerCase();
          return tag === 'input' || tag === 'textarea' || el.isContentEditable;
        }
        """
    )
    if not focused:
        await clear_page_selection(page)
        raise RuntimeError("焦点没有落在输入框，已停止本次输入，避免误选整页文字")
    await page.keyboard.press("Control+A")
    await page.keyboard.type(str(value))
    await page.wait_for_timeout(150)
    await clear_page_selection(page)


async def page_contains_text(page: Page, value: str) -> bool:
    body = await page.locator("body").inner_text(timeout=5000)
    return value in body


async def fill_spec_name_at_point(page: Page, point: dict[str, Any], name: str) -> bool:
    await page.mouse.click(float(point["x"]), float(point["y"]))
    await page.evaluate(
        """
        ({ value }) => {
          const input = document.activeElement;
          if (!input || !('value' in input)) return false;
          const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
          if (setter) setter.call(input, value);
          else input.value = value;
          input.dispatchEvent(new Event('input', { bubbles: true }));
          input.dispatchEvent(new Event('change', { bubbles: true }));
          return true;
        }
        """,
        {"value": name},
    )
    await page.keyboard.press("Tab")
    await page.wait_for_timeout(500)
    return bool(
        await page.evaluate(
            """
            ({ x, y, value }) => {
              const el = document.elementFromPoint(x, y);
              if (!el || !('value' in el)) return false;
              return String(el.value || '').trim() === String(value || '').trim();
            }
            """,
            {"x": float(point["x"]), "y": float(point["y"]), "value": name},
        )
    ) or await page_contains_text(page, name)


async def fill_next_spec_name_input(page: Page, name: str) -> bool:
    inputs = page.locator('input[placeholder="请输入规格名称"]')
    try:
        count = await inputs.count()
    except Exception:
        return False

    candidates: list[tuple[int, str]] = []
    for index in range(count):
        item = inputs.nth(index)
        try:
            box = await item.bounding_box(timeout=1000)
            if not box or box["width"] <= 0 or box["height"] <= 0:
                continue
            current = (await item.input_value(timeout=1000)).strip()
        except Exception:
            continue
        if not current:
            candidates.append((index, current))

    if not candidates:
        return False

    target = inputs.nth(candidates[0][0])
    try:
        await target.scroll_into_view_if_needed(timeout=5000)
        await page.wait_for_timeout(250)
        await target.click(timeout=5000)
        await target.press("Control+A")
        await page.keyboard.type(name)
        await target.press("Tab")
        await page.wait_for_timeout(700)
        return (await target.input_value(timeout=3000)).strip() == name
    except Exception:
        return False


async def spec_value_input_point(page: Page) -> dict[str, Any] | None:
    return await page.evaluate(
        """
        () => {
          const visible = (el) => {
            const style = getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
          };
          const textTop = (needle) => {
            const nodes = Array.from(document.querySelectorAll('div, span, p, label'))
              .filter(visible)
              .map(el => {
                const rect = el.getBoundingClientRect();
                return { el, text: (el.innerText || el.textContent || '').replace(/\\s+/g, ''), area: rect.width * rect.height, top: rect.top };
              })
              .filter(item => item.text.includes(needle) && item.area > 0 && item.area < 30000)
              .sort((a, b) => a.area - b.area || a.top - b.top);
            if (!nodes.length) return null;
            return nodes[0].top;
          };
          const specTop = textTop('商品规格') ?? 0;
          const priceTop = textTop('价格及库存') ?? 99999;
              const inputs = Array.from(document.querySelectorAll('input, textarea, [contenteditable="true"]'))
            .filter(visible)
            .map(el => {
              const rect = el.getBoundingClientRect();
              const placeholder = el.getAttribute('placeholder') || '';
              return {
                x: rect.left + rect.width / 2,
                y: rect.top + rect.height / 2,
                top: rect.top,
                left: rect.left,
                value: el.value || el.innerText || '',
                placeholder,
                score: placeholder.includes('规格名称') ? 0 : 1,
              };
            })
            .filter(item => item.top > specTop && item.top < priceTop)
            .filter(item => !item.value.trim())
            .sort((a, b) => a.score - b.score || a.top - b.top || a.left - b.left);
          return inputs[0] || null;
        }
        """
    )


async def fill_spec_names(page: Page, specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for spec in specs:
        name = str(spec.get("spec_name") or "").strip()
        if not name:
            continue
        if await page_contains_text(page, name):
            results.append({"field": "规格名称", "status": "already_ok", "value": name})
            continue
        success = await fill_next_spec_name_input(page, name)
        if not success:
            results.append({"field": "规格名称", "status": "failed", "value": name, "message": "没有可填写的普通规格名称空框；不会点击添加定制规格"})
            continue
        await page.wait_for_timeout(350)
        results.append({"field": "规格名称", "status": "filled", "value": name})
    await page.wait_for_timeout(1200)
    return results


async def price_table_rows(page: Page) -> list[dict[str, Any]]:
    return await page.evaluate(
        """
        () => {
          const visible = (el) => {
            const style = getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
          };
          const priceNodes = Array.from(document.querySelectorAll('div, span, p, label'))
            .filter(visible)
            .map(el => {
              const rect = el.getBoundingClientRect();
              return { el, text: (el.innerText || el.textContent || '').replace(/\\s+/g, ''), area: rect.width * rect.height, top: rect.top };
            })
            .filter(item => item.text.includes('价格及库存') && item.area > 0 && item.area < 30000)
            .sort((a, b) => a.area - b.area || a.top - b.top);
          const priceTop = priceNodes.length ? priceNodes[0].top : 0;
          const inputs = Array.from(document.querySelectorAll('input'))
            .filter(visible)
            .map(el => {
              const rect = el.getBoundingClientRect();
              let rowText = '';
              let cur = el;
              for (let depth = 0; depth < 8 && cur; depth++, cur = cur.parentElement) {
                const text = (cur.innerText || cur.textContent || '').trim();
                const r = cur.getBoundingClientRect();
                if (text && r.width > 500 && r.height > 25 && r.height < 140) {
                  rowText = text;
                  break;
                }
              }
              return {
                x: rect.left + rect.width / 2,
                y: rect.top + rect.height / 2,
                top: Math.round(rect.top),
                left: Math.round(rect.left),
                placeholder: el.getAttribute('placeholder') || '',
                value: el.value || '',
                width: Math.round(rect.width),
                rowText,
              };
            })
            .filter(item => item.top > priceTop + 30)
            .filter(item => item.placeholder.includes('请输入'))
            .sort((a, b) => a.top - b.top || a.left - b.left);

          const rows = [];
          for (const input of inputs) {
            const row = rows.find(items => Math.abs(items[0].top - input.top) <= 8);
            if (row) row.push(input);
            else rows.push([input]);
          }
          return rows.map(row => {
            const sorted = row.sort((a, b) => a.left - b.left);
            const text = sorted.map(item => item.rowText).find(Boolean) || '';
            const name = (text.split('\\n').map(part => part.trim()).filter(Boolean)[0] || '').replace(/\\s+/g, '');
            return { name, text, inputs: sorted };
          });
        }
        """
    )


async def fill_price_rows(page: Page, specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    for index, spec in enumerate(specs):
        spec_name = str(spec.get("spec_name") or "").strip()
        values = [
            spec.get("stock"),
            spec.get("group_price"),
            spec.get("single_price"),
            spec.get("spec_code"),
        ]
        labels = ["库存", "拼单价", "单买价", "规格编码"]
        filled = await page.evaluate(
            """
            ({ specName, values }) => {
              const clean = (text) => String(text || '').replace(/\\s+/g, '');
              const wanted = clean(specName);
              const visible = (el) => {
                const style = getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
              };
              const setInput = (input, value) => {
                input.focus();
                const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
                if (setter) setter.call(input, String(value ?? ''));
                else input.value = String(value ?? '');
                input.dispatchEvent(new Event('input', { bubbles: true }));
                input.dispatchEvent(new Event('change', { bubbles: true }));
                input.blur();
              };
              const rowCandidates = Array.from(document.querySelectorAll('tr, [role="row"], div'))
                .filter(visible)
                .map(el => {
                  const rect = el.getBoundingClientRect();
                  const text = clean(el.innerText || el.textContent || '');
                  return { el, text, area: rect.width * rect.height, width: rect.width, height: rect.height };
                })
                .filter(item => item.text.includes(wanted) && item.width > 450 && item.height >= 28 && item.height < 180)
                .sort((a, b) => a.area - b.area);

              for (const candidate of rowCandidates) {
                const inputs = Array.from(candidate.el.querySelectorAll('input'))
                  .filter(visible)
                  .filter(input => {
                    const placeholder = input.getAttribute('placeholder') || '';
                    return placeholder.includes('请输入') || ['库存', '拼单价', '单买价', '规格编码'].some(text => placeholder.includes(text));
                  })
                  .sort((a, b) => a.getBoundingClientRect().left - b.getBoundingClientRect().left);
                if (inputs.length >= 4) {
                  inputs.slice(0, 4).forEach((input, index) => setInput(input, values[index]));
                  return { ok: true, inputCount: inputs.length };
                }
              }
              return { ok: false, inputCount: 0 };
            }
            """,
            {"specName": spec_name, "values": values},
        )
        if not filled.get("ok"):
            results.append({"field": "价格行", "status": "failed", "value": spec_name, "message": "找不到对应价格行或输入框"})
            continue

        for label, value in zip(labels, values):
            results.append({"field": f"{spec_name} {label}", "status": "filled", "value": value})
    return results


def listing_extra_product_code(package: dict[str, Any]) -> str:
    meta = package.get("meta") if isinstance(package.get("meta"), dict) else {}
    return str(package.get("productCode") or package.get("product_code") or package.get("price_multiplier") or meta.get("price_multiplier") or "").strip()


def listing_extra_batch_discount(package: dict[str, Any]) -> str:
    return str(package.get("batchDiscount") or package.get("batch_discount") or "9.9").strip()


async def fill_listing_extra_fields(page: Page, package: dict[str, Any]) -> list[dict[str, Any]]:
    fields = [
        {"field": "满件折扣", "area": "#batch_discount", "value": listing_extra_batch_discount(package)},
        {"field": "商品编码", "area": "#out_goods_sn", "value": listing_extra_product_code(package)},
    ]
    results: list[dict[str, Any]] = []

    await page.wait_for_timeout(300)
    filled = await page.evaluate(
        """
        ({ fields }) => {
          const visible = (el) => {
            const style = getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
          };
          const setInput = (input, value) => {
            input.focus();
            const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set;
            if (setter) setter.call(input, String(value ?? ''));
            else input.value = String(value ?? '');
            input.dispatchEvent(new Event('input', { bubbles: true }));
            input.dispatchEvent(new Event('change', { bubbles: true }));
            input.dispatchEvent(new Event('blur', { bubbles: true }));
            input.blur();
          };

          return fields.map((field) => {
            const value = String(field.value || '').trim();
            if (!value) return { field: field.field, ok: false, skipped: true, value };
            const area = document.querySelector(field.area);
            if (!area) return { field: field.field, ok: false, reason: 'area_not_found', value };
            const input = Array.from(area.querySelectorAll('input')).find(visible);
            if (!input) return { field: field.field, ok: false, reason: 'input_not_found', value };
            input.scrollIntoView({ block: 'center', inline: 'nearest' });
            setInput(input, value);
            return { field: field.field, ok: true, value };
          });
        }
        """,
        {"fields": fields},
    )
    await page.wait_for_timeout(500)

    for item in filled:
        if item.get("ok"):
            results.append({"field": item.get("field"), "status": "filled", "value": item.get("value")})
        elif item.get("skipped"):
            results.append({"field": item.get("field"), "status": "skipped", "message": "值为空"})
        else:
            results.append({"field": item.get("field"), "status": "failed", "value": item.get("value"), "message": item.get("reason")})
    return results


async def process_command(page: Page, last_command_id: str | None) -> str | None:
    if not COMMAND_PATH.exists():
        return last_command_id

    command = json.loads(COMMAND_PATH.read_text(encoding="utf-8"))
    command_id = str(command.get("id") or "")
    if not command_id or command_id == last_command_id:
        return last_command_id

    try:
        if command.get("action") == "open_category":
            await page.goto("https://mms.pinduoduo.com/goods/category", wait_until="domcontentloaded", timeout=60000)
            await page.bring_to_front()
            await page.evaluate("window.focus()")
            results = {"url": page.url, "title": await page.title()}
        elif command.get("action") == "read_material":
            results = await read_material_payload(page, str((command.get("payload") or {}).get("path") or "2026/8250"))
        elif command.get("action") == "fill_basic_info":
            results = await fill_basic_info(page, command.get("payload") or {})
        elif command.get("action") == "fill_specs":
            results = await fill_specs(page, command.get("payload") or {})
        else:
            raise ValueError(f"未知命令: {command.get('action')}")

        await clear_page_selection(page)
        write_command_status(
            {
                "id": command_id,
                "status": "done",
                "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "results": results,
            }
        )
    except Exception as exc:
        write_command_status(
            {
                "id": command_id,
                "status": "failed",
                "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "error": str(exc),
            }
        )
    return command_id


async def main() -> None:
    async with async_playwright() as playwright:
        PDD_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        context = await playwright.chromium.launch_persistent_context(
            str(PDD_PROFILE_DIR),
            headless=False,
            viewport={"width": 1400, "height": 900},
            args=["--start-maximized"],
        )
        page = context.pages[0] if context.pages else await context.new_page()
        if not page.url or page.url == "about:blank":
            await page.goto("https://mms.pinduoduo.com/goods/category", wait_until="domcontentloaded", timeout=60000)
        last_command_id = None
        while True:
            try:
                if page.is_closed():
                    if not context.pages:
                        break
                    page = context.pages[0]
                last_command_id = await process_command(page, last_command_id)
                await write_snapshot(page, "running")
            except Exception:
                pass
            await page.wait_for_timeout(3000)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
