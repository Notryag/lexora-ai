from __future__ import annotations

import uvicorn

from lexora_ai.config import get_settings


def run() -> None:
    settings = get_settings()
    uvicorn.run(
        "lexora_ai.api.app:app",
        host=settings.lexora_host,
        port=settings.lexora_port,
        log_level=settings.lexora_log_level,
    )


if __name__ == "__main__":
    run()

