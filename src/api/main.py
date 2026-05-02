"""Cloud Run / container entrypoint: re-exports the LINE webhook FastAPI app.

Use: uvicorn src.api.main:app --host 0.0.0.0 --port ${PORT}

Implementation lives in src.interfaces.line.main; this module fixes a stable import path for deploy.
"""

from src.interfaces.line.main import app

__all__ = ["app"]
