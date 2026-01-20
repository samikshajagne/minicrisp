// Core State Management
let allMessages = [];
let currentConversationEmail = null;
let currentSelectedAccount = null;
let searchFilter = "";
let statusFilter = "all";
let filterStartDate = null;
let filterEndDate = null;
let filterHasAttachments = false;
let filterSource = "all";
let localSearchTerm = "";
let socket = null;

// Search Navigation State
let currentMatchIndex = 0;
let totalMatches = 0;
let matchElements = [];

// UI References
const visitorListEl = document.getElementById('visitor-list');
const messagesAreaEl = document.getElementById('messages-area');
const chatHeaderEl = document.getElementById('chat-header');
const searchInputEl = document.getElementById('search-input');
const advPanel = document.getElementById('adv-search-panel');
const advToggle = document.getElementById('adv-search-toggle');

// Aggressive autofill clearing
if (searchInputEl) {
    searchInputEl.value = '';
    setTimeout(() => { searchInputEl.value = ''; }, 100);
}

// Initial Load
document.addEventListener('DOMContentLoaded', () => {
    fetchAccounts();
    fetchMessages();

    // Modals
    const addAccountBtn = document.getElementById('add-account-btn');
    if (addAccountBtn) {
        addAccountBtn.onclick = () => {
            document.getElementById('account-modal').style.display = 'flex';
        };
    }

    const resyncBtn = document.getElementById('resync-btn');
    if (resyncBtn) {
        resyncBtn.onclick = async () => {
            resyncBtn.innerHTML = '<span>⏳</span><span>Syncing...</span>';
            resyncBtn.disabled = true;
            try {
                await fetch('/api/admin/resync', { method: 'POST' });
                setTimeout(() => {
                    resyncBtn.innerHTML = '<span>❄️</span><span>Resync</span>';
                    resyncBtn.disabled = false;
                    fetchMessages(searchFilter);
                }, 2000);
            } catch (e) {
                resyncBtn.innerHTML = '<span>❄️</span><span>Resync</span>';
                resyncBtn.disabled = false;
            }
        };
    }

    // Account Modal Tabs
    window.switchModalTab = (tab) => {
        document.getElementById('form-email').style.display = tab === 'email' ? 'flex' : 'none';
        document.getElementById('form-whatsapp').style.display = tab === 'whatsapp' ? 'flex' : 'none';
        document.getElementById('tab-email').style.background = tab === 'email' ? 'white' : 'none';
        document.getElementById('tab-whatsapp').style.background = tab === 'whatsapp' ? 'white' : 'none';
    };

    // Save Email Account
    document.getElementById('save-email-acc').onclick = async () => {
        const payload = {
            email: document.getElementById('acc-email').value.trim(),
            app_password: document.getElementById('acc-pwd').value.trim(),
            imap_host: document.getElementById('acc-host').value.trim()
        };
        const btn = document.getElementById('save-email-acc');
        btn.textContent = 'Verifying...';
        btn.disabled = true;

        try {
            const res = await fetch('/api/admin/email-accounts', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const data = await res.json();
            if (data.status === 'ok') {
                alert('Account added successfully!');
                document.getElementById('account-modal').style.display = 'none';
                fetchAccounts();
            } else {
                alert('Error: ' + data.message);
            }
        } catch (e) { alert('Network error'); }
        finally { btn.textContent = 'Connect Email'; btn.disabled = false; }
    };

    // Save WhatsApp Account
    document.getElementById('save-wa-acc').onclick = async () => {
        const payload = {
            phone_number_id: document.getElementById('wa-phone-id').value.trim(),
            access_token: document.getElementById('wa-token').value.trim(),
            display_phone_number: document.getElementById('wa-display').value.trim()
        };
        const btn = document.getElementById('save-wa-acc');
        btn.textContent = 'Saving...';
        btn.disabled = true;

        try {
            const res = await fetch('/api/admin/whatsapp-accounts', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            if (res.ok) {
                alert('WhatsApp account added!');
                document.getElementById('account-modal').style.display = 'none';
            } else {
                const data = await res.json();
                alert('Error: ' + data.detail);
            }
        } catch (e) { alert('Network error'); }
        finally { btn.textContent = 'Connect WhatsApp'; btn.disabled = false; }
    };

    // Filter Chips
    const filterChips = document.querySelectorAll('[data-filter]');
    filterChips.forEach(chip => {
        chip.addEventListener('click', () => {
            statusFilter = chip.dataset.filter;
            filterChips.forEach(c => c.classList.toggle('active', c === chip));
            renderVisitorList();
        });
    });

    // Local Chat Search
    let localSearchTimeout;
    const chatKeywordSearch = document.getElementById('chat-keyword-search');
    if (chatKeywordSearch) {
        chatKeywordSearch.addEventListener('input', (e) => {
            localSearchTerm = e.target.value.trim();
            clearTimeout(localSearchTimeout);
            localSearchTimeout = setTimeout(() => {
                if (currentConversationEmail) renderChat(currentConversationEmail, searchFilter);
            }, 300);
        });
    }

    // Advanced Search Toggle
    if (advToggle) {
        advToggle.onclick = () => {
            advPanel.classList.toggle('open');
        };
    }

    // Advanced Search Apply
    const advApplyBtn = document.getElementById('adv-apply-btn');
    if (advApplyBtn) {
        advApplyBtn.onclick = () => {
            filterStartDate = document.getElementById('filter-start-date').value;
            filterEndDate = document.getElementById('filter-end-date').value;
            searchFilter = document.getElementById('filter-keywords').value;
            if (searchInputEl) searchInputEl.value = searchFilter;
            advPanel.classList.remove('open');
            fetchMessages(searchFilter);
        };
    }

    const advClearBtn = document.getElementById('adv-clear-btn');
    if (advClearBtn) {
        advClearBtn.onclick = () => {
            document.getElementById('filter-start-date').value = '';
            document.getElementById('filter-end-date').value = '';
            document.getElementById('filter-keywords').value = '';
            filterStartDate = null;
            filterEndDate = null;
            searchFilter = '';
            if (searchInputEl) searchInputEl.value = '';
            fetchMessages('');
        };
    }

    // Local Date Filter
    const applyDateFilterBtn = document.getElementById('apply-date-filter');
    if (applyDateFilterBtn) {
        applyDateFilterBtn.onclick = () => {
            if (currentConversationEmail) renderChat(currentConversationEmail, searchFilter);
        };
    }

    // Export Button
    const exportBtn = document.getElementById('export-btn');
    if (exportBtn) {
        exportBtn.onclick = () => {
            if (currentConversationEmail) {
                window.location.href = `/api/export?email=${encodeURIComponent(currentConversationEmail)}`;
            } else {
                alert('Select a conversation first');
            }
        };
    }
});

// Sidebar Search (Debounced)
let searchTimeout;
if (searchInputEl) {
    searchInputEl.addEventListener('input', (e) => {
        const val = e.target.value.trim();
        searchFilter = val;
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => {
            fetchMessages(val);
            if (currentConversationEmail) {
                localSearchTerm = val;
                const lsk = document.getElementById('chat-keyword-search');
                if (lsk) lsk.value = val;
                renderChat(currentConversationEmail, val);
            }
        }, 300);
    });
}

// Account Logic
async function fetchAccounts() {
    const res = await fetch('/api/admin/email-accounts');
    const data = await res.json();
    const selector = document.getElementById('account-selector');
    if (!selector) return;

    const currentVal = selector.value;
    selector.innerHTML = '';

    if (data.accounts && data.accounts.length > 0) {
        data.accounts.forEach(acc => {
            const opt = document.createElement('option');
            opt.value = acc.email;
            opt.textContent = acc.email;
            opt.style.color = '#333';
            selector.appendChild(opt);
        });
        if (currentVal && data.accounts.some(a => a.email === currentVal)) {
            selector.value = currentVal;
        } else {
            selector.value = data.accounts[0].email;
            if (!currentSelectedAccount) handleAccountChange(data.accounts[0].email);
        }
    } else {
        const opt = document.createElement('option');
        opt.textContent = "No Accounts";
        selector.appendChild(opt);
    }
}

function handleAccountChange(email) {
    if (socket) { socket.close(); socket = null; }
    currentSelectedAccount = email;
    console.log("Switched to account:", email);
    fetchMessages(searchFilter);
}

document.getElementById('account-selector').addEventListener('change', (e) => {
    handleAccountChange(e.target.value);
});

// WebSocket
function connectWS(email) {
    if (socket) socket.close();
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    socket = new WebSocket(`${protocol}//${location.host}/ws?email=${encodeURIComponent(email)}`);
    socket.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        if (msg.email === currentConversationEmail) {
            renderChat(currentConversationEmail, searchFilter);
            sendSeen(msg.email);
        }
        fetchMessages(searchFilter);
    };
}

// Message Fetching
async function fetchMessages(query = null) {
    let url = '/api/admin/messages';
    const params = new URLSearchParams();
    if (query) params.append('search', query);
    if (filterStartDate) params.append('start_date', filterStartDate);
    if (filterEndDate) params.append('end_date', filterEndDate);
    if (filterHasAttachments) params.append('has_attachments', 'true');
    if (filterSource && filterSource !== 'all') params.append('source', filterSource);
    if (currentSelectedAccount) params.append('account', currentSelectedAccount);

    if ([...params].length > 0) url += `?${params.toString()}`;

    try {
        const res = await fetch(url);
        const data = await res.json();
        allMessages = data.messages;
        renderVisitorList();
    } catch (err) {
        console.error("Failed to fetch messages:", err);
    }
}

// Rendering Logic
function renderVisitorList() {
    const visitorListEl = document.getElementById('visitor-list');
    if (!visitorListEl) return;
    visitorListEl.innerHTML = '';

    allMessages.forEach(conv => {
        const id = conv.email;
        if (!id) return;
        if (statusFilter === 'unread' && (conv.unread || 0) === 0) return;
        if (statusFilter === 'read' && (conv.unread || 0) > 0) return;

        const source = conv.source || 'chat';
        const sourceIcon = source === 'whatsapp' ? '🟢' : (source === 'email' || source === 'imap' ? '📧' : '💬');

        const div = document.createElement('div');
        div.className = 'visitor-item';
        div.setAttribute('data-email', id);
        if (id === currentConversationEmail) div.classList.add('active');

        div.innerHTML = `
            <div class="visitor-avatar">${source === 'whatsapp' ? '☏' : id.substring(0, 2).toUpperCase()}</div>
            <div class="visitor-info">
                <div style="display:flex; justify-content:space-between;">
                    <div class="visitor-name">${sourceIcon} ${id}</div>
                    <div style="font-size:12px; color:#9ca3af;">${formatTime(conv.timestamp)}</div>
                </div>
                <div class="visitor-preview">${(conv.last_message || '').substring(0, 60)}...</div>
            </div>
            ${conv.unread > 0 ? `<div class="unread-badge">${conv.unread}</div>` : ''}
        `;

        div.onclick = async () => {
            connectWS(id);
            currentConversationEmail = id;
            await fetch('/api/admin/mark-read', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email: id })
            });
            renderChat(id, searchFilter);
            fetchMessages(searchFilter);
        };
        visitorListEl.appendChild(div);
    });
}

async function renderChat(email, searchTerm = "") {
    currentConversationEmail = email;
    if (searchTerm) {
        localSearchTerm = searchTerm;
        const lsi = document.getElementById('chat-keyword-search');
        if (lsi) lsi.value = searchTerm;
    }

    const items = document.querySelectorAll('.visitor-item');
    items.forEach(el => el.classList.remove('active'));
    const activeEl = document.querySelector(`.visitor-item[data-email='${email}']`);
    if (activeEl) activeEl.classList.add('active');

    chatHeaderEl.style.display = 'flex';
    document.getElementById('email-composer').style.display = 'none';
    document.getElementById('reply-bar').style.display = 'flex';

    const isWassap = !email.includes('@');
    const composeBtn = document.getElementById('compose-btn');
    if (composeBtn) composeBtn.innerHTML = isWassap ? '<span>🟢</span> Send WhatsApp' : '<span>💬</span> Compose Reply';

    initializeQuillEditor();

    const headerNameEl = document.getElementById('header-name');
    const headerAvatarEl = document.getElementById('header-avatar');
    if (headerNameEl) headerNameEl.textContent = email;
    if (headerAvatarEl) headerAvatarEl.textContent = getInitials(email);

    const sd = document.getElementById('chat-start-date').value;
    const ed = document.getElementById('chat-end-date').value;
    let url = `/api/sync?email=${encodeURIComponent(email)}`;
    if (sd) url += `&start_date=${sd}`;
    if (ed) url += `&end_date=${ed}`;

    const res = await fetch(url);
    const data = await res.json();

    messagesAreaEl.innerHTML = '';
    let lastDay = null;
    matchElements = [];
    const finalSearch = localSearchTerm || searchTerm;

    data.messages.forEach(m => {
        const day = getDayLabel(m.timestamp);
        if (day !== lastDay) {
            const sep = document.createElement('div');
            sep.className = 'day-separator';
            sep.style.textAlign = 'center';
            sep.style.fontSize = '12px';
            sep.style.opacity = '0.6';
            sep.style.margin = '12px 0';
            sep.textContent = day;
            messagesAreaEl.appendChild(sep);
            lastDay = day;
        }

        const div = document.createElement('div');
        div.className = `message ${m.sender}`;
        if (m.source === 'whatsapp') div.classList.add('whatsapp');

        let content = '';
        if (m.sender === 'visitor' && m.html_content) {
            div.classList.add('has-iframe');
            content = `<iframe sandbox="allow-same-origin" scrolling="no" style="width:100%; border:none; display: block;" 
                srcdoc="<style>body{margin:0;font-family:sans-serif;font-size:13px;}.highlight{background:#fef08a;}</style>${highlightHtml(m.html_content, finalSearch).replace(/"/g, '&quot;')}"
                onload="this.style.height=(this.contentWindow.document.body.scrollHeight+10)+'px'"></iframe>`;
        } else if (m.sender === 'admin' && m.html_content) {
            content = `<div class="email-content">${highlightHtml(m.html_content, finalSearch)}</div>`;
        } else {
            const urlRegex = /(https?:\/\/[^\s]+)/g;
            content = m.text.split(urlRegex).map(p => {
                if (p.match(/^https?:\/\//)) return `<a href="${p}" target="_blank">${p}</a>`;
                return highlightText(p.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"), finalSearch);
            }).join('');
        }

        div.innerHTML = `
            ${m.subject ? `<div class="message-subject">📧 ${highlightText(m.subject, finalSearch)}</div>` : ''}
            ${content}
            <div class="message-time">${formatTime(m.timestamp)} ${m.sender === 'admin' ? (m.seen_at ? '✓✓' : '✓') : ''}</div>
        `;
        messagesAreaEl.appendChild(div);
    });

    matchElements = Array.from(messagesAreaEl.querySelectorAll('.highlight'));
    totalMatches = matchElements.length;
    updateSearchNav();
    if (totalMatches > 0) scrollToMatch(0);
    else messagesAreaEl.scrollTop = messagesAreaEl.scrollHeight;

    sendSeen(email);
}

function updateSearchNav() {
    const tools = document.querySelector('.chat-tools');
    const old = document.getElementById('search-nav-controls');
    if (old) old.remove();

    if (totalMatches > 0) {
        const nav = document.createElement('div');
        nav.id = 'search-nav-controls';
        nav.className = 'search-nav';
        nav.innerHTML = `<span id="search-match-count">1/${totalMatches} matches</span>
            <button onclick="scrollToMatch(currentMatchIndex-1)">Prev</button>
            <button onclick="scrollToMatch(currentMatchIndex+1)">Next</button>`;
        tools.insertBefore(nav, tools.firstChild);
    }
}

function scrollToMatch(index) {
    if (totalMatches === 0) return;
    if (index < 0) index = totalMatches - 1;
    if (index >= totalMatches) index = 0;
    currentMatchIndex = index;

    matchElements.forEach(el => el.classList.remove('active-match'));
    const active = matchElements[currentMatchIndex];
    active.classList.add('active-match');

    const area = document.getElementById('messages-area');
    const rect = active.getBoundingClientRect();
    const areaRect = area.getBoundingClientRect();
    area.scrollTo({ top: area.scrollTop + (rect.top - areaRect.top) - (area.clientHeight / 2), behavior: 'smooth' });

    const count = document.getElementById('search-match-count');
    if (count) count.textContent = `${currentMatchIndex + 1}/${totalMatches}`;
}

window.scrollToMatch = scrollToMatch;
