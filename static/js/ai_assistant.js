// AI Assistant State
let isTtsEnabled = true;
let isContinuousListening = false;
let mediaRecorder;
let transcriptionSocket;
let audioContext;
let analyser;
let silenceStartTime = null;
const SILENCE_THRESHOLD = 0.015;
const SILENCE_TIMEOUT = 1800;

const aiInput = document.getElementById('ai-input');
const aiMessages = document.getElementById('ai-messages');
const voiceBtn = document.getElementById('voice-btn');
const wakeWordBtn = document.getElementById('wake-word-btn');
const statusEl = document.getElementById('ai-status');

document.getElementById('ai-assistant-btn').onclick = () => {
    const box = document.getElementById('ai-assistant-box');
    box.classList.toggle('open');
    if (box.classList.contains('open') && aiMessages.children.length === 0) {
        appendAiMessage('bot', '👋 Hello! I am your AI Assistant. How can I help you today? You can ask me to draft emails, search customers, or summarize chats.');
    }
};

// Wake Word / Continuous Listening Toggle
if (wakeWordBtn) {
    wakeWordBtn.onclick = () => {
        isContinuousListening = !isContinuousListening;
        wakeWordBtn.style.opacity = isContinuousListening ? '1' : '0.4';
        wakeWordBtn.style.transform = isContinuousListening ? 'scale(1.2)' : 'scale(1)';
        if (isContinuousListening) {
            appendAiMessage('bot', '🧠 Continuous listening enabled. I will listen for your commands automatically.');
            startRecording();
        } else {
            appendAiMessage('bot', '🧠 Continuous listening disabled.');
            stopRecording();
        }
    };
}

async function sendAiCommand() {
    const prompt = aiInput.value.trim();
    if (!prompt) return;

    if (prompt.toLowerCase() === 'send') {
        const main = document.getElementById('email-composer');
        const glob = document.getElementById('global-composer-modal');
        if (main.style.display !== 'none') document.getElementById('send-email-btn').click();
        else if (glob.style.display === 'flex') document.getElementById('global-send-btn').click();
        aiInput.value = '';
        return;
    }

    appendAiMessage('user', prompt);
    aiInput.value = '';
    const botId = 'bot-' + Date.now();
    appendAiMessage('bot', '...', botId);

    try {
        const res = await fetch('/api/ai-agent', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ command: prompt })
        });
        const data = await res.json();
        const placeholder = document.getElementById(botId);
        if (placeholder) placeholder.remove();

        if (data.status === 'ok') {
            appendAiMessage('bot', data.output);
            handleAiActions(data.actions || [], data.output);
        }
    } catch (e) {
        const placeholder = document.getElementById(botId);
        if (placeholder) placeholder.remove();
    }
}

document.getElementById('ai-send-btn').onclick = sendAiCommand;
aiInput.onkeypress = (e) => { if (e.key === 'Enter') sendAiCommand(); };

function appendAiMessage(sender, text, id = null, options = null) {
    const div = document.createElement('div');
    div.className = `ai-message ${sender}`;
    div.textContent = text;
    if (id) div.id = id;

    if (options && options.length > 0) {
        const optDiv = document.createElement('div');
        optDiv.style.cssText = 'display:flex; flex-wrap:wrap; gap:6px; margin-top:8px;';
        options.forEach(opt => {
            const btn = document.createElement('button');
            btn.className = 'pill-btn';
            btn.textContent = opt.label || opt;
            btn.onclick = () => {
                if (opt.email) {
                    if (opt.purpose === 'email') ActionBridge.composeNew(opt.email);
                    else if (opt.purpose === 'summary') { aiInput.value = `Summarize conversation with ${opt.email}`; sendAiCommand(); }
                    else ActionBridge.openChat(opt.email);
                }
            };
            optDiv.appendChild(btn);
        });
        div.appendChild(optDiv);
    }

    aiMessages.appendChild(div);
    aiMessages.scrollTop = aiMessages.scrollHeight;
}

const ActionBridge = {
    async openChat(email) {
        const el = document.querySelector(`.visitor-item[data-email='${email}']`);
        if (el) el.click(); else renderChat(email, "");
    },
    async draftReply(body) {
        if (document.getElementById('email-composer').style.display === 'none') {
            document.getElementById('compose-btn')?.click();
        }
        setTimeout(() => { if (quillEditor) quillEditor.root.innerHTML = body; }, 300);
    },
    async navigate(target) {
        const t = target.toLowerCase();
        if (t === 'whatsapp') window.location.href = '/whatsapp';
        else if (t === 'logout') window.location.href = '/logout';
        else if (t === 'inbox') window.location.href = '/admin';
    },
    async composeNew(to, subject, body) {
        openGlobalComposer();
        setTimeout(() => {
            document.getElementById('global-to-input').value = to || "";
            document.getElementById('global-subject-input').value = subject || "";
            document.getElementById('global-message-text').value = body || "";
        }, 300);
    },
    async applyFilters(q, s, e) {
        if (q) {
            document.getElementById('search-input').value = q;
            searchFilter = q;
        }
        if (s) { document.getElementById('filter-start-date').value = s; filterStartDate = s; }
        if (e) { document.getElementById('filter-end-date').value = e; filterEndDate = e; }
        fetchMessages(searchFilter);
    }
};

async function handleAiActions(actions, responseText) {
    let spoken = "";
    if (actions.some(a => a.action === 'draft_reply' || a.action === 'compose_new')) spoken = "I have drafted the email.";
    else if (actions.some(a => a.action === 'open_chat')) spoken = "Opening chat.";
    else if (responseText) {
        spoken = responseText.split(/[.!?\n]/, 1)[0];
        if (spoken.length > 60) spoken = spoken.substring(0, 50) + "...";
    }

    if (isTtsEnabled && spoken && 'speechSynthesis' in window) {
        window.speechSynthesis.cancel();
        const utt = new SpeechSynthesisUtterance(spoken);
        utt.onend = () => resumeContinuousListening();
        utt.onerror = () => resumeContinuousListening();
        window.speechSynthesis.speak(utt);
    } else {
        resumeContinuousListening();
    }

    for (const act of actions) {
        try {
            if (act.action === 'open_chat' && act.email) await ActionBridge.openChat(act.email);
            else if (act.action === 'draft_reply') await ActionBridge.draftReply(act.body);
            else if (act.action === 'navigate') await ActionBridge.navigate(act.target);
            else if (act.action === 'compose_new') await ActionBridge.composeNew(act.to, act.subject, act.body);
            else if (act.action === 'apply_filters') await ActionBridge.applyFilters(act.query, act.start, act.end);
        } catch (e) { console.error(e); }
    }
}

// Deepgram Voice Logic
async function initAudioContext() {
    if (!audioContext) audioContext = new (window.AudioContext || window.webkitAudioContext)();
    if (audioContext.state === 'suspended') await audioContext.resume();
}

async function startRecording() {
    try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        await initAudioContext();
        const source = audioContext.createMediaStreamSource(stream.clone());
        analyser = audioContext.createAnalyser();
        analyser.fftSize = 256;
        source.connect(analyser);

        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        transcriptionSocket = new WebSocket(`${protocol}//${window.location.host}/api/ai/transcribe-live`);
        transcriptionSocket.binaryType = "arraybuffer";

        transcriptionSocket.onopen = () => {
            const mime = MediaRecorder.isTypeSupported('audio/webm;codecs=opus') ? 'audio/webm;codecs=opus' : 'audio/webm';
            mediaRecorder = new MediaRecorder(stream, { mimeType: mime });
            mediaRecorder.ondataavailable = async (e) => {
                if (e.data.size > 0 && transcriptionSocket.readyState === WebSocket.OPEN) {
                    transcriptionSocket.send(await e.data.arrayBuffer());
                }
            };
            mediaRecorder.start(250);
            voiceBtn.classList.add('recording');
            if (statusEl) {
                statusEl.style.display = 'block';
                statusEl.innerHTML = "● Listening...";
                statusEl.style.color = "#ef4444";
            }
            monitorSilence();
        };

        transcriptionSocket.onmessage = (e) => {
            const data = JSON.parse(e.data);
            if (data.type === 'transcript') {
                aiInput.value = data.text;
                if (isContinuousListening && data.is_final) {
                    setTimeout(() => {
                        if (voiceBtn.classList.contains('recording')) {
                            stopRecording();
                            sendAiCommand();
                        }
                    }, 1500);
                }
            }
        };

        transcriptionSocket.onclose = () => {
            voiceBtn.classList.remove('recording');
            if (statusEl) statusEl.style.display = 'none';
        };
    } catch (err) { console.error(err); }
}

function stopRecording() {
    if (mediaRecorder && mediaRecorder.state !== 'inactive') {
        mediaRecorder.stop();
        mediaRecorder.stream.getTracks().forEach(t => t.stop());
    }
    if (transcriptionSocket && transcriptionSocket.readyState === WebSocket.OPEN) {
        transcriptionSocket.send(JSON.stringify({ type: 'stop' }));
    }
}

function monitorSilence() {
    if (!voiceBtn.classList.contains('recording')) return;
    const data = new Uint8Array(analyser.frequencyBinCount);
    analyser.getByteTimeDomainData(data);
    let sum = 0;
    for (const amp of data) { const n = (amp - 128) / 128; sum += n * n; }
    const rms = Math.sqrt(sum / data.length);
    voiceBtn.style.transform = `scale(${Math.min(1 + rms * 3, 1.4)})`;
    requestAnimationFrame(monitorSilence);
}

function resumeContinuousListening() {
    if (isContinuousListening) setTimeout(() => startRecording(), 500);
}

voiceBtn.onclick = () => {
    if (voiceBtn.classList.contains('recording')) stopRecording();
    else startRecording();
};

window.openGlobalAiAssist = async () => {
    const prompt = window.prompt("What should I write?");
    if (!prompt) return;
    const box = document.getElementById('global-message-text');
    const old = box.value;
    box.value = "✨ Generating...";
    try {
        const res = await fetch('/api/ai-agent', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ command: "Draft an email: " + prompt })
        });
        const data = await res.json();
        box.value = data.status === 'ok' ? data.output : old;
    } catch (e) { box.value = old; }
};
