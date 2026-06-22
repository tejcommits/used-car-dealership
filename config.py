"""Application configuration, read from environment variables.

Everything has a sensible local default so the app runs out of the box.
For a real deployment, copy .env.example to .env and change the secrets.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin")
    DATABASE = os.environ.get("DATABASE", str(BASE_DIR / "autohub.db"))

    BUSINESS_NAME = os.environ.get("BUSINESS_NAME", "Pune Auto Deals")
    # Phone in international format without +, e.g. 919999999999
    WHATSAPP_NUMBER = os.environ.get("WHATSAPP_NUMBER", "919999999999")

    RUN_SCHEDULER = os.environ.get("RUN_SCHEDULER", "0") == "1"
    SCRAPE_INTERVAL_HOURS = int(os.environ.get("SCRAPE_INTERVAL_HOURS", "12"))

    UPLOAD_FOLDER = str(BASE_DIR / "app" / "static" / "uploads")
    ALLOWED_IMAGE_EXTS = {"jpg", "jpeg", "png", "webp", "gif"}
    MAX_CONTENT_LENGTH = 12 * 1024 * 1024  # 12 MB per request
