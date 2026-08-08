// State variables
let socket = null;
let pollTimerInterval = null;

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
    setupEventListeners();
    setupSoundEvents();
    await loadCurrentSound();
    await checkPollStatus();
    connectWebSocket();
}

function setupEventListeners() {
    // Add option candidate rows
    if (addCandidateBtn) {
        addCandidateBtn.addEventListener('click', () => {
            const rowCount = candidatesInputList.querySelectorAll('.candidate-input-row').length + 1;
            const newRow = document.createElement('div');
            newRow.className = 'candidate-input-row';
            newRow.style = 'display: flex; gap: 8px; margin-bottom: 10px;';
            newRow.innerHTML = `
                <input type="text" class="candidate-name-input" placeholder="Pilihan ${rowCount}" style="flex: 1; background: rgba(0,0,0,0.25); border: 1px solid rgba(255,255,255,0.1); border-radius: 6px; padding: 8px 10px; color: #fff; font-size: 12px; font-family: inherit;">
                <input type="text" class="candidate-image-input" placeholder="URL Foto (opsional)" style="flex: 1; background: rgba(0,0,0,0.25); border: 1px solid rgba(255,255,255,0.1); border-radius: 6px; padding: 8px 10px; color: #fff; font-size: 12px; font-family: inherit;">
                <input type="text" class="candidate-gift-input" placeholder="Gift Boost (opsional)" style="flex: 1; background: rgba(0,0,0,0.25); border: 1px solid rgba(255,255,255,0.1); border-radius: 6px; padding: 8px 10px; color: #fff; font-size: 12px; font-family: inherit;">
            `;
            candidatesInputList.appendChild(newRow);
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

    const rows = document.querySelectorAll('#candidates-input-list .candidate-input-row');
    const candidates = [];
    rows.forEach(row => {
        const name = row.querySelector('.candidate-name-input').value.trim();
        const imageUrl = row.querySelector('.candidate-image-input').value.trim() || null;
        const giftName = row.querySelector('.candidate-gift-input').value.trim() || null;
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
            body: JSON.stringify({ title, candidates, duration_seconds: durationSeconds })
        });
        const data = await response.json();
        updatePollUI(data);
    } catch (error) {
        console.error('Failed to start poll:', error);
        alert('Gagal memulai voting.');
    }
}

async function handleStopPoll() {
    if (!confirm('Apakah Anda yakin ingin menghentikan dan mereset voting ini?')) return;
    try {
        const response = await fetch('/api/poll/stop', { method: 'POST' });
        const data = await response.json();
        updatePollUI(data);
    } catch (error) {
        console.error('Failed to stop poll:', error);
        alert('Gagal menghentikan voting.');
    }
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
    poll.candidates.forEach(c => {
        const row = document.createElement('div');
        row.className = 'poll-result-row';
        row.style = 'font-size: 13px; margin-bottom: 12px;';
        const giftTriggerText = c.gift_name ? ` <span style="font-size: 11px; color: #ff007f; font-weight: 600;">(Boost: 🎁 ${escapeHTML(c.gift_name)})</span>` : '';
        row.innerHTML = `
            <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
                <span style="color: #ccc; font-weight: 500;">${c.id}. ${escapeHTML(c.name)}${giftTriggerText}</span>
                <span style="font-weight: 700; color: #00f0ff;">${c.votes} votes (${c.percentage}%)</span>
            </div>
            <div style="height: 8px; background: rgba(255,255,255,0.08); border-radius: 4px; overflow: hidden;">
                <div style="width: ${c.percentage}%; height: 100%; background: linear-gradient(90deg, #00f0ff, #0072ff); border-radius: 4px; transition: width 0.3s ease;"></div>
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
const currentSoundName = document.getElementById('current-sound-name');
const testSoundBtn = document.getElementById('test-sound-btn');

async function loadCurrentSound() {
    try {
        const res = await fetch('/api/sounds');
        if (res.ok) {
            const data = await res.json();
            if (data.sounds && data.sounds.length > 0) {
                currentSoundName.textContent = data.sounds[0];
            } else {
                currentSoundName.textContent = "Default Sound";
            }
        }
    } catch (e) {
        console.warn("Could not fetch sounds list:", e);
    }
}

function setupSoundEvents() {
    if (uploadSoundBtn && soundUploadInput) {
        uploadSoundBtn.addEventListener('click', async () => {
            const file = soundUploadInput.files[0];
            if (!file) {
                alert('Pilih file suara (.mp3 atau .wav) terlebih dahulu!');
                return;
            }
            
            const formData = new FormData();
            formData.append('file', file);
            
            uploadSoundBtn.disabled = true;
            uploadSoundBtn.textContent = 'Uploading...';
            
            try {
                const res = await fetch('/api/upload-sound', {
                    method: 'POST',
                    body: formData
                });
                
                const data = await res.json();
                if (res.ok) {
                    alert(`Suara berhasil diupload! (${data.filename})`);
                    currentSoundName.textContent = data.filename;
                    soundUploadInput.value = '';
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
    
    if (testSoundBtn) {
        testSoundBtn.addEventListener('click', () => {
            const filename = currentSoundName.textContent.strip ? currentSoundName.textContent.strip() : currentSoundName.textContent.trim();
            let soundUrl = '/sounds/dragon-studio-thud-sound-effect-405470.mp3';
            if (filename && filename !== 'Default Sound') {
                soundUrl = '/sounds/' + filename;
            }
            
            const audio = new Audio(soundUrl);
            audio.currentTime = 0;
            audio.play()
                .then(() => {
                    console.log("Test sound played successfully:", soundUrl);
                })
                .catch(err => {
                    console.warn("Could not play sound preview:", err);
                    alert("Browser memblokir suara otomatis. Klik sekali lagi di area layar ini lalu coba lagi!");
                });
        });
    }
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
