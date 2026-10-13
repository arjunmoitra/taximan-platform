"""Snowflake connection settings, read from the environment.

Nothing here is ever written to disk or logged. Key pair authentication is the
default because Snowflake is phasing out single factor password sign in, so a
plain password may be refused on a newer account. Browser SSO is the fallback
for a laptop.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

from ..config import PROJECT_ROOT

load_dotenv(PROJECT_ROOT / ".env")


# Fixed names. The SQL under warehouse/snowflake creates exactly these objects.
WAREHOUSE = "TAXIMAN_WH"
DATABASE = "TAXIMAN"


class ConfigError(RuntimeError):
    """Required Snowflake settings are missing."""


@dataclass(frozen=True)
class SnowflakeConfig:
    account: str
    user: str
    role: str | None = None
    private_key_path: str | None = None
    private_key_passphrase: str | None = field(default=None, repr=False)
    password: str | None = field(default=None, repr=False)
    authenticator: str | None = None

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "SnowflakeConfig":
        env = os.environ if env is None else env
        missing = [k for k in ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER") if not env.get(k)]
        if missing:
            raise ConfigError(
                f"missing environment variable(s): {', '.join(missing)}. "
                "See docs/WAREHOUSE.md for the full list."
            )
        return cls(
            account=env["SNOWFLAKE_ACCOUNT"],
            user=env["SNOWFLAKE_USER"],
            role=env.get("SNOWFLAKE_ROLE") or None,
            private_key_path=env.get("SNOWFLAKE_PRIVATE_KEY_PATH") or None,
            private_key_passphrase=env.get("SNOWFLAKE_PRIVATE_KEY_PASSPHRASE") or None,
            password=env.get("SNOWFLAKE_PASSWORD") or None,
            authenticator=env.get("SNOWFLAKE_AUTHENTICATOR") or None,
        )

    @property
    def auth_method(self) -> str:
        if self.private_key_path:
            return "key_pair"
        if self.password:
            return "password"
        return "browser_sso"

    def connect_kwargs(self, with_context: bool = True) -> dict:
        """with_context=False is for `setup`, which runs before the warehouse and
        database exist, so naming them on the connection would fail."""
        kwargs: dict = {
            "account": self.account,
            "user": self.user,
            "session_parameters": {"QUERY_TAG": "taximan-warehouse"},
        }
        if with_context:
            kwargs["warehouse"] = WAREHOUSE
            kwargs["database"] = DATABASE
        if self.role:
            kwargs["role"] = self.role
        if self.private_key_path:
            kwargs["private_key"] = _load_private_key(self.private_key_path, self.private_key_passphrase)
        elif self.password:
            kwargs["password"] = self.password
        else:
            kwargs["authenticator"] = self.authenticator or "externalbrowser"
        if self.authenticator and (self.private_key_path or self.password):
            kwargs["authenticator"] = self.authenticator
        return kwargs


def _load_private_key(path: str, passphrase: str | None) -> bytes:
    """Return the key as unencrypted DER bytes, the form the connector expects."""
    from cryptography.hazmat.primitives import serialization

    key = serialization.load_pem_private_key(
        Path(path).expanduser().read_bytes(),
        password=passphrase.encode() if passphrase else None,
    )
    return key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
