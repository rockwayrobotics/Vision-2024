'use strict';

// Logging enhancement.  Prints the time (with milliseconds)
// and thereby also ensures browsers don't hide "duplicate" log messages.
class Logger {
    constructor(orig) {
        this.con = {
            debug: orig.debug,
            log: orig.log,
            info: orig.info,
            warn: orig.warn,
            error: orig.error,
        };
    }

    // Get current time as local HH:MM:SS.mmm
    static tzoff = (new Date).getTimezoneOffset() * 60000;
    static ts() {
        return (new Date(Date.now() - Logger.tzoff)).toJSON().slice(11, -1);
    }

    _log(level, ...args) {
        this.con[level](`${Logger.ts()}`, ...args);
    }

    debug(...args) { this._log('debug', ...args) }
    log(...args) { this._log('log', ...args) }
    info(...args) { this._log('log', ...args) }
    warn(...args) { this._log('warn', ...args) }
    error(...args) { this._log('error', ...args) }
}

// Comment out this line to remove temporarily.
window.console = new Logger(console);


// Async sleep for specified milliseconds.
export function sleep(ms) {
    return new Promise(res => { setTimeout(res, ms) });
}


async function wait_for(promise, ms) {
    // Create a promise that rejects in <ms> milliseconds
    let timeout = new Promise((resolve, reject) => {
        let id = setTimeout(() => {
            clearTimeout(id);
            reject(`Timed out in ${(ms/1000).toFixed(1)}s.`)
        }, ms)
    });

    // Returns a race between our timeout and the passed in promise
    return Promise.race([
        promise,
        timeout
    ]);
}

export function get_promise() {
    let funcs;
    let p = new Promise((resolve, reject) => {
        funcs = {resolve, reject};
    });

    return Object.assign(p, funcs);
}

function toHex(byteArray) {
    return Array.from(byteArray, function(byte) {
        return ('0' + (byte & 0xFF).toString(16)).slice(-2);
    }).join('')
}

function fmtTime(...fields) {
    return Array.from(fields, x => ('0' + x).slice(-2)).join(':');
}

// Utility routine to make ids. By default does xxxxxx-xxxx-xx
// even though a real UUID is longer.
export function make_uuid(parts) {
    var pad = '000000000000';
    var uuid = [];
    (parts || [3, 2, 1]).forEach(function(len) {
        var num = Math.floor(Math.random() * Math.pow(256, len)); // random
        var part = pad + num.toString(16); // pad and hex
        uuid.push(part.slice(-len*2));
    });
    return uuid.join('-');
}
