"""Dump the OpenAPI document.

The frontend client is generated from this file. Hand-written duplicate API types are the
thing this exists to prevent, so regenerate rather than editing `packages/api-client`.

    python -m app.openapi > openapi.json
"""
import json
import sys

from app.main import app


def main() -> None:
    json.dump(app.openapi(), sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
