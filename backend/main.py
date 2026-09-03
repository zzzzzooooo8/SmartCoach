import os
from pathlib import Path

import uvicorn

from app.main import app as fastapi_app

app = fastapi_app


def main() -> None:
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    reload = os.getenv("RELOAD", "0") == "1"

    os.chdir(Path(__file__).resolve().parent)
    uvicorn.run("app.main:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    main()
