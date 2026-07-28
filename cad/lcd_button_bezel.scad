// ============================================================================
// Greenhouse controller — LCD + button mounting bezel
// ----------------------------------------------------------------------------
// A flat 3 mm acrylic panel that carries the I2C 1602 LCD and the three
// momentary push buttons (window / fans / mister).
//
// The acrylic is CLEAR, so the LCD sits BEHIND the panel and is read straight
// through it — no display window is cut. We only need:
//   * 4 mounting holes for the LCD (75 x 31 mm pattern, M2.5)
//   * 3 x 7 mm holes for the Twidec PBS-110 push buttons
//   * (optional) 4 corner holes to bolt the bezel to the box
//
// Parts this is dimensioned for:
//   LCD     : iUniker I2C 1602 (standard HD44780 module, 80 x 36 mm PCB,
//             mounting holes 75 x 31 mm c-c, ~2.9 mm dia -> M2.5)
//   Buttons : Twidec PBS-110, 7 mm panel mounting hole
//
// Built as a 2D profile that is linear_extrude()d. For laser cutting, render
// with LASER_2D = true (or projection(cut=false) the 3D body) and export DXF.
// ============================================================================

// ---- Panel -----------------------------------------------------------------
panel_w      = 180;   // panel width  (mm)
panel_h      = 100;   // panel height (mm)
panel_t      = 3;     // acrylic thickness (mm)
corner_r     = 4;     // rounded corner radius (0 = square corners)

// ---- LCD (iUniker / standard 1602) -----------------------------------------
lcd_hole_dx  = 75;    // mounting-hole spacing, horizontal, center-to-center
lcd_hole_dy  = 31;    // mounting-hole spacing, vertical,   center-to-center
lcd_hole_d   = 3.4;   // M3 clearance; >= 1/8" so ONE 1/8" bit bores it (no tool change)
lcd_cx       = panel_w / 2;   // LCD center X on the panel
lcd_cy       = 60;            // LCD center Y (upper third)

// Optional: actually cut a window through the acrylic for the LCD viewing area
// (NOT needed for clear acrylic — read through it). Off by default.
lcd_window       = true;
lcd_window_w     = 71.5;  // metal bezel opening of a 1602 is ~71 x 25 mm
lcd_window_h     = 25.5;
lcd_window_r     = 1.5;

// ---- Buttons (Twidec PBS-110, 7 mm) ----------------------------------------
btn_hole_d   = 7.0;   // 7 mm panel hole
btn_count    = 3;
btn_spacing  = 32;    // center-to-center between adjacent buttons
btn_cy       = 30;    // button row center Y (lower third)
btn_cx       = panel_w / 2;   // row is centered on the panel

// ---- Panel-to-box mounting holes (optional) --------------------------------
beam_w = 15;
panel_mounts   = true;
panel_mount_d  = 4.0;   // loose M3 clearance = alignment slop to the 1515 frame (also >= 1/8")
panel_mount_in = beam_w/2;     // inset from each edge to hole center

// ---- Rendering -------------------------------------------------------------
LASER_2D = true;   // true => emit the flat 2D cut profile (for DXF export)
$fn      = 64;

// ============================================================================

box_d = 100;

t1515_w = 15;
t1515_notch_w = 3;
t1515_notch_d = 5;
t1515_hole_ir = 3/2;

module t1515(length=100) {
    translate([0, 0, -length/2])
    linear_extrude(length) {
        difference() {
            square([t1515_w, t1515_w], center=true);
            for (i=[0:3]) {
                rotate([0, 0, 90 * i]) {
                    translate([t1515_w/2 - t1515_notch_d / 2, 0, 0]) {
                        square([t1515_notch_d, t1515_notch_w], center=true);
                    }
                }
            }
            circle(r=t1515_hole_ir, $fn=16);
        }
    }
}

module t1515_hole(length) {
    t1515(length);
    cube([t1515_w - 2, t1515_w - 2, length+1], center=true);
}


module frame() {
    for (z=[-beam_w/2, -beam_w - box_d]) {
        for (x=[beam_w/2, panel_w - beam_w/2]) {
            translate([x, panel_h/2, z]){
                rotate([90, 0, 0])
                    t1515(panel_h);
            }
        }

        for (y=[beam_w/2, panel_h - beam_w/2]) {
            translate([panel_w/2, y, z])
                rotate([0, 90, 0])
                t1515(panel_w - 2*beam_w);
        }
    }

    for (x=[beam_w/2, panel_w - beam_w/2], y=[beam_w/2, panel_h - beam_w/2]) {
        translate([x, y, -box_d/2 - beam_w])
            t1515(box_d);
    }
}

// ! frame();

// A rounded rectangle centered on the origin.
module rrect(w, h, r) {
    if (r > 0)
        offset(r) offset(-r) square([w, h], center = true);
    else
        square([w, h], center = true);
}

// Every hole in the panel, as 2D circles positioned in panel coordinates
// (origin at the panel's bottom-left corner).
module holes_2d() {
    // -- LCD 4 corner mounting holes --
    for (sx = [-1, 1], sy = [-1, 1])
        translate([lcd_cx + sx * lcd_hole_dx / 2,
                   lcd_cy + sy * lcd_hole_dy / 2])
            circle(d = lcd_hole_d);

    // -- 3 button holes, evenly spaced and centered on btn_cx --
    for (i = [0 : btn_count - 1])
        translate([btn_cx + (i - (btn_count - 1) / 2) * btn_spacing, btn_cy])
            circle(d = btn_hole_d);

    // -- optional LCD viewing window --
    if (lcd_window)
        translate([lcd_cx, lcd_cy])
            rrect(lcd_window_w, lcd_window_h, lcd_window_r);
    else
        % translate([lcd_cx, lcd_cy])
            linear_extrude(10, center=true)
            rrect(lcd_window_w, lcd_window_h, lcd_window_r);

    // -- optional panel-to-box corner mounts --
    if (panel_mounts) {
        for (x = [
                panel_mount_in,
                panel_mount_in + beam_w,
                panel_w/2,
                panel_w - panel_mount_in,
                panel_w - panel_mount_in - beam_w,
            ],
             y = [panel_mount_in, panel_h - panel_mount_in])
            translate([x, y]) circle(d = panel_mount_d);
        % frame();
    }
}

// The flat 2D cut profile: rounded outline minus all holes.
module bezel_2d() {
    difference() {
        translate([panel_w / 2, panel_h / 2])
            rrect(panel_w, panel_h, corner_r);
        holes_2d();
    }
}

// ============================================================================

if (LASER_2D)
    bezel_2d();
else
    linear_extrude(height = panel_t)
        bezel_2d();
