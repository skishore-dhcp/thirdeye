import os
import secrets

from dotenv import load_dotenv

load_dotenv()


def _database_url():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set. ThirdEye needs the Supabase connection string.")
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
    SQLALCHEMY_DATABASE_URI = _database_url()
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
    GEMINI_MODEL = os.environ.get("GEMINI_MODEL") or "gemini-3.1-flash-lite"
    GEMINI_THINKING_BUDGET = 0

    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "0") == "1"
    CSRF_ENABLED = True

    MAX_TEXT_CHARS = 5000
    MAX_PDF_BYTES = 10 * 1024 * 1024
    MAX_PDF_PAGES = 30
    MAX_IMAGE_BYTES = 10 * 1024 * 1024
    MAX_IMAGE_PIXELS = 25_000_000
    OCR_MAX_SIDE = 3500
    OCR_MIN_SIDE = 1000
    OCR_TIMEOUT = 60
    OCR_LOW_CONFIDENCE = 60
    MAX_LOGO_BYTES = 2 * 1024 * 1024
    MAX_LLM_CHARS = 8000
    PLACEMENT_UNIT_CHARS = 160
    LLM_REASON_WORDS = 12
    LLM_MAX_OUTPUT_TOKENS = 400
    LLM_CACHE_SIZE = 128
    MAX_RULE_CHARS = 200
    MAX_COLORS = 5
    HISTORY_LIMIT = 15
    INSIGHT_THRESHOLD = 3
    INSIGHT_LIMIT = 5
    DRAFT_TTL_MINUTES = 60
    MIN_PASSWORD_LENGTH = 6
    ALERTS_KEPT = 50
    ALERTS_SHOWN = 10
    MAX_MESSAGE_CHARS = 300
    MIN_ORG_NAME_CHARS = 2
    MAX_ORG_NAME_CHARS = 60

    VISUAL_MAX_PAGES = 5
    LOGO_MATCH_THRESHOLD = 0.65
    COLOR_TOLERANCES = {"Strict": 30, "Normal": 60, "Loose": 90}
    COLOR_MIN_SHARE = 0.05

    DEMO_MODE = os.environ.get("DEMO_MODE", "1").strip().lower() not in ("0", "false", "no", "off")
    DEMO_USERNAME = os.environ.get("DEMO_USERNAME") or "demo123"
    DEMO_PASSWORD = os.environ.get("DEMO_PASSWORD") or "demo"
    DEMO_MEMBER_USERNAME = os.environ.get("DEMO_MEMBER_USERNAME") or "demo-member"
    DEMO_MEMBER_PASSWORD = os.environ.get("DEMO_MEMBER_PASSWORD") or "demo"
    DEMO_ADMIN_USERNAME = os.environ.get("DEMO_ADMIN_USERNAME") or "demo-admin"
    DEMO_ADMIN_PASSWORD = os.environ.get("DEMO_ADMIN_PASSWORD") or "demo"
    DEMO_ORG_ID = 1
    DEMO_ORG_NAME = "Demo Organization"
    SAMPLE_BRAND_COLORS = ["#0033A0", "#F2A900"]
    SAMPLE_BRAND_TOLERANCE = "Normal"

    LOGIN_MAX_FAILURES = 5
    LOGIN_LOCK_SECONDS = 300

    RULE_KINDS = {
        "must_not_use": "Must not use",
        "must_include": "Must include",
        "tone": "Tone / Style",
    }

    SAMPLE_RULES = [
        ("must_not_use", "cheap", "affordable"),
        ("must_not_use", "best ever", "highly rated"),
        ("must_not_use", "guarantee"),
        ("must_include", "Terms and conditions apply"),
    ]
    if GEMINI_API_KEY:
        SAMPLE_RULES.append(("tone", "Friendly and professional, no slang"))
    DEFAULT_RULES = []
    DEFAULT_REPLACEMENT = "[removed]"
