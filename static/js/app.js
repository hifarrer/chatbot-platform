// Main JavaScript for owlbee.ai

document.addEventListener('DOMContentLoaded', function() {
    // Initialize tooltips
    const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    const tooltipList = tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });

    // Auto-hide flash messages
    const alerts = document.querySelectorAll('.alert');
    alerts.forEach(function(alert) {
        if (alert.classList.contains('alert-info') || alert.classList.contains('alert-success')) {
            setTimeout(function() {
                const bsAlert = new bootstrap.Alert(alert);
                bsAlert.close();
            }, 5000);
        }
    });

    // File upload drag and drop
    setupFileUpload();
    
    // Form validation
    setupFormValidation();
});

// File upload with drag and drop
function setupFileUpload() {
    const fileInputs = document.querySelectorAll('input[type="file"]');
    
    fileInputs.forEach(function(input) {
        const form = input.closest('form');
        if (!form) return;
        
        // Create drag overlay
        const overlay = document.createElement('div');
        overlay.className = 'upload-overlay';
        overlay.style.cssText = `
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0, 123, 255, 0.1);
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 2rem;
            color: #007bff;
            z-index: 9999;
            display: none;
        `;
        overlay.innerHTML = '<div><i class="fas fa-cloud-upload-alt"></i><br>Drop files here</div>';
        document.body.appendChild(overlay);
        
        // Drag events
        ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
            document.addEventListener(eventName, preventDefaults, false);
        });
        
        function preventDefaults(e) {
            e.preventDefault();
            e.stopPropagation();
        }
        
        ['dragenter', 'dragover'].forEach(eventName => {
            document.addEventListener(eventName, () => overlay.style.display = 'flex', false);
        });
        
        ['dragleave', 'drop'].forEach(eventName => {
            document.addEventListener(eventName, () => overlay.style.display = 'none', false);
        });
        
        document.addEventListener('drop', handleDrop, false);
        
        function handleDrop(e) {
            const dt = e.dataTransfer;
            const files = dt.files;
            
            if (files.length > 0) {
                input.files = files;
                // Trigger change event
                const event = new Event('change', { bubbles: true });
                input.dispatchEvent(event);
            }
        }
    });
}

// Form validation
function setupFormValidation() {
    const forms = document.querySelectorAll('form[novalidate]');
    
    forms.forEach(function(form) {
        form.addEventListener('submit', function(event) {
            if (!form.checkValidity()) {
                event.preventDefault();
                event.stopPropagation();
                
                // Focus first invalid field
                const firstInvalid = form.querySelector(':invalid');
                if (firstInvalid) {
                    firstInvalid.focus();
                }
            }
            
            form.classList.add('was-validated');
        });
    });
}

// Utility functions
const Utils = {
    // Show loading state
    showLoading: function(element, text = 'Loading...') {
        const spinner = `<i class="fas fa-spinner fa-spin me-2"></i>${text}`;
        if (element.tagName === 'BUTTON') {
            element.dataset.originalHtml = element.innerHTML;
            element.innerHTML = spinner;
            element.disabled = true;
        } else {
            element.classList.add('loading');
        }
    },
    
    // Hide loading state
    hideLoading: function(element) {
        if (element.tagName === 'BUTTON') {
            element.innerHTML = element.dataset.originalHtml || element.innerHTML;
            element.disabled = false;
        } else {
            element.classList.remove('loading');
        }
    },
    
    // Show toast notification
    showToast: function(message, type = 'info') {
        const toastContainer = document.querySelector('.toast-container') || createToastContainer();
        
        const toastHtml = `
            <div class="toast align-items-center text-bg-${type} border-0" role="alert" aria-live="assertive" aria-atomic="true">
                <div class="d-flex">
                    <div class="toast-body">${message}</div>
                    <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
                </div>
            </div>
        `;
        
        toastContainer.insertAdjacentHTML('beforeend', toastHtml);
        const toast = toastContainer.lastElementChild;
        const bsToast = new bootstrap.Toast(toast);
        bsToast.show();
        
        // Remove from DOM after hiding
        toast.addEventListener('hidden.bs.toast', () => toast.remove());
    },
    
    // Copy text to clipboard
    copyToClipboard: function(text) {
        if (navigator.clipboard && window.isSecureContext) {
            return navigator.clipboard.writeText(text);
        } else {
            // Fallback for older browsers
            const textArea = document.createElement('textarea');
            textArea.value = text;
            textArea.style.position = 'fixed';
            textArea.style.left = '-999999px';
            textArea.style.top = '-999999px';
            document.body.appendChild(textArea);
            textArea.focus();
            textArea.select();
            
            return new Promise((resolve, reject) => {
                try {
                    document.execCommand('copy') ? resolve() : reject();
                    textArea.remove();
                } catch (error) {
                    reject(error);
                    textArea.remove();
                }
            });
        }
    },
    
    // Format file size
    formatFileSize: function(bytes) {
        if (bytes === 0) return '0 Bytes';
        
        const k = 1024;
        const sizes = ['Bytes', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    },
    
    // Format date
    formatDate: function(dateString) {
        const date = new Date(dateString);
        return date.toLocaleDateString() + ' ' + date.toLocaleTimeString();
    }
};

// Create toast container if it doesn't exist
function createToastContainer() {
    const container = document.createElement('div');
    container.className = 'toast-container position-fixed bottom-0 end-0 p-3';
    container.style.zIndex = '9999';
    document.body.appendChild(container);
    return container;
}

// Chat functionality
const Chat = {
    init: function(containerId, apiUrl) {
        this.container = document.getElementById(containerId);
        this.apiUrl = apiUrl;
        this.setupEventListeners();
    },
    
    setupEventListeners: function() {
        const input = this.container.querySelector('.chat-input input');
        const button = this.container.querySelector('.chat-input button');
        
        if (input && button) {
            input.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') {
                    this.sendMessage();
                }
            });
            
            button.addEventListener('click', () => {
                this.sendMessage();
            });
        }
    },
    
    sendMessage: function() {
        const input = this.container.querySelector('.chat-input input');
        const message = input.value.trim();
        
        if (!message) return;
        
        this.addMessage(message, 'user');
        input.value = '';
        
        this.showTyping();
        
        fetch(this.apiUrl, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ message: message })
        })
        .then(response => response.json())
        .then(data => {
            this.hideTyping();
            this.addMessage(data.response, 'bot');
        })
        .catch(error => {
            this.hideTyping();
            this.addMessage('Sorry, I encountered an error. Please try again.', 'bot', true);
            console.error('Chat error:', error);
        });
    },
    
    addMessage: function(message, sender, isError = false) {
        const messagesContainer = this.container.querySelector('.chat-messages');
        const messageDiv = document.createElement('div');
        messageDiv.className = `chat-message ${sender}`;
        
        const bubbleClass = isError ? 'message-bubble bot error' : `message-bubble ${sender}`;
        const icon = sender === 'bot' ? '<i class="fas fa-robot me-2"></i>' : '';
        
        // Convert URLs and emails to clickable links
        const processedMessage = this.convertLinksToHtml(message);
        
        messageDiv.innerHTML = `<div class="${bubbleClass}">${icon}${processedMessage}</div>`;
        messagesContainer.appendChild(messageDiv);
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    },

    convertLinksToHtml: function(text) {
        if (!text) return text;
        
        // URL regex pattern (matches http, https, www, and domain patterns)
        const urlRegex = /(https?:\/\/[^\s]+|www\.[^\s]+|[a-zA-Z0-9-]+\.[a-zA-Z]{2,}(?:\/[^\s]*)?)/gi;
        
        // Email regex pattern
        const emailRegex = /([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})/gi;
        
        let processedText = text;
        
        // Convert URLs to clickable links
        processedText = processedText.replace(urlRegex, (match) => {
            let url = match;
            // Add https:// if the URL doesn't have a protocol
            if (!url.match(/^https?:\/\//i)) {
                url = 'https://' + url;
            }
            return `<a href="${url}" target="_blank" rel="noopener noreferrer" class="chatbot-link">${match}</a>`;
        });
        
        // Convert emails to clickable mailto links
        processedText = processedText.replace(emailRegex, (match) => {
            return `<a href="mailto:${match}" class="chatbot-link chatbot-email-link">${match}</a>`;
        });
        
        return processedText;
    },
    
    showTyping: function() {
        const messagesContainer = this.container.querySelector('.chat-messages');
        const typingDiv = document.createElement('div');
        typingDiv.className = 'chat-message bot typing-indicator';
        typingDiv.innerHTML = '<div class="message-bubble bot"><i class="fas fa-spinner fa-spin me-2"></i>Typing...</div>';
        messagesContainer.appendChild(typingDiv);
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    },
    
    hideTyping: function() {
        const typingIndicator = this.container.querySelector('.typing-indicator');
        if (typingIndicator) {
            typingIndicator.remove();
        }
    }
};

// File upload progress
function showUploadProgress(input) {
    const form = input.closest('form');
    const submitBtn = form.querySelector('button[type="submit"]');
    
    if (input.files && input.files[0]) {
        const file = input.files[0];
        const fileName = file.name;
        const fileSize = Utils.formatFileSize(file.size);
        
        // Show file info
        let fileInfo = form.querySelector('.file-info');
        if (!fileInfo) {
            fileInfo = document.createElement('div');
            fileInfo.className = 'file-info mt-2 p-2 bg-light rounded';
            input.parentNode.appendChild(fileInfo);
        }
        
        fileInfo.innerHTML = `
            <div class="d-flex align-items-center">
                <i class="fas fa-file me-2"></i>
                <div class="flex-grow-1">
                    <div class="fw-medium">${fileName}</div>
                    <small class="text-muted">${fileSize}</small>
                </div>
                <i class="fas fa-check-circle text-success"></i>
            </div>
        `;
        
        // Enable submit button
        if (submitBtn) {
            submitBtn.disabled = false;
        }
    }
}

// Export for global use
window.ChatBot = {
    Utils,
    Chat,
    showUploadProgress
}; 