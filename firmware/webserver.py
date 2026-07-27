"""
Non-blocking HTTP server (MicroPython) that delegates to webapp.route().

Uses a non-blocking listening socket polled from the main loop via serve_once(), so
the web server never stalls the button/window/watchdog servicing. One request is
handled per accepted connection (simple, robust for a couple of LAN clients).
"""

import socket

import webapp


class WebServer:
    def __init__(self, actions, port=80):
        self.actions = actions
        addr = socket.getaddrinfo("0.0.0.0", port)[0][-1]
        s = socket.socket()
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(addr)
        s.listen(2)
        s.setblocking(False)
        self._s = s

    def serve_once(self):
        """Accept + handle at most one pending request. Non-blocking; returns
        True if a request was handled, False if none was pending."""
        try:
            conn, _ = self._s.accept()
        except OSError:
            return False  # nothing pending
        try:
            conn.settimeout(2)
            req = conn.recv(1024)
            if req:
                method, path = _parse_request_line(req)
                status, ctype, body = webapp.route(method, path, self.actions)
                _send(conn, status, ctype, body)
        except OSError:
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass
        return True


def _parse_request_line(raw):
    """Extract (METHOD, PATH) from the first line of an HTTP request."""
    try:
        line = raw.split(b"\r\n", 1)[0].decode()
        parts = line.split(" ")
        return parts[0], parts[1]
    except Exception:
        return "GET", "/"


_STATUS_TEXT = {200: "OK", 404: "Not Found"}


def _send(conn, status, ctype, body):
    if isinstance(body, str):
        body = body.encode()
    head = (
        "HTTP/1.1 {} {}\r\n"
        "Content-Type: {}\r\n"
        "Content-Length: {}\r\n"
        "Connection: close\r\n\r\n"
    ).format(status, _STATUS_TEXT.get(status, "OK"), ctype, len(body))
    conn.send(head.encode())
    conn.send(body)
