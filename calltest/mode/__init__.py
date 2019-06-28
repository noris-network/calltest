# Worker base class and helpers, for callout.

import anyio

from asyncari.state import SyncEvtHandler

from calltest.model import locked_links

async def wait_answered(chan):
	await chan.wait_for(lambda: chan.state == "Up")

async def wait_ringing(chan):
	await chan.wait_for(lambda: chan.state in ("Up", "Ringing"))

class DTMFError(RuntimeError):
	def __init__(self, digit):
		self.digit = digit

	def __str__(self):
		return "DTMFError(%s)" % (self.digit,)


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


class ReadDTMF(SyncEvtHandler):
	"""
	A state macine that processes incoming DTMF.
	"""
	expected = ""

	def __init__(self, *a, dtmf, **kw):
		self.dtmf = dtmf
		super().__init__(*a, **kw)

	async def on_dtmf(self, evt):
		if self.expected[0] != evt.digit:
		self.expected = self.expected[1:]
		if self.expected == "":
			await self.done()
		

class BaseWorker:
	def __init__(self, client, call):
        self.client = client
        self.call = call
    
	def repr(self):
		return "<%s:%s>" % (self.__class__.__name__, self.call.name)

	async def __call__(self):
		raise RuntimeError("You need to override '%s.__call__'" % (self.__class__.__name__,))

class BaseInWorker(BaseWorker):
	@property
	def lock(self):
		return self.call.dst.lock

class BaseOutWorker(BaseWorker):
	@property
	def lock(self):
		return self.call.src.lock

class BaseDualWorker(BaseInWorker,BaseOutWorker)
	@property
	def lock(self):
		return locked_links(self.call.src, self.call.dst)

	@asynccontextmanager
	async def work(self):
		async with self.lock:
			async with 
			yield (ic,oc)
