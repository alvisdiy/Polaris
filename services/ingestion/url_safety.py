"""The one place an external URL is allowed to become a request.

Every outbound request in Polaris starts from something untrusted: a URL
typed into a source registry row, a link scraped from a page, a redirect
target the server chose. Anything that can reach the crawler can therefore
ask it to fetch ``http://169.254.169.254/`` (cloud metadata),
``http://127.0.0.1:5432/`` (an internal database) or ``file:///etc/passwd``.

So the rule lives here, once, rather than in each connector:

    an external URL is fetched only if its scheme, host, port and every
    address that host resolves to are public

Checks are structural, not string matching: hosts are parsed with
``urllib.parse`` and addresses with ``ipaddress``, so ``0x7f.0.0.1``,
``0177.0.0.1``, ``[::ffff:127.0.0.1]`` and ``127.1`` are recognised for what
they are. A blocked URL raises :class:`UrlSafetyError` and the fetch does not
happen.

DNS is resolved separately (:func:`assert_public_dns`) and at request time,
because a hostname that looks public can still resolve to a private address —
which is the actual SSRF trick, and the reason string checks alone are not
enough.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

# Only these schemes are ever fetched. `javascript:`, `data:`, `file:` and
# `ftp:` are rejected before anything looks at the host.
ALLOWED_SCHEMES = frozenset({"http", "https"})

# Hostnames that name an internal target rather than a site.
BLOCKED_HOSTS = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "ip6-localhost",
        "ip6-loopback",
        "metadata",
        "metadata.google.internal",
        "metadata.goog",
        "instance-data",
    }
)

# Suffixes reserved for names that only resolve inside a network.
BLOCKED_HOST_SUFFIXES = (".localhost", ".local", ".internal", ".intranet")

# Cloud metadata endpoints. They are link-local and therefore already covered,
# but naming them makes the intent legible to a reader and to a test.
METADATA_ADDRESSES = frozenset({"169.254.169.254", "fd00:ec2::254"})

MIN_PORT = 1
MAX_PORT = 65535


class UrlSafetyError(ValueError):
    """A URL may not be fetched. The reason is part of the message.

    Raised rather than logged-and-continued: a blocked target is a decision,
    and the caller decides whether that ends the run or skips one source.
    """


def _is_blocked_address(address: ipaddress._BaseAddress) -> str | None:
    """Why this address is not a public target, or None if it is fine."""
    text = str(address)
    if text in METADATA_ADDRESSES:
        return "cloud metadata endpoint"
    if address.is_loopback:
        return "loopback address"
    if address.is_link_local:
        return "link-local address"
    if address.is_private:
        return "private address"
    if address.is_multicast:
        return "multicast address"
    if address.is_reserved or address.is_unspecified:
        return "reserved address"
    return None


def validate_external_url(
    url: str,
    *,
    allow_http: bool = True,
    resolve_dns: bool = False,
) -> str:
    """Return the URL unchanged, or raise :class:`UrlSafetyError`.

    Args:
        url: the candidate URL.
        allow_http: when False, only https is accepted. Policy, not safety —
            a plain-http source is a downgrade risk, not an SSRF.
        resolve_dns: also check every address the host resolves to. Cheap only
            when the name is already in a resolver cache, so it is opt-in here
            and mandatory in :func:`assert_public_dns`.
    """
    if not url or not isinstance(url, str):
        raise UrlSafetyError(f"not a URL: {url!r}")

    candidate = url.strip()
    parts = urlsplit(candidate)

    scheme = (parts.scheme or "").lower()
    if not scheme:
        raise UrlSafetyError(f"URL has no scheme: {candidate!r}")
    if scheme not in ALLOWED_SCHEMES:
        raise UrlSafetyError(f"scheme {scheme!r} is not fetchable: {candidate!r}")
    if scheme == "http" and not allow_http:
        raise UrlSafetyError(f"http is not permitted by policy: {candidate!r}")

    if parts.username or parts.password or "@" in (parts.netloc or ""):
        raise UrlSafetyError(
            f"URL carries credentials, which are a credential-leak vector: {candidate!r}"
        )

    try:
        hostname = parts.hostname
    except ValueError as exc:  # malformed IPv6 literal, bad port, ...
        raise UrlSafetyError(f"malformed URL {candidate!r}: {exc}") from None
    if not hostname:
        raise UrlSafetyError(f"URL has no host: {candidate!r}")

    host = hostname.lower().rstrip(".")
    if host in BLOCKED_HOSTS:
        raise UrlSafetyError(f"host {host!r} is an internal target: {candidate!r}")
    if any(host.endswith(suffix) for suffix in BLOCKED_HOST_SUFFIXES):
        raise UrlSafetyError(f"host {host!r} uses an internal-only suffix: {candidate!r}")

    try:
        port = parts.port
    except ValueError:
        raise UrlSafetyError(f"invalid port in {candidate!r}") from None
    if port is not None and not (MIN_PORT <= port <= MAX_PORT):
        raise UrlSafetyError(f"port {port} is out of range: {candidate!r}")

    address = _literal_address(host)
    if address is not None:
        reason = _is_blocked_address(address)
        if reason:
            raise UrlSafetyError(f"host resolves to a {reason} ({host}): {candidate!r}")

    if resolve_dns:
        assert_public_dns(candidate)

    return candidate


def _literal_address(host: str) -> ipaddress._BaseAddress | None:
    """Parse `host` as an IP literal, or None when it is a name.

    Bracketed IPv6 arrives without brackets from ``urlsplit.hostname``.

    The legacy IPv4 shorthand forms matter here: ``127.1``, ``0177.0.0.1`` and
    ``0x7f.0.0.1`` all reach 127.0.0.1, and ``ipaddress`` rejects them as
    malformed. ``socket.inet_aton`` accepts exactly those forms, so a host that
    is all digits and dots is interpreted the way the network stack will
    interpret it rather than the way a strict parser would.
    """
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        pass

    if host and all(char.isdigit() or char == "." for char in host):
        try:
            packed = socket.inet_aton(host)
        except OSError:
            return None
        return ipaddress.ip_address(packed)

    return None


def assert_public_dns(url: str, *, timeout: float = 3.0) -> None:
    """Raise unless every address `url` resolves to is public.

    This is the check a hostname-based filter cannot replace: ``evil.example``
    is allowed to exist precisely because it resolves to whatever its owner
    chose, and a DNS name is not evidence of where a packet will go.
    """
    candidate = validate_external_url(url)
    host = urlsplit(candidate).hostname or ""
    literal = _literal_address(host.lower().rstrip("."))
    if literal is not None:
        return  # already checked as a literal

    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        # An unresolvable name cannot be fetched, and must not be treated as
        # "probably fine" — a DNS failure under attack looks exactly like this.
        raise UrlSafetyError(f"cannot resolve host {host!r}: {exc}") from None

    if not infos:
        raise UrlSafetyError(f"host {host!r} resolved to no addresses")

    for info in infos:
        address_text = info[4][0]
        try:
            address = ipaddress.ip_address(address_text)
        except ValueError:
            raise UrlSafetyError(
                f"host {host!r} resolved to an unparseable address {address_text!r}"
            ) from None
        reason = _is_blocked_address(address)
        if reason:
            raise UrlSafetyError(
                f"host {host!r} resolves to a {reason} ({address_text})"
            )


def validate_redirect_chain(final_url: str, history_urls: list[str]) -> None:
    """Validate the final URL and every hop that led to it.

    A safe first request is not a safe chain: the response a server chooses to
    send is as untrusted as the URL a user types, and a redirect into
    ``169.254.169.254`` is the standard way around a first-hop allowlist.
    """
    for url in list(history_urls) + [final_url]:
        validate_external_url(url)


def is_safe_url(url: str, **kwargs) -> bool:
    """Boolean form, for callers that treat a blocked URL as a skip."""
    try:
        validate_external_url(url, **kwargs)
    except UrlSafetyError:
        return False
    return True
