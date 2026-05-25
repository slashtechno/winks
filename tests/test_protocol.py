import struct

import pytest

from winks.protocol import (
    ATTR_MESSAGE,
    ATTR_SUBTITLE,
    ATTR_TITLE,
    DataSource,
    NotifSource,
    build_attr_request,
    parse_data_source,
    parse_notification_source,
)


def _notif_source(event_id=0, flags=0, cat_id=0, cat_count=1, uid=42):
    return bytearray(struct.pack("<BBBBI", event_id, flags, cat_id, cat_count, uid))


def _data_source(uid, attrs: dict[int, str]) -> bytearray:
    buf = bytearray(struct.pack("<BI", 0x00, uid))
    for attr_id, text in attrs.items():
        encoded = text.encode()
        buf += struct.pack("<BH", attr_id, len(encoded))
        buf += encoded
    return buf


class TestParseNotificationSource:
    def test_basic(self):
        data = _notif_source(event_id=0, flags=2, cat_id=6, uid=99)
        result = parse_notification_source(data)
        assert result == NotifSource(uid=99, event_id=0, flags=2, category="Email")

    def test_unknown_category(self):
        data = _notif_source(cat_id=99, uid=1)
        result = parse_notification_source(data)
        assert result is not None
        assert result.category == "Cat(99)"

    def test_too_short_returns_none(self):
        assert parse_notification_source(bytearray(7)) is None

    def test_exactly_8_bytes(self):
        data = _notif_source(event_id=1, uid=0)
        result = parse_notification_source(data)
        assert result is not None
        assert result.event_id == 1

    @pytest.mark.parametrize("cat_id,expected", [
        (0, "Other"),
        (1, "Incoming Call"),
        (2, "Missed Call"),
        (4, "Social"),
        (11, "Entertainment"),
    ])
    def test_known_categories(self, cat_id, expected):
        data = _notif_source(cat_id=cat_id)
        result = parse_notification_source(data)
        assert result is not None
        assert result.category == expected


class TestParseDataSource:
    def test_basic(self):
        data = _data_source(uid=7, attrs={
            ATTR_TITLE: "Hello",
            ATTR_SUBTITLE: "World",
            ATTR_MESSAGE: "How are you",
        })
        result = parse_data_source(data)
        assert result == DataSource(uid=7, title="Hello", subtitle="World", message="How are you")

    def test_missing_attrs_default_to_empty(self):
        data = _data_source(uid=1, attrs={ATTR_TITLE: "Only title"})
        result = parse_data_source(data)
        assert result is not None
        assert result.subtitle == ""
        assert result.message == ""

    def test_wrong_command_byte_returns_none(self):
        data = bytearray(b"\x01" + b"\x00" * 10)
        assert parse_data_source(data) is None

    def test_too_short_returns_none(self):
        assert parse_data_source(bytearray(4)) is None

    def test_empty_attrs_section(self):
        data = bytearray(struct.pack("<BI", 0x00, 5))
        result = parse_data_source(data)
        assert result == DataSource(uid=5, title="", subtitle="", message="")

    def test_truncated_attr_ignored(self):
        # Attr claims 10 bytes but only 2 remain — should not crash
        buf = bytearray(struct.pack("<BI", 0x00, 1))
        buf += struct.pack("<BH", ATTR_TITLE, 10)
        buf += b"hi"  # only 2 bytes
        result = parse_data_source(buf)
        assert result is not None
        assert result.title == ""


class TestBuildAttrRequest:
    def test_structure(self):
        req = build_attr_request(42)
        assert len(req) == 1 + 4 + 3 * 3  # cmd + uid + 3x (attr_id + max_len)
        cmd, uid, a1, l1, a2, l2, a3, l3 = struct.unpack("<BIBHBHBH", req)
        assert cmd == 0x00
        assert uid == 42
        assert a1 == ATTR_TITLE
        assert l1 == 128
        assert a2 == ATTR_SUBTITLE
        assert l2 == 64
        assert a3 == ATTR_MESSAGE
        assert l3 == 256

    def test_uid_zero(self):
        req = build_attr_request(0)
        _, uid, *_ = struct.unpack("<BIBHBHBH", req)
        assert uid == 0

    def test_uid_max(self):
        req = build_attr_request(0xFFFFFFFF)
        _, uid, *_ = struct.unpack("<BIBHBHBH", req)
        assert uid == 0xFFFFFFFF
