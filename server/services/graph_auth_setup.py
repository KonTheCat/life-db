"""One-time interactive Microsoft Graph sign-in.

Run manually from a machine with browser access (doesn't have to be this
one — the device code flow prints a URL + code you can complete on your
phone). Not an MCP tool; this is a setup step, per plan §7.

    uv run python server/services/graph_auth_setup.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from services import graph  # noqa: E402


def main() -> None:
    result = graph.device_code_login()
    print(f"Signed in as: {result.get('id_token_claims', {}).get('preferred_username', '?')}")
    print(f"Token cache written to: {graph._cache_path().resolve()}")
    print("The MCP server will use this automatically from now on.")


if __name__ == "__main__":
    main()
