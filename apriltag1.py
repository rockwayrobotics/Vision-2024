#!/usr/bin/python3

import asyncio
import io
import logging
import socketserver
from http import server
import itertools
import json
import os
from pathlib import Path
import re
from threading import Condition
import signal
import sys
import time
import traceback
import weakref

from aiohttp import web, http

import robotpy_apriltag as at
import ntcore

import cv2
import numpy as np

logging.basicConfig(level=logging.DEBUG)

try:
    import libcamera
    from picamera2 import Picamera2
    from picamera2.encoders import MJPEGEncoder
    from picamera2.outputs import FileOutput
    async def run_vision(): await _run_vision()
except ImportError:
    async def run_vision():
        logging.getLogger('mock run_vision')
        await core.shutdown()

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
    logging.debug('websocket opened %s', request)

    try:
        client = Client(ws)
        gClients.add(client)
        await client.run()
    except Exception:
        logging.exception('client exception')
    finally:
        gClients.discard(client)
        logging.debug('websocket closed %s', ws)

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
        self.qout.put_nowait(msg)


    def close(self):
        self.ws.close()


gClients = set()

def send_all(*args, **kwargs):
    for c in gClients:
        c.send(*args, **kwargs)


def close_all():
    for c in gClients:
        c.close()


#-----------------------------
# The order is particular... for some reason the /ws has to come first,
# then the /, and then the static routes.  I've tried variations but
# so far this is the only one that works.  Need some digging to explain it.

@routes.get('/')
async def index(request):
    return web.FileResponse('web/index.html')
    # raise web.HTTPFound('/web/index.html')

routes.static('/', WEBDIR, show_index=True)
routes.static('/lib', WEBDIR / 'lib', show_index=True, name='static')

#-----------------------------

class output:
    running = False
    ready = None
    frame = None
    count = 0

@routes.get('/stream1.mjpeg')
async def stream1(request):
    response = web.StreamResponse(
        status=200,
        reason='OK',
        headers={'Content-Type': 'multipart/x-mixed-replace; boundary=FRAME',
            'Age': '0',
            'Cache-Control': 'no-cache, private',
            'Pragma': 'no-cache',
            }
        )
    # breakpoint()
    await response.prepare(request)

    try:
        while output.running:
            await output.ready.wait()
            output.ready.clear()
            frame = output.frame
            await response.write(b'--FRAME\r\n')
            await response.write(b'Content-Type: image/jpeg\r\n')
            await response.write(f'Content-Length: {len(frame)}\r\n\r\n'.encode('utf-8'))
            await response.write(frame)
            await response.write(b'\r\n')

    except Exception as e:
        pass
        # logging.warning(
        #     'Removed streaming client %s: %s',
        #     self.client_address, str(e))
    finally:
        try:
            await response.write_eof()
        except Exception:
            pass
        return response


#-----------------------------

async def on_shutdown(app):
    print('on shutdown')
    for ws in set(app[websockets]):
        await ws.close(code=http.WSCloseCode.GOING_AWAY, message="Server shutdown")

app.on_shutdown.append(on_shutdown)

app.add_routes(routes)

#-----------------------------

# Define the lower and upper bounds for the orange color
LOWER = np.array([115, 140, 180])
UPPER = np.array([125, 255, 255])

FONT = cv2.FONT_HERSHEY_SIMPLEX

class Processor:
    def __init__(self, det):
        self.reported = time.monotonic()
        self.count = 0
        self.missed = 0
        self.fps = 0
        self.found = False
        self.det = det


    def do_frame(self, iraw):
        ihsv = cv2.cvtColor(iraw, cv2.COLOR_RGB2HSV)
        # print(igray.shape) # 360,320 or 720,640
        # print(sum(iraw.flatten()))
        # breakpoint()
        frame = ihsv
        # print(frame.shape)
        # cv2.imwrite('ring3.png', frame)
        # sys.exit(0)

        # Create a mask using the orange color range
        mask = cv2.inRange(frame, LOWER, UPPER)

        # circles = cv2.HoughCircles(mask, cv2.HOUGH_GRADIENT, dp=1, minDist=10,
        #     param1=60, param2=20, minRadius=MIN_SIZE, maxRadius=SIZE[0])

        # if circles is not None:
        #     # print(circles)
        #     circles = list(circles[0])
        #     # circles.sort(key=lambda x: x[2])
        #     ncircles = len(circles)
        #     best = circles[0]
        #     # print(f'{ncircles} {best}      ', end='\r')
        #     cx, cy, cr = best
        #     # ctext = f'{cx!r},{cy!r},{cr!r}'
        #     ctext = f'{cx:.0f},{cy:.0f},{cr:.0f}'
        # else:
        #     ncircles = 0
        #     ctext = 'none'

        # Find contours in the mask
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        # if contours:
        #     print(len(contours))

        matches = []
        for contour in contours:
            # Fit rectangle around contour
            box = cv2.boundingRect(contour)
            x, y, w, h = box
            maxdim = max(w, h)

            # Check if the detected object is big enough
            if maxdim >= MIN_SIZE:
                matches.append((maxdim, box))

        if matches:
            matches.sort()
            _, (x, y, w, h) = matches[-1]

            # outline the object
            imgout = cv2.rectangle(iraw, (x, y), (x+w, y+h), (0, 255, 0), 2)

            # X position of ring center from camera center (right positive, left negative)
            ix = (x + w // 2) - CX
            # Y position of ring center up from bottom of camera (positive)
            iy = SIZE[1] - (y + h // 2)

            # Print the center coordinates of the circle
            # print(f"\rring: {ix:3d},{iy:3d} {ctext:10s}        ", end='')
        else:
            imgout = iraw

        # if ncircles > 0:
        #     try:
        #         imgout = cv2.circle(imgout, (int(cx), int(cy)), int(cr), (255, 0, 40), 15)
        #     except Exception as ex:
        #         # print(ex)
        #         pass

        return imgout


    def do_apriltag(self, arr, imgout):
        # img = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        img = arr[:SIZE[1],:]
        # img = arr
        tags = self.det.detect(img)
        self.count += 1
        now = time.time()
        if now - self.reported > 1:
            self.fps = self.count / (now - self.reported)
            self.reported = now
            self.count = 0

        if self.found != bool(tags):
            self.found = not self.found
            print()

        if not self.found:
            self.missed += 1
            motor = 'ON ' if nt_motor.get() else 'OFF'
            print(f'\r{motor} {self.fps:3.0f} FPS: missed {self.missed}' + ' ' * 40, end='')
            # if self.missed == 25:
            #     cv2.imwrite('fail.png', img)
            #     # breakpoint()
            #     pass

        if self.found:
            self.missed = 0
            for (i, tag) in enumerate(sorted(tags, key=lambda x: x.getDecisionMargin())):
                c = tag.getCenter()
                x = int(c.x)
                y = int(c.y)
                tid = tag.getId()
                # pose = field.getTagPose(tid)H = tag.homography
                if i == 0:
                    nt_tag_x.set(x)
                    nt_tag_y.set(y)

                hmat = '' # '[' + ', '.join(f'{x:.0f}' for x in x.getHomography()) + ']'
                margin = tag.getDecisionMargin()
                motor = 'ON ' if nt_motor.get() else 'OFF'
                print(f'\r{motor} {self.fps:3.0f} FPS: margin={margin:2.0f} @{c.x:3.0f},{c.y:3.0f} id={tid:2} {hmat}    ' % tags, end='')

                if args.nodraw:
                    cv2.circle(imgout, (x, y), 5, (40, 0, 255), -1)

                    H = tag.getHomographyMatrix()

                    # Define the corners of the tag (assuming a 2x2 tag for simplicity)
                    tc = np.array([[-1, -1, 1], [ 1, -1, 1], [ 1,  1, 1], [-1,  1, 1]])

                    # Project the corners into the image plane
                    ic = (H @ tc.T).T

                    # Normalize the points
                    ic2 = (ic[:, :2] / ic[:, 2][:, np.newaxis]).astype(np.int32)

                    # Draw the rectangle
                    for i in range(4):
                        pt1 = tuple(ic2[i % 4])
                        pt2 = tuple(ic2[(i + 1) % 4])
                        cv2.line(imgout, pt1, pt2, (210, 30, 150), 4)

                    cv2.putText(imgout, f'{tag.getId()}', tuple(ic2[1] + [-4, 0]), FONT, 1.2, (128, 255, 128), 3, cv2.LINE_AA)

            # breakpoint()

        return imgout


    async def run(self, cam):
        base = time.monotonic()
        while core.running():
            await asyncio.sleep(0.05)
            # runs every 33ms with camera module v3 at 640x480 or 1024x768
            t0 = time.monotonic()
            imain = cam.capture_array('main')
            ilores = cam.capture_array('lores')
            t1 = time.monotonic()
            out = self.do_frame(imain)
            out = self.do_apriltag(ilores, out)

            okay, buf = cv2.imencode(".jpg", out)
            if okay:
                data = io.BytesIO(buf)
                output.frame = data.getbuffer()
                output.ready.set()

            now = time.monotonic()
            if now - base >= 2.5:
                base = now
                print(f' t={now-t1:.3f}s t={now-t0:.3f}s')

        print('exiting run')


async def _run_vision():
    cam = Picamera2(args.cam)
    print(cam.sensor_modes)
    cfg = cam.create_video_configuration(
        controls=dict(
            FrameRate=args.fps,
        ),
        main=dict(
            size=SIZE,
            format="RGB888",
        ),
        lores=dict(
            size=SIZE,
            format='YUV420'
        ),
    )
    cfg['transform'] = libcamera.Transform(hflip=1, vflip=1)
    # cam.set_controls(dict(FrameRate=120.0))
    print(cfg)
    cam.configure(cfg)

    #cam2 = Picamera2(1)
    #cfg = cam2.create_video_configuration(main={"size": (1024, 768)})
    #cfg['transform'] = libcamera.Transform(vflip=1)
    #cam2.configure(cfg)

    field = at.loadAprilTagLayoutField(at.AprilTagField.k2024Crescendo)
    det = at.AprilTagDetector()
    det.addFamily('tag36h11', bitsCorrected=0)
    cfg = det.getConfig()
    cfg.quadDecimate = args.dec
    cfg.numThreads = args.threads
    cfg.decodeSharpening = 0.25 # margin jumps a lot with 1.0
    # cfg.quadSigma = 0.8
    det.setConfig(cfg)

    output.ready = asyncio.Event()
    output.running = True
    # global output1
    # output1 = StreamingOutput()
    # cam.start_recording(MJPEGEncoder(), FileOutput(output1))
    cam.start()

    # global output2
    # output2 = StreamingOutput()
    #cam2.start_recording(MJPEGEncoder(), FileOutput(output2))
    # address = ('', 8000)
    # server = StreamingServer(address, StreamingHandler)
    # sw = asyncio.to_thread(server.serve_forever)

    try:
        p = Processor(det)
        # await asyncio.gather(sw, p.run(cam))
        await p.run(cam)
    # except KeyboardInterrupt:
    #     pass
    except Exception:
        traceback.print_exc()
    finally:
        print('shutting down')
        # server.shutdown()
        # await asyncio.sleep(0.6)


#-----------------------------

class Core:
    @property
    def running(self):
        not self._shutdown.is_set()

    def shutdown(self):
        return self._shutdown.wait()

    async def shut_down(self):
        try:
            self._shutdown.set()
            close_all()
            await self.runner.cleanup()
        except Exception:
            logging.exception('shutdown')
        finally:
            tasks = asyncio.all_tasks()
            await asyncio.sleep(0.1)
            if len(tasks) > 1:
                logging.debug('tasks (%s): %r', len(tasks), tasks)

    def handle_sig(self, *_sig):
        print('terminate!')

        output.running = False
        output.ready.set()

        asyncio.create_task(self.shut_down())


    async def _run(self):
        self.loop = asyncio.get_running_loop()
        self._shutdown = asyncio.Event()

        output.ready = asyncio.Event()
        for sig in [signal.SIGINT, signal.SIGTERM]:
            self.loop.add_signal_handler(sig, self.handle_sig)
            print('installed handler for', sig)

        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, '', 8000)
        await site.start()
        print('Server started at http://localhost:8000')

        try:
            await run_vision()
        finally:
            await self.runner.cleanup()


    def run(self):
        asyncio.run(self._run())


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('-d', '--debug', action='store_true')
    parser.add_argument('--nodraw', action='store_false')
    parser.add_argument('-c', '--cam', type=int, default=0)
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('-r', '--res', default='1024x768')
    parser.add_argument('--dec', type=int, default=2)
    parser.add_argument('--threads', type=int, default=4)
    parser.add_argument('--fps', type=float, default=60.0)
    parser.add_argument('--time', type=float, default=10.0)
    parser.add_argument('--team', type=int, default=8089)

    args = parser.parse_args()
    SIZE = tuple(int(x) for x in args.res.split('x'))
    MIN_SIZE = int(SIZE[0] * 0.05)

    CX = SIZE[0] // 2
    CY = SIZE[1] // 2
    CAL = np.array([660, 0, CX, 0, 660, CY, 0, 0, 1], np.float32).reshape((3, 3))

    # app.cleanup_ctx.append(run_main)

    NT = ntcore.NetworkTableInstance.getDefault()
    NT.setServerTeam(8089)
    NT.startClient4('fire1')

    vis_serial = NT.getStringTopic('/Vision/serial').publishEx('string', json.dumps(dict(persistent=True)))
    try:
        sn = re.search(r'^Serial\s*:\s*(.*)$', open('/proc/cpuinfo').read(), re.MULTILINE).group(1)
    except:
        sn = '?'
    vis_serial.set(sn)

    nt_running = NT.getBooleanTopic('/Vision/running').publish()
    nt_running.set(True)
    # breakpoint()
    nt_tag_x = NT.getIntegerTopic('/Vision/tag-x').publish()
    nt_tag_x.set(0)
    nt_tag_y = NT.getIntegerTopic('/Vision/tag-y').publish()
    nt_tag_y.set(0)
    nt_motor = NT.getBooleanTopic('/Vision/motor').subscribe(False)

    core = Core()
    try:
        core.run()
        # web.run_app(app)
    except KeyboardInterrupt:
        pass
    finally:
        nt_running.set(False)
