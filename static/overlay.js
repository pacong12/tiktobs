// State management
let socket = null;
let leaderboard = []; // [{username, nickname, total_diamonds, total_gifts}]
const maxEntries = 5; // Display top 5

// Scope: 'session' = active session only, 'all' = full stored history.
let scope = localStorage.getItem('tiktobs_leaderboard_scope') === 'all' ? 'all' : 'session';

// DOM elements
const leaderboardList = document.getElementById('leaderboard-list');
const scopeSessionBtn = document.getElementById('scope-session-btn');
const scopeAllBtn = document.getElementById('scope-all-btn');

// Init overlay
document.addEventListener('DOMContentLoaded', () => {
    initOverlay();
});

async function initOverlay() {
    setupScopeToggle();
    await fetchLeaderboard();
    connectWebSocket();
}

function setupScopeToggle() {
    updateScopeButtons();
    scopeSessionBtn.addEventListener('click', () => setScope('session'));
    scopeAllBtn.addEventListener('click', () => setScope('all'));
}

function updateScopeButtons() {
    scopeSessionBtn.classList.toggle('active', scope === 'session');
    scopeAllBtn.classList.toggle('active', scope === 'all');
}

async function setScope(newScope) {
    if (scope === newScope) return;
    scope = newScope;
    localStorage.setItem('tiktobs_leaderboard_scope', scope);
    updateScopeButtons();
    await fetchLeaderboard();
}

// Fetch leaderboard for the selected scope
async function fetchLeaderboard() {
    try {
        const baseUrl = window.location.protocol === 'file:' ? 'http://127.0.0.1:8000' : '';
        const suffix = scope === 'all' ? '?scope=all' : '';
        const response = await fetch(`${baseUrl}/api/leaderboard${suffix}`);
        leaderboard = await response.json();
        renderLeaderboard();
    } catch (error) {
        console.error('Failed to fetch leaderboard:', error);
    }
}

// Render list dynamically
function renderLeaderboard() {
    leaderboardList.innerHTML = '';
    
    // Sort top entries: by diamonds descending, then total gifts descending, then by username.
    leaderboard.sort((a, b) => {
        if (b.total_diamonds !== a.total_diamonds) {
            return b.total_diamonds - a.total_diamonds;
        }
        if (b.total_gifts !== a.total_gifts) {
            return b.total_gifts - a.total_gifts;
        }
        return a.username.localeCompare(b.username);
    });

    const displayEntries = leaderboard.slice(0, maxEntries);

    if (displayEntries.length === 0) {
        leaderboardList.innerHTML = `<li class="empty-state">Waiting for gifts...</li>`;
        return;
    }

    displayEntries.forEach((entry, index) => {
        const rank = index + 1;
        const li = document.createElement('li');
        li.className = `leaderboard-item rank-${rank}`;
        
        const nick = entry.nickname || entry.username;
        const user = entry.username;
        const score = entry.total_diamonds;

        li.innerHTML = `
            <div class="item-left">
                <span class="rank-badge">${rank}</span>
                <div class="user-name-wrapper">
                    <span class="nickname">${escapeHTML(nick)}</span>
                    <span class="username">@${escapeHTML(user)}</span>
                </div>
            </div>
            <div class="item-right">
                <span class="diamond-icon">💎</span>
                <span class="score-value">${score}</span>
            </div>
        `;
        leaderboardList.appendChild(li);
    });
}

function connectWebSocket() {
    const wsUrl = window.location.protocol === 'file:' 
        ? 'ws://127.0.0.1:8000/ws' 
        : `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws`;

    socket = new WebSocket(wsUrl);

    socket.onopen = () => {
        console.log('Overlay WebSocket connected.');
    };

    socket.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            handleWSMessage(msg);
        } catch (error) {
            console.error('Error parsing WebSocket message:', error);
        }
    };

    socket.onclose = () => {
        console.log('Overlay WebSocket closed. Reconnecting in 3 seconds...');
        setTimeout(connectWebSocket, 3000);
    };

    socket.onerror = (err) => {
        console.error('Overlay WebSocket error:', err);
    };
}

// Handle WebSocket messages
function handleWSMessage(msg) {
    // If the active session is reset or disconnected, clear the local board
    // only in session scope; the history board keeps its stored totals.
    if (msg.type === 'status' && (msg.status === 'disconnected' || msg.status === 'failed')) {
        if (scope === 'session') {
            leaderboard = [];
            renderLeaderboard();
        }
        return;
    }

    // A cleared event stream resets the session board too.
    if (msg.type === 'stream_cleared') {
        if (scope === 'session') {
            leaderboard = [];
            renderLeaderboard();
        }
        return;
    }
    
    // Process new gift events
    if (msg.type === 'event' && msg.event && msg.event.event_type === 'gift') {
        const event = msg.event;
        const eventData = event.data;
        const username = event.username;
        
        if (!username) return;
        
        const nickname = event.nickname || username;
        const quantity = parseInt(eventData.quantity || 1);
        const diamondCount = parseInt(eventData.diamond_count || 0);
        const diamondsAdded = quantity * diamondCount;

        // Find or insert sender
        let entry = leaderboard.find(e => e.username === username);
        if (!entry) {
            entry = {
                username: username,
                nickname: nickname,
                total_diamonds: 0,
                total_gifts: 0
            };
            leaderboard.push(entry);
        }

        if (event.nickname) {
            entry.nickname = event.nickname;
        }

        entry.total_diamonds += diamondsAdded;
        entry.total_gifts += quantity;

        renderLeaderboard();
    }
}

// Utility: HTML Escaper
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
