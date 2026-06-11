from decimal import Decimal

import pytest

from skills.erp_price.client import ERPConfig, ERPPriceClient, ERPSelectors


class FakeLocator:
    def __init__(self, page, selector):
        self.page = page
        self.selector = selector

    def first(self):
        return self

    async def wait_for(self, **_):
        if self.selector == "#search" and not self.page.logged_in:
            raise self.page.timeout_error("not logged in")

    async def fill(self, value):
        self.page.filled[self.selector] = value

    async def click(self):
        if self.selector == "#login":
            self.page.logged_in = True

    async def press(self, key):
        self.page.pressed.append(key)

    async def inner_text(self, **_):
        return "价格: 12.80"


class FakePage:
    class timeout_error(Exception):
        pass

    def __init__(self):
        self.url = ""
        self.logged_in = False
        self.filled = {}
        self.pressed = []

    async def goto(self, url, **_):
        self.url = url

    def locator(self, selector):
        return FakeLocator(self, selector)

    async def reload(self, **_):
        pass

    async def wait_for_load_state(self, *_args, **_kwargs):
        pass

    async def wait_for_url(self, *_args, **_kwargs):
        if not self.logged_in:
            raise self.timeout_error("still on login page")


class FakeContext:
    def __init__(self):
        self.page = FakePage()
        self.saved_path = None

    async def new_page(self):
        return self.page

    async def close(self):
        pass

    async def storage_state(self, path):
        self.saved_path = path


class FakeBrowser:
    def __init__(self):
        self.context = FakeContext()

    async def new_context(self, **_):
        return self.context


class FakeAPIResponse:
    def __init__(self, data):
        self.data = data

    async def json(self):
        return self.data

    async def text(self):
        import json

        return json.dumps(self.data)


class FakeAPIRequest:
    async def post(self, *_args, **_kwargs):
        return FakeAPIResponse({"lists": [{"id": "2497", "price": "10.34"}]})

    async def get(self, *_args, **_kwargs):
        return FakeAPIResponse({"info": {"name": "8160 拉手", "price": "10.34", "skulist": "8160-96"}})


class FakeAPIPage(FakePage):
    def __init__(self):
        super().__init__()
        self.logged_in = True
        self.request = FakeAPIRequest()


class FakeAPIContext(FakeContext):
    def __init__(self):
        self.page = FakeAPIPage()
        self.saved_path = None


class FakeAPIBrowser(FakeBrowser):
    def __init__(self):
        self.context = FakeAPIContext()


@pytest.mark.asyncio
async def test_get_price_logs_in_with_password_when_state_is_expired(tmp_path, monkeypatch):
    import skills.erp_price.client as client_module

    monkeypatch.setattr(client_module, "PlaywrightTimeoutError", FakePage.timeout_error)
    config = ERPConfig(
        login_url="http://erp/login",
        price_page_url="http://erp/prices",
        storage_state=tmp_path / "erp.json",
        username="alice",
        password="secret",
        selectors=ERPSelectors(
            username_input="#user",
            password_input="#pass",
            login_submit="#login",
            search_input="#search",
            price_cell=".price",
        ),
    )

    browser = FakeBrowser()
    erp = ERPPriceClient(browser, config)

    price = await erp.get_price("LDS-2024-001")

    assert price == Decimal("12.80")
    assert browser.context.page.filled["#user"] == "alice"
    assert browser.context.page.filled["#pass"] == "secret"
    assert browser.context.page.filled["#search"] == "LDS-2024-001"
    assert browser.context.saved_path == str(tmp_path / "erp.json")


@pytest.mark.asyncio
async def test_get_price_from_ldswj_api(tmp_path, monkeypatch):
    import skills.erp_price.client as client_module

    monkeypatch.setattr(client_module, "PlaywrightTimeoutError", FakePage.timeout_error)
    config = ERPConfig(
        login_url="http://erp/login",
        price_page_url="http://erp/prices",
        storage_state=tmp_path / "erp.json",
        username="alice",
        password="secret",
        selectors=ERPSelectors(
            username_input="#user",
            password_input="#pass",
            login_submit="#login",
            search_input="#search",
        ),
        lookup_type="ldswj_api",
        api=client_module.ERPAPIConfig(
            search_url="http://erp/search",
            goods2_url_template="http://erp/goods2/{id}",
            price_json_path="info.price",
        ),
    )

    price = await ERPPriceClient(FakeAPIBrowser(), config).get_price("8160")

    assert price == Decimal("10.34")


class FakePremiumRequest:
    async def post(self, *_args, **_kwargs):
        return FakeAPIResponse(
            {
                "title": "优质价类内部专用价格册",
                "lists": [
                    {
                        "name": "8065-20",
                        "colors": [{"color": "古铜色", "price": 11.2}],
                    },
                    {
                        "name": "8065-25",
                        "colors": [
                            {"color": "雅黑", "price": 12.3},
                            {"color": "古铜色", "price": 14.8},
                        ],
                    },
                    {
                        "name": "8065-30",
                        "colors": [{"color": "古铜色", "price": 16.5}],
                    },
                ],
            }
        )


class FakePremiumPage(FakePage):
    def __init__(self):
        super().__init__()
        self.logged_in = True
        self.request = FakePremiumRequest()


class FakePremiumContext(FakeContext):
    def __init__(self):
        self.page = FakePremiumPage()
        self.saved_path = None


class FakePremiumBrowser(FakeBrowser):
    def __init__(self):
        self.context = FakePremiumContext()


@pytest.mark.asyncio
async def test_get_price_from_premium_book_matches_full_model_and_color(tmp_path, monkeypatch):
    import skills.erp_price.client as client_module

    monkeypatch.setattr(client_module, "PlaywrightTimeoutError", FakePage.timeout_error)
    config = ERPConfig(
        login_url="http://erp/login",
        price_page_url="http://erp/premium",
        storage_state=tmp_path / "erp.json",
        username="alice",
        password="secret",
        selectors=ERPSelectors(
            username_input="#user",
            password_input="#pass",
            login_submit="#login",
            search_input="#search",
        ),
        lookup_type="ldswj_premium",
        api=client_module.ERPAPIConfig(
            premium_price_url="http://erp/exportcostprice4xcx",
            premium_price_id="yzfdkja6bvh",
        ),
    )

    price = await ERPPriceClient(FakePremiumBrowser(), config).get_price("8065-25古铜色")

    assert price == Decimal("14.8")


@pytest.mark.asyncio
async def test_get_price_quote_from_premium_book_includes_product_and_color(tmp_path, monkeypatch):
    import skills.erp_price.client as client_module

    monkeypatch.setattr(client_module, "PlaywrightTimeoutError", FakePage.timeout_error)
    config = ERPConfig(
        login_url="http://erp/login",
        price_page_url="http://erp/premium",
        storage_state=tmp_path / "erp.json",
        username="alice",
        password="secret",
        selectors=ERPSelectors(
            username_input="#user",
            password_input="#pass",
            login_submit="#login",
            search_input="#search",
        ),
        lookup_type="ldswj_premium",
        api=client_module.ERPAPIConfig(
            premium_price_url="http://erp/exportcostprice4xcx",
            premium_price_id="yzfdkja6bvh",
        ),
    )

    quote = await ERPPriceClient(FakePremiumBrowser(), config).get_price_quote("8065-25古铜色")

    assert quote.product_name == "8065-25"
    assert quote.color_name == "古铜色"
    assert quote.price == Decimal("14.8")


@pytest.mark.asyncio
async def test_get_price_from_premium_book_allows_safe_model_suffix(tmp_path, monkeypatch):
    import skills.erp_price.client as client_module

    class SuffixPremiumRequest:
        async def post(self, *_args, **_kwargs):
            return FakeAPIResponse(
                {
                    "lists": [
                        {"name": "8064-20直径", "colors": [{"color": "古铜色", "price": 9.8}]},
                        {"name": "8064-25直径", "colors": [{"color": "古铜色", "price": 11.2}]},
                        {"name": "8064-30直径", "colors": [{"color": "古铜色", "price": 13.5}]},
                    ]
                }
            )

    class SuffixPremiumPage(FakePage):
        def __init__(self):
            super().__init__()
            self.logged_in = True
            self.request = SuffixPremiumRequest()

    class SuffixPremiumContext(FakeContext):
        def __init__(self):
            self.page = SuffixPremiumPage()
            self.saved_path = None

    class SuffixPremiumBrowser(FakeBrowser):
        def __init__(self):
            self.context = SuffixPremiumContext()

    monkeypatch.setattr(client_module, "PlaywrightTimeoutError", FakePage.timeout_error)
    config = ERPConfig(
        login_url="http://erp/login",
        price_page_url="http://erp/premium",
        storage_state=tmp_path / "erp.json",
        username="alice",
        password="secret",
        selectors=ERPSelectors(
            username_input="#user",
            password_input="#pass",
            login_submit="#login",
            search_input="#search",
        ),
        lookup_type="ldswj_premium",
        api=client_module.ERPAPIConfig(
            premium_price_url="http://erp/exportcostprice4xcx",
            premium_price_id="yzfdkja6bvh",
        ),
    )

    quote = await ERPPriceClient(SuffixPremiumBrowser(), config).get_price_quote("8064-20古铜色")

    assert quote.product_name == "8064-20直径"
    assert quote.color_name == "古铜色"
    assert quote.price == Decimal("9.8")


@pytest.mark.asyncio
async def test_get_price_from_premium_book_retries_full_model_when_base_has_no_rows(tmp_path, monkeypatch):
    import skills.erp_price.client as client_module

    class RetryPremiumRequest:
        def __init__(self):
            self.words = []

        async def post(self, *_args, **kwargs):
            word = kwargs["form"]["word"]
            self.words.append(word)
            if word == "2075":
                return FakeAPIResponse({"lists": []})
            return FakeAPIResponse(
                {
                    "lists": [
                        {"name": "2075-33", "colors": [{"color": "哑镍拉丝", "price": 18.6}]},
                    ]
                }
            )

    class RetryPremiumPage(FakePage):
        def __init__(self):
            super().__init__()
            self.logged_in = True
            self.request = RetryPremiumRequest()

    class RetryPremiumContext(FakeContext):
        def __init__(self):
            self.page = RetryPremiumPage()
            self.saved_path = None

    class RetryPremiumBrowser(FakeBrowser):
        def __init__(self):
            self.context = RetryPremiumContext()

    monkeypatch.setattr(client_module, "PlaywrightTimeoutError", FakePage.timeout_error)
    config = ERPConfig(
        login_url="http://erp/login",
        price_page_url="http://erp/premium",
        storage_state=tmp_path / "erp.json",
        username="alice",
        password="secret",
        selectors=ERPSelectors(
            username_input="#user",
            password_input="#pass",
            login_submit="#login",
            search_input="#search",
        ),
        lookup_type="ldswj_premium",
        api=client_module.ERPAPIConfig(
            premium_price_url="http://erp/exportcostprice4xcx",
            premium_price_id="yzfdkja6bvh",
        ),
    )
    browser = RetryPremiumBrowser()

    quote = await ERPPriceClient(browser, config).get_price_quote("2075-33哑镍拉丝")

    assert browser.context.page.request.words == ["2075", "2075-33"]
    assert quote.product_name == "2075-33"
    assert quote.color_name == "哑镍拉丝"
    assert quote.price == Decimal("18.6")
