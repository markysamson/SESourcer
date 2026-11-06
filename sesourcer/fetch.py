"""Fetch a job-posting page the user pasted a link to.

Private, loopback, and link-local addresses are refused so a URL cannot be
used to reach the machine running the app or a cloud metadata service.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import httpx

from sesourcer.clean import html_to_text

_MAX_BYTES = 1_000_000
_MAX_REDIRECTS = 5


class FetchError(Exception):
    """The job page could not be read safely."""


def fetch_job_text(url: str) -> tuple[str, str]:
    """Return ``(page title, visible text)`` for a public http(s) job page."""
    current = assert_public_http_url(url)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-GB,en;q=0.9",
    }
    with httpx.Client(timeout=12, follow_redirects=False) as client:
        for _ in range(_MAX_REDIRECTS):
            _reject_linkedin(current)
            assert_public_http_url(current)
            try:
                response = client.get(current, headers=headers)
            except httpx.HTTPError as exc:
                raise FetchError("The job page did not respond. Paste the description instead.") from exc
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                if not location:
                    raise FetchError("The job page redirected without a destination.")
                current = urljoin(current, location)
                continue
            if response.status_code >= 400:
                raise FetchError(
                    f"The job page returned HTTP {response.status_code}. Paste the description instead."
                )
            content_type = response.headers.get("content-type", "")
            if content_type and "html" not in content_type and "text/" not in content_type:
                raise FetchError("That URL is not an HTML page. Paste the job description instead.")
            raw = response.content[:_MAX_BYTES]
            encoding = response.encoding or "utf-8"
            html = raw.decode(encoding, errors="replace")
            return html_to_text(html)
    raise FetchError("The job page redirected too many times.")


def assert_public_http_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"}:
        raise FetchError("Use an http or https link to the job posting.")
    host = parsed.hostname
    if not host:
        raise FetchError("That job link has no host.")
    if not _is_public_host(host):
        raise FetchError("That job link is not a public web address.")
    return url.strip()


def _reject_linkedin(url: str) -> None:
    host = (urlparse(url).hostname or "").lower()
    if host == "linkedin.com" or host.endswith(".linkedin.com"):
        raise FetchError(
            "LinkedIn does not serve job pages to this app. Paste the job description instead."
        )


def _is_public_host(host: str) -> bool:
    lowered = host.strip(".").lower()
    if lowered in {"localhost", "metadata.google.internal"} or lowered.endswith(
        (".local", ".internal", ".localhost")
    ):
        return False
    try:
        addresses = [ipaddress.ip_address(lowered)]
    except ValueError:
        try:
            infos = socket.getaddrinfo(lowered, None)
        except socket.gaierror as exc:
            raise FetchError("The job link's host could not be resolved.") from exc
        addresses = [ipaddress.ip_address(info[4][0]) for info in infos]
    if not addresses:
        return False
    return all(address.is_global for address in addresses)
