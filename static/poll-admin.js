// State variables
let socket = null;
let pollTimerInterval = null;

// Full catalog populated from window.GIFT_ICONS (705+ gifts) + popular presets.
let GIFT_CATALOG = [
    { name: 'Rose', d: 1 },
    { name: 'TikTok', d: 1 },
    { name: 'Ice Cream Cone', d: 1 },
    { name: 'Heart', d: 1 },
    { name: 'GG', d: 1 },
    { name: 'Chic', d: 9 },
    { name: 'Finger Heart', d: 5 },
    { name: 'Friendship Necklace', d: 10 },
    { name: 'Perfume', d: 20 },
    { name: 'Doughnut', d: 30 },
    { name: 'Love you', d: 199 },
    { name: 'Cap', d: 99 },
    { name: 'Star', d: 99 },
    { name: 'Hand Hearts', d: 100 },
    { name: 'Confetti', d: 100 },
    { name: 'Sunglasses', d: 199 },
    { name: 'Hearts', d: 199 },
    { name: 'Rosa', d: 10 },
    { name: 'Corgi', d: 299 },
    { name: 'Coral', d: 499 },
    { name: 'Money Gun', d: 500 },
    { name: 'Dolphin', d: 700 },
    { name: 'Train', d: 899 },
    { name: 'Lightning Bolt', d: 999 },
    { name: 'Galaxy', d: 1000 },
    { name: 'Diamond', d: 1000 },
    { name: 'Rocket', d: 20000 },
    { name: 'Lion', d: 29999 },
    { name: 'Universe', d: 34999 },
    { name: 'TikTok Universe', d: 44999 },
];

// Dynamically expand catalog with all known icons & prices from window.GIFT_PRICES / window.GIFT_ICONS
function expandGiftCatalogFromIcons() {
    const icons = window.GIFT_ICONS || {};
    const prices = window.GIFT_PRICES || {};
    const existing = new Set(GIFT_CATALOG.map(g => g.name.toLowerCase()));
    
    Object.keys(icons).forEach(rawKey => {
        const formattedName = rawKey.split(' ').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
        if (!existing.has(rawKey)) {
            existing.add(rawKey);
            const diamondValue = prices[rawKey] !== undefined ? prices[rawKey] : '?';
            GIFT_CATALOG.push({ name: formattedName, d: diamondValue });
        }
    });
}

if (typeof window !== 'undefined') {
    expandGiftCatalogFromIcons();
}

// Builds the Gift Boost control: a <select> dropdown + a hidden manual-entry input
// that appears only when "Ketik manual…" is chosen. `preset` pre-selects a value.
function buildGiftControl(preset) {
    const wrap = document.createElement('div');
    wrap.className = 'gift-control';

    const select = document.createElement('select');
    select.className = 'field-input candidate-gift-select';

    const noneOpt = document.createElement('option');
    noneOpt.value = '';
    noneOpt.textContent = 'Gift Boost (tidak ada)';
    select.appendChild(noneOpt);

    // Sort catalog: popular presets first, then alphabetical for 700+ extra gifts
    expandGiftCatalogFromIcons();
    
    // Sort gifts alphabetically for clean dropdown browsing
    const popularNames = new Set(['Rose', 'TikTok', 'Ice Cream Cone', 'Heart', 'GG', 'Thumbs Up', 'Coffee', 'Cake Slice', 'Football', 'Basketball']);
    const popularGifts = GIFT_CATALOG.filter(g => popularNames.has(g.name));
    const otherGifts = GIFT_CATALOG.filter(g => !popularNames.has(g.name)).sort((a, b) => a.name.localeCompare(b.name));
    
    const sortedCatalog = [...popularGifts, ...otherGifts];

    sortedCatalog.forEach(g => {
        const opt = document.createElement('option');
        opt.value = g.name;
        opt.textContent = `${g.name} — ${g.d} 💎`;
        select.appendChild(opt);
    });

    const customOpt = document.createElement('option');
    customOpt.value = '__custom__';
    customOpt.textContent = '✏️ Ketik manual…';
    select.appendChild(customOpt);

    const manual = document.createElement('input');
    manual.type = 'text';
    manual.className = 'field-input candidate-gift-manual';
    manual.placeholder = 'Nama gift persis (mis. Galaxy)';
    manual.style.display = 'none';
    manual.style.marginTop = '6px';

    // Pre-fill from an existing value (e.g. when reopening an active poll).
    if (preset) {
        const known = GIFT_CATALOG.some(g => g.name.toLowerCase() === preset.toLowerCase());
        if (known) {
            select.value = GIFT_CATALOG.find(g => g.name.toLowerCase() === preset.toLowerCase()).name;
        } else {
            select.value = '__custom__';
            manual.value = preset;
            manual.style.display = 'block';
        }
    }

    select.addEventListener('change', () => {
        manual.style.display = select.value === '__custom__' ? 'block' : 'none';
        if (select.value !== '__custom__') manual.value = '';
    });

    wrap.appendChild(select);
    wrap.appendChild(manual);
    return wrap;
}

// Builds one candidate input row, optionally pre-filled (used when loading
// a past round's candidates back into the setup form).
// Futuristic neon palette used to auto-assign card border colors when a
// candidate does not pick one explicitly.
const CARD_PALETTE = ['#00e5ff', '#ff2d78', '#ffd60a', '#7c4dff', '#00ff9d', '#ff9100'];

function createCandidateRow(name = '', imageUrl = '', giftPreset = null, color = '') {
    const rowCount = candidatesInputList.querySelectorAll('.candidate-input-row').length + 1;
    const row = document.createElement('div');
    row.className = 'candidate-input-row';
    row.innerHTML = `
        <input type="text" class="field-input candidate-name-input" placeholder="Pilihan ${rowCount}">
        <div style="display:flex; gap:4px; align-items:center; flex:1;">
            <input type="text" class="field-input candidate-image-input" placeholder="URL Foto (opsional)" style="flex:1;">
            <label class="btn secondary" style="cursor:pointer; padding:6px 10px; font-size:12px; margin:0;" title="Upload foto HD dari komputer">
                📁 Upload
                <input type="file" accept="image/*" class="candidate-file-upload" style="display:none;">
            </label>
        </div>
        <div class="candidate-gift-cell"></div>
        <input type="color" class="candidate-color-input" title="Warna border kartu overlay" value="">
        <button class="candidate-remove-btn" title="Hapus pilihan" type="button">✕</button>
    `;
    row.querySelector('.candidate-name-input').value = name;
    const imgInput = row.querySelector('.candidate-image-input');
    imgInput.value = imageUrl || '';
    
    // File upload handler for HD local photos
    const fileUpload = row.querySelector('.candidate-file-upload');
    fileUpload.addEventListener('change', async (e) => {
        const file = e.target.files[0];
        if (!file) return;
        const formData = new FormData();
        formData.append('file', file);
        try {
            const res = await fetch('/api/upload-image', { method: 'POST', body: formData });
            const data = await res.json();
            if (data.url) {
                imgInput.value = data.url;
                showToast(`Foto HD '${file.name}' berhasil diunggah!`);
            } else {
                alert('Gagal mengunggah foto: ' + (data.detail || 'Error'));
            }
        } catch (err) {
            console.error('Upload image error:', err);
            alert('Gagal mengunggah foto.');
        }
    });

    // Default to the palette color for this row index unless reusing a saved one.
    row.querySelector('.candidate-color-input').value =
        color || CARD_PALETTE[(rowCount - 1) % CARD_PALETTE.length];
    row.querySelector('.candidate-gift-cell').replaceWith(buildGiftControl(giftPreset));
    return row;
}

// Replaces the whole candidate form with the candidates, title, round name & duration of an archived round.
function loadPastRoundIntoForm(roundData) {
    const candidates = roundData.candidates;
    if (!Array.isArray(candidates) || candidates.length < 2) {
        alert('Ronde ini tidak punya cukup kandidat untuk dipakai ulang.');
        return;
    }
    candidatesInputList.innerHTML = '';
    candidates.forEach(c => {
        candidatesInputList.appendChild(
            createCandidateRow(c.name || '', c.image_url || '', c.gift_name || null, c.color || '')
        );
    });

    // Reuse round name, title, and duration
    const pollTitleInput = document.getElementById('poll-title-input');
    const pollRoundInput = document.getElementById('poll-round-input');
    const pollDurationInput = document.getElementById('poll-duration-input');

    if (pollTitleInput && roundData.title) pollTitleInput.value = roundData.title;
    if (pollRoundInput && roundData.round_name) pollRoundInput.value = roundData.round_name;
    if (pollDurationInput && roundData.duration_seconds !== undefined && roundData.duration_seconds !== null) {
        pollDurationInput.value = roundData.duration_seconds > 0 ? roundData.duration_seconds : '';
    }

    // Bring the form into view so the user sees the loaded setup.
    document.getElementById('poll-setup-section')?.scrollIntoView({ behavior: 'smooth' });
    showToast(`Pengaturan ronde '${roundData.round_name || 'Riwayat'}' dimuat ke form.`);
}

// Small transient toast for admin feedback.
function showToast(message) {
    let toast = document.getElementById('admin-toast');
    if (!toast) {
        toast = document.createElement('div');
        toast.id = 'admin-toast';
        document.body.appendChild(toast);
    }
    toast.textContent = message;
    toast.classList.add('show');
    clearTimeout(toast._hideTimer);
    toast._hideTimer = setTimeout(() => toast.classList.remove('show'), 2600);
}

// Reads the chosen gift name from a candidate row (dropdown or manual entry).
function readGiftValue(row) {
    const select = row.querySelector('.candidate-gift-select');
    if (!select) return null;
    if (select.value === '__custom__') {
        const manual = row.querySelector('.candidate-gift-manual');
        return (manual && manual.value.trim()) || null;
    }
    return select.value.trim() || null;
}

// DOM Elements
const pollSetupSection = document.getElementById('poll-setup-section');
const pollActiveConfigHint = document.getElementById('poll-active-config-hint');
const pollSetupPreview = document.getElementById('poll-setup-preview');
const pollActiveSection = document.getElementById('poll-active-section');
const pollActiveTitle = document.getElementById('poll-active-title');
const pollActiveTotal = document.getElementById('poll-active-total');
const pollActiveResults = document.getElementById('poll-active-results');
const countdownRow = document.getElementById('poll-active-countdown');
const countdownTimer = document.getElementById('poll-active-timer');

const addCandidateBtn = document.getElementById('add-candidate-btn');
const candidatesInputList = document.getElementById('candidates-input-list');
const startPollBtn = document.getElementById('start-poll-btn');
const stopPollBtn = document.getElementById('stop-poll-btn');
const pollActiveRound = document.getElementById('poll-active-round');

// Round history
const roundsHistoryList = document.getElementById('rounds-history-list');
const roundsEmpty = document.getElementById('rounds-empty');
const clearRoundsBtn = document.getElementById('clear-rounds-btn');

// Simulation Controls
const simulationPanel = document.getElementById('simulation-panel');
const testCommentVoteBtn = document.getElementById('test-comment-vote-btn');
const testGiftVoteBtn = document.getElementById('test-gift-vote-btn');
const testGiftNormalBtn = document.getElementById('test-gift-normal-btn');

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    initPollAdmin();
});

async function initPollAdmin() {
    // Re-render initial candidate rows dynamically using createCandidateRow so upload buttons exist
    candidatesInputList.innerHTML = '';
    candidatesInputList.appendChild(createCandidateRow());
    candidatesInputList.appendChild(createCandidateRow());

    setupEventListeners();
    setupSoundEvents();
    await loadCurrentSound();
    await checkPollStatus();
    await loadRounds();
    connectWebSocket();
}

function setupEventListeners() {
    // Add option candidate rows
    if (addCandidateBtn) {
        addCandidateBtn.addEventListener('click', () => {
            candidatesInputList.appendChild(createCandidateRow());
        });
    }

    // Remove candidate rows (event delegation). Keep a minimum of 2 rows.
    if (candidatesInputList) {
        candidatesInputList.addEventListener('click', (e) => {
            const btn = e.target.closest('.candidate-remove-btn');
            if (!btn) return;
            const rows = candidatesInputList.querySelectorAll('.candidate-input-row');
            if (rows.length <= 2) {
                alert('Minimal harus ada 2 pilihan.');
                return;
            }
            btn.closest('.candidate-input-row').remove();
        });
    }

    // Live "menit" hint for the duration input
    const durationInput = document.getElementById('poll-duration-input');
    const durationHint = document.getElementById('duration-hint');
    if (durationInput && durationHint) {
        durationInput.addEventListener('input', () => {
            const v = parseInt(durationInput.value);
            if (!v || v < 5) {
                durationHint.textContent = 'Kosongkan untuk voting tanpa batas waktu.';
                durationHint.classList.remove('warn');
            } else {
                const m = Math.floor(v / 60);
                const s = v % 60;
                const parts = [];
                if (m) parts.push(`${m} menit`);
                if (s) parts.push(`${s} detik`);
                durationHint.textContent = `≈ ${parts.join(' ')}`;
                durationHint.classList.remove('warn');
            }
        });
    }

    // Start poll
    if (startPollBtn) {
        startPollBtn.addEventListener('click', handleStartPoll);
    }

    // Stop poll
    if (stopPollBtn) {
        stopPollBtn.addEventListener('click', handleStopPoll);
    }

    // Load a past round's full setup (candidates, title, round name, duration) back into the setup form
    if (roundsHistoryList) {
        roundsHistoryList.addEventListener('click', (e) => {
            const btn = e.target.closest('.round-reuse-btn');
            if (!btn) return;
            const card = btn.closest('.round-card');
            if (!card || !card.dataset.roundData) return;
            try {
                const roundData = JSON.parse(card.dataset.roundData);
                loadPastRoundIntoForm(roundData);
            } catch (err) {
                console.error('Failed to parse archived round data:', err);
            }
        });
    }

    // Clear round history
    if (clearRoundsBtn) {
        clearRoundsBtn.addEventListener('click', handleClearRounds);
    }

    // Simulation tool buttons
    if (testCommentVoteBtn) {
        testCommentVoteBtn.addEventListener('click', () => triggerSimulation('/api/test/comment-vote'));
    }
    if (testGiftVoteBtn) {
        testGiftVoteBtn.addEventListener('click', () => triggerSimulation('/api/test/gift-vote'));
    }
    if (testGiftNormalBtn) {
        testGiftNormalBtn.addEventListener('click', () => triggerSimulation('/api/test/gift-normal'));
    }
}

async function triggerSimulation(endpoint) {
    try {
        const res = await fetch(endpoint, { method: 'POST' });
        if (!res.ok) {
            const err = await res.json();
            alert(`Simulation failed: ${err.detail || 'Unknown error'}`);
            return;
        }
        console.log(`Simulation triggered successfully: ${endpoint}`);
    } catch (err) {
        console.error('Error triggering simulation:', err);
    }
}

async function handleStartPoll() {
    const titleInput = document.getElementById('poll-title-input');
    const title = titleInput.value.trim();
    if (!title) {
        alert('Tulis pertanyaan/judul voting terlebih dahulu!');
        return;
    }

    const roundName = document.getElementById('poll-round-input').value.trim();

    const rows = document.querySelectorAll('#candidates-input-list .candidate-input-row');
    const candidates = [];
    rows.forEach(row => {
        const name = row.querySelector('.candidate-name-input').value.trim();
        const imageUrl = row.querySelector('.candidate-image-input').value.trim() || null;
        const giftName = readGiftValue(row);
        const colorVal = row.querySelector('.candidate-color-input')?.value || '';
        if (name) {
            candidates.push({ name, image_url: imageUrl, gift_name: giftName, color: colorVal });
        }
    });

    if (candidates.length < 2) {
        alert('Minimal harus ada 2 pilihan (kandidat) yang diisi!');
        return;
    }

    const durationVal = document.getElementById('poll-duration-input').value.trim();
    const durationSeconds = durationVal ? parseInt(durationVal) : null;

    const includeHistory = document.getElementById('include-history-check')?.checked || false;

    try {
        const response = await fetch('/api/poll/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title, round_name: roundName || null, candidates, duration_seconds: durationSeconds, include_history: includeHistory })
        });
        const data = await response.json();
        if (!response.ok) {
            alert(`Gagal memulai voting: ${data.detail || 'error'}`);
            return;
        }
        updatePollUI(data);
        if (includeHistory && data.history_applied) {
            const h = data.history_applied;
            if (h.votes > 0) {
                alert(`Riwayat sesi dihitung: +${h.votes} suara (${h.comments} komentar, ${h.gifts} gift).`);
            } else {
                alert('Riwayat sesi diperiksa, tapi tidak ada komentar/gift yang cocok dengan kandidat.');
            }
        }
    } catch (error) {
        console.error('Failed to start poll:', error);
        alert('Gagal memulai voting.');
    }
}

async function handleStopPoll() {
    if (!confirm('Hentikan ronde ini? Hasilnya akan otomatis tersimpan ke Riwayat Ronde.')) return;
    try {
        const response = await fetch('/api/poll/stop', { method: 'POST' });
        const data = await response.json();
        // New response shape: { poll, archived }. Fall back to old shape for safety.
        const poll = data.poll || data;
        updatePollUI(poll);
        await loadRounds();
    } catch (error) {
        console.error('Failed to stop poll:', error);
        alert('Gagal menghentikan voting.');
    }
}

async function handleClearRounds() {
    if (!confirm('Hapus SEMUA riwayat ronde? Tindakan ini tidak bisa dibatalkan.')) return;
    try {
        await fetch('/api/poll/rounds/clear', { method: 'POST' });
        await loadRounds();
    } catch (error) {
        console.error('Failed to clear rounds:', error);
    }
}

async function deleteRound(id) {
    if (!confirm('Hapus ronde ini dari riwayat?')) return;
    try {
        await fetch(`/api/poll/rounds/${id}`, { method: 'DELETE' });
        await loadRounds();
    } catch (error) {
        console.error('Failed to delete round:', error);
    }
}

async function loadRounds() {
    try {
        const res = await fetch('/api/poll/rounds');
        if (!res.ok) return;
        const data = await res.json();
        renderRounds(data.rounds || []);
    } catch (error) {
        console.error('Failed to load rounds:', error);
    }
}

function renderRounds(rounds) {
    if (!roundsHistoryList) return;
    roundsHistoryList.innerHTML = '';

    if (!rounds.length) {
        if (roundsEmpty) roundsEmpty.style.display = 'block';
        return;
    }
    if (roundsEmpty) roundsEmpty.style.display = 'none';

    rounds.forEach(r => {
        const winner = (r.candidates || []).reduce((best, c) => (!best || c.votes > best.votes ? c : best), null);
        const endedStr = r.ended_at ? new Date(r.ended_at).toLocaleString() : '';
        const durText = r.duration_seconds ? `${r.duration_seconds}s` : 'manual';

        const rowsHtml = (r.candidates || [])
            .slice()
            .sort((a, b) => b.votes - a.votes)
            .map(c => {
                const isWinner = winner && c.id === winner.id && r.total_votes > 0;
                return `
                <div class="round-row${isWinner ? ' rr-winner' : ''}">
                    <span class="rr-name">
                        ${isWinner ? '🏆 ' : ''}${escapeHTML(c.name)}
                        ${c.gift_name ? `<span class="rr-boost">(${giftIconInline(c.gift_name)} ${escapeHTML(c.gift_name)})</span>` : ''}
                    </span>
                    <span class="rr-track"><span class="rr-fill" style="width:${c.percentage}%;"></span></span>
                    <span class="rr-votes">${c.votes} (${c.percentage}%)</span>
                </div>`;
            }).join('');

        const card = document.createElement('div');
        card.className = 'round-card';
        // Archived round setup travels with the card so the "Pakai lagi" button can refill the full setup form.
        const reusableSetup = {
            round_name: r.round_name || '',
            title: r.title || '',
            duration_seconds: r.duration_seconds || 0,
            candidates: (r.candidates || []).map(c => ({
                name: c.name || '',
                image_url: c.image_url || '',
                gift_name: c.gift_name || ''
            }))
        };
        card.dataset.roundData = JSON.stringify(reusableSetup);
        card.innerHTML = `
            <div class="round-card-head">
                <div style="min-width:0;">
                    <div class="round-name">${escapeHTML(r.round_name)}</div>
                    <div class="round-title">${escapeHTML(r.title)}</div>
                    <div class="round-meta">${endedStr} • durasi: ${durText} • total: ${r.total_votes} suara</div>
                </div>
                <div class="round-card-actions">
                    <button class="round-reuse-btn" title="Pakai kandidat ronde ini lagi" type="button">♻️ Pakai lagi</button>
                    <button class="round-delete-btn" data-id="${r.id}" title="Hapus ronde">🗑️</button>
                </div>
            </div>
            ${rowsHtml}
        `;
        roundsHistoryList.appendChild(card);
    });

    roundsHistoryList.querySelectorAll('.round-delete-btn').forEach(btn => {
        btn.addEventListener('click', () => deleteRound(parseInt(btn.dataset.id)));
    });
}

async function checkPollStatus() {
    try {
        const response = await fetch('/api/poll/status');
        const data = await response.json();
        updatePollUI(data);
    } catch (error) {
        console.error('Failed to check poll status:', error);
    }
}

function updatePollUI(poll) {
    // Clear timer
    if (pollTimerInterval) {
        clearInterval(pollTimerInterval);
        pollTimerInterval = null;
    }

    if (!poll || !poll.is_active) {
        // Show setup form, hide results panel
        pollSetupSection.classList.remove('hidden');
        pollActiveConfigHint.classList.add('hidden');
        pollSetupPreview.classList.remove('hidden');
        pollActiveSection.classList.add('hidden');
        if (simulationPanel) simulationPanel.classList.add('hidden');
        return;
    }

    // Hide setup form, show active results panel
    pollSetupSection.classList.add('hidden');
    pollActiveConfigHint.classList.remove('hidden');
    pollSetupPreview.classList.add('hidden');
    pollActiveSection.classList.remove('hidden');
    if (simulationPanel) simulationPanel.classList.remove('hidden');

    pollActiveTitle.textContent = poll.title;
    pollActiveTotal.textContent = poll.total_votes.toLocaleString();
    if (pollActiveRound) {
        pollActiveRound.textContent = poll.round_name ? poll.round_name : 'Voting Active';
    }

    // Setup timer
    if (poll.expires_at) {
        countdownRow.classList.remove('hidden');
        
        const updateCountdown = () => {
            const expireTime = new Date(poll.expires_at).getTime();
            const now = new Date().getTime();
            const secLeft = Math.max(0, Math.round((expireTime - now) / 1000));
            
            if (secLeft <= 0) {
                countdownTimer.textContent = '00:00';
                clearInterval(pollTimerInterval);
                pollTimerInterval = null;
            } else {
                const mins = Math.floor(secLeft / 60).toString().padStart(2, '0');
                const secs = (secLeft % 60).toString().padStart(2, '0');
                countdownTimer.textContent = `${mins}:${secs}`;
            }
        };
        
        if (!pollTimerInterval) {
            updateCountdown();
            pollTimerInterval = setInterval(updateCountdown, 1000);
        }
    } else {
        countdownRow.classList.add('hidden');
    }

    const existingRows = pollActiveResults.querySelectorAll('.poll-result-row');
    const maxVotes = Math.max(0, ...poll.candidates.map(c => c.votes));

    if (existingRows.length === poll.candidates.length) {
        poll.candidates.forEach((c, i) => {
            const row = existingRows[i];
            if (!row) return;
            if (maxVotes > 0 && c.votes === maxVotes) {
                row.classList.add('is-leading');
            } else {
                row.classList.remove('is-leading');
            }
            const votesEl = row.querySelector('.result-votes');
            const fillEl = row.querySelector('.progress-fill');
            if (votesEl) votesEl.textContent = `${c.votes} suara (${c.percentage}%)`;
            if (fillEl) fillEl.style.width = `${c.percentage}%`;
        });
    } else {
        pollActiveResults.innerHTML = '';
        poll.candidates.forEach(c => {
            const row = document.createElement('div');
            row.className = 'poll-result-row';
            if (maxVotes > 0 && c.votes === maxVotes) row.classList.add('is-leading');
            const giftTriggerText = c.gift_name ? ` <span class="result-boost">(Boost: ${giftIconInline(c.gift_name)} ${escapeHTML(c.gift_name)})</span>` : '';
            row.innerHTML = `
                <div class="result-top">
                    <span class="result-name">${c.id}. ${escapeHTML(c.name)}${giftTriggerText}</span>
                    <span class="result-votes">${c.votes} suara (${c.percentage}%)</span>
                </div>
                <div class="progress-track">
                    <div class="progress-fill" style="width: ${c.percentage}%;"></div>
                </div>
            `;
            pollActiveResults.appendChild(row);
        });
    }
}

function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws`;

    socket = new WebSocket(wsUrl);

    socket.onopen = () => {
        console.log('Poll admin WebSocket connected.');
    };

    socket.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            if (msg.type === 'poll_update') {
                updatePollUI(msg.poll);
            } else if (msg.type === 'poll_round_archived') {
                // A round finished (e.g. via timer) — refresh the history panel.
                loadRounds();
            } else if (msg.type === 'poll_gift_ignored') {
                // Someone sent a gift no candidate owns: it counted for nobody.
                // Surface it so the host can tell the sender (and maybe fix
                // the candidate gift assignments).
                const icon = typeof giftIconInline === 'function' ? giftIconInline(msg.gift_name) : '';
                showToast(`⚠️ Gift ${icon} ${msg.gift_name} dari ${msg.nickname || msg.username} TIDAK dihitung — tidak ada kandidat dengan gift itu.`);
            }
        } catch (error) {
            console.error('Error handling WebSocket message:', error);
        }
    };

    socket.onclose = () => {
        console.log('Poll admin WebSocket disconnected. Reconnecting in 3 seconds...');
        setTimeout(connectWebSocket, 3000);
    };

    socket.onerror = (err) => {
        console.error('Poll admin WebSocket error:', err);
    };
}

// Sound Management Logic
const soundUploadInput = document.getElementById('sound-upload-input');
const uploadSoundBtn = document.getElementById('upload-sound-btn');
const giftSoundSelect = document.getElementById('gift-sound-select');
const voteSoundSelect = document.getElementById('vote-sound-select');
const giftVolume = document.getElementById('gift-volume');
const voteVolume = document.getElementById('vote-volume');
const giftVolumeValue = document.getElementById('gift-volume-value');
const voteVolumeValue = document.getElementById('vote-volume-value');

const DEFAULT_SOUND_URL = '/sounds/dragon-studio-thud-sound-effect-405470.mp3';
let availableSounds = [];

function fillSoundSelect(selectEl, selectedValue) {
    if (!selectEl) return;
    selectEl.innerHTML = '';
    const defOpt = document.createElement('option');
    defOpt.value = '';
    defOpt.textContent = '🔔 Default (chime bawaan)';
    selectEl.appendChild(defOpt);
    availableSounds.forEach(name => {
        const opt = document.createElement('option');
        opt.value = name;
        opt.textContent = name;
        selectEl.appendChild(opt);
    });
    selectEl.value = selectedValue || '';
}

async function loadCurrentSound() {
    try {
        const res = await fetch('/api/sounds');
        if (!res.ok) return;
        const data = await res.json();
        availableSounds = data.sounds || [];
        const cfg = data.config || {};

        fillSoundSelect(giftSoundSelect, cfg.gift_sound);
        fillSoundSelect(voteSoundSelect, cfg.vote_sound);

        const gVol = typeof cfg.gift_volume === 'number' ? Math.round(cfg.gift_volume * 100) : 100;
        const vVol = typeof cfg.vote_volume === 'number' ? Math.round(cfg.vote_volume * 100) : 100;
        if (giftVolume) { giftVolume.value = gVol; giftVolumeValue.textContent = gVol + '%'; }
        if (voteVolume) { voteVolume.value = vVol; voteVolumeValue.textContent = vVol + '%'; }
    } catch (e) {
        console.warn("Could not fetch sounds list:", e);
    }
}

async function saveSoundConfig(partial) {
    try {
        const res = await fetch('/api/sound-config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(partial)
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            alert(`Gagal menyimpan pengaturan suara: ${err.detail || 'error'}`);
        }
    } catch (e) {
        console.error("Failed to save sound config:", e);
    }
}

function playPreview(filename, volume) {
    const url = filename ? '/sounds/' + filename : DEFAULT_SOUND_URL;
    const audio = new Audio(url);
    audio.volume = typeof volume === 'number' ? volume : 1.0;
    audio.currentTime = 0;
    audio.play().catch(err => {
        console.warn("Could not play sound preview:", err);
        alert("Browser memblokir suara otomatis. Klik sekali di area layar ini lalu coba lagi!");
    });
}

function setupSoundEvents() {
    // Upload
    if (uploadSoundBtn && soundUploadInput) {
        uploadSoundBtn.addEventListener('click', async () => {
            const file = soundUploadInput.files[0];
            if (!file) {
                alert('Pilih file suara (.mp3, .wav, .ogg, .m4a) terlebih dahulu!');
                return;
            }
            const formData = new FormData();
            formData.append('file', file);
            uploadSoundBtn.disabled = true;
            uploadSoundBtn.textContent = 'Uploading...';
            try {
                const res = await fetch('/api/upload-sound', { method: 'POST', body: formData });
                const data = await res.json();
                if (res.ok) {
                    soundUploadInput.value = '';
                    await loadCurrentSound();
                    alert(`Suara berhasil diupload! (${data.filename})\nPilih di dropdown untuk mengaktifkannya.`);
                } else {
                    alert(`Gagal upload: ${data.detail || 'Terjadi kesalahan'}`);
                }
            } catch (err) {
                console.error("Upload error:", err);
                alert('Gagal mengupload file suara.');
            } finally {
                uploadSoundBtn.disabled = false;
                uploadSoundBtn.textContent = '📤 Upload';
            }
        });
    }

    // Sound selection dropdowns
    if (giftSoundSelect) {
        giftSoundSelect.addEventListener('change', () => saveSoundConfig({ gift_sound: giftSoundSelect.value }));
    }
    if (voteSoundSelect) {
        voteSoundSelect.addEventListener('change', () => saveSoundConfig({ vote_sound: voteSoundSelect.value }));
    }

    // Volume sliders (update label live, save on release)
    if (giftVolume) {
        giftVolume.addEventListener('input', () => { giftVolumeValue.textContent = giftVolume.value + '%'; });
        giftVolume.addEventListener('change', () => saveSoundConfig({ gift_volume: parseInt(giftVolume.value) / 100 }));
    }
    if (voteVolume) {
        voteVolume.addEventListener('input', () => { voteVolumeValue.textContent = voteVolume.value + '%'; });
        voteVolume.addEventListener('change', () => saveSoundConfig({ vote_volume: parseInt(voteVolume.value) / 100 }));
    }

    // Test buttons
    document.querySelectorAll('.sound-test-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            if (btn.dataset.type === 'gift') {
                playPreview(giftSoundSelect.value, parseInt(giftVolume.value) / 100);
            } else {
                playPreview(voteSoundSelect.value, parseInt(voteVolume.value) / 100);
            }
        });
    });

    // Delete selected sound file
    document.querySelectorAll('.sound-delete-btn').forEach(btn => {
        btn.addEventListener('click', async () => {
            const target = btn.dataset.target;
            const selectEl = target === 'gift' ? giftSoundSelect : voteSoundSelect;
            const filename = selectEl.value;
            if (!filename) {
                alert('Pilih file suara (bukan Default) untuk dihapus.');
                return;
            }
            if (!confirm(`Hapus file suara "${filename}"? File akan hilang permanen.`)) return;
            try {
                const res = await fetch(`/api/sounds/${encodeURIComponent(filename)}`, { method: 'DELETE' });
                if (res.ok) {
                    await loadCurrentSound();
                } else {
                    const err = await res.json().catch(() => ({}));
                    alert(`Gagal menghapus: ${err.detail || 'error'}`);
                }
            } catch (e) {
                console.error("Delete error:", e);
                alert('Gagal menghapus file suara.');
            }
        });
    });
}

// Helper: Escape HTML
// Official TikTok gift icon (inline, for text labels) with 🎁 fallback.
function giftIconKey(name) {
    return ((name || '').toLowerCase().replace(/[^\w\s]/g, ' ').replace(/\s+/g, ' ').trim());
}
function giftIconInline(giftName) {
    const icons = window.GIFT_ICONS || {};
    const url = icons[giftIconKey(giftName)];
    if (!url) return '🎁';
    return `<img class="gift-icon-inline" src="${url}" alt="" loading="lazy" onerror="this.outerHTML='🎁'">`;
}

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
