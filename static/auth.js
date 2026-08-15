/* Optional API token support.
 *
 * When the server runs with TIKTOBS_API_TOKEN set, every /api request and
 * the /ws socket require that token. This script makes that transparent:
 *   1. Picks up a token from the page URL (?token=...) and persists it to
 *      localStorage — useful for OBS browser source URLs.
 *   2. Wraps window.fetch to attach the X-API-Token header on same-origin
 *      requests.
 *   3. Wraps window.WebSocket to append ?token=... on same-origin sockets.
 *
 * Include this BEFORE any other script on the page. When no token is stored
 * it does nothing, keeping the default (no auth) setup unchanged.
 */
(function () {
    const STORAGE_KEY = 'tiktobs_token';

    function tokenFromURL() {
        try {
            return new URLSearchParams(window.location.search).get('token') || '';
        } catch (e) {
            return '';
        }
    }

    // A token in the URL wins and gets persisted (OBS sources are stateless).
    const urlToken = tokenFromURL();
    if (urlToken) {
        try { localStorage.setItem(STORAGE_KEY, urlToken); } catch (e) { /* ignore */ }
    }

    window.TiktobsAuth = {
        get token() {
            try { return localStorage.getItem(STORAGE_KEY) || ''; } catch (e) { return ''; }
        },
        set(token) {
            try {
                if (token) localStorage.setItem(STORAGE_KEY, token);
                else localStorage.removeItem(STORAGE_KEY);
            } catch (e) { /* ignore */ }
        }
    };

    const getToken = () => window.TiktobsAuth.token;

    // --- fetch wrapper: attach the token header on same-origin calls ---
    const nativeFetch = window.fetch.bind(window);
    window.fetch = function (input, init = {}) {
        const token = getToken();
        if (token) {
            const url = typeof input === 'string' ? input : (input && input.url) || '';
            const sameOrigin = !/^[a-z][a-z0-9+.-]*:\/\//i.test(url) || url.startsWith(window.location.origin);
            if (sameOrigin) {
                init = Object.assign({}, init);
                const headers = new Headers(init.headers || (typeof input === 'object' && input ? input.headers : undefined));
                if (!headers.has('X-API-Token')) headers.set('X-API-Token', token);
                init.headers = headers;
            }
        }
        return nativeFetch(input, init);
    };

    // --- WebSocket wrapper: append ?token= on same-origin sockets ---
    const NativeWebSocket = window.WebSocket;
    window.WebSocket = function (url, protocols) {
        const token = getToken();
        if (token) {
            try {
                const u = new URL(url, window.location.origin);
                if (u.hostname === window.location.hostname && !u.searchParams.has('token')) {
                    u.searchParams.set('token', token);
                    url = u.toString();
                }
            } catch (e) { /* keep original URL */ }
        }
        return protocols !== undefined ? new NativeWebSocket(url, protocols) : new NativeWebSocket(url);
    };
    window.WebSocket.prototype = NativeWebSocket.prototype;
    window.WebSocket.CONNECTING = NativeWebSocket.CONNECTING;
    window.WebSocket.OPEN = NativeWebSocket.OPEN;
    window.WebSocket.CLOSING = NativeWebSocket.CLOSING;
    window.WebSocket.DONE = NativeWebSocket.DONE;
})();
