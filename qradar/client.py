from __future__ import annotations

import configparser
import ipaddress
import os
import re
from pathlib import Path
from typing import Any, Iterable

import requests
from requests import Response, Session

from .exceptions import QRadarAPIError, QRadarConfigError, QRadarNotFoundError


class QRadarClient:
    """Client for the non-deprecated QRadar Reference Data Collections API.

    Uses only:
      GET  /api/reference_data_collections/sets
      GET  /api/reference_data_collections/sets/{id}
      GET  /api/reference_data_collections/set_entries
      POST /api/reference_data_collections/set_entries
      DELETE /api/reference_data_collections/set_entries/{id}

    The reference_data_collections API is present in QRadar REST API 16.0+.
    """

    SETS_ENDPOINT = "/reference_data_collections/sets"
    ENTRIES_ENDPOINT = "/reference_data_collections/set_entries"

    def __init__(
        self,
        config_file: str = "config.ini",
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        self.config_path = Path(config_file).expanduser().resolve()
        cfg = self._load_config(self.config_path)

        self.host = cfg.get("host", "").strip().rstrip("/")
        if not self.host:
            raise QRadarConfigError("Missing qradar.host in config.ini")
        if not self.host.startswith(("https://", "http://")):
            self.host = f"https://{self.host}"

        # Jenkins can inject the token as a secret environment variable.
        self.token = os.getenv("QRADAR_TOKEN", cfg.get("token", "")).strip()
        if not self.token:
            raise QRadarConfigError(
                "Missing QRadar token. Set qradar.token in config.ini "
                "or environment variable QRADAR_TOKEN."
            )

        self.api_version = os.getenv(
            "QRADAR_API_VERSION", cfg.get("api_version", "16.0")
        ).strip()
        self._validate_api_version(self.api_version)

        try:
            self.timeout = int(cfg.get("timeout", "30"))
        except ValueError as exc:
            raise QRadarConfigError("qradar.timeout must be an integer") from exc

        self.verify = self._resolve_tls_verify(cfg.get("certificate", "").strip())

        self.session = Session()
        self.session.headers.update(
            {
                "SEC": self.token,
                "Version": self.api_version,
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "qradar-refset-cli/1.0",
            }
        )

    @staticmethod
    def _load_config(path: Path) -> configparser.SectionProxy:
        if not path.exists():
            raise QRadarConfigError(f"Configuration file not found: {path}")

        parser = configparser.ConfigParser()
        parser.read(path, encoding="utf-8")
        if "qradar" not in parser:
            raise QRadarConfigError("Missing [qradar] section in configuration file")
        return parser["qradar"]

    @staticmethod
    def _validate_api_version(version: str) -> None:
        match = re.fullmatch(r"(\d+)(?:\.(\d+))?", version)
        if not match:
            raise QRadarConfigError(f"Invalid API version: {version!r}")
        major = int(match.group(1))
        if major < 16:
            raise QRadarConfigError(
                "This tool intentionally requires QRadar REST API 16.0 or newer "
                "because it uses reference_data_collections instead of deprecated "
                "reference_data/sets endpoints."
            )

    def _resolve_tls_verify(self, certificate: str) -> bool | str:
        if not certificate:
            return True

        if certificate.lower() in {"false", "no", "0"}:
            return False

        cert_path = Path(certificate).expanduser()
        if not cert_path.is_absolute():
            cert_path = self.config_path.parent / cert_path
        cert_path = cert_path.resolve()

        if not cert_path.exists():
            raise QRadarConfigError(f"TLS certificate not found: {cert_path}")
        return str(cert_path)

    def _request(
        self,
        method: str,
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[Any, Response]:
        url = f"{self.host}/api{endpoint}"
        self.logger.debug(
            "HTTP request: method=%s url=%s body=%s",
            method.upper(),
            url,
            json_body if json_body is not None else "-",
        )

        try:
            response = self.session.request(
                method=method,
                url=url,
                params=params,
                json=json_body,
                headers=headers,
                timeout=self.timeout,
                verify=self.verify,
            )
        except requests.RequestException as exc:
            raise QRadarAPIError(f"Connection error calling {url}: {exc}") from exc

        if not response.ok:
            self._raise_api_error(response)

        if response.status_code == 204 or not response.content:
            return None, response

        try:
            return response.json(), response
        except ValueError:
            return response.text, response

    @staticmethod
    def _raise_api_error(response: Response) -> None:
        try:
            payload = response.json()
        except ValueError:
            payload = response.text

        if isinstance(payload, dict):
            message = (
                payload.get("message")
                or payload.get("description")
                or payload.get("http_response", {}).get("message")
                or str(payload)
            )
        else:
            message = str(payload)

        if response.status_code == 401:
            message = (
                "Unauthorized (401). Check the Authorized Service token and ensure "
                "it is sent in the SEC header. Server response: " + message
            )
        elif response.status_code == 403:
            message = "Forbidden (403). Token lacks required permissions. " + message

        raise QRadarAPIError(
            f"QRadar API HTTP {response.status_code}: {message}"
        )

    def _get_all(
        self,
        endpoint: str,
        *,
        params: dict[str, Any] | None = None,
        page_size: int = 500,
    ) -> list[dict[str, Any]]:
        """Fetch a QRadar collection using the Range header."""
        result: list[dict[str, Any]] = []
        start = 0

        while True:
            end = start + page_size - 1
            data, response = self._request(
                "GET",
                endpoint,
                params=params,
                headers={"Range": f"items={start}-{end}"},
            )

            if not isinstance(data, list):
                raise QRadarAPIError(
                    f"Expected a JSON list from {endpoint}, got {type(data).__name__}"
                )

            result.extend(item for item in data if isinstance(item, dict))

            if len(data) < page_size:
                break

            content_range = response.headers.get("Content-Range", "")
            total_match = re.search(r"/(\d+)$", content_range)
            if total_match and len(result) >= int(total_match.group(1)):
                break

            start += page_size

        return result

    # ---------- Reference sets ----------

    def list_reference_sets(self) -> list[dict[str, Any]]:
        sets = self._get_all(
            self.SETS_ENDPOINT,
            params={
                "fields": "id,name,entry_type,namespace,number_of_entries,tenant_id,time_to_live,expiry_type"
            },
        )
        return sorted(sets, key=lambda item: str(item.get("name", "")).lower())

    def get_reference_set_by_id(self, refset_id: int) -> dict[str, Any]:
        data, _ = self._request("GET", f"{self.SETS_ENDPOINT}/{refset_id}")
        if not isinstance(data, dict):
            raise QRadarAPIError("Unexpected response while reading reference set")
        return data

    def get_reference_set_by_name(self, name: str) -> dict[str, Any]:
        matches = [s for s in self.list_reference_sets() if s.get("name") == name]
        if not matches:
            raise QRadarNotFoundError(f"Reference set not found: {name}")
        if len(matches) > 1:
            ids = ", ".join(str(s.get("id")) for s in matches)
            raise QRadarAPIError(
                f"More than one reference set named {name!r} is visible (IDs: {ids}). "
                "Use --refset-id to disambiguate."
            )
        return matches[0]

    def resolve_reference_set(
        self, *, refset: str | None = None, refset_id: int | None = None
    ) -> dict[str, Any]:
        if refset_id is not None:
            return self.get_reference_set_by_id(refset_id)
        if refset:
            return self.get_reference_set_by_name(refset)
        raise QRadarConfigError("Specify --refset NAME or --refset-id ID")

    @staticmethod
    def _require_ip_set(refset: dict[str, Any]) -> None:
        if refset.get("entry_type") != "IP":
            raise QRadarAPIError(
                f"Reference set {refset.get('name')!r} has entry_type="
                f"{refset.get('entry_type')!r}; this CLI manages IP reference sets only."
            )

    # ---------- Entries ----------

    def list_entries(self, refset_id: int, *, entry_type: str = "IP") -> list[dict[str, Any]]:
        return self._get_all(
            self.ENTRIES_ENDPOINT,
            params={
                "entry_type": entry_type,
                "filter": f"collection_id = {int(refset_id)}",
                "fields": "id,collection_id,value,first_seen,last_seen,source,notes,domain_id",
                "sort": "+value",
            },
        )

    def get_entry(self, refset_id: int, value: str) -> dict[str, Any] | None:
        for entry in self.list_entries(refset_id):
            if str(entry.get("value")) == value:
                return entry
        return None

    def add_ip(self, refset: dict[str, Any], ip: str) -> dict[str, Any]:
        self._require_ip_set(refset)
        value = self.validate_ip(ip)
        refset_id = int(refset["id"])

        existing = self.get_entry(refset_id, value)
        if existing:
            return {"status": "exists", "entry": existing}

        data, _ = self._request(
            "POST",
            self.ENTRIES_ENDPOINT,
            json_body={"collection_id": refset_id, "value": value},
        )
        if not isinstance(data, dict):
            raise QRadarAPIError("Unexpected response after creating set entry")
        return {"status": "added", "entry": data}

    def remove_ip(self, refset: dict[str, Any], ip: str) -> dict[str, Any]:
        self._require_ip_set(refset)
        value = self.validate_ip(ip)
        refset_id = int(refset["id"])

        entry = self.get_entry(refset_id, value)
        if not entry:
            return {"status": "not_found", "value": value}

        entry_id = int(entry["id"])
        self._request("DELETE", f"{self.ENTRIES_ENDPOINT}/{entry_id}")
        return {"status": "removed", "entry_id": entry_id, "value": value}

    def contains_ip(self, refset: dict[str, Any], ip: str) -> bool:
        self._require_ip_set(refset)
        value = self.validate_ip(ip)
        return self.get_entry(int(refset["id"]), value) is not None


    @staticmethod
    def parse_ip_input(raw: str) -> list[str]:
        """
        Parse one or many IP addresses from Jenkins/CLI input.

        Accepted forms:
            10.0.0.1
            10.0.0.1,10.0.0.2
            10.0.0.1, 10.0.0.2
            10.0.0.1
            10.0.0.2

        Commas and line breaks can be mixed.
        Empty items are ignored.
        Duplicates are removed while preserving order.
        Every item is validated and normalized.
        """
        if raw is None:
            raise ValueError("IP input is missing")

        tokens = re.split(r"[\r\n,]+", raw)

        result: list[str] = []
        seen: set[str] = set()

        for token in tokens:
            token = token.strip()

            if not token:
                continue

            ip = QRadarClient.validate_ip(token)

            if ip not in seen:
                seen.add(ip)
                result.append(ip)

        if not result:
            raise ValueError("No valid IP addresses were provided")

        return result

    def add_ips(
        self,
        reference_set_name: str,
        ips: list[str],
        *,
        source: str = "Jenkins",
        notes: str | None = None,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []

        for index, ip in enumerate(ips, start=1):
            self.logger.info(
                "ADD %s/%s: refset=%r ip=%s",
                index,
                len(ips),
                reference_set_name,
                ip,
            )

            try:
                result = self.add_ip(
                    reference_set_name,
                    ip,
                    source=source,
                    notes=notes,
                )
            except Exception as exc:
                self.logger.error(
                    "ADD failed: refset=%r ip=%s error=%s",
                    reference_set_name,
                    ip,
                    exc,
                )
                results.append(
                    {
                        "status": "failed",
                        "reference_set": reference_set_name,
                        "ip": ip,
                        "error": str(exc),
                    }
                )
            else:
                self.logger.info(
                    "ADD result: refset=%r ip=%s status=%s",
                    reference_set_name,
                    ip,
                    result.get("status"),
                )
                results.append(result)

        return results

    def remove_ips(
        self,
        reference_set_name: str,
        ips: list[str],
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []

        for index, ip in enumerate(ips, start=1):
            self.logger.info(
                "REMOVE %s/%s: refset=%r ip=%s",
                index,
                len(ips),
                reference_set_name,
                ip,
            )

            try:
                result = self.remove_ip(
                    reference_set_name,
                    ip,
                )
            except Exception as exc:
                self.logger.error(
                    "REMOVE failed: refset=%r ip=%s error=%s",
                    reference_set_name,
                    ip,
                    exc,
                )
                results.append(
                    {
                        "status": "failed",
                        "reference_set": reference_set_name,
                        "ip": ip,
                        "error": str(exc),
                    }
                )
            else:
                self.logger.info(
                    "REMOVE result: refset=%r ip=%s status=%s",
                    reference_set_name,
                    ip,
                    result.get("status"),
                )
                results.append(result)

        return results

    def contains_ips(
        self,
        reference_set_name: str,
        ips: list[str],
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []

        for index, ip in enumerate(ips, start=1):
            self.logger.info(
                "CONTAINS %s/%s: refset=%r ip=%s",
                index,
                len(ips),
                reference_set_name,
                ip,
            )

            try:
                exists = self.contains_ip(
                    reference_set_name,
                    ip,
                )
            except Exception as exc:
                self.logger.error(
                    "CONTAINS failed: refset=%r ip=%s error=%s",
                    reference_set_name,
                    ip,
                    exc,
                )
                results.append(
                    {
                        "status": "failed",
                        "reference_set": reference_set_name,
                        "ip": ip,
                        "error": str(exc),
                    }
                )
            else:
                results.append(
                    {
                        "status": "found" if exists else "not_found",
                        "reference_set": reference_set_name,
                        "ip": ip,
                        "exists": exists,
                    }
                )

        return results

    def import_ips(
        self,
        refset: dict[str, Any],
        values: Iterable[str],
        *,
        continue_on_error: bool = True,
    ) -> dict[str, list[Any]]:
        self._require_ip_set(refset)
        refset_id = int(refset["id"])

        existing = {str(e.get("value")) for e in self.list_entries(refset_id)}
        added: list[str] = []
        skipped: list[str] = []
        invalid: list[str] = []
        failed: list[dict[str, str]] = []

        for raw in values:
            raw = raw.strip()
            if not raw or raw.startswith("#"):
                continue

            try:
                value = self.validate_ip(raw)
            except ValueError:
                invalid.append(raw)
                if continue_on_error:
                    continue
                raise

            if value in existing:
                skipped.append(value)
                continue

            try:
                data, _ = self._request(
                    "POST",
                    self.ENTRIES_ENDPOINT,
                    json_body={"collection_id": refset_id, "value": value},
                )
                if not isinstance(data, dict):
                    raise QRadarAPIError("Unexpected response after creating entry")
                added.append(value)
                existing.add(value)
            except QRadarAPIError as exc:
                failed.append({"value": value, "error": str(exc)})
                if not continue_on_error:
                    raise

        return {
            "added": added,
            "skipped": skipped,
            "invalid": invalid,
            "failed": failed,
        }

    @staticmethod
    def validate_ip(value: str) -> str:
        try:
            return str(ipaddress.ip_address(value.strip()))
        except ValueError as exc:
            raise ValueError(f"Invalid IP address: {value}") from exc
