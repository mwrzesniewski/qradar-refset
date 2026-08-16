#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from qradar import (
    QRadarAPIError,
    QRadarClient,
    QRadarConfigError,
    QRadarNotFoundError,
    setup_logger,
)


EXIT_OK = 0
EXIT_FALSE = 1
EXIT_ERROR = 2


def emit_json(data: Any) -> None:
    print(
        json.dumps(
            data,
            indent=2,
            ensure_ascii=False,
            default=str,
        )
    )


def cmd_refsets(
    client: QRadarClient,
    args: argparse.Namespace,
) -> int:
    sets = client.list_reference_sets(
        ip_only=args.ip_only
    )

    if args.output == "json":
        emit_json(sets)
    elif args.output == "plain":
        for item in sets:
            if item.get("name"):
                print(item["name"])
    else:
        print(
            f"{'ID':>6}  {'TYPE':<6} "
            f"{'ENTRIES':>8}  NAME"
        )
        for item in sets:
            print(
                f"{str(item.get('id', '')):>6}  "
                f"{str(item.get('entry_type', '')):<6} "
                f"{str(item.get('number_of_entries', '')):>8}  "
                f"{item.get('name', '')}"
            )

    return EXIT_OK


def cmd_jenkins_refsets(
    client: QRadarClient,
    args: argparse.Namespace,
) -> int:
    for name in client.jenkins_reference_set_names(
        ip_only=not args.all_types
    ):
        print(name)

    return EXIT_OK


def cmd_list(
    client: QRadarClient,
    args: argparse.Namespace,
) -> int:
    entries = client.list_entries(
        args.refset
    )

    if args.output == "json":
        emit_json(entries)
    else:
        for entry in entries:
            print(entry.get("value", ""))

    return EXIT_OK


def cmd_add(
    client: QRadarClient,
    args: argparse.Namespace,
) -> int:
    results = client.add_ips(
        args.refset,
        args.ip,
    )

    if args.output == "json":
        emit_json(results)
    else:
        for item in results:
            status = item.get("status")
            ip = item.get("ip")

            if status == "added":
                print(
                    f"ADDED {ip} -> {args.refset}"
                )
            elif status == "exists":
                print(
                    f"EXISTS {ip} -> {args.refset}"
                )
            else:
                print(
                    f"FAILED {ip}: "
                    f"{item.get('error', 'unknown error')}"
                )

    return (
        EXIT_ERROR
        if any(
            item.get("status") == "failed"
            for item in results
        )
        else EXIT_OK
    )


def cmd_remove(
    client: QRadarClient,
    args: argparse.Namespace,
) -> int:
    results = client.remove_ips(
        args.refset,
        args.ip,
    )

    if args.output == "json":
        emit_json(results)
    else:
        for item in results:
            status = item.get("status")
            ip = item.get("ip")

            if status == "removed":
                print(
                    f"REMOVED {ip} <- {args.refset}"
                )
            elif status == "not_found":
                print(
                    f"NOT_FOUND {ip} in {args.refset}"
                )
            else:
                print(
                    f"FAILED {ip}: "
                    f"{item.get('error', 'unknown error')}"
                )

    return (
        EXIT_ERROR
        if any(
            item.get("status") == "failed"
            for item in results
        )
        else EXIT_OK
    )


def cmd_contains(
    client: QRadarClient,
    args: argparse.Namespace,
) -> int:
    results = client.contains_ips(
        args.refset,
        args.ip,
    )

    if args.output == "json":
        emit_json(results)
    else:
        for item in results:
            if item.get("status") == "failed":
                print(
                    f"{item.get('ip')}=ERROR:"
                    f"{item.get('error')}"
                )
            else:
                print(
                    f"{item.get('ip')}="
                    f"{str(bool(item.get('exists'))).lower()}"
                )

    if any(
        item.get("status") == "failed"
        for item in results
    ):
        return EXIT_ERROR

    if len(results) == 1:
        return (
            EXIT_OK
            if results[0].get("exists")
            else EXIT_FALSE
        )

    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Manage QRadar IP reference sets via "
            "reference_data_collections API"
        )
    )

    parser.add_argument(
        "--config",
        default="config.ini",
        help="Path to config.ini",
    )

    parser.add_argument(
        "--log-level",
        choices=[
            "DEBUG",
            "INFO",
            "WARNING",
            "ERROR",
            "CRITICAL",
        ],
        default="INFO",
    )

    parser.add_argument(
        "--log-file",
        default=None,
        help="Optional log file",
    )

    sub = parser.add_subparsers(
        dest="command",
        required=True,
    )

    p = sub.add_parser(
        "refsets",
        help="List reference sets",
    )
    p.add_argument(
        "--ip-only",
        action="store_true",
    )
    p.add_argument(
        "--output",
        choices=("table", "plain", "json"),
        default="table",
    )
    p.set_defaults(func=cmd_refsets)

    p = sub.add_parser(
        "jenkins-refsets",
        help="Print names only for Jenkins Active Choices",
    )
    p.add_argument(
        "--all-types",
        action="store_true",
        help="Include non-IP reference sets",
    )
    p.set_defaults(func=cmd_jenkins_refsets)

    p = sub.add_parser(
        "list",
        help="List IP addresses in a reference set",
    )
    p.add_argument(
        "--refset",
        required=True,
        help="Reference set name",
    )
    p.add_argument(
        "--output",
        choices=("plain", "json"),
        default="plain",
    )
    p.set_defaults(func=cmd_list)

    for command, help_text, func in [
        ("add", "Add one or many IP addresses", cmd_add),
        ("remove", "Remove one or many IP addresses", cmd_remove),
        ("contains", "Check one or many IP addresses", cmd_contains),
    ]:
        p = sub.add_parser(
            command,
            help=help_text,
        )
        p.add_argument(
            "--refset",
            required=True,
            help="Reference set name",
        )
        p.add_argument(
            "--ip",
            required=True,
            help=(
                "One IP or multiple IPs separated "
                "by commas and/or new lines"
            ),
        )
        p.add_argument(
            "--output",
            choices=("plain", "json"),
            default="plain",
        )
        p.set_defaults(func=func)

    return parser


def main() -> int:
    args = build_parser().parse_args()

    logger = setup_logger(
        level=args.log_level,
        log_file=args.log_file,
    )

    logger.info(
        "Starting command: %s",
        args.command,
    )

    try:
        client = QRadarClient(
            args.config,
            logger=logger,
        )

        exit_code = int(
            args.func(client, args)
        )

        logger.info(
            "Command finished: %s exit_code=%s",
            args.command,
            exit_code,
        )

        return exit_code

    except (
        QRadarAPIError,
        QRadarConfigError,
        QRadarNotFoundError,
        FileNotFoundError,
        ValueError,
    ) as exc:
        logger.error("%s", exc)
        print(
            f"ERROR: {exc}",
            file=sys.stderr,
        )
        return EXIT_ERROR

    except KeyboardInterrupt:
        logger.warning("Interrupted")
        return 130


if __name__ == "__main__":
    sys.exit(main())
