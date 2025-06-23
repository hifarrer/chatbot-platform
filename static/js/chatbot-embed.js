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
                ...config
            };

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
                        <div class="chatbot-toggle-icon">
                            <svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor">
                                <path d="M20 2H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h4l4 4 4-4h4c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm-2 12H6v-2h12v2zm0-3H6V9h12v2zm0-3H6V6h12v2z"/>
                            </svg>
                        </div>
                        <div class="chatbot-toggle-close" style="display: none;">
                            <svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor">
                                <path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/>
                            </svg>
                        </div>
                    </div>
                    
                    <div class="chatbot-window" id="chatbot-window-${this.config.embedCode}" style="display: none;">
                        <div class="chatbot-header">
                            <div class="chatbot-title">
                                <div class="chatbot-avatar">🤖</div>
                                <span>${this.config.title}</span>
                            </div>
                            <div class="chatbot-status">
                                <div class="status-indicator online"></div>
                                <span>Online</span>
                            </div>
                        </div>
                        
                        <div class="chatbot-messages" id="chatbot-messages-${this.config.embedCode}">
                            <div class="message bot-message">
                                <div class="message-avatar">🤖</div>
                                <div class="message-content">
                                    <div class="message-bubble">
                                        Hi! I'm here to help you. Feel free to ask me anything!
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
                            <small>Powered by ChatBot Platform</small>
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
                    z-index: 9999;
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                }

                .chatbot-toggle {
                    width: 60px;
                    height: 60px;
                    background: #007bff;
                    border-radius: 50%;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    cursor: pointer;
                    box-shadow: 0 4px 12px rgba(0, 123, 255, 0.4);
                    transition: all 0.3s ease;
                    color: white;
                }

                .chatbot-toggle:hover {
                    transform: scale(1.05);
                    box-shadow: 0 6px 20px rgba(0, 123, 255, 0.6);
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

                .chatbot-title {
                    display: flex;
                    align-items: center;
                    font-weight: 600;
                }

                .chatbot-avatar {
                    margin-right: 8px;
                    font-size: 20px;
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

                .user-message .message-bubble {
                    background: #007bff;
                    color: white;
                    margin-left: auto;
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
                    .chatbot-window {
                        width: calc(100vw - 40px);
                        height: calc(100vh - 100px);
                        bottom: 80px;
                        right: 20px;
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

            // Toggle chat window
            toggle.addEventListener('click', () => {
                const isVisible = window.style.display !== 'none';
                window.style.display = isVisible ? 'none' : 'flex';
                
                const icon = toggle.querySelector('.chatbot-toggle-icon');
                const closeIcon = toggle.querySelector('.chatbot-toggle-close');
                
                if (isVisible) {
                    icon.style.display = 'block';
                    closeIcon.style.display = 'none';
                } else {
                    icon.style.display = 'none';
                    closeIcon.style.display = 'block';
                    input.focus();
                }
            });

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

            // Send to API
            fetch(this.config.apiUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ message: message })
            })
            .then(response => response.json())
            .then(data => {
                this.hideTyping();
                // Handle undefined, null, or empty responses
                const botResponse = data.response || data.error || 'Sorry, I encountered an issue. Please try again.';
                this.addMessage(botResponse, 'bot');
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

            const avatar = sender === 'user' ? '👤' : '🤖';
            const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

            messageDiv.innerHTML = `
                <div class="message-avatar">${avatar}</div>
                <div class="message-content">
                    <div class="message-bubble">${text}</div>
                    <div class="message-time">${time}</div>
                </div>
            `;

            messagesContainer.appendChild(messageDiv);
            messagesContainer.scrollTop = messagesContainer.scrollHeight;
        },

        showTyping: function() {
            const messagesContainer = document.getElementById(`chatbot-messages-${this.config.embedCode}`);
            const typingDiv = document.createElement('div');
            typingDiv.className = 'message bot-message typing-message';
            typingDiv.innerHTML = `
                <div class="message-avatar">🤖</div>
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
        }
    };
})(); 