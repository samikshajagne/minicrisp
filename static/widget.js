document.addEventListener('DOMContentLoaded', () => {
    const launcher = document.getElementById('chat-launcher');
    const container = document.getElementById('chat-container');
    const sendBtn = document.getElementById('send-btn');
    const magicBtn = document.getElementById('magic-btn');
    const messageInput = document.getElementById('message-input');
    const emailInput = document.getElementById('email-input');
    const messagesArea = document.getElementById('chat-messages');

    // Guest ID
    let guestId = localStorage.getItem("mini-crisp-guest-id");
    if (!guestId) {
        guestId = "guest_" + Math.random().toString(36).substr(2, 9);
        localStorage.setItem("mini-crisp-guest-id", guestId);
    }

    launcher.addEventListener('click', () => {
        container.classList.toggle('active');
    });

    // Add message to UI
    function addMessage(text, type) {
        const m = document.createElement("div");
        m.className = `message ${type}`;
        m.textContent = text;
        messagesArea.appendChild(m);
        messagesArea.scrollTop = messagesArea.scrollHeight;
    }

    // Send message
    async function sendMessage() {
        const text = messageInput.value.trim();
        const email = emailInput.value.trim();
        if (!text) return;

        addMessage(text, "visitor");
        messageInput.value = "";

        await fetch("/api/message", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ text, email, guest_id: guestId })
        });
    }

    sendBtn.addEventListener("click", sendMessage);
    messageInput.addEventListener("keypress", e => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    // ---------------------------
    // WebSockets
    // ---------------------------
    let socket = null;

    function connectSocket() {
        const email = emailInput.value.trim();
        const id = email || guestId;

        const protocol = window.location.protocol === "https:" ? "wss" : "ws";
        const url = `${protocol}://${window.location.host}/ws?${email ? `email=${encodeURIComponent(email)}` : `guest_id=${guestId}`}`;

        socket = new WebSocket(url);
        socket._id = id;

        socket.onmessage = event => {
            try {
                const data = JSON.parse(event.data);
                addMessage(data.text, data.sender === "admin" ? "admin" : "visitor");
            } catch (e) {
                console.error("WS parse error", e);
            }
        };

        socket.onclose = () => {
            socket = null;
        };
    }

    // ---------------------------
    // Polling Fallback
    // ---------------------------
    let lastCount = 0;

    async function pollMessages() {
        const email = emailInput.value.trim();
        const url = email
            ? `/api/sync?email=${encodeURIComponent(email)}`
            : `/api/sync?guest_id=${guestId}`;

        const res = await fetch(url);
        const data = await res.json();
        const msgs = data.messages || [];

        if (msgs.length !== lastCount) {
            messagesArea.innerHTML = "";
            msgs.forEach(m => addMessage(m.text, m.sender === "admin" ? "admin" : "visitor"));
            lastCount = msgs.length;
        }
    }

    setInterval(() => {
        if (!socket || socket.readyState === WebSocket.CLOSED) {
            connectSocket();
        }
        pollMessages();
    }, 3000);

    connectSocket();
});
