"""Run the VOXORA API (and, by default, the background worker).

    python backend/main.py            (from the repository root)
    python main.py                    (from backend/)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import uvicorn  # noqa: E402

from app.core.config import get_settings  # noqa: E402

if __name__ == "__main__":
    s = get_settings()
    reload = "--reload" in sys.argv
    uvicorn.run(
        "app.main:app",
        host=s.host,
        port=s.port,
        reload=reload,
        reload_dirs=[str(Path(__file__).parent / "app")] if reload else None,
        log_config=None,
        timeout_keep_alive=30,
    )
