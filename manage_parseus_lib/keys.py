from __future__ import annotations

import base64
import secrets

def generate_django_secret_key(length: int = 50) -> str:
    alphabet = (
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%^&*(-_=+)"
    )
    return "".join(secrets.choice(alphabet) for _ in range(length))

def generate_fernet_key() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii")

