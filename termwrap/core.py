from __future__ import absolute_import, print_function

from ansiwrap.ansistate import ANSIState
import re
import sys
import imp
import wcwidth
import unicodedata

# import a copy of textwrap3 which we will viciously monkey-patch
# to use our version of len, not the built-in
import os
a_textwrap = imp.load_module('a_textwrap', *imp.find_module('textwrap3'))


__all__ = 'wrap fill shorten strip_color ansilen ansilen_unicode ansi_terminate_lines wrap_proper'.split()

ANSIRE = re.compile('\x1b\\[(K|.*?m)')


_PY2 = sys.version_info[0] == 2
string_types = basestring if _PY2 else str


def strip_color(s):
    """
    Remove ANSI color/style sequences from a string. The set of all
    possibly ANSI sequences is large, so does not try to strip every
    possible one. But does strip some outliers seen not just in text
    generated by this module, but by other ANSI colorizers in the wild.
    Those include `\x1b[K` (aka EL or erase to end of line) and `\x1b[m`
    a terse version of the more common `\x1b[0m`.
    """
    return ANSIRE.sub('', s)

    # strip_color provided here until correct version can be installed
    # via ansicolors


def ansilen_unicode(s):
    if isinstance(s, string_types):
        s_without_ansi = unicodedata.normalize('NFC', ANSIRE.sub('', s))
        s_without_ansi = s_without_ansi.replace("\n", "_")
        return sum(map(lambda c: max(wcwidth.wcwidth(c), 0), s_without_ansi))
    else:
        return len(s)
    
def ansilen(s):
    """
    Return the length of a string as it would be without common
    ANSI control codes. The check of string type not needed for
    pure string operations, but remembering we are using this to
    monkey-patch len(), needed because textwrap code can and does
    use len() for non-string measures.
    """
    if isinstance(s, string_types):
        s_without_ansi = ANSIRE.sub('', s)
        return len(s_without_ansi)
    else:
        return len(s)

# monkeypatch!
a_textwrap.len = ansilen_unicode


def _unified_indent(kwargs):
    """
    Private helper. If kwargs has an `indent` parameter, that is
    made into the the value of both the `initial_indent` and the
    `subsequent_indent` parameters in the returned dictionary.
    """
    indent = kwargs.get('indent')
    if indent is None:
        return kwargs
    unifed = kwargs.copy()
    del unifed['indent']
    str_or_int = lambda val: ' ' * val if isinstance(val, int) else val
    if isinstance(indent, tuple):
        initial, subsequent = indent
    else:
        initial, subsequent = (indent, indent)

    initial, subsequent = indent if isinstance(indent, tuple) else (indent, indent)
    unifed['initial_indent'] = str_or_int(initial)
    unifed['subsequent_indent'] = str_or_int(subsequent)
    return unifed


def wrap(s, width=70, **kwargs):
    """
    Wrap a single paragraph of text, returning a list of wrapped lines.

    Designed to work exactly as `textwrap.wrap`, with two exceptions:
    1. Wraps text containing ANSI control code sequences without considering
    the length of those (hidden, logically zero-length) sequences.
    2. Accepts a unified `indent` parameter that, if present, sets the
    `initial_indent` and `subsequent_indent` parameters at the same time.
    """
    kwargs = _unified_indent(kwargs)
    wrapped = a_textwrap.wrap(s, width, **kwargs)
    return ansi_terminate_lines(wrapped)

def wrap_proper(in_text, width):
    """
    Wrap text without mucking up the ansi escapes, for real.
    
    doesn't support indent because I do not need indent.
    """
    lines = []
    for line in in_text.split("\n"):
        lines.extend(wrap_proper_line(line, width))
    return lines

def wrap_proper_line(in_text, width):
    ansi_seqs = list(ANSIRE.finditer(in_text))
    stripped_text = strip_color(in_text)
    wrapped_text = wrap(stripped_text, width)
    offset = 0
    wrapped_ansi_text = []
    for line in wrapped_text:
        ansi_line = line
        for match in ansi_seqs:
            if match.start() - offset >= 0 and match.start() - offset < len(ansi_line):
                match_text = in_text[match.start():match.end()]
                ansi_line = ansi_line[:match.start() - offset] + match_text + ansi_line[match.start() - offset:] # TODO refresh more
        offset += len(ansi_line)
        wrapped_ansi_text.append(ansi_line)
    wrapped_ansi_text = ansi_terminate_lines(wrapped_ansi_text)
    return wrapped_ansi_text

def fill(s, width=70, **kwargs):
    """
    Fill a single paragraph of text, returning a new string.

    Designed to work exactly as `textwrap.fill`, with two exceptions:
    1. Fills text containing ANSI control code sequences without considering
    the length of those (hidden, logically zero-length) sequences.
    2. Accepts a unified `indent` parameter that, if present, sets the
    `initial_indent` and `subsequent_indent` parameters at the same time.
    """
    return '\n'.join(wrap(s, width, **kwargs))


def _ansi_optimize(s):
    # remove clear-to-end-of-line (EL)
    s = re.sub('\x1b\[K', '', s)
    return s


# It is very appealing to think that we can write an optimize() routine, esp.
# since textwrap can add some obviously-null sequences to strings (e.g. if
# style was applied to spaces, but the spaces were then removed ad the end
# of lines, leaving only styling). But this requires EXTREME CARE. ANSI is
# very stateful. Some states simple string search would suggest are positive
# e.g. (20-29, 39, 49) are explicitly negative, and only by parsing a stream
# from a null state (either the last esc[m or the very beginning) can you truly
# be sure you have parsed all the state transitions properly. The ANSIState
# class would probably need to be used to for this. So beware. MANY snakes lurk
# in this grass.


def ansi_terminate_lines(lines):
    """
    Walk through lines of text, terminating any outstanding color spans at
    the end of each line, and if one needed to be terminated, starting it on
    starting the color at the beginning of the next line.
    """
    state = ANSIState()
    term_lines = []
    end_code = None
    for line in lines:
        codes = ANSIRE.findall(line)
        for c in codes:
            state.consume(c)
        if end_code:          # from prior line
            line = end_code + line
        end_code = state.code()
        if end_code:          # from this line
            line = line + '\x1b[0m'

        term_lines.append(line)

    return term_lines


def shorten(text, width, **kwargs):
    """Collapse and truncate the given text to fit in the given width.
    The text first has its whitespace collapsed.  If it then fits in
    the *width*, it is returned as is.  Otherwise, as many words
    as possible are joined and then the placeholder is appended::
        >>> textwrap.shorten("Hello  world!", width=12)
        'Hello world!'
        >>> textwrap.shorten("Hello  world!", width=11)
        'Hello [...]'
    """
    w = a_textwrap.TextWrapper(width=width, max_lines=1, **kwargs)
    unterm = w.wrap(' '.join(text.strip().split()))
    if not unterm:
        return ''
    term = ansi_terminate_lines(unterm[:1])
    return term[0]


# TODO: extend ANSI-savvy handling to other textwrap entry points such
#       as indent, dedent, and TextWrapper
# TODO: shorten added for py34 and ff; is it worth back-porting?
# TODO: should we provide a late model (py36) version of textwrap for prev
#       versions? has its behavior changed? would unicode issues make this a morass?
# TODO: add lru_cache memoization to ansilen given textwrap's sloppy/excessive
#       use of the len function
# TODO: tests (see https://github.com/python/cpython/blob/6f0eb93183519024cb360162bdd81b9faec97ba6/Lib/test/test_textwrap.py)
# TODO: documentation
