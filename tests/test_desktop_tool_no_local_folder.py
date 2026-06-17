from decimal import Decimal

import desktop_tool
from skills.erp_price.client import ERPPriceClient


def test_parse_material_sku_lookup_extracts_size_from_descriptive_filename():
    lookup_name, color = desktop_tool.parse_material_sku_lookup("8105胡桃木-古铜色-96尺寸图")

    assert lookup_name == "8105-96"
    assert color == "古铜色"


def test_parse_material_sku_lookup_ignores_single_hole_suffix():
    lookup_name, color = desktop_tool.parse_material_sku_lookup("2715云栖-铬色-单孔")

    assert lookup_name == "2715"
    assert color == "铬"


def test_parse_material_sku_lookup_ignores_parenthesized_single_hole_size():
    lookup_name, color = desktop_tool.parse_material_sku_lookup("2075-哑镍拉丝-单孔（33）")

    assert lookup_name == "2075"
    assert color == "哑镍拉丝"


def test_parse_material_sku_lookup_maps_titanium_silver_to_bright_nickel():
    lookup_name, color = desktop_tool.parse_material_sku_lookup("2715云栖-钛银-单孔")

    assert lookup_name == "2715"
    assert color == "亮镍"


def test_parse_material_sku_lookup_maps_bright_gold_to_rose_gold():
    lookup_name, color = desktop_tool.parse_material_sku_lookup("2715云栖-亮金-单孔")

    assert lookup_name == "2715"
    assert color == "玫瑰金"


def test_parse_material_sku_lookup_maps_pvd_gold_to_chrome_pvd():
    lookup_name, color = desktop_tool.parse_material_sku_lookup("8118-PVD金-单孔")

    assert lookup_name == "8118"
    assert color == "铬PVD"


def test_material_sku_sort_key_orders_sizes_numerically():
    images = [
        {"filename": "6787-亮镍-128尺寸图.jpg"},
        {"filename": "6787-亮镍-192尺寸图.jpg"},
        {"filename": "6787-亮镍-96尺寸图.jpg"},
    ]

    assert [item["filename"] for item in sorted(images, key=desktop_tool.material_sku_sort_key)] == [
        "6787-亮镍-96尺寸图.jpg",
        "6787-亮镍-128尺寸图.jpg",
        "6787-亮镍-192尺寸图.jpg",
    ]


def test_price_book_color_matches_short_chrome_name():
    client = ERPPriceClient.__new__(ERPPriceClient)

    assert client._color_matches("铬", "铬色")


def test_money_with_cent_ending_sets_second_decimal_digit():
    assert desktop_tool.money_with_cent_ending(Decimal("23.044"), "8") == Decimal("23.08")
    assert desktop_tool.money_with_cent_ending(Decimal("23.044"), "9") == Decimal("23.09")


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
    assert data["batchDiscount"] == "9.9"
    assert data["productCode"] == "1.8"
