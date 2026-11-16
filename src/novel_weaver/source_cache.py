"""Explicit caller-owned immutable page cache, never implicit server suppression.

Only callers that still hold the returned page may reuse it. Clear on context
loss or reader handoff. No book-status, context-ticket or authorization caching.
"""
from collections import OrderedDict
from copy import deepcopy
import time


class SourcePageCache:
    def __init__(self, max_chars=200000, ttl_seconds=300, clock=time.monotonic, max_pages=128):
        if max_chars < 1 or ttl_seconds <= 0 or max_pages < 1:
            raise ValueError("Cache limits must be positive")
        self.max_chars, self.ttl_seconds, self.clock = max_chars, ttl_seconds, clock
        self.max_pages = max_pages
        self.pages = OrderedDict()
        self.chars = 0

    @staticmethod
    def key(request):
        identity = tuple(request.get(k) for k in ("project", "book_id", "source_version"))
        if not all(isinstance(x, str) and x for x in identity):
            raise ValueError("Explicit project, book_id and source_version required")
        offset, maximum = request.get("offset", 0), request.get("max_chars", 12000)
        if type(offset) is not int or type(maximum) is not int or offset < 0 or maximum < 1:
            raise ValueError("Valid page coordinates required")
        return (*identity, offset, maximum)

    def clear(self):
        self.pages.clear()
        self.chars = 0

    def _drop(self, key):
        _, page = self.pages.pop(key)
        self.chars -= len(page["content"])

    def get(self, request, *, source_hash=None):
        key = self.key(request)
        value = self.pages.get(key)
        if value is None:
            return None
        saved, page = value
        if self.clock() - saved >= self.ttl_seconds or (source_hash is not None and source_hash != page["source_hash"]):
            self._drop(key)
            return None
        self.pages.move_to_end(key)
        return deepcopy(page)

    def put(self, request, page):
        key = self.key(request)
        content = page.get("content")
        if (not isinstance(content, str) or not page.get("source_hash")
                or page.get("source_version") != request["source_version"] or page.get("offset") != key[-2]):
            raise ValueError("Cache requires an actual, matching source page")
        expected = max(0, min(key[-1], page["total_chars"] - key[-2]))
        end = key[-2] + len(content)
        next_offset = end if end < page["total_chars"] else None
        if len(content) != expected or page.get("next_offset") != next_offset:
            raise ValueError("Incomplete or mismatched pagination")
        if key in self.pages:
            self._drop(key)
        if len(content) > self.max_chars:
            return
        for old in list(self.pages):
            if self.clock() - self.pages[old][0] >= self.ttl_seconds:
                self._drop(old)
        while self.pages and (self.chars + len(content) > self.max_chars or len(self.pages) >= self.max_pages):
            self._drop(next(iter(self.pages)))
        self.pages[key] = (self.clock(), deepcopy(page))
        self.chars += len(content)
