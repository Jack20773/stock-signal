import os
from dotenv import load_dotenv

load_dotenv(override=True)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL   = "gemini-flash-lite-latest"
DATABASE_URL   = os.getenv("DATABASE_URL", "")
