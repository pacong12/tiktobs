// State management
let socket = null;
const recentGifts = [];
const MAX_GIFTS = 10;

// DOM Elements
const giftsList = document.getElementById('gifts-list');
const emptyPlaceholder = document.getElementById('empty-placeholder');
const feedCount = document.getElementById('feed-count');

// Init
document.addEventListener('DOMContentLoaded', () => {
    connectWebSocket();
});

// Map common gifts to emojis
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
                addGiftToFeed({
                    sender: giftEvent.nickname || giftEvent.username,
                    giftName: giftEvent.data.gift_name,
                    quantity: giftEvent.data.quantity || 1
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

    // Add to state
    recentGifts.unshift(gift);
    feedCount.textContent = recentGifts.length;

    // Create DOM element
    const item = document.createElement('div');
    item.className = 'gift-item';
    
    const emoji = getGiftEmoji(gift.giftName);
    
    item.innerHTML = `
        <span class="gift-emoji-badge">${emoji}</span>
        <div class="gift-info">
            <div class="gift-sender">${escapeHTML(gift.sender)}</div>
            <div class="gift-action">sent <span class="gift-name-label">${escapeHTML(gift.giftName)}</span></div>
        </div>
        <div class="gift-multiplier">x${gift.quantity}</div>
    `;

    // Insert at the top of the feed
    giftsList.insertBefore(item, giftsList.firstChild);

    // Enforce max item limits
    const items = giftsList.querySelectorAll('.gift-item');
    if (items.length > MAX_GIFTS) {
        const lastItem = items[items.length - 1];
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
