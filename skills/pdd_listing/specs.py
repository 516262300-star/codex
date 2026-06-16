from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any


SEPARATOR_RE = re.compile(r"^[\s\-_—/]+|[\s\-_—/]+$")
SPEC_NAME_DISPLAY_ALIASES = {
    "亮镍": "钛银",
}


@dataclass(frozen=True)
class SKUSpec:
    sku_name: str
    spec_type: str
    spec_name: str
    spec_code: str
    base_price: Decimal
    group_price: Decimal
    single_price: Decimal
    stock: int
    local_image: str
    material_image_filename: str
    material_image_url: str
    material_image_width: int | None
    material_image_height: int | None


def normalize_spec_name(value: str) -> str:
    return SEPARATOR_RE.sub("", value.strip())


def derive_spec_name(sku_name: str, erp_model: str) -> str:
    sku = sku_name.strip()
    model = erp_model.strip()
    spec_name = ""
    if model and sku.lower().startswith(model.lower()):
        suffix = normalize_spec_name(sku[len(model) :])
        if suffix:
            spec_name = suffix
    if not spec_name:
        spec_name = normalize_spec_name(sku)
    for source, display in SPEC_NAME_DISPLAY_ALIASES.items():
        spec_name = spec_name.replace(source, display)
    return spec_name


def build_sku_specs(
    sku_rows: list[dict[str, Any]],
    erp_model: str,
    spec_type: str = "型号",
) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    seen: set[str] = set()

    for index, row in enumerate(sku_rows, start=1):
        sku_name = str(row["sku_name"])
        spec_name = derive_spec_name(sku_name, erp_model)
        price_book_name = str(row.get("price_book_name") or erp_model or sku_name).strip()
        price_book_color = str(row.get("price_book_color") or spec_name).strip()
        spec_code = f"{price_book_name}#{price_book_color}"
        if spec_name in seen:
            raise ValueError(f"规格名称重复: {spec_name}; 请检查尺寸图文件名")
        seen.add(spec_name)

        image = row.get("material_image") or {}
        group_price = str(row.get("group_price") or row.get("final_price"))
        single_price = str(row.get("single_price") or Decimal(group_price) + Decimal("1"))
        specs.append(
            {
                "index": index,
                "sku_name": sku_name,
                "spec_type": spec_type,
                "spec_name": spec_name,
                "spec_code": spec_code,
                "price_book_name": price_book_name,
                "price_book_color": price_book_color,
                "base_price": str(row["base_price"]),
                "group_price": group_price,
                "single_price": single_price,
                "final_price": group_price,
                "stock": int(row["stock"]),
                "local_image": str(row.get("image") or ""),
                "material_image_filename": str(image.get("filename") or ""),
                "material_image_url": str(image.get("url") or ""),
                "material_image_width": image.get("width"),
                "material_image_height": image.get("height"),
            }
        )

    return specs
