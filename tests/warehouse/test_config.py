import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from taximan.warehouse.config import ConfigError, SnowflakeConfig

BASE = {"SNOWFLAKE_ACCOUNT": "org-acct", "SNOWFLAKE_USER": "ARJUN"}


def test_account_and_user_are_required():
    with pytest.raises(ConfigError, match="SNOWFLAKE_ACCOUNT, SNOWFLAKE_USER"):
        SnowflakeConfig.from_env({})
    with pytest.raises(ConfigError, match="SNOWFLAKE_USER"):
        SnowflakeConfig.from_env({"SNOWFLAKE_ACCOUNT": "x"})


def test_auth_method_precedence():
    assert SnowflakeConfig.from_env(BASE).auth_method == "browser_sso"
    assert SnowflakeConfig.from_env({**BASE, "SNOWFLAKE_PASSWORD": "p"}).auth_method == "password"
    both = {**BASE, "SNOWFLAKE_PASSWORD": "p", "SNOWFLAKE_PRIVATE_KEY_PATH": "/k.p8"}
    assert SnowflakeConfig.from_env(both).auth_method == "key_pair"


def test_secrets_are_not_in_the_repr():
    cfg = SnowflakeConfig.from_env({**BASE, "SNOWFLAKE_PASSWORD": "hunter2", "SNOWFLAKE_PRIVATE_KEY_PASSPHRASE": "swordfish"})
    assert "hunter2" not in repr(cfg) and "swordfish" not in repr(cfg)


def test_browser_sso_is_the_default_and_context_can_be_left_out():
    kwargs = SnowflakeConfig.from_env(BASE).connect_kwargs()
    assert kwargs["authenticator"] == "externalbrowser"
    assert kwargs["warehouse"] == "TAXIMAN_WH" and kwargs["database"] == "TAXIMAN"
    setup = SnowflakeConfig.from_env(BASE).connect_kwargs(with_context=False)
    assert "warehouse" not in setup and "database" not in setup


def test_role_is_passed_only_when_set():
    assert "role" not in SnowflakeConfig.from_env(BASE).connect_kwargs()
    assert SnowflakeConfig.from_env({**BASE, "SNOWFLAKE_ROLE": "SYSADMIN"}).connect_kwargs()["role"] == "SYSADMIN"


@pytest.mark.parametrize("passphrase", [None, "correct horse"])
def test_key_pair_is_loaded_as_unencrypted_der(tmp_path, passphrase):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    enc = (
        serialization.BestAvailableEncryption(passphrase.encode()) if passphrase else serialization.NoEncryption()
    )
    path = tmp_path / "rsa_key.p8"
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, enc))
    env = {**BASE, "SNOWFLAKE_PRIVATE_KEY_PATH": str(path)}
    if passphrase:
        env["SNOWFLAKE_PRIVATE_KEY_PASSPHRASE"] = passphrase
    kwargs = SnowflakeConfig.from_env(env).connect_kwargs()
    assert "password" not in kwargs and "authenticator" not in kwargs
    loaded = serialization.load_der_private_key(kwargs["private_key"], password=None)
    assert loaded.private_numbers() == key.private_numbers()
