"""Entry point: `python run.py` to start the API server."""
from __future__ import annotations

import uvicorn

from app.config import load_config


def main() -> None:
    cfg = load_config()
    uvicorn.run(
        "app.main:app",
        host=cfg.api_host,
        port=cfg.api_port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
