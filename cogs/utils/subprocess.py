import asyncio


async def stream_handler(self, stream):
    async for line in stream:
        await self._stream.put(line.decode())
    # stream was closed
    await self._stream.put(None)


class Subprocess:
    def __init__(self, loop):
        self._process = None
        self._stream = asyncio.Queue(loop=loop)
        self._stream_handlers = []
        self.loop = loop

    @classmethod
    async def init(cls, cmd, *args, loop=None):
        loop = loop or asyncio.get_event_loop()
        self = cls(loop)
        self._process = await asyncio.create_subprocess_exec(cmd, *args, loop=loop)
        self._stream_handlers.append(loop.create_task(stream_handler(self, self._process.stdout)))
        self._stream_handlers.append(loop.create_task(stream_handler(self, self._process.stderr)))

    def __aiter__(self):
        return self

    async def __anext__(self):
        n = await self._stream.get()
        if not n:
            list(map(asyncio.Task.cancel, self._stream_handlers))
            raise StopAsyncIteration
        return n