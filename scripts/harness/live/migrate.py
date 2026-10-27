"""Run the entire historical chain without printing SQL/connection credentials."""

import json
import logging
import sys
import traceback
from pathlib import Path

from alembic.config import Config

from alembic import command

logging.disable(logging.CRITICAL)


def main():
    try:
        command.upgrade(Config("alembic/alembic.ini"), "head")
    except BaseException as error:
        code = getattr(getattr(error, "orig", None), "sqlstate", None)
        print(
            json.dumps(
                {
                    "stage": "migration",
                    "error": type(error).__name__,
                    "sqlstate": code if isinstance(code, str) and code.isalnum() else None,
                    "frames": [
                        {
                            "file": Path(frame.filename).name,
                            "line": frame.lineno,
                            "function": frame.name,
                        }
                        for frame in traceback.extract_tb(error.__traceback__)[-5:]
                    ],
                }
            )
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
