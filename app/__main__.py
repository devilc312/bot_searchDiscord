import logging

from dotenv import load_dotenv

from .bot import SearchBot
from .config import Config


def main() -> None:
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = Config.from_env()
    SearchBot(cfg).run(cfg.discord_token, log_handler=None)


if __name__ == "__main__":
    main()
