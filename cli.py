#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from qradar import QRadarAPIError, QRadarClient, QRadarConfigError, QRadarNotFoundError


def emit_json(data: Any) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str))


def add_refset_selector(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--refset", help="Reference set name")
    group.add_argument("--refset-id", type=int, help="Reference set numeric ID")


def resolve(client: QRadarClient, args: argparse.Namespace) -> dict[str, Any]:
    return client.resolve_reference_set(
        refset=getattr(args, "refset", None),
        refset_id=getattr(args, "refset_id", None),
    )


def cmd_refsets(client: QRadarClient, args: argparse.Namespace) -> int:
    sets = client.list_reference_sets()
    if args.ip_only:
        sets = [item for item in sets if item.get("entry_type") == "IP"]

    if args.output == "json":
        emit_json(sets)
    elif args.output == "plain":
        for item in sets:
            print(item.get("name", ""))
    else:
        print(f"{'ID':>6}  {'TYPE':<6} {'ENTRIES':>8}  NAME")
        for item in sets:
            print(
                f"{str(item.get('id', '')):>6}  "
                f"{str(item.get('entry_type', '')):<6} "
                f"{str(item.get('number_of_entries', '')):>8}  "
                f"{item.get('name', '')}"
            )
    return 0


def cmd_list(client: QRadarClient, args: argparse.Namespace) -> int:
    refset = resolve(client, args)
    if refset.get("entry_type") != "IP":
        raise QRadarAPIError(
            f"Reference set {refset.get('name')!r} is not an IP set "
            f"(entry_type={refset.get('entry_type')!r})"
        )
    entries = client.list_entries(int(refset["id"]))

    if args.output == "json":
        emit_json(entries)
    else:
        for entry in entries:
            print(entry.get("value", ""))
    return 0


def cmd_add(client: QRadarClient, args: argparse.Namespace) -> int:
    refset = resolve(client, args)
    result = client.add_ip(refset, args.ip)
    if args.output == "json":
        emit_json(result)
    elif result["status"] == "added":
        print(f"ADDED {result['entry'].get('value')} -> {refset.get('name')}")
    else:
        print(f"EXISTS {result['entry'].get('value')} -> {refset.get('name')}")
    return 0


def cmd_remove(client: QRadarClient, args: argparse.Namespace) -> int:
    refset = resolve(client, args)
    result = client.remove_ip(refset, args.ip)
    if args.output == "json":
        emit_json(result)
    elif result["status"] == "removed":
        print(f"REMOVED {result['value']} <- {refset.get('name')}")
    else:
        print(f"NOT_FOUND {result['value']} in {refset.get('name')}")
    return 0 if result["status"] == "removed" else 1


def cmd_contains(client: QRadarClient, args: argparse.Namespace) -> int:
    refset = resolve(client, args)
    found = client.contains_ip(refset, args.ip)
    if args.output == "json":
        emit_json({"contains": found, "ip": QRadarClient.validate_ip(args.ip)})
    else:
        print("true" if found else "false")
    return 0 if found else 1


def cmd_import(client: QRadarClient, args: argparse.Namespace) -> int:
    refset = resolve(client, args)
    path = Path(args.file)
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")

    with path.open("r", encoding="utf-8") as handle:
        result = client.import_ips(
            refset,
            handle,
            continue_on_error=not args.stop_on_error,
        )

    if args.output == "json":
        emit_json(result)
    else:
        print(f"added={len(result['added'])}")
        print(f"skipped={len(result['skipped'])}")
        print(f"invalid={len(result['invalid'])}")
        print(f"failed={len(result['failed'])}")
        for value in result["invalid"]:
            print(f"INVALID {value}", file=sys.stderr)
        for item in result["failed"]:
            print(f"FAILED {item['value']}: {item['error']}", file=sys.stderr)

    return 2 if result["failed"] else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage QRadar IP reference sets via reference_data_collections API"
    )
    parser.add_argument(
        "--config", default="config.ini", help="Path to config.ini (default: config.ini)"
    )

    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("refsets", help="List reference sets")
    p.add_argument("--ip-only", action="store_true", help="Show only entry_type=IP")
    p.add_argument("--output", choices=("table", "plain", "json"), default="table")
    p.set_defaults(func=cmd_refsets)

    p = sub.add_parser("list", help="List IP addresses in a reference set")
    add_refset_selector(p)
    p.add_argument("--output", choices=("plain", "json"), default="plain")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("add", help="Add one IP address")
    add_refset_selector(p)
    p.add_argument("--ip", required=True)
    p.add_argument("--output", choices=("plain", "json"), default="plain")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("remove", aliases=["delete"], help="Remove one IP address")
    add_refset_selector(p)
    p.add_argument("--ip", required=True)
    p.add_argument("--output", choices=("plain", "json"), default="plain")
    p.set_defaults(func=cmd_remove)

    p = sub.add_parser("contains", help="Check whether an IP exists")
    add_refset_selector(p)
    p.add_argument("--ip", required=True)
    p.add_argument("--output", choices=("plain", "json"), default="plain")
    p.set_defaults(func=cmd_contains)

    p = sub.add_parser("import", help="Import IP addresses from a text file")
    add_refset_selector(p)
    p.add_argument("--file", required=True, help="One IPv4/IPv6 address per line")
    p.add_argument("--stop-on-error", action="store_true")
    p.add_argument("--output", choices=("plain", "json"), default="plain")
    p.set_defaults(func=cmd_import)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        client = QRadarClient(args.config)
        return int(args.func(client, args))
    except (
        QRadarAPIError,
        QRadarConfigError,
        QRadarNotFoundError,
        FileNotFoundError,
        ValueError,
    ) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
