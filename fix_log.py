#!/bin/env python3
from __future__ import annotations
import csv
import sys
import typing as t


class HeaderDecodeError(ValueError):
    def __init__(self, message: str, header: bytes):
        super().__init__(message)
        self.header = header


class BodyDecodeError(ValueError):
    def __init__(self, message_type_str: str, message: str, body: bytes):
        super().__init__(message)
        self.type_str = message_type_str
        self.body = body


def message_type_str(msg: HTMessage):
    match msg:
        case RadioReceivedAprsChunk():
            return "radio_received_aprs_chunk"
        case ChannelInfoRequest():
            return "channel_info_request"
        case ChannelInfoResponse():
            return "channel_info_response"
        case SetDigitalMessageUpdates():
            return "set_digital_message_updates"
        case UnknownMessage():
            return "unknown"


def message_type_id(msg: HTMessage):
    match msg:
        case RadioReceivedAprsChunk():
            return (0x00, 0x09)
        case ChannelInfoRequest():
            return (0x00, 0x0D)
        case ChannelInfoResponse():
            return (0x00, 0x0E)
        case SetDigitalMessageUpdates():
            return (0x00, 0x06)
        case UnknownMessage():
            return msg.message_type_id


class UnknownMessage(t.NamedTuple):
    message_type_id: t.Tuple[int, int]
    data: bytes

    @staticmethod
    def from_message_body(body: bytes, message_type_id: t.Tuple[int, int]) -> UnknownMessage:
        return UnknownMessage(
            message_type_id=message_type_id,
            data=body,
        )

    def to_message_body(self) -> bytes:
        return self.data

    def __str__(self) -> str:
        return f"UnknownMessage(message_type_id=[{','.join(hex(i) for i in self.message_type_id)}], data={self.data})"


class SetDigitalMessageUpdates(t.NamedTuple):
    enabled: bool

    @staticmethod
    def from_message_body(body: bytes) -> SetDigitalMessageUpdates:
        if len(body) != 1:
            raise BodyDecodeError(
                "set_digital_message_updates",
                f"Expected body length 1, got {len(body)}",
                body
            )
        if body[0] not in (0x00, 0x01):
            raise BodyDecodeError(
                "set_messaging_reports",
                f"Expected body[0] to be 0x00 or 0x01, got {body[0]}",
                body
            )
        return SetDigitalMessageUpdates(enabled=body[0] == 0x01)

    def to_message_body(self) -> bytes:
        return bytes([0x01 if self.enabled else 0x00])


class ChannelInfoRequest(t.NamedTuple):
    channel_id: int

    @staticmethod
    def from_message_body(body: bytes) -> ChannelInfoRequest:
        if len(body) != 1:
            raise BodyDecodeError(
                "channel_info_request",
                f"Expected body length 1, got {len(body)}",
                body
            )
        return ChannelInfoRequest(body[0])

    def to_message_body(self) -> bytes:
        return bytes([self.channel_id])


class ChannelInfoResponse(t.NamedTuple):
    action_id: int
    channel_id: int
    channel_data: bytes

    @staticmethod
    def from_message_body(body: bytes) -> ChannelInfoResponse:
        if len(body) < 2:
            raise BodyDecodeError(
                "channel_info_response",
                f"Expected least 1 byte, got {len(body)}",
                body
            )
        (
            action_id,
            channel_id,
            *channel_data
        ) = body

        return ChannelInfoResponse(
            action_id=action_id,
            channel_id=channel_id,
            channel_data=bytes(channel_data),
        )

    def to_message_body(self) -> bytes:
        return bytes([0x00, self.channel_id]) + self.channel_data


class RadioReceivedAprsChunk(t.NamedTuple):
    chunk_data: bytes
    chunk_num: int
    is_final_chunk: bool
    decode_status: t.Literal["ok", "error"]

    @staticmethod
    def from_message_body(body: bytes) -> RadioReceivedAprsChunk:
        if len(body) < 2:
            raise BodyDecodeError(
                "radio_received_aprs_chunk",
                f"Expected least 2 bytes, got {len(body)}",
                body
            )

        aprs_header = body[:2]
        aprs_body = body[2:]

        (
            decode_status_id,
            chunk_info,
        ) = aprs_header

        match decode_status_id:
            case 0x01:
                decode_status = "error"
            case 0x02:
                decode_status = "ok"
            case _:
                raise BodyDecodeError(
                    "radio_received_aprs_chunk",
                    f"Unknown decode status: {decode_status_id}",
                    body
                )

        is_final_part = chunk_info & 0x80 == 0x80

        chunk_num = chunk_info & 0x7f

        return RadioReceivedAprsChunk(
            chunk_data=aprs_body,
            chunk_num=chunk_num,
            decode_status=decode_status,
            is_final_chunk=is_final_part,
        )

    def to_message_body(self) -> bytes:
        chunk_info = self.chunk_num | (0x80 if self.is_final_chunk else 0x00)
        match self.decode_status:
            case "error":
                decode_status_id = 0x01
            case "ok":
                decode_status_id = 0x02
        return bytes([decode_status_id, chunk_info]) + self.chunk_data


HTMessage = t.Union[
    RadioReceivedAprsChunk,
    ChannelInfoRequest,
    ChannelInfoResponse,
    SetDigitalMessageUpdates,
    UnknownMessage,
]


def encode_ht_message(msg: HTMessage) -> bytes:
    body = msg.to_message_body()

    header = bytes([
        0xff,  # start_flag
        0x01,  # constant_1
        0x00,  # reserved_1
        len(body),  # message_length
        0x00,  # reserved_2
        0x02,  # constant_2
        *message_type_id(msg),  # message_type_id
    ])

    return header + body


def decode_ht_message(buffer: bytes) -> t.Tuple[HTMessage | None, bytes]:
    if len(buffer) < 8:
        return (None, buffer)

    header = buffer[:8]
    buffer = buffer[8:]

    (
        start_flag,
        constant_1,
        reserved_1,
        body_length,
        reserved_2,
        constant_2,
        message_type_id_1,
        message_type_id_2,
    ) = header

    message_type_id = (message_type_id_1, message_type_id_2)

    if start_flag != 0xff:
        raise HeaderDecodeError(
            f"Expected byte[0](start_flag) = 0xff, got {start_flag}", buffer
        )

    if constant_1 != 0x01:
        raise HeaderDecodeError(
            f"Expected byte[1](constant_1) = 0x01, got {constant_1}", buffer
        )

    if reserved_1 != 0x00:
        raise HeaderDecodeError(
            f"Expected byte[2](reserved_1) = 0x00, got {reserved_1}", buffer
        )

    if reserved_2 != 0x00:
        raise HeaderDecodeError(
            f"Expected byte[4](reserved_2) = 0x00, got {reserved_2}", buffer
        )

    if constant_2 != 0x02:
        raise HeaderDecodeError(
            f"Expected byte[5](constant_2) = 0x02, got {constant_2}", buffer
        )

    if body_length > len(buffer):
        return (None, buffer)

    body = buffer[:body_length]
    buffer = buffer[body_length:]

    match message_type_id:
        case (0x00, 0x09):
            return (
                RadioReceivedAprsChunk.from_message_body(body),
                buffer
            )
        case (0x00, 0x0D):
            return (
                ChannelInfoRequest.from_message_body(body),
                buffer
            )
        case (0x80, 0x0D):
            return (
                ChannelInfoResponse.from_message_body(body),
                buffer
            )
        case (0x00, 0x06):
            return (
                SetDigitalMessageUpdates.from_message_body(body),
                buffer
            )
        case _:
            return (
                UnknownMessage.from_message_body(
                    body, message_type_id
                ),
                buffer
            )


class HTMessageStream:
    _buffer: bytes

    def __init__(self):
        self._buffer = b""

    def feed(self, data: bytes) -> t.List[HTMessage]:
        self._buffer += data

        messages: t.List[HTMessage] = []

        while len(self._buffer) >= 8:
            if self._buffer[0] != 0xff:
                print(
                    f"Expected buffer[0] = 0xff, got {self._buffer}",
                    file=sys.stderr
                )
                idx = self._buffer.find(b"\xff")
                if idx == -1:
                    self._buffer = b""
                else:
                    self._buffer = self._buffer[idx:]
                continue

            msg, self._buffer = decode_ht_message(self._buffer)

            if msg is None:
                break

            messages.append(msg)

        return messages


def to_text(cmd: bytes):
    return "".join([chr(i) if i >= 32 and i <= 126 else "." for i in cmd])


reader = csv.DictReader(sys.stdin)

output_header = ["id", "dir", "msg_type", "msg"]

writer = csv.DictWriter(sys.stdout, fieldnames=output_header)
writer.writeheader()

phone_to_radio = HTMessageStream()
radio_to_phone = HTMessageStream()

for frame in reader:
    data = bytes.fromhex(frame["data"].replace(":", ""))

    try:
        match frame["dir"]:
            case "phone->radio":
                messages = phone_to_radio.feed(data)
            case "radio->phone":
                messages = radio_to_phone.feed(data)
            case _:
                raise ValueError(f"Unknown direction: {frame['dir']}")
    except ValueError as e:
        print(data, file=sys.stderr)
        print(f"Error processing frame {frame['id']}: {e}", file=sys.stderr)
        break

    for message in messages:
        writer.writerow({
            "id": frame["id"],
            "dir": frame["dir"],
            "msg_type": message_type_str(message),
            "msg": str(message)
        })
