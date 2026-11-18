"""Safe structural inspection of the authenticated MFL lineup web form (GET only)."""
from html.parser import HTMLParser
from collections import Counter
from urllib.parse import urlsplit
import re


class FormShape(HTMLParser):
    def __init__(self):
        super().__init__()
        self.form = False
        self.actions = []
        self.names = Counter()
        self.submit_controls = Counter()
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "form":
            self.form = True
            act = urlsplit(a.get("action") or "")
            self.actions.append({"route": act.path.rsplit("/", 1)[-1].lower(),
                                 "method": (a.get("method") or "get").lower(),
                                 "has_query": bool(act.query),
                                 "has_host": bool(act.hostname)})
            return
        if not self.form:
            return
        if tag in ("input", "select", "button", "textarea"):
            name = str(a.get("name") or "")
            # The field name itself is not secret; reject arbitrary strings.
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_\[\]]{0,40}", name):
                name = "[nonstandard]"
            typ = (a.get("type") or tag).lower()
            if not re.fullmatch("[a-z]{1,20}", typ):
                typ = "other"
            self.names[(name, typ)] += 1
            if typ in ("submit", "button"):
                self.submit_controls[name] += 1
    def handle_endtag(self, tag):
        if tag == "form":
            self.form = False

def report(html):
    p = FormShape()
    p.feed(html)
    return {
        "forms": p.actions,
        "fields": [{"name": name, "type": kind, "count": count}
                   for (name, kind), count in sorted(p.names.items())],
        "submit_controls": dict(p.submit_controls),
    }
