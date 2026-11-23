"""Set an isolated signing key before the application settings are imported by tests."""

import os
import secrets

os.environ["JWT_SECRET"] = secrets.token_urlsafe(32)
