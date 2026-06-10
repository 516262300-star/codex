from dataclasses import dataclass
from decimal import Decimal

from skills.pdd_listing import resolve_listing_template


@dataclass(frozen=True)
class Meta:
    erp_model: str
    category_path: str
    price_multiplier: Decimal
    material: str
    color: str
    stock_per_sku: int


def test_resolve_listing_template_uses_meta_values(tmp_path):
    template = tmp_path / "attrs.yaml"
    template.write_text(
        """
default_category: "基础建材 > 家用五金 > 拉手 > 明装小拉手"
categories:
  "基础建材 > 家用五金 > 拉手 > 明装小拉手":
    title_template: "梵居匠 {erp_model} {material}"
    attributes:
      材质: "{material}"
      颜色: "{color}"
      孔距: "{hole_distance|单孔}"
""",
        encoding="utf-8",
    )

    meta = Meta(
        erp_model="8250",
        category_path="基础建材 > 家用五金 > 拉手 > 明装小拉手",
        price_multiplier=Decimal("1.6"),
        material="锌合金",
        color="古铜色",
        stock_per_sku=500,
    )

    plan = resolve_listing_template(meta, template)

    assert plan["matched_by"] == "meta.category_path"
    assert plan["template"]["title_template"] == "梵居匠 8250 锌合金"
    assert plan["template"]["attributes"]["材质"] == "锌合金"
    assert plan["template"]["attributes"]["颜色"] == "古铜色"
    assert plan["template"]["attributes"]["孔距"] == "单孔"


def test_default_template_does_not_force_store_brand():
    meta = Meta(
        erp_model="8105-8255",
        category_path="基础建材 > 家用五金 > 拉手 > 明装小拉手",
        price_multiplier=Decimal("1.8"),
        material="黄铜",
        color="古铜色",
        stock_per_sku=500,
    )

    plan = resolve_listing_template(meta, "templates/category_attributes.yaml")

    assert not plan["template"]["title_template"].startswith("梵居匠")
    assert "品牌" not in plan["template"]["attributes"]
