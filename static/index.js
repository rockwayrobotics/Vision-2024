'use strict';

(function() {
    let client_uuid, server_uuid;
    let core, model, app, vm;
    let first_hash = true;
    let lodash = _;     // alias this to be less obscure

    // First time, retrieve stored UUID if possible, else create new one and store it.
    if (!client_uuid) {
        try {
            client_uuid = localStorage.app_uuid || (localStorage.app_uuid = make_uuid());
        } catch(error) {
            client_uuid = make_uuid();
        }
    }

    function sleep(s) { return new Promise(resolve => setTimeout(resolve, s)) }

    class Core {    // the controller
        constructor() {
            // super();

            this.name = 'Core';
            this.conn = new Connector(this);
            this.conn.addEventListener('connection', evt => this.onConnectionEvent(evt));
            this.fft = null;  // tracks FFT status
            this.trace_index = 0;
            this.updating = false;

            console.log('core created');
        }

        emit(msg, data) {
            this.conn.emit(msg, data);
        }

        async init() {
            console.log('core running', this);

            // Build ws[s] WebSocket URL with same host and initial directory name
            // as the parent page, but ending with .ws
            let url = location.href.replace(/http(.*?:\/\/[^/]*)(\/[^/]*)(.*)/, 'ws$1/ws')

            this.conn.open(url);

            console.log('core done');
        }

        onConnectionEvent(evt) {
            if (evt.msg == 'connected') {
                vm.connected = true;
                this.emit('auth', {uuid: client_uuid});
            }
            else if (evt.msg == 'disconnected') {
                vm.connected = false;
            }
            else {
                console.debug(`unhandled connection event: ${evt.msg}`);
            }
        }


        // //------------------------
        // // Convenience routine, allowing short emit('foo').
        // async emit(msg, data, callback) {
        //     msg = Object.assign({_t: msg, _r: ++this.msg_ref}, data);
        //     console.debug('emit', msg);

        //     if (callback) {
        //         let ref = {id: this.msg_ref, ts: Date.now(), callback};
        //         this.refs[ref.id] = ref;
        //         this.reflog.push(ref);
        //     }

        //     if (app.ws)
        //         await app.ws.send(msg);
        // }

        //------------------------
        // Handle metadata from server
        async _msg_meta(msg) {
            if (msg.uuid) {
                // detect whether we connected, reconnected, or server restarted
                if (msg.uuid != server_uuid) {
                    if (!server_uuid)
                        console.debug('server connected');
                    else
                        console.debug('server restarted');

                    server_uuid = msg.uuid;
                }
                else if (msg.first) {
                    console.debug('server reconnected');
                }
            }

            vm.server = msg;
        }

        async _msg_hash(msg) {
            // tell user if source files have changed, so they can trigger
            // a cache-clearing reload
            let old = sessionStorage.web_hash || localStorage.web_hash || null;
            if (old != msg.data) {
                console.debug(`hash ${old} -> ${msg.data}`); // won't see this on a reload
                sessionStorage.web_hash = localStorage.web_hash = msg.data;
                vm.uihash = msg.data;
                if (first_hash) {
                    window.location.reload(true);
                }
                else if (old) {
                    vm.verwarn = 'App updated. Click to reload.';
                }
            } else if (!msg.first) {
                console.debug('hash unchanged, not reloading');
            } else {
                vm.uihash = msg.data;
            }

            first_hash = false;
        }


        async _msg_users(msg) {
            vm.user_count = msg.count;
        }

        async _msg_audio(msg) {
            core.updating = true;
            vm.audio = Object.assign(vm.audio, msg);
            core.updating = false;
        }

        async _msg_faults(msg) {
            let text = msg.data.map(x => FAULTS[x]).join(', ')
            vm.faults = text;
        }

        async _msg_stats(msg) {
            // console.log('stats', msg);
            vm.stats = Object.assign(vm.stats, msg);
        }

        // Receive experimental binary data and print bytes in decimal
        async _msg_bintest(msg) {
            console.log(`bintest: ${new Uint8Array(msg._binary)}`);
        }

        //
        async _msg_full_state(msg) {
            vm.audio = Object.assign(vm.audio, msg.audio);
            // override default with hostname for convenience
            if (!vm.audio.rec_tag && vm.server.hostname) {
                vm.audio.rec_tag = vm.server.hostname;
            }

            vm.meta = Object.assign(vm.meta, msg.meta);
            vm.core = Object.assign(vm.core, msg.core);
            // vm.calls = Object.assign(vm.calls, msg.calls);
            vm.signals = Object.assign(vm.signals, msg.gpio);
            vm.readings = Object.assign(vm.readings, msg.readings);
            vm.stats = Object.assign(vm.stats, msg.stats);

            vm.faults = msg.faults.map(x => FAULTS[x]).join(', ');

            // update page title
            document.title = `${vm.meta.mod_name} Diagnostic Tool`;
        }

        async _msg_gpios(msg) {
            // console.log('gpios', msg);
            for (let x in msg.data) {
                let data = msg.data[x];
                // if (!vm.signals[x].ui.noisy) {
                //     console.log(x, data.mode, data.raw, data.forced);
                // }
                vm.signals[x] = Object.assign(vm.signals[x], data);
            }
        }

        async _msg_readings(msg) {
            // console.log('readings', msg);
            for (let x in msg.data) {
                let data = msg.data[x];
                // console.log(x, data.mode, data.raw, data.forced);
                vm.readings[x] = Object.assign(vm.readings[x], data);
            }
        }

        async _msg_fft(msg) {
            if (!vm.audio.fft) {
                return;
            }

            let elem = document.getElementById('fft-graph');
            if (!elem)
                return;

            let ydata = new Int8Array(msg._binary);
            window.lastmsg = msg;

            if (!core.fft || core.fft.last_tag != msg.tag) {
                core.xaxis = [];
                for (let i = 0; i < ydata.length; i++) {
                    core.xaxis[i] = i * msg.bw;
                }

                // initialize with this trace only
                core.fft = {last_tag: msg.tag};

                // https://observablehq.com/@d3/margin-convention?collection=@d3/d3-axis
                var margin = {top: 35, right: 20, bottom: 20, left: 50};
                var width = 570, height = 300;

                // https://observablehq.com/@d3/d3-scalelinear
                core.xscale = d3.scaleLinear().domain([0, 4000])
                    .range([margin.left, width - margin.right]);
                core.yscale = d3.scaleLinear().domain([0, -120])
                    .range([margin.top, height - margin.bottom]);

                // TODO: save to PNG: see https://www.demo2s.com/javascript/javascript-d3-js-save-svg-to-png-image.html
                var svg = d3.select(elem);

                // https://stackoverflow.com/questions/3674265/is-there-an-easy-way-to-clear-an-svg-elements-contents/23673547#23673547
                svg.selectAll('*').remove();

                svg
                    .attr('viewBox', [0, 0, width, height]) // unclear what this does
                    .attr('width', width)
                    .attr('height', height);

                // https://www.essycode.com/posts/adding-gridlines-chart-d3/
                const graphHeight = height - margin.top - margin.bottom;
                const graphWidth = width - margin.left - margin.right;

                svg.append('g')
                    .attr('class', 'y axis-grid')
                    .attr('transform', `translate(${margin.left}, 0)`)
                    .call(d3.axisLeft(core.yscale).tickSize(-graphWidth).tickFormat('').ticks(4));
                svg.append('g')
                    .attr('class', 'y axis')
                    .attr('transform', `translate(${margin.left}, 0)`)
                    .call(d3.axisLeft(core.yscale)); //.ticks(7));

                svg.append('g')
                    .attr('class', 'x axis-grid')
                    .attr('transform', `translate(0, ${margin.top})`)
                    .call(d3.axisTop(core.xscale).tickSize(-graphHeight).tickFormat('').ticks(4));
                svg.append('g')
                    .attr('class', 'x axis')
                    .attr('transform', `translate(0, ${margin.top})`)
                    .call(d3.axisTop(core.xscale)); //.ticks(5));

                svg.append('text')
                    .attr('text-anchor', 'end')
                    .attr('x', margin.left + graphWidth / 2)
                    .attr('y', margin.top - 20)
                    .text('Hz');

                svg.append('text')
                    .attr('text-anchor', 'end')
                    .attr('transform', 'rotate(-90)')
                    .attr('x', (-graphHeight - margin.top) / 2)
                    .attr('y', margin.left - 30)
                    .text('dBFS');

                core.I = d3.range(ydata.length);
                const line = d3.line()
                      .x(i => core.xscale(core.xaxis[i]))
                      .y(i => core.yscale(ydata[i]));

                svg.append('path')
                    .attr('class', 'fft-data')
                    .attr('fill', 'none')
                    .attr('stroke', COLORS[msg.tag])
                    // .attr('stroke-width', 1)
                    // .attr('stroke-linecap', strokeLinecap)
                    // .attr('stroke-linejoin', strokeLinejoin)
                    // .attr('stroke-opacity', strokeOpacity)
                    .attr('d', line(core.I));
            }
            else {
                var svg = d3.select(elem);
                svg.selectAll('.fft-data').remove();

                const line = d3.line()
                      .x(i => core.xscale(core.xaxis[i]))
                      .y(i => core.yscale(ydata[i]));

                svg.append('path')
                    .attr('class', 'fft-data')
                    .attr('fill', 'none')
                    .attr('stroke', COLORS[msg.tag])
                    .attr('d', line(core.I));
            }
            // console.log('fft', msg.tag, msg.bw, new Int8Array(msg._binary));
        }

        // async _msg_all_groups(msg) {
        //     for (group in msg.groups)
        //         vm[group] = Object.assign(vm[group], msg.data[group]);
        // }

        // //
        // async _msg_group_update(msg) {
        //     vm[msg.group] = Object.assign(vm[msg.group], msg.data);
        // }
    }

    // // Check whether current firmware is at least the specified version.
    // function version_check(required) {
    //     return (numver(vm.dev.fwver) >= numver(required));
    // }


    //----------------------------------------------

    let slider_count = 0;
    const Model = {
        data() {
            // console.log('returning model from data()');
            return model;
        },
        created() {
            console.log('hook: created');
            vm = window.vm = this;
        },
        mounted() {
            console.log('hook: mounted');

            core = window.core = new Core();
            core.init(); // launch microtask to initialize in background
        },
        methods: {
            hilite() {
                if (this.devmode)
                    document.body.classList.toggle('hilite');
            },
            full_reload() {
                window.location.reload(true);
            },

            onClick(msg) {
                console.log(`click ${msg}`);
                core.emit(msg);
            },

            onRecord(msg) {
                core.emit('diag_record', {rec_tag: this.audio.rec_tag});
            },

            onPlay(msg) {
                let audio = this.audio;

                if (audio.playing) {
                    core.emit('diag_play_stop');
                }
                else {
                    core.emit('diag_play_start', {
                        spk_src: audio.spk_src,
                        freq: audio.freq,
                        file: audio.file,
                        gain: audio.gain,
                        loop: audio.loop,
                        duration: audio.duration,
                    });
                }
            },
            onAudio(msg) {
                let audio = this.audio;

                if (audio.active) {
                    core.emit('diag_stop');
                }
                else {
                    core.emit('diag_call', {
                        // spk_src: audio.spk_src,
                        timeout: audio.timeout || null,
                        // freq: audio.freq,
                        // file: audio.file,
                        host: audio.host,
                        rtp_send: audio.rtp_send,
                        rtp_recv: audio.rtp_recv,
                        // mic_rtp: audio.mic_rtp,
                        // mic_rec: audio.mic_rec,
                    });
                }
            },
            async onAlarmCancel() {
                core.emit('diag_alarm_cancel');
            },
            async onEchoReset() {
                core.emit('echo_reset');

                vm.aec_reset_inhibit = true;
                await sleep(2000);
                vm.aec_reset_inhibit = false;
            },
            onSpkVolChanging: lodash.throttle(function() {
                core.emit('spk_vol', {value: this.audio.spk_vol});
                }, 200),
            onSpkVolChanged() {
                core.emit('spk_vol', {value: this.audio.spk_vol});
            },
            onMicVolChanging: lodash.throttle(function() {
                core.emit('mic_vol', {value: this.audio.mic_vol});
                }, 200),
            onMicVolChanged() {
                core.emit('mic_vol', {value: this.audio.mic_vol});
            },
            onSidetoneVolChanging: lodash.throttle(function() {
                core.emit('sidetone_vol', {value: this.audio.sidetone_vol});
                }, 200),
            onSidetoneVolChanged() {
                core.emit('sidetone_vol', {value: this.audio.sidetone_vol});
            },
        },

        // computed: {
        //     pav3() { return this.dev.hwver=='6.0.0' },
        // },

        watch: {
            'audio.fft': function (val) {
                if (!core.updating) {
                    core.emit('fft', {src: val});

                    if (!val) {
                        core.fft = {};
                        let elem = document.getElementById('fft-graph');
                        // Plotly.deleteTraces(elem, 0);
                    }
                }
            },
            'audio.rec_dur': function (val) {
                core.emit('rec_info', {rec_dur: this.audio.rec_dur, recording: this.audio.recording});
            },
            'audio.recording': function (val) {
                core.emit('rec_info', {rec_dur: this.audio.rec_dur, recording: this.audio.recording});
            },
        },
    };

    function setup_app() {
        app = window.app = Vue.createApp(Model);
        app.config.warnHandler = function(msg, vm, trace) {
            console.warn(`Vue warning: ${msg}`);
        }

        //------------------------
        app.component('data-section', {
            template: '#data-section',
            props: {
                label: String,
                sect: Object,
            },
        });

        app.component('data-field', {
            template: '#data-field',
            props: {
                label: String,
            },
        });

        app.component('data-signal', {
            template: '#data-signal',
            props: {
                name: String,
            },
            setup(props) {
                // Hack: this relies on our use of the created() hook in the root
                // component to set the "vm" variable.  There's almost certainly
                // a more elegant way to do this.
                // console.log('setup', props.name);
                let value = vm.signals[props.name] = Vue.ref({name: props.name, ui: {} });
                return {signal: value, gpio: vm.gpio};
            },
            // mounted() {
            //     console.log('mounted', this.name, vm.version);
            // },
            computed: {
                effective() {
                    if (this.signal.forced != null)
                        return this.signal.forced;
                    else
                        return this.signal.raw;
                },
                forced: {
                    get() { return this.signal.forced; },
                    set(newval) {
                        this.signal.forced = newval;
                        core.emit('force', {name: this.name, state: newval});
                    }
                },
            },
            methods: {
                async pulse(name) {
                    // experimental
                    core.emit('force', {name: name, state: 1});
                    await sleep(250);
                    core.emit('force', {name: name, state: null});
                },
            },
            // watch: {
            //     forced(newval) {
            //         core.emit('force', {name: this.name, state: newval});
            //     },
            // },
        });


        app.component('data-reading', {
            template: '#data-reading',
            props: {
                name: String,
            },
            setup(props) {
                // Hack: this relies on our use of the created() hook in the root
                // component to set the "vm" variable.  There's almost certainly
                // a more elegant way to do this.
                // console.log('setup', props.name);
                let value = vm.readings[props.name] = Vue.ref({name: props.name, ui: {} });
                return {reading: value, gpio: vm.gpio};
            },
            computed: {
                effective() {
                    // if (this.reading.force != null)
                    //     return this.reading.forced;
                    // else
                        return this.reading.raw;
                },
            },
        });

        vm = window.vm = app.mount('#vue-root');

        vm.user_agent = navigator.userAgent;

        console.log('main function end');

        if (/#dev/.test(location.href)) {
            less.env = 'development';
            less.poll = 2000;
            less.watch();
            console.log('enabled Less watch mode');

            vm.devmode = true;
        }

        return app;
    }

    window.model = model = {
        // metadata
        devmode: false,
        uuid: client_uuid,
        verwarn: '',
        uihash: '',

        connecting: false,
        connected: false,

        user_count: 0,
        server: {
        },

        // UI sections
        status: {},
        dev: {},
        admin: {},
        meta: {},

        aec_reset_inhibit: false,

        signals: {
        },

        // sensor and temperature readings etc
        readings: {
        },

        // Stuff to control the GPIO panel
        gpio: {
            advanced: true,
            allow_forcing: false,
            show_hw: false,
        },

        console: console,

        core: {
        },

        faults: '',

        audio: {
            active: false,
            playing: false,
            aec: false,
            fft: null,
            timeout: 0,

            spk_src: 'tone',
            spk_vol: null,
            freq: 1000,
            gain: -20,
            file: 'greeting',
            loop: false,
            duration: 10,

            host: '',

            mic_mute: false,
            mic_vol: null,
            sidetone: false,    // true in HCT
            sidetone_vol: null,

            // recording
            recording: false,
            rec_dur: 10,
            rec_tag: '',

            // not really part of audio... should refactor
            req_mode: 0,
        },

        stats: {
            recv_count: 0,
            pow_spk: 0,
            pow_send: 0,
            pow_mic: 0,
        },
    };

    app = setup_app();
})();
