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

// Fetch poll status on load
async function fetchPollStatus() {
    try {
        const baseUrl = window.location.protocol === 'file:' ? 'http://127.0.0.1:8000' : '';
        const response = await fetch(`${baseUrl}/api/poll/status`);
        const poll = await response.json();
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

    if (!poll || !poll.is_active || !poll.expires_at) {
        timerContainer.classList.add('hidden');
        inactiveContainer.classList.remove('hidden');
        countdownClock.classList.remove('warning');
        maxDuration = 0;
        return;
    }

    timerContainer.classList.remove('hidden');
    inactiveContainer.classList.add('hidden');

    if (poll.title) {
        pollTitle.textContent = poll.title;
    } else {
        pollTitle.textContent = 'Voting Time Remaining';
    }

    const expireTime = new Date(poll.expires_at).getTime();

    // Local countdown clock update function
    const updateTime = () => {
        const now = new Date().getTime();
        const secLeft = Math.max(0, Math.round((expireTime - now) / 1000));

        if (secLeft > maxDuration) {
            maxDuration = secLeft;
        }

        // Clock text
        const mins = Math.floor(secLeft / 60).toString().padStart(2, '0');
        const secs = (secLeft % 60).toString().padStart(2, '0');
        countdownClock.textContent = `${mins}:${secs}`;

        // Alert state warning class
        if (secLeft <= 10 && secLeft > 0) {
            countdownClock.classList.add('warning');
        } else {
            countdownClock.classList.remove('warning');
        }

        // Progress bar percentage calculation
        const percent = maxDuration > 0 ? (secLeft / maxDuration) * 100 : 0;
        countdownBar.style.width = `${percent}%`;

        // Handle expiration
        if (secLeft <= 0) {
            clearInterval(countdownInterval);
            countdownInterval = null;
            // Short delay before showing inactive container
            setTimeout(() => {
                timerContainer.classList.add('hidden');
                inactiveContainer.classList.remove('hidden');
                maxDuration = 0;
            }, 1000);
        }
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
                renderTimer(msg.poll);
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
