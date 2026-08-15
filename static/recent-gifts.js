// State management
let socket = null;
const recentGifts = [];
const MAX_GIFTS = 10;

// Active streak combos: key -> DOM row. A streakable gift (gift_type === 1)
// emits one event per combo increment; instead of adding a new row for every
// increment, all of them update a single "Gift xN" row in place until the
// combo ends (repeat_end === 1).
const activeCombos = new Map();

function comboKey(username, giftName) {
    return `${(username || '').toLowerCase()}|${(giftName || '').toLowerCase()}`;
}

// DOM Elements
const giftsList = document.getElementById('gifts-list');
const emptyPlaceholder = document.getElementById('empty-placeholder');
const feedCount = document.getElementById('feed-count');

// Init
document.addEventListener('DOMContentLoaded', () => {
    connectWebSocket();
});

// Normalized key for the GIFT_ICONS map (same rules as the backend:
// lowercase, emoji/punctuation stripped, whitespace collapsed).
function giftIconKey(name) {
    return ((name || '').toLowerCase().replace(/[^\w\s]/g, ' ').replace(/\s+/g, ' ').trim());
}

// Official TikTok gift icon <img>, or '' when the gift has no known icon
// (callers fall back to the emoji mapping). On load error the img replaces
// itself with the emoji fallback so the badge is never empty.
function giftIconHtml(giftName, cls) {
    const icons = window.GIFT_ICONS || {};
    const url = icons[giftIconKey(giftName)];
    if (!url) return '';
    const fallback = getGiftEmoji(giftName);
    return `<img class="${cls}" src="${url}" alt="" loading="lazy" data-fallback="${fallback}" onerror="this.outerHTML=this.dataset.fallback">`;
}

// Map common gifts to emojis (fallback when no official icon is available)
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

function escapeHTML(str) {
    if (!str) return '';
    return str.replace(/[&<>'"]/g, 
        tag => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[tag] || tag)
    );
}

function connectWebSocket() {
    const wsUrl = window.location.protocol === 'file:' 
        ? 'ws://127.0.0.1:8000/ws' 
        : `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws`;

    socket = new WebSocket(wsUrl);

    socket.onopen = () => {
        console.log('Recent gifts feed WebSocket connected.');
    };

    socket.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            if (msg.type === 'event' && msg.event && msg.event.event_type === 'gift') {
                const giftEvent = msg.event;
                const data = giftEvent.data || {};
                addGiftToFeed({
                    sender: giftEvent.nickname || giftEvent.username,
                    username: giftEvent.username,
                    giftName: data.gift_name,
                    quantity: data.quantity || 1,
                    streak: data.gift_type === 1,
                    final: data.repeat_end === 1
                });
            }
        } catch (error) {
            console.error('Error processing WS recent-gifts message:', error);
        }
    };

    socket.onclose = () => {
        console.log('Recent gifts feed WebSocket closed. Reconnecting in 3 seconds...');
        setTimeout(connectWebSocket, 3000);
    };

    socket.onerror = (err) => {
        console.error('Recent gifts feed WebSocket error:', err);
    };
}

function addGiftToFeed(gift) {
    // Hide placeholder
    if (emptyPlaceholder) {
        emptyPlaceholder.style.display = 'none';
    }

    const key = comboKey(gift.username, gift.giftName);

    // Combo already on screen: just bump the multiplier in place.
    if (gift.streak) {
        const existing = activeCombos.get(key);
        if (existing && existing.isConnected) {
            const mult = existing.querySelector('.gift-multiplier');
            if (mult) mult.textContent = `x${gift.quantity}`;
            existing.classList.remove('combo-pulse');
            void existing.offsetWidth; // restart the CSS animation
            existing.classList.add('combo-pulse');
            if (gift.final) activeCombos.delete(key);
            return;
        }
        activeCombos.delete(key); // stale entry, if any
    }

    // Add to state
    recentGifts.unshift(gift);
    feedCount.textContent = recentGifts.length;

    // Create DOM element
    const item = document.createElement('div');
    item.className = 'gift-item';

    const badge = giftIconHtml(gift.giftName, 'gift-icon-img')
        || `<span class="gift-emoji-fallback">${getGiftEmoji(gift.giftName)}</span>`;

    item.innerHTML = `
        <span class="gift-emoji-badge">${badge}</span>
        <div class="gift-info">
            <div class="gift-sender">${escapeHTML(gift.sender)}</div>
            <div class="gift-action">sent <span class="gift-name-label">${escapeHTML(gift.giftName)}</span></div>
        </div>
        <div class="gift-multiplier">x${gift.quantity}</div>
    `;

    // Insert at the top of the feed
    giftsList.insertBefore(item, giftsList.firstChild);

    // An ongoing combo owns its row until the final event arrives.
    if (gift.streak && !gift.final) {
        activeCombos.set(key, item);
    }

    // Enforce max item limits
    const items = giftsList.querySelectorAll('.gift-item');
    if (items.length > MAX_GIFTS) {
        const lastItem = items[items.length - 1];
        for (const [k, el] of activeCombos) {
            if (el === lastItem) activeCombos.delete(k);
        }
        lastItem.classList.add('fade-out');

        // Remove after transition finishes
        setTimeout(() => {
            if (lastItem.parentNode === giftsList) {
                giftsList.removeChild(lastItem);
            }
        }, 350);

        recentGifts.pop();
    }
}
