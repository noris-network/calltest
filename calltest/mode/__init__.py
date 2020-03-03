# Worker base class and helpers, for callout.

import anyio
import random
from contextlib import asynccontextmanager
from functools import partial
from ..util import attrdict
from asyncari.util import mayNotExist

from asyncari.state import DTMFHandler, SyncEvtHandler, ChannelState
from asyncari.model import Channel
from asyncari.state import SyncPlay as _SyncPlay

from calltest.model import locked_links

import logging
logger = logging.getLogger(__name__)

class IncomingCollisionError(RuntimeError):
    pass

async def wait_answered(chan_state):
    await chan_state.channel.wait_for(lambda: chan_state.channel.state == "Up")

async def wait_ringing(chan_state):
    await chan_state.channel.wait_for(lambda: chan_state.channel.state in {"Up", "Ringing", "Ring"})

class ConfigError(RuntimeError):
    pass

class WrongCallerID(ValueError):
    pass

class DTMFError(RuntimeError):
    def __init__(self, digit, dts):
        self.digit = digit
        self.dts = dts

    def __str__(self):
        return "DTMFError(%s %s)" % (self.digit,self.dts)

class SyncPlay(_SyncPlay):
    def __init__(self, base, filename):
        filename = base.client._calltest_config.asterisk.audio.play + filename
        super().__init__(base, filename)

async def start_record(state, filename, format="wav", ifExists="overwrite", **kw):
    #rec = chan_state.client._calltest_config.asterisk.audio.record
    evt = anyio.create_event()
    rec = await state.ref.record(name=filename, format=format, ifExists=ifExists, **kw)
    await rec.wait_recording()
    return rec


def random_dtmf(len=6):
    if len<8:
        res = random.sample("0124356789", k=len-1)
        res[len//2:len//2] = [res[len//2]]
    else:
        res = random.choices("0124356789", k=len)
    return "".join(res)


class ExpectDTMF(DTMFHandler, SyncEvtHandler):
    """
    A state macine that processes incoming DTMF.
    """
    expected = ""

    def __init__(self, *a, dtmf, may_repeat=False, **kw):
        self.dtmf = dtmf
        self.dtmf_pos = 0
        self.may_repeat = may_repeat
        super().__init__(*a, **kw)

    @property
    def dts(self):
        return self.dtmf[:self.dtmf_pos]+'/'+self.dtmf[self.dtmf_pos:]

    def __repr__(self):
        dts = self.dtmf[:self.dtmf_pos]+'/'+self.dtmf[self.dtmf_pos:]
        return "<%s: %s>" % (self.__class__.__name__, self.dts)

    async def on_dtmf(self, evt):
        logger.debug("DTMF: %s for %s", evt.digit,self.dts)
        
        if self.dtmf[self.dtmf_pos] != evt.digit:
            if self.may_repeat and self.dtmf_pos > 0 and self.dtmf[self.dtmf_pos-1] == evt.digit:
                return
            raise DTMFError(evt.digit, self.dts)
        self.dtmf_pos += 1
        if self.dtmf_pos == len(self.dtmf):
            await self.done()


def nr_check(dialed, cid, dialplan):
    """Verify that the incoming callerid matches the dialled number"""
    if dialed[0] != '+':
        return cid.endswith(dialed)
    if cid[0] != '+':
        if dialplan.country == '1': ## NANP
            if cid[0] == '1':
                cid = '+'+cid
            elif cid[0:3] == "011":
                cid = '+'+cid[3:]
            elif len(cid) == 7:
                cid = "+1"+dialplan.city+cid
            elif len(cid) == 10:
                cid = "+1"+cid
            else:
                return False
        else:
            if cid.startswith(dialplan.intl):
                cid = '+'+cid[len(dialplan.intl):]
            elif cid.startswith(dialplan.natl):
                cid = '+'+dialplan.country+cid[len(dialplan.natl):]
            else:
                cid = '+'+dialplan.country+dialplan.city+cid
    return dialed == cid


class BaseWorker:
    def __init__(self, client, call):
        self.client = client
        self.call = call
    
    def repr(self):
        return "<%s:%s>" % (self.__class__.__name__, self.call.name)

    async def __call__(self):
        """
        Single-shot test-once handler, propagates exceptions.
        """
        raise RuntimeError("You need to override '%s.__call__'" % (self.__class__.__name__,))

    @asynccontextmanager
    async def work(self):
        async with self.lock:
            async with Channel.new(self.client) as c:
                try:
                    cs = ChannelState(c)
                    async with cs.task:
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

    def in_call(self, delayed=False, state_factory=ChannelState):
        """
        An async context manager that handles processing of a single
        incoming call.

        Usage::

            async with worker.in_call() as in_hdl:
                await start_call_to(some.phone_no)
                in_mgr = await in_hdl.get(MyChannelStateClass)
                await in_mgr.channel.ring()
        """
        return _InCall(self, delayed, state_factory=state_factory)

    async def connect_in(self, state, handle_ringing=True, handle_answer=True):
            pre_delay = self.call.delay.pre
            if self.call.check_callerid:
                if self.call.src is None:
                    self.in_logger.error("No source set: cannot check caller ID")
                elif not nr_check(self.call.src.number, state.channel.caller['number'], self.client._calltest_config.asterisk.dialplan):
                    raise WrongCallerID(self.call.src.number, state.channel.caller['number'])
            await anyio.sleep(pre_delay)
            if handle_ringing:
                ring_delay = self.call.delay.ring
                await state.channel.ring()
                await anyio.sleep(ring_delay)
            if handle_answer:
                answer_delay = self.call.delay.answer
                await state.channel.answer()
                await wait_answered(state)
                await anyio.sleep(answer_delay)

    async def url_open(self, dest_nr, url):
        import asks
        if isinstance(url, str):
            url = {"url": url}
        method = url.get("method","GET")
        query = url.get("query","")
        body = url.get("query","")
        url = url['url']

        url = url.replace('{number}', dest_nr)
        query = query.replace('{number}', dest_nr)
        body = body.replace('{number}', dest_nr)

        self.in_logger.info("URL %s %s p=%s d=%s",method,url,query,body)
        res = await asks.request(method, url=url, path=query, data=body)
        return res
    
    async def exec_open(self, dest_nr, args):
        import trio
        args = [x.replace("{number}",dest_nr) for x in args]
        self.in_logger.info("Exec %s",args)
        await trio.run_process(args)

class _InCall:
    _in_scope = None
    _in_channel = None
    _evt = None
    _state = None

    def __init__(self, worker, delayed=False, state_factory=ChannelState):
        self.worker = worker
        self.delayed = delayed
        self.state_factory = state_factory

    async def _listen(self, evt):
        w = self.worker
        number = w.call.number or w.call.dst.number
        async with anyio.open_cancel_scope() as sc:
            self._in_scope = sc
            self.worker.in_logger.debug("Wait for call: using %s", w.call.dst.name)
            async with w.client.on_start_of(w.call.dst.name) as d:
                await evt.set()
                url = getattr(w.call,'url', None)
                if url is not None:
                    await self.worker.client.taskgroup.spawn(w.url_open, number, url)
                args = getattr(w.call,'exec', None)
                if args is not None:
                    await self.worker.client.taskgroup.spawn(w.exec_open, number, args)
                async for ic_, evt_ in d:
                    if self._in_channel is None:
                        self._in_channel = ic_['channel']
                        await self._evt.set()
                    else:
                        self.worker.in_logger.error("Duplicate incall on %s %s %s", w.call.dst.name, ic_, evt_)
                        #raise IncomingCollisionError(w.call.dst.name, ic_, evt_)

    async def __aenter__(self):
        self.worker.in_logger.debug("Enter InCall %s",self.worker.call.dst.name)
        self._evt = anyio.create_event()
        evt = anyio.create_event()
        await self.worker.client.taskgroup.spawn(self._listen, evt)
        await evt.wait()
        if self.delayed:
            return self

        await self._evt.wait()
        self._state = self.state_factory(self._in_channel)
        await self._state.start_task()
        return self._state

    @asynccontextmanager
    async def get(self, state_factory=None):
        """
        Wait for the incoming call, return the appropriate ChannelState.

        This is an async context manager because it runs the object's state
        machine in the background.
        """
        self.worker.in_logger.debug("Wait for call")
        await self._evt.wait()
        if state_factory is None:
            state_factory = self.state_factory
        ics = state_factory(self._in_channel)
        self.worker.in_logger.debug("Wait for call: %r", ics)
        async with ics.task:
            yield ics

    async def __aexit__(self, *tb):
        self.worker.in_logger.debug("Exit InCall %s",self.worker.call.dst.name)
        async with anyio.open_cancel_scope(shield=True):
            try:
                if self._state is not None:
                    await self._state.done()
                    self._state = None
                if self._in_scope is not None:
                    await self._in_scope.cancel()
                    self._in_scope = None
                if self._in_channel is not None:
                    self.worker.in_logger.debug("Hang up %r", self._in_channel)
                    with mayNotExist:
                        await self._in_channel.hangup()
            finally:
                self._in_channel = None

class BaseOutWorker(BaseWorker):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        if self.call.src is None:
            raise ConfigError("Config %s doesn't have 'src'" % (self.call.name,))
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
                        destination number or to the destination's configured number.
        :param state_factory: The ChannelState subclass to be instantiated
                              with this call. Defaults to ChannelState.

        Usage::

            async with worker.out_call() as out_mgr:
                await out_mgr.channel.wait_up()
                pass # do whatever else with it

        """
        ep = self.call.src.channel
        if dest_nr is None:
            dest_nr = self.call.number or self.call.dst.number
        if dest_nr is None:
            if '{number}' in ep:
                raise ValueError("Need a destination (for the number)")
            dest_nr=""
        else:
            ep = ep.replace('{number}', dest_nr)
        oc = None
        self.out_logger.debug("Calling %s", ep)

        try:
            src_name = self.call.src.name
        except AttributeError:
            src_name = self.call.name
        try:
            src_number = self.call.src.number
        except AttributeError:
            src_number = ""
        src_cid = "%s <%s>" % (src_name,src_number)

        try:
            vars = {'CALLERID(name)': src_name, 'CALLERID(num)': src_number,
                    'CONNECTEDLINE(name)': src_name, 'CONNECTEDLINE(num)': src_number,}
            chan_id = self.client.generate_id("C")
            oc = Channel(self.client, id=chan_id)
            ocs = state_factory(oc)
            await ocs.start_task()
            await self.client.channels.originateWithId(channelId=chan_id, endpoint=ep, app=self.client._app,
                    appArgs=[":dialed",dest_nr], variables=vars, callerId=src_cid)
            self.out_logger.debug("Call placed: %r", ocs)
            yield ocs
        finally:
            async with anyio.open_cancel_scope(shield=True):
                self.out_logger.debug("Hang up %r", oc)
                if oc is not None:
                    with mayNotExist:
                        await oc.hangup()

    async def connect_out(self, state, handle_answer=True, handle_ringing=False):
        if handle_ringing:
            ring_delay = self.call.delay.ring
            await wait_ringing(state)
            await anyio.sleep(ring_delay)
        elif handle_answer:
            answer_delay = self.call.delay.answer
            await wait_answered(state)
            await anyio.sleep(answer_delay)


class BaseDualWorker(BaseInWorker,BaseOutWorker):
    @property
    def lock(self):
        return locked_links(self.call.src, self.call.dst)

    @asynccontextmanager
    async def dual_call(self):
        async with self.in_call(delayed=True) as ic:
            async with self.out_call() as ocm:
                async with ic.get() as icm:
                    yield icm,ocm

