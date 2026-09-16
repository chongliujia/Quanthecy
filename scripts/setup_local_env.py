"""Initialize local credential encryption without printing or replacing secrets."""

import base64
import os
import re
import secrets
from pathlib import Path


def initialize(path: Path) -> bool:
    content = path.read_text() if path.exists() else ""
    pattern = re.compile(r"^AGENT_ENCRYPTION_KEY[ \t]*=(.*)$", re.MULTILINE)
    match = pattern.search(content)
    if match and match.group(1).strip().strip("\"'"):
        return False
    key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
    entry = f"AGENT_ENCRYPTION_KEY={key}"
    if match:
        content = content[: match.start()] + entry + content[match.end() :]
    else:
        content += ("\n" if content and not content.endswith("\n") else "") + entry + "\n"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as file:
        os.fchmod(file.fileno(), 0o600)
        file.write(content)
    return True


if __name__ == "__main__":
    created = initialize(Path(__file__).resolve().parent.parent / ".env")
    print(
        "Local credential encryption initialized." if created else "Existing encryption key kept."
    )
