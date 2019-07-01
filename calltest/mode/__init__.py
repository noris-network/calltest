# Worker base class and helpers, for callout.

import anyio
import random
from contextlib import asynccontextmanager

from asyncari.state import DTMFHandler, SyncEvtHandler, ChannelState
from asyncari.model import Channel

from calltest.model import locked_links

import logging

from asks.errors import BadStatus
NOT_FOUND = 404

async def wait_answered(chan_state):
    await chan_state.channel.wait_for(lambda: chan_state.channel.state == "Up")

async def wait_ringing(chan_state):
    await chan_state.channel.wait_for(lambda: chan_state.channel.state in ("Up", "Ringing"))

class DTMFError(RuntimeError):
    def __init__(self, digit, dts):
        self.digit = digit
        self.dts = dts

    def __str__(self):
        return "DTMFError(%s: %s %s)" % (self.total,self.dts)


class BaseCall:
    def __init__(self, worker):
        self.worker = worker
        self.client = self.worker.client
        self.call = self.worker.call
    
    def __repr__(self):
        return "<%s:%s>" % (self.__class__.__name__, self.worker.call.name)



class BaseInCall(BaseCall):
    async def listen(self):
        try:
            yield self
        finally:
            del self.client.in_chan


class BaseOutCall(BaseCall):
    @asynccontextmanager
    async def call(self):
        ch_id = self.client.generate_id("C")
        ch_dest = self.call.src.channel.format(nr=self.call.dst.number)
        ch = await self.client.channels.originate(channelId=ch_id, endpoint=ch_dest, app=self.client._app, appArgs=[":dialed", self.call.name], **kw)
        try:
            yield ch
        finally:
            async with anyio.open_cancel_scope(shield=True):
                await ch.hang_up()


def random_dtmf(len=6):
    res = random.sample("0124356789", k=5)
    res[len//2:len//2] = [res[len//2]]
    return "".join(res)


class ExpectDTMF(DTMFHandler, SyncEvtHandler):
    """
    A state macine that processes incoming DTMF.
    """
    expected = ""

    def __init__(self, *a, dtmf, **kw):
        self.dtmf = dtmf
        self.dtmf_pos = 0
        super().__init__(*a, **kw)

    @property
    def dts(self):
        return self.dtmf[:self.dtmf_pos]+'/'+self.dtmf[self.dtmf_pos:]

    def __repr__(self):
        dts = self.dtmf[:self.dtmf_pos]+'/'+self.dtmf[self.dtmf_pos:]
        return "<%s: %s>" % (self.__class__.__name__, self.dts)

    async def on_dtmf(self, evt):
        if self.dtmf[self.dtmf_pos] != evt.digit:
            raise DTMFError(evt.digit, self.dts)
        self.dtmf_pos += 1
        if self.dtmf_pos == len(self.dtmf):
            await self.done()


class BaseWorker:
    def __init__(self, client, call):
        self.client = client
        self.call = call
    
    def repr(self):
        return "<%s:%s>" % (self.__class__.__name__, self.call.name)

    async def __call__(self):
        raise RuntimeError("You need to override '%s.__call__'" % (self.__class__.__name__,))

    @asynccontextmanager
    async def work(self):
        async with self.lock:
            async with Channel.new(self.client) as c:
                try:
                    cs = ChannelState(c)
                    async with cs:
                        yield cs
                finally:
                    async with anyio.open_cancel_scope(shield=True):
                        await c.hang_up()

class BaseInWorker(BaseWorker):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.in_logger = logging.getLogger("%s.in.%s" % (__name__, self.call.dst.name))

    @property
    def lock(self):
        return self.call.dst.lock

    def in_call(self):
        """
        An async context manager that handles processing of a single
        incoming call.

        Usage::

            async with worker.in_call() as in_hdl:
                await start_call_to(some.phone_no)
                in_mgr = await in_hdl.get(MyChannelStateClass)
                await in_mgr.channel.ring()
        """
        return _InCall(self)

class _InCall:
    _in_scope = None
    _in_channel = None
    _evt = None

    def __init__(self, worker):
        self.worker = worker

    async def _listen(self, evt):
        w = self.worker
        async with anyio.open_cancel_scope() as sc:
            self._in_scope = sc
            self.worker.in_logger.debug("Wait for call: using %s", w.call.dst.name)
            async with w.client.on_start_of(w.call.dst.name) as d:
                await evt.set()
                async for ic_, evt_ in d:
                    if self._in_channel is None:
                        self._in_channel = ic_['channel']
                        await self._evt.set()
                    else:
                        raise RuntimeError("Another incoming call", w.call.dst.name)

    async def __aenter__(self):
        self.worker.in_logger.debug("Wait for call: starting")
        self._evt = anyio.create_event()
        evt = anyio.create_event()
        await self.worker.client.taskgroup.spawn(self._listen, evt)
        await evt.wait()
        self.worker.in_logger.debug("Wait for call: registered")
        return self

    @asynccontextmanager
    async def get(self, state_factory=ChannelState):
        """
        Wait for the incoming call, return the appropriate ChannelState.

        This is an async context manager because it runs the object's state
        machine in the background.
        """
        self.worker.in_logger.debug("Wait for call")
        await self._evt.wait()
        ics = state_factory(self._in_channel)
        self.worker.in_logger.debug("Wait for call: %r", ics)
        async with ics:
            yield ics

    async def __aexit__(self, *tb):
        self.worker.in_logger.debug("Wait for call: end")
        async with anyio.open_cancel_scope(shield=True):
            if self._in_scope is not None:
                await self._in_scope.cancel()
                self._in_scope = None
            if self._in_channel is not None:
                self.worker.in_logger.debug("Hang up %r", self._in_channel)
                try:
                    await self._in_channel.hangup()
                except BadStatus as e:
                    if e.status_code != NOT_FOUND:
                        raise
                finally:
                    self._in_channel = None

class BaseOutWorker(BaseWorker):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.out_logger = logging.getLogger("%s.out.%s" % (__name__, self.call.src.name))

    @property
    def lock(self):
        return self.call.src.lock

    @asynccontextmanager
    async def out_call(self, dest_nr=None, state_factory=ChannelState):
        """
        An async context manager that handles processing of a single
        outgoing call.

        :param dest_nr: Number to call. Optional, defaults to the call's
                        destination number.
        :param state_factory: The ChannelState subclass to be instantiated
                              with this call. Defaults to ChannelState.

        Usage::

            async with worker.out_call() as out_mgr:
                await out_mgr.channel.wait_up()
                pass # do whatever else with it

        """
        if dest_nr is None:
            dest_nr = self.call.dst.number
        ep = self.call.src.channel.replace('{nr}', dest_nr)
        oc = None
        self.out_logger.debug("Calling %s", ep)

        try:
            oc = await self.client.channels.originate(endpoint=ep, app=self.client._app, appArgs=[":dialed",dest_nr])
            ocs = state_factory(oc)
            async with ocs:
                self.out_logger.debug("Call placed: %r", ocs)
                yield ocs
        finally:
            async with anyio.open_cancel_scope(shield=True):
                self.out_logger.debug("Hang up %r", oc)
                if oc is not None:
                    try:
                        await oc.hangup()
                    except BadStatus as e:
                        if e.status_code != NOT_FOUND:
                            raise


class BaseDualWorker(BaseInWorker,BaseOutWorker):
    @property
    def lock(self):
        return locked_links(self.call.src, self.call.dst)

    @asynccontextmanager
    async def dual_call(self):
        async with self.in_call() as ic:
            async with self.out_call() as ocm:
                async with ic.get() as icm:
                    yield icm,ocm

