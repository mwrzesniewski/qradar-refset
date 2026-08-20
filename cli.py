from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from qradar.client import QRadarClient
from qradar.logger import setup_logger


EXIT_OK = 0

# Used for a single CHECK when the IP
# does not exist in the Reference Set.
EXIT_FALSE = 1

# Configuration / API / validation / other error.
EXIT_ERROR = 2


# ==============================================================
# OUTPUT
# ==============================================================

def emit_json(
    data: Any,
) -> None:

    print(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
        )
    )


# ==============================================================
# LIST REFERENCE SETS
# ==============================================================

def cmd_refsets(
    client: QRadarClient,
    args: argparse.Namespace,
) -> int:

    refsets = client.list_reference_sets(
        ip_only=not args.all_types
    )

    if args.output == "json":

        emit_json(
            refsets
        )

    else:

        for refset in refsets:

            print(
                refset.get(
                    "name",
                    ""
                )
            )

    return EXIT_OK


# ==============================================================
# JENKINS ACTIVE CHOICES
# ==============================================================

def cmd_jenkins_refsets(
    client: QRadarClient,
    args: argparse.Namespace,
) -> int:

    names = (
        client.jenkins_reference_set_names(
            ip_only=not args.all_types
        )
    )

    # IMPORTANT:
    #
    # stdout contains ONLY JSON.
    #
    # Logger must write to stderr.
    #
    # Example:
    #
    # [
    #   "Blocked IPs",
    #   "IOC_IPs"
    # ]

    print(
        json.dumps(
            names,
            ensure_ascii=False,
        )
    )

    return EXIT_OK


# ==============================================================
# LIST IP
# ==============================================================

def cmd_list(
    client: QRadarClient,
    args: argparse.Namespace,
) -> int:

    ips = client.list_ips(
        args.refset
    )

    if args.output == "json":

        emit_json(
            ips
        )

    else:

        for ip in ips:

            print(ip)

    return EXIT_OK


# ==============================================================
# CHECK / CONTAINS
# ==============================================================

def cmd_contains(
    client: QRadarClient,
    args: argparse.Namespace,
) -> int:

    results = client.contains_ips(
        args.refset,
        args.ip,
    )

    if args.output == "json":

        emit_json(
            results
        )

    else:

        for item in results:

            if item[
                "status"
            ] == "failed":

                print(
                    f"{item['ip']}="
                    f"ERROR:"
                    f"{item.get('error', '')}"
                )

            else:

                print(
                    f"{item['ip']}="
                    f"{str(item['exists']).lower()}"
                )

    # Any technical/API failure causes
    # Jenkins build failure.

    if any(
        item.get(
            "status"
        ) == "failed"
        for item in results
    ):

        return EXIT_ERROR

    # Single IP:
    #
    # 0 = found
    # 1 = not found

    if len(results) == 1:

        return (
            EXIT_OK
            if results[0]["exists"]
            else EXIT_FALSE
        )

    # Multiple IP addresses:
    #
    # 0 means all checks completed successfully.
    #
    # true/false for individual IPs is available
    # in stdout.

    return EXIT_OK


# ==============================================================
# ADD
# ==============================================================

def cmd_add(
    client: QRadarClient,
    args: argparse.Namespace,
) -> int:

    results = client.add_ips(
        args.refset,
        args.ip,
    )

    if args.output == "json":

        emit_json(
            results
        )

    else:

        for item in results:

            status = item.get(
                "status"
            )

            ip = item.get(
                "ip",
                "",
            )

            if status == "added":

                print(
                    f"ADDED {ip}"
                )

            elif status == "exists":

                print(
                    f"EXISTS {ip}"
                )

            elif status == "failed":

                print(
                    f"FAILED {ip}: "
                    f"{item.get('error', '')}"
                )

            else:

                print(
                    f"{status} {ip}"
                )

    if any(
        item.get(
            "status"
        ) == "failed"
        for item in results
    ):

        return EXIT_ERROR

    return EXIT_OK


# ==============================================================
# REMOVE
# ==============================================================

def cmd_remove(
    client: QRadarClient,
    args: argparse.Namespace,
) -> int:

    results = client.remove_ips(
        args.refset,
        args.ip,
    )

    if args.output == "json":

        emit_json(
            results
        )

    else:

        for item in results:

            status = item.get(
                "status"
            )

            ip = item.get(
                "ip",
                "",
            )

            if status == "removed":

                print(
                    f"REMOVED {ip}"
                )

            elif status == "not_found":

                print(
                    f"NOT_FOUND {ip}"
                )

            elif status == "failed":

                print(
                    f"FAILED {ip}: "
                    f"{item.get('error', '')}"
                )

            else:

                print(
                    f"{status} {ip}"
                )

    if any(
        item.get(
            "status"
        ) == "failed"
        for item in results
    ):

        return EXIT_ERROR

    return EXIT_OK


# ==============================================================
# ARGUMENT PARSER
# ==============================================================

def build_parser() -> argparse.ArgumentParser:

    parser = argparse.ArgumentParser(
        description=(
            "QRadar Reference Set CLI "
            "for REST API 16+"
        )
    )

    parser.add_argument(
        "--config",
        default="config.ini",
        help=(
            "Path to config.ini "
            "(default: config.ini)"
        ),
    )

    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=[
            "DEBUG",
            "INFO",
            "WARNING",
            "ERROR",
            "CRITICAL",
        ],
        help=(
            "Logging level "
            "(default: INFO)"
        ),
    )

    parser.add_argument(
        "--log-file",
        default=None,
        help=(
            "Optional log file"
        ),
    )

    parser.add_argument(
        "--output",
        choices=[
            "text",
            "json",
        ],
        default="text",
        help=(
            "Output format "
            "(default: text)"
        ),
    )

    sub = parser.add_subparsers(
        dest="command",
        required=True,
    )

    # ----------------------------------------------------------
    # refsets
    # ----------------------------------------------------------

    p_refsets = sub.add_parser(
        "refsets",
        help=(
            "List Reference Sets"
        ),
    )

    p_refsets.add_argument(
        "--all-types",
        action="store_true",
        help=(
            "Include non-IP Reference Sets"
        ),
    )

    p_refsets.set_defaults(
        func=cmd_refsets
    )

    # ----------------------------------------------------------
    # jenkins-refsets
    # ----------------------------------------------------------

    p_jenkins = sub.add_parser(
        "jenkins-refsets",
        help=(
            "Return Reference Set names "
            "as JSON array for Jenkins "
            "Active Choices"
        ),
    )

    p_jenkins.add_argument(
        "--all-types",
        action="store_true",
        help=(
            "Include non-IP Reference Sets"
        ),
    )

    p_jenkins.set_defaults(
        func=cmd_jenkins_refsets
    )

    # ----------------------------------------------------------
    # list
    # ----------------------------------------------------------

    p_list = sub.add_parser(
        "list",
        aliases=[
            "list-ips",
        ],
        help=(
            "List all IP addresses "
            "from Reference Set"
        ),
    )

    p_list.add_argument(
        "--refset",
        required=True,
        help=(
            "Reference Set name"
        ),
    )

    p_list.set_defaults(
        func=cmd_list
    )

    # ----------------------------------------------------------
    # contains / check
    # ----------------------------------------------------------

    p_contains = sub.add_parser(
        "contains",
        aliases=[
            "check",
        ],
        help=(
            "Check one or many IP addresses"
        ),
    )

    p_contains.add_argument(
        "--refset",
        required=True,
        help=(
            "Reference Set name"
        ),
    )

    p_contains.add_argument(
        "--ip",
        required=True,
        help=(
            "One or many IP addresses. "
            "Separate with commas or new lines."
        ),
    )

    p_contains.set_defaults(
        func=cmd_contains
    )

    # ----------------------------------------------------------
    # add
    # ----------------------------------------------------------

    p_add = sub.add_parser(
        "add",
        aliases=[
            "add-ip",
        ],
        help=(
            "Add one or many IP addresses"
        ),
    )

    p_add.add_argument(
        "--refset",
        required=True,
        help=(
            "Reference Set name"
        ),
    )

    p_add.add_argument(
        "--ip",
        required=True,
        help=(
            "One or many IP addresses. "
            "Separate with commas or new lines."
        ),
    )

    p_add.set_defaults(
        func=cmd_add
    )

    # ----------------------------------------------------------
    # remove
    # ----------------------------------------------------------

    p_remove = sub.add_parser(
        "remove",
        aliases=[
            "delete",
            "remove-ip",
        ],
        help=(
            "Remove one or many IP addresses"
        ),
    )

    p_remove.add_argument(
        "--refset",
        required=True,
        help=(
            "Reference Set name"
        ),
    )

    p_remove.add_argument(
        "--ip",
        required=True,
        help=(
            "One or many IP addresses. "
            "Separate with commas or new lines."
        ),
    )

    p_remove.set_defaults(
        func=cmd_remove
    )

    return parser


# ==============================================================
# MAIN
# ==============================================================

def main() -> int:

    parser = build_parser()

    args = parser.parse_args()

    logger = setup_logger(
        level=args.log_level,
        log_file=args.log_file,
    )

    try:

        client = QRadarClient(
            config_file=args.config,
            logger=logger,
        )

        return args.func(
            client,
            args,
        )

    except KeyboardInterrupt:

        logger.warning(
            "Interrupted by user"
        )

        return 130

    except ValueError as exc:

        logger.error(
            "Validation error: %s",
            exc,
        )

        return EXIT_ERROR

    except Exception as exc:

        logger.exception(
            "Command failed: %s",
            exc,
        )

        return EXIT_ERROR


if __name__ == "__main__":

    sys.exit(
        main()
    )
