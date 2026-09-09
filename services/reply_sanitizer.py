"""Turn a chatbot reply into HTML that a browser can render without guessing.

Every chat surface in this app ends in `innerHTML`. Until this module existed,
nothing between the model and that assignment escaped, validated, or repaired
anything - and two separate layers *injected* markup into the reply and then let
a regex loose over the result.

The failure that motivated this. `formatBoldText` in the owner-facing chat
bolded plan names with /\\b(Free|Starter|Basic|Premium|Enterprise)\\b/gi. A
hyphen is a word boundary, so `free` inside a perfectly ordinary URL matched:

    https://smallscholars.com.au/free-trial-enquiries/
    -> https://smallscholars.com.au/<strong class="text-primary">free</strong>-trial-enquiries/

Then the link regex - https?://[^\\s]+, greedy to the first space, which was now
the space inside `<strong class=...` - wrapped `https://smallscholars.com.au/<strong`
in an anchor and left the rest of the tag dangling as text. The visitor saw:

    You can also book online here: https://smallscholars.com.au/ class="text-primary">free-trial-enquiries/

An earlier fix (Oct 2025) reordered the email/phone/URL passes in all four
copies of that function. It could not have worked: the ordering was never the
problem. Running a regex over markup is the problem, and it is unfixable by
tuning the regex, because any pattern that injects a tag containing a space
re-creates it.

So this module inverts the order. It parses first, and only then walks *text
nodes* to linkify. Building anchors out of text-node content and splicing them
in as siblings is structurally incapable of reaching inside an attribute or
splitting a tag - which is the property the regex approach never had, and the
reason this is a fix rather than another patch.

The parse is also the repair. BeautifulSoup's html.parser closes tags left open
at end of input and discards stray end tags, so a truncated
`<a href="...">Book` comes back closed instead of swallowing the rest of the
message. And because parsing decodes entities before we inspect anything, the
obfuscated `&#106;avascript:` and `java&#9;script:` forms are already normalised
by the time the scheme check sees them.

Tags and attributes are allowlisted, not blocklisted. The chatbot's system
prompt and its scraped knowledge base are both customer-supplied and both end up
in the model's mouth, and the widget runs on the customer's own website - so
`<img src=x onerror=...>` in a reply was script execution on their page, not a
cosmetic bug.

    from services.reply_sanitizer import sanitize_reply, reply_to_plain_text

    html = sanitize_reply(model_text)       # safe, well-formed, links live
    text = reply_to_plain_text(model_text)  # same content, no markup

Privacy rule from CONTRIBUTING applies here as everywhere: this module logs
counts and lengths, never reply text.
"""
import html as _html
import re

from bs4 import BeautifulSoup, Comment, Doctype, NavigableString

from .logging_setup import RunLogger, get_logger

_log = RunLogger(get_logger('owlbee.sanitize'))

# What a support answer legitimately needs, and nothing else. Deliberately no
# <img> (tracking pixels, and onerror is the classic payload), no <table> (a
# model-invented table does not fit a 400px widget), and no <div> (layout
# escape onto the customer's page).
ALLOWED_TAGS = {'a', 'b', 'strong', 'i', 'em', 'u', 'br', 'p',
                'ul', 'ol', 'li', 'code', 'span'}

# Removed *with* their contents. Unwrapping <script> would print the payload as
# visible text, which is how a careless sanitizer turns XSS into defacement.
DROP_WITH_CONTENT = {'script', 'style', 'iframe', 'object', 'embed', 'applet',
                     'noscript', 'template', 'svg', 'math', 'form', 'input',
                     'textarea', 'select', 'button', 'link', 'meta', 'base',
                     'head', 'title'}

# Anything else - <div>, <h3>, <table> - is unwrapped: the tag goes, the text
# stays. A stray wrapper must not cost the visitor a sentence.

# An allowlist rather than a blocklist of on* handlers, so `onpointerrawupdate`
# and whatever ships next year die without anyone having to remember them.
GLOBAL_ATTRS = {'class', 'title'}
TAG_ATTRS = {'a': {'href'}}

ALLOWED_SCHEMES = ('http', 'https', 'mailto', 'tel')

# ~15k tokens. Longer than any real answer, short enough that a runaway
# generation cannot hand BeautifulSoup a pathological document.
MAX_REPLY_CHARS = 60000

# A class attribute is for `text-primary`, not for a Bootstrap layout escape.
MAX_CLASS_TOKENS = 8
_CLASS_TOKEN_RE = re.compile(r'^[A-Za-z0-9_-]{1,40}$')

# "java\tscript:" and "java\nscript:" are live URLs in every browser.
_HREF_STRIP_RE = re.compile(r'[\x00-\x20\x7f]')

# Linkification never descends into these: an <a> because nesting anchors is the
# original bug, <code> because a URL in a code sample is being shown, not offered.
SKIP_LINKIFY_INSIDE = {'a', 'code'}

# One left-to-right alternation, email first. The previous implementation ran
# three sequential passes and patched the interference with an indexOf() check
# that only ever inspected the first occurrence of a match - so the second
# mention of a domain in a reply was judged by the first one's context. With a
# single pass, bob@example.com consumes the whole token and scanning resumes
# after it, so example.com can never be re-matched out of an address.
_LINKIFY_RE = re.compile(r"""
    (?P<email>[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})
  | (?P<url>(?:https?://|www\.)[^\s<>"']+
        | [A-Za-z0-9][A-Za-z0-9\-]*(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,24}(?:/[^\s<>"']*)?)
  | (?P<phone>(?<![0-9])(?:\+?1[-.\s]?)?\(?[0-9]{3}\)?[-.\s]?[0-9]{3}[-.\s]?[0-9]{4}(?![0-9]))
""", re.VERBOSE)

# A bare word.word token is only a link if its last label is a real TLD.
# Without this, "etc.Please" and "report.pdf" both became anchors. Anything
# carrying a scheme, a www. prefix, or a /path skips this check entirely.
COMMON_TLDS = {
    'com', 'org', 'net', 'edu', 'gov', 'mil', 'int', 'io', 'ai', 'co', 'info',
    'biz', 'app', 'dev', 'me', 'tv', 'xyz', 'online', 'store', 'site', 'shop',
    'blog', 'cloud', 'tech', 'agency', 'studio', 'design', 'email',
    'au', 'uk', 'nz', 'ca', 'us', 'de', 'fr', 'es', 'it', 'nl', 'ie', 'in',
    'jp', 'cn', 'br', 'mx', 'za', 'se', 'no', 'dk', 'fi', 'ch', 'at', 'be',
    'pl', 'pt', 'gr', 'cz', 'ru', 'sg', 'hk', 'kr', 'il', 'ae',
}

# Trailing punctuation belongs to the sentence, not the URL. "See example.com."
# used to put the full stop inside the anchor.
_URL_TAIL = '.,;:!?\'"'
_URL_CLOSERS = {')': '(', ']': '[', '}': '{'}


def _safe_href(value):
    """Normalise a link target, or return None if it must not become a link.

    Runs after parsing, so entity- and whitespace-obfuscated schemes have
    already been decoded into their real form by the time we look at them.
    """
    if not value:
        return None
    url = _HREF_STRIP_RE.sub('', value).strip()
    if not url:
        return None
    if url.startswith('#'):
        return url
    # Protocol-relative: no honest use in a support answer, and a plain
    # open-redirect surface.
    if url.startswith('//'):
        return None

    head, sep, _rest = url.partition(':')
    if sep and not any(c in head for c in '/?#'):
        if head.lower() not in ALLOWED_SCHEMES:
            return None
        return url
    return 'https://' + url


def _trim_url_tail(matched):
    """Split a URL match into (url, trailing_text) so punctuation stays prose."""
    tail = ''
    while matched:
        last = matched[-1]
        if last in _URL_TAIL:
            pass
        elif last in _URL_CLOSERS:
            # Keep a closer the URL actually opened, e.g. a wiki (foo)_bar link.
            if matched.count(_URL_CLOSERS[last]) >= matched.count(last):
                break
        else:
            break
        tail = last + tail
        matched = matched[:-1]
    return matched, tail


def _skip_node(node):
    """True when this text node sits inside a tag we must not linkify into."""
    for parent in node.parents:
        if getattr(parent, 'name', None) in SKIP_LINKIFY_INSIDE:
            return True
    return False


def _linkify_text_nodes(soup, stats):
    """Turn bare URLs, emails and phone numbers in text nodes into markup.

    Only text nodes are touched, and only ones with no <a>/<code> ancestor, so
    this pass cannot reach into an attribute or split an existing tag no matter
    what the surrounding markup looks like.
    """
    nodes = [n for n in soup.find_all(string=True)
             if not isinstance(n, (Comment, Doctype))]

    for node in nodes:
        text = str(node)
        if not text.strip() or _skip_node(node):
            continue

        parts = []
        cursor = 0
        for match in _LINKIFY_RE.finditer(text):
            kind = match.lastgroup
            raw = match.group()
            start, end = match.span()

            if kind == 'url':
                raw, tail = _trim_url_tail(raw)
                if not raw:
                    continue
                bare = not raw.lower().startswith(('http://', 'https://', 'www.'))
                if bare and '/' not in raw:
                    if raw.rsplit('.', 1)[-1].lower() not in COMMON_TLDS:
                        continue
                href = _safe_href(raw)
                if not href:
                    continue
                new = soup.new_tag('a', href=href, target='_blank',
                                   rel='noopener noreferrer',
                                   attrs={'class': 'chatbot-link'})
                new.string = raw
                stats['links_added'] += 1
            else:
                # Emails and phone numbers render bold, never as links - that is
                # the behaviour the Oct 2025 change settled on and customers see.
                # Already the whole of a <strong>? Leave it alone, or a second
                # pass would nest <strong> inside <strong> and idempotence -
                # the property that makes double-processing harmless - is lost.
                if (getattr(node.parent, 'name', None) in ('strong', 'b')
                        and raw == text.strip()):
                    continue
                tail = ''
                new = soup.new_tag('strong')
                new.string = raw

            if start > cursor:
                parts.append(NavigableString(text[cursor:start]))
            parts.append(new)
            if tail:
                parts.append(NavigableString(tail))
            cursor = end

        if not parts:
            continue
        if cursor < len(text):
            parts.append(NavigableString(text[cursor:]))
        node.replace_with(*parts)


def sanitize_reply(text, linkify=True, stats_sink=None):
    """Return well-formed, allowlisted HTML for a chatbot reply.

    Repairs unclosed tags, drops anything off the allowlist, strips every
    attribute except class/title/href, refuses non-http(s)/mailto/tel targets,
    and linkifies bare URLs in text nodes. Safe to call twice: the operation is
    idempotent, which matters because double-processing is exactly what caused
    the bug this module exists to fix.
    """
    stats = stats_sink if stats_sink is not None else {}
    for key in ('tags_dropped', 'tags_unwrapped', 'attrs_dropped',
                'hrefs_rejected', 'links_added'):
        stats.setdefault(key, 0)
    stats.setdefault('truncated', False)

    if not text or not isinstance(text, str):
        stats['chars_in'] = 0
        stats['chars_out'] = 0
        return ''

    stats['chars_in'] = len(text)
    if len(text) > MAX_REPLY_CHARS:
        text = text[:MAX_REPLY_CHARS]
        stats['truncated'] = True

    try:
        soup = BeautifulSoup(text, 'html.parser')

        for comment in soup.find_all(string=lambda s: isinstance(s, Comment)):
            comment.extract()

        for tag in soup.find_all(list(DROP_WITH_CONTENT)):
            if not tag.decomposed:
                tag.decompose()
                stats['tags_dropped'] += 1

        for tag in soup.find_all(True):
            if tag.decomposed:
                continue

            if tag.name not in ALLOWED_TAGS:
                tag.unwrap()
                stats['tags_unwrapped'] += 1
                continue

            keep = GLOBAL_ATTRS | TAG_ATTRS.get(tag.name, set())
            for attr in list(tag.attrs):
                if attr not in keep:
                    del tag[attr]
                    stats['attrs_dropped'] += 1

            if 'class' in tag.attrs:
                values = tag['class']
                if isinstance(values, str):
                    values = values.split()
                values = [c for c in values if _CLASS_TOKEN_RE.match(c)][:MAX_CLASS_TOKENS]
                if values:
                    tag['class'] = values
                else:
                    del tag['class']

            if tag.name == 'a':
                # html.parser keeps a nested <a> that a browser would have
                # split apart, and a nested anchor is the exact shape this
                # module exists to stop shipping. Outermost wins.
                if any(getattr(p, 'name', None) == 'a' for p in tag.parents):
                    tag.unwrap()
                    stats['tags_unwrapped'] += 1
                    continue

                href = _safe_href(tag.get('href'))
                if not href:
                    # The link dies, the sentence lives.
                    tag.unwrap()
                    stats['hrefs_rejected'] += 1
                    continue
                tag['href'] = href
                # Matches what the widget produced before, and closes
                # reverse-tabnabbing on the customer's own site.
                tag['target'] = '_blank'
                tag['rel'] = 'noopener noreferrer'

        if linkify:
            _linkify_text_nodes(soup, stats)

        result = str(soup)
    except Exception:
        # A bug in here must never turn a good answer into a 500 or a blank
        # bubble - same rule as the metering guard in the chat route.
        _log.error('sanitize.failed', exc_info=True, chars_in=stats['chars_in'])
        result = _html.escape(text)

    stats['chars_out'] = len(result)
    return result


def reply_to_plain_text(text):
    """The same reply with every tag removed - the legacy plain-text API field."""
    if not text or not isinstance(text, str):
        return ''
    if len(text) > MAX_REPLY_CHARS:
        text = text[:MAX_REPLY_CHARS]
    try:
        soup = BeautifulSoup(text, 'html.parser')
        for tag in soup.find_all(list(DROP_WITH_CONTENT)):
            if not tag.decomposed:
                tag.decompose()
        for tag in soup.find_all(['br', 'p', 'li', 'div', 'tr', 'h1', 'h2', 'h3']):
            tag.insert_before(NavigableString('\n'))
        out = soup.get_text()
    except Exception:
        _log.error('plain_text.failed', exc_info=True, chars_in=len(text))
        return text
    out = re.sub(r'[ \t]+\n', '\n', out)
    out = re.sub(r'\n{3,}', '\n\n', out)
    return out.strip()
