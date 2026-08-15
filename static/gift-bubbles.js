// Gift Bubbles overlay — every settled gift that maps to a candidate spawns a
// small square "bubble" (the candidate's card) that floats up the screen.
//
// Counting rule matches the poll: streakable gifts (gift_type === 1) emit one
// event per combo increment, but a bubble only appears on the FINAL event
// (repeat_end === 1) so mid-combo spam does not flood the screen.

let socket = null;
let currentPoll = null;

// Hard cap so a gift storm cannot pile up hundreds of bubbles at once.
const MAX_BUBBLES = 18;

const stage = document.getElementById('bubble-stage');

document.addEventListener('DOMContentLoaded', () => {
    initOverlay();
});

async function initOverlay() {
    await fetchPollStatus();
    connectWebSocket();
}

async function fetchPollStatus() {
    try {
        const baseUrl = window.location.protocol === 'file:' ? 'http://127.0.0.1:8000' : '';
        const response = await fetch(`${baseUrl}/api/poll/status`);
        const poll = await response.json();
        currentPoll = poll;
    } catch (error) {
        console.error('Failed to fetch poll status:', error);
    }
}

function connectWebSocket() {
    const wsUrl = window.location.protocol === 'file:'
        ? 'ws://127.0.0.1:8000/ws'
        : `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws`;

    socket = new WebSocket(wsUrl);

    socket.onopen = () => {
        console.log('Gift bubbles overlay WebSocket connected.');
    };

    socket.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            if (msg.type === 'poll_update') {
                currentPoll = msg.poll;
            } else if (msg.type === 'event' && msg.event && msg.event.event_type === 'gift') {
                handleGiftEvent(msg.event);
            }
        } catch (error) {
            console.error('Error handling WebSocket message:', error);
        }
    };

    socket.onclose = () => {
        console.log('Gift bubbles overlay WebSocket disconnected. Reconnecting in 3 seconds...');
        setTimeout(connectWebSocket, 3000);
    };

    socket.onerror = (err) => {
        console.error('Gift bubbles overlay WebSocket error:', err);
    };
}

function handleGiftEvent(giftEvent) {
    if (!currentPoll || !currentPoll.is_active || !currentPoll.candidates) return;
    const data = giftEvent.data || {};
    const giftKey = normalizeGiftName(data.gift_name);
    if (!giftKey) return;

    // Only gifts assigned to a candidate get a bubble.
    const candidate = currentPoll.candidates.find(
        c => normalizeGiftName(c.gift_name) === giftKey
    );
    if (!candidate) return;

    // Streakable gifts bubble only when the combo lands (repeat_end === 1).
    const isStreak = data.gift_type === 1;
    if (isStreak && data.repeat_end !== 1) return;

    spawnBubble(candidate, data);
}

function spawnBubble(candidate, data) {
    // Enforce the cap by dropping the oldest bubble still on screen.
    const live = stage.querySelectorAll('.gift-bubble');
    if (live.length >= MAX_BUBBLES) {
        live[0].remove();
    }

    const qty = data.quantity || 1;
    const cardColor = (candidate.color || '').trim() || CARD_PALETTE[(candidate.id || 0) % CARD_PALETTE.length];

    const bubble = document.createElement('div');
    bubble.className = 'gift-bubble';
    bubble.style.setProperty('--bub-color', cardColor);
    bubble.style.setProperty('--bub-glow', hexToRgba(cardColor, 0.6));
    bubble.style.setProperty('--bub-fill', hexToRgba(cardColor, 0.22));
    // Random sway amplitude + direction, spawn position and travel speed so
    // each bubble drifts on its own path.
    bubble.style.setProperty('--sway', (Math.random() * 26 + 8).toFixed(0) + 'px');
    bubble.style.left = (Math.random() * 76 + 10).toFixed(1) + '%';
    const duration = (Math.random() * 3.5 + 6).toFixed(1); // 6s .. 9.5s
    bubble.style.animationDuration = duration + 's';

    const media = candidate.image_url
        ? `<img src="${escapeHTML(candidate.image_url)}" class="bub-img" alt="">`
        : `<div class="bub-img default-avatar" style="background: ${getGradientForName(candidate.name)};">${escapeHTML((candidate.name || '?').charAt(0).toUpperCase())}</div>`;

    const icon = giftIconHtml(data.gift_name, 'bub-gift-icon') || getGiftEmoji(data.gift_name);

    bubble.innerHTML = `
        <div class="bub-card">
            <div class="bub-media">${media}</div>
            <div class="bub-gift">${icon}<span class="bub-qty">&times;${qty}</span></div>
        </div>
        <div class="bub-name">${escapeHTML(candidate.name)}</div>
    `;

    stage.appendChild(bubble);

    // Remove when the float-up animation finishes (plus a safety timeout).
    bubble.addEventListener('animationend', () => bubble.remove());
    setTimeout(() => { if (bubble.isConnected) bubble.remove(); }, (parseFloat(duration) + 2) * 1000);
}

// --- Shared helpers (self-contained for the OBS browser source) -----------

// Futuristic neon palette — fallback border color when the host picked none.
const CARD_PALETTE = ['#00e5ff', '#ff2d78', '#ffd60a', '#7c4dff', '#00ff9d', '#ff9100'];

function hexToRgba(hex, alpha) {
    let h = String(hex || '').trim().replace('#', '');
    if (h.length === 3) h = h.split('').map(ch => ch + ch).join('');
    if (!/^[0-9a-fA-F]{6}$/.test(h)) return `rgba(0, 229, 255, ${alpha})`;
    const n = parseInt(h, 16);
    return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
}

function getGradientForName(name) {
    const colors = [
        ['#00f0ff', '#0072ff'],
        ['#ffd700', '#ff8c00'],
        ['#ff007f', '#7f00ff'],
        ['#00ff87', '#60efff'],
        ['#f5576c', '#f093fb'],
        ['#4facfe', '#00f2fe']
    ];
    let hash = 0;
    for (let i = 0; i < (name || '').length; i++) {
        hash = name.charCodeAt(i) + ((hash << 5) - hash);
    }
    const idx = Math.abs(hash) % colors.length;
    return `linear-gradient(135deg, ${colors[idx][0]}, ${colors[idx][1]})`;
}

function escapeHTML(str) {
    if (!str) return '';
    return str.replace(/[&<>'"]/g,
        tag => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[tag] || tag)
    );
}

function normalizeGiftName(name) {
    return ((name || '').toLowerCase().replace(/[^\w\s]/g, ' ').replace(/\s+/g, ' ').trim());
}

function giftIconKey(name) {
    return ((name || '').toLowerCase().replace(/[^\w\s]/g, ' ').replace(/\s+/g, ' ').trim());
}

function giftIconHtml(giftName, cls) {
    const icons = window.GIFT_ICONS || {};
    const url = icons[giftIconKey(giftName)];
    if (!url) return '';
    return `<img class="${cls}" src="${url}" alt="" loading="lazy" onerror="this.style.display='none'">`;
}

function getGiftEmoji(giftName) {
    if (!giftName) return '🎁';
    const name = giftName.toLowerCase();
    if (name.includes('rose') || name.includes('mawar')) return '🌹';
    if (name.includes('heart') || name.includes('hati')) return '❤️';
    if (name.includes('finger')) return '🫰';
    if (name.includes('corona') || name.includes('crown')) return '👑';
    if (name.includes('diamond') || name.includes('berlian')) return '💎';
    if (name.includes('perfume') || name.includes('parfum')) return '💖';
    if (name.includes('ice cream') || name.includes('es krim')) return '🍦';
    if (name.includes('fire') || name.includes('api')) return '🔥';
    return '🎁';
}
