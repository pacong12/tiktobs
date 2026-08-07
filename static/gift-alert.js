// State management
let socket = null;
const alertQueue = [];
let isAlertActive = false;

// DOM Elements
const alertCard = document.getElementById('alert-card');
const alertUser = document.getElementById('alert-user');
const alertGiftName = document.getElementById('alert-gift-name');
const alertCombo = document.getElementById('alert-combo');
const alertEmoji = document.getElementById('gift-emoji');

let audioCtx = null;
let customSoundBuffer = null;

const soundPaths = [
    'sounds/dragon-studio-thud-sound-effect-405470.mp3',
    'sounds/gift-alert.wav',
    'sounds/gift-alert.mp3'
];

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
        const baseUrl = window.location.protocol === 'file:' ? 'http://127.0.0.1:8000/' : '';

        let filesToTry = soundPaths;
        try {
            const res = await fetch(baseUrl + 'api/sounds');
            if (res.ok) {
                const data = await res.json();
                if (data.sounds && data.sounds.length > 0) {
                    filesToTry = data.sounds.map(f => 'sounds/' + f);
                }
            }
        } catch (e) {
            console.warn("Could not fetch /api/sounds list, using default sound paths:", e);
        }

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
    } catch (e) {
        console.error("Web Audio initialization error:", e);
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
            source.connect(audioCtx.destination);
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
            if (msg.type === 'event' && msg.event && msg.event.event_type === 'gift') {
                const giftEvent = msg.event;
                const sender = giftEvent.nickname || giftEvent.username;
                const giftName = giftEvent.data.gift_name;
                const count = giftEvent.data.quantity || 1;

                // Play sound INSTANTLY for real-time response (protected by try-catch)
                try {
                    playAlertSound();
                } catch (soundErr) {
                    console.error("Audio playback crashed during WS event:", soundErr);
                }

                alertQueue.push({
                    sender: sender,
                    giftName: giftName,
                    count: count
                });

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
    const alert = alertQueue.shift();

    // Set UI details
    alertUser.textContent = alert.sender;
    alertGiftName.textContent = alert.giftName;
    alertEmoji.textContent = getGiftEmoji(alert.giftName);

    if (alert.count > 1) {
        alertCombo.textContent = `x${alert.count}`;
        alertCombo.style.display = 'inline-block';
    } else {
        alertCombo.style.display = 'none';
    }

    // Play sound removed (moved to instant WS receipt trigger)

    // Display popup
    alertCard.classList.add('show');

    // Keep visible for 2.2 seconds, then fade out
    setTimeout(() => {
        alertCard.classList.remove('show');

        // Wait 0.6 seconds for fadeout transition before processing next gift
        setTimeout(() => {
            isAlertActive = false;
            processQueue();
        }, 600);
    }, 2200);
}
