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

function link_distance_for(model, link) {
    const base = model.get("link_distance_base") ?? default_link_distance_base;
    const scale = model.get("link_distance_scale") ?? default_link_distance_scale;
    const routeLength = (link.data && typeof link.data.length === "number") ? link.data.length : 1;
    return base + scale * routeLength;
}

function render({ model, el }) {
    const debouncedSaveChanges = debounce(() => model.save_changes(), 300);

    const create_plot = (data) => {
        return ForceGraph()(el)
            .width(width)
            .height(height)
            .graphData(data)
            .cooldownTime(5000)
            .warmupTicks(10)
            .nodeLabel("label")
            .linkColor((link) => link.color || "#999999")
            .linkWidth((link) => link.width || 1)
            .d3AlphaDecay(0.001)
            .minZoom(0.001)
            .nodeCanvasObjectMode(() => "replace")
            .onEngineStop(() => {
                plot.zoomToFit(400);
                create_rtree(data["nodes"]);
            });
    };

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

    // force-graph's graphData() setter is designed to be called again for
    // incremental updates: nodes whose id matches an existing node keep
    // their current position/velocity, only genuinely new nodes get a fresh
    // starting position. Re-using the same `plot` instance (instead of
    // constructing a new widget/ForceGraph per update, which is what the
    // calling notebook used to do) is what makes this actually apply -
    // otherwise every update restarts the simulation from scratch, which is
    // what "flies all over the place" on every board-state update was.
    const update_data = () => {
        data = model.get("data");
        plot.graphData(data);
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
