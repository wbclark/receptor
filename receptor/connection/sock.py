import asyncio
import logging

from .base import Transport, log_ssl_detail

logger = logging.getLogger(__name__)


class RawSocket(Transport):
    def __init__(self, reader, writer, chunk_size=2 ** 16):
        self.reader = reader
        self.writer = writer
        self._closed = False
        self.chunk_size = chunk_size

    async def __anext__(self):
        bytes_ = await self.reader.read(self.chunk_size)
        if not bytes_:
            self.close()
        return bytes_

    @property
    def closed(self):
        return self._closed

    def close(self):
        self._closed = True
        self.writer.close()

    async def send(self, q):
        async for chunk in q:
            self.writer.write(chunk)
        await self.writer.drain()

    def _diagnostics(self):
        t = self.writer._transport.get_extra_info
        addr, port = t("peername", (None, None))
        return {
            "address": addr,
            "port": port,
            "compression": t("compression"),
            "cipher": t("cipher"),
            "peercert": t("peercert"),
            "sslcontext": t("sslcontext"),
            "closed": self.closed,
            "chunk_size": self.chunk_size,
        }


async def connect(host, port, factory, loop=None, ssl=None, reconnect=True):
    if not loop:
        loop = asyncio.get_event_loop()

    worker = factory()
    try:
        r, w = await asyncio.open_connection(host, port, loop=loop, ssl=ssl)
        log_ssl_detail(w._transport)
        t = RawSocket(r, w)
        await worker.client(t)
    except Exception as ex:
        logger.info(f"sock.connect: connection failed, {str(ex)}")
        if not reconnect:
            return False
    finally:
        if reconnect:
            await asyncio.sleep(5)
            logger.debug("sock.connect: reconnection")
            loop.create_task(connect(host, port, factory, loop))
    return True


async def serve(reader, writer, factory):
    log_ssl_detail(writer._transport)
    t = RawSocket(reader, writer)
    await factory().server(t)
