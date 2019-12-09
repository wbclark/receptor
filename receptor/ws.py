import logging

import asyncio
import aiohttp
import aiohttp.web

from .messages.envelope import FramedBuffer

logger = logging.getLogger(__name__)


async def watch_queue(ws, buf):
    while not ws.closed:
        try:
            msg = await asyncio.wait_for(buf.get(), 5.0)
        except asyncio.TimeoutError:
            continue
        except Exception:
            logger.exception("watch_queue: error getting data from buffer")
            continue

        try:
            await ws.send_bytes(msg)
        except Exception:
            logger.exception("watch_queue: error received trying to write")
            await buf.put(msg)
            return await ws.close()
    logger.debug("watch_queue: ws is now closed")


class WSBase:
    def __init__(self, receptor, loop):
        self.receptor = receptor
        self.loop = loop
        self.buf = FramedBuffer(loop=self.loop)
        self.remote_id = None
        self.read_task = None
        self.handle_task = None
        self.write_task = None

    def start_receiving(self, ws):
        logger.debug("starting recv")
        self.read_task = self.loop.create_task(self.receive(ws))

    async def receive(self, ws):
        try:
            async for msg in ws:
                await self.buf.put(msg.data)
        except Exception:
            logger.exception("receive")

    def register(self, ws):
        self.receptor.update_connections(ws, id_=self.remote_id)

    def unregister(self, ws):
        self.receptor.remove_connection(ws, id_=self.remote_id, loop=self.loop)
        self._cancel(self.read_task)
        self._cancel(self.handle_task)
        self._cancel(self.write_task)

    def _cancel(self, task):
        if task:
            task.cancel()

    async def hello(self, ws):
        logger.debug("sending HI")
        msg = self.receptor._say_hi().serialize()
        await ws.send_bytes(msg)

    async def start_processing(self, ws):
        logger.debug("sending routes")
        await self.receptor.send_route_advertisement()
        logger.debug("starting normal loop")
        self.handle_task = self.loop.create_task(
            self.receptor.message_handler(self.buf)
        )
        out = self.receptor.buffer_mgr.get_buffer_for_node(
            self.remote_id, self.receptor
        )
        self.write_task = self.loop.create_task(watch_queue(ws, out))
        return await self.write_task

    async def _wait_handshake(self, ws):
        logger.debug("serve: waiting for HI")
        response = await self.buf.get()  # TODO: deal with timeout
        self.remote_id = response.header["id"]
        self.register(ws)


class WSClient(WSBase):
    async def connect(self, uri):
        async with aiohttp.ClientSession().ws_connect(uri) as ws:
            try:
                self.start_receiving(ws)
                await self.hello(ws)
                await self._wait_handshake(ws)
                await self.start_processing(ws)
                logger.debug("connect: normal exit")
            except Exception:
                logger.exception("connect")
            finally:
                self.unregister(ws)
                await asyncio.sleep(5)
                logger.debug("connect: reconnecting")
                self.loop.create_task(self.connect(uri))


class WSServer(WSBase):
    async def serve(self, request):

        ws = aiohttp.web.WebSocketResponse()
        await ws.prepare(request)

        try:
            self.start_receiving(ws)
            await self._wait_handshake(ws)
            await self.hello(ws)
            await self.start_processing(ws)
        finally:
            self.unregister(ws)

    def app(self):
        app = aiohttp.web.Application()
        app.add_routes([aiohttp.web.get("/", self.serve)])
        return app