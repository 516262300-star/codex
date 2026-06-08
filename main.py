from __future__ import annotations

import argparse
import asyncio
import re
from dataclasses import dataclass, replace
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import yaml
from playwright.async_api import async_playwright

from skills.erp_price import ERPPriceClient, load_config


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


@dataclass(frozen=True)
class ProductMeta:
    erp_model: str
    category_path: str
    price_multiplier: Decimal
    material: str
    color: str
    stock_per_sku: int


@dataclass(frozen=True)
class SKUPreview:
    sku_name: str
    price_book_name: str
    price_book_color: str
    image_path: Path
    base_price: Decimal
    group_price: Decimal
    single_price: Decimal
    stock: int


def natural_image_key(path: Path) -> tuple[int, str]:
    match = re.search(r"\d+", path.stem)
    if not match:
        raise ValueError(f"图片文件名缺少数字顺序前缀或编号: {path.name}")
    return (int(match.group(0)), path.name.lower())


def list_images(folder: Path) -> list[Path]:
    if not folder.exists():
        raise FileNotFoundError(f"缺少文件夹: {folder}")

    images = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS]
    if not images:
        raise FileNotFoundError(f"文件夹里没有图片: {folder}")

    return sorted(images, key=natural_image_key)


def list_sku_images(folder: Path) -> list[Path]:
    if not folder.exists():
        raise FileNotFoundError(f"缺少文件夹: {folder}")

    images = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS]
    if not images:
        raise FileNotFoundError(f"尺寸图文件夹里没有图片: {folder}")

    return sorted(images, key=lambda p: p.name.lower())


def load_product_meta(product_folder: Path) -> ProductMeta:
    meta_path = product_folder / "meta.yaml"
    if not meta_path.exists():
        raise FileNotFoundError(f"缺少 meta.yaml: {meta_path}")

    with meta_path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    return ProductMeta(
        erp_model=str(raw["erp_model"]),
        category_path=str(raw["category_path"]),
        price_multiplier=Decimal(str(raw["price_multiplier"])),
        material=str(raw["material"]),
        color=str(raw["color"]),
        stock_per_sku=int(raw["stock_per_sku"]),
    )


def money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


async def build_dry_run(
    product_folder: Path,
    price_multiplier: Decimal | None = None,
) -> tuple[ProductMeta, list[Path], list[Path], list[SKUPreview]]:
    meta = load_product_meta(product_folder)
    if price_multiplier is not None:
        meta = replace(meta, price_multiplier=price_multiplier)
    main_images = list_images(product_folder / "主图")
    detail_images = list_images(product_folder / "详情页")
    sku_images = list_sku_images(product_folder / "尺寸图")

    config = load_config("config.yaml")
    skus: list[SKUPreview] = []

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            async with ERPPriceClient(browser, config) as erp:
                for image in sku_images:
                    sku_name = image.stem
                    quote = await erp.get_price_quote(sku_name)
                    group_price = money(quote.price * meta.price_multiplier)
                    single_price = money(group_price + Decimal("1"))
                    skus.append(
                        SKUPreview(
                            sku_name=sku_name,
                            price_book_name=quote.product_name,
                            price_book_color=quote.color_name,
                            image_path=image,
                            base_price=quote.price,
                            group_price=group_price,
                            single_price=single_price,
                            stock=meta.stock_per_sku,
                        )
                    )
        finally:
            await browser.close()

    return meta, main_images, detail_images, skus


def print_dry_run(product_folder: Path, meta: ProductMeta, main_images: list[Path], detail_images: list[Path], skus: list[SKUPreview]) -> None:
    print(f"商品文件夹: {product_folder}")
    print(f"ERP 基础型号: {meta.erp_model}")
    print(f"类目: {meta.category_path}")
    print(f"材质: {meta.material}")
    print(f"默认颜色: {meta.color}")
    print(f"价格倍数: {meta.price_multiplier}")
    print()

    print("主图顺序:")
    for index, image in enumerate(main_images, start=1):
        print(f"  {index}. {image.name}")
    print()

    print("详情页顺序:")
    for index, image in enumerate(detail_images, start=1):
        print(f"  {index}. {image.name}")
    print()

    print("SKU / 优质价 / 平台售价:")
    for sku in skus:
        print(
            f"  {sku.sku_name} | 优质价 {sku.base_price} | "
            f"拼单价 {sku.group_price} | 单买价 {sku.single_price} | 库存 {sku.stock} | "
            f"规格编码 {sku.price_book_name}#{sku.price_book_color} | 图 {sku.image_path.name}"
        )


async def async_main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--folder", required=True, help="商品文件夹路径")
    parser.add_argument("--dry-run", action="store_true", help="只核对数据，不上传、不保存草稿")
    parser.add_argument("--price-multiplier", default=None, help="临时价格倍数，留空则使用 meta.yaml")
    args = parser.parse_args()

    if not args.dry_run:
        raise SystemExit("当前只实现了 --dry-run；正式上传会在核对无误后再接入。")

    product_folder = Path(args.folder).expanduser().resolve()
    price_multiplier = Decimal(str(args.price_multiplier)) if args.price_multiplier else None
    meta, main_images, detail_images, skus = await build_dry_run(product_folder, price_multiplier=price_multiplier)
    print_dry_run(product_folder, meta, main_images, detail_images, skus)


if __name__ == "__main__":
    asyncio.run(async_main())
