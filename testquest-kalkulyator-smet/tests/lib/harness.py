# -*- coding: utf-8 -*-
"""Мини-хелперы для блоков тестов."""


class Checks:
    def __init__(self):
        self.items = []

    def ok(self, name, condition, info=""):
        self.items.append({"name": name, "ok": bool(condition), "info": info})

    def eq(self, name, actual, expected, info=""):
        good = actual == expected
        detail = info or ("получено %r, ожидалось %r" % (actual, expected))
        if good and not info:
            detail = "%r" % (actual,)
        self.items.append({"name": name, "ok": good, "info": detail})

    def near(self, name, actual, expected, tol=1.0, info=""):
        good = abs(actual - expected) <= tol
        detail = info or ("получено %s, ожидалось %s (±%s)" % (actual, expected, tol))
        self.items.append({"name": name, "ok": good, "info": detail})

    def contains(self, name, haystack, needle, info=""):
        good = needle in haystack
        self.items.append(
            {"name": name, "ok": good, "info": info or ("нашли %r" % needle if good else "НЕ нашли %r" % needle)}
        )
