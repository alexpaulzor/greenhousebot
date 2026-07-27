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
            cols = ("t", "in_t", "in_h", "out_t", "out_h", "fans", "mist", "win")
        else:
            rows = snap["events"]
            cols = ("t", "src", "dev", "act", "in_t", "in_h", "out_t", "out_h")
        return 200, "text/csv", _to_csv(rows, cols)

    if method == "POST" and p == "/auto":
        # toggle automation, or ?a=on|off
        a = params.get("a")
        return 200, "application/json", json.dumps(actions.auto(a))

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
body{font-family:sans-serif;max-width:640px;margin:20px auto;padding:0 12px;color:#222}
h1{font-size:1.3rem}.r{font-size:2rem;margin:6px 0}
.row{display:flex;gap:8px;align-items:center;margin:8px 0}
button{flex:1;padding:12px;font-size:1rem;border:0;border-radius:8px;background:#2b7;color:#fff}
button:active{opacity:.7}.s{font-weight:bold}.dev{width:5.5rem}
#auto{background:#888}#auto.on{background:#e67}
small{color:#666}canvas{width:100%;height:260px;border:1px solid #ddd;border-radius:6px}
.lg{display:flex;flex-wrap:wrap;gap:10px;font-size:.8rem;margin:6px 0}
.lg span{display:inline-flex;align-items:center;gap:4px}
.sw{width:12px;height:12px;border-radius:2px;display:inline-block}</style></head><body>
<h1>&#127793; Greenhouse</h1>
<div class=r>in <span id=temp>--</span>&deg;<span class=u>C</span> <span id=humid>--</span>%</div>
<div class=r style="font-size:1.3rem;color:#557">out <span id=otemp>--</span>&deg;<span class=u>C</span> <span id=ohumid>--</span>%</div>
<div class=row><span class=dev>Automation:</span>
<button id=auto onclick="toggleAuto()">?</button></div>
<div class=row><span class=dev>Window: <span class=s id=window>?</span></span>
<button onclick="act('window')">Toggle</button></div>
<div class=row><span class=dev>Fans: <span class=s id=fans>?</span></span>
<button onclick="act('fans')">Toggle</button></div>
<div class=row><span class=dev>Mister: <span class=s id=mister>?</span></span>
<button onclick="act('mister')">Toggle</button></div>
<canvas id=chart></canvas>
<div class=lg>
<span><i class=sw style=background:#d33></i>temp in</span>
<span><i class=sw style=background:#f99></i>temp out</span>
<span><i class=sw style=background:#36c></i>humid in</span>
<span><i class=sw style=background:#9cf></i>humid out</span>
<span><i class=sw style=background:#3a7></i>fan</span>
<span><i class=sw style=background:#7ad></i>window</span>
<span><i class=sw style=background:#48c></i>mister</span>
</div>
<p><small id=t></small> &middot; <a href="/data.csv">samples.csv</a> &middot;
<a href="/events.csv">events.csv</a></p>
<script>
function $(id){return document.getElementById(id)}
function n(v,d){return v==null?'--':v.toFixed(d)}
var UNIT='C';
function cvt(c){return (c==null)?null:(UNIT=='F'?c*9/5+32:c);}  // C -> display unit
function paint(s){UNIT=s.unit||'C';
[].forEach.call(document.getElementsByClassName('u'),function(e){e.textContent=UNIT;});
$('temp').textContent=n(cvt(s.temp),1);$('humid').textContent=n(s.humid,0);
$('otemp').textContent=n(cvt(s.out_temp),1);$('ohumid').textContent=n(s.out_humid,0);
$('window').textContent=s.window;$('fans').textContent=s.fans?'ON':'off';
$('mister').textContent=s.mister?'ON':'off';
var a=$('auto');a.textContent=s.auto?'ON (auto)':'OFF (manual)';
a.className=s.auto?'on':'';
$('t').textContent='updated '+new Date().toLocaleTimeString();}
function refresh(){fetch('/status').then(r=>r.json()).then(paint)}
function act(d){fetch('/'+d,{method:'POST'}).then(r=>r.json()).then(paint)}
function toggleAuto(){fetch('/auto',{method:'POST'}).then(r=>r.json()).then(paint)}

function drawChart(samples){
 var c=document.getElementById('chart'),dpr=devicePixelRatio||1;
 var W=c.clientWidth,H=c.clientHeight;c.width=W*dpr;c.height=H*dpr;
 var x=c.getContext('2d');x.scale(dpr,dpr);x.clearRect(0,0,W,H);
 if(!samples.length){x.fillStyle='#999';x.fillText('no data yet',10,20);return;}
 var padL=32,padR=32,padT=8,barH=8,gap=2;
 var bars=3,barsH=bars*(barH+gap);
 var plotB=H-padT-barsH-14,plotT=padT;
 var t0=samples[0].t,t1=samples[samples.length-1].t||t0+1;
 var tw=(t1-t0)||1;
 function X(t){return padL+(t-t0)/tw*(W-padL-padR);}
 // temp axis in display unit (data is Celsius); humidity 0..100 on right.
 // C: 0..40 ; F: 32..104 (= cvt(0)..cvt(40)). 5 gridlines either way.
 var tLo=cvt(0),tHi=cvt(40);
 function YT(v){return plotB-((cvt(v)-tLo)/(tHi-tLo))*(plotB-plotT);}
 function YH(v){return plotB-(v/100)*(plotB-plotT);}
 // gridlines
 x.strokeStyle='#eee';x.fillStyle='#999';x.font='10px sans-serif';
 for(var k=0;k<=4;k++){var cV=k*10,y=YT(cV);
  x.strokeStyle='#eee';x.beginPath();x.moveTo(padL,y);x.lineTo(W-padR,y);x.stroke();
  x.fillStyle='#d33';x.fillText(Math.round(cvt(cV)),2,y+3);
  x.fillStyle='#36c';x.fillText((k*25),W-padR+3,y+3);}
 function line(key,Y,color){x.strokeStyle=color;x.lineWidth=1.5;x.beginPath();var started=false;
  for(var i=0;i<samples.length;i++){var v=samples[i][key];if(v==null){started=false;continue;}
   var px=X(samples[i].t),py=Y(v);if(!started){x.moveTo(px,py);started=true;}else x.lineTo(px,py);}
  x.stroke();}
 line('in_t',YT,'#d33');line('out_t',YT,'#f99');
 line('in_h',YH,'#36c');line('out_h',YH,'#9cf');
 // state bars (fan, window, mister) beneath the plot
 var rows=[['fans','#3a7'],['win','#7ad'],['mist','#48c']];
 for(var r=0;r<rows.length;r++){var by=plotB+14+r*(barH+gap);x.fillStyle=rows[r][1];
  for(var i=0;i<samples.length;i++){if(samples[i][rows[r][0]]){var x0=X(samples[i].t);
   var x1=i+1<samples.length?X(samples[i+1].t):x0+2;x.fillRect(x0,by,Math.max(1,x1-x0),barH);}}}
}
function refreshChart(){fetch('/data').then(r=>r.json()).then(d=>drawChart(d.samples||[]))}
refresh();refreshChart();setInterval(refresh,3000);setInterval(refreshChart,15000);
addEventListener('resize',refreshChart);
</script></body></html>"""
