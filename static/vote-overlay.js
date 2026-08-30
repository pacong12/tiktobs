// --- Audio Alert for TikTok LIVE Studio & Web Browsers ---------------------
let audioCtx = null;
let customSoundBuffer = null;
let alertVolume = 1.0;
let lastSoundPath = '';

const fallbackSoundPaths = [
    'sounds/dragon-studio-thud-sound-effect-405470.mp3',
    'sounds/vote-gift-alert.wav',
    'sounds/vote-gift-alert.mp3'
];

async function initWebAudio() {
    try {
        audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    } catch (e) {
        console.error("Web Audio init error:", e);
    }
    await loadConfiguredSound();
}

async function loadConfiguredSound() {
    const baseUrl = window.location.protocol === 'file:' ? 'http://127.0.0.1:8000/' : '';
    let filesToTry = fallbackSoundPaths;
    try {
        const res = await fetch(baseUrl + 'api/sounds');
        if (res.ok) {
            const data = await res.json();
            const cfg = data.config || {};
            if (typeof cfg.vote_volume === 'number') alertVolume = cfg.vote_volume;
            if (cfg.vote_sound) {
                filesToTry = ['sounds/' + cfg.vote_sound];
            } else if (data.sounds && data.sounds.length > 0) {
                filesToTry = data.sounds.map(f => 'sounds/' + f);
            }
        }
    } catch (e) {
        console.warn("Could not fetch sounds list:", e);
    }

    customSoundBuffer = null;
    if (audioCtx) {
        for (const path of filesToTry) {
            try {
                const response = await fetch(baseUrl + path);
                if (response.ok) {
                    const arrayBuffer = await response.arrayBuffer();
                    customSoundBuffer = await audioCtx.decodeAudioData(arrayBuffer);
                    lastSoundPath = path;
                    break;
                }
            } catch (err) {
                console.warn(`Could not decode audio ${path}:`, err);
            }
        }
    }
}

function playAlertSound() {
    const baseUrl = window.location.protocol === 'file:' ? 'http://127.0.0.1:8000/' : '';
    try {
        if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        if (audioCtx.state === 'suspended') audioCtx.resume();
        if (customSoundBuffer) {
            const source = audioCtx.createBufferSource();
            source.buffer = customSoundBuffer;
            const gainNode = audioCtx.createGain();
            gainNode.gain.value = alertVolume;
            source.connect(gainNode);
            gainNode.connect(audioCtx.destination);
            source.start(0);
        } else {
            playDefaultChime();
        }
    } catch (err) {
        console.warn("Web Audio API play error:", err);
    }
}

function playDefaultChime() {
    try {
        if (!audioCtx) return;
        const playNote = (freq, delay, duration) => {
            const osc = audioCtx.createOscillator();
            const gainNode = audioCtx.createGain();
            osc.type = 'triangle';
            osc.frequency.setValueAtTime(freq, audioCtx.currentTime + delay);
            gainNode.gain.setValueAtTime(0, audioCtx.currentTime + delay);
            gainNode.gain.linearRampToValueAtTime(0.25, audioCtx.currentTime + delay + 0.04);
            gainNode.gain.exponentialRampToValueAtTime(0.0001, audioCtx.currentTime + delay + duration);
            osc.connect(gainNode);
            gainNode.connect(audioCtx.destination);
            osc.start(audioCtx.currentTime + delay);
            osc.stop(audioCtx.currentTime + delay + duration);
        };
        playNote(523.25, 0.0, 0.5);
        playNote(659.25, 0.12, 0.5);
        playNote(783.99, 0.24, 0.7);
    } catch (err) {
        console.error('Synth sound failed:', err);
    }
}

// Throttle DOM updates with requestAnimationFrame to eliminate lag during spam/high vote bursts
let pendingPollData = null;
let rafId = null;

function scheduleRenderPoll(poll) {
    pendingPollData = poll;
    if (!rafId) {
        rafId = requestAnimationFrame(() => {
            rafId = null;
            if (pendingPollData) {
                renderPoll(pendingPollData);
            }
        });
    }
}

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
    initWebAudio();
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
                    candidates: (latestRound.candidates || []).map(c => {
                        const statusCand = poll && poll.candidates && poll.candidates.find(pc => pc.name.trim().toLowerCase() === c.name.trim().toLowerCase());
                        const winsVal = (statusCand && statusCand.wins !== undefined && statusCand.wins !== null)
                            ? statusCand.wins
                            : (c.wins !== undefined && c.wins !== null ? c.wins : 0);
                        return { ...c, wins: winsVal };
                    })
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

    // If rank order changed or card structure not yet present, rebuild grid to reflect leader rank position smoothly
    const existingCards = candidatesList.querySelectorAll('.candidate-card');
    const sameCandidateOrder = existingCards.length === poll.candidates.length &&
        ranked.every((c, i) => existingCards[i] && existingCards[i].dataset.candidateId === String(c.id));

    if (sameCandidateOrder) {
        let maxVotes = poll.total_votes > 0 ? Math.max(...poll.candidates.map(c => c.votes)) : 0;
        ranked.forEach((c, i) => {
            const card = existingCards[i];
            if (!card) return;
            const isLeading = maxVotes > 0 && c.votes === maxVotes;
            card.classList.toggle('leading', isLeading);

            const votesEl = card.querySelector('.candidate-votes');
            const pctEl = card.querySelector('.candidate-pct');
            const winEl = card.querySelector('.badge-win');

            if (votesEl && votesEl.textContent !== c.votes.toLocaleString()) {
                votesEl.textContent = c.votes.toLocaleString();
            }
            if (pctEl && pctEl.textContent !== `${c.percentage}%`) {
                pctEl.textContent = `${c.percentage}%`;
            }

            const wins = Number(c.wins) || 0;
            if (winEl) {
                winEl.innerHTML = `win ${wins}&times;`;
            } else {
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
        const winHtml = `<div class="edge-badges"><span class="card-badge badge-win" title="Round wins this session">win ${wins}&times;</span></div>`;
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

let reconnectTimeout = null;

function connectWebSocket() {
    clearTimeout(reconnectTimeout);
    reconnectTimeout = null;
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
                if (msg.poll && msg.poll.is_active) {
                    scheduleRenderPoll(msg.poll);
                } else {
                    fetchPollStatus();
                }
            } else if (msg.type === 'poll_round_archived') {
                fetchPollStatus();
            } else if (msg.type === 'poll_gift_vote') {
                if (msg.poll && msg.poll.is_active) {
                    scheduleRenderPoll(msg.poll);
                }
                playAlertSound();
                handleGiftEventForToast({
                    data: {
                        gift_name: msg.gift_name,
                        quantity: msg.quantity || 1,
                        repeat_end: 1
                    }
                });
            } else if (msg.type === 'poll_fallback_vote') {
                playAlertSound();
                handleFallbackVoteToast(msg);
            } else if (msg.type === 'poll_gift_ignored') {
                handleIgnoredGiftToast(msg);
            }
        } catch (error) {
            console.error('Error handling WebSocket message:', error);
        }
    };
    socket.onclose = () => {
        console.log('Poll overlay WebSocket disconnected. Reconnecting in 3 seconds...');
        clearTimeout(reconnectTimeout);
        reconnectTimeout = setTimeout(connectWebSocket, 3000);
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
    toast.classList.add('show');
    if (isFinal) toast.classList.add('final');

    clearTimeout(comboToastTimer);
    comboToastTimer = setTimeout(
        () => toast.classList.remove('show', 'final'),
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
    toast.classList.add('show');

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
    toast.classList.add('show');

    clearTimeout(ignoredToastTimer);
    ignoredToastTimer = setTimeout(() => toast.classList.remove('show'), 5000);
}
