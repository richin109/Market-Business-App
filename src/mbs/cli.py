from __future__ import annotations

import argparse
import getpass

from sqlalchemy import select

from mbs.auth import Role, create_user, recover_admin
from mbs.db import SessionLocal
from mbs.models import User


def bootstrap_admin(username: str, password: str) -> None:
    with SessionLocal.begin() as session:
        if session.scalar(select(User)) is not None:
            raise SystemExit("An admin or user already exists")
        create_user(session, username, password, Role.ADMIN)


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
