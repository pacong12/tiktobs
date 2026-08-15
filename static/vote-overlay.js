// State variables
let socket = null;

// DOM Elements
const pollContainer = document.getElementById('poll-container');
const inactiveContainer = document.getElementById('inactive-container');
const pollTitle = document.getElementById('poll-title');
const totalVotesSpan = document.getElementById('total-votes');
const candidatesList = document.getElementById('candidates-list');
const pollCountdown = document.getElementById('poll-countdown');
const pollCountdownTime = document.getElementById('poll-countdown-time');

// Countdown state
let expiresAtMs = null;
let countdownInterval = null;

function formatCountdown(totalSeconds) {
    const s = Math.max(0, totalSeconds);
    const m = Math.floor(s / 60);
    const sec = s % 60;
    return `${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`;
}

function updateCountdownDisplay() {
    if (expiresAtMs === null) return;
    const remaining = Math.floor((expiresAtMs - Date.now()) / 1000);
    pollCountdownTime.textContent = formatCountdown(remaining);
    if (remaining <= 10) {
        pollCountdown.classList.add('urgent');
    } else {
        pollCountdown.classList.remove('urgent');
    }
}

function startCountdown(expiresAtIso) {
    if (!expiresAtIso) {
        expiresAtMs = null;
        pollCountdown.classList.add('hidden');
        if (countdownInterval) { clearInterval(countdownInterval); countdownInterval = null; }
        return;
    }
    expiresAtMs = new Date(expiresAtIso).getTime();
    pollCountdown.classList.remove('hidden');
    updateCountdownDisplay();
    if (!countdownInterval) {
        countdownInterval = setInterval(updateCountdownDisplay, 1000);
    }
}

// Init overlay
document.addEventListener('DOMContentLoaded', () => {
    initOverlay();
});

async function initOverlay() {
    await fetchPollStatus();
    connectWebSocket();
}

// Fetch current poll status on load
async function fetchPollStatus() {
    try {
        const baseUrl = window.location.protocol === 'file:' ? 'http://127.0.0.1:8000' : '';
        const response = await fetch(`${baseUrl}/api/poll/status`);
        const poll = await response.json();
        renderPoll(poll);
    } catch (error) {
        console.error('Failed to fetch poll status:', error);
    }
}

// Render the active poll or inactive state
function renderPoll(poll) {
    if (!poll || !poll.is_active) {
        pollContainer.classList.add('hidden');
        inactiveContainer.classList.remove('hidden');
        startCountdown(null);
        return;
    }

    // Show active poll container
    inactiveContainer.classList.add('hidden');
    pollContainer.classList.remove('hidden');

    pollTitle.textContent = poll.title;
    startCountdown(poll.expires_at);
    totalVotesSpan.textContent = poll.total_votes.toLocaleString();



    // Determine the leading candidate's vote count
    let maxVotes = 0;
    if (poll.total_votes > 0) {
        maxVotes = Math.max(...poll.candidates.map(c => c.votes));
    }

    // Rank candidates: most votes first. Sort a copy descending.
    const ranked = [...poll.candidates].sort((a, b) => b.votes - a.votes);

    // Layout tiers (all cards stay square):
    //   2 candidates   -> 2 large squares side by side (duel view)
    //   3 candidates   -> 3 large squares in one row
    //   4 candidates   -> 2x2 large squares
    //   5+ candidates  -> BENTO: rank #1 gets a huge 2x2 square, ranks #2/#3
    //                     fill the right column as squares, every remaining
    //                     candidate becomes a small square below.
    // Because `ranked` is sorted by votes, the bento positions follow the
    // live ranking and re-shuffle as votes come in.
    const count = ranked.length;

    candidatesList.className = 'candidates-list';
    candidatesList.innerHTML = '';
    // Build a card where the candidate photo fills the whole card; the vote
    // badge floats in the top-right corner and the progress bar + percentage
    // float along the bottom (all layered above the photo).
    const buildCard = (c) => {
        const isLeading = maxVotes > 0 && c.votes === maxVotes;
        const card = document.createElement('div');
        card.className = `glass-card candidate-card ${isLeading ? 'leading' : ''}`;

        const bgHtml = c.image_url
            ? `<img src="${escapeHTML(c.image_url)}" class="candidate-bg" alt="">`
            : `<div class="candidate-bg default-avatar" style="background: ${getGradientForName(c.name)};">${escapeHTML(c.name.charAt(0).toUpperCase())}</div>`;

        card.innerHTML = `
            <div class="candidate-media">
                ${bgHtml}
                <div class="candidate-scrim"></div>
            </div>
            <div class="candidate-number">${c.id}</div>
            <div class="candidate-badge"><span class="votes-value">${c.votes.toLocaleString()}</span> votes</div>
            <div class="candidate-overlay">
                <span class="candidate-name">${escapeHTML(c.name)}</span>
                <div class="candidate-bottom">
                    <div class="progress-track">
                        <div class="progress-fill" style="width: ${c.percentage}%"></div>
                    </div>
                    <span class="candidate-percentage">${c.percentage}%</span>
                </div>
            </div>
        `;
        return card;
    };

    if (count >= 5) {
        const bentoGrid = document.createElement('div');
        bentoGrid.className = 'candidate-grid grid-bento';
        ranked.slice(0, 3).forEach((c, i) => {
            const card = buildCard(c);
            if (i === 0) card.classList.add('rank-1');
            bentoGrid.appendChild(card);
        });
        candidatesList.appendChild(bentoGrid);

        const rest = ranked.slice(3);
        if (rest.length > 0) {
            const restGrid = document.createElement('div');
            restGrid.className = 'candidate-grid grid-rest';
            rest.forEach(c => restGrid.appendChild(buildCard(c)));
            candidatesList.appendChild(restGrid);
        }
    } else {
        const grid = document.createElement('div');
        grid.className = 'candidate-grid ' + (count === 3 ? 'cols-3' : 'cols-2');
        ranked.forEach(c => grid.appendChild(buildCard(c)));
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
                renderPoll(msg.poll);
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
