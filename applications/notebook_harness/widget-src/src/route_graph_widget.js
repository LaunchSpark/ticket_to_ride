// Forked from https://github.com/koaning/graph_widget (anywidget wrapper around
// vasturiano/force-graph), vendored and bundled locally (no runtime CDN imports)
// so bot notebooks work fully offline. Changes from upstream:
//   - link distance is a spring proportional to each edge's route length
//     (link_distance_base + link_distance_scale * link.data.length), instead
//     of force-graph's fixed default link distance
//   - repulsion and link-distance forces are applied on initial render, not
//     only in reaction to a later trait change (upstream only wires the
//     `change:repulsion` event, so the constructor's initial value is never
//     actually applied until something changes it)
//   - link color/width are read directly from each edge's own color/width
//     fields, so callers don't need a colour_feature/node_size_feature dance
//     for edges
//   - links are painted as Ticket to Ride routes: each edge's data.length
//     determines how many rectangular "train spaces" are drawn along it
//     (rotated to the edge direction, following the same bezier as curved
//     parallel edges), on top of a thin default line kept as a roadbed. A
//     claimed route keeps its base color and gets an inset rectangle in the
//     owner's color inside each space, so the route color stays visible
//     around the claim marker (and a black player's claim reads differently
//     from a black route)
import ForceGraph from "force-graph";
import { select } from "d3-selection";
import { extent, min, max } from "d3-array";
import { brush } from "d3-brush";
import { drag as node_drag } from "d3-drag";
import { forceManyBody, forceLink } from "d3-force";
import { scaleLinear, scaleOrdinal, scaleIdentity } from "d3-scale";
import { schemeCategory10 } from "d3-scale-chromatic";
import RBush from "rbush";

let default_width = 800;
let default_height = 500;
let default_repulsion = 80;
let default_link_distance_base = 30;
let default_link_distance_scale = 15;
let default_node_scale = 3;

// Train-space (route rectangle) geometry, in graph units.
let train_space_width = 6;
// Fraction of each slot the rectangle fills; the rest is the gap between spaces.
let train_space_fill = 0.72;
// Unclaimed routes recede slightly so claimed routes remain visually primary.
let default_unclaimed_route_opacity = 0.5;
// Claim-marker inset on every side, as a fraction of the space width, so the
// route's base color pokes out around the owner's color.
let claim_inset_fraction = 0.25;
// Opacity of the full-width band stroked under a claimed route's train
// spaces, in the owner's color, replacing the thin roadbed line.
let claim_band_alpha = 0.45;

class MyRBush extends RBush {
    toBBox(node) { return { id: node.id, minX: node.x, minY: node.y, maxX: node.x, maxY: node.y }; }
    compareMinX(a, b) { return a.x - b.x; }
    compareMinY(a, b) { return a.y - b.y; }
}

let default_node_size = 5;

function debounce(func, wait) {
    let timeout;
    return function (...args) {
        clearTimeout(timeout);
        timeout = setTimeout(() => func.apply(this, args), wait);
    };
}

const get_feature_type = (value) => {
    if (typeof value === "number") return "numeric";
    if (typeof value === "string" && value.startsWith("#")) return "hash_string";
    return "categorical";
};

const ua = navigator.userAgent.toLowerCase();
const isMac = ua.includes("macintosh");

// Train spaces get an outline contrasting their own fill (not the page
// background), so dark spaces stay visible on dark themes and light spaces
// on light themes without the painter knowing the notebook's theme at all.
const is_dark_color = (color) => {
    const hex = /^#?([0-9a-f]{6})$/i.exec(color || "");
    if (!hex) return false;
    const value = parseInt(hex[1], 16);
    const r = (value >> 16) & 255;
    const g = (value >> 8) & 255;
    const b = value & 255;
    return (r * 299 + g * 587 + b * 114) / 1000 < 90;
};

const color_with_alpha = (color, alpha) => {
    const hex = /^#?([0-9a-f]{6})$/i.exec(color || "");
    if (!hex) return color;
    const value = parseInt(hex[1], 16);
    return `rgba(${(value >> 16) & 255},${(value >> 8) & 255},${value & 255},${alpha})`;
};

// Quadratic bezier helpers matching force-graph's own curved-link geometry
// (it stores the single control point in link.__controlPoints).
const bezier_point = (t, p0, cp, p1) => {
    const u = 1 - t;
    return {
        x: u * u * p0.x + 2 * u * t * cp.x + t * t * p1.x,
        y: u * u * p0.y + 2 * u * t * cp.y + t * t * p1.y,
    };
};

const bezier_tangent = (t, p0, cp, p1) => ({
    x: 2 * (1 - t) * (cp.x - p0.x) + 2 * t * (p1.x - cp.x),
    y: 2 * (1 - t) * (cp.y - p0.y) + 2 * t * (p1.y - cp.y),
});

function link_distance_for(model, link) {
    const base = model.get("link_distance_base") ?? default_link_distance_base;
    const scale = model.get("link_distance_scale") ?? default_link_distance_scale;
    const routeLength = (link.data && typeof link.data.length === "number") ? link.data.length : 1;
    return base + scale * routeLength;
}

function render({ model, el }) {
    const debouncedSaveChanges = debounce(() => model.save_changes(), 300);
    const normalized_opacity = (value) => Math.min(1, Math.max(0, Number(value)));
    let local_selected_ids = [];
    let colour_scale_type = "";
    let plot;
    let tree;
    let colour_feature;
    let node_size_feature;
    let colour_scale;
    let select_feature;
    let select_feature_value;

    const create_rtree = (nodes) => {
        tree = new MyRBush();
        tree.load(nodes);
    };

    const create_node_canvas_object = (graph, scale, size_feature) => {
        return graph.nodeCanvasObject((node, ctx) => {
            const radius = size_feature == undefined || size_feature == ""
                ? default_node_size * scale
                : node[size_feature] * scale;
            const isLocalSelected = local_selected_ids.includes(node.id);
            const hasSelection = local_selected_ids.length > 0;
            const fillColour = colour_scale ? colour_scale(node[colour_feature]) : "#4a4a4a";

            ctx.globalAlpha = hasSelection && !isLocalSelected ? 0.2 : 1.0;
            ctx.beginPath();
            ctx.arc(node.x, node.y, radius, 0, 2 * Math.PI, false);
            ctx.fillStyle = fillColour;
            ctx.fill();
            ctx.lineWidth = isLocalSelected ? radius / 5 : radius / 10;
            ctx.strokeStyle = isLocalSelected ? "red" : "lightgrey";
            ctx.stroke();
            ctx.globalAlpha = 1.0;
        });
    };

    let unclaimed_route_opacity = normalized_opacity(
        model.get("unclaimed_route_opacity") ?? default_unclaimed_route_opacity
    );
    const route_opacity = (link) => Number.isFinite(Number(link.opacity))
        ? normalized_opacity(link.opacity)
        : (link.claimedColor ? 1 : unclaimed_route_opacity);

    const node_radius = (node) => {
        if (node_size_feature == undefined || node_size_feature == "") {
            return default_node_size * node_scale;
        }
        return node[node_size_feature] * node_scale;
    };

    // Paints one link as its route's train spaces: data.length rectangles
    // evenly spaced between the two city circles, each rotated to the local
    // edge direction. Runs in "after" mode, so force-graph's default thin
    // line stays underneath as a roadbed. Reuses link.__controlPoints (the
    // bezier control point force-graph computes for every visible link right
    // before custom paints) so spaces follow the exact same bow as curved
    // parallel edges.
    const paint_train_spaces = (link, ctx) => {
        const start = link.source;
        const end = link.target;
        if (!start || !end || typeof start.x !== "number" || typeof end.x !== "number") return;

        const controlPoints = link.__controlPoints;
        if (controlPoints && controlPoints.length !== 2) return; // self-loop, nowhere sensible to put spaces
        const cp = controlPoints ? { x: controlPoints[0], y: controlPoints[1] } : null;

        const chord = Math.hypot(end.x - start.x, end.y - start.y);
        if (chord === 0) return;

        const point = cp
            ? (t) => bezier_point(t, start, cp, end)
            : (t) => ({ x: start.x + (end.x - start.x) * t, y: start.y + (end.y - start.y) * t });
        const tangent = cp
            ? (t) => bezier_tangent(t, start, cp, end)
            : () => ({ x: end.x - start.x, y: end.y - start.y });

        // Keep the spaces between the city circles, not underneath them.
        const tMin = Math.min(node_radius(start) / chord, 0.35);
        const tMax = 1 - Math.min(node_radius(end) / chord, 0.35);

        const routeLength = link.data && Number.isFinite(link.data.length) ? link.data.length : 1;
        const spaces = Math.max(1, Math.round(routeLength));

        // Claimed routes get a translucent full-width band in the owner's
        // color under the train spaces (the thin roadbed line is hidden for
        // claimed links via the linkColor accessor), stroked along the same
        // straight/bezier path the default line would follow. The width is
        // in graph units so it stays flush with the rectangles at any zoom -
        // the default line couldn't do this, since linkWidth is screen-px.
        if (link.claimedColor) {
            ctx.save();
            ctx.globalAlpha = claim_band_alpha;
            ctx.strokeStyle = link.claimedColor;
            ctx.lineWidth = train_space_width;
            ctx.beginPath();
            ctx.moveTo(start.x, start.y);
            if (cp) {
                ctx.quadraticCurveTo(cp.x, cp.y, end.x, end.y);
            } else {
                ctx.lineTo(end.x, end.y);
            }
            ctx.stroke();
            ctx.restore();
        }

        const baseColor = link.color || "#999999";
        const segments = (link.data && Array.isArray(link.data.segments))
            ? link.data.segments : null;
        for (let i = 0; i < spaces; i++) {
            const t0 = tMin + ((tMax - tMin) * i) / spaces;
            const t1 = tMin + ((tMax - tMin) * (i + 1)) / spaces;
            const tCenter = (t0 + t1) / 2;

            const slotStart = point(t0);
            const slotEnd = point(t1);
            const center = point(tCenter);
            const direction = tangent(tCenter);

            const slotLength = Math.hypot(slotEnd.x - slotStart.x, slotEnd.y - slotStart.y);
            const carLength = slotLength * train_space_fill;
            if (carLength <= 0) continue;

            ctx.save();
            ctx.globalAlpha = route_opacity(link);
            ctx.translate(center.x, center.y);
            ctx.rotate(Math.atan2(direction.y, direction.x));

            const seg = (segments && segments[i])
                ? segments[i]
                : { kind: "solid", colors: [baseColor] };
            const x0 = -carLength / 2;
            const y0 = -train_space_width / 2;
            if (seg.kind === "loco") {
                const grad = ctx.createLinearGradient(x0, 0, x0 + carLength, 0);
                const stops = seg.colors && seg.colors.length ? seg.colors : ["#999"];
                stops.forEach((color, index) => grad.addColorStop(
                    stops.length === 1 ? 0 : index / (stops.length - 1), color));
                ctx.fillStyle = grad;
                ctx.fillRect(x0, y0, carLength, train_space_width);
            } else if (seg.colors && seg.colors.length > 1) {
                const colorCount = seg.colors.length;
                ctx.save();
                ctx.beginPath();
                ctx.rect(x0, y0, carLength, train_space_width);
                ctx.clip();
                for (let colorIndex = 0; colorIndex < colorCount; colorIndex++) {
                    const f0 = colorIndex / colorCount;
                    const f1 = (colorIndex + 1) / colorCount;
                    ctx.fillStyle = seg.colors[colorIndex];
                    ctx.beginPath();
                    ctx.moveTo(x0 + 2 * f0 * carLength, y0);
                    ctx.lineTo(x0, y0 + 2 * f0 * train_space_width);
                    ctx.lineTo(x0, y0 + 2 * f1 * train_space_width);
                    ctx.lineTo(x0 + 2 * f1 * carLength, y0);
                    ctx.closePath();
                    ctx.fill();
                }
                ctx.restore();
            } else {
                ctx.fillStyle = (seg.colors && seg.colors[0]) || baseColor;
                ctx.fillRect(x0, y0, carLength, train_space_width);
            }
            ctx.lineWidth = 0.6;
            ctx.strokeStyle = is_dark_color(baseColor) ? "rgba(255,255,255,0.5)" : "rgba(0,0,0,0.4)";
            ctx.strokeRect(-carLength / 2, -train_space_width / 2, carLength, train_space_width);

            if (link.claimedColor) {
                const inset = train_space_width * claim_inset_fraction;
                const innerLength = carLength - 2 * inset;
                const innerWidth = train_space_width - 2 * inset;
                if (innerLength > 0 && innerWidth > 0) {
                    ctx.fillStyle = link.claimedColor;
                    ctx.fillRect(-innerLength / 2, -innerWidth / 2, innerLength, innerWidth);
                    // Light outline so the claim still reads when the owner's
                    // color matches the route color (black on black).
                    ctx.lineWidth = 0.5;
                    ctx.strokeStyle = "rgba(255,255,255,0.75)";
                    ctx.strokeRect(-innerLength / 2, -innerWidth / 2, innerLength, innerWidth);
                }
            }

            ctx.restore();
        }
    };

    const create_plot = (data) => {
        return ForceGraph()(el)
            .width(width)
            .height(height)
            .graphData(data)
            // Hover, tooltips and node dragging are implemented below from
            // node/route coordinates - the same always-current data the
            // brush selection uses - instead of force-graph's hidden
            // hit-testing canvas (a pixel/color-registry pipeline that
            // proved fragile across long notebook sessions). Disabling the
            // built-in pointer interaction turns all of it off.
            .enablePointerInteraction(false)
            .enableNodeDrag(false)
            .cooldownTime(5000)
            .warmupTicks(10)
            // Claimed links hide the default line entirely; paint_train_spaces
            // strokes a full-width claim band in its place.
            .linkColor((link) => link.claimedColor
                ? "rgba(0,0,0,0)"
                : color_with_alpha(link.color || "#999999", route_opacity(link)))
            // Thin roadbed only - the visible route body is the train spaces
            // painted on top in "after" mode.
            .linkWidth(() => 1)
            .linkCanvasObjectMode(() => "after")
            .linkCanvasObject(paint_train_spaces)
            .linkCurvature((link) => link.curvature || 0)
            .d3AlphaDecay(0.001)
            .minZoom(0.001)
            .nodeCanvasObjectMode(() => "replace")
            // Repaint every frame regardless of engine state, so board
            // updates always show immediately even when the layout is idle.
            .autoPauseRedraw(false)
            .onEngineTick(() => {
                simulation_running = true;
            })
            .onEngineStop(() => {
                simulation_running = false;
                // Fit only after an initial or topology-change settle - the
                // engine also stops after drag cooldowns, which must not
                // re-zoom.
                if (zoom_to_fit_pending) {
                    zoom_to_fit_pending = false;
                    plot.zoomToFit(400);
                }
                create_rtree(data["nodes"]);
            });
    };

    const idSet = (items) => new Set(items.map((item) => item.id));
    const idSetsEqual = (a, b) => a.size === b.size && [...a].every((id) => b.has(id));

    let data = model.get("data");
    // ForceGraph's graphData setter always resets d3's alpha to 1. Track the
    // live alpha so a genuine topology change can be ingested at the energy
    // the prior graph actually had, rather than visibly exploding outward.
    let simulation_running = true;
    let last_simulation_alpha = 1;
    let alpha_decay_to_restore = null;
    // True while an initial or topology-change layout is still settling;
    // cleared by onEngineStop after the one zoomToFit it gates.
    let zoom_to_fit_pending = true;
    let node_scale = model.get("node_scale") || default_node_scale;
    let configured_width = model.get("width") || default_width;
    const measured_host_content_width = () => {
        const style = window.getComputedStyle(el);
        const horizontal_padding =
            (Number.parseFloat(style.paddingLeft) || 0) +
            (Number.parseFloat(style.paddingRight) || 0);
        return Math.floor(el.clientWidth - horizontal_padding);
    };
    const host_content_width = () => {
        const measured_width = measured_host_content_width();
        // AnyWidget may render while its output is still detached. Treat
        // that transient zero-width measurement as "not laid out yet" so
        // the initial zoom-to-fit is never calculated against a 1px canvas.
        return measured_width > 32 ? measured_width : configured_width;
    };
    // `width` is an upper bound. Composite layouts may give the widget a
    // narrower grid column, in which case ForceGraph's actual canvas and
    // backing store must shrink too (CSS-only scaling breaks hit testing).
    let width = Math.min(configured_width, host_content_width());
    let host_layout_ready = measured_host_content_width() > 32;
    let height = model.get("height") || default_height;
    colour_scale_type = model.get("colour_scale_type");
    colour_feature = model.get("colour_feature");
    node_size_feature = model.get("node_size_feature");
    select_feature = model.get("select_feature");
    select_feature_value = model.get("select_feature_value");
    let global_selected_ids = model.get("selected_ids") || [];

    plot = create_plot(data);
    // A force receives the simulation alpha on every tick. It runs after the
    // built-in forces, records that alpha, and restores the normal decay after
    // the one specially tempered tick used for a topology change.
    plot.d3Force("__continuity_probe", (alpha) => {
        last_simulation_alpha = alpha;
        if (alpha_decay_to_restore !== null) {
            const decay = alpha_decay_to_restore;
            alpha_decay_to_restore = null;
            plot.d3AlphaDecay(decay);
        }
    });

    // ------------------------------------------------------------------
    // Coordinate-based pointer interaction (hover, tooltip, drag).
    //
    // Hits are computed from the live node/route coordinates - the exact
    // data the painter draws and the brush selection queries - so they can
    // never drift from the picture the way force-graph's pixel-based
    // hit-canvas could (stale color registries, buffer/DPR desyncs).
    // ------------------------------------------------------------------

    const container = el.querySelector(".force-graph-container");
    const canvas = container.querySelector("canvas");

    const graph_coords_from_event = (ev) => {
        const rect = canvas.getBoundingClientRect();
        return plot.screen2GraphCoords(ev.clientX - rect.left, ev.clientY - rect.top);
    };

    const node_at = (gx, gy) => {
        let best = null;
        let best_distance = Infinity;
        for (const node of data.nodes) {
            if (typeof node.x !== "number") continue;
            const distance = Math.hypot(gx - node.x, gy - node.y);
            // Slightly padded so small circles are forgiving to grab.
            if (distance <= node_radius(node) + 3 && distance < best_distance) {
                best = node;
                best_distance = distance;
            }
        }
        return best;
    };

    const point_segment_distance = (px, py, a, b) => {
        const abx = b.x - a.x;
        const aby = b.y - a.y;
        const lengthSq = abx * abx + aby * aby;
        const t = lengthSq === 0 ? 0 : Math.max(0, Math.min(1, ((px - a.x) * abx + (py - a.y) * aby) / lengthSq));
        return Math.hypot(px - (a.x + t * abx), py - (a.y + t * aby));
    };

    const link_at = (gx, gy) => {
        const threshold = train_space_width / 2 + 2;
        let best = null;
        let best_distance = Infinity;
        for (const link of data.links) {
            const start = link.source;
            const end = link.target;
            if (!start || !end || typeof start.x !== "number" || typeof end.x !== "number") continue;
            // Walk the same straight line / quadratic bezier the painter draws.
            const controlPoints = link.__controlPoints;
            const cp = controlPoints && controlPoints.length === 2 ? { x: controlPoints[0], y: controlPoints[1] } : null;
            const steps = cp ? 12 : 1;
            let previous = { x: start.x, y: start.y };
            for (let i = 1; i <= steps; i++) {
                const point = cp ? bezier_point(i / steps, start, cp, end) : { x: end.x, y: end.y };
                const distance = point_segment_distance(gx, gy, previous, point);
                if (distance < best_distance) {
                    best_distance = distance;
                    best = link;
                }
                previous = point;
            }
        }
        return best_distance <= threshold ? best : null;
    };

    // Tooltip: reuses the .float-tooltip-kap styling vendored into the
    // widget CSS, positioned by us within the (position:relative) container.
    const tooltip = document.createElement("div");
    tooltip.className = "float-tooltip-kap route-graph-tooltip";
    tooltip.style.display = "none";
    container.appendChild(tooltip);

    let dragged_node = null;

    container.addEventListener("pointermove", (ev) => {
        if (dragged_node) return; // no hover churn mid-drag
        const coords = graph_coords_from_event(ev);
        const node = node_at(coords.x, coords.y);
        const link = node ? null : link_at(coords.x, coords.y);

        const usage = link && link.data && Number.isFinite(link.data.claimCount)
            ? `${link.data.claimCount} claims · ${(100 * link.data.claimShare).toFixed(1)}% of claims`
            : "";
        const label = node
            ? node.name
            : link
                ? `${link.data && link.data.length ? `${link.id} (${link.data.length})` : link.id}${usage ? ` · ${usage}` : ""}`
                : "";
        if (label) {
            const rect = canvas.getBoundingClientRect();
            tooltip.textContent = label;
            tooltip.style.display = "";
            tooltip.style.left = `${ev.clientX - rect.left + 10}px`;
            tooltip.style.top = `${ev.clientY - rect.top + 10}px`;
        } else {
            tooltip.style.display = "none";
        }
        canvas.style.cursor = node ? "grab" : "";
    });
    container.addEventListener("pointerleave", () => {
        tooltip.style.display = "none";
        canvas.style.cursor = "";
    });

    // Node dragging (same math as force-graph's own: d3-drag accumulates
    // pointer deltas onto the subject's coordinates, scaled by the zoom).
    // The pan filter below keeps d3-zoom's panning off while a drag starts
    // on a node.
    let drag_start_position = null;
    select(canvas).call(
        node_drag()
            .filter((ev) => !ev.button && !ev.metaKey) // meta belongs to the brush
            .subject((ev) => {
                const coords = graph_coords_from_event(ev.sourceEvent ?? ev);
                return node_at(coords.x, coords.y);
            })
            .on("start", (ev) => {
                dragged_node = ev.subject;
                drag_start_position = { x: dragged_node.x, y: dragged_node.y };
                dragged_node.fx = dragged_node.x;
                dragged_node.fy = dragged_node.y;
                tooltip.style.display = "none";
                canvas.style.cursor = "grabbing";
                // Playback updates freeze the tick budget; give the drag
                // fully live physics for its duration + natural cooldown.
                plot.cooldownTicks(Infinity);
            })
            .on("drag", (ev) => {
                const zoom_level = plot.zoom();
                dragged_node.fx = dragged_node.x = drag_start_position.x + (ev.x - drag_start_position.x) / zoom_level;
                dragged_node.fy = dragged_node.y = drag_start_position.y + (ev.y - drag_start_position.y) / zoom_level;
                plot.d3ReheatSimulation();
            })
            .on("end", () => {
                if (dragged_node) {
                    dragged_node.fx = undefined;
                    dragged_node.fy = undefined;
                }
                dragged_node = null;
                drag_start_position = null;
                canvas.style.cursor = "";
            }),
    );

    // Don't pan the canvas when the gesture starts on a node - that's a drag.
    plot.enablePanInteraction((ev) => {
        if (!ev || typeof ev.clientX !== "number") return true;
        const coords = graph_coords_from_event(ev);
        return node_at(coords.x, coords.y) === null;
    });

    const patch_node = (current, incoming) => {
        // Never overwrite force-owned kinematics or a live drag pin.
        for (const [key, value] of Object.entries(incoming)) {
            if (!["x", "y", "vx", "vy", "fx", "fy", "index"].includes(key)) {
                current[key] = value;
            }
        }
    };

    const patch_link = (current, incoming) => {
        // d3-force replaces source/target ids with node object references.
        // Preserve those references and its private curve cache.
        for (const [key, value] of Object.entries(incoming)) {
            if (!["source", "target", "index", "__controlPoints"].includes(key)) {
                current[key] = value;
            }
        }
    };

    const node_members = (node) => {
        const members = node.data && node.data.members;
        return Array.isArray(members) && members.length ? members : [node.id];
    };

    const seed_from_members = (node, currentNodes) => {
        const members = new Set(node_members(node));
        const sources = currentNodes.filter((candidate) =>
            node_members(candidate).some((member) => members.has(member))
        );
        if (!sources.length) return;

        for (const field of ["x", "y", "vx", "vy"]) {
            const values = sources
                .map((source) => source[field])
                .filter((value) => Number.isFinite(value));
            if (values.length) {
                node[field] = values.reduce((sum, value) => sum + value, 0) / values.length;
            }
        }
    };

    // A same-topology frame only changes board styling and metadata. Patch
    // the objects already owned by d3-force so alpha, countdown, positions,
    // velocities and stopped/running state all continue untouched. Only a
    // real topology change is passed through graphData().
    const update_data = () => {
        const newData = model.get("data");
        const currentData = plot.graphData();
        const currentNodesById = new Map(currentData.nodes.map((node) => [node.id, node]));
        const currentLinksById = new Map(currentData.links.map((link) => [link.id, link]));

        const sameTopology =
            idSetsEqual(idSet(currentData.nodes), idSet(newData.nodes)) &&
            idSetsEqual(idSet(currentData.links), idSet(newData.links));
        if (sameTopology) {
            newData.nodes.forEach((node) => patch_node(currentNodesById.get(node.id), node));
            newData.links.forEach((link) => patch_link(currentLinksById.get(link.id), link));
            currentData.layoutKey = newData.layoutKey;
            data = currentData;
        } else {
            const was_running = simulation_running;
            newData.nodes.forEach((node) => {
                const previous = currentNodesById.get(node.id);
                if (previous) {
                    node.x = previous.x;
                    node.y = previous.y;
                    if (Number.isFinite(previous.vx)) node.vx = previous.vx;
                    if (Number.isFinite(previous.vy)) node.vy = previous.vy;
                } else {
                    // Contracted nodes start at their member-city centroid;
                    // expanding a contraction seeds each city from the old
                    // merged node. Velocities are averaged the same way.
                    seed_from_members(node, currentData.nodes);
                }
            });

            zoom_to_fit_pending = true;
            plot.cooldownTicks(Infinity);
            plot.warmupTicks(0);

            // graphData() internally forces alpha(1). Choose a one-tick decay
            // that lands on the previous live alpha before any force runs.
            // A genuinely new topology gets a small amount of energy when
            // the old graph was idle so its new nodes can settle naturally.
            const desired_alpha = was_running
                ? Math.min(0.999, Math.max(0, last_simulation_alpha))
                : 0.08;
            alpha_decay_to_restore = plot.d3AlphaDecay();
            plot.d3AlphaDecay(1 - desired_alpha);
            simulation_running = true;
            data = newData;
            plot.graphData(data);
        }

        build_colour_scale();
        create_node_canvas_object(plot, node_scale, node_size_feature);
    };
    model.on("change:data", update_data);

    const update_repulsion = () => {
        const repulsion = model.get("repulsion") ?? default_repulsion;
        plot.d3Force("charge", forceManyBody().strength(-repulsion));
        plot.d3ReheatSimulation();
    };
    model.on("change:repulsion", update_repulsion);

    const update_link_distance = () => {
        plot.d3Force(
            "link",
            forceLink()
                .id((d) => d.id)
                .distance((link) => link_distance_for(model, link)),
        );
        plot.d3ReheatSimulation();
    };
    model.on("change:link_distance_base", update_link_distance);
    model.on("change:link_distance_scale", update_link_distance);

    const update_unclaimed_route_opacity = () => {
        unclaimed_route_opacity = normalized_opacity(
            model.get("unclaimed_route_opacity") ?? default_unclaimed_route_opacity
        );
    };
    model.on("change:unclaimed_route_opacity", update_unclaimed_route_opacity);

    const update_node_scale = () => {
        node_scale = model.get("node_scale");
        create_node_canvas_object(plot, node_scale, node_size_feature);
        plot.d3ReheatSimulation();
    };
    model.on("change:node_scale", update_node_scale);

    const update_node_size_feature = () => {
        node_size_feature = model.get("node_size_feature");
        create_node_canvas_object(plot, node_scale, node_size_feature);
    };
    model.on("change:node_size_feature", update_node_size_feature);

    const build_colour_scale = () => {
        if (!colour_feature) {
            colour_scale = undefined;
            return;
        }
        let feature_values = data.nodes.map((node) => node[colour_feature]);
        let feature_type = get_feature_type(feature_values[0]);
        if (feature_type == "numeric") {
            if (colour_scale_type == "diverging") {
                colour_scale = scaleLinear().domain([min(feature_values), 0, max(feature_values)]).range(["#0000FFBF", "white", "#FF0000BF"]);
            } else {
                colour_scale = scaleLinear().domain(extent(feature_values)).range(["#FFFF0080", "#0000FF80"]);
            }
        } else if (feature_type == "hash_string") {
            colour_scale = scaleIdentity();
        } else {
            colour_scale = scaleOrdinal().domain(extent(feature_values)).range(schemeCategory10);
        }
    };

    const update_colour_feature = () => {
        colour_feature = model.get("colour_feature");
        build_colour_scale();
        create_node_canvas_object(plot, node_scale, node_size_feature);
    };
    model.on("change:colour_feature", update_colour_feature);

    const update_colour_scale_type = () => {
        colour_feature = model.get("colour_feature");
        colour_scale_type = model.get("colour_scale_type");
        build_colour_scale();
        create_node_canvas_object(plot, node_scale, node_size_feature);
    };
    model.on("change:colour_scale_type", update_colour_scale_type);

    const apply_select_feature = () => {
        select_feature = model.get("select_feature");
        select_feature_value = model.get("select_feature_value");
        if (select_feature && select_feature_value !== undefined && select_feature_value !== "") {
            local_selected_ids = data.nodes
                .filter((node) => String(node[select_feature]) === String(select_feature_value))
                .map((node) => node.id);
        } else {
            local_selected_ids = [];
        }
        model.set("selected_ids", local_selected_ids);
        debouncedSaveChanges();
        create_node_canvas_object(plot, node_scale, node_size_feature);
    };
    model.on("change:select_feature", apply_select_feature);
    model.on("change:select_feature_value", apply_select_feature);

    model.on("change:selected_ids", () => {
        global_selected_ids = model.get("selected_ids");
        plot.nodeColor((d) =>
            global_selected_ids.includes(d.id)
                ? "red"
                : local_selected_ids.includes(d.id)
                    ? "rgba(255,0,0,0.5)"
                    : (colour_scale ? colour_scale(d[colour_feature]) : "#4a4a4a"),
        );
    });

    update_repulsion();
    update_link_distance();
    update_node_scale();
    update_colour_feature();
    update_node_size_feature();
    apply_select_feature();

    let brush_active = false;

    let overlay = select(container)
        .append("svg")
        .attr("id", "overlay")
        .style("position", "absolute")
        .style("top", 0)
        .style("left", 0)
        .style("width", "100%")
        .style("height", "100%")
        .style("pointer-events", "none");

    let activate_brush = () => {
        brush_active = true;
        el.style.pointerEvents = "none";
        overlay.style.pointerEvents = "auto";

        if (!overlay.select("#brush_group").empty()) return;
        overlay.insert("g", ":first-child")
            .attr("id", "brush_group")
            .attr("class", "brush")
            .call(my_brush);
    };
    let disactivate_brush = () => {
        brush_active = false;
        el.style.pointerEvents = "auto";
        overlay.style.pointerEvents = "none";
        overlay.select("#brush_group").remove();
    };

    let brushed = (event) => {
        if (event.selection) {
            brush_active = true;
            let [[x0_screen, y0_screen], [x1_screen, y1_screen]] = event.selection;
            let corner0 = plot.screen2GraphCoords(x0_screen, y0_screen);
            let corner1 = plot.screen2GraphCoords(x1_screen, y1_screen);
            let bbox = {
                minX: Math.min(corner0.x, corner1.x),
                minY: Math.min(corner0.y, corner1.y),
                maxX: Math.max(corner0.x, corner1.x),
                maxY: Math.max(corner0.y, corner1.y),
            };
            let selectedNodes = tree.search(bbox);
            local_selected_ids = selectedNodes.map((node) => node.id);
            model.set("selected_ids", local_selected_ids);
            debouncedSaveChanges();
        }
    };

    let my_brush = brush()
        .filter((event) => {
            const modifierKey = isMac ? event.metaKey : event.ctrlKey;
            return (
                event.button == 0 &&
                (modifierKey || ["selection", "s", "e", "n", "w"].includes(event.target.__data__.type))
            );
        })
        .extent([[0, 0], [width, height]])
        .on("start brush end", brushed);

    let refit_frame = null;
    const refit_after_layout = () => {
        if (refit_frame != null) cancelAnimationFrame(refit_frame);
        // Two frames lets marimo finish replacing and expanding its output
        // wrapper before force-graph reads the canvas bounds.
        refit_frame = requestAnimationFrame(() => {
            refit_frame = requestAnimationFrame(() => {
                refit_frame = null;
                plot.zoomToFit(0, 20);
            });
        });
    };
    const resize_to_host = () => {
        const measured_width = measured_host_content_width();
        if (measured_width <= 32) return;

        const became_visible = !host_layout_ready;
        host_layout_ready = true;
        const next_width = Math.min(configured_width, measured_width);
        const changed_size = next_width !== width;
        if (changed_size) {
            width = next_width;
            plot.width(width).height(height);
            my_brush.extent([[0, 0], [width, height]]);
            if (!overlay.select("#brush_group").empty()) {
                overlay.select("#brush_group").call(my_brush);
            }
        }
        // Do not skip the first visible fit merely because the fallback
        // canvas happened to have the same numeric width as the real host.
        if (changed_size || became_visible) refit_after_layout();
    };
    const host_resize_observer = new ResizeObserver(resize_to_host);
    host_resize_observer.observe(el);
    requestAnimationFrame(resize_to_host);

    const update_configured_width = () => {
        configured_width = model.get("width") || default_width;
        resize_to_host();
    };
    model.on("change:width", update_configured_width);

    // Brush mode is held, not toggled: active only while the meta key is
    // down. Upstream armed it on any meta keydown and only released it on a
    // double-click - on macOS, where cmd-S (save), cmd-Tab, etc. are pressed
    // constantly, that silently set pointer-events:none on the whole widget
    // and killed node dragging/hover until a stray double-click revived it.
    window.addEventListener("keydown", (e) => {
        if (e.metaKey && !brush_active) { activate_brush(); }
    });
    window.addEventListener("keyup", (e) => {
        if (!e.metaKey && brush_active) { disactivate_brush(); }
    });
    window.addEventListener("blur", () => {
        if (brush_active) { disactivate_brush(); }
    });
    window.addEventListener("dblclick", () => {
        if (brush_active) { disactivate_brush(); }
    });

    // force-graph sizes its canvas backing stores from window.devicePixelRatio
    // once per width/height change. If the DPR changes afterwards - browser
    // cmd +/- zoom (Chrome persists it per site), or dragging the window
    // between a retina and a non-retina display - the pointer hit-map scales
    // away from the visible pixels, anchored at the top-left corner, and most
    // nodes silently stop responding to hover and drag. Watch for it and
    // force a canvas resize (re-setting width/height re-runs force-graph's
    // adjustCanvasSize with the fresh DPR; Kapsule fires onChange even for
    // unchanged values), restoring the view afterwards since the resize
    // recentering math assumes the DPR didn't move.
    let last_device_pixel_ratio = window.devicePixelRatio;
    const device_pixel_ratio_watch = setInterval(() => {
        if (window.devicePixelRatio === last_device_pixel_ratio) return;
        last_device_pixel_ratio = window.devicePixelRatio;
        const center = plot.centerAt();
        const zoom_level = plot.zoom();
        plot.width(width).height(height);
        plot.centerAt(center.x, center.y);
        plot.zoom(zoom_level);
    }, 500);

    // Debug handle (used by the repo's headless probes; harmless otherwise).
    // `build` is stamped by the npm build script - check it in the browser
    // console to confirm which bundle a session is actually running.
    const build_tag = typeof __RG_BUILD__ === "string" ? __RG_BUILD__ : "dev";
    console.log(`route_graph_widget build ${build_tag}`);
    window.__routeGraphDebug = { plot, el, build: build_tag };

    return () => {
        clearInterval(device_pixel_ratio_watch);
        if (refit_frame != null) cancelAnimationFrame(refit_frame);
        host_resize_observer.disconnect();
        model.off("change:width", update_configured_width);
        model.off("change:unclaimed_route_opacity", update_unclaimed_route_opacity);
    };
}

export default { render };
