from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml


PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)(?:\|([^{}]*))?\}")


def _meta_context(meta: Any) -> dict[str, Any]:
    if isinstance(meta, dict):
        return dict(meta)

    return {
        key: getattr(meta, key)
        for key in ("erp_model", "category_path", "price_multiplier", "material", "color", "stock_per_sku")
        if hasattr(meta, key)
    }


def _resolve_string(value: str, context: dict[str, Any]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        fallback = match.group(2)
        raw = context.get(key)
        if raw is None or raw == "":
            return fallback or ""
        return str(raw)

    return PLACEHOLDER_RE.sub(replace, value)


def _resolve_value(value: Any, context: dict[str, Any]) -> Any:
    if isinstance(value, str):
        return _resolve_string(value, context)
    if isinstance(value, list):
        return [_resolve_value(item, context) for item in value]
    if isinstance(value, dict):
        return {key: _resolve_value(item, context) for key, item in value.items()}
    return value


def resolve_listing_template(meta: Any, template_path: str | Path) -> dict[str, Any]:
    template_file = Path(template_path)
    with template_file.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    categories = raw.get("categories") or {}
    context = _meta_context(meta)
    requested_category = str(context.get("category_path") or "")
    default_category = str(raw.get("default_category") or "")

    if requested_category in categories:
        matched_category = requested_category
        matched_by = "meta.category_path"
    elif default_category in categories:
        matched_category = default_category
        matched_by = "default_category"
    elif categories:
        matched_category = next(iter(categories))
        matched_by = "first_template"
    else:
        raise ValueError(f"类目属性模板为空: {template_file}")

    resolved = _resolve_value(categories[matched_category], context)
    return {
        "requested_category_path": requested_category,
        "matched_category_path": matched_category,
        "matched_by": matched_by,
        "template": resolved,
    }
