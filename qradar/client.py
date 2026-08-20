from __future__ import annotations

import configparser
import ipaddress
import logging
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

import requests
from requests import Response, Session

from .exceptions import (
    QRadarAPIError,
    QRadarConfigError,
    QRadarNotFoundError,
)


class QRadarClient:
    SETS_ENDPOINT = "/reference_data_collections/sets"
    ENTRIES_ENDPOINT = "/reference_data_collections/set_entries"

    def __init__(
        self,
        config_file: str = "config.ini",
        *,
        logger: logging.Logger | None = None,
    ) -> None:

        self.logger = logger or logging.getLogger(
            "qradar_refset"
        )

        self.config_path = Path(
            config_file
        ).expanduser().resolve()

        cfg = self._load_config(
            self.config_path
        )

        self.host = cfg.get(
            "host",
            "",
        ).strip().rstrip("/")

        if not self.host:
            raise QRadarConfigError(
                "Missing qradar.host in config.ini"
            )

        if not self.host.startswith(
            (
                "https://",
                "http://",
            )
        ):
            self.host = f"https://{self.host}"

        self.token = (
            os.getenv(
                "QRADAR_TOKEN",
                "",
            ).strip()
            or cfg.get(
                "token",
                "",
            ).strip()
        )

        if not self.token:
            raise QRadarConfigError(
                "Missing QRadar token. "
                "Set QRADAR_TOKEN or qradar.token."
            )

        self.api_version = (
            os.getenv(
                "QRADAR_API_VERSION",
                "",
            ).strip()
            or cfg.get(
                "api_version",
                "16.0",
            ).strip()
        )

        self._validate_api_version(
            self.api_version
        )

        try:
            self.timeout = int(
                cfg.get(
                    "timeout",
                    "30",
                )
            )

            self.page_size = int(
                cfg.get(
                    "page_size",
                    "500",
                )
            )

        except ValueError as exc:
            raise QRadarConfigError(
                "qradar.timeout and qradar.page_size "
                "must be integers"
            ) from exc

        self.verify = self._resolve_tls_verify(
            cfg.get(
                "certificate",
                "",
            ).strip()
        )

        self.session = Session()

        self.session.headers.update(
            {
                "SEC": self.token,
                "Version": self.api_version,
                "Accept": "application/json",
                "User-Agent": "qradar-refset-cli/5.1",
            }
        )

        self._set_cache: dict[
            str,
            dict[str, Any],
        ] = {}

        self.logger.info(
            "QRadar client initialized: "
            "host=%s api_version=%s verify=%s",
            self.host,
            self.api_version,
            self.verify,
        )

    # ============================================================
    # Configuration
    # ============================================================

    @staticmethod
    def _load_config(
        path: Path,
    ) -> configparser.SectionProxy:

        if not path.exists():
            raise QRadarConfigError(
                f"Configuration file not found: {path}"
            )

        parser = configparser.ConfigParser()

        parser.read(
            path,
            encoding="utf-8",
        )

        if "qradar" not in parser:
            raise QRadarConfigError(
                "Missing [qradar] section "
                "in configuration file"
            )

        return parser["qradar"]

    @staticmethod
    def _validate_api_version(
        version: str,
    ) -> None:

        match = re.fullmatch(
            r"(\d+)(?:\.(\d+))?",
            version,
        )

        if not match:
            raise QRadarConfigError(
                f"Invalid API version: {version!r}"
            )

        major = int(
            match.group(1)
        )

        if major < 16:
            raise QRadarConfigError(
                "This tool requires QRadar REST API "
                "16.0 or newer."
            )

    def _resolve_tls_verify(
        self,
        certificate: str,
    ) -> bool | str:

        if not certificate:
            return True

        if certificate.lower() in {
            "false",
            "no",
            "0",
        }:
            return False

        path = Path(
            certificate
        ).expanduser()

        if not path.is_absolute():
            path = (
                self.config_path.parent
                / path
            )

        path = path.resolve()

        if not path.exists():
            raise QRadarConfigError(
                f"TLS certificate not found: {path}"
            )

        return str(
            path
        )

    # ============================================================
    # Encoding
    # ============================================================

    @staticmethod
    def _escape_filter_string(
        value: str,
    ) -> str:

        return (
            value
            .replace(
                "\\",
                "\\\\",
            )
            .replace(
                '"',
                '\\"',
            )
        )

    @staticmethod
    def _encode_query_params(
        params: dict[
            str,
            Any,
        ] | None,
    ) -> str:

        if not params:
            return ""

        normalized = {
            str(key): value
            for key, value in params.items()
            if value is not None
        }

        return urlencode(
            normalized,
            doseq=True,
            quote_via=quote,
            safe="",
        )

    def _build_url(
        self,
        endpoint: str,
        params: dict[
            str,
            Any,
        ] | None = None,
    ) -> str:

        endpoint = (
            "/"
            + endpoint.lstrip("/")
        )

        url = (
            f"{self.host}"
            f"/api"
            f"{endpoint}"
        )

        query = self._encode_query_params(
            params
        )

        if query:
            url = (
                f"{url}"
                f"?{query}"
            )

        return url

    # ============================================================
    # HTTP
    # ============================================================

    def _request(
        self,
        method: str,
        endpoint: str,
        *,
        params: dict[
            str,
            Any,
        ] | None = None,
        json_body: Any | None = None,
        headers: dict[
            str,
            str,
        ] | None = None,
    ) -> tuple[
        Any,
        Response,
    ]:

        url = self._build_url(
            endpoint,
            params=params,
        )

        request_headers: dict[
            str,
            str,
        ] = {}

        if headers:
            request_headers.update(
                headers
            )

        # IMPORTANT:
        # Content-Type application/json only when
        # we actually send a JSON body.
        if json_body is not None:
            request_headers[
                "Content-Type"
            ] = "application/json"

        self.logger.debug(
            "HTTP request: "
            "method=%s url=%s body=%s headers=%s",
            method.upper(),
            url,
            (
                json_body
                if json_body is not None
                else "-"
            ),
            request_headers,
        )

        try:
            response = self.session.request(
                method=method.upper(),
                url=url,
                json=(
                    json_body
                    if json_body is not None
                    else None
                ),
                headers=request_headers,
                timeout=self.timeout,
                verify=self.verify,
            )

        except requests.RequestException as exc:

            self.logger.error(
                "HTTP request failed: %s",
                exc,
            )

            raise QRadarAPIError(
                f"Connection error calling "
                f"{url}: {exc}"
            ) from exc

        self.logger.debug(
            "HTTP response: "
            "status=%s content_type=%s",
            response.status_code,
            response.headers.get(
                "Content-Type",
                "-",
            ),
        )

        if not response.ok:
            self._raise_api_error(
                response
            )

        if (
            response.status_code == 204
            or not response.content
        ):
            return (
                None,
                response,
            )

        try:
            return (
                response.json(),
                response,
            )

        except ValueError:
            return (
                response.text,
                response,
            )

    @staticmethod
    def _raise_api_error(
        response: Response,
    ) -> None:

        try:
            payload = response.json()

        except ValueError:
            payload = response.text

        if isinstance(
            payload,
            dict,
        ):

            message = (
                payload.get(
                    "message"
                )
                or payload.get(
                    "description"
                )
                or payload.get(
                    "http_response",
                    {},
                ).get(
                    "message"
                )
                or str(
                    payload
                )
            )

        else:
            message = str(
                payload
            )

        if response.status_code == 401:
            message = (
                "Unauthorized (401). "
                "Check Authorized Service token / SEC header. "
                + message
            )

        elif response.status_code == 403:
            message = (
                "Forbidden (403). "
                "Token lacks required permissions. "
                + message
            )

        elif response.status_code == 406:
            message = (
                "Not Acceptable (406). "
                "Check Accept/Content-Type MIME headers. "
                + message
            )

        raise QRadarAPIError(
            f"QRadar API HTTP "
            f"{response.status_code}: "
            f"{message}"
        )

    def _get_all(
        self,
        endpoint: str,
        *,
        params: dict[
            str,
            Any,
        ] | None = None,
    ) -> list[
        dict[str, Any]
    ]:

        result: list[
            dict[str, Any]
        ] = []

        start = 0

        while True:

            end = (
                start
                + self.page_size
                - 1
            )

            data, response = self._request(
                "GET",
                endpoint,
                params=params,
                headers={
                    "Range": (
                        f"items={start}-{end}"
                    )
                },
            )

            if not isinstance(
                data,
                list,
            ):
                raise QRadarAPIError(
                    f"Expected JSON list "
                    f"from {endpoint}"
                )

            result.extend(
                item
                for item in data
                if isinstance(
                    item,
                    dict,
                )
            )

            if len(
                data
            ) < self.page_size:
                break

            content_range = (
                response.headers.get(
                    "Content-Range",
                    "",
                )
            )

            total_match = re.search(
                r"/(\d+)$",
                content_range,
            )

            if (
                total_match
                and len(result)
                >= int(
                    total_match.group(1)
                )
            ):
                break

            start += self.page_size

        return result

    # ============================================================
    # IP parsing and validation
    # ============================================================

    @staticmethod
    def validate_ip(
        value: str,
    ) -> str:

        value = value.strip()

        try:
            return str(
                ipaddress.ip_address(
                    value
                )
            )

        except ValueError as exc:
            raise ValueError(
                f"Invalid IP address: "
                f"{value}"
            ) from exc

    @classmethod
    def parse_ip_input(
        cls,
        raw: str,
    ) -> list[str]:

        if raw is None:
            raise ValueError(
                "IP input is missing"
            )

        tokens = re.split(
            r"[\r\n,]+",
            raw,
        )

        result: list[
            str
        ] = []

        seen: set[
            str
        ] = set()

        invalid: list[
            str
        ] = []

        for token in tokens:

            token = token.strip()

            if not token:
                continue

            try:
                ip = cls.validate_ip(
                    token
                )

            except ValueError:
                invalid.append(
                    token
                )
                continue

            if ip not in seen:
                seen.add(
                    ip
                )

                result.append(
                    ip
                )

        if invalid:
            raise ValueError(
                "Invalid IP address(es): "
                + ", ".join(
                    invalid
                )
            )

        if not result:
            raise ValueError(
                "No valid IP addresses "
                "were provided"
            )

        return result

    # ============================================================
    # Reference Sets
    # ============================================================

    def list_reference_sets(
        self,
        *,
        ip_only: bool = False,
    ) -> list[
        dict[str, Any]
    ]:

        params: dict[
            str,
            Any,
        ] = {
            "fields": (
                "id,name,entry_type,"
                "namespace,"
                "number_of_entries,"
                "tenant_id,"
                "time_to_live,"
                "expiry_type"
            ),
        }

        if ip_only:
            params["filter"] = (
                'entry_type="IP"'
            )

        sets = self._get_all(
            self.SETS_ENDPOINT,
            params=params,
        )

        return sorted(
            sets,
            key=lambda item: str(
                item.get(
                    "name",
                    "",
                )
            ).casefold(),
        )

    def jenkins_reference_set_names(
        self,
        *,
        ip_only: bool = True,
    ) -> list[str]:

        return [
            str(
                item["name"]
            )
            for item
            in self.list_reference_sets(
                ip_only=ip_only
            )
            if item.get(
                "name"
            )
        ]

    def get_reference_set_by_name(
        self,
        name: str,
    ) -> dict[
        str,
        Any,
    ]:

        name = name.strip()

        if not name:
            raise ValueError(
                "Reference set name "
                "cannot be empty"
            )

        if name in self._set_cache:

            self.logger.debug(
                "Reference set cache hit: %r",
                name,
            )

            return self._set_cache[
                name
            ]

        self.logger.info(
            "Resolving reference set "
            "name: %r",
            name,
        )

        escaped_name = (
            self._escape_filter_string(
                name
            )
        )

        sets = self._get_all(
            self.SETS_ENDPOINT,
            params={
                "filter": (
                    f'name="{escaped_name}"'
                ),
                "fields": (
                    "id,name,entry_type,"
                    "namespace,"
                    "number_of_entries,"
                    "tenant_id"
                ),
            },
        )

        exact = [
            item
            for item in sets
            if str(
                item.get(
                    "name",
                    "",
                )
            ) == name
        ]

        if not exact:
            raise QRadarNotFoundError(
                f"Reference set not found: "
                f"{name!r}"
            )

        if len(
            exact
        ) > 1:

            ids = ", ".join(
                str(
                    item.get(
                        "id"
                    )
                )
                for item
                in exact
            )

            raise QRadarAPIError(
                f"Multiple reference sets "
                f"named {name!r}. "
                f"IDs: {ids}"
            )

        refset = exact[0]

        self._set_cache[
            name
        ] = refset

        self.logger.info(
            "Resolved reference set: "
            "name=%r id=%s entry_type=%s",
            name,
            refset.get(
                "id"
            ),
            refset.get(
                "entry_type"
            ),
        )

        return refset

    @staticmethod
    def _require_ip_set(
        refset: dict[
            str,
            Any,
        ],
    ) -> None:

        if str(
            refset.get(
                "entry_type",
                "",
            )
        ).upper() != "IP":

            raise QRadarAPIError(
                f"Reference set "
                f"{refset.get('name')!r} "
                f"is not entry_type=IP"
            )

    # ============================================================
    # List IPs
    # ============================================================

    def list_entries(
        self,
        reference_set_name: str,
    ) -> list[
        dict[str, Any]
    ]:

        refset = (
            self.get_reference_set_by_name(
                reference_set_name
            )
        )

        self._require_ip_set(
            refset
        )

        refset_id = int(
            refset["id"]
        )

        self.logger.info(
            "Reading entries: "
            "refset=%r id=%s",
            reference_set_name,
            refset_id,
        )

        return self._get_all(
            self.ENTRIES_ENDPOINT,
            params={
                "entry_type": "IP",
                "filter": (
                    f"collection_id="
                    f"{refset_id}"
                ),
                "fields": (
                    "id,collection_id,"
                    "value,first_seen,"
                    "last_seen,source,"
                    "notes,domain_id"
                ),
                "sort": "+value",
            },
        )

    def list_ips(
        self,
        reference_set_name: str,
    ) -> list[str]:

        entries = self.list_entries(
            reference_set_name
        )

        ips = [
            str(
                entry["value"]
            )
            for entry
            in entries
            if entry.get(
                "value"
            )
        ]

        self.logger.info(
            "LIST IPs: "
            "refset=%r count=%s",
            reference_set_name,
            len(
                ips
            ),
        )

        return ips

    # ============================================================
    # Check IP
    # ============================================================

    def get_entry(
        self,
        reference_set_name: str,
        value: str,
    ) -> dict[
        str,
        Any,
    ] | None:

        normalized = (
            self.validate_ip(
                value
            )
        )

        refset = (
            self.get_reference_set_by_name(
                reference_set_name
            )
        )

        self._require_ip_set(
            refset
        )

        refset_id = int(
            refset["id"]
        )

        escaped_value = (
            self._escape_filter_string(
                normalized
            )
        )

        self.logger.info(
            "CHECK: "
            "refset=%r id=%s ip=%s",
            reference_set_name,
            refset_id,
            normalized,
        )

        entries = self._get_all(
            self.ENTRIES_ENDPOINT,
            params={
                "entry_type": "IP",
                "filter": (
                    f'collection_id='
                    f'{refset_id} '
                    f'and value="'
                    f'{escaped_value}"'
                ),
                "fields": (
                    "id,collection_id,"
                    "value,first_seen,"
                    "last_seen,source,"
                    "notes,domain_id"
                ),
            },
        )

        for entry in entries:

            if (
                int(
                    entry.get(
                        "collection_id",
                        -1,
                    )
                )
                == refset_id
                and str(
                    entry.get(
                        "value",
                        "",
                    )
                )
                == normalized
            ):

                self.logger.info(
                    "CHECK result: FOUND "
                    "refset=%r ip=%s "
                    "entry_id=%s",
                    reference_set_name,
                    normalized,
                    entry.get(
                        "id"
                    ),
                )

                return entry

        self.logger.info(
            "CHECK result: NOT_FOUND "
            "refset=%r ip=%s",
            reference_set_name,
            normalized,
        )

        return None

    def check_ip(
        self,
        reference_set_name: str,
        ip: str,
    ) -> dict[
        str,
        Any,
    ]:

        normalized = (
            self.validate_ip(
                ip
            )
        )

        entry = self.get_entry(
            reference_set_name,
            normalized,
        )

        return {
            "reference_set": (
                reference_set_name
            ),
            "ip": normalized,
            "exists": (
                entry is not None
            ),
            "entry": entry,
        }

    def contains_ip(
        self,
        reference_set_name: str,
        ip: str,
    ) -> bool:

        return (
            self.get_entry(
                reference_set_name,
                ip,
            )
            is not None
        )

    # ============================================================
    # ADD
    # ============================================================

    def add_ip(
        self,
        reference_set_name: str,
        ip: str,
    ) -> dict[
        str,
        Any,
    ]:

        value = self.validate_ip(
            ip
        )

        refset = (
            self.get_reference_set_by_name(
                reference_set_name
            )
        )

        self._require_ip_set(
            refset
        )

        refset_id = int(
            refset["id"]
        )

        self.logger.info(
            "ADD: "
            "refset=%r id=%s ip=%s",
            reference_set_name,
            refset_id,
            value,
        )

        existing = self.get_entry(
            reference_set_name,
            value,
        )

        if existing:

            self.logger.info(
                "ADD skipped, "
                "IP already exists: %s",
                value,
            )

            return {
                "status": "exists",
                "ip": value,
                "entry": existing,
            }

        data, _ = self._request(
            "POST",
            self.ENTRIES_ENDPOINT,
            json_body={
                "collection_id": (
                    refset_id
                ),
                "value": value,
            },
        )

        if not isinstance(
            data,
            dict,
        ):
            raise QRadarAPIError(
                "Unexpected response "
                "after creating set entry"
            )

        self.logger.info(
            "ADD success: "
            "refset=%r ip=%s "
            "entry_id=%s",
            reference_set_name,
            value,
            data.get(
                "id"
            ),
        )

        return {
            "status": "added",
            "ip": value,
            "entry": data,
        }

    # ============================================================
    # REMOVE
    # ============================================================

    def remove_ip(
        self,
        reference_set_name: str,
        ip: str,
    ) -> dict[
        str,
        Any,
    ]:

        value = self.validate_ip(
            ip
        )

        refset = (
            self.get_reference_set_by_name(
                reference_set_name
            )
        )

        self._require_ip_set(
            refset
        )

        self.logger.info(
            "REMOVE: "
            "refset=%r ip=%s",
            reference_set_name,
            value,
        )

        entry = self.get_entry(
            reference_set_name,
            value,
        )

        if not entry:

            self.logger.warning(
                "REMOVE not found: "
                "refset=%r ip=%s",
                reference_set_name,
                value,
            )

            return {
                "status": "not_found",
                "ip": value,
            }

        entry_id = int(
            entry["id"]
        )

        self.logger.debug(
            "Deleting QRadar entry: "
            "id=%s ip=%s",
            entry_id,
            value,
        )

        # IMPORTANT:
        # QRadar DELETE endpoint does NOT accept
        # application/json MIME type.
        self._request(
            "DELETE",
            (
                f"{self.ENTRIES_ENDPOINT}"
                f"/{entry_id}"
            ),
            headers={
                "Accept": "text/plain",
            },
        )

        self.logger.info(
            "REMOVE success: "
            "refset=%r ip=%s "
            "entry_id=%s",
            reference_set_name,
            value,
            entry_id,
        )

        return {
            "status": "removed",
            "ip": value,
            "entry_id": entry_id,
        }

    # ============================================================
    # BULK ADD
    # ============================================================

    def add_ips(
        self,
        reference_set_name: str,
        raw_ips: str,
    ) -> list[
        dict[str, Any]
    ]:

        ips = self.parse_ip_input(
            raw_ips
        )

        self.logger.info(
            "Bulk ADD requested: "
            "refset=%r count=%s",
            reference_set_name,
            len(
                ips
            ),
        )

        results: list[
            dict[str, Any]
        ] = []

        for index, ip in enumerate(
            ips,
            start=1,
        ):

            self.logger.info(
                "Bulk ADD %s/%s: %s",
                index,
                len(
                    ips
                ),
                ip,
            )

            try:
                result = self.add_ip(
                    reference_set_name,
                    ip,
                )

            except Exception as exc:

                self.logger.error(
                    "Bulk ADD failed: "
                    "ip=%s error=%s",
                    ip,
                    exc,
                )

                results.append(
                    {
                        "status": "failed",
                        "ip": ip,
                        "error": str(
                            exc
                        ),
                    }
                )

            else:
                results.append(
                    result
                )

        return results

    # ============================================================
    # BULK REMOVE
    # ============================================================

    def remove_ips(
        self,
        reference_set_name: str,
        raw_ips: str,
    ) -> list[
        dict[str, Any]
    ]:

        ips = self.parse_ip_input(
            raw_ips
        )

        self.logger.info(
            "Bulk REMOVE requested: "
            "refset=%r count=%s",
            reference_set_name,
            len(
                ips
            ),
        )

        results: list[
            dict[str, Any]
        ] = []

        for index, ip in enumerate(
            ips,
            start=1,
        ):

            self.logger.info(
                "Bulk REMOVE %s/%s: %s",
                index,
                len(
                    ips
                ),
                ip,
            )

            try:
                result = self.remove_ip(
                    reference_set_name,
                    ip,
                )

            except Exception as exc:

                self.logger.error(
                    "Bulk REMOVE failed: "
                    "ip=%s error=%s",
                    ip,
                    exc,
                )

                results.append(
                    {
                        "status": "failed",
                        "ip": ip,
                        "error": str(
                            exc
                        ),
                    }
                )

            else:
                results.append(
                    result
                )

        return results

    # ============================================================
    # BULK CHECK
    # ============================================================

    def contains_ips(
        self,
        reference_set_name: str,
        raw_ips: str,
    ) -> list[
        dict[str, Any]
    ]:

        ips = self.parse_ip_input(
            raw_ips
        )

        self.logger.info(
            "Bulk CHECK requested: "
            "refset=%r count=%s",
            reference_set_name,
            len(
                ips
            ),
        )

        results: list[
            dict[str, Any]
        ] = []

        for index, ip in enumerate(
            ips,
            start=1,
        ):

            self.logger.info(
                "Bulk CHECK %s/%s: %s",
                index,
                len(
                    ips
                ),
                ip,
            )

            try:
                result = self.check_ip(
                    reference_set_name,
                    ip,
                )

            except Exception as exc:

                self.logger.error(
                    "Bulk CHECK failed: "
                    "ip=%s error=%s",
                    ip,
                    exc,
                )

                results.append(
                    {
                        "status": "failed",
                        "reference_set": (
                            reference_set_name
                        ),
                        "ip": ip,
                        "error": str(
                            exc
                        ),
                    }
                )

            else:

                result["status"] = (
                    "found"
                    if result["exists"]
                    else "not_found"
                )

                results.append(
                    result
                )

        return results
