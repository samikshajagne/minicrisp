document.addEventListener('DOMContentLoaded', () => {
    const launcher = document.getElementById('chat-launcher');
    const container = document.getElementById('chat-container');
    const sendBtn = document.getElementById('send-btn');
    const magicBtn = document.getElementById('magic-btn');
    const messageInput = document.getElementById('message-input');
    const emailInput = document.getElementById('email-input');
    const messagesArea = document.getElementById('chat-messages');

    // -----------------------------
    // Guest ID (helper only)
    // -----------------------------
    let guestId = localStorage.getItem("mini-crisp-guest-id");
    if (!guestId) {
        guestId = "guest_" + Math.random().toString(36).substr(2, 9);
        localStorage.setItem("mini-crisp-guest-id", guestId);
    }

    // -----------------------------
    // State
    // -----------------------------
    let socket = null;
    let lastCount = 0;

    // -----------------------------
    // UI actions
    // -----------------------------
    launcher.addEventListener('click', () => {
        container.classList.toggle('active');
    });

    function addMessage(text, type) {
        const m = document.createElement("div");
        m.className = `message ${type}`;
        m.textContent = text;
        messagesArea.appendChild(m);
        messagesArea.scrollTop = messagesArea.scrollHeight;
    }

    // -----------------------------
    // Send message (email required)
    // -----------------------------
    async function sendMessage() {
        const text = messageInput.value.trim();
        const email = emailInput.value.trim();

        if (!email) {
            emailInput.focus();
            alert("Please enter your email to start the chat.");
            return;
        }

        if (!text) return;

        addMessage(text, "visitor");
        messageInput.value = "";

        await fetch("/api/message", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                text,
                email,
                guest_id: guestId
            })
        });
    }

    sendBtn.addEventListener("click", sendMessage);
    messageInput.addEventListener("keypress", e => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    // -----------------------------
    // WebSocket (EMAIL ONLY)
    // -----------------------------
    function connectSocket() {
        const email = emailInput.value.trim();
        if (!email) return;

        const protocol = window.location.protocol === "https:" ? "wss" : "ws";
        const url = `${protocol}://${window.location.host}/ws?email=${encodeURIComponent(email)}`;

        try {
            socket = new WebSocket(url);

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
        } catch (err) {
            console.error("WS connect error", err);
            socket = null;
        }
    }

    // -----------------------------
    // Polling fallback (EMAIL ONLY)
    // -----------------------------
    async function pollMessages() {
        const email = emailInput.value.trim();
        if (!email) return;

        try {
            const res = await fetch(`/api/sync?email=${encodeURIComponent(email)}`);
            const data = await res.json();
            const msgs = data.messages || [];

            if (msgs.length !== lastCount) {
                messagesArea.innerHTML = "";
                msgs.forEach(m =>
                    addMessage(m.text, m.sender === "admin" ? "admin" : "visitor")
                );
                lastCount = msgs.length;
            }
        } catch (err) {
            console.error("poll error", err);
        }
    }

    // -----------------------------
    // 🔁 VERY IMPORTANT UX FIX
    // Reset chat when email changes
    // -----------------------------
    emailInput.addEventListener("change", () => {
        messagesArea.innerHTML = "";
        lastCount = 0;

        if (socket) {
            socket.close();
            socket = null;
        }

        connectSocket();
    });

    // -----------------------------
    // Background sync loop
    // -----------------------------
    setInterval(() => {
        if (!socket || socket.readyState === WebSocket.CLOSED) {
            connectSocket();
        }
        pollMessages();
    }, 1000);

    connectSocket();
});
