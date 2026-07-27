"""
Web application logic — PURE request routing, no sockets. Host-tested.

route(method, path, actions) -> (status, content_type, body_str)

  GET  /            -> HTML control page
  GET  /status      -> JSON {temp, humid, window, fans, mister, time}
  GET  /data        -> JSON datalog snapshot
  POST /window      -> toggle window   (or ?a=open|close|stop)
  POST /fans        -> toggle fans     (or ?a=on|off)
  POST /mister      -> toggle mister   (or ?a=on|off)

`actions` is an object the caller supplies exposing:
    status()  -> dict
    snapshot()-> dict (datalog)
    window(a) / fans(a) / mister(a)  -> perform + return new status dict
The socket layer (webserver.py) wires a real controller to this.
"""

try:
    import ujson as json
except ImportError:
    import json


def _qs(path):
    """Split 'p?a=b&c=d' -> ('p', {'a':'b','c':'d'})."""
    if "?" not in path:
        return path, {}
    p, q = path.split("?", 1)
    params = {}
    for pair in q.split("&"):
        if "=" in pair:
            k, v = pair.split("=", 1)
            params[k] = v
        elif pair:
            params[pair] = ""
    return p, params


def route(method, path, actions):
    p, params = _qs(path)

    if method == "GET" and p == "/":
        return 200, "text/html", PAGE

    if method == "GET" and p == "/status":
        return 200, "application/json", json.dumps(actions.status())

    if method == "GET" and p == "/data":
        return 200, "application/json", json.dumps(actions.snapshot())

    if method == "GET" and p in ("/data.csv", "/events.csv"):
        snap = actions.snapshot()
        if p == "/data.csv":
            rows = snap["samples"]
            cols = ("t", "in_t", "in_h", "out_t", "out_h")
        else:
            rows = snap["events"]
            cols = ("t", "src", "dev", "act", "in_t", "in_h", "out_t", "out_h")
        return 200, "text/csv", _to_csv(rows, cols)

    if method == "POST" and p in ("/window", "/fans", "/mister"):
        device = p[1:]
        a = params.get("a")  # optional explicit action; None = toggle
        new_status = getattr(actions, device)(a)
        return 200, "application/json", json.dumps(new_status)

    return 404, "text/plain", "not found"


def _to_csv(rows, cols):
    out = [",".join(cols)]
    for r in rows:
        out.append(",".join("" if r.get(c) is None else str(r.get(c)) for c in cols))
    return "\n".join(out) + "\n"


# Minimal single-file page: shows readings + status, buttons POST then refresh.
PAGE = """<!DOCTYPE html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Greenhouse</title><style>
body{font-family:sans-serif;max-width:480px;margin:24px auto;padding:0 12px}
h1{font-size:1.3rem}.r{font-size:2.2rem;margin:8px 0}
.row{display:flex;gap:8px;align-items:center;margin:10px 0}
button{flex:1;padding:14px;font-size:1rem;border:0;border-radius:8px;background:#2b7;color:#fff}
button:active{opacity:.7}.s{font-weight:bold}.dev{width:5.5rem}
small{color:#666}</style></head><body>
<h1>&#127793; Greenhouse</h1>
<div class=r>in <span id=temp>--</span>&deg;C <span id=humid>--</span>%</div>
<div class=r style="font-size:1.4rem;color:#557">out <span id=otemp>--</span>&deg;C <span id=ohumid>--</span>%</div>
<div class=row><span class=dev>Window: <span class=s id=window>?</span></span>
<button onclick="act('window')">Toggle</button></div>
<div class=row><span class=dev>Fans: <span class=s id=fans>?</span></span>
<button onclick="act('fans')">Toggle</button></div>
<div class=row><span class=dev>Mister: <span class=s id=mister>?</span></span>
<button onclick="act('mister')">Toggle</button></div>
<p><small id=t></small> &middot; <a href="/data.csv">samples.csv</a> &middot;
<a href="/events.csv">events.csv</a></p>
<script>
function n(v,d){return v==null?'--':v.toFixed(d)}
function paint(s){temp.textContent=n(s.temp,1);humid.textContent=n(s.humid,0);
otemp.textContent=n(s.out_temp,1);ohumid.textContent=n(s.out_humid,0);
window.textContent=s.window;fans.textContent=s.fans?'ON':'off';
mister.textContent=s.mister?'ON':'off';
t.textContent='updated '+new Date().toLocaleTimeString();}
function refresh(){fetch('/status').then(r=>r.json()).then(paint)}
function act(d){fetch('/'+d,{method:'POST'}).then(r=>r.json()).then(paint)}
refresh();setInterval(refresh,3000);
</script></body></html>"""
