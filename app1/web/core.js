import {sleep, get_promise, make_uuid} from 'util';
import {Connector} from './connector.js';

export class Core {
    #qout = [];
    #qout_ready;
    app;
    conn;
    connected;
    #first_hash = true;

    static client_uuid = localStorage.app_uuid || (localStorage.app_uuid = make_uuid());

    constructor() {
        this.#qout_ready = get_promise();

        this.conn = new Connector(this);
        this.conn.addEventListener('connection', evt => this.onConnectionEvent(evt));
    }

    start(app) {
        this.app = app;
        this.run(); // spawn task
    }

    onConnectionEvent(evt) {
        if (evt.msg == 'connected') {
            this.app.connected = this.connected = true;
            this.send('auth', {uuid: Core.client_uuid});
        }
        else if (evt.msg == 'disconnected') {
            this.app.connected = this.connected = false;
            console.warn('disconnected');
        }
        else {
            console.debug(`unhandled connection event: ${evt.msg}`);
        }
    }

    async run() {
        // Build ws[s] WebSocket URL with same host and initial directory name
        // as the parent page, but ending with .ws
        let url = location.href.replace(/http(.*?:\/\/[^/]*)(\/[^/]*)(.*)/, 'ws$1/ws')
        this.conn.open(url);

        while (true) {
            await this.#qout_ready;
            this.#qout_ready = get_promise();
            // console.log('wake');

            let msgs = this.#qout.splice(0);
            for (let msg of msgs) {
                if (this.connected) {
                    console.log(`send ${JSON.stringify(msg)}`);
                    this.conn.emit(...msg);
                    // await sleep(500);
                }
                else {
                    console.log(`discard ${JSON.stringify(msg)}`);
                }
            }
            // await sleep(1500);
        }
    }

    send(data, args) {
        let msg = [data];
        if (args != null) {
            msg.push(args)
        }
        // console.log(`queue ${JSON.stringify(msg)}`);
        this.#qout.push(msg);
        try {
            this.#qout_ready.resolve();
        }
        catch (e) {
            console.error('error', e);
        }
    }

    _msg_meta(msg) {
        let data = JSON.stringify(msg);
        console.log(`meta ${this}, ${data}`);
        this.set_ver(msg.ver);
    }

    _msg_hash(msg) {
        // tell user if source files have changed, so they can trigger
        // a cache-clearing reload
        let old = sessionStorage.web_hash || localStorage.web_hash || null;
        if (old != msg.data) {
            console.debug(`hash changed ${old} -> ${msg.data}`); // won't see this on a reload
            sessionStorage.web_hash = localStorage.web_hash = msg.data;
            if (this.#first_hash) {
                window.location.reload(true);
            }
            else if (old) {
                this.app.verwarn = true;
            }
        } else if (!msg.first) {
            console.debug('hash unchanged, not reloading');
        }

        this.#first_hash = false;
    }

    _msg_fps(msg) {
        let fps = msg.n / msg.t;
        this.app.cams[msg.cam].fps = Math.round(fps, 1);
        this.app.requestUpdate('cams');
        // console.log(`cam ${msg.cam} ${Math.round(fps, 1)} FPS`);
    }

    _msg_dist1(msg) {
        this.app.robot.dist1 = msg.data;
        this.app.requestUpdate('robot');
    }

    _msg_beam1(msg) {
        this.app.robot.beam1 = msg.data;
        this.app.requestUpdate('robot');
    }

    set_ver(ver) {
        console.log('version', ver, this.app);
        this.app.version = ver;
    }
}

window.core = new Core();
