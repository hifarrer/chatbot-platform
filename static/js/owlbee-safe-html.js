/**
 * Client-side counterpart to services/reply_sanitizer.py.
 *
 * The server already sanitizes every chat reply, so this is defence in depth -
 * but it is defence that matters, because the widget executes on the customer's
 * own website, where a bad reply is script execution on their page rather than
 * a cosmetic glitch on ours.
 *
 * It also gives the dashboard's cosmetic formatter (bold plan names, prices,
 * lists, JSON tables) a way to run over *text nodes only*. That is the actual
 * fix for the reported bug: formatBoldText used to rewrite the whole HTML
 * string, so /\bfree\b/gi matched inside
 * https://smallscholars.com.au/free-trial-enquiries/ and injected a <strong>
 * into the middle of a URL, which the link regex then tore in half.
 *
 * There is no build step in this project, so the implementation between the
 * sentinel comments below is duplicated verbatim inside
 * static/js/chatbot-embed.js - that file ships to third-party sites as a single
 * pasted <script src>, where a second request would add a CSP failure mode and
 * a load-order race. qa_phase6_reply_html.py fails if the two copies drift.
 */
(function (global) {
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

    global.OwlbeeSafeHtml = SafeHtml;
})(typeof window !== 'undefined' ? window : this);
