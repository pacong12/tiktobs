// State management
let socket = null;
const alertQueue = [];
let isAlertActive = false;
let shownAlert = null;        // alert currently on screen
let comboHideTimer = null;
let comboFadeTimer = null;

// Streak combos (gift_type === 1) arrive as one event per increment. They are
// merged into ONE alert whose counter climbs live, and the sound plays once,
// at the start of the combo.
function comboKey(username, giftName) {
    return `${(username || '').toLowerCase()}|${(giftName || '').toLowerCase()}`;
}

// DOM Elements
const alertCard = document.getElementById('alert-card');
const alertUser = document.getElementById('alert-user');
const alertGiftName = document.getElementById('alert-gift-name');
const alertCombo = document.getElementById('alert-combo');
const alertEmoji = document.getElementById('gift-emoji');

let audioCtx = null;
let customSoundBuffer = null;
let alertVolume = 1.0;

const fallbackSoundPaths = [
    'sounds/dragon-studio-thud-sound-effect-405470.mp3',
    'sounds/gift-alert.wav',
    'sounds/gift-alert.mp3'
];

const baseUrl = window.location.protocol === 'file:' ? 'http://127.0.0.1:8000/' : '';

// Init
document.addEventListener('DOMContentLoaded', () => {
    initWebAudio();
    connectWebSocket();
});

// Resume AudioContext if suspended by browser autoplay policy
document.addEventListener('click', () => {
    if (audioCtx && audioCtx.state === 'suspended') {
        audioCtx.resume();
    }
});

async function initWebAudio() {
    try {
        audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    } catch (e) {
        console.error("Web Audio initialization error:", e);
        return;
    }
    await loadConfiguredSound();
}

// Fetch the chosen sound file (gift_sound) + volume from the server, then decode it.
async function loadConfiguredSound() {
    let filesToTry = fallbackSoundPaths;
    try {
        const res = await fetch(baseUrl + 'api/sounds');
        if (res.ok) {
            const data = await res.json();
            const cfg = data.config || {};
            if (typeof cfg.gift_volume === 'number') alertVolume = cfg.gift_volume;
            if (cfg.gift_sound) {
                // Explicit selection wins.
                filesToTry = ['sounds/' + cfg.gift_sound];
            } else if (cfg.gift_sound === '') {
                // Explicitly set to default synth chime.
                customSoundBuffer = null;
                return;
            } else if (data.sounds && data.sounds.length > 0) {
                filesToTry = data.sounds.map(f => 'sounds/' + f);
            }
        }
    } catch (e) {
        console.warn("Could not fetch /api/sounds list, using default sound paths:", e);
    }

    customSoundBuffer = null;
    for (const path of filesToTry) {
        try {
            const response = await fetch(baseUrl + path);
            if (response.ok) {
                const arrayBuffer = await response.arrayBuffer();
                customSoundBuffer = await audioCtx.decodeAudioData(arrayBuffer);
                console.log(`Web Audio decoded sound buffer successfully: ${path}`);
                break; // Stop on first successful file
            }
        } catch (err) {
            console.warn(`Could not load/decode sound file ${path}:`, err);
        }
    }
}

// Play Alert Sound via Web Audio API (0ms latency, supports unlimited simultaneous overlapping plays)
function playAlertSound() {
    try {
        if (!audioCtx) {
            audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        }

        if (audioCtx.state === 'suspended') {
            audioCtx.resume();
        }

        if (customSoundBuffer) {
            const source = audioCtx.createBufferSource();
            source.buffer = customSoundBuffer;
            const gainNode = audioCtx.createGain();
            gainNode.gain.value = alertVolume;
            source.connect(gainNode);
            gainNode.connect(audioCtx.destination);
            source.start(0);
            console.log("Played custom sound via Web Audio API!");
        } else {
            playDefaultChime();
        }
    } catch (err) {
        console.error("Error playing alert sound:", err);
    }
}

// Synthesize a chime programmatically (C5 -> E5 -> G5)
function playDefaultChime() {
    try {
        if (!audioCtx) return;
        const playNote = (freq, delay, duration) => {
            const osc = audioCtx.createOscillator();
            const gainNode = audioCtx.createGain();

            osc.type = 'triangle'; // Smooth bell-like tone
            osc.frequency.setValueAtTime(freq, audioCtx.currentTime + delay);

            gainNode.gain.setValueAtTime(0, audioCtx.currentTime + delay);
            gainNode.gain.linearRampToValueAtTime(0.25, audioCtx.currentTime + delay + 0.04);
            gainNode.gain.exponentialRampToValueAtTime(0.0001, audioCtx.currentTime + delay + duration);

            osc.connect(gainNode);
            gainNode.connect(audioCtx.destination);

            osc.start(audioCtx.currentTime + delay);
            osc.stop(audioCtx.currentTime + delay + duration);
        };

        // Play arpeggio
        playNote(523.25, 0.0, 0.5);  // C5
        playNote(659.25, 0.12, 0.5); // E5
        playNote(783.99, 0.24, 0.7); // G5
    } catch (err) {
        console.error('AudioContext synth failed:', err);
    }
}

// Map common gifts to emojis
function getGiftEmoji(giftName) {
    if (!giftName) return '🎁';
    const name = giftName.toLowerCase();
    if (name.includes('rose') || name.includes('mawar')) return '🌹';
    if (name.includes('heart') || name.includes('hati')) return '❤️';
    if (name.includes('finger')) return '🫰';
    if (name.includes('corona') || name.includes('crown')) return '👑';
    if (name.includes('diamond') || name.includes('berlian')) return '💎';
    if (name.includes('perfume') || name.includes('parfum')) return '💖';
    if (name.includes('ice cream') || name.includes('es krim')) return '🍦';
    if (name.includes('fire') || name.includes('api')) return '🔥';
    return '🎁';
}

function connectWebSocket() {
    const wsUrl = window.location.protocol === 'file:'
        ? 'ws://127.0.0.1:8000/ws'
        : `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws`;

    socket = new WebSocket(wsUrl);

    socket.onopen = () => {
        console.log('Gift alert overlay WebSocket connected.');
    };

    socket.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            if (msg.type === 'sound_config_update') {
                // Admin changed the sound selection/volume — reload without refresh.
                loadConfiguredSound();
                return;
            }
            if (msg.type === 'event' && msg.event && msg.event.event_type === 'gift') {
                const giftEvent = msg.event;
                const data = giftEvent.data || {};
                const sender = giftEvent.nickname || giftEvent.username;
                const giftName = data.gift_name;
                const count = data.quantity || 1;
                const isStreak = data.gift_type === 1;
                const isFinal = data.repeat_end === 1;
                const key = comboKey(giftEvent.username, giftName);
                const alert = { sender, giftName, count, streak: isStreak, final: isFinal, key };

                if (isStreak) {
                    // Combo already on screen -> update its counter in place.
                    if (isAlertActive && shownAlert && shownAlert.key === key) {
                        updateShownAlert(alert);
                        return;
                    }
                    // Same combo already waiting in the queue -> merge.
                    const queued = alertQueue.find(a => a.key === key);
                    if (queued) {
                        queued.count = count;
                        queued.final = isFinal;
                        return;
                    }
                    // New combo: sound plays once, right here.
                    try {
                        playAlertSound();
                    } catch (soundErr) {
                        console.error("Audio playback crashed during WS event:", soundErr);
                    }
                    alertQueue.push(alert);
                    processQueue();
                    return;
                }

                // Non-streak gift: alert per event (original behavior).
                try {
                    playAlertSound();
                } catch (soundErr) {
                    console.error("Audio playback crashed during WS event:", soundErr);
                }
                alertQueue.push({ sender, giftName, count, streak: false, final: true, key: null });
                processQueue();
            }
        } catch (error) {
            console.error('Error handling WS alert message:', error);
        }
    };

    socket.onclose = () => {
        console.log('Gift alert WebSocket closed. Reconnecting in 3 seconds...');
        setTimeout(connectWebSocket, 3000);
    };

    socket.onerror = (err) => {
        console.error('Gift alert WebSocket error:', err);
    };
}

function processQueue() {
    if (isAlertActive || alertQueue.length === 0) return;

    isAlertActive = true;
    shownAlert = alertQueue.shift();
    renderAlert(shownAlert);

    // Display popup
    alertCard.classList.add('show');
    scheduleHide();
}

function renderAlert(alert) {
    alertUser.textContent = alert.sender;
    alertGiftName.textContent = alert.giftName;
    alertEmoji.textContent = getGiftEmoji(alert.giftName);

    if (alert.count > 1) {
        alertCombo.textContent = `x${alert.count}`;
        alertCombo.style.display = 'inline-block';
    } else {
        alertCombo.style.display = 'none';
    }
}

// Live update while a combo is still climbing.
function updateShownAlert(alert) {
    shownAlert = alert;
    renderAlert(alert);
    alertCard.classList.remove('combo-pulse');
    void alertCard.offsetWidth; // restart the CSS animation
    alertCard.classList.add('combo-pulse');
    scheduleHide(); // keep it visible while the combo grows
}

function scheduleHide() {
    clearTimeout(comboHideTimer);
    clearTimeout(comboFadeTimer);

    // Keep visible for 2.2 seconds, then fade out
    comboHideTimer = setTimeout(() => {
        alertCard.classList.remove('show');

        // Wait 0.6 seconds for fadeout transition before processing next gift
        comboFadeTimer = setTimeout(() => {
            isAlertActive = false;
            shownAlert = null;
            processQueue();
        }, 600);
    }, 2200);
}
