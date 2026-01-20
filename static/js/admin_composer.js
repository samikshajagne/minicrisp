let quillEditor = null;
let selectedFiles = [];

function initializeQuillEditor() {
    if (quillEditor) return;
    quillEditor = new Quill('#email-editor', {
        theme: 'snow',
        placeholder: 'Type your message here...',
        modules: {
            toolbar: [
                [{ 'header': [1, 2, 3, false] }],
                ['bold', 'italic', 'underline', 'strike'],
                [{ 'list': 'ordered' }, { 'list': 'bullet' }],
                ['link', 'image'],
                ['clean']
            ]
        }
    });
    quillEditor.on('text-change', () => {
        document.getElementById('char-count').textContent = `${quillEditor.getText().trim().length} characters`;
    });
}

// CC/BCC Toggle
const toggleBtn = document.getElementById('toggle-cc-bcc');
if (toggleBtn) {
    toggleBtn.addEventListener('click', () => {
        const fields = document.getElementById('cc-bcc-fields');
        fields.classList.toggle('visible');
        toggleBtn.textContent = fields.classList.contains('visible') ? '- Hide CC/BCC' : '+ CC/BCC';
    });
}

// Attachments
const attachBtn = document.getElementById('attach-btn');
if (attachBtn) {
    attachBtn.addEventListener('click', () => document.getElementById('email-attachments').click());
}

const fileInput = document.getElementById('email-attachments');
if (fileInput) {
    fileInput.addEventListener('change', (e) => {
        selectedFiles = [...selectedFiles, ...Array.from(e.target.files)];
        renderFilePreviews();
        e.target.value = '';
    });
}

function renderFilePreviews() {
    const container = document.getElementById('file-previews');
    container.innerHTML = '';
    selectedFiles.forEach((file, index) => {
        const chip = document.createElement('div');
        chip.className = 'file-chip';
        chip.innerHTML = `<span>${file.name}</span><span class="remove-file" onclick="removeFile(${index})">×</span>`;
        container.appendChild(chip);
    });
}

window.removeFile = (index) => {
    selectedFiles.splice(index, 1);
    renderFilePreviews();
};

// Send Reply
const sendBtn = document.getElementById('send-email-btn');
if (sendBtn) {
    sendBtn.addEventListener('click', async () => {
        if (!currentConversationEmail) return alert('No conversation selected');
        const plainText = quillEditor.getText().trim();
        if (!plainText) return alert('Message is empty');

        const formData = new FormData();
        formData.append('visitor_email', currentConversationEmail);
        formData.append('text', plainText);
        formData.append('html_content', `<div style="font-family:sans-serif;">${quillEditor.root.innerHTML}</div>`);
        formData.append('subject', document.getElementById('email-subject').value.trim() || `Re: Conversation`);

        const cc = document.getElementById('email-cc').value.trim();
        const bcc = document.getElementById('email-bcc').value.trim();
        if (cc) formData.append('cc', JSON.stringify(cc.split(',').map(e => e.trim())));
        if (bcc) formData.append('bcc', JSON.stringify(bcc.split(',').map(e => e.trim())));
        if (currentSelectedAccount) formData.append('account_email', currentSelectedAccount);
        selectedFiles.forEach(f => formData.append('files', f));

        sendBtn.disabled = true;
        sendBtn.textContent = '📤 Sending...';

        try {
            const res = await fetch('/api/reply', { method: 'POST', body: formData });
            if (res.ok) {
                quillEditor.setText('');
                selectedFiles = [];
                renderFilePreviews();
                document.getElementById('email-composer').style.display = 'none';
                document.getElementById('reply-bar').style.display = 'flex';
                fetchMessages(searchFilter);
            } else alert('Failed to send');
        } catch (e) { alert('Error sending'); }
        finally { sendBtn.disabled = false; sendBtn.textContent = '📧 Send Email'; }
    });
}

// Global Composer
function openGlobalComposer() {
    document.getElementById('global-composer-modal').style.display = 'flex';
    document.getElementById('global-from-preview').textContent = currentSelectedAccount || "Default";
}
window.openGlobalComposer = openGlobalComposer;

function closeGlobalComposer() {
    document.getElementById('global-composer-modal').style.display = 'none';
}
window.closeGlobalComposer = closeGlobalComposer;
