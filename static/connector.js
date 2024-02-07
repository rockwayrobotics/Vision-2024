'use strict';

var Connector;

{
    class Timer {
        constructor() { this.t = Date.now() }
        get() { return Date.now() - this.t }
    }

    function sleep(ms) { return new Promise(resolve => setTimeout(resolve, ms)) }

    class _Connector extends EventTarget {
        constructor (owner, opts) {
            super();
            this.owner = owner;

            // compile options, with defaults that may be overridden (individually)
            this.opts = Object.assign({}, _Connector.DEFAULTS, opts);

            this.state = 'closed';
            this.ws = null;
            this.discarding = false;

            this._binary = null;
        }

        // //------------------------
        // dispatchEvent(name, data) {
        //     let evt = new Event(name);
        //     Object.assign(evt, data);
        //     super.dispatchEvent(evt)
        // }

        _notify(msg) {
            let evt = new Event('connection');
            evt.msg = msg;
            this.dispatchEvent(evt);
        }

        // Open connection to specified url, or previous url if one was given
        // earlier (in a previous open() call or in the constructor).
        open(url) {
            // Failure test cases:
            // 1.   url = 'ws://192.168.7.53/missing.ws';
            //      Host is online but the path is invalid and rejected.
            //      Results in immediate 404 (which we can't detect directly)
            //      then onerror (readyState already 3) then onclose.

            // 2.   url = 'ws://192.168.7.253/hostmissing.ws';
            //      Host is not online on local subnet.
            //      Same result if the packets are dropped, though we can
            //      see repeated TCP SYN packets at 1, 2, 4, 8...
            //      Results in 20s timeout (on Firefox) then onerror
            //      with readyState already 3, then onclose.

            // 3.   url = 'ws://192.168.7.53:12345/portclosed.ws';
            //      Host is online but not listening on the port.
            //      Results in 2s timeout, then onerror (3) then onclose.

            this.url = url || this.url;
            console.debug('opening', this.url);
            this._run_connecting();   // release the hounds!
        }

        close() {
            if (this.ws) {
                console.log('closing ws');
                this.ws.close();
            }

            this._prepare();
        }

        _connecting() {
            // Could include a timeout here, and reject() if we don't get
            // any other activity before that.
            return new Promise((resolve, reject) => {
                this.ws.onopen =    (evt) => { console.debug('_connecting:onopen'); resolve() };
                this.ws.onmessage = (evt) => { console.warn('ws early msg') };
                this.ws.onclose =   (evt) => { console.debug('_connecting:onclose'); reject(new Error(`close ${evt.code}: ${evt.reason}`)) };
                this.ws.onerror =   (evt) => { console.debug('_connecting:onerror'); reject(new Error(`error: ${evt.type}`)) }; // nothing useful in error attributes
            });
        }

        _processing() {
            return new Promise((resolve, reject) => {
                this.ws.onopen =    (evt) => { console.warn('re-open?') };
                this.ws.onmessage = (evt) => { window.mymsg = evt; this._dispatch(evt.data) };
                this.ws.onclose =   (evt) => { console.debug('_processing:onclose'); resolve(`close ${evt.code}: ${evt.reason || "no reason"}`) };
                this.ws.onerror =   (evt) => { console.debug('_processing:onerror'); reject(new Error(`error: ${evt.type}`)) };
                // if (Math.random() < 0.2) {
                //     console.log('you got unlucky! will fake-error in a moment');
                //     setTimeout(evt => reject(new Error('fake error')), 1100);
                // }
            });
        }

        _closing() {
            return new Promise((resolve, reject) => {
                this.ws.onopen =    (evt) => { console.warn('re-open?') };
                this.ws.onmessage = (evt) => { console.warn('late msg: ' + evt.data); this._dispatch(evt.data) };
                this.ws.onclose =   (evt) => { console.debug('_closing:onclose'); resolve(`close ${evt.code}: ${evt.reason}`) };
                this.ws.onerror =   (evt) => { console.debug('_closing:onerror'); reject(new Error(`error: ${evt.type}`)) };
            });
        }

        async _run_connecting() {
            let retry = true;
            // let last_conn = new Timer(); // pretend last connected at this time
            let res;
            console.debug('conn: connector running');

            while (retry) {
                // console.debug('wait connectable');

                // let url = await this._connectable;
                console.debug('conn: opening!');

                this.state = 'opening';
                let timer = new Timer();

                //----------------------------
                // Try to open a socket to the server.
                // Based on experimentation, if it does not connect it will
                // time out either immediately or after a short (2s) or longer
                // (20s) delay depending on whether it gets any responses from
                // the host.  It doesn't wait for the regular
                try {
                    this.ws = new WebSocket(this.url);
                    // Note: WebSocket.readyState: 0=CONNECTING, 1=OPEN, 2=CLOSING, 3=CLOSED

                    // Change from default Blob to arraybuffer for binary messages.
                    this.ws.binaryType = 'arraybuffer';

                    await this._connecting();
                    this.state = 'open';
                }
                catch (error) {
                    console.debug(`caught error, readyState=${this.ws.readyState}`);

                    // Probably already closed... could call only if not closed,
                    // but what should we do if actually open, or already closing?
                    this.ws = null;

                    console.debug(`error connecting (${timer.get()} ms)`);
                    // this.retry_delay = Math.max(this.opts.max_retry_delay,
                    //     this.retry_delay ? this.retry_delay * 2 : 0.5);
                    // await this.cancellable_sleep(this.retry_delay);

                    // if (last_conn.get() > 5*60*1000) {
                    //     this._notify('disabled');
                    // }

                    // TODO: improve this for non-dev Firefox, where we haven't
                    // toggled network.websocket.delay-failed-reconnects,
                    // by eventually halting automatic connection attempts,
                    // flagging this in an event to the owner, and not retrying
                    // until the owner tells us to again (with another open() call?).

                    await sleep(5000);
                    this.state = 'closed';
                    continue;
                }

                // start new timer so we can tell if we disconnect
                // rapidly (in which case we pause before retrying)
                timer = new Timer();

                //----------------------------
                // Now connected. Set up for normal operation.
                try {
                    let task = this._processing();

                    console.log(`connected (${timer.get()} ms)`);

                    // Do this after _processing() sets up the event handlers
                    // or we may miss a message.
                    this._notify('connected');

                    res = await task;   // wait until closed or error

                    console.log(`conn: disconnected:`, res);
                }
                catch (error) {
                    console.error('processing:', error);
                    this.ws.close();

                    try {
                        res = await this._closing();
                        console.log(`conn: disconnected:`, res);
                    }
                    catch (error) {
                        console.error('closing:', error);
                    }
                }

                this.ws = null;
                this.state = 'closed';
                console.debug('conn closed');

                this._notify('disconnected');

                         // extra pause in case we disconnect rapidly, to avoid thrashing
                // This situation was seen once but we don't know how to
                // reproduce it yet, so this workaround is untested.
                if (timer.get() < 2000) {
                    console.warn('too-fast disconnect, pausing');
                    await sleep(5000);
                }
                else
                    await sleep(1000);
            }
            // }
            // catch (error) {
            //     console.error('connector error:', error);
            //     // await sleep(1.0);
            // }
        }


        emit(msg, data) {
            if (this.ws) {
                let pkt = Object.assign({_t: msg}, data || {});
                // let pkt = {
                //     m: msg,
                //     d: data,
                // };

                let payload = JSON.stringify(pkt);
                let text = (payload.length > 120) ? payload.substr(0, 80) + ' ... ' + payload.substr(-20) : payload;
                console.debug(`\u25b6 ${text}`);
                this.ws.send(payload);

                this.discarding = false;
            }
            else {
                if (!this.discarding) {
                    console.warn(`not connected, discarding msg ${msg}`);
                    this.discarding = true;
                }
            }
        }

        _dispatch(pkt) {
            if (pkt instanceof ArrayBuffer) {
                this._binary = pkt;
                // console.log(`save binary, n=${pkt.byteLength}`);
            }
            else {
                let text = (pkt.length > 120) ? pkt.substr(0, 80) + ' ... ' + pkt.substr(-20) : pkt;
                // console.debug(`\u25c0 ${text}`);

                let msg;
                try {
                    msg = JSON.parse(pkt);
                }
                catch (e) {
                    // bad JSON, ignore
                    return;
                }

                if (this._binary) {
                    msg._binary = this._binary;
                    this._binary = null;
                }

                let name = '_msg_' + msg._t;
                let handler = this.owner[name];
                if (!handler) {
                    console.error(`no handler for "${msg._t}" in ${this.owner}`);
                }
                else {
                    try {
                        handler(msg);
                    }
                    catch (error) {
                        console.error(`${name} failed:`, error);
                    }
                }
            }
        }
    }


    _Connector.DEFAULTS = {
        // 'reconnect_delay': 5.0, // pause after disconnect before reconnect
        // 'max_retry_delay': 10.0, // pause between failed attempts
        // 'max_queue': 2 ** 5,
        // 'autoconnect': false,
    };

    Connector = _Connector;
}


// EOF
