"""
Web application logic — PURE request routing, no sockets. Host-tested.

route(method, path, actions) -> (status, content_type, body_str)

  GET  /            -> HTML control page
  GET  /status      -> JSON status dict (readings, per-actuator modes, states)
  GET  /data        -> JSON datalog snapshot
  GET  /data.csv    -> samples CSV        GET /events.csv -> events CSV
  POST /window      -> cycle window mode  (or ?a=AUTO|OFF|OPN|CLS)
  POST /fans        -> cycle fans mode    (or ?a=AUTO|OFF|VNT|CIR|ALL)
  POST /mister      -> cycle mister mode  (or ?a=AUTO|OFF|ON|TIM)
  POST /auto        -> toggle automation master (or ?a=on|off)
  GET  /settings    -> JSON specs+values of the web-adjustable tuning settings
  POST /settings    -> update settings (?key=value&... ) -> fresh specs + applied

`actions` is an object the caller supplies exposing:
    status()  -> dict
    snapshot()-> dict (datalog)
    window(a) / fans(a) / mister(a) / auto(a)  -> perform + return new status dict
    get_settings() / set_settings(dict)        -> settings specs / apply + persist
The socket layer (webserver.py) wires a real controller to this.
"""

try:
    import ujson as json
except ImportError:
    import json


def _unquote(s):
    """Minimal percent/plus decode for query values (MicroPython has no urllib). Today's
    values are plain numbers and F/C, but a future setting whose value carries a space,
    '%', '&' or '+' would otherwise arrive corrupted or split the pair."""
    if "%" not in s and "+" not in s:
        return s
    s = s.replace("+", " ")
    out = []
    i, n = 0, len(s)
    while i < n:
        if s[i] == "%" and i + 2 < n:
            try:
                out.append(chr(int(s[i + 1 : i + 3], 16)))
                i += 3
                continue
            except ValueError:
                pass
        out.append(s[i])
        i += 1
    return "".join(out)


def _qs(path):
    """Split 'p?a=b&c=d' -> ('p', {'a':'b','c':'d'}), percent-decoding values."""
    if "?" not in path:
        return path, {}
    p, q = path.split("?", 1)
    params = {}
    for pair in q.split("&"):
        if "=" in pair:
            k, v = pair.split("=", 1)
            params[_unquote(k)] = _unquote(v)
        elif pair:
            params[_unquote(pair)] = ""
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
            cols = (
                "t",
                "in_t",
                "in_h",
                "out_t",
                "out_h",
                "vent",
                "circ",
                "mist",
                "win",
            )
        else:
            rows = snap["events"]
            cols = ("t", "src", "dev", "act", "in_t", "in_h", "out_t", "out_h")
        return 200, "text/csv", _to_csv(rows, cols)

    if method == "POST" and p == "/auto":
        # toggle automation master, or ?a=on|off
        a = params.get("a")
        return 200, "application/json", json.dumps(actions.auto(a))

    if method == "GET" and p == "/settings":
        return 200, "application/json", json.dumps(actions.get_settings())

    if method == "POST" and p == "/settings":
        # query params carry key=value pairs to update (same convention as the mode
        # buttons — webserver.py doesn't parse request bodies)
        return 200, "application/json", json.dumps(actions.set_settings(params))

    if method == "POST" and p in ("/window", "/fans", "/mister"):
        device = p[1:]
        a = params.get("a")  # optional explicit MODE; None = cycle to next mode
        new_status = getattr(actions, device)(a)
        return 200, "application/json", json.dumps(new_status)

    return 404, "text/plain", "not found"


def _to_csv(rows, cols):
    out = [",".join(cols)]
    for r in rows:
        out.append(",".join("" if r.get(c) is None else str(r.get(c)) for c in cols))
    return "\n".join(out) + "\n"


# Single-file page: readings + per-actuator mode selectors, POST then refresh.
PAGE = """<!DOCTYPE html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Greenhouse</title><style>
body{font-family:sans-serif;max-width:640px;margin:20px auto;padding:0 12px;color:#222}
h1{font-size:1.3rem}.r{font-size:2rem;margin:6px 0}
.row{display:flex;gap:8px;align-items:center;margin:8px 0}
.dev{width:5.5rem}.grp{margin:10px 0;border:1px solid #eee;border-radius:8px;padding:8px}
.hd{font-size:.95rem;margin-bottom:6px}.hd .s{font-weight:bold}
.modes{display:flex;gap:6px}
.modes button,#auto{flex:1;padding:10px;font-size:.95rem;border:0;border-radius:8px;background:#dde;color:#334}
.modes button.on{background:#2b7;color:#fff}
#auto{background:#888;color:#fff}#auto.on{background:#e67}
small{color:#666}canvas{width:100%;height:280px;border:1px solid #ddd;border-radius:6px}
.lg{display:flex;flex-wrap:wrap;gap:10px;font-size:.8rem;margin:6px 0}
.lg span{display:inline-flex;align-items:center;gap:4px}
.sw{width:12px;height:12px;border-radius:2px;display:inline-block}
details{margin:12px 0;border:1px solid #eee;border-radius:8px;padding:6px 10px}
summary{cursor:pointer;font-weight:bold}
.sg{font-weight:bold;margin:10px 0 4px;color:#557}
.srow{display:flex;justify-content:space-between;align-items:center;gap:8px;margin:3px 0}
.sin{width:6.5rem;padding:4px}
#save{margin-top:8px;padding:8px 14px;border:0;border-radius:8px;background:#2b7;color:#fff}
</style></head><body>
<h1>&#127793; Greenhouse</h1>
<div class=r>in <span id=temp>--</span>&deg;<span class=u>C</span> <span id=humid>--</span>%</div>
<div class=r style="font-size:1.3rem;color:#557">out <span id=otemp>--</span>&deg;<span class=u>C</span> <span id=ohumid>--</span>%</div>
<div class=row><span class=dev>Automation:</span>
<button id=auto onclick="toggleAuto()">?</button></div>
<div class=grp><div class=hd>Window &middot; <span class=s id=win_mode>?</span>
<small id=winpos></small></div><div class=modes id=window></div></div>
<div class=grp><div class=hd>Fans &middot; <span class=s id=fan_mode>?</span>
<small id=fanstate></small></div><div class=modes id=fans></div></div>
<div class=grp><div class=hd>Mister &middot; <span class=s id=mis_mode>?</span>
<small id=misstate></small></div><div class=modes id=mister></div></div>
<canvas id=chart></canvas>
<div class=lg>
<span><i class=sw style=background:#d33></i>temp in</span>
<span><i class=sw style=background:#f99></i>temp out</span>
<span><i class=sw style=background:#36c></i>humid in</span>
<span><i class=sw style=background:#9cf></i>humid out</span>
<span><i class=sw style=background:#3a7></i>vent</span>
<span><i class=sw style=background:#2a9></i>circ</span>
<span><i class=sw style=background:#7ad></i>window</span>
<span><i class=sw style=background:#48c></i>mister</span>
</div>
<p><small id=t></small> &middot; <a href="/data.csv">samples.csv</a> &middot;
<a href="/events.csv">events.csv</a></p>
<details id=setwrap><summary>&#9881; Settings</summary>
<div id=settings><small>&hellip;</small></div>
<button id=save onclick=saveSettings()>Save</button>
<small id=savemsg></small></details>
<script>
function $(id){return document.getElementById(id)}
function n(v,d){return v==null?'--':v.toFixed(d)}
var UNIT='C';
var MODES={window:['AUTO','OFF','OPN','CLS'],
           fans:['AUTO','OFF','VNT','CIR','ALL'],
           mister:['AUTO','OFF','ON','TIM']};
function buildModes(){Object.keys(MODES).forEach(function(dev){var c=$(dev);
 MODES[dev].forEach(function(m){var b=document.createElement('button');
  b.textContent=m;b.onclick=function(){setMode(dev,m)};c.appendChild(b);});});}
function hl(dev,mode){[].forEach.call($(dev).children,function(b){
 b.className=(b.textContent==mode)?'on':'';});}
function cvt(c){return (c==null)?null:(UNIT=='F'?c*9/5+32:c);}  // C -> display unit
function paint(s){UNIT=s.unit||'C';
[].forEach.call(document.getElementsByClassName('u'),function(e){e.textContent=UNIT;});
$('temp').textContent=n(cvt(s.temp),1);$('humid').textContent=n(s.humid,0);
$('otemp').textContent=n(cvt(s.out_temp),1);$('ohumid').textContent=n(s.out_humid,0);
$('win_mode').textContent=s.win_mode;hl('window',s.win_mode);
$('winpos').textContent='('+s.window+')';
$('fan_mode').textContent=s.fan_mode;hl('fans',s.fan_mode);
$('fanstate').textContent=((s.vent?'vent ':'')+(s.circ?'circ':'')).trim()||'off';
$('mis_mode').textContent=s.mis_mode;hl('mister',s.mis_mode);
$('misstate').textContent=s.mister?('ON'+(s.mis_left!=null?' '+s.mis_left+'m':'')):'off';
var a=$('auto');a.textContent=s.auto?'ON (auto)':'OFF (manual)';
a.className=s.auto?'on':'';
$('t').textContent='updated '+new Date().toLocaleTimeString();}
function refresh(){fetch('/status').then(r=>r.json()).then(paint)}
function setMode(d,m){fetch('/'+d+'?a='+m,{method:'POST'}).then(r=>r.json()).then(paint)}
function toggleAuto(){fetch('/auto',{method:'POST'}).then(r=>r.json()).then(paint)}

function drawChart(samples){
 var c=document.getElementById('chart'),dpr=devicePixelRatio||1;
 var W=c.clientWidth,H=c.clientHeight;c.width=W*dpr;c.height=H*dpr;
 var x=c.getContext('2d');x.scale(dpr,dpr);x.clearRect(0,0,W,H);
 if(!samples.length){x.fillStyle='#999';x.fillText('no data yet',10,20);return;}
 var padL=32,padR=32,padT=8,barH=8,gap=2;
 var bars=4,barsH=bars*(barH+gap);
 var plotB=H-padT-barsH-14,plotT=padT;
 var t0=samples[0].t,t1=samples[samples.length-1].t||t0+1;
 var tw=(t1-t0)||1;
 function X(t){return padL+(t-t0)/tw*(W-padL-padR);}
 var tLo=cvt(0),tHi=cvt(40);
 function YT(v){return plotB-((cvt(v)-tLo)/(tHi-tLo))*(plotB-plotT);}
 function YH(v){return plotB-(v/100)*(plotB-plotT);}
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
 var rows=[['vent','#3a7'],['circ','#2a9'],['win','#7ad'],['mist','#48c']];
 for(var r=0;r<rows.length;r++){var by=plotB+14+r*(barH+gap);x.fillStyle=rows[r][1];
  for(var i=0;i<samples.length;i++){if(samples[i][rows[r][0]]){var x0=X(samples[i].t);
   var x1=i+1<samples.length?X(samples[i+1].t):x0+2;x.fillRect(x0,by,Math.max(1,x1-x0),barH);}}}
}
function refreshChart(){fetch('/data').then(r=>r.json()).then(d=>drawChart(d.samples||[]))}

function renderSettings(d){var host=$('settings');host.innerHTML='';var grp='';
 (d.specs||[]).forEach(function(s){
  if(s.group!=grp){grp=s.group;var h=document.createElement('div');
   h.className='sg';h.textContent=grp;host.appendChild(h);}
  var row=document.createElement('label');row.className='srow';
  var nm=document.createElement('span');nm.textContent=s.label;row.appendChild(nm);
  var inp;
  if(s.type=='choice'){inp=document.createElement('select');
   s.choices.forEach(function(c){var o=document.createElement('option');
    o.value=o.textContent=c;if(c==s.value)o.selected=true;inp.appendChild(o);});}
  else{inp=document.createElement('input');inp.type='number';
   inp.min=s.min;inp.max=s.max;inp.step=s.step;inp.value=s.value;}
  inp.className='sin';inp.setAttribute('data-key',s.key);
  row.appendChild(inp);host.appendChild(row);});}
function loadSettings(){fetch('/settings').then(r=>r.json()).then(renderSettings)}
function saveSettings(){var q=[];
 [].forEach.call(document.getElementsByClassName('sin'),function(i){
  q.push(encodeURIComponent(i.getAttribute('data-key'))+'='+encodeURIComponent(i.value));});
 fetch('/settings?'+q.join('&'),{method:'POST'}).then(r=>r.json()).then(function(d){
  renderSettings(d);refresh();
  $('savemsg').textContent=' saved '+Object.keys(d.applied||{}).length+' at '
   +new Date().toLocaleTimeString();});}
$('setwrap').addEventListener('toggle',function(){if(this.open)loadSettings();});

buildModes();refresh();refreshChart();setInterval(refresh,3000);setInterval(refreshChart,15000);
addEventListener('resize',refreshChart);
</script></body></html>"""
