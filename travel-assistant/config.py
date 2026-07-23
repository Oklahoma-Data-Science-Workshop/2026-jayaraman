import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    APP_NAME = "Travel Assistant"
    SECRET_KEY = os.environ.get("SECRET_KEY", "change-me")
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:///trips.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
    GOOGLE_MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")
    SERPAPI_KEY = os.environ.get("SERPAPI_KEY", "")
    CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")
