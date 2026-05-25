from __future__ import annotations

# ANCS packet formats (all little-endian):
#
# Notification Source (8 bytes):
#   [EventID:1][Flags:1][CatID:1][CatCount:1][UID:4]
#   EventID: 0=Added 1=Modified 2=Removed
#
# Control Point command (write-with-response):
#   [Cmd:1][UID:4][AttrID:1][MaxLen:2] ...repeat attrs...
#   Cmd: 0=GetNotificationAttributes
#
# Data Source response:
#   [Cmd:1][UID:4][AttrID:1][Len:2][Data:Len] ...repeat attrs...
#
# Attribute IDs: 0=AppID 1=Title 2=Subtitle 3=Message 4=MessageSize 5=Date
# Category IDs:  0=Other 1=IncomingCall 2=MissedCall 3=Voicemail 4=Social
#                5=Schedule 6=Email 7=News 8=Health 9=Business 10=Location 11=Entertainment

import struct
from dataclasses import dataclass

APPLE_MFR_ID = 0x004C
ANCS_SERVICE_UUID = "7905f431-b5ce-4e99-a40f-4b1e122d00d0"
NOTIF_SOURCE_UUID = "9fbf120d-6301-42d9-8c58-25e699a21dbd"
CONTROL_POINT_UUID = "69d1d8f3-45e1-49a8-9821-9bbdfdaad9d9"
DATA_SOURCE_UUID = "22eac6e9-24d6-4bb5-be44-b36ace7c7bfb"

ATTR_TITLE = 1
ATTR_SUBTITLE = 2
ATTR_MESSAGE = 3

_CATEGORIES: dict[int, str] = {
    0: "Other",
    1: "Incoming Call",
    2: "Missed Call",
    3: "Voicemail",
    4: "Social",
    5: "Schedule",
    6: "Email",
    7: "News",
    8: "Health & Fitness",
    9: "Business",
    10: "Location",
    11: "Entertainment",
}


@dataclass
class NotifSource:
    uid: int
    event_id: int  # 0=Added 1=Modified 2=Removed
    flags: int
    category: str


@dataclass
class DataSource:
    uid: int
    title: str
    subtitle: str
    message: str


def parse_notification_source(data: bytearray) -> NotifSource | None:
    if len(data) < 8:
        return None
    event_id, flags, cat_id, _ = struct.unpack_from("<BBBB", data, 0)
    uid = struct.unpack_from("<I", data, 4)[0]
    return NotifSource(
        uid=uid,
        event_id=event_id,
        flags=flags,
        category=_CATEGORIES.get(cat_id, f"Cat({cat_id})"),
    )


def parse_data_source(data: bytearray) -> DataSource | None:
    if len(data) < 5 or data[0] != 0x00:
        return None
    uid = struct.unpack_from("<I", data, 1)[0]
    attrs: dict[int, str] = {}
    offset = 5
    while offset + 3 <= len(data):
        attr_id = data[offset]
        attr_len = struct.unpack_from("<H", data, offset + 1)[0]
        offset += 3
        if offset + attr_len > len(data):
            break
        attrs[attr_id] = (
            data[offset : offset + attr_len]
            .decode("utf-8", errors="replace")
            .strip("\x00")
        )
        offset += attr_len
    return DataSource(
        uid=uid,
        title=attrs.get(ATTR_TITLE, ""),
        subtitle=attrs.get(ATTR_SUBTITLE, ""),
        message=attrs.get(ATTR_MESSAGE, ""),
    )


def build_attr_request(uid: int) -> bytes:
    return struct.pack(
        "<BIBHBHBH",
        0x00, uid,
        ATTR_TITLE, 128,
        ATTR_SUBTITLE, 64,
        ATTR_MESSAGE, 256,
    )
