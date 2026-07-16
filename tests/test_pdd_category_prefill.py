from pathlib import Path

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


def test_category_task_waits_for_stable_prefill_page_before_claiming():
    content = (Path(__file__).parents[1] / "pdd_publisher_helper_local" / "content.js").read_text(encoding="utf-8")
    poll_start = content.index("function pollOnce()")
    poll_body = content[poll_start:]

    assert "waitForStableCategoryVariant(20000)" in poll_body
    assert poll_body.index("waitForStableCategoryVariant(20000)") < poll_body.index("claimTask(item)")
    assert "variant === 'v2' && elapsed < 6000" in content


def test_prefill_flow_keeps_main_image_title_category_order():
    content = (Path(__file__).parents[1] / "pdd_publisher_helper_local" / "content.js").read_text(encoding="utf-8")
    flow_start = content.index("function executeCategoryFill")
    flow_end = content.index("// ====== 详情页完整填充流程 ======")
    flow = content[flow_start:flow_end]

    assert flow.index("uploadImages(items") < flow.index("fillTitleOnCategoryPage")
    assert flow.index("fillTitleOnCategoryPage") < flow.index("selectPredictedCategory")
    assert flow.index("activatePrefillMainImageUpload") < flow.index("uploadImages(items")
    assert "if (!uploaded) throw new Error" in flow


def test_image_publish_prefill_without_title_is_detected_and_skips_title_requirement():
    root = Path(__file__).parents[1]
    content = (root / "pdd_publisher_helper_local" / "content.js").read_text(encoding="utf-8")
    handler = (root / "pdd_publisher_helper_local" / "modules" / "category-handler.js").read_text(encoding="utf-8")

    assert "bodyText.includes('上传商品轮播图')" in content
    assert "bodyText.includes('选择商品分类')" in content
    assert "prefillState.hasTitleInput && productData.title" in content
    assert "!state.hasTitleInput || !!state.title" in handler
    assert "selectedPageText.includes('已选分类')" in handler
