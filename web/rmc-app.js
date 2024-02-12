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
    margin: 2px;
    background-color: red;
    color: black;
    border-radius: 0.5em;
    padding: 0.2em;
    font-size: 1.1rem;
    i {
        translate: 0 5px;   /* fix alignment */
    }
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
        // this.verwarn = true;

        this.run(); // spawn task
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

    onReload(flag) {
        window.location.reload(flag);
    }

    //----------------
    render() {
        const classes = {
            connected: this.connected,
        };

        return html`
            <div class="container ${classMap(classes)}">
                ${this.verwarn
                    ? html`<button id="reload" @click=${() => this.onReload(true)}
                    >New version <i class="md-icon">refresh</i></button>`
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
            <button @click=${() => this.onReload(false)}>Test Reload</button>
        `;
    }
}
customElements.define('rmc-app', RmcApp);
