import asyncio
import io
import itertools
import json
import logging
from pathlib import Path
import weakref

from aiohttp import web, http

from . import vision
from .utils import log_uncaught

weblog = logging.getLogger('web')
WEBDIR = Path(__file__).parent / 'web'

# middleware to turn off caching for things in the 'static' folder,
# specifically those covered by the name='static' route, as opposed
# to others that may be created to bypass that e.g. third-party packages.
@web.middleware
async def cache_control(request: web.Request, handler):
    response: web.Response = await handler(request)
    resource_name = request.match_info.route.name
    if resource_name and resource_name.startswith('static'):
        response.headers.setdefault('Cache-Control', 'no-cache')
    return response

app = web.Application(middlewares=[cache_control])

routes = web.RouteTableDef()
#

#-----------------------------

websockets = web.AppKey('websockets', weakref.WeakSet)
app[websockets] = weakref.WeakSet()

@routes.get('/ws')
async def websocket_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    request.app[websockets].add(ws)
    weblog.debug('websocket opened %s', request)

    try:
        client = Client(ws)
        gClients.add(client)
        await client.run()
    except Exception:
        weblog.exception('client exception')
    finally:
        gClients.discard(client)
        weblog.debug('websocket closed %s', ws)

    return ws


class Client:
    _id = itertools.count(0)

    def __init__(self, ws):
        self.ws = ws
        self.id = next(Client._id)
        self.log = logging.getLogger(f'c.{self.id}')
        self.qout = asyncio.Queue()
        self.send_task = None

    async def run(self):
        try:
            await self.run_receiving()
        finally:
            if self.send_task:
                self.send_task.cancel()
                await self.send_task

    async def run_receiving(self):
        async for msg in self.ws:
            if msg.type == web.WSMsgType.TEXT:
                self.do_text(msg)
            elif msg.type == web.WSMsgType.ERROR:
                self.log.error('ws connection closed with exception %s',
                      ws.exception())
            elif msg.type == web.WSMsgType.BINARY:
                self.log.debug('<-- binary, %s bytes', len(msg.data))
            else:
                self.log.warning('<== %r', msg)


    async def run_sending(self):
        while True:
            msg = await self.qout.get()
            try:
                await self.ws.send_json(msg)
            except Exception:
                self.log.exception('ws send error')


    def do_text(self, msg):
        self.log.debug('<-- %s', msg)
        msg = msg.json()
        try:
            handler = getattr(self, '_msg_' + msg['_t'])
        except KeyError:
            self.log.error('bad msg %r', msg)
        except AttributeError:
            self.log.error('no handler for %s', msg['_t'])
        else:
            try:
                handler(msg)
            except Exception:
                self.log.exception('error handling %r', msg['_t'])


    def _msg_auth(self, msg):
        self.log.info('uuid %s', msg['uuid'])
        if not self.send_task:
            self.send_task = asyncio.create_task(self.run_sending())

        self.send('meta', foo='bar', ver='0.1.1')

        self.send_hash()


    def send_hash(self):
        # Calculate and send hash of timestamps of sorted list of all files
        # in the web folder, to let the UI know if files have changed.
        import hashlib, struct
        data = b''.join(struct.pack('L', int(x.stat().st_mtime)) for x in sorted(WEBDIR.glob('**/*')))
        self.send('hash', data=hashlib.md5(data).hexdigest())


    def send(self, msg, **kwargs):
        self.log.debug('sending: %r %r', msg, kwargs)
        msg = dict(_t=msg)
        msg.update(kwargs)
        self._send(msg)


    def _send(self, msg):
        self.qout.put_nowait(msg)


    async def close(self):
        await self.ws.close()


gClients = set()

def send_all(msg, **kwargs):
    # logging.debug('send_all: %r %r', msg, kwargs)
    msg = dict(_t=msg)
    msg.update(kwargs)
    for c in gClients:
        c._send(msg)


async def close_all():
    for c in gClients:
        await c.close()


#-----------------------------
# The order is particular... for some reason the /ws has to come first,
# then the /, and then the static routes.  I've tried variations but
# so far this is the only one that works.  Need some digging to explain it.

@routes.get('/')
async def index(request):
    return web.FileResponse(WEBDIR / 'index.html')
    # raise web.HTTPFound('/web/index.html')

routes.static('/', WEBDIR, show_index=True)
routes.static('/lib', WEBDIR / 'lib', show_index=True, name='static')

#-----------------------------

@log_uncaught
async def on_shutdown(app):
    weblog.debug('on shutdown')
    for ws in set(app[websockets]):
        await ws.close(code=http.WSCloseCode.GOING_AWAY, message="Server shutdown")

app.on_shutdown.append(on_shutdown)

app.add_routes(routes)
app.add_routes([
    web.get('/stream1.mjpeg', vision.stream1),
    ])


class Web:
    def __init__(self):
        self.log = logging.getLogger('web')

    async def start(self, args):
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, '', args.port)
        await site.start()

        self.log.info(f'server started at http://:{args.port}')


    async def stop(self):
        try:
            await self.runner.cleanup()
        except Exception:
            pass


async def start(args):
    weblog.info(f'web dir is {WEBDIR}')
    web = Web()
    await web.start(args)
    return web
