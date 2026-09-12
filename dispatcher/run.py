import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from services import keyvault  # noqa: E402

keyvault.bootstrap_env({"TELEGRAM_BOT_TOKEN": "telegram-bot-token"})

from services import notifications as notifications_service  # noqa: E402


def main() -> None:
    result = notifications_service.dispatch_due()
    print(f"scanned {result['scanned']} due notification(s)")
    for r in result["results"]:
        print(f"  {r['id']}: {r['status']}")


if __name__ == "__main__":
    main()
