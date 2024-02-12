import {css} from 'lit';

export const theme = css`
    :host {
      display: inline-block;
      outline: none;
      padding: 8px;
      --mdc-theme-primary: #0069c0;
      --mdc-theme-secondary: #1b5e20;
      --mdc-typography-body2-font-size: 1.1rem;
      --mdc-typography-body2-font-weight: 400;
      --mdc-checkbox-unchecked-color: black;
    }

    mwc-textfield {
      display: block;
      margin-top: 16px;
      --mdc-shape-small: 12px;
    }

    .controls {
      display: flex;
      padding: 8px 0;
      justify-content: flex-end;
    }

    .lists {
      display: flex;
    }

    .list {
      flex: 1;
    }

    ul {
      margin: 0;
      padding: 0;
      outline: none;
    }

    li {
      will-change: transform;
      position: relative;
      background: #ffeb3b;
      padding: 8px;
      border-radius: 12px;
      margin: 8px;
      display: flex;
      align-items: center;
    }

    li > button {
      border: none;
      background: none;
      outline: none;
      font-family: 'Material Icons';
      font-size: 24px;
      cursor: pointer;
    }

    li > mwc-formfield {
      flex: 1;
    }

    .list.completed li {
      background: #4caf50;
    }

    .x-test {
        color: red !important;
    }

    /* Including <link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined" rel="stylesheet" />
       in the index.html is the "correct" way to use the Material Design icons,
       but I haven't yet found a clean way of sharing that style with all
       the components, which are each scoped inside a shadow DOM, so this is a workaround. */
    @font-face {
      font-family: 'Material Symbols Outlined';
      font-style: normal;
      font-weight: 400;
      src: url(https://fonts.gstatic.com/s/materialsymbolsoutlined/v161/kJF1BvYX7BgnkSrUwT8OhrdQw4oELdPIeeII9v6oDMzByHX9rA6RzaxHMPdY43zj-jCxv3fzvRNU22ZXGJpEpjC_1v-p_4MrImHCIJIZrDCvHOej.woff2) format('woff2');
    }

    .md-icon {
      font-family: 'Material Symbols Outlined';
      font-weight: normal;
      font-style: normal;
      font-size: 24px;
      line-height: 1;
      letter-spacing: normal;
      text-transform: none;
      display: inline-block;
      white-space: nowrap;
      word-wrap: normal;
      direction: ltr;
      -moz-font-feature-settings: 'liga';
      -moz-osx-font-smoothing: grayscale;
    }
`;
