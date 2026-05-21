"""Tests for update_waf_ip.

Run with:
    uv run --with pytest --with boto3 pytest test_update_waf_ip.py
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

import update_waf_ip as mod


def test_to_cidr_ipv4():
    assert mod.to_cidr("1.2.3.4") == "1.2.3.4/32"


def test_to_cidr_ipv6():
    assert mod.to_cidr("2001:db8::1") == "2001:db8::1/128"


def test_to_cidr_rejects_invalid():
    with pytest.raises(ValueError):
        mod.to_cidr("not-an-ip")


def _mock_urlopen_returning(body: bytes):
    cm = MagicMock()
    cm.__enter__.return_value.read.return_value = body
    cm.__exit__.return_value = False
    return cm


def test_fetch_egress_ip_strips_whitespace():
    with patch("update_waf_ip.urllib.request.urlopen") as urlopen:
        urlopen.return_value = _mock_urlopen_returning(b"203.0.113.42\n")
        assert mod.fetch_egress_ip("http://example") == "203.0.113.42"


def test_fetch_egress_ip_rejects_garbage_response():
    with patch("update_waf_ip.urllib.request.urlopen") as urlopen:
        urlopen.return_value = _mock_urlopen_returning(b"definitely not an ip")
        with pytest.raises(ValueError):
            mod.fetch_egress_ip("http://example")


def _ip_set(addresses, token="t1"):
    return {"IPSet": {"Addresses": list(addresses)}, "LockToken": token}


def _lock_error():
    return ClientError(
        {"Error": {"Code": "WAFOptimisticLockException", "Message": "stale lock"}},
        "UpdateIPSet",
    )


def test_ensure_ip_in_set_skips_when_already_present():
    client = MagicMock()
    client.get_ip_set.return_value = _ip_set(["1.2.3.4/32", "5.6.7.8/32"])

    added = mod.ensure_ip_in_set(
        client, name="n", set_id="i", scope="REGIONAL", cidr="1.2.3.4/32"
    )

    assert added is False
    client.update_ip_set.assert_not_called()


def test_ensure_ip_in_set_adds_when_missing():
    client = MagicMock()
    client.get_ip_set.return_value = _ip_set(["9.9.9.9/32"], token="lock-A")

    added = mod.ensure_ip_in_set(
        client, name="n", set_id="i", scope="REGIONAL", cidr="1.2.3.4/32"
    )

    assert added is True
    client.update_ip_set.assert_called_once()
    kwargs = client.update_ip_set.call_args.kwargs
    assert set(kwargs["Addresses"]) == {"9.9.9.9/32", "1.2.3.4/32"}
    assert kwargs["LockToken"] == "lock-A"
    assert kwargs["Name"] == "n"
    assert kwargs["Id"] == "i"
    assert kwargs["Scope"] == "REGIONAL"


def test_ensure_ip_in_set_retries_on_lock_conflict_and_refreshes_token():
    client = MagicMock()
    client.get_ip_set.side_effect = [
        _ip_set([], token="stale"),
        _ip_set(["10.0.0.1/32"], token="fresh"),
    ]
    client.update_ip_set.side_effect = [_lock_error(), None]

    with patch("update_waf_ip.time.sleep"):
        added = mod.ensure_ip_in_set(
            client, name="n", set_id="i", scope="REGIONAL", cidr="1.2.3.4/32"
        )

    assert added is True
    assert client.get_ip_set.call_count == 2
    assert client.update_ip_set.call_count == 2
    second_call = client.update_ip_set.call_args_list[1].kwargs
    assert second_call["LockToken"] == "fresh"
    assert set(second_call["Addresses"]) == {"10.0.0.1/32", "1.2.3.4/32"}


def test_ensure_ip_in_set_gives_up_after_max_retries():
    client = MagicMock()
    client.get_ip_set.return_value = _ip_set([])
    client.update_ip_set.side_effect = _lock_error()

    with patch("update_waf_ip.time.sleep"), pytest.raises(Exception):
        mod.ensure_ip_in_set(
            client, name="n", set_id="i", scope="REGIONAL", cidr="1.2.3.4/32"
        )

    assert client.update_ip_set.call_count == mod.MAX_LOCK_RETRIES


def test_ensure_ip_in_set_does_not_retry_on_unrelated_error():
    client = MagicMock()
    client.get_ip_set.return_value = _ip_set([])
    client.update_ip_set.side_effect = ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "no"}},
        "UpdateIPSet",
    )

    with pytest.raises(ClientError):
        mod.ensure_ip_in_set(
            client, name="n", set_id="i", scope="REGIONAL", cidr="1.2.3.4/32"
        )

    assert client.update_ip_set.call_count == 1


def test_remove_ip_from_set_skips_when_absent():
    client = MagicMock()
    client.get_ip_set.return_value = _ip_set(["9.9.9.9/32"])

    removed = mod.remove_ip_from_set(
        client, name="n", set_id="i", scope="REGIONAL", cidr="1.2.3.4/32"
    )

    assert removed is False
    client.update_ip_set.assert_not_called()


def test_remove_ip_from_set_removes_when_present():
    client = MagicMock()
    client.get_ip_set.return_value = _ip_set(
        ["1.2.3.4/32", "9.9.9.9/32"], token="lock-A"
    )

    removed = mod.remove_ip_from_set(
        client, name="n", set_id="i", scope="REGIONAL", cidr="1.2.3.4/32"
    )

    assert removed is True
    client.update_ip_set.assert_called_once()
    kwargs = client.update_ip_set.call_args.kwargs
    assert kwargs["Addresses"] == ["9.9.9.9/32"]
    assert kwargs["LockToken"] == "lock-A"
    assert kwargs["Name"] == "n"
    assert kwargs["Id"] == "i"
    assert kwargs["Scope"] == "REGIONAL"


def test_remove_ip_from_set_leaves_other_addresses_intact():
    client = MagicMock()
    client.get_ip_set.return_value = _ip_set(
        ["1.2.3.4/32", "5.6.7.8/32", "9.9.9.9/32"]
    )

    removed = mod.remove_ip_from_set(
        client, name="n", set_id="i", scope="REGIONAL", cidr="5.6.7.8/32"
    )

    assert removed is True
    kwargs = client.update_ip_set.call_args.kwargs
    assert set(kwargs["Addresses"]) == {"1.2.3.4/32", "9.9.9.9/32"}


def test_remove_ip_from_set_retries_on_lock_conflict_and_refreshes_token():
    client = MagicMock()
    client.get_ip_set.side_effect = [
        _ip_set(["1.2.3.4/32", "9.9.9.9/32"], token="stale"),
        _ip_set(["1.2.3.4/32", "10.0.0.1/32"], token="fresh"),
    ]
    client.update_ip_set.side_effect = [_lock_error(), None]

    with patch("update_waf_ip.time.sleep"):
        removed = mod.remove_ip_from_set(
            client, name="n", set_id="i", scope="REGIONAL", cidr="1.2.3.4/32"
        )

    assert removed is True
    assert client.get_ip_set.call_count == 2
    assert client.update_ip_set.call_count == 2
    second_call = client.update_ip_set.call_args_list[1].kwargs
    assert second_call["LockToken"] == "fresh"
    assert second_call["Addresses"] == ["10.0.0.1/32"]


def test_remove_ip_from_set_gives_up_after_max_retries():
    client = MagicMock()
    client.get_ip_set.return_value = _ip_set(["1.2.3.4/32"])
    client.update_ip_set.side_effect = _lock_error()

    with patch("update_waf_ip.time.sleep"), pytest.raises(Exception):
        mod.remove_ip_from_set(
            client, name="n", set_id="i", scope="REGIONAL", cidr="1.2.3.4/32"
        )

    assert client.update_ip_set.call_count == mod.MAX_LOCK_RETRIES


def test_remove_ip_from_set_does_not_retry_on_unrelated_error():
    client = MagicMock()
    client.get_ip_set.return_value = _ip_set(["1.2.3.4/32"])
    client.update_ip_set.side_effect = ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "no"}},
        "UpdateIPSet",
    )

    with pytest.raises(ClientError):
        mod.remove_ip_from_set(
            client, name="n", set_id="i", scope="REGIONAL", cidr="1.2.3.4/32"
        )

    assert client.update_ip_set.call_count == 1


@pytest.fixture
def main_env(monkeypatch):
    monkeypatch.setenv("WAF_IP_SET_NAME", "n")
    monkeypatch.setenv("WAF_IP_SET_ID", "i")
    monkeypatch.setenv("AWS_REGION", "eu-west-2")
    monkeypatch.delenv("WAF_IP_SET_SCOPE", raising=False)


def test_main_default_mode_adds_ip_to_waf(main_env):
    waf = MagicMock()
    waf.get_ip_set.return_value = _ip_set(["9.9.9.9/32"])

    with patch("update_waf_ip.fetch_egress_ip", return_value="1.2.3.4"), patch(
        "update_waf_ip.boto3.client", return_value=waf
    ):
        rc = mod.main([])

    assert rc == 0
    waf.update_ip_set.assert_called_once()
    kwargs = waf.update_ip_set.call_args.kwargs
    assert set(kwargs["Addresses"]) == {"1.2.3.4/32", "9.9.9.9/32"}


def test_main_remove_mode_removes_only_current_ip(main_env):
    waf = MagicMock()
    waf.get_ip_set.return_value = _ip_set(["1.2.3.4/32", "9.9.9.9/32"])

    with patch("update_waf_ip.fetch_egress_ip", return_value="1.2.3.4"), patch(
        "update_waf_ip.boto3.client", return_value=waf
    ):
        rc = mod.main(["--remove"])

    assert rc == 0
    waf.update_ip_set.assert_called_once()
    kwargs = waf.update_ip_set.call_args.kwargs
    assert kwargs["Addresses"] == ["9.9.9.9/32"]


def test_main_remove_mode_is_noop_when_ip_absent(main_env):
    waf = MagicMock()
    waf.get_ip_set.return_value = _ip_set(["9.9.9.9/32"])

    with patch("update_waf_ip.fetch_egress_ip", return_value="1.2.3.4"), patch(
        "update_waf_ip.boto3.client", return_value=waf
    ):
        rc = mod.main(["--remove"])

    assert rc == 0
    waf.update_ip_set.assert_not_called()


def test_main_missing_required_env_returns_error(monkeypatch):
    monkeypatch.delenv("WAF_IP_SET_NAME", raising=False)
    monkeypatch.delenv("WAF_IP_SET_ID", raising=False)

    rc = mod.main([])

    assert rc != 0
