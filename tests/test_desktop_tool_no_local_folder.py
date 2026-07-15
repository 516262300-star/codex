import json
from decimal import Decimal

import desktop_tool
from skills.erp_price.client import ERPPriceClient


def test_parse_material_sku_lookup_extracts_size_from_descriptive_filename():
    lookup_name, color = desktop_tool.parse_material_sku_lookup("8105胡桃木-古铜色-96尺寸图")

    assert lookup_name == "8105-96"
    assert color == "古铜色"


def test_parse_material_sku_lookup_extracts_size_before_inline_color():
    cases = [
        ("8264-96铜本色.jpeg", "8264-96", "铜本色"),
        ("8264-128古铜色.jpeg", "8264-128", "古铜色"),
        ("8264-160铬.jpeg", "8264-160", "铬"),
    ]

    for filename, expected_model, expected_color in cases:
        lookup_name, color = desktop_tool.parse_material_sku_lookup(filename)
        assert lookup_name == expected_model
        assert color == expected_color


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


def test_hole_distance_is_derived_from_size_skus_instead_of_template_default():
    rows = [
        {"price_book_name": "8264-96", "sku_name": "8264-96铜本色"},
        {"price_book_name": "8264-128", "sku_name": "8264-128古铜色"},
    ]

    listing = {"attributes": {"孔距": "单孔", "材质": "锌合金"}}

    assert desktop_tool.apply_sku_derived_attributes(listing, rows) == "96mm/128mm"
    assert listing["attributes"]["孔距"] == "96mm/128mm"


def test_hole_distance_keeps_single_hole_only_when_size_skus_contain_it():
    assert desktop_tool.infer_hole_distance_from_skus([
        {"sku_name": "2718-亮金-单孔", "price_book_name": "2718-单孔"},
    ]) == "单孔"


def test_hole_distance_can_include_single_and_multiple_numeric_distances():
    assert desktop_tool.infer_hole_distance_from_skus([
        {"sku_name": "8256-金-单孔", "price_book_name": "8256-单孔"},
        {"sku_name": "8256-金-96尺寸图", "price_book_name": "8256-96"},
    ]) == "单孔/96mm"


def test_hole_distance_is_omitted_when_skus_do_not_identify_it():
    listing = {"attributes": {"孔距": "单孔"}}

    assert desktop_tool.apply_sku_derived_attributes(listing, [{"sku_name": "8105-古铜色"}]) == ""
    assert "孔距" not in listing["attributes"]


def test_listing_videos_use_square_video_for_product_and_vertical_for_explanation():
    vertical = {"filename": "9-16.mp4", "url": "vertical"}
    square = {"filename": "800视频.mp4", "url": "square"}

    product, explain, ordered = desktop_tool.choose_listing_videos([vertical, square])

    assert product == square
    assert explain == vertical
    assert ordered == [square, vertical]


def test_listing_reference_price_is_one_yuan_above_highest_single_price():
    assert desktop_tool.listing_reference_price([
        {"single_price": "9.79"},
        {"single_price": "10.59"},
        {"single_price": "10.09"},
    ]) == Decimal("11.59")


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
    assert data["mainVideos"] == [
        {
            "url": "https://example.test/main.mp4",
            "name": "主图视频1.mp4",
            "filename": "主图视频1.mp4",
            "materialPath": "",
            "useMaterialPicker": True,
        }
    ]
    assert data["detailImages"] == ["https://example.test/detail.jpg"]
    assert data["productVideo"] == data["mainVideos"][0]
    assert data["explainVideo"] == data["mainVideos"][0]
    assert data["skus"][0]["productCode"] == "8105#古铜色"
    assert data["marketPrice"] == Decimal("20.00")
    assert data["serviceOptions"] == [
        {"name": "假一赔十", "type": "checkbox", "checked": True},
        {"name": "正品发票", "type": "checkbox", "checked": True},
        {"name": "开票方式", "type": "select", "value": "每申请单必开"},
    ]
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
    assert history["items"][0]["record_key"] == "mall-1:abc"


def test_read_saved_draft_history_backfills_goods_id_and_record_key(tmp_path, monkeypatch):
    history_path = tmp_path / "saved_draft_history.json"
    monkeypatch.setattr(desktop_tool, "DRAFT_HISTORY_PATH", history_path)
    history_path.write_text(
        json.dumps({
            "version": 1,
            "items": [
                {
                    "saved_at": "2026-06-17 15:30:00",
                    "mall_id": "mall-2",
                    "url": "https://mms.pinduoduo.com/goods/goods_add/index?goods_id=goods-2",
                }
            ],
        }, ensure_ascii=False),
        encoding="utf-8",
    )

    history = desktop_tool.read_saved_draft_history()

    assert history["items"][0]["goods_id"] == "goods-2"
    assert history["items"][0]["record_key"] == "mall-2:goods-2"


def test_append_saved_draft_history_deduplicates_by_mall_and_goods(tmp_path, monkeypatch):
    history_path = tmp_path / "saved_draft_history.json"
    monkeypatch.setattr(desktop_tool, "DRAFT_HISTORY_PATH", history_path)

    desktop_tool.append_saved_draft_history(
        {"id": "first-task"},
        {
            "stage": "draft_saved",
            "updated_at": "2026-06-17 15:30:00",
            "detail": {
                "title": "旧标题",
                "mall_id": "mall-1",
                "goods_id": "goods-1",
            },
        },
    )
    desktop_tool.append_saved_draft_history(
        {"id": "second-task"},
        {
            "stage": "draft_saved",
            "updated_at": "2026-06-17 15:35:00",
            "detail": {
                "title": "新标题",
                "mall_id": "mall-1",
                "goods_id": "goods-1",
            },
        },
    )

    history = desktop_tool.read_saved_draft_history()
    assert history["total"] == 1
    assert history["items"][0]["task_id"] == "second-task"
    assert history["items"][0]["title"] == "新标题"
    assert history["items"][0]["record_key"] == "mall-1:goods-1"


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
