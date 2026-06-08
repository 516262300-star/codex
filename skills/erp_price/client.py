from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml
from playwright.async_api import Browser, BrowserContext, Page, TimeoutError as PlaywrightTimeoutError


def load_dotenv(path: str | Path = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


class ERPPriceError(RuntimeError):
    """Base class for ERP price lookup failures."""


class ERPLoginRequired(ERPPriceError):
    """Raised when credentials or login selectors are missing."""


class ERPLoginFailed(ERPPriceError):
    """Raised when ERP account/password login fails."""


class ERPPriceNotFound(ERPPriceError):
    """Raised when a model/color cannot be found or the parsed price is invalid."""


@dataclass(frozen=True)
class ERPSelectors:
    username_input: str
    password_input: str
    login_submit: str
    search_input: str
    price_cell: str | None = None
    search_submit: str | None = None
    login_error: str | None = None


@dataclass(frozen=True)
class ERPAPIConfig:
    search_url: str | None = None
    goods2_url_template: str | None = None
    price_json_path: str = "info.price"
    premium_price_url: str | None = None
    premium_price_id: str | None = None


@dataclass(frozen=True)
class ERPConfig:
    login_url: str
    price_page_url: str
    storage_state: Path
    username: str | None
    password: str | None
    selectors: ERPSelectors
    price_regex: str = r"([0-9]+(?:\.[0-9]+)?)"
    wait_timeout_ms: int = 8000
    lookup_type: str = "page"
    login_check_url: str | None = None
    api: ERPAPIConfig | None = None


@dataclass(frozen=True)
class ERPPriceQuote:
    product_name: str
    color_name: str
    price: Decimal


def _expand_secret(value: Any) -> str | None:
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    match = re.fullmatch(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", text)
    if match:
        return os.getenv(match.group(1))
    return os.path.expandvars(text)


def _required(mapping: dict[str, Any], key: str) -> str:
    value = mapping.get(key)
    if value is None or str(value).strip() == "":
        raise ValueError(f"Missing required ERP config field: {key}")
    return str(value)


def load_config(path: str | Path = "config.yaml") -> ERPConfig:
    config_path = Path(path)
    load_dotenv(config_path.parent / ".env")

    with config_path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    erp = raw.get("erp") or {}
    selectors = erp.get("selectors") or {}
    api = erp.get("api") or {}
    lookup_type = str(erp.get("lookup_type") or "page")

    return ERPConfig(
        login_url=_required(erp, "login_url"),
        price_page_url=_required(erp, "price_page_url"),
        storage_state=Path(_required(erp, "storage_state")),
        username=_expand_secret(erp.get("username")),
        password=_expand_secret(erp.get("password")),
        selectors=ERPSelectors(
            username_input=_required(selectors, "username_input"),
            password_input=_required(selectors, "password_input"),
            login_submit=_required(selectors, "login_submit"),
            search_input=_required(selectors, "search_input"),
            search_submit=str(selectors["search_submit"]).strip() if selectors.get("search_submit") else None,
            price_cell=str(selectors["price_cell"]).strip() if selectors.get("price_cell") else None,
            login_error=str(selectors["login_error"]).strip() if selectors.get("login_error") else None,
        ),
        price_regex=str(erp.get("price_regex") or r"([0-9]+(?:\.[0-9]+)?)"),
        wait_timeout_ms=int(erp.get("wait_timeout_ms") or 8000),
        lookup_type=lookup_type,
        login_check_url=str(erp["login_check_url"]).strip() if erp.get("login_check_url") else None,
        api=ERPAPIConfig(
            search_url=str(api["search_url"]).strip() if api.get("search_url") else None,
            goods2_url_template=str(api["goods2_url_template"]).strip() if api.get("goods2_url_template") else None,
            price_json_path=str(api.get("price_json_path") or "info.price"),
            premium_price_url=str(api["premium_price_url"]).strip() if api.get("premium_price_url") else None,
            premium_price_id=str(api["premium_price_id"]).strip() if api.get("premium_price_id") else None,
        )
        if lookup_type in {"ldswj_api", "ldswj_premium"}
        else None,
    )


class ERPPriceClient:
    def __init__(self, browser: Browser, config: ERPConfig):
        self.browser = browser
        self.config = config
        self.context: BrowserContext | None = None
        self.page: Page | None = None

    async def __aenter__(self) -> "ERPPriceClient":
        await self.start()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def start(self) -> None:
        context_kwargs: dict[str, Any] = {}
        if self.config.storage_state.exists():
            context_kwargs["storage_state"] = str(self.config.storage_state)

        self.context = await self.browser.new_context(**context_kwargs)
        self.page = await self.context.new_page()

    async def close(self) -> None:
        if self.context is not None:
            await self.context.close()
        self.context = None
        self.page = None

    async def get_price(self, sku_name: str, color: str | None = None) -> Decimal:
        quote = await self.get_price_quote(sku_name, color=color)
        return quote.price

    async def get_price_quote(self, sku_name: str, color: str | None = None) -> ERPPriceQuote:
        if self.page is None:
            await self.start()

        assert self.page is not None
        page = self.page

        for attempt in range(3):
            try:
                await self._ensure_logged_in(page)
                if self.config.lookup_type == "ldswj_premium":
                    return await self._get_premium_quote(page, sku_name, color=color)
                if self.config.lookup_type == "ldswj_api":
                    price = await self._get_price_from_ldswj_api(page, sku_name)
                    return ERPPriceQuote(product_name=sku_name, color_name=color or "", price=price)
                await self._search_model(page, sku_name)
                price = await self._read_price(page, sku_name)
                return ERPPriceQuote(product_name=sku_name, color_name=color or "", price=price)
            except (PlaywrightTimeoutError, ERPPriceNotFound):
                if attempt == 2:
                    raise
                await page.reload(wait_until="domcontentloaded")

        raise ERPPriceNotFound(f"ERP price not found: {sku_name}")

    async def _ensure_logged_in(self, page: Page) -> None:
        if self.config.login_check_url:
            await page.goto(self.config.login_check_url, wait_until="domcontentloaded")
            if not await self._is_login_page(page):
                await self._save_storage_state()
                return

        await page.goto(self.config.price_page_url, wait_until="domcontentloaded")
        if await self._is_price_page_ready(page):
            await self._save_storage_state()
            return

        if not await self._is_login_page(page):
            await page.goto(self.config.login_url, wait_until="domcontentloaded")

        await self._login_with_password(page)
        await self._save_storage_state()

    async def _is_price_page_ready(self, page: Page) -> bool:
        try:
            await page.locator(self.config.selectors.search_input).wait_for(
                state="visible",
                timeout=min(self.config.wait_timeout_ms, 3000),
            )
            return True
        except PlaywrightTimeoutError:
            return False

    async def _is_login_page(self, page: Page) -> bool:
        if page.url.startswith(self.config.login_url):
            return True
        try:
            await page.locator(self.config.selectors.username_input).wait_for(state="visible", timeout=1500)
            await page.locator(self.config.selectors.password_input).wait_for(state="visible", timeout=1500)
            return True
        except PlaywrightTimeoutError:
            return False

    async def _login_with_password(self, page: Page) -> None:
        if not self.config.username or not self.config.password:
            raise ERPLoginRequired("ERP credentials are missing in .env/config.yaml")

        selectors = self.config.selectors
        await page.goto(self.config.login_url, wait_until="domcontentloaded")
        await page.locator(selectors.username_input).fill(self.config.username)
        await page.locator(selectors.password_input).fill(self.config.password)
        await page.locator(selectors.login_submit).click()

        try:
            await page.wait_for_load_state("domcontentloaded", timeout=self.config.wait_timeout_ms)
        except PlaywrightTimeoutError:
            pass

        try:
            await page.wait_for_url(
                lambda url: not str(url).startswith(self.config.login_url),
                timeout=min(self.config.wait_timeout_ms, 3000),
            )
            return
        except PlaywrightTimeoutError:
            if selectors.login_error:
                error_text = (await page.locator(selectors.login_error).first().inner_text(timeout=1000)).strip()
                if error_text:
                    raise ERPLoginFailed(f"ERP login failed: {error_text}") from None
            if await self._is_login_page(page):
                raise ERPLoginFailed("ERP login failed; check account, password, and selectors") from None

    async def _search_model(self, page: Page, model: str) -> None:
        selectors = self.config.selectors
        search = page.locator(selectors.search_input)
        await search.wait_for(state="visible", timeout=self.config.wait_timeout_ms)
        await search.fill(model)

        if selectors.search_submit:
            await page.locator(selectors.search_submit).click()
        else:
            await search.press("Enter")

    async def _read_price(self, page: Page, model: str) -> Decimal:
        if not self.config.selectors.price_cell:
            raise ERPPriceNotFound("Missing ERP price selector: erp.selectors.price_cell")

        cell = page.locator(self.config.selectors.price_cell).first()
        await cell.wait_for(state="visible", timeout=self.config.wait_timeout_ms)
        return self._parse_price(await cell.inner_text(timeout=self.config.wait_timeout_ms), model)

    async def _get_premium_quote(self, page: Page, sku_name: str, color: str | None = None) -> ERPPriceQuote:
        if not self.config.api or not self.config.api.premium_price_url or not self.config.api.premium_price_id:
            raise ERPPriceNotFound("Missing premium price API config")

        sku = self._parse_sku_name(sku_name, color=color)
        response = await page.request.post(
            self.config.api.premium_price_url,
            form={
                "page": "0",
                "priceid": self.config.api.premium_price_id,
                "word": sku.search_word,
                "label": "",
                "labeltype": "",
                "get_profit_rate": "0",
            },
            timeout=self.config.wait_timeout_ms,
        )
        data = self._loads_json(await response.text())
        products = data.get("lists") or []
        if not products:
            raise ERPPriceNotFound(f"Premium price book returned no rows for {sku.search_word}")

        product = self._match_premium_product(products, sku)
        color_row = self._match_premium_color(product, sku)
        return ERPPriceQuote(
            product_name=str(product.get("name") or sku_name).strip(),
            color_name=str(color_row.get("color") or color or "").strip(),
            price=self._parse_price(color_row.get("price"), sku_name),
        )

    def _match_premium_product(self, products: list[dict[str, Any]], sku: "ParsedSKU") -> dict[str, Any]:
        for product in products:
            if self._model_matches(str(product.get("name") or ""), sku.model_key):
                return product

        suffix_matches = [
            product
            for product in products
            if self._model_matches_with_safe_suffix(str(product.get("name") or ""), sku.model_key)
        ]
        if len(suffix_matches) == 1:
            return suffix_matches[0]

        base_matches = [
            product
            for product in products
            if self._compact_model(str(product.get("name") or "")).startswith(self._compact_model(sku.search_word))
        ]
        if len(base_matches) == 1:
            return base_matches[0]

        names = ", ".join(str(item.get("name") or "") for item in products[:10])
        raise ERPPriceNotFound(f"Premium price model {sku.model_key} not found. Candidates: {names}")

    def _match_premium_color(self, product: dict[str, Any], sku: "ParsedSKU") -> dict[str, Any]:
        colors = product.get("colors") or []
        if not colors:
            raise ERPPriceNotFound(f"Premium price model {product.get('name')} has no color rows")

        if not sku.color_key:
            if len(colors) == 1:
                return colors[0]
            color_names = ", ".join(str(row.get("color") or "") for row in colors)
            raise ERPPriceNotFound(
                f"Color is required for {product.get('name')}; candidates: {color_names}"
            )

        for row in colors:
            if self._color_matches(str(row.get("color") or ""), sku.color_key):
                return row

        color_names = ", ".join(str(row.get("color") or "") for row in colors)
        raise ERPPriceNotFound(
            f"Premium price color {sku.color_key} not found for {product.get('name')}; candidates: {color_names}"
        )

    async def _get_price_from_ldswj_api(self, page: Page, model: str) -> Decimal:
        if not self.config.api or not self.config.api.search_url or not self.config.api.goods2_url_template:
            raise ERPPriceNotFound("Missing LDSWJ API price config")

        search_response = await page.request.post(
            self.config.api.search_url,
            form={
                "page": "0",
                "word": model,
                "kj": "{}",
                "area": "{}",
                "color": "",
                "style": "",
                "price": "",
                "csname": "",
            },
            timeout=self.config.wait_timeout_ms,
        )
        search_data = self._loads_json(await search_response.text())
        products = search_data.get("lists") or []
        if not products:
            raise ERPPriceNotFound(f"ERP price book returned no rows for {model}")

        for product in products[:5]:
            product_id = product.get("id")
            if not product_id:
                continue

            goods_url = self.config.api.goods2_url_template.format(id=product_id)
            goods_response = await page.request.get(goods_url, timeout=self.config.wait_timeout_ms)
            goods_data = self._loads_json(await goods_response.text())
            if not self._goods_matches_model(goods_data, model):
                continue

            value = self._get_json_path(goods_data, self.config.api.price_json_path)
            return self._parse_price(value, model)

        return self._parse_price(products[0].get("price"), model)

    def _goods_matches_model(self, goods_data: dict[str, Any], model: str) -> bool:
        info = goods_data.get("info") or {}
        haystack = " ".join(str(info.get(key) or "") for key in ("name", "autoproduct", "skulist", "outername"))
        return self._compact(model) in self._compact(haystack)

    def _get_json_path(self, data: dict[str, Any], path: str) -> Any:
        value: Any = data
        for part in path.split("."):
            if not isinstance(value, dict) or part not in value:
                raise ERPPriceNotFound(f"ERP price API missing field: {path}")
            value = value[part]
        return value

    def _parse_price(self, value: Any, model: str) -> Decimal:
        text = str(value or "").strip()
        match = re.search(self.config.price_regex, text)
        if not match:
            raise ERPPriceNotFound(f"ERP price for {model} cannot be parsed: {text!r}")

        try:
            price = Decimal(match.group(1))
        except InvalidOperation as exc:
            raise ERPPriceNotFound(f"ERP price for {model} is not numeric: {match.group(1)!r}") from exc

        if price <= 0:
            raise ERPPriceNotFound(f"ERP price for {model} is invalid: {price}")
        return price

    def _loads_json(self, text: str) -> dict[str, Any]:
        return json.loads(text.lstrip("\ufeff"))

    def _parse_sku_name(self, sku_name: str, color: str | None = None) -> "ParsedSKU":
        source = Path(str(sku_name)).stem
        text = source.strip()

        model_match = re.search(
            r"\d+[A-Za-z]*(?:[-_](?:[A-Za-z0-9]+(?:直径)?|直径|单孔|吊坠))*",
            text,
        )
        if not model_match:
            raise ERPPriceNotFound(f"Cannot parse model from SKU name: {sku_name}")

        model_text = model_match.group(0).replace("_", "-")
        color_text = color if color is not None else text[model_match.end() :]
        color_text = color_text.lstrip("-_ #/").strip()

        search_match = re.match(r"\d+[A-Za-z]*", model_text)
        search_word = search_match.group(0) if search_match else model_text

        return ParsedSKU(
            original=text,
            search_word=search_word,
            model_key=self._compact_model(model_text),
            color_key=self._compact_color(color_text),
        )

    def _model_matches(self, candidate: str, model_key: str) -> bool:
        return self._compact_model(candidate) == model_key

    def _model_matches_with_safe_suffix(self, candidate: str, model_key: str) -> bool:
        candidate_key = self._compact_model(candidate)
        if not candidate_key.startswith(model_key):
            return False
        suffix = candidate_key[len(model_key) :]
        return suffix in {"直径", "mm", "毫米"}

    def _color_matches(self, candidate: str, color_key: str) -> bool:
        compact_candidate = self._compact_color(candidate)
        return color_key in compact_candidate or compact_candidate in color_key

    def _compact_model(self, value: str) -> str:
        value = Path(str(value)).stem
        value = value.replace("_", "-")
        value = re.sub(r"\s+", "", value)
        value = value.strip("-#/")
        return value.lower()

    def _compact_color(self, value: str) -> str:
        return self._compact(value).replace("-", "")

    def _compact(self, value: str) -> str:
        value = Path(str(value)).stem
        value = value.replace("_", "")
        return re.sub(r"[\s#/_\\\-]+", "", value).lower()

    async def _save_storage_state(self) -> None:
        if self.context is None:
            return
        self.config.storage_state.parent.mkdir(parents=True, exist_ok=True)
        await self.context.storage_state(path=str(self.config.storage_state))


@dataclass(frozen=True)
class ParsedSKU:
    original: str
    search_word: str
    model_key: str
    color_key: str
