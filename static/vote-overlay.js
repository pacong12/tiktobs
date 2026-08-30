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

// Throttle DOM updates with requestAnimationFrame
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

// Pagination state
let currentOverlayPage = 0;
const ITEMS_PER_PAGE = 4;
let paginationInterval = null;

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

function startPaginationTimer(totalCandidates) {
    if (paginationInterval) {
        clearInterval(paginationInterval);
        paginationInterval = null;
    }
    const totalPages = Math.ceil(totalCandidates / ITEMS_PER_PAGE);
    if (totalPages > 1) {
        paginationInterval = setInterval(() => {
            currentOverlayPage = (currentOverlayPage + 1) % totalPages;
            if (currentPoll) {
                renderPollView(currentPoll);
            }
        }, 7000); // Ganti halaman setiap 7 detik secara halus
    } else {
        currentOverlayPage = 0;
    }
}

function renderPoll(poll) {
    if (!poll || (!poll.is_active && !poll.is_archived)) {
        currentPoll = poll;
        if (paginationInterval) clearInterval(paginationInterval);
        pollContainer.classList.add('hidden');
        inactiveContainer.classList.remove('hidden');
        return;
    }

    const prevCandidateCount = currentPoll ? currentPoll.candidates.length : 0;
    currentPoll = poll;

    if (prevCandidateCount !== poll.candidates.length) {
        startPaginationTimer(poll.candidates.length);
    }

    inactiveContainer.classList.add('hidden');
    pollContainer.classList.remove('hidden');

    renderPollView(poll);
}

function renderPollView(poll) {
    const allRanked = [...poll.candidates].sort((a, b) => b.votes - a.votes);
    const maxVotes = poll.total_votes > 0 ? Math.max(...allRanked.map(c => c.votes)) : 0;
    const totalCandidates = allRanked.length;
    const totalPages = Math.ceil(totalCandidates / ITEMS_PER_PAGE);

    if (currentOverlayPage >= totalPages) {
        currentOverlayPage = 0;
    }

    // Ambil maksimal 4 kandidat per halaman
    const startIdx = currentOverlayPage * ITEMS_PER_PAGE;
    const pageCandidates = allRanked.slice(startIdx, startIdx + ITEMS_PER_PAGE);

    candidatesList.innerHTML = '';

    const buildCard = (c, rankIdx) => {
        const isLeading = maxVotes > 0 && c.votes === maxVotes;
        const cardColor = (c.color || '').trim() || CARD_PALETTE[rankIdx % CARD_PALETTE.length];
        const card = document.createElement('div');
        card.className = `candidate-card ${isLeading ? 'leading' : ''}`;
        card.dataset.candidateId = String(c.id);
        card.style.setProperty('--card-color', cardColor);

        const bgHtml = c.image_url
            ? `<img src="${escapeHTML(c.image_url)}" class="candidate-bg" alt="">`
            : `<div class="candidate-bg default-avatar">${escapeHTML(c.name.charAt(0).toUpperCase())}</div>`;

        const wins = Number(c.wins) || 0;
        const giftLabel = (c.gift_name || '').trim();
        let giftHtml = '';
        if (giftLabel) {
            const icon = giftIconHtml(giftLabel, 'gift-icon');
            const labelHtml = icon || getGiftEmoji(giftLabel);
            giftHtml = `<span class="card-badge badge-gift" title="${escapeHTML(giftLabel)}">${labelHtml}</span>`;
        }

        card.innerHTML = `
            <div class="candidate-media">${bgHtml}</div>
            <div class="card-header-bar">
                <div class="edge-badges">
                    <span class="card-badge badge-win" title="Round wins this session">win ${wins}&times;</span>
                </div>
                <div class="top-right-col">
                    <div class="candidate-number">${String(c.id).padStart(2, '0')}</div>
                    ${giftHtml}
                </div>
            </div>
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

    const grid = document.createElement('div');
    grid.className = 'candidate-grid cols-2';
    pageCandidates.forEach((c, idx) => {
        grid.appendChild(buildCard(c, startIdx + idx));
    });
    candidatesList.appendChild(grid);

    // Indicator pagination dot jika lebih dari 1 halaman
    if (totalPages > 1) {
        const pageDots = document.createElement('div');
        pageDots.className = 'pagination-indicator';
        for (let i = 0; i < totalPages; i++) {
            const dot = document.createElement('span');
            dot.className = `page-dot ${i === currentOverlayPage ? 'active' : ''}`;
            pageDots.appendChild(dot);
        }
        candidatesList.appendChild(pageDots);
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

const CARD_PALETTE = ['#00e5ff', '#ff2d78', '#ffd60a', '#7c4dff', '#00ff9d', '#ff9100'];

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

function normalizeGiftName(name) {
    return ((name || '').toLowerCase().replace(/[^\w\s]/g, ' ').replace(/\s+/g, ' ').trim());
}

function giftIconKey(name) {
    return ((name || '').toLowerCase().replace(/[^\w\s]/g, ' ').replace(/\s+/g, ' ').trim());
}

function giftIconHtml(giftName, cls) {
    const icons = window.GIFT_ICONS || {};
    const key = giftIconKey(giftName);
    const url = icons[key];
    if (!url) return '';
    return `<img class="${cls}" src="${url}" alt="" loading="lazy">`;
}

function getGiftEmoji(name) {
    const n = (name || '').toLowerCase();
    if (n.includes('rose')) return '🌹';
    if (n.includes('heart')) return '❤️';
    if (n.includes('lion')) return '🦁';
    if (n.includes('galaxy') || n.includes('universe')) return '🌌';
    if (n.includes('diamond')) return '💎';
    if (n.includes('gg')) return '🎮';
    if (n.includes('ice cream')) return '🍦';
    if (n.includes('coffee')) return '☕';
    return '🎁';
}

function handleGiftEventForToast(event) {
    const data = event.data || {};
    const giftName = data.gift_name || '';
    const quantity = Number(data.quantity) || 1;
    const isStreakEnd = Number(data.repeat_end) === 1;
    
    let matchedName = '';
    if (currentPoll && currentPoll.candidates) {
        const norm = normalizeGiftName(giftName);
        const cand = currentPoll.candidates.find(c => normalizeGiftName(c.gift_name) === norm);
        if (cand) matchedName = cand.name;
    }
    if (!matchedName) return;

    showComboToast(giftName, quantity, matchedName, isStreakEnd);
}

function showComboToast(giftName, count, targetName, isFinal) {
    const toast = document.getElementById('combo-toast');
    if (!toast) return;

    const countEl = toast.querySelector('.combo-count');
    const targetEl = toast.querySelector('.combo-target');
    const iconEl = toast.querySelector('.combo-icon');

    if (countEl) countEl.textContent = count;
    if (targetEl) targetEl.textContent = targetName;
    if (iconEl) {
        const icon = giftIconHtml(giftName, 'gift-icon-toast');
        iconEl.innerHTML = icon || getGiftEmoji(giftName);
    }

    toast.classList.remove('hidden');
    toast.classList.add('active');

    clearTimeout(comboToastTimer);
    comboToastTimer = setTimeout(() => {
        toast.classList.remove('active');
        setTimeout(() => toast.classList.add('hidden'), 300);
    }, isFinal ? 3500 : 2000);
}

function handleFallbackVoteToast(msg) {
    showIgnoredToast(`✨ Vote via Komentar: +${msg.votes} untuk ${msg.candidate}`);
}

function handleIgnoredGiftToast(msg) {
    showIgnoredToast(`⚠️ Gift '${msg.gift_name}' tidak terdaftar`);
}

function showIgnoredToast(text) {
    let toast = document.getElementById('ignored-toast');
    if (!toast) {
        toast = document.createElement('div');
        toast.id = 'ignored-toast';
        toast.className = 'ignored-toast';
        document.body.appendChild(toast);
    }
    toast.textContent = text;
    toast.classList.add('show');
    clearTimeout(ignoredToastTimer);
    ignoredToastTimer = setTimeout(() => {
        toast.classList.remove('show');
    }, 2800);
}
