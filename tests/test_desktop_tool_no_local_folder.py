from decimal import Decimal

import desktop_tool


def test_plugin_product_json_works_without_local_meta(tmp_path, monkeypatch):
    package = {
        "product_folder": str(tmp_path / "missing-product-folder"),
        "material_path": "2026/8105-8255",
        "erp_model": "8105-8255",
        "category_path": desktop_tool.DEFAULT_CATEGORY_PATH,
        "price_multiplier": "1.8",
        "meta": {
            "erp_model": "8105-8255",
            "category_path": desktop_tool.DEFAULT_CATEGORY_PATH,
            "price_multiplier": "1.8",
            "material": "黄铜",
            "color": "",
            "stock_per_sku": 500,
        },
        "main_images": [{"index": 1, "url": "https://example.test/main.jpg"}],
        "detail_images": [{"index": 1, "url": "https://example.test/detail.jpg"}],
        "sku_specs": [
            {
                "spec_type": "型号",
                "spec_name": "古铜色",
                "stock": 500,
                "group_price": "18.00",
                "single_price": "19.00",
                "spec_code": "8105#古铜色",
                "material_image_url": "https://example.test/sku.jpg",
            }
        ],
    }

    monkeypatch.setattr(desktop_tool, "cached_recommended_title", lambda _folder: "")

    data = desktop_tool.plugin_product_json(package)

    assert data["carouselImages"] == {"image1": "https://example.test/main.jpg"}
    assert data["detailImages"] == ["https://example.test/detail.jpg"]
    assert data["skus"][0]["productCode"] == "8105#古铜色"
    assert data["marketPrice"] == Decimal("19.00")
