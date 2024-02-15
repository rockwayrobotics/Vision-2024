import json
import logging
import re

import ntcore


class mock:
    def get(*_): return 0
    def set(*_): pass


class Nt:
    def __init__(self):
        self.log = logging.getLogger('nt')

    # mock stuff... will be shadowed by real pub/sub/entries if not mocking
    running = mock()
    motor = mock()
    tag_x = mock()
    tag_y = mock()
    dist1 = mock()
    beam1 = mock()

    def start(self, args):
        self._nt = ntcore.NetworkTableInstance.getDefault()
        self._nt.setServerTeam(args.team)
        self._nt.startClient4('fire1') # TODO: use hostname or arg

        self.vis_serial = self._nt.getStringTopic('/Vision/serial').publishEx('string', json.dumps(dict(persistent=True)))
        try:
            sn = re.search(r'^Serial\s*:\s*(.*)$', open('/proc/cpuinfo').read(), re.MULTILINE).group(1)
        except:
            sn = '?'
        self.vis_serial.set(sn)

        self.running = self._nt.getBooleanTopic('/Vision/running').publish()
        self.running.set(True)

        self.tag_x = self._nt.getIntegerTopic('/Vision/tag-x').publish()
        self.tag_x.set(0)
        self.tag_y = self._nt.getIntegerTopic('/Vision/tag-y').publish()
        self.tag_y.set(0)
        self.motor = self._nt.getBooleanTopic('/Vision/motor').getEntry(False)
        self.motor.set(False)
        self.dist1 = self._nt.getIntegerTopic('/Vision/Dist1').subscribe(0)
        self.beam1 = self._nt.getBooleanTopic('/Shuffleboard/Digital/Beam Break Sensor >:3').subscribe(False)


    def stop(self):
        try:
            self._nt.stopClient()
            # TODO: investigate why the stopClient() call stalls for
            # a few seconds before we can exit.
            # 2024-02-15: it was not stalling the other day at Rockway,
            # but back home it's stalling again.  May be because there's
            # no default server running on a robot here.
        except:
            self.log.exception('stop failed')


NT = Nt()
