from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_product_video_uses_product_video_area_not_carousel_area():
    source = (ROOT / "pdd_publisher_helper_local" / "content.js").read_text(encoding="utf-8")

    assert "return ImageHandler.selectVideoFromMaterial(videoItem, ['商品视频']" in source
    assert "ImageHandler.selectVideoFromMaterial(productData.productVideo, ['商品视频']" in source
    assert "selectMainVideoFromMaterial(videoItem" not in source


def test_material_folder_and_page_video_entry_are_documented_separately():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "视频虽然存放在图片空间的 `主图` 文件夹，但页面入口不在“商品轮播图”区域" in readme
    assert "从发布页“商品视频”区域点击“上传视频”进入视频选择器" in readme
