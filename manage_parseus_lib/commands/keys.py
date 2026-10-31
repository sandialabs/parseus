from __future__ import annotations

import argparse

from manage_parseus_lib.keys import generate_django_secret_key, generate_fernet_key
from manage_parseus_lib.output import die

def do_create_key(args: argparse.Namespace) -> None:
    if args.kind == "fernet":
        print(generate_fernet_key())
        return

    if args.kind == "django-secret":
        print(generate_django_secret_key())
        return

    die(f"Unsupported --kind: {args.kind}")

