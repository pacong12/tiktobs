// OBS Running Text / Marquee Overlay V2 (Connected Badge Groups Inside Scroll)
const wrapEl = document.getElementById('running-text-wrap');
const trackEl = document.getElementById('marquee-track');
const contentA = document.getElementById('marquee-content-a');
const contentB = document.getElementById('marquee-content-b');

let config = null;

document.addEventListener('DOMContentLoaded', () => {
    loadConfig();
    connectWebSocket();
});

async function loadConfig() {
    try {
        const baseUrl = window.location.protocol === 'file:' ? 'http://127.0.0.1:8000' : '';
        const res = await fetch(`${baseUrl}/api/running-text`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        render(await res.json());
    } catch (err) {
        console.error('Failed to load running text config:', err);
        setTimeout(loadConfig, 3000);
    }
}

function escapeHTML(str) {
    if (!str) return '';
    return str.replace(/[&<>'"]/g, tag => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        "'": '&#39;',
        '"': '&quot;'
    }[tag] || tag));
}

function render(cfg) {
    config = cfg;
    // Always prioritize cfg.groups when available, otherwise fall back to cfg.messages
    let groups = [];
    if (Array.isArray(cfg.groups) && cfg.groups.length > 0) {
        groups = cfg.groups.filter(g => g && g.message && g.message.trim());
    } else if (Array.isArray(cfg.messages) && cfg.messages.length > 0) {
        groups = cfg.messages.filter(m => m && m.trim()).map(m => ({
            title: cfg.header_title || 'INFO',
            color: cfg.header_color || '#ff0055',
            message: m
        }));
    }

    if (!cfg.enabled || groups.length === 0) {
        wrapEl.classList.add('hidden');
        return;
    }

    // Build connected badge HTML string for each group item
    let innerHtml = groups.map(g => `
        <div class="badge-group">
            <div class="badge-header" style="--header-bg: ${escapeHTML(g.color || '#ff0055')};">${escapeHTML((g.title || 'INFO').toUpperCase())}</div>
            <div class="badge-body">${escapeHTML(g.message)}</div>
        </div>
    `).join('');

    // Repeat enough times to ensure seamless infinite loop
    let repeatedHtml = innerHtml;
    while (repeatedHtml.length < 1500) {
        repeatedHtml += innerHtml;
    }

    contentA.innerHTML = repeatedHtml;
    contentB.innerHTML = repeatedHtml;
    wrapEl.classList.remove('hidden');

    requestAnimationFrame(() => {
        const halfWidth = trackEl.scrollWidth / 2;
        const speed = Math.max(10, Math.min(300, cfg.speed || 60));
        const duration = Math.max(1, halfWidth / speed);

        trackEl.classList.remove('scroll-left', 'scroll-right');
        trackEl.style.animationDuration = `${duration}s`;
        void trackEl.offsetWidth; // force reflow
        trackEl.classList.add(cfg.direction === 'right' ? 'scroll-right' : 'scroll-left');
    });
}

function connectWebSocket() {
    const wsUrl = window.location.protocol === 'file:'
        ? 'ws://127.0.0.1:8000/ws'
        : `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws`;

    const socket = new WebSocket(wsUrl);

    socket.onopen = () => {
        loadConfig();
    };

    socket.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            if (msg.type === 'running_text_update' && msg.config) {
                render(msg.config);
            }
        } catch (err) {
            console.error('WS message error:', err);
        }
    };

    socket.onclose = () => {
        setTimeout(connectWebSocket, 3000);
    };
}
