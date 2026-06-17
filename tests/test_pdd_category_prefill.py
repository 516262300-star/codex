from scripts.open_pdd_category import main_image_urls_from_payload


def test_main_image_urls_from_payload_accepts_package_rows_and_plain_urls():
    payload = {
        "main_images": [
            {"filename": "1.jpg", "url": "https://example.test/1.jpg"},
            "https://example.test/2.jpg",
            {"filename": "missing-url.jpg"},
        ]
    }

    assert main_image_urls_from_payload(payload) == [
        "https://example.test/1.jpg",
        "https://example.test/2.jpg",
    ]
