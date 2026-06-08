from skills.pdd_listing import build_sku_specs, derive_spec_name


def test_derive_spec_name_strips_erp_model_prefix():
    assert derive_spec_name("8250-古铜色", "8250") == "古铜色"
    assert derive_spec_name("8065-25-古铜色", "8065-25") == "古铜色"
    assert derive_spec_name("8250铬色", "8250") == "铬色"


def test_build_sku_specs_pairs_name_price_stock_and_image():
    specs = build_sku_specs(
        [
            {
                "sku_name": "8250-古铜色",
                "price_book_name": "8250-33直径",
                "price_book_color": "古铜色",
                "image": "8250-古铜色.jpg",
                "base_price": "14.4",
                "group_price": "23.04",
                "single_price": "24.04",
                "stock": 500,
                "material_image": {
                    "filename": "8250-古铜色.jpeg",
                    "url": "https://example.test/sku.jpeg",
                    "width": 800,
                    "height": 800,
                },
            }
        ],
        erp_model="8250",
    )

    assert specs == [
        {
            "index": 1,
            "sku_name": "8250-古铜色",
            "spec_type": "型号",
            "spec_name": "古铜色",
            "spec_code": "8250-33直径#古铜色",
            "price_book_name": "8250-33直径",
            "price_book_color": "古铜色",
            "base_price": "14.4",
            "group_price": "23.04",
            "single_price": "24.04",
            "final_price": "23.04",
            "stock": 500,
            "local_image": "8250-古铜色.jpg",
            "material_image_filename": "8250-古铜色.jpeg",
            "material_image_url": "https://example.test/sku.jpeg",
            "material_image_width": 800,
            "material_image_height": 800,
        }
    ]
