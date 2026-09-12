import hmac
import os

from fastmcp.server.auth.auth import AccessToken, TokenVerifier


class StaticBearerTokenVerifier(TokenVerifier):
    """A single static bearer token for a single-user personal server.

    Deliberately not OAuth: that machinery exists for multi-tenant hosted
    servers granting scoped access to many callers. Here there's exactly one
    caller (the user's own Claude client) and one token, stored in Key Vault
    in production and compared in constant time to avoid timing attacks.
    """

    def __init__(self, token: str):
        super().__init__()
        self._token = token

    async def verify_token(self, token: str) -> AccessToken | None:
        if hmac.compare_digest(token, self._token):
            return AccessToken(token=token, client_id="personal-db-owner", scopes=[])
        return None


def get_auth_provider() -> StaticBearerTokenVerifier:
    token = os.environ["MCP_BEARER_TOKEN"]
    return StaticBearerTokenVerifier(token)
