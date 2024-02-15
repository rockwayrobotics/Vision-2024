import {css, html, LitElement} from 'lit';
import {until, classMap} from 'lit';

import {theme} from './theme.js';

import {sleep} from 'util';

const local = css`
:host {
    display: inline-block;
}

/* Note: the layout is garbage for now... */

.outer {
    position: relative;
    width: 18em;
    height: 10em;
    margin: 5px;
    border: 2px solid gray;

    &.active {
        border-color: green;
        background-color: lightgreen;
    }
}

.frame {
    position: absolute;
    left: 10px;
    right: 10px;
    bottom: 10px;
    height: 50%;
    border: 2px solid black;
    padding: 10px;
    background: var(--bg-page);
}

.name {
    color: blue;
}
`;

export class RmcCamView extends LitElement {
    static styles = [theme, local];

    static properties = {
        name: {type: String},
        num: {type: Number},
        enabled: {type: Boolean},
        count: {state: true},
        image: {state: true},
        data: {attribute: false},
    };

    #ready;

    constructor() {
        super();

        this.name = 'Cam1';
        this.num = 1;
        this.enabled = true;
        this.count = 0;
        this.data = {fps: 0};
        this.image = new Promise(res => {
            this.#ready = res;
        });

        this.run();
    }

    // connectedCallback() {
    //     super.connectedCallback();
    //     console.log('renderRoot', this.renderRoot);
    // }

    async run() {
        while (true) {
            await sleep(1000);
            if (this.enabled) {
                this.count += 1;
                if (this.count == 10) {
                    this.#ready(html`image ready`);
                }
            }
        }
    }

    // Event handlers can update the state of @properties on the element
    // instance, causing it to re-render
    snapshot() {
        // console.log(this.name, 'snapshot', this.num);
        this.dispatchEvent(new CustomEvent('snapshot', {detail: this.num}));
        core.send('this', this.count);
        this.count += 1;
    }

    _enableChanged(_evt) {
        this.enabled = !this.enabled;
        // console.log(this.name, this.enabled);
        this.dispatchEvent(new CustomEvent('enabled', {detail: this.num}));
    }

    //----------------
    render() {
        const classes = {
            outer: true,
            active: this.enabled,
        };

        return html`
            <div class=${classMap(classes)}>
                <div class="name">${this.num}: ${this.name}</div>
                <span class="md-icon">remove_circle</span><span>${this.count}</span>
                <input type="checkbox"
                    .checked=${this.enabled}
                    @change=${this._enableChanged}
                />
                <span class="fps">${this.data.fps} FPS</span>
                <div class="frame" @click=${this.snapshot}>
                    ${until(this.image, html`<img
                        src="img/no-cam.svg" width="100%" height="100%">`)}
                </div>
            </div>
        `;
    }
}
customElements.define('rmc-cam-view', RmcCamView);
