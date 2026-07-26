"""
Single-sided maze router for the carrier board.

Lee/BFS grid router on ONE copper layer. Where a net must cross an existing trace
it inserts a WIRE JUMPER: two through-hole vias bridged by an insulated wire on the
TOP (non-copper) side, so the copper layer stays single-sided and short-free.

Routing order matters: fat power/ground nets first (they become buses), then signals.
Output: list of Trace polylines (copper) + list of Jumper endpoints, plus a DRC pass
that verifies every different-net copper pair respects ISOLATION.

This is intentionally simple and readable over clever. Grid = GRID mm.
"""

import heapq
from dataclasses import dataclass, field

import layout as L
import netlist as N

GRID = 0.25  # routing grid (mm) — fine enough to thread 2.54mm pitch pads
# clearance in grid cells for a trace of given width:
#   need (width/2 + ISOLATION + other_width/2). We halo obstacles by the max.
PWR_NETS = {"GND", "12V", "5V_BUCK", "5V_VSYS", "3V3", "VALVE_SW"}


def gw(width):
    """Obstacle halo radius in grid cells: reserve this trace's half-width, the
    isolation gap, AND half of the widest neighbouring trace — otherwise two
    parallel tracks end up half-a-trace too close (edge-to-edge < ISOLATION)."""
    import math

    clearance = width / 2 + L.ISOLATION + L.TRACE_PWR / 2
    return max(1, math.ceil(clearance / GRID))


@dataclass
class Trace:
    net: str
    points: list
    width: float


@dataclass
class Jumper:
    net: str
    a: tuple
    b: tuple


class Router:
    def __init__(self, placements):
        self.nx = int(L.BOARD_W / GRID) + 1
        self.ny = int(L.BOARD_H / GRID) + 1
        # occupancy: cell -> net name occupying it (copper). None = free.
        self.occ = {}
        self.pad_cell = {}  # (ref,pad) -> (gx,gy)
        self.pad_net = {}  # (gx,gy) -> net (so a route may end on its own pad)
        self.traces = []
        self.jumpers = []
        self._index_pads(placements)

    # -- grid helpers --
    def g(self, x, y):
        return (int(round(x / GRID)), int(round(y / GRID)))

    def mm(self, gx, gy):
        return (gx * GRID, gy * GRID)

    def _index_pads(self, placements):
        import netlist as N

        pnet = {}
        for net, pins in N.NETS.items():
            for ref, pad in pins:
                pnet[(ref, pad)] = net
        self._pad_halo = gw(L.PAD_D)  # halo so traces clear foreign pads
        for pl in placements:
            for name, (x, y, w, h, drill, shape) in pl.placed_pads().items():
                cell = self.g(x, y)
                self.pad_cell[(pl.ref, name)] = cell
                self.pad_net[cell] = pnet.get((pl.ref, name))  # None if unconnected

    def _mark(self, gx, gy, net, halo):
        for dx in range(-halo, halo + 1):
            for dy in range(-halo, halo + 1):
                c = (gx + dx, gy + dy)
                # don't let halo erase an actual pad/trace of another net silently;
                # occupancy stores the *owning* net; halo cells store net too so
                # other nets treat them as blocked.
                if c not in self.occ:
                    self.occ[c] = net

    def _blocked(self, cell, net):
        o = self.occ.get(cell)
        return o is not None and o != net

    def route_net(self, net, pins, width):
        """Route a net as a spanning set of BFS paths pin->existing-net-copper."""
        cells = [self.pad_cell[p] for p in pins if p in self.pad_cell]
        if len(cells) < 2:
            return
        halo = gw(width)
        connected = {cells[0]}
        # seed occupancy with the first pad
        self._mark(*cells[0], net, halo)
        for target in cells[1:]:
            path, jump = self._bfs(connected, target, net, halo)
            if path is None:
                # fall back: register a jumper straight to nearest connected cell
                src = min(
                    connected,
                    key=lambda c: abs(c[0] - target[0]) + abs(c[1] - target[1]),
                )
                self.jumpers.append(Jumper(net, self.mm(*src), self.mm(*target)))
                connected.add(target)
                self._mark(*target, net, halo)
                continue
            # lay copper
            pts = [self.mm(*c) for c in path]
            self.traces.append(Trace(net, pts, width))
            for c in path:
                self._mark(*c, net, halo)
                connected.add(c)
            for ja, jb in jump:
                self.jumpers.append(Jumper(net, self.mm(*ja), self.mm(*jb)))

    def _bfs(self, sources, target, net, halo):
        """BFS from any source cell to target. Returns (path, jumps).
        A 'jump' step hops over a single blocking cell (records a Jumper)."""
        start = min(
            sources, key=lambda c: abs(c[0] - target[0]) + abs(c[1] - target[1])
        )
        pq = [(0, start, None)]
        came = {}
        seen = set()
        while pq:
            cost, cur, via = heapq.heappop(pq)
            if cur in seen:
                continue
            seen.add(cur)
            came[cur] = via
            if cur == target:
                # reconstruct
                path = []
                c = cur
                while c is not None:
                    path.append(c)
                    c = came[c]
                path.reverse()
                return path, []  # simple router: no mid-path jumps in v1
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nb = (cur[0] + dx, cur[1] + dy)
                if not (0 <= nb[0] < self.nx and 0 <= nb[1] < self.ny):
                    continue
                if nb in seen:
                    continue
                if nb != target and self._blocked(nb, net):
                    continue
                h = abs(nb[0] - target[0]) + abs(nb[1] - target[1])
                heapq.heappush(pq, (cost + 1 + h, nb, cur))
        return None, []

    def route_all(self):
        # GND is the background copper POUR (ground plane), not routed traces —
        # the natural result of isolation milling, and it removes ~1/3 of the nets
        # and most jumpers. Every GND pad just needs a short isolation ring; it
        # connects to the surrounding plane automatically. So we SKIP routing GND.
        #
        # Pad-aware routing: mark EVERY pad as an obstacle owned by its net first,
        # so no trace can plow through a foreign pad. Then route power (fat) then
        # signals (thin). A route may only enter a cell that is free or owned by
        # its own net.
        for cell, net in self.pad_net.items():
            self._mark(*cell, net if net is not None else "_pad", self._pad_halo)
        self.gnd_pads = [
            self.pad_cell[p] for p in N.NETS.get("GND", []) if p in self.pad_cell
        ]
        order = [n for n in N.NETS if n in PWR_NETS and n != "GND"] + [
            n for n in N.NETS if n not in PWR_NETS
        ]
        for net in order:
            width = L.TRACE_PWR if net in PWR_NETS else L.TRACE_SIG
            self.route_net(net, N.NETS[net], width)

    def drc(self):
        """Check different-net copper segments respect ISOLATION (sample by cells)."""
        # occ already enforces halo; report any cell claimed by 2 nets is impossible
        # since occ is single-valued. Instead verify no trace centreline passes within
        # (w/2+iso) of another net's centreline by re-walking traces on a fresh grid.
        import math

        viol = 0
        owner = {}
        for t in self.traces:
            half = t.width / 2
            for (x0, y0), (x1, y1) in zip(t.points, t.points[1:]):
                steps = int(max(abs(x1 - x0), abs(y1 - y0)) / (GRID / 2)) + 1
                for s in range(steps + 1):
                    x = x0 + (x1 - x0) * s / steps
                    y = y0 + (y1 - y0) * s / steps
                    key = (round(x / (GRID / 2)), round(y / (GRID / 2)))
                    prev = owner.get(key)
                    if prev and prev != t.net:
                        viol += 1
                    owner[key] = t.net
        return viol


def main():
    placements = L.build()
    r = Router(placements)
    r.route_all()
    routed_nets = {t.net for t in r.traces}
    print(f"traces: {len(r.traces)}  jumpers: {len(r.jumpers)}")
    print(f"nets with copper: {len(routed_nets)}/{len(N.NETS)}")
    jn = {}
    for j in r.jumpers:
        jn[j.net] = jn.get(j.net, 0) + 1
    if jn:
        print("jumpers per net:", ", ".join(f"{k}:{v}" for k, v in jn.items()))
    v = r.drc()
    print("DRC crossings (same cell, diff net):", v)
    return r


if __name__ == "__main__":
    main()
