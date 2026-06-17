from decimal import Decimal

import desktop_tool
from skills.erp_price.client import ERPPriceClient


def test_parse_material_sku_lookup_extracts_size_from_descriptive_filename():
    lookup_name, color = desktop_tool.parse_material_sku_lookup("8105胡桃木-古铜色-96尺寸图")

    assert lookup_name == "8105-96"
    assert color == "古铜色"


def test_parse_material_sku_lookup_keeps_single_hole_suffix():
    lookup_name, color = desktop_tool.parse_material_sku_lookup("2715云栖-铬色-单孔")

    assert lookup_name == "2715-单孔"
    assert color == "铬"


def test_parse_material_sku_lookup_ignores_parenthesized_single_hole_size():
    lookup_name, color = desktop_tool.parse_material_sku_lookup("2075-哑镍拉丝-单孔（33）")

    assert lookup_name == "2075-单孔"
    assert color == "哑镍拉丝"


def test_parse_material_sku_lookup_maps_titanium_silver_to_bright_nickel():
    lookup_name, color = desktop_tool.parse_material_sku_lookup("2715云栖-钛银-单孔")

    assert lookup_name == "2715-单孔"
    assert color == "亮镍"


def test_parse_material_sku_lookup_maps_bright_gold_to_rose_gold():
    lookup_name, color = desktop_tool.parse_material_sku_lookup("2715云栖-亮金-单孔")

    assert lookup_name == "2715-单孔"
    assert color == "玫瑰金"


def test_parse_material_sku_lookup_maps_pvd_gold_to_chrome_pvd():
    lookup_name, color = desktop_tool.parse_material_sku_lookup("8118-PVD金-单孔")

    assert lookup_name == "8118-单孔"
    assert color == "铬PVD"


def test_parse_material_sku_lookup_uses_install_suffix_when_base_model_missing():
    lookup_name, color = desktop_tool.parse_material_sku_lookup("8256-金-单孔")

    assert lookup_name == "8256-单孔"
    assert color == "金"


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


def test_material_video_detection_falls_back_to_filename_suffix():
    assert desktop_tool.is_material_video({"filename": "主图视频.mp4", "extension": ""})
    assert desktop_tool.is_material_video({"filename": "讲解视频.MOV"})


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
        "main_videos": [{"index": 1, "url": "https://example.test/main.mp4"}],
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
    assert data["productVideo"] == "https://example.test/main.mp4"
    assert data["explainVideo"] == "https://example.test/main.mp4"
    assert data["skus"][0]["productCode"] == "8105#古铜色"
    assert data["marketPrice"] == Decimal("19.00")
    assert data["batchDiscount"] == "9.9"
    assert data["productCode"] == "1.8"


def test_plugin_product_json_falls_back_to_main_image_generated_videos(tmp_path, monkeypatch):
    package = {
        "product_folder": str(tmp_path / "missing-product-folder"),
        "category_path": desktop_tool.DEFAULT_CATEGORY_PATH,
        "price_multiplier": "1.8",
        "meta": {
            "erp_model": "8105",
            "category_path": desktop_tool.DEFAULT_CATEGORY_PATH,
            "price_multiplier": "1.8",
            "material": "黄铜",
            "stock_per_sku": 500,
        },
        "main_images": [{"index": 1, "url": "https://example.test/main.jpg"}],
        "main_videos": [],
        "detail_images": [],
        "sku_specs": [],
    }

    monkeypatch.setattr(desktop_tool, "cached_recommended_title", lambda _folder: "")

    data = desktop_tool.plugin_product_json(package)

    assert data["productVideo"] == {
        "url": "https://example.test/main.jpg",
        "name": "商品视频.webm",
        "makeVideoFromImage": True,
    }
    assert data["explainVideo"] == {
        "url": "https://example.test/main.jpg",
        "name": "商品讲解视频.webm",
        "makeVideoFromImage": True,
    }


def test_append_saved_draft_history_appends_and_deduplicates(tmp_path, monkeypatch):
    history_path = tmp_path / "saved_draft_history.json"
    monkeypatch.setattr(desktop_tool, "DRAFT_HISTORY_PATH", history_path)
    status = {"id": 123}
    progress = {
        "stage": "draft_saved",
        "updated_at": "2026-06-17 15:30:00",
        "url": "https://mms.pinduoduo.com/goods/goods_add/index?goods_id=abc",
        "detail": {
            "title": "测试商品",
            "mall_name": "测试店铺",
            "mall_id": "mall-1",
            "material_path": "2026/2705",
            "sku_count": 2,
        },
    }

    desktop_tool.append_saved_draft_history(status, progress)
    desktop_tool.append_saved_draft_history(status, progress)

    history = desktop_tool.read_saved_draft_history()
    assert history["total"] == 1
    assert history["items"][0]["title"] == "测试商品"
    assert history["items"][0]["mall_name"] == "测试店铺"
    assert history["items"][0]["task_id"] == "123"
    assert history["items"][0]["goods_id"] == "abc"


def test_enrich_latest_saved_draft_backfills_success_url(tmp_path, monkeypatch):
    history_path = tmp_path / "saved_draft_history.json"
    monkeypatch.setattr(desktop_tool, "DRAFT_HISTORY_PATH", history_path)
    desktop_tool.write_saved_draft_history({
        "version": 1,
        "items": [
            {
                "saved_at": "2026-06-17 15:30:00",
                "task_id": "123",
                "title": "测试商品",
                "url": "https://mms.pinduoduo.com/goods/goods_add/index",
                "goods_id": "",
            }
        ],
    })

    desktop_tool.enrich_latest_saved_draft({
        "stage": "page_changed",
        "url": "https://mms.pinduoduo.com/goods/goods_add/success?goods_id=987",
    })

    history = desktop_tool.read_saved_draft_history()
    assert history["total"] == 1
    assert history["items"][0]["goods_id"] == "987"
    assert history["items"][0]["url"].endswith("goods_id=987")
