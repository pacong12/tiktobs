// State management
let socket = null;
let countdownInterval = null;
let maxDuration = 0;

// DOM Elements
const timerContainer = document.getElementById('timer-container');
const inactiveContainer = document.getElementById('inactive-container');
const pollTitle = document.getElementById('poll-title');
const countdownClock = document.getElementById('countdown-clock');
const countdownBar = document.getElementById('countdown-bar');

// Init overlay
document.addEventListener('DOMContentLoaded', () => {
    initOverlay();
});

async function initOverlay() {
    await fetchPollStatus();
    connectWebSocket();
}

// Fetch poll status on load (or latest archived round if active poll ended)
async function fetchPollStatus() {
    try {
        const baseUrl = window.location.protocol === 'file:' ? 'http://127.0.0.1:8000' : '';
        const response = await fetch(`${baseUrl}/api/poll/status`);
        const poll = await response.json();

        if (!poll || !poll.is_active) {
            // Check if there is a recently completed round
            const roundsRes = await fetch(`${baseUrl}/api/poll/rounds?limit=1`);
            const roundsData = await roundsRes.json();
            if (roundsData.rounds && roundsData.rounds.length > 0) {
                const latestRound = roundsData.rounds[0];
                renderTimer({
                    is_active: false,
                    is_expired: true,
                    title: latestRound.title || 'Voting Selesai'
                });
                return;
            }
        }

        renderTimer(poll);
    } catch (error) {
        console.error('Failed to fetch poll status:', error);
    }
}

// Render active timer or inactive state
function renderTimer(poll) {
    if (countdownInterval) {
        clearInterval(countdownInterval);
        countdownInterval = null;
    }

    if (!poll || (!poll.is_active && !poll.is_expired)) {
        timerContainer.classList.add('hidden');
        inactiveContainer.classList.remove('hidden');
        countdownClock.classList.remove('warning');
        maxDuration = 0;
        return;
    }

    timerContainer.classList.remove('hidden');
    inactiveContainer.classList.add('hidden');

    if (pollTitle) {
        if (poll.title) {
            pollTitle.textContent = poll.title;
        } else {
            pollTitle.textContent = 'Voting Time Remaining';
        }
    }

    // If poll was completed/expired
    if (poll.is_expired) {
        countdownClock.textContent = 'SELESAI';
        countdownClock.classList.remove('warning');
        countdownBar.style.width = '0%';
        maxDuration = 0;
        return;
    }

    const expireTime = new Date(poll.expires_at).getTime();

    // Local countdown clock update function
    const updateTime = () => {
        const now = new Date().getTime();
        const secLeft = Math.max(0, Math.round((expireTime - now) / 1000));

        if (secLeft > maxDuration) {
            maxDuration = secLeft;
        }

        // Handle expiration
        if (secLeft <= 0) {
            clearInterval(countdownInterval);
            countdownInterval = null;
            countdownClock.textContent = 'SELESAI';
            countdownClock.classList.remove('warning');
            countdownBar.style.width = '0%';
            return;
        }

        // Clock text
        const mins = Math.floor(secLeft / 60).toString().padStart(2, '0');
        const secs = (secLeft % 60).toString().padStart(2, '0');
        countdownClock.textContent = `${mins}:${secs}`;
    };

    updateTime();
    countdownInterval = setInterval(updateTime, 1000);
}

// Connect WebSocket for real-time events
function connectWebSocket() {
    const wsUrl = window.location.protocol === 'file:' 
        ? 'ws://127.0.0.1:8000/ws' 
        : `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws`;

    socket = new WebSocket(wsUrl);

    socket.onopen = () => {
        console.log('Timer overlay WebSocket connected.');
    };

    socket.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            if (msg.type === 'poll_update') {
                if (!msg.poll || !msg.poll.is_active) {
                    fetchPollStatus();
                } else {
                    renderTimer(msg.poll);
                }
            } else if (msg.type === 'poll_round_archived') {
                fetchPollStatus();
            }
        } catch (error) {
            console.error('Error parsing WebSocket message:', error);
        }
    };

    socket.onclose = () => {
        console.log('Timer overlay WebSocket closed. Reconnecting in 3 seconds...');
        setTimeout(connectWebSocket, 3000);
    };

    socket.onerror = (err) => {
        console.error('Timer WebSocket error:', err);
    };
}
