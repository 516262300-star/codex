from scripts.open_pdd_category import listing_extra_batch_discount, listing_extra_product_code


def test_listing_extra_fields_use_new_package_values():
    package = {"batchDiscount": "9.9", "productCode": "1.6", "price_multiplier": "1.8"}

    assert listing_extra_batch_discount(package) == "9.9"
    assert listing_extra_product_code(package) == "1.6"


def test_listing_extra_fields_fall_back_for_cached_packages():
    package = {"price_multiplier": "1.6"}

    assert listing_extra_batch_discount(package) == "9.9"
    assert listing_extra_product_code(package) == "1.6"


def test_listing_extra_product_code_falls_back_to_meta_multiplier():
    package = {"meta": {"price_multiplier": "1.7"}}

    assert listing_extra_product_code(package) == "1.7"
