// State variables
let socket = null;
let pollTimerInterval = null;

// TikTok popular gift catalog (name + diamond value) for the Gift Boost dropdown.
// TikTok has hundreds of gifts and they vary by region, so a "Ketik manual" option
// is always included to let the user type any gift name exactly.
const GIFT_CATALOG = [
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
    { name: 'Love you', d: 49 },
    { name: 'Cap', d: 99 },
    { name: 'Star', d: 99 },
    { name: 'Hand Hearts', d: 100 },
    { name: 'Confetti', d: 100 },
    { name: 'Sunglasses', d: 199 },
    { name: 'Hearts', d: 199 },
    { name: 'Rosa', d: 199 },
    { name: 'Corgi', d: 399 },
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

    GIFT_CATALOG.forEach(g => {
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
    // Populate the two initial candidate rows' Gift Boost dropdowns.
    document.querySelectorAll('.candidate-gift-cell').forEach(cell => {
        cell.replaceWith(buildGiftControl());
    });
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
            const rowCount = candidatesInputList.querySelectorAll('.candidate-input-row').length + 1;
            const newRow = document.createElement('div');
            newRow.className = 'candidate-input-row';
            newRow.innerHTML = `
                <input type="text" class="field-input candidate-name-input" placeholder="Pilihan ${rowCount}">
                <input type="text" class="field-input candidate-image-input" placeholder="URL Foto (opsional)">
                <div class="candidate-gift-cell"></div>
                <button class="candidate-remove-btn" title="Hapus pilihan" type="button">✕</button>
            `;
            newRow.querySelector('.candidate-gift-cell').replaceWith(buildGiftControl());
            candidatesInputList.appendChild(newRow);
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

    // Start poll
    if (startPollBtn) {
        startPollBtn.addEventListener('click', handleStartPoll);
    }

    // Stop poll
    if (stopPollBtn) {
        stopPollBtn.addEventListener('click', handleStopPoll);
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
        if (name) {
            candidates.push({ name, image_url: imageUrl, gift_name: giftName });
        }
    });

    if (candidates.length < 2) {
        alert('Minimal harus ada 2 pilihan (kandidat) yang diisi!');
        return;
    }

    const durationVal = document.getElementById('poll-duration-input').value.trim();
    const durationSeconds = durationVal ? parseInt(durationVal) : null;

    try {
        const response = await fetch('/api/poll/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title, round_name: roundName || null, candidates, duration_seconds: durationSeconds })
        });
        const data = await response.json();
        updatePollUI(data);
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
                        ${c.gift_name ? `<span class="rr-boost">(🎁 ${escapeHTML(c.gift_name)})</span>` : ''}
                    </span>
                    <span class="rr-track"><span class="rr-fill" style="width:${c.percentage}%;"></span></span>
                    <span class="rr-votes">${c.votes} (${c.percentage}%)</span>
                </div>`;
            }).join('');

        const card = document.createElement('div');
        card.className = 'round-card';
        card.innerHTML = `
            <div class="round-card-head">
                <div style="min-width:0;">
                    <div class="round-name">${escapeHTML(r.round_name)}</div>
                    <div class="round-title">${escapeHTML(r.title)}</div>
                    <div class="round-meta">${endedStr} • durasi: ${durText} • total: ${r.total_votes} suara</div>
                </div>
                <button class="round-delete-btn" data-id="${r.id}" title="Hapus ronde">🗑️</button>
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
        
        updateCountdown();
        pollTimerInterval = setInterval(updateCountdown, 1000);
    } else {
        countdownRow.classList.add('hidden');
    }

    pollActiveResults.innerHTML = '';
    const maxVotes = Math.max(0, ...poll.candidates.map(c => c.votes));
    poll.candidates.forEach(c => {
        const row = document.createElement('div');
        row.className = 'poll-result-row';
        if (maxVotes > 0 && c.votes === maxVotes) row.classList.add('is-leading');
        const giftTriggerText = c.gift_name ? ` <span class="result-boost">(Boost: 🎁 ${escapeHTML(c.gift_name)})</span>` : '';
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
