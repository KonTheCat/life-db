import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from services import keyvault  # noqa: E402

keyvault.bootstrap_env({"TELEGRAM_BOT_TOKEN": "telegram-bot-token"})

from services import notifications as notifications_service  # noqa: E402
from services import servicebus as servicebus_service  # noqa: E402


def main() -> None:
    result = servicebus_service.receive_and_handle(
        lambda body: notifications_service.handle_wakeup(body["notification_id"])
    )
    if result is None:
        print("no message available (lost the race to another execution) -- exiting cleanly")
        return
    print(f"{result['id']}: {result['status']}")


if __name__ == "__main__":
    main()
