# -*- coding: utf-8 -*-
"""Chinese name to pinyin conversion using pypinyin (offline, no network needed)."""

from pypinyin import Style, lazy_pinyin


def to_pinyin(name: str) -> str:
    """Convert Chinese name to searchable pinyin string.

    Returns e.g. "zs zhangsan" for "张三" (initials + full pinyin).
    """
    if not name:
        return ''
    full = lazy_pinyin(name, style=Style.NORMAL)
    initials = [p[0] for p in full if p]
    return ''.join(initials) + ' ' + ''.join(full)


def pinyin_initial(name: str) -> str:
    """Return lowercase first pinyin initial of a name, or '' if not alphabetic."""
    py = to_pinyin(name)
    return py[0].lower() if py and py[0].isalpha() else ''
