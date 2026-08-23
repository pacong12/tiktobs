// State management
let socket = null;
const alertQueue = [];
const MAX_QUEUE = 25;
let isAlertActive = false;

// DOM Elements
const alertCard = document.getElementById('alert-card');
const senderNameSpan = document.getElementById('sender-name');
const giftNameSpan = document.getElementById('gift-name');
const boostCountDiv = document.getElementById('boost-count');
const boostTargetDiv = document.getElementById('boost-target');
const giftEmojiSpan = document.getElementById('gift-emoji');
const viaCommentNoteDiv = document.getElementById('via-comment-note');

// Static markup of the "credited to ..." line, restored for normal vote
// alerts after an ignored-gift alert replaced it.
const BOOST_TARGET_VOTE_HTML = boostTargetDiv.innerHTML;

function escapeHTML(str) {
    return String(str == null ? '' : str).replace(/[&<>"']/g,
        ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
}

let audioCtx = null;
let customSoundBuffer = null;
let alertVolume = 1.0;

const fallbackSoundPaths = [
    'sounds/dragon-studio-thud-sound-effect-405470.mp3',
    'sounds/vote-gift-alert.wav',
    'sounds/vote-gift-alert.mp3'
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

// Fetch the chosen vote-boost sound file + volume from the server, then decode it.
async function loadConfiguredSound() {
    let filesToTry = fallbackSoundPaths;
    try {
        const res = await fetch(baseUrl + 'api/sounds');
        if (res.ok) {
            const data = await res.json();
            const cfg = data.config || {};
            if (typeof cfg.vote_volume === 'number') alertVolume = cfg.vote_volume;
            if (cfg.vote_sound) {
                filesToTry = ['sounds/' + cfg.vote_sound];
            } else if (cfg.vote_sound === '') {
                // When empty, fallback to sound catalog or synthesized chime
                if (data.sounds && data.sounds.length > 0) {
                    filesToTry = data.sounds.map(f => 'sounds/' + f);
                } else {
                    filesToTry = fallbackSoundPaths;
                }
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
            console.log("Played custom vote-gift sound via Web Audio API!");
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
// Normalized key for the GIFT_ICONS map (same rules as the backend).
function giftIconKey(name) {
    return ((name || '').toLowerCase().replace(/[^\w\s]/g, ' ').replace(/\s+/g, ' ').trim());
}

// Official TikTok gift icon <img>, or '' when the gift has no known icon
// (callers fall back to the emoji mapping). On load error the img replaces
// itself with the emoji fallback so the alert is never empty.
function giftIconHtml(giftName, cls) {
    const icons = window.GIFT_ICONS || {};
    const url = icons[giftIconKey(giftName)];
    if (!url) return '';
    const fallback = getGiftEmoji(giftName);
    return `<img class="${cls}" src="${url}" alt="" loading="lazy" data-fallback="${fallback}" onerror="this.outerHTML=this.dataset.fallback">`;
}

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
        console.log('Vote gift alert WebSocket connected.');
    };

    socket.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            if (msg.type === 'sound_config_update') {
                loadConfiguredSound();
                return;
            }
            if (msg.type === 'poll_gift_vote') {
                // Play sound INSTANTLY for real-time response (protected by try-catch)
                try {
                    playAlertSound();
                } catch (soundErr) {
                    console.error("Audio playback crashed during WS event:", soundErr);
                }

                if (alertQueue.length >= MAX_QUEUE) alertQueue.shift();
                alertQueue.push({
                    sender: msg.nickname || msg.username,
                    giftName: msg.gift_name,
                    candidateName: msg.candidate_name,
                    votesAdded: msg.votes_added,
                    viaComment: msg.via_comment || null
                });
                
                processQueue();
            } else if (msg.type === 'poll_gift_ignored') {
                // Gift sent during an active poll that no candidate owns:
                // nothing was counted, but the sender must get visible
                // feedback instead of believing the gift became a vote.
                // No celebration sound — this is a warning, not a boost.
                alertQueue.push({
                    ignored: true,
                    sender: msg.nickname || msg.username,
                    giftName: msg.gift_name
                });

                processQueue();
            }
        } catch (error) {
            console.error('Error handling WS vote-gift alert message:', error);
        }
    };

    socket.onclose = () => {
        console.log('Vote gift alert WebSocket closed. Reconnecting in 3 seconds...');
        setTimeout(connectWebSocket, 3000);
    };

    socket.onerror = (err) => {
        console.error('Vote gift alert WebSocket error:', err);
    };
}

function processQueue() {
    if (isAlertActive || alertQueue.length === 0) return;
    
    isAlertActive = true;
    const alert = alertQueue.shift();
    
    // Set UI details
    senderNameSpan.textContent = alert.sender;
    giftNameSpan.textContent = alert.giftName;
    giftEmojiSpan.innerHTML = giftIconHtml(alert.giftName, 'gift-icon-img')
        || `<span class="gift-emoji-fallback">${getGiftEmoji(alert.giftName)}</span>`;

    if (alert.ignored) {
        // Gift that no candidate owns and no vote comment backs up: warn
        // and tell the sender how to make the next gift count.
        alertCard.classList.add('ignored');
        boostCountDiv.textContent = '+0 VOTES';
        boostTargetDiv.innerHTML = '<span class="ignored-note">not counted &mdash; comment the candidate number first, then send your gift</span>';
        viaCommentNoteDiv.classList.add('hidden');
    } else {
        alertCard.classList.remove('ignored');
        boostCountDiv.textContent = `+${alert.votesAdded} VOTES`;
        boostTargetDiv.innerHTML = BOOST_TARGET_VOTE_HTML;
        boostTargetDiv.querySelector('#candidate-name').textContent = `${alert.candidateName} 👑`;
        // Comment-fallback votes are marked so viewers see WHY this gift
        // landed on that candidate.
        if (alert.viaComment) {
            viaCommentNoteDiv.textContent = `via last comment: “${alert.viaComment}”`;
            viaCommentNoteDiv.classList.remove('hidden');
        } else {
            viaCommentNoteDiv.classList.add('hidden');
        }
    }
    
    // Play sound removed (moved to instant WS receipt trigger)
    
    // Display popup
    alertCard.classList.add('show');
    
    // Keep visible for 2.8 seconds, then fade out
    setTimeout(() => {
        alertCard.classList.remove('show');
        
        // Wait 0.6 seconds for fadeout transition before processing next gift
        setTimeout(() => {
            isAlertActive = false;
            processQueue();
        }, 600);
    }, 2800);
}
