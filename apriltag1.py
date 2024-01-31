#!/usr/bin/python3

import asyncio
import io
import logging
import socketserver
from http import server
from threading import Condition
import sys
import time
import traceback

import robotpy_apriltag as at

import cv2
import numpy as np

import libcamera
from picamera2 import Picamera2
from picamera2.encoders import MJPEGEncoder
from picamera2.outputs import FileOutput

PAGE = """\
<html>
<head>
<title>Pi5 dual cams</title>
</head>
<body>
<div style="display: flex; width: 98%">
    <div style="width: 45%">
        <h1>Cam1</h1>
        <img src="stream1.mjpg" width="100%"/>
    </div>
    <div style="width: 45%">
    <h1>Cam2</h1>
    <img src="stream2.mjpg" width="100%" />
    </div>
</div>
</body>
</html>
"""


class StreamingOutput(io.BufferedIOBase):
    def __init__(self):
        self.frame = None
        self.condition = Condition()

    def write(self, buf):
        with self.condition:
            self.frame = buf
            self.condition.notify_all()


class StreamingHandler(server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            self.send_response(301)
            self.send_header('Location', '/index.html')
            self.end_headers()
        elif self.path == '/index.html':
            content = PAGE.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.send_header('Content-Length', len(content))
            self.end_headers()
            self.wfile.write(content)
        elif self.path == '/stream1.mjpg':
            self.send_response(200)
            self.send_header('Age', 0)
            self.send_header('Cache-Control', 'no-cache, private')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=FRAME')
            self.end_headers()
            try:
                while True:
                    with output1.condition:
                        output1.condition.wait()
                        frame = output1.frame
                    self.wfile.write(b'--FRAME\r\n')
                    self.send_header('Content-Type', 'image/jpeg')
                    self.send_header('Content-Length', len(frame))
                    self.end_headers()
                    self.wfile.write(frame)
                    self.wfile.write(b'\r\n')
            except Exception as e:
                logging.warning(
                    'Removed streaming client %s: %s',
                    self.client_address, str(e))
        elif self.path == '/stream2.mjpg':
            self.send_response(200)
            self.send_header('Age', 0)
            self.send_header('Cache-Control', 'no-cache, private')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=FRAME')
            self.end_headers()
            try:
                while True:
                    with output2.condition:
                        output2.condition.wait()
                        frame = output2.frame
                    self.wfile.write(b'--FRAME\r\n')
                    self.send_header('Content-Type', 'image/jpeg')
                    self.send_header('Content-Length', len(frame))
                    self.end_headers()
                    self.wfile.write(frame)
                    self.wfile.write(b'\r\n')
            except Exception as e:
                logging.warning(
                    'Removed streaming client %s: %s',
                    self.client_address, str(e))
        else:
            self.send_error(404)
            self.end_headers()


class StreamingServer(socketserver.ThreadingMixIn, server.HTTPServer):
    allow_reuse_address = True
    daemon_threads = True

SIZE = (640, 480)
CX = SIZE[0] // 2
CY = SIZE[1] // 2

# Define the lower and upper bounds for the orange color
LOWER = np.array([100, 150, 100])
UPPER = np.array([130, 255, 255])


class Processor:
    def __init__(self, det):
        self.reported = time.monotonic()
        self.count = 0
        self.missed = 0
        self.fps = 0
        self.found = False
        self.yuv_height = SIZE[0] * 2 // 3
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

        circles = cv2.HoughCircles(mask, cv2.HOUGH_GRADIENT, dp=1, minDist=10,
            param1=60, param2=20, minRadius=MIN_SIZE, maxRadius=SIZE[0])

        if circles is not None:
            # print(circles)
            circles = list(circles[0])
            # circles.sort(key=lambda x: x[2])
            ncircles = len(circles)
            best = circles[0]
            # print(f'{ncircles} {best}      ', end='\r')
            cx, cy, cr = best
            # ctext = f'{cx!r},{cy!r},{cr!r}'
            ctext = f'{cx:.0f},{cy:.0f},{cr:.0f}'
        else:
            ncircles = 0
            ctext = 'none'

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
            imgout = cv2.rectangle(iraw, (x, y), (x+w, y+h), (0, 255, 0), 5)

            # X position of ring center from camera center (right positive, left negative)
            ix = (x + w // 2) - CX
            # Y position of ring center up from bottom of camera (positive)
            iy = SIZE[1] - (y + h // 2)

            # Print the center coordinates of the circle
            # print(f"\rring: {ix:3d},{iy:3d} {ctext:10s}        ", end='')
        else:
            imgout = iraw

        if ncircles > 0:
            try:
                imgout = cv2.circle(imgout, (int(cx), int(cy)), int(cr), (255, 0, 40), 15)
            except Exception as ex:
                # print(ex)
                pass

        return imgout


    def do_apriltag(self, arr, imgout):
        img = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        # img = arr[:self.yuv_height,:]
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
            print(f'\r{self.fps:3.0f} FPS: missed {self.missed}' + ' ' * 40, end='')
            # if self.missed == 25:
            #     cv2.imwrite('fail.png', img)
            #     # breakpoint()
            #     pass

        if self.found:
            self.missed = 0
            x = sorted(tags, key=lambda x: -x.getDecisionMargin())[0]
            c = x.getCenter()
            tid = x.getId()
            # pose = field.getTagPose(tid)
            hmat = '' # '[' + ', '.join(f'{x:.0f}' for x in x.getHomography()) + ']'
            margin = x.getDecisionMargin()
            print(f'\r{self.fps:3.0f} FPS: margin={margin:2.0f} @{c.x:3.0f},{c.y:3.0f} id={tid:2} {hmat}    ' % tags, end='')

        return imgout


    async def run(self, cam):
        base = time.monotonic()
        while True:
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
                output2.write(data.getbuffer())

            now = time.monotonic()
            if now - base >= 2.5:
                base = now
                print(f' t={now-t1:.3f}s t={now-t0:.3f}s')


async def main():
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
            format='RGB888'
        ),
    )
    # cfg['transform'] = libcamera.Transform(vflip=1)
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

    global output1
    output1 = StreamingOutput()
    cam.start_recording(MJPEGEncoder(), FileOutput(output1))

    global output2
    output2 = StreamingOutput()
    #cam2.start_recording(MJPEGEncoder(), FileOutput(output2))
    address = ('', 8000)
    server = StreamingServer(address, StreamingHandler)
    sw = asyncio.to_thread(server.serve_forever)

    try:
        p = Processor(det)
        await asyncio.gather(sw, p.run(cam))
    except KeyboardInterrupt:
        pass
    except Exception as ex:
        traceback.print_exc()
    finally:
        print('shutting down')
        server.shutdown()
        await asyncio.sleep(0.6)



if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('-d', '--debug', action='store_true')
    parser.add_argument('--cam', type=int, default=0)
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--res', default='640x480')
    parser.add_argument('--dec', type=int, default=2)
    parser.add_argument('--threads', type=int, default=4)
    parser.add_argument('--fps', type=float, default=50.0)
    parser.add_argument('--time', type=float, default=10.0)

    args = parser.parse_args()
    SIZE = tuple(int(x) for x in args.res.split('x'))
    MIN_SIZE = int(SIZE[0] * 0.05)

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

