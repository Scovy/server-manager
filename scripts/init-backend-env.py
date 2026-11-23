"""Prepare the backend environment for a new or existing installation."""

import os
import re
import secrets
from pathlib import Path
from tempfile import NamedTemporaryFile


def initialize(backend: Path) -> None:
    target = backend / ".env"
    source = target if target.exists() else backend / ".env.example"
    content = source.read_text(encoding="utf-8")
    matches = list(re.finditer(r"(?m)^[ \t]*(?:export[ \t]+)?JWT_SECRET[ \t]*=(.*)$", content))
    if len(matches) > 1:
        raise SystemExit("Multiple JWT_SECRET entries in backend/.env. Keep one before setup.")
    match = matches[0] if matches else None
    if match:
        value = match[1].strip().split(" #", 1)[0].strip().strip("\"'")
        if target.exists() and value and value != "CHANGE-ME-IN-PRODUCTION":
            return
    entry = f"JWT_SECRET={secrets.token_hex(32)}"
    if match:
        content = content[:match.start()] + entry + content[match.end():]
    else:
        content = content.rstrip() + "\n" + entry + "\n"
    file = NamedTemporaryFile(dir=backend, mode="w", encoding="utf-8", delete=False)
    temporary = Path(file.name)
    try:
        with file:
            file.write(content)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    initialize(Path(__file__).resolve().parents[1] / "backend")
