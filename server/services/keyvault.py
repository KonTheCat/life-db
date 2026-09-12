import os
from functools import lru_cache

from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient


@lru_cache(maxsize=1)
def _client() -> SecretClient | None:
    vault_url = os.environ.get("AZURE_KEY_VAULT_URL")
    if not vault_url:
        return None
    return SecretClient(vault_url=vault_url, credential=DefaultAzureCredential())


def enabled() -> bool:
    return _client() is not None


def get_secret(name: str) -> str | None:
    client = _client()
    if client is None:
        return None
    try:
        return client.get_secret(name).value
    except Exception:
        return None


def set_secret(name: str, value: str) -> None:
    client = _client()
    if client is not None:
        client.set_secret(name, value)


def bootstrap_env(env_to_secret: dict[str, str]) -> None:
    """Populate os.environ from Key Vault for plain code that reads secrets
    straight from the environment (telegram.py, auth.py), the same way it
    would read them from .env locally. No-op if Key Vault isn't configured.
    Every entrypoint that needs these secrets (server/main.py,
    dispatcher/run.py) must call this itself -- it doesn't happen implicitly.
    """
    if not enabled():
        return
    for env_name, secret_name in env_to_secret.items():
        value = get_secret(secret_name)
        if value:
            os.environ[env_name] = value
