import {css, html, LitElement, repeat} from 'lit';
import {until, classMap} from 'lit';

import {theme} from './theme.js';

// import {Connector} from './connector.js';
import {} from './rmc-cam-view.js';

import {sleep} from 'util';

const local = css`
:host {
    display: inline-block;
}

.container:not(.connected) {
    background-color: pink;
}

rmc-cam-view {
    margin: 5px;
    border: 2px solid var(--theme-primary, black);
    padding: 5px;
}
::slotted(*) {
    /* border: 1px solid blue;
    padding: 6px; */
}
.meta {
    color: gray;
}
#reload {
    display: inline-block;
    background-color: lightgray;
    margin: 2px;
    border: 2px solid red;
    padding: 5px;
}
`;

export class RmcApp extends LitElement {
    static styles = [theme, local];

    static properties = {
        cams: {},
        version: {},
        connected: {},
        verwarn: {},
    };

    constructor() {
        super();

        this.cams = [
            {num: 0, name: 'Cam-0'},
            {num: 1, name: 'GS-1'},
        ];

        this.run(); // spawn task

        // this.addEventListener('snapshot', (e) => {
        //     console.log('1snapshot', e);
        // });
    }

    async run() {
        await sleep(500);
        window.core.start(this);
        await sleep(2500);
    }

    camEnabled(e) {
        let cam = e.target;
        // console.log('camEnabled', cam.name, cam.enabled);
    }

    camSnapshot(e) {
        let cam = e.target;
        // console.log('camSnapshot', cam.num, cam.name);
        core.send('resend', e.target.count);
    }

    onReload() {
        window.location.reload(true);
    }

    //----------------
    render() {
        const classes = {
            connected: this.connected,
        };

        return html`
            <div class="container ${classMap(classes)}">
                ${this.verwarn
                    ? html`<div id="reload"
                    >Updated. <button @click=${this.onReload}>Click to reload.</button></div>`
                    : ''
                }
                <div class="meta">v${this.version}</div>
                <slot></slot>
                ${repeat(this.cams, (item) => item.num, (item) =>
                    html`<rmc-cam-view
                        num="${item.num}"
                        name="${item.name}"
                        @enabled=${this.camEnabled}
                        @snapshot=${this.camSnapshot}
                    ></rmc-cam-view>`
                )}
            </div>
        `;
    }
}
customElements.define('rmc-app', RmcApp);
