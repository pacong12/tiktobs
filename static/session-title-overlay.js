// State variables
let socket = null;
let currentPoll = null;

// DOM Elements
const sessionTitleContainer = document.getElementById('session-title-container');
const inactiveContainer = document.getElementById('inactive-container');
const roundBadge = document.getElementById('round-badge');
const pollTitleText = document.getElementById('poll-title-text');

// Init overlay
document.addEventListener('DOMContentLoaded', () => {
    initOverlay();
});

async function initOverlay() {
    await fetchPollStatus();
    connectWebSocket();
}

// Fetch current poll status on load (or latest archived round if active poll ended)
async function fetchPollStatus() {
    try {
        const baseUrl = window.location.protocol === 'file:' ? 'http://127.0.0.1:8000' : '';
        const response = await fetch(`${baseUrl}/api/poll/status`);
        const poll = await response.json();

        if (!poll || !poll.is_active) {
            // Fetch latest archived round
            const roundsRes = await fetch(`${baseUrl}/api/poll/rounds?limit=1`);
            const roundsData = await roundsRes.json();
            if (roundsData.rounds && roundsData.rounds.length > 0) {
                const latestRound = roundsData.rounds[0];
                renderSessionTitle({
                    is_active: false,
                    is_archived: true,
                    round_name: latestRound.round_name,
                    title: latestRound.title
                });
                return;
            }
        }
        renderSessionTitle(poll);
    } catch (error) {
        console.error('Failed to fetch poll status:', error);
    }
}

// Render session & title (supports displaying the latest archived round)
function renderSessionTitle(poll) {
    currentPoll = poll;
    if (!poll || (!poll.is_active && !poll.is_archived)) {
        sessionTitleContainer.classList.add('hidden');
        inactiveContainer.classList.remove('hidden');
        return;
    }

    inactiveContainer.classList.add('hidden');
    sessionTitleContainer.classList.remove('hidden');

    const roundName = poll.round_name || 'SESI POLLING';
    const titleText = poll.title || 'POLLING LIVE';

    if (roundBadge) roundBadge.textContent = roundName.toUpperCase();
    if (pollTitleText) pollTitleText.textContent = titleText.toUpperCase();
}

function connectWebSocket() {
    const wsUrl = window.location.protocol === 'file:'
        ? 'ws://127.0.0.1:8000/ws'
        : `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws`;

    socket = new WebSocket(wsUrl);

    socket.onopen = () => {
        console.log('Session & Title overlay WebSocket connected.');
    };

    socket.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            if (msg.type === 'poll_update') {
                if (!msg.poll || !msg.poll.is_active) {
                    fetchPollStatus();
                } else {
                    renderSessionTitle(msg.poll);
                }
            } else if (msg.type === 'poll_start' || msg.type === 'poll_stop' || msg.type === 'poll_round_archived') {
                fetchPollStatus();
            }
        } catch (error) {
            console.error('Error handling WebSocket message:', error);
        }
    };

    socket.onclose = () => {
        console.log('Session & Title overlay WebSocket disconnected. Reconnecting in 3 seconds...');
        setTimeout(connectWebSocket, 3000);
    };

    socket.onerror = (err) => {
        console.error('Session & Title overlay WebSocket error:', err);
    };
}
