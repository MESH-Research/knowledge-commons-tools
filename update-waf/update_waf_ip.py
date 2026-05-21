#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "boto3>=1.34",
# ]
# ///
"""Add this container's egress IP to a WAFv2 IP set on startup.

Required environment variables:
    WAF_IP_SET_NAME     Name of the IPSet
    WAF_IP_SET_ID       Id of the IPSet (WAFv2 requires both name and id)

Optional environment variables:
    WAF_IP_SET_SCOPE    REGIONAL (default) or CLOUDFRONT
    AWS_REGION          Required when scope is REGIONAL
    IP_CHECK_URL        Echo service returning the egress IP as plain text
                        (default: https://checkip.amazonaws.com)
    LOG_LEVEL           Python logging level (default: INFO)

AWS credentials are resolved through the standard boto3 chain
(environment variables, ECS task role, instance profile, ...).
"""
from __future__ import annotations

import ipaddress
import logging
import os
import sys
import time
import urllib.error
import urllib.request

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger("update-waf-ip")

DEFAULT_IP_CHECK_URL = "https://checkip.amazonaws.com"
MAX_LOCK_RETRIES = 5
RETRY_BACKOFF_SECONDS = 1.0


def fetch_egress_ip(url: str, timeout: float = 5.0) -> str:
    """Return this host's egress IP as seen by an external echo service."""
    req = urllib.request.Request(url, headers={"User-Agent": "update-waf-ip/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("ascii").strip()
    return str(ipaddress.ip_address(raw))


def to_cidr(ip: str) -> str:
    """Return the /32 (IPv4) or /128 (IPv6) CIDR for a single IP."""
    addr = ipaddress.ip_address(ip)
    suffix = 32 if isinstance(addr, ipaddress.IPv4Address) else 128
    return f"{addr}/{suffix}"


def ensure_ip_in_set(
    client,
    *,
    name: str,
    set_id: str,
    scope: str,
    cidr: str,
) -> bool:
    """Add cidr to the WAFv2 IPSet if missing.

    Returns True if added, False if already present. Retries on
    WAFOptimisticLockException up to MAX_LOCK_RETRIES.
    """
    for attempt in range(MAX_LOCK_RETRIES):
        current = client.get_ip_set(Name=name, Scope=scope, Id=set_id)
        addresses = list(current["IPSet"]["Addresses"])
        lock_token = current["LockToken"]

        if cidr in addresses:
            return False

        addresses.append(cidr)
        try:
            client.update_ip_set(
                Name=name,
                Scope=scope,
                Id=set_id,
                Addresses=addresses,
                LockToken=lock_token,
            )
            return True
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code != "WAFOptimisticLockException":
                raise
            if attempt + 1 >= MAX_LOCK_RETRIES:
                raise
            wait = RETRY_BACKOFF_SECONDS * (2**attempt)
            logger.warning(
                "Lock conflict on attempt %d/%d; retrying in %.1fs",
                attempt + 1,
                MAX_LOCK_RETRIES,
                wait,
            )
            time.sleep(wait)

    # Defensive — the loop above either returns or raises.
    raise RuntimeError(f"Exhausted retries updating IPSet {name}")


def remove_ip_from_set(
    client,
    *,
    name: str,
    set_id: str,
    scope: str,
    cidr: str,
) -> bool:
    """Remove cidr from the WAFv2 IPSet if present.

    Returns True if removed, False if it was not in the set. Retries on
    WAFOptimisticLockException up to MAX_LOCK_RETRIES.
    """
    for attempt in range(MAX_LOCK_RETRIES):
        current = client.get_ip_set(Name=name, Scope=scope, Id=set_id)
        addresses = list(current["IPSet"]["Addresses"])
        lock_token = current["LockToken"]

        if cidr not in addresses:
            return False

        addresses.remove(cidr)
        try:
            client.update_ip_set(
                Name=name,
                Scope=scope,
                Id=set_id,
                Addresses=addresses,
                LockToken=lock_token,
            )
            return True
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code != "WAFOptimisticLockException":
                raise
            if attempt + 1 >= MAX_LOCK_RETRIES:
                raise
            wait = RETRY_BACKOFF_SECONDS * (2**attempt)
            logger.warning(
                "Lock conflict on attempt %d/%d; retrying in %.1fs",
                attempt + 1,
                MAX_LOCK_RETRIES,
                wait,
            )
            time.sleep(wait)

    raise RuntimeError(f"Exhausted retries updating IPSet {name}")


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    remove_mode = "--remove" in argv

    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    try:
        name = os.environ["WAF_IP_SET_NAME"]
        set_id = os.environ["WAF_IP_SET_ID"]
    except KeyError as missing:
        logger.error("Missing required env var: %s", missing.args[0])
        return 2

    scope = os.environ.get("WAF_IP_SET_SCOPE", "REGIONAL")
    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
    if scope == "REGIONAL" and not region:
        logger.error("AWS_REGION must be set when WAF_IP_SET_SCOPE=REGIONAL")
        return 2

    url = os.environ.get("IP_CHECK_URL", DEFAULT_IP_CHECK_URL)

    try:
        ip = fetch_egress_ip(url)
    except (urllib.error.URLError, ValueError, OSError) as exc:
        logger.error("Could not determine egress IP via %s: %s", url, exc)
        return 1

    cidr = to_cidr(ip)
    logger.info("Egress IP detected: %s", cidr)

    client = boto3.client("wafv2", region_name=region)

    if remove_mode:
        try:
            removed = remove_ip_from_set(
                client, name=name, set_id=set_id, scope=scope, cidr=cidr
            )
        except ClientError as exc:
            logger.error("WAFv2 update failed: %s", exc)
            return 1

        if removed:
            logger.info("Removed %s from WAFv2 IPSet %s (%s)", cidr, name, scope)
        else:
            logger.info("%s not present in WAFv2 IPSet %s (%s)", cidr, name, scope)
        return 0

    try:
        added = ensure_ip_in_set(
            client, name=name, set_id=set_id, scope=scope, cidr=cidr
        )
    except ClientError as exc:
        logger.error("WAFv2 update failed: %s", exc)
        return 1

    if added:
        logger.info("Added %s to WAFv2 IPSet %s (%s)", cidr, name, scope)
    else:
        logger.info("%s already present in WAFv2 IPSet %s (%s)", cidr, name, scope)
    return 0


if __name__ == "__main__":
    sys.exit(main())
