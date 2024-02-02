#!/usr/bin/python3

# This is the same as mjpeg_server.py, but uses the h/w MJPEG encoder.

import asyncio
import io
import logging
import socketserver
from http import server
from threading import Condition
import sys
import time
import traceback

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

IMG_SIZE = (640, 480)
CX = IMG_SIZE[0] // 2
CY = IMG_SIZE[1] // 2

# Define the lower and upper bounds for the orange color
LOWER = np.array([100, 150, 100])
UPPER = np.array([130, 255, 255])
MIN_SIZE = int(IMG_SIZE[0] * 0.05)

def do_frame(iraw):
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
        param1=60, param2=20, minRadius=MIN_SIZE, maxRadius=IMG_SIZE[0])

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
        iy = IMG_SIZE[1] - (y + h // 2)

        # Print the center coordinates of the circle
        print(f"\rring: {ix:3d},{iy:3d} {ctext:10s}        ", end='')
    else:
        imgout = iraw

    if ncircles > 0:
        try:
            imgout = cv2.circle(imgout, (int(cx), int(cy)), int(cr), (255, 0, 40), 15)
        except Exception as ex:
            # print(ex)
            pass

    okay, buf = cv2.imencode(".jpg", imgout)
    if okay:
        data = io.BytesIO(buf)
        # breakpoint()
        output2.write(data.getbuffer())
    # else:
    #     breakpoint()


async def process(cam):
    base = time.monotonic()
    while True:
        # runs every 33ms with camera module v3 at 640x480 or 1024x768
        t0 = time.monotonic()
        iraw = cam.capture_array()
        t1 = time.monotonic()
        do_frame(iraw)

        now = time.monotonic()
        if now - base >= 2.5:
            base = now
            print(f' t={now-t1:.3f}s t={now-t0:.3f}s')


async def main():
    cam1 = Picamera2(0)
    print(cam1.sensor_modes)
    cfg = cam1.create_video_configuration(controls=dict(
            FrameDurationLimits=(16000, 16000),
        ),
        main=dict(
            size=IMG_SIZE,
            format="RGB888",
            )
        )
    cfg['transform'] = libcamera.Transform(vflip=1)
    # cam1.set_controls(dict(FrameRate=120.0))
    print(cfg)
    cam1.configure(cfg)

    #cam2 = Picamera2(1)
    #cfg = cam2.create_video_configuration(main={"size": (1024, 768)})
    #cfg['transform'] = libcamera.Transform(vflip=1)
    #cam2.configure(cfg)

    global output1
    output1 = StreamingOutput()
    cam1.start_recording(MJPEGEncoder(), FileOutput(output1))

    global output2
    output2 = StreamingOutput()
    #cam2.start_recording(MJPEGEncoder(), FileOutput(output2))
    address = ('', 8000)
    server = StreamingServer(address, StreamingHandler)
    sw = asyncio.to_thread(server.serve_forever)

    try:
        await asyncio.gather(sw, process(cam1))
    except KeyboardInterrupt:
        pass
    except Exception as ex:
        traceback.print_exc()
    finally:
        print('shutting down')
        server.shutdown()
        await asyncio.sleep(0.6)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

