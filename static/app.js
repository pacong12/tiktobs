// STATE VARIABLES
let socket = null;
let activeAnchorId = null;
let activeFilter = 'all';
let eventCache = []; // Stores recent events
const maxCacheSize = 500;

// DOM ELEMENTS
const statusBulb = document.getElementById('status-indicator');
const statusText = document.getElementById('status-text');
const usernameInput = document.getElementById('username-input');
const connectBtn = document.getElementById('connect-btn');
const disconnectBtn = document.getElementById('disconnect-btn');

const sessionInfo = document.getElementById('session-info');
const infoSessionId = document.getElementById('info-session-id');
const infoUsername = document.getElementById('info-username');

const filterTabs = document.getElementById('filter-tabs');
const eventStreamBody = document.getElementById('event-stream-body');
const clearStreamBtn = document.getElementById('clear-stream-btn');
const consoleLogs = document.getElementById('console-logs');
const clearLogsBtn = document.getElementById('clear-logs');

const inspectorEventId = document.getElementById('inspector-event-id');
const inspectorJson = document.getElementById('inspector-json');
const rawEventType = document.getElementById('raw-event-type');
const rawEventJson = document.getElementById('raw-event-json');

// MODAL ELEMENTS
const detailModal = document.getElementById('detail-modal');
const modalCloseBtn = document.getElementById('close-modal-btn');
const modalTitle = document.getElementById('modal-title');
const modalEventId = document.getElementById('modal-event-id');
const modalEventType = document.getElementById('modal-event-type');
const modalEventUser = document.getElementById('modal-event-user');
const modalEventTime = document.getElementById('modal-event-time');
const modalEventJson = document.getElementById('modal-event-json');

// COUNTERS STATE
const counters = {
    gift: 0,
    comment: 0,
    like: 0,
    follow: 0,
    share: 0,
    viewer: 0
};

// GIFT LEADERBOARD STATE (dashboard card, active session)
let dashboardLeaderboard = []; // [{username, nickname, total_diamonds, total_gifts}]

// INITIALIZATION
document.addEventListener('DOMContentLoaded', () => {
    initApp();
});

async function initApp() {
    setupEventListeners();
    await checkStatus();
    await loadRecentEvents();
    await loadLeaderboard();
    await loadOverlays();
    connectWebSocket();
}

function setupEventListeners() {
    connectBtn.addEventListener('click', handleConnect);
    disconnectBtn.addEventListener('click', handleDisconnect);
    clearLogsBtn.addEventListener('click', () => {
        consoleLogs.innerHTML = '';
        addConsoleLog('Logs cleared.', 'system');
    });
    clearStreamBtn.addEventListener('click', handleClearStream);

    // Filter tab clicks
    filterTabs.addEventListener('click', (e) => {
        if (e.target.classList.contains('filter-tab')) {
            document.querySelectorAll('.filter-tab').forEach(tab => tab.classList.remove('active'));
            e.target.classList.add('active');
            activeFilter = e.target.dataset.filter;
            renderEventStream();
        }
    });

    // Overlay copy buttons are wired in loadOverlays()/wireOverlayCopyButton()
    // because the overlay list is rendered dynamically from GET /api/overlays.

    // Modal close
    modalCloseBtn.addEventListener('click', () => {
        detailModal.classList.add('hidden');
    });

    // Close modal on outside click
    detailModal.addEventListener('click', (e) => {
        if (e.target === detailModal) {
            detailModal.classList.add('hidden');
        }
    });

    // Rankings Modal listeners
    const viewRankingsBtn = document.getElementById('view-rankings-btn');
    const rankingsModal = document.getElementById('rankings-modal');
    const closeRankingsBtn = document.getElementById('close-rankings-btn');

    if (viewRankingsBtn) {
        viewRankingsBtn.addEventListener('click', handleViewRankings);
    }
    if (closeRankingsBtn) {
        closeRankingsBtn.addEventListener('click', () => {
            rankingsModal.classList.add('hidden');
        });
    }
    if (rankingsModal) {
        rankingsModal.addEventListener('click', (e) => {
            if (e.target === rankingsModal) {
                rankingsModal.classList.add('hidden');
            }
        });
    }
}

// API INTERACTION
async function checkStatus() {
    try {
        const response = await fetch('/api/status');
        const data = await response.json();
        updateConnectionUI(data.status, data.username, data.session_id, data.anchor_id);
        
        // Sync poll timer status on load
        fetch('/api/poll/status').then(r => r.json()).then(poll => updatePollTimerDOM(poll)).catch(() => {});
    } catch (error) {
        console.error('Failed to get connection status:', error);
        addConsoleLog('Failed to sync connection status with server.', 'error');
    }
}

async function loadRecentEvents() {
    try {
        const response = await fetch('/api/events/recent');
        const data = await response.json();
        
        eventCache = data.map(item => ({
            id: item.id,
            event_type: item.event_type,
            username: item.username,
            nickname: item.nickname,
            timestamp: new Date(item.created_at || item.payload.timestamp),
            data: item.payload.data || item.payload
        }));

        recalculateCounters();
        renderEventStream();
        addConsoleLog(`Loaded ${eventCache.length} recent events from database.`, 'success');
    } catch (error) {
        console.error('Failed to load recent events:', error);
        addConsoleLog('Failed to load connection history from database.', 'error');
    }
}

async function handleConnect() {
    const username = usernameInput.value.trim();
    if (!username) {
        addConsoleLog('Error: Username cannot be blank.', 'error');
        return;
    }

    try {
        updateConnectionUI('connecting', username);
        const response = await fetch('/api/connect', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username })
        });
        const data = await response.json();
        updateConnectionUI('connecting', username, data.session_id);
        addConsoleLog(`Initiated connection to @${username}...`, 'system');
    } catch (error) {
        console.error('Connect error:', error);
        updateConnectionUI('failed', username);
        addConsoleLog('Connection initiation failed.', 'error');
    }
}

async function handleDisconnect() {
    try {
        addConsoleLog('Disconnecting from stream...', 'system');
        const response = await fetch('/api/disconnect', { method: 'POST' });
        const data = await response.json();
        updateConnectionUI('disconnected');
    } catch (error) {
        console.error('Disconnect error:', error);
        addConsoleLog('Disconnection request failed.', 'error');
    }
}

// Clears the visible stream, counters, and inspector panels.
function resetStreamPanels() {
    eventCache = [];
    counters.gift = 0;
    counters.comment = 0;
    counters.like = 0;
    counters.follow = 0;
    counters.share = 0;
    counters.viewer = 0;
    dashboardLeaderboard = [];

    updateCounterDOM();
    renderEventStream();
    renderDashboardLeaderboard();

    // Clear inspector panels
    inspectorEventId.textContent = 'No event selected';
    inspectorJson.textContent = 'Select an event from the stream above to inspect its properties and payload structure.';
    rawEventType.textContent = 'Waiting for data...';
    rawEventJson.textContent = 'Raw data packets received from the TikTok provider will populate here in real-time.';
}

async function handleClearStream() {
    const confirmed = confirm(
        'Clear the event stream?\n\n' +
        'This also deletes the stored events from the database and resets the gift leaderboard.'
    );
    if (!confirmed) return;

    try {
        const response = await fetch('/api/events/clear', { method: 'POST' });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        // The server broadcasts 'stream_cleared' to every client (including
        // this one); if the WebSocket happens to be down, clear locally.
        if (!socket || socket.readyState !== WebSocket.OPEN) {
            resetStreamPanels();
        }
        addConsoleLog(`Event stream cleared (${data.deleted} stored event(s) deleted).`, 'system');
    } catch (error) {
        console.error('Clear stream error:', error);
        addConsoleLog('Failed to clear the event stream.', 'error');
    }
}

// WEBSOCKET BROADCAST RECEIVER
function updateServerLink(state) {
    const link = document.getElementById('server-link');
    const text = document.getElementById('server-link-text');
    if (!link || !text) return;
    link.className = 'server-link ' + state;
    text.textContent = state === 'online' ? 'Server: online'
        : state === 'connecting' ? 'Server: connecting…'
        : 'Server: offline';
}

function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws`;

    addConsoleLog('Connecting to WebSocket server...', 'system');
    updateServerLink('connecting');
    socket = new WebSocket(wsUrl);

    socket.onopen = () => {
        addConsoleLog('WebSocket channel connected successfully.', 'success');
        updateServerLink('online');
    };

    socket.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            handleWSMessage(data);
        } catch (error) {
            console.error('Error handling WebSocket message:', error);
        }
    };

    socket.onclose = () => {
        addConsoleLog('WebSocket link severed. Reconnecting in 3 seconds...', 'error');
        updateServerLink('offline');
        setTimeout(connectWebSocket, 3000);
    };

    socket.onerror = (err) => {
        console.error('WebSocket error:', err);
    };
}

function handleWSMessage(msg) {
    if (msg.type === 'log') {
        const time = new Date(msg.timestamp).toLocaleTimeString();
        let level = 'system';
        if (msg.message.includes('Connected!')) level = 'success';
        if (msg.message.includes('error') || msg.message.includes('failed')) {
            level = 'error';
            showConnectionErrorBanner(msg.message);
        }
        if (msg.message.includes('received') || msg.message.includes('liked') || msg.message.includes('followed') || msg.message.includes('shared')) level = 'event';

        addConsoleLog(`[${time}] ${msg.message}`, level);
    } 
    else if (msg.type === 'status') {
        updateConnectionUI(msg.status, msg.username, msg.session_id || null, msg.anchor_id || null);
        if (msg.status === 'failed') {
            const errStr = msg.error || 'Server error';
            addConsoleLog(`Connection Failed: ${errStr}`, 'error');
            showConnectionErrorBanner(errStr);
        }
    } 
    else if (msg.type === 'poll_update') {
        updatePollTimerDOM(msg.poll);
    }
    else if (msg.type === 'stream_cleared') {
        resetStreamPanels();
        addConsoleLog('Event stream cleared (synced from server).', 'system');
    }
    else if (msg.type === 'event') {
        const event = msg.event;
        
        // Transform incoming event
        const normalized = {
            id: event.id,
            event_type: event.event_type,
            username: event.username,
            nickname: event.nickname,
            timestamp: new Date(event.timestamp),
            data: event.data
        };

        // Cache event
        eventCache.unshift(normalized);
        if (eventCache.length > maxCacheSize) {
            eventCache.pop();
        }

        // Update real-time counter
        incrementCounter(normalized.event_type, normalized.data);

        // Keep the gift leaderboard card in sync
        if (normalized.event_type === 'gift') {
            updateLeaderboardFromGift(normalized);
        }

        // Update raw live developer panel
        updateRawEventDebug(normalized.event_type, event);

        // Render stream with requestAnimationFrame throttling to prevent main thread blocking
        scheduleRenderEventStream();
    }
}

// UI LOGGING & ERROR BANNER
function showConnectionErrorBanner(message) {
    const banner = document.getElementById('connection-error-banner');
    const textEl = document.getElementById('connection-error-text');
    if (!banner || !textEl) return;

    let friendlyMsg = message;
    if (message.includes('4429') || message.includes('rate limit')) {
        friendlyMsg = 'Quota EulerStream API habis (Code 4429). Otomatis beralih ke mode lokal...';
    } else if (message.includes('4404') || message.includes('not currently live')) {
        friendlyMsg = 'Akun streamer tidak sedang LIVE (Code 4404). Pastikan siaran di TikTok sudah aktif.';
    } else if (message.includes('4005') || message.includes('stream ended')) {
        friendlyMsg = 'Siaran LIVE telah berakhir (Code 4005).';
    } else if (message.includes('1011') || message.includes('room_info')) {
        friendlyMsg = 'EulerStream gagal membaca room info akun ini (Code 1011). Coba hapus API key di Settings untuk switch ke mode lokal.';
    }

    textEl.textContent = friendlyMsg;
    banner.classList.remove('hidden');
}

function hideConnectionErrorBanner() {
    const banner = document.getElementById('connection-error-banner');
    if (banner) banner.classList.add('hidden');
}

function addConsoleLog(text, level = 'system') {
    const line = document.createElement('div');
    line.className = `console-line ${level}`;
    line.textContent = text;
    consoleLogs.appendChild(line);
    consoleLogs.scrollTop = consoleLogs.scrollHeight;
}

// UI CONNECTION SYNCS
function updateConnectionUI(status, username = null, sessionId = null, anchorId = null) {
    // Reset bulb classes
    statusBulb.className = 'status-bulb';
    
    const infoAnchorRow = document.getElementById('info-anchor-row');
    const infoAnchorId = document.getElementById('info-anchor-id');
    const viewRankingsBtn = document.getElementById('view-rankings-btn');
    
    if (status === 'connected') {
        hideConnectionErrorBanner();
        statusBulb.classList.add('connected');
        statusText.textContent = `Connected to @${username}`;
        connectBtn.disabled = true;
        disconnectBtn.disabled = false;
        usernameInput.disabled = true;
        
        sessionInfo.classList.remove('hidden');
        infoSessionId.textContent = sessionId || '-';
        infoUsername.textContent = `@${username}`;

        if (anchorId && anchorId !== 'unknown') {
            activeAnchorId = anchorId;
            infoAnchorId.textContent = anchorId;
            infoAnchorRow.style.display = 'flex';
            viewRankingsBtn.style.display = 'block';
        } else {
            activeAnchorId = null;
            infoAnchorRow.style.display = 'none';
            viewRankingsBtn.style.display = 'none';
        }
    } 
    else if (status === 'connecting') {
        hideConnectionErrorBanner();
        statusBulb.classList.add('connecting');
        statusText.textContent = 'Connecting...';
        connectBtn.disabled = true;
        disconnectBtn.disabled = false;
        usernameInput.disabled = true;
    } 
    else if (status === 'failed') {
        statusBulb.classList.add('disconnected');
        statusText.textContent = 'Connection Failed';
        connectBtn.disabled = false;
        disconnectBtn.disabled = true;
        usernameInput.disabled = false;
        
        sessionInfo.classList.add('hidden');
        if (infoAnchorRow) infoAnchorRow.style.display = 'none';
        if (viewRankingsBtn) viewRankingsBtn.style.display = 'none';
        activeAnchorId = null;
        clearSessionData();
    } 
    else { // disconnected
        statusBulb.classList.add('disconnected');
        statusText.textContent = 'Disconnected';
        connectBtn.disabled = false;
        disconnectBtn.disabled = true;
        usernameInput.disabled = false;
        
        sessionInfo.classList.add('hidden');
        if (infoAnchorRow) infoAnchorRow.style.display = 'none';
        if (viewRankingsBtn) viewRankingsBtn.style.display = 'none';
        activeAnchorId = null;
        clearSessionData();
    }
}

function clearSessionData() {
    resetStreamPanels();
}

// COUNTERS PROCESSING
function recalculateCounters() {
    // Reset counts
    counters.gift = 0;
    counters.comment = 0;
    counters.like = 0;
    counters.follow = 0;
    counters.share = 0;
    counters.viewer = 0;

    // Standard TikTok LIVE limits viewer count to current. 
    // Likes, gifts are sums, other events are action tallies.
    eventCache.forEach(evt => {
        if (evt.event_type === 'gift') {
            counters.gift += (evt.data.quantity || 1);
        } else if (evt.event_type === 'comment') {
            counters.comment++;
        } else if (evt.event_type === 'like') {
            counters.like += (evt.data.count || 1);
        } else if (evt.event_type === 'follow') {
            counters.follow++;
        } else if (evt.event_type === 'share') {
            counters.share++;
        } else if (evt.event_type === 'viewer') {
            // viewer count is absolute, store max or latest
            counters.viewer = Math.max(counters.viewer, evt.data.viewer_count || 0);
        }
    });

    updateCounterDOM();
}

function incrementCounter(type, data) {
    let bumpCard = true;

    if (type === 'gift') {
        counters.gift += (data.quantity || 1);
    } else if (type === 'comment') {
        counters.comment++;
    } else if (type === 'like') {
        counters.like += (data.count || 1);
    } else if (type === 'follow') {
        counters.follow++;
    } else if (type === 'share') {
        counters.share++;
    } else if (type === 'viewer') {
        counters.viewer = data.viewer_count || 0;
        // Don't trigger massive glows for regular spectator numbers
        bumpCard = false; 
    }

    updateCounterDOM(type, bumpCard);
}

function updateCounterDOM(highlightType = null, shouldBump = false) {
    // Compact format for large numbers (e.g. 12.3K, 1.2M) to avoid overflow,
    // keeping the full value available on hover via the title attribute.
    const compact = (num) => {
        if (num >= 1_000_000) return (num / 1_000_000).toFixed(num >= 10_000_000 ? 0 : 1).replace(/\.0$/, '') + 'M';
        if (num >= 10_000) return (num / 1_000).toFixed(num >= 100_000 ? 0 : 1).replace(/\.0$/, '') + 'K';
        return num.toLocaleString();
    };

    const setCounter = (id, value) => {
        const el = document.getElementById(id);
        if (!el) return;
        el.textContent = compact(value);
        el.title = value.toLocaleString();
    };

    setCounter('counter-gifts', counters.gift);
    setCounter('counter-comments', counters.comment);
    setCounter('counter-likes', counters.like);
    setCounter('counter-follows', counters.follow);
    setCounter('counter-shares', counters.share);
    setCounter('counter-viewers', counters.viewer);

    // Micro-animation triggers
    if (highlightType && shouldBump) {
        const card = document.querySelector(`.counter-card[data-type="${highlightType}"]`);
        if (card) {
            card.classList.remove('bump');
            void card.offsetWidth; // restart animation
            card.classList.add('bump');
            setTimeout(() => card.classList.remove('bump'), 400);
        }
    }
}

let dashboardTimerInterval = null;

function updatePollTimerDOM(poll) {
    const el = document.getElementById('counter-timer');
    const sessionEl = document.getElementById('counter-session');

    if (sessionEl) {
        if (poll && poll.is_active) {
            const roundName = poll.round_name || 'Active';
            const titleText = poll.title ? ` (${poll.title})` : '';
            sessionEl.textContent = `${roundName}${titleText}`;
            sessionEl.title = `${roundName}${titleText}`;
        } else {
            sessionEl.textContent = '--';
            sessionEl.title = 'No active poll';
        }
    }

    if (!el) return;

    clearInterval(dashboardTimerInterval);

    if (!poll || !poll.is_active || !poll.expires_at) {
        el.textContent = '--:--';
        return;
    }

    const updateClock = () => {
        const expiresAt = new Date(poll.expires_at).getTime();
        const now = Date.now();
        const diffMs = expiresAt - now;

        if (diffMs <= 0) {
            el.textContent = '00:00';
            clearInterval(dashboardTimerInterval);
            return;
        }

        const totalSec = Math.floor(diffMs / 1000);
        const mins = Math.floor(totalSec / 60);
        const secs = totalSec % 60;
        el.textContent = `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
    };

    updateClock();
    dashboardTimerInterval = setInterval(updateClock, 1000);
}

let renderEventStreamScheduled = false;
function scheduleRenderEventStream() {
    if (renderEventStreamScheduled) return;
    renderEventStreamScheduled = true;
    requestAnimationFrame(() => {
        renderEventStreamScheduled = false;
        renderEventStream();
    });
}

// EVENT TABLE DRAWING (Render top 50 recent items to prevent UI freeze during high-traffic streams)
function renderEventStream() {
    eventStreamBody.innerHTML = '';

    const filtered = eventCache.filter(evt => {
        if (activeFilter === 'all') return true;
        return evt.event_type === activeFilter;
    }).slice(0, 50);

    if (filtered.length === 0) {
        const emptyRow = document.createElement('tr');
        emptyRow.className = 'empty-state';
        emptyRow.innerHTML = `<td colspan="4">No events match the selected filter.</td>`;
        eventStreamBody.appendChild(emptyRow);
        return;
    }

    filtered.forEach(evt => {
        const row = document.createElement('tr');
        row.className = 'event-row';
        row.dataset.id = evt.id;
        row.dataset.type = evt.event_type;

        // Formats cells
        const timeStr = evt.timestamp.toLocaleTimeString();
        const displayUser = evt.username ? `@${escapeHTML(evt.username)}` : 'System';
        const displayNick = evt.nickname ? `<span class="nickname">${escapeHTML(evt.nickname)}</span>` : '';
        if (evt.event_type === 'comment') {
            displayData = evt.data.comment || '';
        } else if (evt.event_type === 'gift') {
            displayData = `${evt.data.gift_name} x${evt.data.quantity}`;
        } else if (evt.event_type === 'like') {
            displayData = `Sent ${evt.data.count} likes`;
        } else if (evt.event_type === 'follow') {
            displayData = 'Followed the stream';
        } else if (evt.event_type === 'share') {
            displayData = evt.data.share_target ? `Shared the stream to ${evt.data.share_target}` : 'Shared the stream';
        } else if (evt.event_type === 'viewer') {
            displayData = `Spectator count: ${evt.data.viewer_count}`;
        }

        row.innerHTML = `
            <td class="type-cell"><span>${evt.event_type}</span></td>
            <td class="user-cell">${displayUser}${displayNick}</td>
            <td class="data-cell">${escapeHTML(displayData)}</td>
            <td class="time-cell">${timeStr}</td>
        `;

        row.addEventListener('click', () => openInspector(evt));
        eventStreamBody.appendChild(row);
    });
}

// GIFT LEADERBOARD CARD (dashboard, active session)
async function loadLeaderboard() {
    try {
        const response = await fetch('/api/leaderboard');
        dashboardLeaderboard = await response.json();
        renderDashboardLeaderboard();
    } catch (error) {
        console.error('Failed to load gift leaderboard:', error);
    }
}

// --- OBS overlay registry (persisted in the DB) ---------------------------

async function loadOverlays() {
    const list = document.getElementById('overlay-links-list');
    if (!list) return;
    try {
        const response = await fetch('/api/overlays');
        if (!response.ok) throw new Error('HTTP ' + response.status);
        const data = await response.json();
        renderOverlays(list, data.overlays || []);
    } catch (error) {
        console.error('Failed to load overlay list:', error);
        list.innerHTML = '<div class="overlay-links-empty">Failed to load overlay list.</div>';
    }
}

function renderOverlays(list, overlays) {
    list.innerHTML = '';
    overlays.forEach(ov => {
        const item = document.createElement('div');
        item.className = 'overlay-link-item';
        item.dataset.accent = ov.accent || 'cyan';
        item.innerHTML = `
            <span class="overlay-link-label" title="${escapeHTML(ov.description)}"><span class="ol-icon">${escapeHTML(ov.icon)}</span> ${escapeHTML(ov.label)}</span>
            <div class="overlay-link-actions">
                <a href="${escapeHTML(ov.url)}" target="_blank" class="ol-btn open">Open</a>
                <button class="ol-btn copy" data-url="${escapeHTML(ov.url)}">Copy</button>
            </div>
        `;
        list.appendChild(item);
        const copyBtn = item.querySelector('.ol-btn.copy');
        if (copyBtn) wireOverlayCopyButton(copyBtn);
    });
}

// Copy overlay URL to clipboard (for OBS Browser Source)
function wireOverlayCopyButton(btn) {
    btn.addEventListener('click', async () => {
        const fullUrl = window.location.origin + btn.dataset.url;
        try {
            await navigator.clipboard.writeText(fullUrl);
        } catch {
            // Fallback for non-secure contexts
            const ta = document.createElement('textarea');
            ta.value = fullUrl;
            document.body.appendChild(ta);
            ta.select();
            document.execCommand('copy');
            document.body.removeChild(ta);
        }
        const original = btn.textContent;
        btn.textContent = 'Copied!';
        btn.classList.add('copied');
        showToast(`URL copied: ${fullUrl}`);
        setTimeout(() => {
            btn.textContent = original;
            btn.classList.remove('copied');
        }, 1500);
    });
}

function renderDashboardLeaderboard() {
    const list = document.getElementById('dashboard-leaderboard');
    if (!list) return;

    const sorted = [...dashboardLeaderboard].sort((a, b) =>
        (b.total_diamonds - a.total_diamonds) ||
        (b.total_gifts - a.total_gifts) ||
        a.username.localeCompare(b.username)
    );
    const top = sorted.slice(0, 5);

    if (top.length === 0) {
        list.innerHTML = '<li class="lb-empty">Belum ada gift di sesi ini.</li>';
        return;
    }

    const medals = ['🥇', '🥈', '🥉'];
    list.innerHTML = top.map((entry, i) => `
        <li class="lb-row lb-rank-${i + 1}">
            <span class="lb-rank">${medals[i] || i + 1}</span>
            <span class="lb-name" title="@${escapeHTML(entry.username)}">${escapeHTML(entry.nickname || entry.username)}</span>
            <span class="lb-diamonds">💎 ${entry.total_diamonds.toLocaleString()}</span>
        </li>
    `).join('');
}

function updateLeaderboardFromGift(event) {
    const data = event.data || {};
    const username = event.username;
    if (!username) return;

    const quantity = parseInt(data.quantity || 1, 10) || 1;
    const diamondsAdded = quantity * (parseInt(data.diamond_count || 0, 10) || 0);

    let entry = dashboardLeaderboard.find(e => e.username === username);
    if (!entry) {
        entry = { username, nickname: event.nickname || username, total_diamonds: 0, total_gifts: 0 };
        dashboardLeaderboard.push(entry);
    }
    if (event.nickname) entry.nickname = event.nickname;
    entry.total_diamonds += diamondsAdded;
    entry.total_gifts += quantity;

    renderDashboardLeaderboard();
}

function openInspector(event) {
    // Update Sidebar Inspector
    inspectorEventId.textContent = `ID: ${event.id}`;
    inspectorJson.textContent = JSON.stringify(event, null, 2);

    // Update Full Modal Panel
    modalTitle.textContent = `${capitalize(event.event_type)} Event`;
    modalEventId.textContent = event.id;
    modalEventType.textContent = event.event_type.toUpperCase();
    modalEventUser.textContent = event.username ? `@${event.username} (${event.nickname || 'No Nickname'})` : 'System';
    modalEventTime.textContent = event.timestamp.toLocaleString();
    modalEventJson.textContent = JSON.stringify(event, null, 2);

    detailModal.classList.remove('hidden');
}

function updateRawEventDebug(type, fullEventObj) {
    rawEventType.textContent = `TYPE: ${type.toUpperCase()}`;
    rawEventJson.textContent = JSON.stringify(fullEventObj, null, 2);
}

// UTILITY FUNCTIONS
function escapeHTML(str) {
    if (!str) return '';
    return str.toString()
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

function capitalize(str) {
    if (!str) return '';
    return str.charAt(0).toUpperCase() + str.slice(1);
}

async function handleViewRankings() {
    if (!activeAnchorId) return;

    const rankingsModal = document.getElementById('rankings-modal');
    const rankingsLoading = document.getElementById('rankings-loading');
    const rankingsContent = document.getElementById('rankings-content');
    const rankingsTableBody = document.getElementById('rankings-table-body');

    rankingsModal.classList.remove('hidden');
    rankingsLoading.classList.remove('hidden');
    rankingsContent.classList.add('hidden');
    rankingsTableBody.innerHTML = '';

    try {
        const response = await fetch(`/api/rankings?anchor_id=${activeAnchorId}`);
        if (!response.ok) {
            throw new Error(`Failed to fetch rankings: ${response.statusText}`);
        }
        const data = await response.json();
        
        const leaderboards = data.leaderboards || {};
        const regions = Object.keys(leaderboards);
        
        rankingsLoading.classList.add('hidden');
        rankingsContent.classList.remove('hidden');

        if (regions.length === 0) {
            rankingsTableBody.innerHTML = `<tr><td colspan="2" class="empty-state" style="text-align: center; padding: 20px;">No rankings found for this creator in the past 30 days.</td></tr>`;
            return;
        }

        regions.forEach(region => {
            const row = document.createElement('tr');
            const ranks = (leaderboards[region] || []).join(', ');
            row.innerHTML = `
                <td style="font-weight: 700; color: #00f0ff;">${region}</td>
                <td style="color: #ffffff;">${ranks}</td>
            `;
            rankingsTableBody.appendChild(row);
        });

    } catch (error) {
        console.error('Error fetching rankings:', error);
        rankingsLoading.classList.add('hidden');
        rankingsContent.classList.remove('hidden');
        rankingsTableBody.innerHTML = `<tr><td colspan="2" class="empty-state" style="text-align: center; color: #ff4a5a; padding: 20px;">Error: ${error.message}</td></tr>`;
    }
}

// TOAST NOTIFICATION HELPER
let toastTimer = null;
function showToast(message) {
    let toast = document.getElementById('app-toast');
    if (!toast) {
        toast = document.createElement('div');
        toast.id = 'app-toast';
        toast.className = 'toast';
        document.body.appendChild(toast);
    }
    toast.textContent = message;
    // Force reflow so re-triggering the animation works
    void toast.offsetWidth;
    toast.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove('show'), 2600);
}
