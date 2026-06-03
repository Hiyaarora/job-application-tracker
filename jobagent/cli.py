"""Command-line interface for the Job Search Agent."""
import argparse

from . import auth


def cmd_login(args):
    auth.login()
    print("Login successful. Encrypted token stored in ~/.jobagent/")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jobagent", description="AI Job Search Agent")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("login", help="Authenticate with Google").set_defaults(func=cmd_login)
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)
