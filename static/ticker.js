// OBS Running Text (ticker) overlay.
// Fetches its configuration from /api/ticker, renders a seamless marquee,
// and updates live whenever the server broadcasts a 'ticker_update' message
// (triggered by saving the ticker settings on the Settings page).

const tickerWrap = document.getElementById('ticker-wrap');
const tickerTrack = document.getElementById('ticker-track');
const contentA = document.getElementById('ticker-content-a');
const contentB = document.getElementById('ticker-content-b');

let config = null;
let socket = null;

async function loadConfig() {
    try {
        const res = await fetch('/api/ticker');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        render(await res.json());
    } catch (err) {
        console.error('Failed to load ticker config:', err);
        // Retry so OBS sources opened before the server was ready recover.
        setTimeout(loadConfig, 3000);
    }
}

function render(cfg) {
    config = cfg;
    const messages = (cfg.messages || []).filter(m => m && m.trim());

    if (!cfg.enabled || messages.length === 0) {
        tickerWrap.classList.add('hidden');
        return;
    }

    // Two identical copies make the scroll loop seamless.
    const text = messages.join(cfg.separator || '  \u2022  ');
    contentA.textContent = text;
    contentB.textContent = text;
    tickerWrap.classList.remove('hidden');

    // Restart the marquee; duration derives from content width and speed.
    requestAnimationFrame(() => {
        const halfWidth = tickerTrack.scrollWidth / 2;
        const speed = Math.max(10, Math.min(300, cfg.speed || 60)); // px per second
        const duration = Math.max(1, halfWidth / speed);

        tickerTrack.classList.remove('scroll-left', 'scroll-right');
        tickerTrack.style.animationDuration = `${duration}s`;
        void tickerTrack.offsetWidth; // force reflow so the animation restarts
        tickerTrack.classList.add(cfg.direction === 'right' ? 'scroll-right' : 'scroll-left');
    });
}

function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    socket = new WebSocket(`${protocol}//${window.location.host}/ws`);

    socket.onopen = () => {
        // Re-sync in case the config changed while we were disconnected.
        loadConfig();
    };

    socket.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            if (msg.type === 'ticker_update' && msg.config) {
                render(msg.config);
            }
        } catch (err) {
            console.error('Ticker WS message error:', err);
        }
    };

    socket.onclose = () => {
        setTimeout(connectWebSocket, 3000);
    };

    socket.onerror = () => {
        socket.close();
    };
}

// Pause the scroll while the tab is hidden (OBS scene switches) to avoid
// big position jumps when it becomes visible again.
document.addEventListener('visibilitychange', () => {
    tickerTrack.classList.toggle('paused', document.hidden);
});

// Web fonts load asynchronously; re-measure once they arrive so the
// scroll duration matches the final rendered width.
if (document.fonts && document.fonts.ready) {
    document.fonts.ready.then(() => {
        if (config) render(config);
    });
}

loadConfig();
connectWebSocket();
