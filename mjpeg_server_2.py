#!/usr/bin/python3

# This is the same as mjpeg_server.py, but uses the h/w MJPEG encoder.

import io
import logging
import socketserver
from http import server
from threading import Condition

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
    <div style="width: 40%">
        <h1>Cam1</h1>
        <img src="stream1.mjpg" width="320" height="240" />
    </div>
    <div style="width: 40%">
    <h1>Cam2</h1>
    <img src="stream2.mjpg" width="320" height="240" />
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


cam1 = Picamera2(0)
cfg = cam1.create_video_configuration(main={"size": (1024, 768)})
cfg['transform'] = libcamera.Transform(vflip=1)
cam1.configure(cfg)

cam2 = Picamera2(1)
cfg = cam2.create_video_configuration(main={"size": (1024, 768)})
cfg['transform'] = libcamera.Transform(vflip=1)
cam2.configure(cfg)

output1 = StreamingOutput()
cam1.start_recording(MJPEGEncoder(), FileOutput(output1))

output2 = StreamingOutput()
cam2.start_recording(MJPEGEncoder(), FileOutput(output2))

try:
    address = ('', 8000)
    server = StreamingServer(address, StreamingHandler)
    server.serve_forever()
finally:
    cam1.stop_recording()
    cam2.stop_recording()
