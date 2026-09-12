import os

from dotenv import load_dotenv
from fastmcp import FastMCP

load_dotenv()

mcp = FastMCP("personal-db")


@mcp.tool
def ping(message: str = "pong") -> str:
    """Echo a message back. Used to confirm the server is reachable end-to-end."""
    return f"personal-db says: {message}"


from tools import documents, schema, search  # noqa: E402  (after load_dotenv, before tool registration)

schema.register(mcp)
documents.register(mcp)
search.register(mcp)


def main() -> None:
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if transport == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.run(
            transport="http",
            host=os.environ.get("MCP_HOST", "0.0.0.0"),
            port=int(os.environ.get("MCP_PORT", "8000")),
        )


if __name__ == "__main__":
    main()
