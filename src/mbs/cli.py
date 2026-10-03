from __future__ import annotations

import argparse
import getpass

from mbs.auth import recover_admin
from mbs.db import SessionLocal
from mbs.errors import ConflictError
from mbs.services.auth import bootstrap_admin_user


def bootstrap_admin(username: str, password: str) -> None:
    with SessionLocal.begin() as session:
        try:
            bootstrap_admin_user(session, username, password)
        except ConflictError as error:
            raise SystemExit(str(error)) from error


def recover_admin_account(username: str, password: str) -> None:
    with SessionLocal.begin() as session:
        recover_admin(session, username, password)


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    bootstrap = subparsers.add_parser("bootstrap-admin")
    bootstrap.add_argument("username")
    recovery = subparsers.add_parser("recover-admin")
    recovery.add_argument("username")
    args = parser.parse_args()
    password = getpass.getpass("Admin password: ")
    if args.command == "bootstrap-admin":
        bootstrap_admin(args.username, password)
    else:
        recover_admin_account(args.username, password)


if __name__ == "__main__":
    main()
