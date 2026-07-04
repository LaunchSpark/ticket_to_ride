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

let local_selected_ids = [];
let colour_scale_type = "";
let plot;
let tree;
let default_node_size = 5;
let colour_feature = undefined;
let node_size_feature = undefined;
let colour_scale;
let select_feature = undefined;
let select_feature_value = undefined;

function debounce(func, wait) {
    let timeout;
    return function (...args) {
        clearTimeout(timeout);
        timeout = setTimeout(() => func.apply(this, args), wait);
    };
}

const create_rtree = (data) => {
    tree = new MyRBush();
    tree.load(data);
};

const get_feature_type = (value) => {
    if (typeof value === "number") return "numeric";
    if (typeof value === "string" && value.startsWith("#")) return "hash_string";
    return "categorical";
};

const ua = navigator.userAgent.toLowerCase();
const isMac = ua.includes("macintosh");

const create_node_canvas_object = (plot, node_scale, node_size_feature) => {
    return plot.nodeCanvasObject((node, ctx) => {
        let radius;
        if (node_size_feature == undefined || node_size_feature == "") {
            radius = default_node_size * node_scale;
        } else {
            radius = node[node_size_feature] * node_scale;
        }
        const isLocalSelected = local_selected_ids.includes(node.id);
        const hasSelection = local_selected_ids.length > 0;
        const fillColour = colour_scale ? colour_scale(node[colour_feature]) : "#4a4a4a";

        ctx.globalAlpha = hasSelection && !isLocalSelected ? 0.2 : 1.0;

        ctx.beginPath();
        ctx.arc(node.x, node.y, radius, 0, 2 * Math.PI, false);
        ctx.fillStyle = fillColour;
        ctx.fill();

        if (isLocalSelected) {
            ctx.lineWidth = radius / 5;
            ctx.strokeStyle = "red";
            ctx.stroke();
        } else {
            ctx.lineWidth = radius / 10;
            ctx.strokeStyle = "lightgrey";
            ctx.stroke();
        }

        ctx.globalAlpha = 1.0;
    });
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
            ctx.translate(center.x, center.y);
            ctx.rotate(Math.atan2(direction.y, direction.x));

            ctx.fillStyle = baseColor;
            ctx.fillRect(-carLength / 2, -train_space_width / 2, carLength, train_space_width);
            ctx.lineWidth = 0.6;
            ctx.strokeStyle = "rgba(0,0,0,0.4)";
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
            .cooldownTime(5000)
            .warmupTicks(10)
            .nodeLabel("label")
            // Claimed links hide the default line entirely; paint_train_spaces
            // strokes a full-width claim band in its place. (Safe for hover:
            // the pointer-picking shadow canvas colors links by __indexColor,
            // not this accessor.)
            .linkColor((link) => (link.claimedColor ? "rgba(0,0,0,0)" : link.color || "#999999"))
            // Thin roadbed only - the visible route body is the train spaces
            // painted on top in "after" mode.
            .linkWidth(() => 1)
            .linkCanvasObjectMode(() => "after")
            .linkCanvasObject(paint_train_spaces)
            .linkCurvature((link) => link.curvature || 0)
            .d3AlphaDecay(0.001)
            .minZoom(0.001)
            .nodeCanvasObjectMode(() => "replace")
            // graphData()'s setter always resets alpha to 1 and restarts the
            // cooldown countdown ("re-heat the simulation"), even when it
            // preserves existing node positions - so autoPauseRedraw's
            // default (only repaint while the engine is actively ticking)
            // would otherwise mean our in-place cosmetic mutations below
            // (update_data) never actually get painted once the simulation
            // has settled and gone idle between board-state updates.
            .autoPauseRedraw(false)
            .onEngineStop(() => {
                plot.zoomToFit(400);
                create_rtree(data["nodes"]);
            });
    };

    const idSet = (items) => new Set(items.map((item) => item.id));
    const idSetsEqual = (a, b) => a.size === b.size && [...a].every((id) => b.has(id));

    let data = model.get("data");
    let node_scale = model.get("node_scale") || default_node_scale;
    let width = model.get("width") || default_width;
    let height = model.get("height") || default_height;
    colour_scale_type = model.get("colour_scale_type");
    colour_feature = model.get("colour_feature");
    node_size_feature = model.get("node_size_feature");
    select_feature = model.get("select_feature");
    select_feature_value = model.get("select_feature_value");
    let global_selected_ids = model.get("selected_ids");

    plot = create_plot(data);

    // Calling plot.graphData() again - even just to recolor a claimed route -
    // unconditionally resets the simulation's alpha to 1 and restarts its
    // cooldown countdown (see force-graph's own graphData setter: `.stop()
    // .alpha(1) // re-heat the simulation`). With updates arriving every
    // ~300ms from a PlaySlider and a 5s cooldownTime, that means the engine
    // never gets to settle - it looks like the simulation restarting on
    // every step, because it genuinely is.
    //
    // For our case the board's topology never actually changes mid-game -
    // only which routes are colored as claimed - so instead of calling
    // graphData() again, mutate the *same* live node/link objects in place
    // (matched by id) and let the existing, already-settled simulation keep
    // running undisturbed. autoPauseRedraw(false) above ensures the canvas
    // still repaints on the next frame to pick up the new colors even once
    // the engine has gone idle. Only fall back to a full graphData() reload
    // if the set of node/link ids actually changed (a genuine topology
    // change, which none of our current notebooks trigger mid-game).
    const update_data = () => {
        const newData = model.get("data");
        const currentData = plot.graphData();

        const sameTopology =
            idSetsEqual(idSet(currentData.nodes), idSet(newData.nodes)) &&
            idSetsEqual(idSet(currentData.links), idSet(newData.links));

        if (sameTopology) {
            const newNodesById = new Map(newData.nodes.map((node) => [node.id, node]));
            currentData.nodes.forEach((node) => {
                const updated = newNodesById.get(node.id);
                if (!updated) return;
                node.name = updated.name;
                node.size = updated.size;
                node.color = updated.color;
                node.data = updated.data;
            });

            const newLinksById = new Map(newData.links.map((link) => [link.id, link]));
            currentData.links.forEach((link) => {
                const updated = newLinksById.get(link.id);
                if (!updated) return;
                link.name = updated.name;
                link.width = updated.width;
                link.color = updated.color;
                link.claimedColor = updated.claimedColor;
                link.curvature = updated.curvature;
                link.data = updated.data;
            });

            data = currentData;
        } else {
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
    let container = el.querySelector(".force-graph-container");

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

    window.addEventListener("keydown", (e) => {
        if (e.metaKey && !brush_active) { activate_brush(); }
    });
    window.addEventListener("dblclick", (e) => {
        if (brush_active) { disactivate_brush(); }
    });
}

export default { render };
