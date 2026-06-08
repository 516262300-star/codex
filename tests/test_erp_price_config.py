import os

from skills.erp_price import load_config


def test_load_config_expands_erp_credentials_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ERP_USERNAME", "alice")
    monkeypatch.setenv("ERP_PASSWORD", "secret")

    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        """
erp:
  login_url: "http://erp/login"
  price_page_url: "http://erp/prices"
  storage_state: "./states/erp.json"
  username: "${ERP_USERNAME}"
  password: "${ERP_PASSWORD}"
  selectors:
    username_input: "#user"
    password_input: "#pass"
    login_submit: "#login"
    search_input: "#search"
    price_cell: ".price"
""",
        encoding="utf-8",
    )

    config = load_config(config_file)

    assert config.username == "alice"
    assert config.password == "secret"
    assert config.selectors.username_input == "#user"
