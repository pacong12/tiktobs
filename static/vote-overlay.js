// State variables
let socket = null;
let currentPoll = null;
let comboToastTimer = null;
let ignoredToastTimer = null;

// DOM Elements
const pollContainer = document.getElementById('poll-container');
const inactiveContainer = document.getElementById('inactive-container');
const candidatesList = document.getElementById('candidates-list');

// Init overlay
document.addEventListener('DOMContentLoaded', () => {
    initOverlay();
});

async function initOverlay() {
    await fetchPollStatus();
    connectWebSocket();
}

// Fetch current poll status or latest archived round on load
async function fetchPollStatus() {
    try {
        const baseUrl = window.location.protocol === 'file:' ? 'http://127.0.0.1:8000' : '';
        const response = await fetch(`${baseUrl}/api/poll/status`);
        const poll = await response.json();
        
        if (!poll || !poll.is_active) {
            // Fetch latest archived round if active poll doesn't exist
            const roundsRes = await fetch(`${baseUrl}/api/poll/rounds?limit=1`);
            const roundsData = await roundsRes.json();
            if (roundsData.rounds && roundsData.rounds.length > 0) {
                const latestRound = roundsData.rounds[0];
                const lastPoll = {
                    is_active: false,
                    is_archived: true,
                    title: latestRound.title,
                    round_name: latestRound.round_name,
                    total_votes: latestRound.total_votes,
                    candidates: latestRound.candidates
                };
                renderPoll(lastPoll);
                return;
            }
        }
        renderPoll(poll);
    } catch (error) {
        console.error('Failed to fetch poll status:', error);
    }
}

// Render the active poll or inactive state (supports displaying the latest archived round)
function renderPoll(poll) {
    if (!poll || (!poll.is_active && !poll.is_archived)) {
        currentPoll = poll;
        pollContainer.classList.add('hidden');
        inactiveContainer.classList.remove('hidden');
        return;
    }

    // Show active or archived poll container
    inactiveContainer.classList.add('hidden');
    pollContainer.classList.remove('hidden');

    // Rank candidates: most votes first. Sort a copy descending.
    const ranked = [...poll.candidates].sort((a, b) => b.votes - a.votes);

    // In-place update: If card elements already exist and ranking order hasn't changed, update ONLY numbers and percentages in DOM
    const existingCards = candidatesList.querySelectorAll('.candidate-card');
    const sameRankOrder = currentPoll && (currentPoll.is_active || currentPoll.is_archived) &&
        currentPoll.candidates.length === poll.candidates.length &&
        existingCards.length === ranked.length &&
        ranked.every((c, i) => String(c.id) === existingCards[i].dataset.candidateId);

    if (sameRankOrder && currentPoll.is_archived === poll.is_archived) {
        let maxVotes = poll.total_votes > 0 ? Math.max(...poll.candidates.map(c => c.votes)) : 0;
        ranked.forEach((c, i) => {
            const card = existingCards[i];
            const isLeading = maxVotes > 0 && c.votes === maxVotes;
            card.classList.toggle('leading', isLeading);

            const votesEl = card.querySelector('.candidate-votes');
            const pctEl = card.querySelector('.candidate-pct');
            const winEl = card.querySelector('.badge-win');

            if (votesEl) votesEl.textContent = c.votes.toLocaleString();
            if (pctEl) pctEl.textContent = `${c.percentage}%`;

            const wins = Number(c.wins) || 0;
            if (winEl) {
                if (wins > 0) {
                    winEl.innerHTML = `win ${wins}&times;`;
                    if (winEl.parentElement) winEl.parentElement.style.display = '';
                } else {
                    const edgeWrap = card.querySelector('.edge-badges');
                    if (edgeWrap) edgeWrap.remove();
                }
            } else if (wins > 0) {
                const edgeBadges = document.createElement('div');
                edgeBadges.className = 'edge-badges';
                edgeBadges.innerHTML = `<span class="card-badge badge-win" title="Round wins this session">win ${wins}&times;</span>`;
                card.insertBefore(edgeBadges, card.firstChild);
            }
        });
        currentPoll = poll;
        return;
    }

    currentPoll = poll;

    // Determine the leading candidate's vote count
    let maxVotes = 0;
    if (poll.total_votes > 0) {
        maxVotes = Math.max(...poll.candidates.map(c => c.votes));
    }

    const count = ranked.length;

    candidatesList.className = 'candidates-list';
    candidatesList.innerHTML = '';

    const buildCard = (c, rankIdx) => {
        const isLeading = maxVotes > 0 && c.votes === maxVotes;
        const cardColor = (c.color || '').trim() || CARD_PALETTE[rankIdx % CARD_PALETTE.length];
        const card = document.createElement('div');
        card.className = `candidate-card ${isLeading ? 'leading' : ''}`;
        card.dataset.candidateId = String(c.id);
        card.style.setProperty('--card-color', cardColor);
        card.style.setProperty('--card-glow', hexToRgba(cardColor, 0.55));
        card.style.setProperty('--card-glow-soft', hexToRgba(cardColor, 0.26));
        // Thin (subtle) color gradient so the transparent card is not empty,
        // yet still lets the no-bg PNG photo show through.
        // Thin background gradient tinted with the BORDER color so each card
        // clearly carries its candidate color (still subtle enough for no-bg PNGs).
        card.style.setProperty('--card-fill-a', hexToRgba(cardColor, 0.20));
        card.style.setProperty('--card-fill-b', hexToRgba(cardColor, 0.06));
        card.style.setProperty('--card-fill-gift', hexToRgba(cardColor, 0.30));
        card.style.setProperty('--card-fill-panel', hexToRgba(cardColor, 0.80));

        const bgHtml = c.image_url
            ? `<img src="${escapeHTML(c.image_url)}" class="candidate-bg" alt="">`
            : `<div class="candidate-bg default-avatar" style="background: ${getGradientForName(c.name)};">${escapeHTML(c.name.charAt(0).toUpperCase())}</div>`;

        // Win badge pins onto the top-LEFT border; the gift badge sits in the
        // top-RIGHT column directly below the number chip (thin gradient bg).
        const wins = Number(c.wins) || 0;
        const giftLabel = (c.gift_name || '').trim();
        const winHtml = wins > 0
            ? `<div class="edge-badges"><span class="card-badge badge-win" title="Round wins this session">win ${wins}&times;</span></div>`
            : '';
        let giftHtml = '';
        if (giftLabel) {
            // Icon only (no text); hover shows the gift name. Falls back to
            // the emoji alone when the gift has no known icon.
            const icon = giftIconHtml(giftLabel, 'gift-icon');
            const labelHtml = icon || getGiftEmoji(giftLabel);
            giftHtml = `<span class="card-badge badge-gift" title="${escapeHTML(giftLabel)}">${labelHtml}</span>`;
        }

        card.innerHTML = `
            <div class="candidate-media">${bgHtml}</div>
            ${winHtml}
            <div class="top-right-col">
                <div class="candidate-number">${String(c.id).padStart(2, '0')}</div>
                ${giftHtml}
            </div>
            <div class="candidate-info-bg"></div>
            <div class="candidate-info">
                <div class="candidate-info-row">
                    <span class="candidate-votes">${c.votes.toLocaleString()}</span>
                    <span class="candidate-pct">${c.percentage}%</span>
                </div>
                <div class="candidate-name">${escapeHTML(c.name)}</div>
            </div>
        `;
        return card;
    };

    if (count >= 5) {
        const bentoGrid = document.createElement('div');
        bentoGrid.className = 'candidate-grid grid-bento';
        ranked.slice(0, 3).forEach((c, i) => {
            const card = buildCard(c, i);
            if (i === 0) card.classList.add('rank-1');
            bentoGrid.appendChild(card);
        });
        candidatesList.appendChild(bentoGrid);

        const rest = ranked.slice(3);
        if (rest.length > 0) {
            const restGrid = document.createElement('div');
            restGrid.className = 'candidate-grid grid-rest';
            rest.forEach((c, i) => restGrid.appendChild(buildCard(c, i + 3)));
            candidatesList.appendChild(restGrid);
        }
    } else if (count === 3) {
        // Champion (most votes) gets the big wide card on top; the other
        // two render as squares directly below it.
        const grid = document.createElement('div');
        grid.className = 'candidate-grid grid-top3';
        ranked.forEach((c, i) => {
            const card = buildCard(c, i);
            if (i === 0) card.classList.add('rank-1');
            grid.appendChild(card);
        });
        candidatesList.appendChild(grid);
    } else {
        const grid = document.createElement('div');
        grid.className = 'candidate-grid cols-2';
        ranked.forEach((c, i) => grid.appendChild(buildCard(c, i)));
        candidatesList.appendChild(grid);
    }
}

function connectWebSocket() {
    const wsUrl = window.location.protocol === 'file:' 
        ? 'ws://127.0.0.1:8000/ws' 
        : `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws`;

    socket = new WebSocket(wsUrl);

    socket.onopen = () => {
        console.log('Poll overlay WebSocket connected.');
    };

    socket.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            if (msg.type === 'poll_update') {
                if (!msg.poll || !msg.poll.is_active) {
                    fetchPollStatus();
                } else {
                    renderPoll(msg.poll);
                }
            } else if (msg.type === 'poll_round_archived') {
                fetchPollStatus();
            }
        } catch (error) {
            console.error('Error handling WebSocket message:', error);
        }
    };

    socket.onclose = () => {
        console.log('Poll overlay WebSocket disconnected. Reconnecting in 3 seconds...');
        setTimeout(connectWebSocket, 3000);
    };

    socket.onerror = (err) => {
        console.error('Poll overlay WebSocket error:', err);
    };
}

// Futuristic neon palette — fallback border color per candidate when the
// host did not pick one in the Poll Admin.
const CARD_PALETTE = ['#00e5ff', '#ff2d78', '#ffd60a', '#7c4dff', '#00ff9d', '#ff9100'];

// Converts #rrggbb (or #rgb) to an rgba() string for glow effects.
function hexToRgba(hex, alpha) {
    let h = String(hex || '').trim().replace('#', '');
    if (h.length === 3) h = h.split('').map(ch => ch + ch).join('');
    if (!/^[0-9a-fA-F]{6}$/.test(h)) return `rgba(0, 229, 255, ${alpha})`;
    const n = parseInt(h, 16);
    return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
}

// Generate deterministic linear gradients based on candidate name string hash
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
    for (let i = 0; i < name.length; i++) {
        hash = name.charCodeAt(i) + ((hash << 5) - hash);
    }
    const idx = Math.abs(hash) % colors.length;
    return `linear-gradient(135deg, ${colors[idx][0]}, ${colors[idx][1]})`;
}

// Helper: Escape HTML
function escapeHTML(str) {
    if (!str) return '';
    return str.replace(/[&<>'"]/g, 
        tag => ({
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            "'": '&#39;',
            '"': '&quot;'
        }[tag] || tag)
    );
}

// --- Live combo toast -------------------------------------------------------
// Streakable gifts (gift_type === 1) emit one event per combo increment.
// While votes are only tallied once at the final event (repeat_end === 1),
// this toast gives instant visual feedback: the counter climbs live and the
// candidate receiving the combo is named.

function normalizeGiftName(name) {
    return ((name || '').toLowerCase().replace(/[^\w\s]/g, ' ').replace(/\s+/g, ' ').trim());
}

// Normalized key for the GIFT_ICONS map (same rules as the backend:
// lowercase, emoji/punctuation stripped, whitespace collapsed).
function giftIconKey(name) {
    return ((name || '').toLowerCase().replace(/[^\w\s]/g, ' ').replace(/\s+/g, ' ').trim());
}

// Returns an <img> tag with the official TikTok gift icon, or '' when the
// gift has no known icon (callers fall back to the emoji mapping).
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

function handleGiftEventForToast(giftEvent) {
    if (!currentPoll || !currentPoll.is_active || !currentPoll.candidates) return;
    const data = giftEvent.data || {};
    const giftKey = normalizeGiftName(data.gift_name);
    if (!giftKey) return;

    // Only gifts assigned to a candidate deserve the spotlight.
    const candidate = currentPoll.candidates.find(
        c => normalizeGiftName(c.gift_name) === giftKey
    );
    if (!candidate) return;

    const toast = document.getElementById('combo-toast');
    if (!toast) return;

    const isFinal = data.repeat_end === 1;
    const quantity = data.quantity || 1;
    const toastIcon = giftIconHtml(data.gift_name, 'gift-icon gift-icon-toast');
    const toastGift = toastIcon
        ? `${toastIcon} ${escapeHTML(data.gift_name)}`
        : `${getGiftEmoji(data.gift_name)} ${escapeHTML(data.gift_name)}`;
    toast.innerHTML = `
        <span class="combo-toast-gift">${toastGift}</span>
        <span class="combo-toast-count">&times;${quantity}</span>
        <span class="combo-toast-target">&#10148; ${escapeHTML(candidate.name)}</span>
    `;
    toast.classList.remove('show', 'combo-pulse', 'final');
    void toast.offsetWidth; // restart animations
    toast.classList.add('show', 'combo-pulse');
    if (isFinal) toast.classList.add('final');

    clearTimeout(comboToastTimer);
    // Mid-combo: stay until the next increment arrives (or the combo stalls).
    // Final: linger a moment so the landing is visible.
    comboToastTimer = setTimeout(
        () => toast.classList.remove('show'),
        isFinal ? 2500 : 9000
    );
}

// --- Comment-fallback vote toast --------------------------------------------
// A gift that matched no candidate was credited via the sender's last vote
// comment. Show it on the combo toast with a "via komentar" note so viewers
// understand where the votes came from.

function handleFallbackVoteToast(msg) {
    const toast = document.getElementById('combo-toast');
    if (!toast) return;

    const toastIcon = giftIconHtml(msg.gift_name, 'gift-icon gift-icon-toast');
    const toastGift = toastIcon
        ? `${toastIcon} ${escapeHTML(msg.gift_name)}`
        : `${getGiftEmoji(msg.gift_name)} ${escapeHTML(msg.gift_name)}`;
    toast.innerHTML = `
        <span class="combo-toast-gift">${toastGift}</span>
        <span class="combo-toast-count">+${msg.votes_added}</span>
        <span class="combo-toast-target">&#10148; ${escapeHTML(msg.candidate_name)}</span>
        <span class="combo-toast-note">via komentar "${escapeHTML(msg.via_comment)}"</span>
    `;
    toast.classList.remove('show', 'combo-pulse', 'final');
    void toast.offsetWidth; // restart animations
    toast.classList.add('show', 'combo-pulse', 'final');

    clearTimeout(comboToastTimer);
    comboToastTimer = setTimeout(() => toast.classList.remove('show'), 3500);
}

// --- Ignored gift toast -------------------------------------------------------
// Gift counted for NOBODY (no candidate owns it and the sender never voted by
// comment this round). Shown on-stream so the sender gets direct feedback and
// learns the correct flow: comment the candidate number first, then gift.

function handleIgnoredGiftToast(msg) {
    const toast = document.getElementById('ignored-toast');
    if (!toast) return;

    const icon = giftIconHtml(msg.gift_name, 'gift-icon gift-icon-toast')
        || getGiftEmoji(msg.gift_name);
    toast.innerHTML = `
        <span class="ignored-toast-badge">&#9888;&#65039;</span>
        <span>${icon} ${escapeHTML(msg.gift_name)} dari ${escapeHTML(msg.nickname || msg.username)}
        <b>tidak dihitung</b> &mdash; komentar nomor/nama kandidat dulu, baru gift!</span>
    `;
    toast.classList.remove('show');
    void toast.offsetWidth; // restart transition
    toast.classList.add('show');

    clearTimeout(ignoredToastTimer);
    ignoredToastTimer = setTimeout(() => toast.classList.remove('show'), 5000);
}
