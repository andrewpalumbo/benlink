from __future__ import annotations
import typing as t
import asyncio
from .link import AudioLink, RfcommAudioLink
from .internal import protocol as p


class AudioConnection:
    _link: AudioLink
    _handlers: list[t.Callable[[AudioMessage], None]]

    def is_connected(self) -> bool:
        return self._link.is_connected()

    def __init__(
        self,
        link: AudioLink,
    ):
        self._link = link
        self._handlers = []

    @classmethod
    def create_rfcomm(cls, device_uuid: str, channel: int | t.Literal["auto"] = "auto") -> AudioConnection:
        return AudioConnection(
            RfcommAudioLink(device_uuid, channel)
        )

    def register_event_handler(self, handler: t.Callable[[AudioEvent], None]) -> t.Callable[[], None]:
        def on_message(msg: AudioMessage):
            if isinstance(msg, AudioEvent):
                handler(msg)
        return self._register_message_handler(on_message)

    def _register_message_handler(self, handler: t.Callable[[AudioMessage], None]) -> t.Callable[[], None]:
        def remove_handler():
            self._handlers.remove(handler)

        self._handlers.append(handler)

        return remove_handler

    async def _send_message(self, msg: AudioMessage) -> None:
        await self._link.send(audio_message_to_protocol(msg))

    async def _send_message_expect_reply(self, msg: AudioMessage, reply: t.Type[AudioMessageT]) -> AudioMessageT:
        queue: asyncio.Queue[AudioMessageT] = asyncio.Queue()

        def on_ack(msg: AudioMessage):
            if isinstance(msg, reply):
                queue.put_nowait(msg)

        remove_handler = self._register_message_handler(on_ack)

        await self._send_message(msg)

        out = await queue.get()

        remove_handler()

        return out

    async def connect(self) -> None:
        def on_msg(msg: p.AudioMessage):
            for handler in self._handlers:
                handler(audio_message_from_protocol(msg))
        await self._link.connect(on_msg)

    async def disconnect(self) -> None:
        await self._link.disconnect()

    # Audio API

    async def send_audio_data(self, sbc_data: bytes) -> None:
        # TODO: large messages should be fragmented
        await self._send_message_expect_reply(AudioData(sbc_data), AudioAck)

    async def send_audio_end(self) -> None:
        await self._send_message(AudioEnd())


class AudioData(t.NamedTuple):
    sbc_data: bytes


class AudioEnd:
    pass


class AudioAck:
    pass


class AudioError(t.NamedTuple):
    message: str


AudioEvent = AudioData | AudioEnd | AudioError

AudioMessage = AudioEvent | AudioAck

AudioMessageT = t.TypeVar("AudioMessageT", bound=AudioMessage)


def audio_message_from_protocol(proto: p.AudioMessage) -> AudioMessage:
    match proto:
        case p.AudioData(sbc_data=sbc_data):
            return AudioData(sbc_data)
        case p.AudioEnd():
            return AudioEnd()
        case p.AudioAck():
            return AudioAck()
        case p.AudioError(message=message):
            return AudioError(message)


def audio_message_to_protocol(msg: AudioMessage) -> p.AudioMessage:
    match msg:
        case AudioData(sbc_data=sbc_data):
            return p.AudioData(sbc_data)
        case AudioEnd():
            return p.AudioEnd()
        case AudioAck():
            return p.AudioAck()
        case AudioError(message=message):
            return p.AudioError(message)
