// Gift Bubbles overlay — incoming gifts spawn small square "bubbles" that
// float up the screen.
//
//   • Gifts ASSIGNED to a candidate  -> a candidate bubble (their photo framed
//     in their border color, gift icon + ×N).
//   • Any OTHER gift                 -> a generic gift bubble (big gift icon +
//     sender name) so every gift still gets a visual.
//
// Counting rule matches the poll: streakable gifts (gift_type === 1) emit one
// event per combo increment, but a bubble only appears once the combo lands
// (repeat_end === 1), so mid-combo events do not flood the screen.
//
// Dedup: a real candidate gift fires BOTH an `event` and a `poll_gift_vote`
// message. The `event` path spawns the bubble (it carries the streak quantity);
// the `poll_gift_vote` path is what the Poll Admin "simulate gift vote" button
// emits on its own, so it only spawns when the gift did NOT just bubble via an
// `event`. This keeps real gifts from bubbling twice while still letting the
// simulation button work.

let socket = null;
let currentPoll = null;

// Hard cap so a gift storm cannot pile up hundreds of bubbles at once.
const MAX_BUBBLES = 18;

// giftKey -> timestamp of the last candidate bubble spawned from an `event`.
const recentCandidateBubbles = new Map();
const DEDUP_MS = 1500;

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
            } else if (msg.type === 'poll_gift_vote') {
                // Candidate gift vote (real boost or the Poll Admin simulate button).
                handlePollGiftVote(msg);
            } else if (msg.type === 'poll_gift_ignored') {
                // Gift matched no candidate and the sender has no vote comment:
                // keep it visible to viewers, but clearly marked as not counted.
                handleIgnoredGift(msg);
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

// Find the candidate a gift is assigned to (by normalized gift name).
function findCandidateByGift(giftName) {
    if (!currentPoll || !currentPoll.is_active || !currentPoll.candidates) return null;
    const giftKey = normalizeGiftName(giftName);
    if (!giftKey) return null;
    return currentPoll.candidates.find(
        c => normalizeGiftName(c.gift_name) === giftKey
    ) || null;
}

// --- Message handlers -------------------------------------------------------

function handleGiftEvent(giftEvent) {
    const data = giftEvent.data || {};
    // Streakable gifts bubble only when the combo lands (repeat_end === 1).
    const isStreak = data.gift_type === 1;
    if (isStreak && data.repeat_end !== 1) return;

    const candidate = findCandidateByGift(data.gift_name);
    if (candidate) {
        spawnCandidateBubble(candidate, data);
        recentCandidateBubbles.set(normalizeGiftName(data.gift_name), Date.now());
    } else if (currentPoll && currentPoll.is_active) {
        // During a poll, unmatched gifts are surfaced by poll_gift_vote
        // (credited via the comment fallback) or poll_gift_ignored (red
        // bubble) — a generic gold bubble here would duplicate or mislead.
        return;
    } else {
        // No active poll — celebrate any gift with a generic bubble.
        spawnGenericBubble(data, giftEvent);
    }
}

function handlePollGiftVote(msg) {
    let candidate = findCandidateByGift(msg.gift_name);
    let dedupKey = normalizeGiftName(msg.gift_name);

    // Comment-fallback vote: no candidate owns this gift, it was credited via
    // the sender's last vote comment. Resolve the bubble target from the
    // credited candidate carried in the broadcast.
    if (!candidate && msg.via_comment && currentPoll && currentPoll.candidates) {
        candidate = currentPoll.candidates.find(c => c.name === msg.candidate_name) || null;
        dedupKey = `candidate:${(msg.candidate_name || '').trim().toLowerCase()}`;
    }
    if (!candidate) return;

    const last = recentCandidateBubbles.get(dedupKey) || 0;
    // A real gift already bubbled via the `event` path a moment ago -> skip.
    if (Date.now() - last < DEDUP_MS) return;

    spawnCandidateBubble(candidate, {
        gift_name: `${msg.gift_name} (via ${msg.via_comment})`,
        quantity: msg.quantity || 1
    });
    recentCandidateBubbles.set(dedupKey, Date.now());
}

// A gift that was counted for NOBODY: spawn the same generic bubble but with
// a red "ignored" treatment and a ❌ badge so the overlay stays honest
// without hiding the gift.
function handleIgnoredGift(msg) {
    const bubble = prepareBubble();
    bubble.classList.add('ignored');

    const iconLarge = giftIconHtml(msg.gift_name, 'bub-gift-big')
        || `<span class="bub-emoji-big">${getGiftEmoji(msg.gift_name)}</span>`;
    const iconSmall = giftIconHtml(msg.gift_name, 'bub-gift-icon') || getGiftEmoji(msg.gift_name);
    const sender = msg.nickname || msg.username || msg.gift_name || '';
    const qty = msg.quantity || 1;
    const avatar = msg.avatar_url || '';

    bubble.innerHTML = `
        <div class="bub-card">
            <div class="bub-media bub-media-generic">${avatar ? `<img class="bub-avatar" src="${escapeHTML(avatar)}" alt="" loading="lazy" onerror="this.replaceWith(Object.assign(document.createElement('span'),{className:'bub-emoji-big',textContent:'🎁'}))">` : iconLarge}</div>
            <div class="bub-gift">${iconSmall}<span class="bub-qty">&times;${qty}</span></div>
            <div class="bub-badge">&#10060;</div>
        </div>
        <div class="bub-name">${escapeHTML(sender)}</div>
    `;
}

// --- Bubble spawning --------------------------------------------------------

// Shared setup: enforce the cap, randomize path/speed, attach cleanup.
function prepareBubble() {
    const live = stage.querySelectorAll('.gift-bubble');
    if (live.length >= MAX_BUBBLES) {
        live[0].remove();
    }

    const bubble = document.createElement('div');
    bubble.className = 'gift-bubble';
    bubble.style.setProperty('--sway', (Math.random() * 26 + 8).toFixed(0) + 'px');
    bubble.style.left = (Math.random() * 76 + 10).toFixed(1) + '%';
    const duration = (Math.random() * 3.5 + 6).toFixed(1); // 6s .. 9.5s
    bubble.style.animationDuration = duration + 's';

    stage.appendChild(bubble);
    bubble.addEventListener('animationend', () => bubble.remove());
    setTimeout(() => { if (bubble.isConnected) bubble.remove(); }, (parseFloat(duration) + 2) * 1000);
    return bubble;
}

function spawnCandidateBubble(candidate, data) {
    const qty = data.quantity || 1;
    const cardColor = (candidate.color || '').trim() || CARD_PALETTE[(candidate.id || 0) % CARD_PALETTE.length];

    const bubble = prepareBubble();
    bubble.style.setProperty('--bub-color', cardColor);
    bubble.style.setProperty('--bub-glow', hexToRgba(cardColor, 0.6));
    bubble.style.setProperty('--bub-fill', hexToRgba(cardColor, 0.22));

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
}

function spawnGenericBubble(data, giftEvent) {
    const qty = data.quantity || 1;
    const accent = '#ffd60a'; // gold — no candidate color to inherit

    const bubble = prepareBubble();
    bubble.classList.add('generic');
    bubble.style.setProperty('--bub-color', accent);
    bubble.style.setProperty('--bub-glow', hexToRgba(accent, 0.6));
    bubble.style.setProperty('--bub-fill', hexToRgba(accent, 0.16));

    const iconLarge = giftIconHtml(data.gift_name, 'bub-gift-big')
        || `<span class="bub-emoji-big">${getGiftEmoji(data.gift_name)}</span>`;
    const iconSmall = giftIconHtml(data.gift_name, 'bub-gift-icon') || getGiftEmoji(data.gift_name);
    const sender = giftEvent.nickname || giftEvent.username || data.gift_name || '';

    bubble.innerHTML = `
        <div class="bub-card">
            <div class="bub-media bub-media-generic">${iconLarge}</div>
            <div class="bub-gift">${iconSmall}<span class="bub-qty">&times;${qty}</span></div>
        </div>
        <div class="bub-name">${escapeHTML(sender)}</div>
    `;
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
