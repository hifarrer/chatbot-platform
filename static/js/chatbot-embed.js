// Embeddable ChatBot Widget
(function() {
    'use strict';

    // ChatBot Embed Library
    window.ChatbotEmbed = {
        init: function(config) {
            this.config = {
                embedCode: config.embedCode,
                apiUrl: config.apiUrl,
                containerId: config.containerId,
                theme: config.theme || 'light',
                position: config.position || 'bottom-right',
                title: config.title || 'AI Assistant',
                placeholder: config.placeholder || 'Type your message...',
                width: config.width || '400px',
                height: config.height || '500px',
                avatarUrl: config.avatarUrl || null,
                greetingMessage: config.greetingMessage || "Hi! I'm here to help you. Feel free to ask me anything!",
                ...config
            };

            // Initialize conversation tracking
            this.conversationId = null;

            this.createChatWidget();
            this.attachEventListeners();
        },

        createChatWidget: function() {
            const container = document.getElementById(this.config.containerId);
            if (!container) {
                console.error('ChatBot: Container not found');
                return;
            }

            // Inject CSS
            this.injectCSS();

            // Create chat widget HTML
            const widgetHTML = `
                <div class="chatbot-widget" id="chatbot-${this.config.embedCode}">
                    <div class="chatbot-toggle" id="chatbot-toggle-${this.config.embedCode}">
                        <div class="chatbot-toggle-avatar">
                            ${this.config.avatarUrl ? 
                                `<img src="${this.config.avatarUrl}" alt="Chatbot Avatar">` : 
                                '🤖'
                            }
                        </div>
                        <div class="chatbot-toggle-content">
                            <div class="chatbot-toggle-greeting">
                                ${this.config.greetingMessage || "Need help?"}
                            </div>
                            <div class="chatbot-toggle-button">
                                <span>Ask anything</span>
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                                    <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/>
                                </svg>
                            </div>
                        </div>
                        <div class="chatbot-toggle-close" style="display: none;">
                            <svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor">
                                <path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/>
                            </svg>
                        </div>
                        <div class="chatbot-toggle-minimize" title="Minimize">
                            <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                                <path d="M6 19h12v2H6z"/>
                            </svg>
                        </div>
                    </div>
                    
                    <div class="chatbot-restore" id="chatbot-restore-${this.config.embedCode}" style="display: none;">
                        <div class="chatbot-restore-content">
                            <div class="chatbot-restore-avatar">
                                ${this.config.avatarUrl ? 
                                    `<img src="${this.config.avatarUrl}" alt="Chatbot Avatar">` : 
                                    '🤖'
                                }
                            </div>
                            <div class="chatbot-restore-text">
                                <span>Chat closed</span>
                            </div>
                            <button class="chatbot-restore-btn" title="Restore Chat">
                                <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                                    <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/>
                                </svg>
                            </button>
                        </div>
                    </div>
                    
                    <div class="chatbot-window" id="chatbot-window-${this.config.embedCode}" style="display: none;">
                        <div class="chatbot-header">
                            <div class="chatbot-title">
                                <div class="chatbot-avatar">
                                    ${this.config.avatarUrl ? 
                                        `<img src="${this.config.avatarUrl}" alt="Chatbot Avatar">` : 
                                        '🤖'
                                    }
                                </div>
                                <span>${this.config.title}</span>
                            </div>
                            <div class="chatbot-header-controls">
                                <div class="chatbot-status">
                                    <div class="status-indicator online"></div>
                                    <span>Online</span>
                                </div>
                                <div class="chatbot-control-buttons">
                                    <button class="chatbot-minimize-btn" title="Minimize">
                                        <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                                            <path d="M6 19h12v2H6z"/>
                                        </svg>
                                    </button>
                                    <button class="chatbot-close-btn" title="Close">
                                        <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                                            <path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/>
                                        </svg>
                                    </button>
                                </div>
                            </div>
                        </div>
                        
                        <div class="chatbot-messages" id="chatbot-messages-${this.config.embedCode}">
                            <div class="message bot-message">
                                <div class="message-avatar">
                                    ${this.config.avatarUrl ? 
                                        `<img src="${this.config.avatarUrl}" alt="Chatbot Avatar">` : 
                                        '🤖'
                                    }
                                </div>
                                <div class="message-content">
                                    <div class="message-bubble">
                                        ${this.config.greetingMessage}
                                    </div>
                                </div>
                            </div>
                        </div>
                        
                        <div class="chatbot-input">
                            <div class="input-group">
                                <input type="text" 
                                       id="chatbot-input-${this.config.embedCode}" 
                                       placeholder="${this.config.placeholder}"
                                       maxlength="1000">
                                <button id="chatbot-send-${this.config.embedCode}" type="button">
                                    <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                                        <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/>
                                    </svg>
                                </button>
                            </div>
                        </div>
                        
                        <div class="chatbot-footer">
                            <small>Powered by owlbee.ai</small>
                        </div>
                    </div>
                </div>
            `;

            container.innerHTML = widgetHTML;
        },

        injectCSS: function() {
            if (document.getElementById('chatbot-embed-styles')) return;

            const css = `
                .chatbot-widget {
                    position: fixed;
                    bottom: 20px;
                    right: 20px;
                    z-index: 999999;
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                }

                .chatbot-widget.minimized .chatbot-window {
                    display: none !important;
                }

                .chatbot-toggle.minimized-avatar {
                    width: 60px !important;
                    height: 60px !important;
                    min-width: 60px !important;
                    max-width: 60px !important;
                    padding: 0 !important;
                    border-radius: 50% !important;
                    display: flex !important;
                    align-items: center !important;
                    justify-content: center !important;
                    background: #007bff !important;
                    box-shadow: 0 4px 12px rgba(0, 123, 255, 0.3) !important;
                    transition: all 0.3s ease !important;
                }

                .chatbot-toggle.minimized-avatar:hover {
                    transform: translateY(-2px) scale(1.05) !important;
                    box-shadow: 0 6px 20px rgba(0, 123, 255, 0.4) !important;
                }

                .chatbot-toggle.minimized-avatar .chatbot-toggle-avatar {
                    width: 50px !important;
                    height: 50px !important;
                    background: rgba(255, 255, 255, 0.2) !important;
                    border-radius: 50% !important;
                    display: flex !important;
                    align-items: center !important;
                    justify-content: center !important;
                    font-size: 24px !important;
                }

                .chatbot-toggle.minimized-avatar .chatbot-toggle-avatar img {
                    width: 100% !important;
                    height: 100% !important;
                    border-radius: 50% !important;
                }

                .chatbot-widget.closed {
                    display: none !important;
                }

                .chatbot-widget.closed .chatbot-toggle {
                    display: none !important;
                }

                .chatbot-restore {
                    background: #28a745;
                    border-radius: 12px;
                    display: flex;
                    align-items: center;
                    cursor: pointer;
                    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
                    transition: all 0.3s ease;
                    color: white;
                    padding: 12px 16px;
                    min-width: 200px;
                    max-width: 250px;
                    animation: slideInRestore 0.3s ease-out;
                    z-index: 1000000;
                }

                .chatbot-restore:hover {
                    transform: translateY(-2px);
                    box-shadow: 0 6px 20px rgba(0, 0, 0, 0.2);
                }

                .chatbot-restore-content {
                    display: flex;
                    align-items: center;
                    gap: 12px;
                    width: 100%;
                }

                .chatbot-restore-avatar {
                    width: 32px;
                    height: 32px;
                    border-radius: 50%;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    overflow: hidden;
                    flex-shrink: 0;
                    background: rgba(255, 255, 255, 0.2);
                }

                .chatbot-restore-avatar img {
                    width: 100%;
                    height: 100%;
                    object-fit: cover;
                    border-radius: 50%;
                }

                .chatbot-restore-text {
                    flex: 1;
                    font-weight: 500;
                    font-size: 14px;
                }

                .chatbot-restore-btn {
                    background: rgba(255, 255, 255, 0.2);
                    color: white;
                    border: none;
                    border-radius: 6px;
                    padding: 6px;
                    cursor: pointer;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    transition: all 0.2s ease;
                    flex-shrink: 0;
                }

                .chatbot-restore-btn:hover {
                    background: rgba(255, 255, 255, 0.3);
                    transform: scale(1.05);
                }

                @keyframes slideInRestore {
                    from {
                        opacity: 0;
                        transform: translateX(20px);
                    }
                    to {
                        opacity: 1;
                        transform: translateX(0);
                    }
                }

                .chatbot-toggle {
                    background: white;
                    border-radius: 12px;
                    display: flex;
                    align-items: center;
                    cursor: pointer;
                    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
                    transition: all 0.3s ease;
                    color: #333;
                    padding: 16px;
                    min-width: 280px;
                    max-width: 320px;
                    position: relative;
                    gap: 12px;
                }

                .chatbot-toggle:hover {
                    transform: translateY(-2px);
                    box-shadow: 0 6px 20px rgba(0, 0, 0, 0.2);
                }

                .chatbot-toggle-content {
                    display: flex;
                    align-items: center;
                    gap: 12px;
                    flex: 1;
                }

                .chatbot-toggle-avatar {
                    width: 40px;
                    height: 40px;
                    border-radius: 50%;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    overflow: hidden;
                    flex-shrink: 0;
                    background: #f0f0f0;
                }

                .chatbot-toggle-avatar img {
                    width: 100%;
                    height: 100%;
                    object-fit: cover;
                    border-radius: 50%;
                }

                .chatbot-toggle-greeting {
                    flex: 1;
                    font-weight: 500;
                    color: #333;
                    font-size: 14px;
                }

                .chatbot-toggle-button {
                    background: #333;
                    color: white;
                    border-radius: 8px;
                    padding: 8px 12px;
                    display: flex;
                    align-items: center;
                    gap: 6px;
                    font-size: 12px;
                    font-weight: 500;
                    flex-shrink: 0;
                }

                .chatbot-toggle-button svg {
                    width: 14px;
                    height: 14px;
                }

                .chatbot-toggle-minimize {
                    position: absolute;
                    top: 8px;
                    right: 8px;
                    width: 24px;
                    height: 24px;
                    background: rgba(0, 0, 0, 0.1);
                    border-radius: 50%;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    cursor: pointer;
                    transition: all 0.2s ease;
                    opacity: 0.7;
                    color: #666;
                }

                .chatbot-toggle-minimize:hover {
                    background: rgba(0, 123, 255, 0.2);
                    color: #007bff;
                    opacity: 1;
                }

                .chatbot-toggle-minimize svg {
                    width: 14px;
                    height: 14px;
                }

                .chatbot-window {
                    width: ${this.config.width};
                    height: ${this.config.height};
                    background: white;
                    border-radius: 12px;
                    box-shadow: 0 8px 30px rgba(0, 0, 0, 0.12);
                    position: absolute;
                    bottom: 80px;
                    right: 0;
                    display: flex;
                    flex-direction: column;
                    overflow: hidden;
                    animation: slideUp 0.3s ease-out;
                    z-index: 1000000;
                }

                @keyframes slideUp {
                    from {
                        opacity: 0;
                        transform: translateY(20px);
                    }
                    to {
                        opacity: 1;
                        transform: translateY(0);
                    }
                }

                .chatbot-header {
                    background: #007bff;
                    color: white;
                    padding: 16px 20px;
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                }

                .chatbot-header-controls {
                    display: flex;
                    align-items: center;
                    gap: 12px;
                }

                .chatbot-control-buttons {
                    display: flex;
                    align-items: center;
                    gap: 8px;
                }

                .chatbot-minimize-btn,
                .chatbot-close-btn {
                    background: none;
                    border: none;
                    color: white;
                    cursor: pointer;
                    padding: 4px;
                    border-radius: 4px;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    transition: all 0.2s ease;
                    opacity: 0.8;
                }

                .chatbot-minimize-btn:hover,
                .chatbot-close-btn:hover {
                    background: rgba(255, 255, 255, 0.2);
                    opacity: 1;
                }

                .chatbot-close-btn:hover {
                    background: rgba(220, 53, 69, 0.8);
                }

                .chatbot-title {
                    display: flex;
                    align-items: center;
                    font-weight: 600;
                }

                .chatbot-avatar {
                    margin-right: 8px;
                    font-size: 20px;
                    width: 20px;
                    height: 20px;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    overflow: hidden;
                }
                
                .chatbot-avatar img {
                    width: 100%;
                    height: 100%;
                    object-fit: cover;
                    border-radius: 50%;
                }

                .chatbot-status {
                    display: flex;
                    align-items: center;
                    font-size: 12px;
                    opacity: 0.9;
                }

                .status-indicator {
                    width: 8px;
                    height: 8px;
                    border-radius: 50%;
                    margin-right: 4px;
                }

                .status-indicator.online {
                    background: #28a745;
                }

                .chatbot-messages {
                    flex: 1;
                    padding: 20px;
                    overflow-y: auto;
                    background: #f8f9fa;
                }

                .message {
                    margin-bottom: 16px;
                    display: flex;
                    align-items: flex-start;
                }

                .message.user-message {
                    flex-direction: row-reverse;
                }

                .message-avatar {
                    width: 32px;
                    height: 32px;
                    border-radius: 50%;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    font-size: 16px;
                    margin: 0 8px;
                    flex-shrink: 0;
                    overflow: hidden;
                }
                
                .message-avatar img {
                    width: 100%;
                    height: 100%;
                    object-fit: cover;
                    border-radius: 50%;
                }

                .user-message .message-avatar {
                    background: #007bff;
                    color: white;
                }

                .bot-message .message-avatar {
                    background: #e9ecef;
                }

                .message-content {
                    flex: 1;
                    display: flex;
                    flex-direction: column;
                }

                .message-bubble {
                    background: white;
                    padding: 12px 16px;
                    border-radius: 18px;
                    max-width: 80%;
                    word-wrap: break-word;
                    line-height: 1.4;
                    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.1);
                }

                .chatbot-link {
                    color: #007bff;
                    text-decoration: none;
                    border-bottom: 1px solid transparent;
                    transition: all 0.2s ease;
                    word-break: break-all;
                }

                .chatbot-link:hover {
                    color: #0056b3;
                    border-bottom-color: #0056b3;
                    text-decoration: none;
                }

                .chatbot-email-link {
                    color: #28a745;
                }

                .chatbot-email-link:hover {
                    color: #1e7e34;
                    border-bottom-color: #1e7e34;
                }

                .user-message .message-bubble {
                    background: #007bff;
                    color: white;
                    margin-left: auto;
                }

                .user-message .chatbot-link {
                    color: #ffffff;
                    border-bottom-color: rgba(255, 255, 255, 0.5);
                }

                .user-message .chatbot-link:hover {
                    color: #ffffff;
                    border-bottom-color: #ffffff;
                }

                .message-time {
                    font-size: 11px;
                    color: #6c757d;
                    margin-top: 4px;
                    padding: 0 16px;
                }

                .user-message .message-time {
                    text-align: right;
                }

                .chatbot-input {
                    padding: 16px 20px;
                    background: white;
                    border-top: 1px solid #e9ecef;
                }

                .input-group {
                    display: flex;
                    align-items: center;
                    background: #f8f9fa;
                    border-radius: 24px;
                    padding: 4px;
                }

                .input-group input {
                    flex: 1;
                    border: none;
                    outline: none;
                    padding: 12px 16px;
                    background: transparent;
                    font-size: 14px;
                }

                .input-group button {
                    width: 40px;
                    height: 40px;
                    border: none;
                    background: #007bff;
                    color: white;
                    border-radius: 50%;
                    cursor: pointer;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    transition: all 0.2s ease;
                }

                .input-group button:hover {
                    background: #0056b3;
                    transform: scale(1.05);
                }

                .input-group button:disabled {
                    background: #6c757d;
                    cursor: not-allowed;
                    transform: none;
                }

                .chatbot-footer {
                    padding: 8px 20px;
                    background: #f8f9fa;
                    border-top: 1px solid #e9ecef;
                    text-align: center;
                    color: #6c757d;
                }

                .typing-indicator {
                    display: flex;
                    align-items: center;
                    padding: 12px 16px;
                    background: white;
                    border-radius: 18px;
                    max-width: 80%;
                }

                .typing-dots {
                    display: flex;
                    align-items: center;
                }

                .typing-dots span {
                    width: 8px;
                    height: 8px;
                    border-radius: 50%;
                    background: #6c757d;
                    margin: 0 2px;
                    animation: typing 1.4s infinite;
                }

                .typing-dots span:nth-child(2) {
                    animation-delay: 0.2s;
                }

                .typing-dots span:nth-child(3) {
                    animation-delay: 0.4s;
                }

                @keyframes typing {
                    0%, 60%, 100% {
                        transform: scale(1);
                        opacity: 0.5;
                    }
                    30% {
                        transform: scale(1.2);
                        opacity: 1;
                    }
                }

                /* Mobile responsive */
                @media (max-width: 480px) {
                    .chatbot-toggle {
                        min-width: 260px;
                        max-width: calc(100vw - 40px);
                        padding: 12px;
                    }
                    
                    .chatbot-toggle-avatar {
                        width: 32px;
                        height: 32px;
                    }
                    
                    .chatbot-toggle-greeting {
                        font-size: 13px;
                    }
                    
                    .chatbot-toggle-button {
                        padding: 6px 10px;
                        font-size: 11px;
                    }
                    
                    .chatbot-window {
                        width: calc(100vw - 40px);
                        height: calc(100vh - 100px);
                        bottom: 80px;
                        right: 20px;
                    }

                    .chatbot-restore {
                        min-width: 200px;
                        max-width: calc(100vw - 40px);
                        padding: 10px 12px;
                    }

                    .chatbot-restore-avatar {
                        width: 28px;
                        height: 28px;
                    }

                    .chatbot-restore-text {
                        font-size: 13px;
                    }

                    .chatbot-control-buttons {
                        gap: 6px;
                    }

                    .chatbot-minimize-btn,
                    .chatbot-close-btn {
                        padding: 3px;
                    }

                    .chatbot-toggle-minimize,
                    .chatbot-toggle-close-btn {
                        width: 20px;
                        height: 20px;
                        top: 6px;
                        right: 6px;
                    }

                    .chatbot-toggle-minimize svg,
                    .chatbot-toggle-close-btn svg {
                        width: 12px;
                        height: 12px;
                    }
                }
            `;

            const style = document.createElement('style');
            style.id = 'chatbot-embed-styles';
            style.textContent = css;
            document.head.appendChild(style);
        },

        attachEventListeners: function() {
            const toggle = document.getElementById(`chatbot-toggle-${this.config.embedCode}`);
            const window = document.getElementById(`chatbot-window-${this.config.embedCode}`);
            const input = document.getElementById(`chatbot-input-${this.config.embedCode}`);
            const sendBtn = document.getElementById(`chatbot-send-${this.config.embedCode}`);
            const minimizeBtn = document.querySelector(`#chatbot-window-${this.config.embedCode} .chatbot-minimize-btn`);
            const closeBtn = document.querySelector(`#chatbot-window-${this.config.embedCode} .chatbot-close-btn`);
            const toggleMinimizeBtn = document.querySelector(`#chatbot-toggle-${this.config.embedCode} .chatbot-toggle-minimize`);
            const restoreBtn = document.getElementById(`chatbot-restore-${this.config.embedCode}`);
            const widget = document.getElementById(`chatbot-${this.config.embedCode}`);

            // Toggle chat window
            toggle.addEventListener('click', (e) => {
                // Don't toggle if clicking on control buttons
                if (e.target.closest('.chatbot-toggle-minimize')) {
                    return;
                }
                
                // If minimized (showing only avatar), restore from minimized state
                if (toggle.classList.contains('minimized-avatar')) {
                    this.restoreFromMinimized();
                    return;
                }
                
                const isVisible = window.style.display !== 'none';
                window.style.display = isVisible ? 'none' : 'flex';
                
                const content = toggle.querySelector('.chatbot-toggle-content');
                const closeIcon = toggle.querySelector('.chatbot-toggle-close');
                
                if (isVisible) {
                    content.style.display = 'flex';
                    closeIcon.style.display = 'none';
                    widget.classList.remove('minimized');
                } else {
                    content.style.display = 'none';
                    closeIcon.style.display = 'block';
                    input.focus();
                }
            });

            // Minimize button
            if (minimizeBtn) {
                minimizeBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    this.minimizeChat();
                });
            }

            // Close button (in chat window)
            if (closeBtn) {
                closeBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    this.closeChat();
                });
            }

            // Toggle minimize button
            if (toggleMinimizeBtn) {
                toggleMinimizeBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    this.minimizeChat();
                });
            }

            // Restore button
            if (restoreBtn) {
                restoreBtn.addEventListener('click', () => {
                    this.restoreChat();
                });
            }

            // Send message on Enter
            input.addEventListener('keypress', (e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    this.sendMessage();
                }
            });

            // Send message on button click
            sendBtn.addEventListener('click', () => {
                this.sendMessage();
            });
        },

        sendMessage: function() {  
            const input = document.getElementById(`chatbot-input-${this.config.embedCode}`);
            const message = input.value.trim();

            if (!message) return;

            // Add user message
            this.addMessage(message, 'user');
            input.value = '';

            // Show typing indicator
            this.showTyping();

            // Prepare request data with conversation ID
            const requestData = { 
                message: message 
            };
            
            // Add conversation ID if it exists
            if (this.conversationId) {
                requestData.conversation_id = this.conversationId;
            }

            // Send to API
            fetch(this.config.apiUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(requestData)
            })
            .then(response => response.json())
            .then(data => {
                this.hideTyping();
                // Handle undefined, null, or empty responses
                const botResponse = data.response || data.error || 'Sorry, I encountered an issue. Please try again.';
                this.addMessage(botResponse, 'bot');
                
                // Store conversation ID for future messages
                if (data.conversation_id) {
                    this.conversationId = data.conversation_id;
                    console.log('Conversation ID stored:', this.conversationId);
                }
            })
            .catch(error => {
                this.hideTyping();
                this.addMessage('Sorry, I encountered an error. Please try again.', 'bot');
                console.error('Chat error:', error);
            });
        },

        addMessage: function(text, sender) {
            const messagesContainer = document.getElementById(`chatbot-messages-${this.config.embedCode}`);
            const messageDiv = document.createElement('div');
            messageDiv.className = `message ${sender}-message`;

            const avatar = sender === 'user' ? '👤' : 
                          (this.config.avatarUrl ? 
                            `<img src="${this.config.avatarUrl}" alt="Chatbot Avatar">` : 
                            '🤖');
            const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

            // Convert URLs and emails to clickable links
            const processedText = this.convertLinksToHtml(text);

            messageDiv.innerHTML = `
                <div class="message-avatar">${avatar}</div>
                <div class="message-content">
                    <div class="message-bubble">${processedText}</div>
                    <div class="message-time">${time}</div>
                </div>
            `;

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
            const messagesContainer = document.getElementById(`chatbot-messages-${this.config.embedCode}`);
            const typingDiv = document.createElement('div');
            typingDiv.className = 'message bot-message typing-message';
            
            const avatar = this.config.avatarUrl ? 
                          `<img src="${this.config.avatarUrl}" alt="Chatbot Avatar">` : 
                          '🤖';
            
            typingDiv.innerHTML = `
                <div class="message-avatar">${avatar}</div>
                <div class="message-content">
                    <div class="typing-indicator">
                        <div class="typing-dots">
                            <span></span>
                            <span></span>
                            <span></span>
                        </div>
                    </div>
                </div>
            `;

            messagesContainer.appendChild(typingDiv);
            messagesContainer.scrollTop = messagesContainer.scrollHeight;
        },

        hideTyping: function() {
            const typingMessage = document.querySelector(`#chatbot-messages-${this.config.embedCode} .typing-message`);
            if (typingMessage) {
                typingMessage.remove();
            }
        },

        minimizeChat: function() {
            const widget = document.getElementById(`chatbot-${this.config.embedCode}`);
            const window = document.getElementById(`chatbot-window-${this.config.embedCode}`);
            const toggle = document.getElementById(`chatbot-toggle-${this.config.embedCode}`);
            
            widget.classList.add('minimized');
            window.style.display = 'none';
            
            // Hide toggle content and control buttons, keep avatar visible
            const content = toggle.querySelector('.chatbot-toggle-content');
            const closeIcon = toggle.querySelector('.chatbot-toggle-close');
            const minimizeBtn = toggle.querySelector('.chatbot-toggle-minimize');
            
            content.style.display = 'none';
            closeIcon.style.display = 'none';
            if (minimizeBtn) minimizeBtn.style.display = 'none';
            
            // Add circular avatar class for styling
            toggle.classList.add('minimized-avatar');
        },

        closeChat: function() {
            const widget = document.getElementById(`chatbot-${this.config.embedCode}`);
            const window = document.getElementById(`chatbot-window-${this.config.embedCode}`);
            const toggle = document.getElementById(`chatbot-toggle-${this.config.embedCode}`);
            const restore = document.getElementById(`chatbot-restore-${this.config.embedCode}`);
            
            // Hide the chat window
            window.style.display = 'none';
            
            // Hide the toggle button
            toggle.style.display = 'none';
            
            // Add closed class to widget
            widget.classList.add('closed');
            
            // Show restore button after a short delay
            setTimeout(() => {
                restore.style.display = 'block';
            }, 500);
        },

        restoreChat: function() {
            const widget = document.getElementById(`chatbot-${this.config.embedCode}`);
            const restore = document.getElementById(`chatbot-restore-${this.config.embedCode}`);
            const toggle = document.getElementById(`chatbot-toggle-${this.config.embedCode}`);
            const window = document.getElementById(`chatbot-window-${this.config.embedCode}`);
            const restoreText = restore.querySelector('.chatbot-restore-text span');
            
            // Update text to show it's being restored
            if (restoreText) {
                restoreText.textContent = 'Chat reopened';
            }
            
            // Remove closed class and show toggle
            widget.classList.remove('closed');
            restore.style.display = 'none';
            toggle.style.display = 'flex';
            
            // Make sure the chat window is hidden initially
            window.style.display = 'none';
            
            // Reset text back to "Chat closed" after a delay
            setTimeout(() => {
                if (restoreText) {
                    restoreText.textContent = 'Chat closed';
                }
            }, 2000);
        },

        restoreFromMinimized: function() {
            const widget = document.getElementById(`chatbot-${this.config.embedCode}`);
            const toggle = document.getElementById(`chatbot-toggle-${this.config.embedCode}`);
            const window = document.getElementById(`chatbot-window-${this.config.embedCode}`);
            
            // Remove minimized state
            widget.classList.remove('minimized');
            toggle.classList.remove('minimized-avatar');
            
            // Show toggle content and control buttons
            const content = toggle.querySelector('.chatbot-toggle-content');
            const minimizeBtn = toggle.querySelector('.chatbot-toggle-minimize');
            
            content.style.display = 'flex';
            if (minimizeBtn) minimizeBtn.style.display = 'flex';
            
            // Open the chat window
            window.style.display = 'flex';
            
            // Focus on input
            const input = document.getElementById(`chatbot-input-${this.config.embedCode}`);
            if (input) {
                input.focus();
            }
        }
    };
})(); 