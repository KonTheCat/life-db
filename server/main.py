import os

from dotenv import load_dotenv
from fastmcp import FastMCP

load_dotenv()

_TRANSPORT = os.environ.get("MCP_TRANSPORT", "stdio")

_auth = None
if _TRANSPORT != "stdio":
    from services import keyvault

    keyvault.bootstrap_env(
        {"TELEGRAM_BOT_TOKEN": "telegram-bot-token", "MCP_BEARER_TOKEN": "mcp-bearer-token"}
    )

    from services.auth import get_auth_provider

    _auth = get_auth_provider()

mcp = FastMCP("personal-db", auth=_auth)


@mcp.tool
def ping(message: str = "pong") -> str:
    """Echo a message back. Used to confirm the server is reachable end-to-end."""
    return f"personal-db says: {message}"


from tools import (  # noqa: E402  (after load_dotenv, before tool registration)
    attachments,
    documents,
    notifications,
    schema,
    search,
    time_tool,
)

schema.register(mcp)
documents.register(mcp)
search.register(mcp)
notifications.register(mcp)
attachments.register(mcp)
time_tool.register(mcp)


def main() -> None:
    if _TRANSPORT == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.run(
            transport="http",
            host=os.environ.get("MCP_HOST", "0.0.0.0"),
            port=int(os.environ.get("MCP_PORT", "8000")),
        )


if __name__ == "__main__":
    main()
