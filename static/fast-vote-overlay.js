// OBS Fast-Track Vote Overlay (Gift Boost Focus)
let socket = null;
let currentPoll = null;

const fastVoteWrap = document.getElementById('fast-vote-wrap');
const inactiveContainer = document.getElementById('inactive-container');
const candidatesList = document.getElementById('fast-candidates-list');

document.addEventListener('DOMContentLoaded', () => {
    initOverlay();
});

async function initOverlay() {
    await fetchPollStatus();
    connectWebSocket();
}

// Fetch poll status on load (or latest archived round)
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
                renderFastVote({
                    is_active: false,
                    is_archived: true,
                    title: latestRound.title,
                    total_votes: latestRound.total_votes,
                    candidates: (latestRound.candidates || []).map(c => ({
                        ...c,
                        wins: (poll && poll.candidates)
                            ? (poll.candidates.find(pc => pc.name.trim().toLowerCase() === c.name.trim().toLowerCase())?.wins ?? c.wins ?? 0)
                            : (c.wins ?? 0)
                    }))
                });
                return;
            }
        }
        renderFastVote(poll);
    } catch (error) {
        console.error('Failed to fetch fast poll status:', error);
    }
}

function escapeHTML(str) {
    if (!str) return '';
    return str.replace(/[&<>'"]/g, tag => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        "'": '&#39;',
        '"': '&quot;'
    }[tag] || tag));
}

function giftIconKey(name) {
    return ((name || '').toLowerCase().replace(/[^\w\s]/g, ' ').replace(/\s+/g, ' ').trim());
}

function giftIconHtml(giftName, cls) {
    const icons = window.GIFT_ICONS || {};
    const url = icons[giftIconKey(giftName)];
    if (!url) return '⚡';
    return `<img class="${cls}" src="${url}" alt="" loading="lazy" onerror="this.outerHTML='⚡'">`;
}

function renderFastVote(poll) {
    if (!poll || (!poll.is_active && !poll.is_archived)) {
        currentPoll = poll;
        fastVoteWrap.classList.add('hidden');
        inactiveContainer.classList.remove('hidden');
        return;
    }

    currentPoll = poll;
    inactiveContainer.classList.add('hidden');
    fastVoteWrap.classList.remove('hidden');

    const ranked = [...poll.candidates].sort((a, b) => b.votes - a.votes);
    const maxVotes = poll.total_votes > 0 ? Math.max(...ranked.map(c => c.votes)) : 0;

    // In-place update keyed by candidate ID to prevent layout jumps / flicker
    const existingRows = candidatesList.querySelectorAll('.fast-candidate-row');
    const allPresent = poll.candidates.every(c => candidatesList.querySelector(`.fast-candidate-row[data-id="${c.id}"]`));

    if (existingRows.length === poll.candidates.length && allPresent) {
        ranked.forEach(c => {
            const row = candidatesList.querySelector(`.fast-candidate-row[data-id="${c.id}"]`);
            if (!row) return;
            const isLeading = maxVotes > 0 && c.votes === maxVotes;
            row.classList.toggle('leading', isLeading);

            const votesEl = row.querySelector('.fast-votes-val');
            const pctEl = row.querySelector('.fast-pct-val');
            const winEl = row.querySelector('.fast-win-badge');

            if (votesEl && votesEl.textContent !== `⚡ ${c.votes.toLocaleString()}`) {
                votesEl.textContent = `⚡ ${c.votes.toLocaleString()}`;
            }
            if (pctEl && pctEl.textContent !== `${c.percentage}%`) {
                pctEl.textContent = `${c.percentage}%`;
            }
            const wins = Number(c.wins) || 0;
            if (winEl) winEl.innerHTML = `win ${wins}&times;`;
        });
        return;
    }

    candidatesList.innerHTML = '';
    ranked.forEach(c => {
        const isLeading = maxVotes > 0 && c.votes === maxVotes;
        const giftLabel = (c.gift_name || 'Gift Boost').trim();
        const iconHtml = giftIconHtml(giftLabel, 'fast-gift-icon');
        const wins = Number(c.wins) || 0;
        const winHtml = `<span class="fast-win-badge">win ${wins}&times;</span>`;

        const row = document.createElement('div');
        row.className = `fast-candidate-row ${isLeading ? 'leading' : ''}`;
        row.dataset.id = String(c.id);
        row.innerHTML = `
            <div class="fast-left">
                <div class="fast-gift-badge">${iconHtml}</div>
                <div class="fast-name-wrap">
                    <div style="display:flex; align-items:center; gap:6px;">
                        <span class="fast-cand-name">${escapeHTML(c.name)}</span>
                        ${winHtml}
                    </div>
                    <span class="fast-gift-name">Boost: ${escapeHTML(giftLabel)}</span>
                </div>
            </div>
            <div class="fast-right">
                <span class="fast-votes-val">⚡ ${c.votes.toLocaleString()}</span>
                <span class="fast-pct-val">${c.percentage}%</span>
            </div>
        `;
        candidatesList.appendChild(row);
    });
}

function connectWebSocket() {
    const wsUrl = window.location.protocol === 'file:'
        ? 'ws://127.0.0.1:8000/ws'
        : `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws`;

    socket = new WebSocket(wsUrl);

    socket.onopen = () => {
        console.log('Fast vote overlay WebSocket connected.');
    };

    socket.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            if (msg.type === 'poll_update') {
                if (msg.poll && msg.poll.is_active) {
                    renderFastVote(msg.poll);
                } else {
                    fetchPollStatus();
                }
            } else if (msg.type === 'poll_start' || msg.type === 'poll_stop' || msg.type === 'poll_round_archived') {
                fetchPollStatus();
            }
        } catch (error) {
            console.error('Fast vote WS message error:', error);
        }
    };

    socket.onclose = () => {
        setTimeout(connectWebSocket, 3000);
    };
}
