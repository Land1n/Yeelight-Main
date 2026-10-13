from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent


def load_project_env() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
