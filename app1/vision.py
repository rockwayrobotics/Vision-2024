import asyncio
import io
import itertools
import json
import logging
import os
from pathlib import Path
import re
import signal
import sys
import threading
import time
import traceback
import weakref

import robotpy_apriltag as at

import cv2
import numpy as np

from .utils import log_uncaught
from .net_tables import NT

logging.getLogger('picamera2').setLevel(logging.INFO)

vlog = logging.getLogger('vision')

try:
    import libcamera
    from picamera2 import Picamera2
    from picamera2.encoders import MJPEGEncoder
    from picamera2.outputs import FileOutput
except ImportError:
    pass

# This is NOT how anyone should do this. Just a hack for a quick "singleton".
class output:
    running = False
    ready = None
    frame = None
    count = 0


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
        # vlog.warning(
        #     'Removed streaming client %s: %s',
        #     self.client_address, str(e))
    finally:
        try:
            await response.write_eof()
        except Exception:
            pass
        return response


#-----------------------------

# Define the lower and upper bounds for the orange color
LOWER = np.array([115, 140, 180])
UPPER = np.array([125, 255, 255])

FONT = cv2.FONT_HERSHEY_SIMPLEX

class Processor:
    def __init__(self, shutdown, det, sender, loop):
        self.shutdown = shutdown
        self._sender = sender
        self.loop = loop
        self.det = det
        self.log = logging.getLogger('proc')

        self.reported = time.monotonic()
        self.count = 0
        self.missed = 0
        self.found = False
        self.dist1 = None
        self.beam1 = None

    def send(self, msg, **kwargs):
        def _send():
            self._sender(msg, **kwargs)
        self.loop.call_soon_threadsafe(_send)


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
            elapsed = now - self.reported
            self.send('fps', cam=args.cam, t=elapsed, n=self.count) # raw info for FPS or period
            self.reported = now
            self.count = 0

        if self.found != bool(tags):
            self.found = not self.found
            # print()

        if not self.found:
            self.missed += 1
            motor = 'ON ' if NT.motor.get() else 'OFF'
            # print(f'\r{motor} missed {self.missed}' + ' ' * 40, end='')
            # if self.missed == 25:
            #     cv2.imwrite('fail.png', img)
            #     # breakpoint()
            #     pass
            NT.tag_x.set(SIZE[0]//2)
            NT.tag_y.set(SIZE[1]//2)
        else:
            self.missed = 0
            for (i, tag) in enumerate(sorted(tags, key=lambda x: x.getDecisionMargin())):
                c = tag.getCenter()
                x = int(c.x)
                y = int(c.y)
                tid = tag.getId()
                # pose = field.getTagPose(tid)H = tag.homography
                if i == 0:
                    NT.tag_x.set(x)
                    NT.tag_y.set(y)

                hmat = '' # '[' + ', '.join(f'{x:.0f}' for x in x.getHomography()) + ']'
                margin = tag.getDecisionMargin()
                motor = 'ON ' if NT.motor.get() else 'OFF'
                print(f'\r{motor} margin={margin:2.0f} @{c.x:3.0f},{c.y:3.0f} id={tid:2} {hmat}    ' % tags, end='')

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


    def run(self, cam):
        base = time.monotonic()
        done = self.shutdown.is_set # local var for faster access
        while not done():
            # time.sleep(0.005)
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
                self.loop.call_soon_threadsafe(output.ready.set)

            x = NT.dist1.get()
            if x != self.dist1:
                self.dist1 = x
                # self.log.debug('dist1 now %s', x)
                self.send('dist1', data=x)

            x = NT.beam1.get()
            if x != self.beam1:
                self.beam1 = x
                self.send('beam1', data=x)

            now = time.monotonic()
            if now - base >= 2.5:
                base = now
                print(f' t={now-t1:.3f}s t={now-t0:.3f}s')

        vlog.debug('exiting run')


def run_vision(shutdown, sender, loop):
    cam = Picamera2(args.cam)
    vlog.debug('modes: %s', cam.sensor_modes)
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
        p = Processor(shutdown, det, sender, loop)
        p.run(cam)
    except Exception:
        traceback.print_exc()
    finally:
        cam.stop()

# Install mock function when not on host with the camera stuff installed.
try:
    libcamera
except NameError:
    def run_vision(shutdown, *_):
        while not shutdown.is_set():
            time.sleep(1)


async def run(_args, sender):
    # Globals are a poor way to do this...
    global args
    args = _args

    # Globals are a poor way to do this...
    global SIZE, MIN_SIZE
    SIZE = tuple(int(x) for x in args.res.split('x'))
    MIN_SIZE = int(SIZE[0] * 0.05)

    # Globals are a poor way to do this...
    global CX, CY, CAL
    CX = SIZE[0] // 2
    CY = SIZE[1] // 2
    CAL = np.array([660, 0, CX, 0, 660, CY, 0, 0, 1], np.float32).reshape((3, 3))

    try:
        shutdown = threading.Event()
        loop = asyncio.get_running_loop()
        await asyncio.to_thread(run_vision, shutdown, sender, loop)
    except asyncio.CancelledError:
        vlog.debug('cancelled')
    except Exception as ex:
        vlog.exception('run_vision failed')
    finally:
        shutdown.set()


# EOF
