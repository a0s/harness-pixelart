"""Live studio: a local split-screen viewer.

Run it in one pane, work in the other. The page re-renders whenever any .pxa in
the watched directory changes, plays the animation at its real timing, replays
the stage history as a time-lapse, and offers every export as a download.

Standard library only -- no build step, no dependency, no network access.
"""

import os
import json
import time
import threading
import mimetypes
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pxa
import render
import anim
import lint as lintmod
import export as exportmod

WATCH_EXT = (".pxa",)
POLL = 0.35
PAGE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "assets", "studio.html")


class State(object):
    def __init__(self, root):
        self.root = os.path.abspath(root)
        self.version = 0
        self.lock = threading.Lock()
        self.docs = {}
        self.signature = None
        self.subscribers = []

    def files(self):
        out = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames
                           if d not in (".git", "out", "review", "node_modules", ".venv",
                                        "__pycache__", "history")]
            for fn in sorted(filenames):
                if fn.endswith(WATCH_EXT):
                    out.append(os.path.join(dirpath, fn))
        return out

    def _signature(self):
        sig = []
        for p in self.files():
            try:
                sig.append((p, os.path.getmtime(p), os.path.getsize(p)))
            except OSError:
                pass
            hist = os.path.join(os.path.dirname(p), "history")
            if os.path.isdir(hist):
                try:
                    sig.append((hist, len(os.listdir(hist)), 0))
                except OSError:
                    pass
        return tuple(sig)

    def refresh(self, force=False):
        sig = self._signature()
        if sig == self.signature and not force:
            return False
        docs = {}
        for p in self.files():
            try:
                docs[self.key(p)] = (p, pxa.load(p))
            except Exception as exc:
                docs[self.key(p)] = (p, exc)
        with self.lock:
            self.signature = sig
            self.docs = docs
            self.version += 1
        return True

    def key(self, path):
        return os.path.relpath(path, self.root).replace(os.sep, "/")

    def get(self, key):
        item = self.docs.get(key)
        if not item and self.docs:
            item = self.docs[sorted(self.docs)[0]]
        if not item:
            raise KeyError(key)
        path, doc = item
        if isinstance(doc, Exception):
            raise doc
        return path, doc

    def snapshot(self):
        projects = []
        for key in sorted(self.docs):
            path, doc = self.docs[key]
            if isinstance(doc, Exception):
                projects.append({"key": key, "name": key, "error": str(doc),
                                 "frames": [], "palette": [], "history": [], "findings": []})
                continue
            try:
                findings = [f.as_dict() for f in lintmod.run(doc)]
            except Exception as exc:
                findings = [{"rule": "lint-crashed", "severity": "info", "message": str(exc),
                             "frame": None, "at": [], "hint": ""}]
            counts = doc.frames[0].counts() if doc.frames else {}
            timings = anim.timing(doc)
            projects.append({
                "key": key,
                "name": doc.meta.get("name", os.path.splitext(os.path.basename(path))[0]),
                "path": path,
                "meta": doc.meta,
                "width": doc.width,
                "height": doc.height,
                "stage": doc.meta.get("stage", ""),
                "frames": [{"name": f.name, "index": i, "duration": timings[i]}
                           for i, f in enumerate(doc.frames)],
                "palette": [{"key": s.key, "hex": pxa.format_hex(s.rgba, s.is_transparent),
                             "name": s.name, "count": counts.get(s.key, 0)}
                            for s in doc.swatches],
                "history": self._history(path),
                "findings": findings,
                "brief": self._brief(path),
            })
        return {"version": self.version, "root": self.root, "projects": projects,
                "time": time.time()}

    def _history(self, path):
        d = os.path.join(os.path.dirname(path), "history")
        if not os.path.isdir(d):
            return []
        items = []
        for fn in sorted(f for f in os.listdir(d) if f.endswith(".png")):
            note = ""
            npath = os.path.join(d, os.path.splitext(fn)[0] + ".txt")
            if os.path.exists(npath):
                try:
                    with open(npath) as fh:
                        note = fh.read().strip()
                except OSError:
                    pass
            items.append({"file": fn, "note": note,
                          "url": "/file?path=" + urllib.parse.quote(os.path.join(d, fn))})
        return items

    def _brief(self, path):
        d = os.path.dirname(path)
        for name in ("brief.md", "BRIEF.md"):
            p = os.path.join(d, name)
            if os.path.exists(p):
                try:
                    with open(p) as fh:
                        return fh.read()[:8000]
                except OSError:
                    return ""
        return ""

    def subscribe(self):
        item = ([], threading.Condition())
        with self.lock:
            self.subscribers.append(item)
        return item

    def unsubscribe(self, item):
        with self.lock:
            if item in self.subscribers:
                self.subscribers.remove(item)

    def publish(self):
        with self.lock:
            subs = list(self.subscribers)
            version = self.version
        for q, cond in subs:
            with cond:
                q.append(version)
                cond.notify()


def watcher(state):
    while True:
        try:
            if state.refresh():
                state.publish()
        except Exception:
            pass
        time.sleep(POLL)


class Handler(BaseHTTPRequestHandler):
    state = None
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, ctype="application/json", extra=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(parsed.query)
        route = parsed.path
        try:
            if route == "/":
                with open(PAGE_PATH, "rb") as fh:
                    return self._send(200, fh.read(), "text/html; charset=utf-8")
            if route == "/api/state":
                return self._send(200, json.dumps(self.state.snapshot()))
            if route == "/api/events":
                return self.sse()
            if route == "/render":
                return self.render_png(q)
            if route == "/gif":
                return self.render_gif(q)
            if route == "/sheet":
                return self.review_sheet(q)
            if route == "/download":
                return self.download(q)
            if route == "/file":
                return self.raw_file(q)
            return self._send(404, json.dumps({"error": "not found"}))
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:
            try:
                return self._send(500, json.dumps({"error": str(exc)}))
            except Exception:
                pass

    def sse(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        item = self.state.subscribe()
        qu, cond = item
        try:
            self.wfile.write(b"retry: 1000\n\n")
            self.wfile.flush()
            while True:
                with cond:
                    if not qu:
                        cond.wait(timeout=15)
                    payload = qu[-1] if qu else None
                    del qu[:]
                if payload is None:
                    self.wfile.write(b": ping\n\n")
                else:
                    self.wfile.write(("event: change\ndata: %d\n\n" % payload).encode())
                self.wfile.flush()
        except Exception:
            pass
        finally:
            self.state.unsubscribe(item)

    def _png_bytes(self, img):
        tmp = os.path.join(_tmpdir(), "r%d_%d.png" % (os.getpid(), threading.get_ident()))
        pxa.write_png(tmp, img)
        with open(tmp, "rb") as fh:
            data = fh.read()
        os.unlink(tmp)
        return data

    def render_png(self, q):
        path, doc = self.state.get(q.get("p", [""])[0])
        frame = q.get("f", [""])[0] or None
        scale = max(1, min(32, int(q.get("s", ["1"])[0])))
        mode = q.get("mode", ["normal"])[0]
        fr = doc.frame(frame)
        if mode == "onion":
            base = anim.onion(doc, doc.frames.index(fr), prev=1, next=1)
            img = [[px for px in row for _ in range(scale)] for row in base]
            img = [row for row in img for _ in range(scale)]
        elif mode == "value":
            img = render.value_view(doc, fr, scale)
        elif mode == "silhouette":
            img = render.silhouette_view(doc, fr, scale)
        else:
            img = render.render_frame(doc, fr, scale)
        if q.get("grid", ["0"])[0] == "1" and scale >= 3:
            render.draw_grid(img, scale, major=8)
        return self._send(200, self._png_bytes(img), "image/png")

    def render_gif(self, q):
        path, doc = self.state.get(q.get("p", [""])[0])
        scale = max(1, min(24, int(q.get("s", ["6"])[0])))
        tmp = os.path.join(_tmpdir(), "a%d_%d.gif" % (os.getpid(), threading.get_ident()))
        anim.to_gif(doc, tmp, scale=scale)
        with open(tmp, "rb") as fh:
            data = fh.read()
        os.unlink(tmp)
        return self._send(200, data, "image/gif",
                          {"Content-Disposition": 'attachment; filename="%s.gif"'
                           % doc.meta.get("name", "anim")})

    def review_sheet(self, q):
        path, doc = self.state.get(q.get("p", [""])[0])
        img = render.review_sheet(doc, q.get("f", [""])[0] or None)
        return self._send(200, self._png_bytes(img), "image/png")

    def raw_file(self, q):
        path = os.path.abspath(q.get("path", [""])[0])
        if not path.startswith(self.state.root) or not os.path.isfile(path):
            return self._send(403, json.dumps({"error": "outside workspace"}))
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        with open(path, "rb") as fh:
            return self._send(200, fh.read(), ctype)

    def download(self, q):
        key = q.get("p", [""])[0]
        kind = q.get("kind", ["pxa"])[0]
        path, doc = self.state.get(key)
        name = doc.meta.get("name", "sprite")
        if kind == "pxa":
            with open(path, "rb") as fh:
                return self._send(200, fh.read(), "text/plain",
                                  {"Content-Disposition": 'attachment; filename="%s.pxa"' % name})
        if kind.startswith("png"):
            scale = int(kind[3:] or 1)
            img = render.render_frame(doc, doc.frame(q.get("f", [""])[0] or None), scale)
            return self._send(200, self._png_bytes(img), "image/png",
                              {"Content-Disposition": 'attachment; filename="%s@%dx.png"'
                               % (name, scale)})
        if kind == "gif":
            return self.render_gif(q)
        if kind == "sheet":
            tmp = os.path.join(_tmpdir(), "sh%d.png" % os.getpid())
            exportmod.spritesheet(doc, tmp)
            with open(tmp, "rb") as fh:
                data = fh.read()
            os.unlink(tmp)
            return self._send(200, data, "image/png",
                              {"Content-Disposition": 'attachment; filename="%s_sheet.png"' % name})
        if kind == "bundle":
            out_dir = os.path.join(os.path.dirname(path), "out")
            written = exportmod.bundle(doc, out_dir)
            return self._send(200, json.dumps({"written": written}))
        return self._send(400, json.dumps({"error": "unknown kind"}))


def _tmpdir():
    d = os.path.join(os.path.expanduser("~"), ".cache", "pixelart-studio")
    if not os.path.isdir(d):
        os.makedirs(d)
    return d


def serve(root, host="127.0.0.1", port=8765, open_browser=False):
    state = State(root)
    state.refresh(force=True)
    Handler.state = state
    threading.Thread(target=watcher, args=(state,), daemon=True).start()
    httpd = ThreadingHTTPServer((host, port), Handler)
    url = "http://%s:%d/" % (host, port)
    print("pixel-art studio watching %s" % state.root)
    print("open %s   (ctrl-c to stop)" % url)
    print("%d sprite(s) found" % len(state.docs))
    if open_browser:
        import webbrowser
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstudio stopped")
