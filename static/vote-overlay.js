// State variables
let socket = null;

// DOM Elements
const pollContainer = document.getElementById('poll-container');
const inactiveContainer = document.getElementById('inactive-container');
const pollTitle = document.getElementById('poll-title');
const totalVotesSpan = document.getElementById('total-votes');
const candidatesList = document.getElementById('candidates-list');

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
        return;
    }

    // Show active poll container
    inactiveContainer.classList.add('hidden');
    pollContainer.classList.remove('hidden');

    pollTitle.textContent = poll.title;
    totalVotesSpan.textContent = poll.total_votes.toLocaleString();



    // Determine the leading candidate's vote count
    let maxVotes = 0;
    if (poll.total_votes > 0) {
        maxVotes = Math.max(...poll.candidates.map(c => c.votes));
    }

    // Rank candidates: most votes = rank 0 (biggest photo). Sort a copy descending.
    const ranked = [...poll.candidates].sort((a, b) => b.votes - a.votes);
    const count = ranked.length;

    // Photo size scales with candidate count so everything still fits on screen.
    let topSize, restSize;
    if (count <= 4)      { topSize = 110; restSize = 84; }
    else if (count <= 8) { topSize = 96;  restSize = 64; }
    else                 { topSize = 84;  restSize = 50; }

    // Build a vertical grid card (photo on top, name + votes below).
    const buildCard = (c, size) => {
        const isLeading = maxVotes > 0 && c.votes === maxVotes;
        const card = document.createElement('div');
        card.className = `glass-card candidate-card ${isLeading ? 'leading' : ''}`;

        const initialFont = Math.round(size * 0.4);
        const avatarHtml = c.image_url
            ? `<img src="${escapeHTML(c.image_url)}" class="candidate-avatar" alt="Avatar" style="width: ${size}px; height: ${size}px;">`
            : `<div class="candidate-avatar default-avatar" style="background: ${getGradientForName(c.name)}; display: flex; align-items: center; justify-content: center; font-weight: 800; font-size: ${initialFont}px; width: ${size}px; height: ${size}px; text-shadow: 0 1px 4px rgba(0,0,0,0.3);">${escapeHTML(c.name.charAt(0).toUpperCase())}</div>`;

        card.innerHTML = `
            <div class="candidate-number">${c.id}</div>
            ${avatarHtml}
            <div class="candidate-main">
                <div class="candidate-info">
                    <span class="candidate-name">${escapeHTML(c.name)}</span>
                    <span class="candidate-percentage">${c.percentage}%</span>
                </div>
                <div class="progress-track">
                    <div class="progress-fill" style="width: ${c.percentage}%"></div>
                </div>
            </div>
            <div class="candidate-votes">
                <span class="votes-value">${c.votes.toLocaleString()}</span>
                <span class="votes-label">Votes</span>
            </div>
        `;
        return card;
    };

    candidatesList.className = 'candidates-list';
    candidatesList.innerHTML = '';

    // Top 2 (rank #1 & #2) -> grid of 2 columns
    const topGroup = ranked.slice(0, 2);
    const restGroup = ranked.slice(2);

    const topGrid = document.createElement('div');
    topGrid.className = 'candidate-grid grid-top';
    topGroup.forEach(c => topGrid.appendChild(buildCard(c, topSize)));
    candidatesList.appendChild(topGrid);

    // The rest -> grid of 3 columns
    if (restGroup.length > 0) {
        const restGrid = document.createElement('div');
        restGrid.className = 'candidate-grid grid-rest';
        restGroup.forEach(c => restGrid.appendChild(buildCard(c, restSize)));
        candidatesList.appendChild(restGrid);
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
