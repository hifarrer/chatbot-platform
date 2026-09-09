// Embeddable ChatBot Widget
(function() {
    'use strict';

    /* ===== owlbee-safe-html v1 BEGIN - mirrored in static/js/chatbot-embed.js;
       qa_phase6_reply_html.py fails if these two blocks differ ===== */
    var SafeHtml = (function () {
        'use strict';

        // Mirrors ALLOWED_TAGS in services/reply_sanitizer.py.
        var ALLOWED_TAGS = ['A', 'B', 'STRONG', 'I', 'EM', 'U', 'BR', 'P',
                            'UL', 'OL', 'LI', 'CODE', 'SPAN'];

        // Removed with their contents: unwrapping a <script> would print the
        // payload as visible text instead of running it, which is not a win.
        var DROP_WITH_CONTENT = ['SCRIPT', 'STYLE', 'IFRAME', 'OBJECT', 'EMBED',
                                 'APPLET', 'NOSCRIPT', 'TEMPLATE', 'SVG', 'MATH',
                                 'FORM', 'INPUT', 'TEXTAREA', 'SELECT', 'BUTTON',
                                 'LINK', 'META', 'BASE'];

        var GLOBAL_ATTRS = ['class', 'title'];
        var TAG_ATTRS = { A: ['href'] };
        var ALLOWED_SCHEMES = ['http:', 'https:', 'mailto:', 'tel:'];

        // A tab or newline inside "java<tab>script:" still makes a live URL,
        // so these die before the scheme is inspected.
        var CONTROL_CHARS = /[\x00-\x20\x7f]/g;
        var SCHEME_RE = /^([a-zA-Z][a-zA-Z0-9+.\-]*):/;

        function escapeHtml(text) {
            return String(text === null || text === undefined ? '' : text)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#39;');
        }

        function safeHref(value) {
            if (!value) { return null; }
            var url = String(value).replace(CONTROL_CHARS, '');
            if (!url) { return null; }
            if (url.charAt(0) === '#') { return url; }
            // Protocol-relative: no honest use in a support answer.
            if (url.indexOf('//') === 0) { return null; }
            var scheme = SCHEME_RE.exec(url);
            if (scheme) {
                return ALLOWED_SCHEMES.indexOf(scheme[1].toLowerCase() + ':') === -1
                    ? null : url;
            }
            return 'https://' + url;
        }

        function contains(list, value) {
            return list.indexOf(value) !== -1;
        }

        function attachedTo(root, node) {
            var current = node;
            while (current) {
                if (current === root) { return true; }
                current = current.parentNode;
            }
            return false;
        }

        function unwrap(el) {
            var parent = el.parentNode;
            if (!parent) { return; }
            while (el.firstChild) {
                parent.insertBefore(el.firstChild, el);
            }
            parent.removeChild(el);
        }

        function hasAncestorTag(root, el, tagName) {
            var current = el.parentNode;
            while (current && current !== root) {
                if (current.nodeName === tagName) { return true; }
                current = current.parentNode;
            }
            return false;
        }

        /**
         * Parse untrusted HTML into an inert DocumentFragment, allowlisted.
         * <template> content is inert: no scripts run and no resources load while
         * we inspect it.
         */
        function sanitizeFragment(html, extraTags) {
            var tpl = document.createElement('template');
            tpl.innerHTML = html === null || html === undefined ? '' : String(html);
            var root = tpl.content;
            var allowed = extraTags ? ALLOWED_TAGS.concat(extraTags) : ALLOWED_TAGS;

            var elements = Array.prototype.slice.call(root.querySelectorAll('*'));
            for (var i = 0; i < elements.length; i++) {
                var el = elements[i];
                if (!attachedTo(root, el)) { continue; }

                var name = el.nodeName;
                if (contains(DROP_WITH_CONTENT, name)) {
                    if (el.parentNode) { el.parentNode.removeChild(el); }
                    continue;
                }
                if (!contains(allowed, name)) {
                    unwrap(el);
                    continue;
                }

                var keep = GLOBAL_ATTRS.concat(TAG_ATTRS[name] || []);
                var attrs = Array.prototype.slice.call(el.attributes);
                for (var a = 0; a < attrs.length; a++) {
                    if (!contains(keep, attrs[a].name.toLowerCase())) {
                        el.removeAttribute(attrs[a].name);
                    }
                }

                if (name === 'A') {
                    // A nested anchor is the exact shape this code exists to stop.
                    if (hasAncestorTag(root, el, 'A')) { unwrap(el); continue; }
                    var href = safeHref(el.getAttribute('href'));
                    if (!href) { unwrap(el); continue; }
                    el.setAttribute('href', href);
                    el.setAttribute('target', '_blank');
                    el.setAttribute('rel', 'noopener noreferrer');
                }
            }
            return root;
        }

        /**
         * Run fn over every text node under root, skipping those inside any tag
         * named in opts.skipInside. Callers that rewrite text must go through
         * this, never over the serialized HTML - rewriting the string is what put
         * a <strong> inside an href and broke the link in the first place.
         */
        function walkTextNodes(root, opts, fn) {
            var skip = (opts && opts.skipInside ? opts.skipInside : []).map(function (t) {
                return t.toUpperCase();
            });
            var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null, false);
            var nodes = [];
            var node;
            while ((node = walker.nextNode())) { nodes.push(node); }

            for (var i = 0; i < nodes.length; i++) {
                var current = nodes[i];
                var blocked = false;
                var parent = current.parentNode;
                while (parent && parent !== root) {
                    if (skip.indexOf(parent.nodeName) !== -1) { blocked = true; break; }
                    parent = parent.parentNode;
                }
                if (!blocked) { fn(current); }
            }
        }

        /** Replace an element's children with sanitized HTML. */
        function setSafeHtml(el, html, extraTags) {
            while (el.firstChild) { el.removeChild(el.firstChild); }
            el.appendChild(sanitizeFragment(html, extraTags));
            return el;
        }

        return {
            escapeHtml: escapeHtml,
            safeHref: safeHref,
            sanitizeFragment: sanitizeFragment,
            walkTextNodes: walkTextNodes,
            setSafeHtml: setSafeHtml
        };
    })();
    /* ===== owlbee-safe-html v1 END ===== */

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
                                `<img src="${SafeHtml.escapeHtml(this.config.avatarUrl)}" alt="Chatbot Avatar">` : 
                                '🤖'
                            }
                        </div>
                        <div class="chatbot-toggle-content">
                            <div class="chatbot-toggle-greeting">
                                ${SafeHtml.escapeHtml(this.config.greetingMessage || "Need help?")}
                            </div>
                            <div class="chatbot-toggle-button">
                                <span>Ask anything</span>
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                                    <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/>
                                </svg>
                            </div>
                        </div>
                        <div class="chatbot-toggle-minimize" title="Minimize">
                            <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                                <path d="M6 19h12v2H6z"/>
                            </svg>
                        </div>
                    </div>
                    
                    
                    <div class="chatbot-window" id="chatbot-window-${this.config.embedCode}" style="display: none;">
                        <div class="chatbot-header">
                            <div class="chatbot-title">
                                <div class="chatbot-avatar">
                                    ${this.config.avatarUrl ? 
                                        `<img src="${SafeHtml.escapeHtml(this.config.avatarUrl)}" alt="Chatbot Avatar">` : 
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
                                </div>
                            </div>
                        </div>
                        
                        <div class="chatbot-messages" id="chatbot-messages-${this.config.embedCode}">
                            <div class="message bot-message">
                                <div class="message-avatar">
                                    ${this.config.avatarUrl ? 
                                        `<img src="${SafeHtml.escapeHtml(this.config.avatarUrl)}" alt="Chatbot Avatar">` : 
                                        '🤖'
                                    }
                                </div>
                                <div class="message-content">
                                    <div class="message-bubble">
                                        ${SafeHtml.escapeHtml(this.config.greetingMessage)}
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
                            <div class="chatbot-end-conversation">
                                <button id="chatbot-end-conversation-${this.config.embedCode}" class="end-conversation-btn" type="button">
                                    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                                        <path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/>
                                    </svg>
                                    End Conversation
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
            
            // Initialize in minimized (circle) state by default
            const toggle = document.getElementById(`chatbot-toggle-${this.config.embedCode}`);
            const content = toggle.querySelector('.chatbot-toggle-content');
            const minimizeBtn = toggle.querySelector('.chatbot-toggle-minimize');
            
            // Hide content and minimize button, add minimized-avatar class
            content.style.display = 'none';
            if (minimizeBtn) minimizeBtn.style.display = 'none';
            toggle.classList.add('minimized-avatar');
            
            // Add minimized class to widget
            const widget = document.getElementById(`chatbot-${this.config.embedCode}`);
            widget.classList.add('minimized');
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
                    animation: pulse-circle 2s ease-in-out infinite !important;
                    position: relative !important;
                }

                .chatbot-toggle.minimized-avatar::before {
                    content: '';
                    position: absolute;
                    top: 50%;
                    left: 50%;
                    width: 60px;
                    height: 60px;
                    border-radius: 50%;
                    background: rgba(0, 123, 255, 0.3);
                    transform: translate(-50%, -50%);
                    animation: pulse-ring 2s ease-out infinite;
                    pointer-events: none;
                    z-index: -1;
                }

                .chatbot-toggle.minimized-avatar:hover {
                    animation: pulse-circle-hover 1s ease-in-out infinite !important;
                    box-shadow: 0 6px 20px rgba(0, 123, 255, 0.4) !important;
                }

                @keyframes pulse-circle-hover {
                    0%, 100% {
                        transform: translateY(-2px) scale(1.05);
                        box-shadow: 0 6px 20px rgba(0, 123, 255, 0.4);
                    }
                    50% {
                        transform: translateY(-2px) scale(1.08);
                        box-shadow: 0 8px 25px rgba(0, 123, 255, 0.6);
                    }
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

                .chatbot-toggle.minimized-avatar .chatbot-toggle-content,
                .chatbot-toggle.minimized-avatar .chatbot-toggle-minimize {
                    display: none !important;
                }

                .chatbot-widget.closed {
                    display: none !important;
                }

                .chatbot-widget.closed .chatbot-toggle {
                    display: none !important;
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
                    bottom: 20px;
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

                .chatbot-minimize-btn {
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

                .chatbot-minimize-btn:hover {
                    background: rgba(255, 255, 255, 0.2);
                    opacity: 1;
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

                .chatbot-end-conversation {
                    padding: 8px 0;
                    text-align: center;
                }

                .end-conversation-btn {
                    background: #dc3545;
                    color: white;
                    border: none;
                    border-radius: 6px;
                    padding: 8px 16px;
                    font-size: 12px;
                    font-weight: 500;
                    cursor: pointer;
                    display: inline-flex;
                    align-items: center;
                    gap: 6px;
                    transition: all 0.2s ease;
                }

                .end-conversation-btn:hover {
                    background: #c82333;
                    transform: translateY(-1px);
                }

                .end-conversation-btn:active {
                    transform: translateY(0);
                }

                .end-conversation-btn svg {
                    width: 14px;
                    height: 14px;
                }

                .end-conversation-options {
                    display: flex;
                    gap: 12px;
                    justify-content: center;
                    margin-top: 8px;
                }

                .end-conversation-yes-btn,
                .end-conversation-no-btn {
                    background: #007bff;
                    color: white;
                    border: none;
                    border-radius: 6px;
                    padding: 8px 16px;
                    font-size: 12px;
                    font-weight: 500;
                    cursor: pointer;
                    display: inline-flex;
                    align-items: center;
                    gap: 6px;
                    transition: all 0.2s ease;
                }

                .end-conversation-yes-btn:hover {
                    background: #0056b3;
                    transform: translateY(-1px);
                }

                .end-conversation-no-btn {
                    background: #6c757d;
                }

                .end-conversation-no-btn:hover {
                    background: #545b62;
                    transform: translateY(-1px);
                }

                .end-conversation-yes-btn svg,
                .end-conversation-no-btn svg {
                    width: 14px;
                    height: 14px;
                }

                .contact-us-btn {
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    background: #007bff;
                    color: white;
                    border: none;
                    border-radius: 6px;
                    padding: 10px 20px;
                    font-size: 14px;
                    font-weight: 500;
                    text-decoration: none;
                    cursor: pointer;
                    transition: all 0.2s ease;
                    margin-top: 8px;
                }

                .contact-us-btn:hover {
                    background: #0056b3;
                    transform: translateY(-1px);
                    box-shadow: 0 4px 8px rgba(0, 123, 255, 0.3);
                    color: white;
                    text-decoration: none;
                }

                .contact-us-btn:active {
                    transform: translateY(0);
                }

                .contact-us-btn svg {
                    width: 16px;
                    height: 16px;
                    vertical-align: middle;
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

                @keyframes pulse-circle {
                    0%, 100% {
                        transform: scale(1);
                        box-shadow: 0 4px 12px rgba(0, 123, 255, 0.3);
                    }
                    50% {
                        transform: scale(1.05);
                        box-shadow: 0 4px 20px rgba(0, 123, 255, 0.5);
                    }
                }

                @keyframes pulse-ring {
                    0% {
                        transform: translate(-50%, -50%) scale(1);
                        opacity: 0.7;
                    }
                    100% {
                        transform: translate(-50%, -50%) scale(1.4);
                        opacity: 0;
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
                        bottom: 20px;
                        right: 20px;
                    }


                    .chatbot-control-buttons {
                        gap: 6px;
                    }

                    .chatbot-minimize-btn {
                        padding: 3px;
                    }

                    .chatbot-toggle-minimize {
                        width: 20px;
                        height: 20px;
                        top: 6px;
                        right: 6px;
                    }

                    .chatbot-toggle-minimize svg {
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
            const endConversationBtn = document.getElementById(`chatbot-end-conversation-${this.config.embedCode}`);
            const minimizeBtn = document.querySelector(`#chatbot-window-${this.config.embedCode} .chatbot-minimize-btn`);
            const toggleMinimizeBtn = document.querySelector(`#chatbot-toggle-${this.config.embedCode} .chatbot-toggle-minimize`);
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
                
                if (isVisible) {
                    // Chat window is closing, show toggle button
                    toggle.style.display = 'flex';
                    content.style.display = 'flex';
                    widget.classList.remove('minimized');
                } else {
                    // Chat window is opening, hide toggle button
                    toggle.style.display = 'none';
                    content.style.display = 'none';
                    
                    // Clear messages if flag is set
                    if (this.shouldClearMessages) {
                        this.clearMessages();
                        this.shouldClearMessages = false;
                        this.conversationId = null; // Reset conversation ID
                    }
                    
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


            // Toggle minimize button
            if (toggleMinimizeBtn) {
                toggleMinimizeBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    this.minimizeChat();
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

            // End conversation button
            if (endConversationBtn) {
                endConversationBtn.addEventListener('click', () => {
                    this.showEndConversationDialog();
                });
            }
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
                // response_html is the server-sanitized, well-formed reply.
                // data.response is the plain-text twin, kept so a widget
                // cached from before that field existed still works.
                if (data.response_html) {
                    this.addMessage(data.response_html, 'bot', { html: true });
                } else {
                    this.addMessage(data.response || data.error || 'Sorry, I encountered an issue. Please try again.', 'bot');
                }
                
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

        addMessage: function(text, sender, options) {
            const opts = options || {};
            const messagesContainer = document.getElementById(`chatbot-messages-${this.config.embedCode}`);
            const messageDiv = document.createElement('div');
            messageDiv.className = `message ${sender}-message`;

            const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

            const avatarDiv = document.createElement('div');
            avatarDiv.className = 'message-avatar';
            if (sender === 'user') {
                avatarDiv.textContent = '\u{1F464}';
            } else if (this.config.avatarUrl) {
                const img = document.createElement('img');
                img.src = this.config.avatarUrl;
                img.alt = 'Chatbot Avatar';
                avatarDiv.appendChild(img);
            } else {
                avatarDiv.textContent = '\u{1F916}';
            }

            const bubble = document.createElement('div');
            bubble.className = 'message-bubble';
            if (opts.html) {
                // Only ever the server's sanitized response_html. Re-sanitized
                // here because this widget runs on the customer's own site.
                bubble.appendChild(SafeHtml.sanitizeFragment(text));
            } else {
                // Visitor input, error strings and canned copy. textContent
                // cannot be talked into becoming markup, which is what the old
                // innerHTML path allowed - a visitor could store XSS on the
                // customer's page just by typing it.
                bubble.textContent = text;
            }

            const timeDiv = document.createElement('div');
            timeDiv.className = 'message-time';
            timeDiv.textContent = time;

            const contentDiv = document.createElement('div');
            contentDiv.className = 'message-content';
            contentDiv.appendChild(bubble);
            contentDiv.appendChild(timeDiv);

            messageDiv.appendChild(avatarDiv);
            messageDiv.appendChild(contentDiv);

            messagesContainer.appendChild(messageDiv);
            messagesContainer.scrollTop = messagesContainer.scrollHeight;
        },


        showTyping: function() {
            const messagesContainer = document.getElementById(`chatbot-messages-${this.config.embedCode}`);
            const typingDiv = document.createElement('div');
            typingDiv.className = 'message bot-message typing-message';
            
            const avatar = this.config.avatarUrl ? 
                          `<img src="${SafeHtml.escapeHtml(this.config.avatarUrl)}" alt="Chatbot Avatar">` : 
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
            
            // Show toggle button and hide content, keep avatar visible
            toggle.style.display = 'flex';
            const content = toggle.querySelector('.chatbot-toggle-content');
            const minimizeBtn = toggle.querySelector('.chatbot-toggle-minimize');
            
            content.style.display = 'none';
            if (minimizeBtn) minimizeBtn.style.display = 'none';
            
            // Add circular avatar class for styling
            toggle.classList.add('minimized-avatar');
        },



        restoreFromMinimized: function() {
            const widget = document.getElementById(`chatbot-${this.config.embedCode}`);
            const toggle = document.getElementById(`chatbot-toggle-${this.config.embedCode}`);
            const window = document.getElementById(`chatbot-window-${this.config.embedCode}`);
            
            // Remove minimized state
            widget.classList.remove('minimized');
            toggle.classList.remove('minimized-avatar');
            
            // Hide toggle button when chat window opens
            toggle.style.display = 'none';
            
            // Show toggle content and control buttons (for when it's shown again)
            const content = toggle.querySelector('.chatbot-toggle-content');
            const minimizeBtn = toggle.querySelector('.chatbot-toggle-minimize');
            
            content.style.display = 'flex';
            if (minimizeBtn) minimizeBtn.style.display = 'flex';
            
            // Clear messages if flag is set
            if (this.shouldClearMessages) {
                this.clearMessages();
                this.shouldClearMessages = false;
                this.conversationId = null; // Reset conversation ID
            }
            
            // Open the chat window
            window.style.display = 'flex';
            
            // Focus on input
            const input = document.getElementById(`chatbot-input-${this.config.embedCode}`);
            if (input) {
                input.focus();
            }
        },

        clearMessages: function() {
            const messagesContainer = document.getElementById(`chatbot-messages-${this.config.embedCode}`);
            if (messagesContainer) {
                // Clear all messages except the initial greeting
                messagesContainer.innerHTML = `
                    <div class="message bot-message">
                        <div class="message-avatar">
                            ${this.config.avatarUrl ? 
                                `<img src="${SafeHtml.escapeHtml(this.config.avatarUrl)}" alt="Chatbot Avatar">` : 
                                '🤖'
                            }
                        </div>
                        <div class="message-content">
                            <div class="message-bubble">
                                ${SafeHtml.escapeHtml(this.config.greetingMessage)}
                            </div>
                        </div>
                    </div>
                `;
            }
        },

        showEndConversationDialog: function() {
            const messagesContainer = document.getElementById(`chatbot-messages-${this.config.embedCode}`);
            
            // Add bot message asking if questions are answered
            this.addMessage("Have I answered all your questions?", 'bot');
            
            // Add Yes/No buttons
            const buttonContainer = document.createElement('div');
            buttonContainer.className = 'message bot-message end-conversation-buttons';
            buttonContainer.innerHTML = `
                <div class="message-avatar">
                    ${this.config.avatarUrl ? 
                        `<img src="${SafeHtml.escapeHtml(this.config.avatarUrl)}" alt="Chatbot Avatar">` : 
                        '🤖'
                    }
                </div>
                <div class="message-content">
                    <div class="message-bubble">
                        <div class="end-conversation-options">
                            <button class="end-conversation-yes-btn" onclick="ChatbotEmbed.handleEndConversationResponse('${this.config.embedCode}', true)">
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                                    <path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/>
                                </svg>
                                Yes
                            </button>
                            <button class="end-conversation-no-btn" onclick="ChatbotEmbed.handleEndConversationResponse('${this.config.embedCode}', false)">
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                                    <path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/>
                                </svg>
                                No
                            </button>
                        </div>
                    </div>
                </div>
            `;
            
            messagesContainer.appendChild(buttonContainer);
            messagesContainer.scrollTop = messagesContainer.scrollHeight;
        },

        handleEndConversationResponse: function(embedCode, isResolved) {
            if (isResolved) {
                // Mark conversation as resolved
                this.markConversationResolved();
                this.addMessage("Great! I'm glad I could help. Feel free to start a new conversation anytime!", 'bot');
                
                // Set flag to clear messages on next open
                this.shouldClearMessages = true;
                
                // Auto-minimize after 5 seconds
                setTimeout(() => {
                    this.minimizeChat();
                }, 5000);
            } else {
                // Show apology message and contact us option
                const contactUsUrl = this.config.contactUsUrl || null;
                let message = "I'm sorry I couldn't fully resolve your issue. ";
                
                if (contactUsUrl && contactUsUrl.trim() !== '') {
                    message += "Please contact our team and we'll be happy to assist you further.";
                    this.addMessage(message, 'bot');
                    
                    // Add Contact Us button
                    const messagesContainer = document.querySelector(`#chatbot-messages-${embedCode}`);
                    if (messagesContainer) {
                        const buttonDiv = document.createElement('div');
                        buttonDiv.className = 'chatbot-message chatbot-message-bot';
                        buttonDiv.innerHTML = `
                            <div class="text-center mt-2">
                                <a href="${contactUsUrl}" target="_blank" rel="noopener noreferrer" class="contact-us-btn">
                                    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" style="margin-right: 5px;">
                                        <path d="M20 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zm0 4l-8 5-8-5V6l8 5 8-5v2z"/>
                                    </svg>
                                    Contact Us
                                </a>
                            </div>
                        `;
                        messagesContainer.appendChild(buttonDiv);
                        messagesContainer.scrollTop = messagesContainer.scrollHeight;
                    }
                } else {
                    message += "Please reach out to our support team for further assistance.";
                    this.addMessage(message, 'bot');
                }
            }
            
            // Remove the Yes/No buttons
            const buttonContainer = document.querySelector(`#chatbot-messages-${embedCode} .end-conversation-buttons`);
            if (buttonContainer) {
                buttonContainer.remove();
            }
        },

        markConversationResolved: function() {
            // Send request to mark conversation as resolved
            if (this.conversationId) {
                fetch(this.config.apiUrl, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        action: 'end_conversation',
                        conversation_id: this.conversationId,
                        resolved: true
                    })
                })
                .then(response => response.json())
                .then(data => {
                    console.log('Conversation marked as resolved:', data);
                })
                .catch(error => {
                    console.error('Error marking conversation as resolved:', error);
                });
            }
        }
    };
})(); 