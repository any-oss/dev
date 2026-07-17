from __future__ import annotations

import uvicorn

from config_loader import settings_from_environment

from .app import create_app

settings = settings_from_environment()
app = create_app(settings)


def main() -> None:
    uvicorn.run("policy_gateway.main:app", host=settings.host, port=settings.port, factory=False)


if __name__ == "__main__":
    main()
