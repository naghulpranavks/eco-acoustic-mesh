/* ============================================
   EcoMesh Ranger Dashboard — Application Logic
   SSE-powered real-time alert feed + Leaflet map
   ============================================ */

(function () {
    "use strict";

    // --- Configuration ---
    const CONFIG = {
        apiBase: window.location.origin,
        sseEndpoint: "/api/alerts/stream",
        pollInterval: 10000,
        mapCenter: [-1.948975, 34.786740],  // Masai Mara default
        mapZoom: 12,
    };

    // --- State ---
    const state = {
        alerts: [],
        nodes: {},
        markers: {},
        filter: "all",
        mapReady: false,
        connected: false,
    };

    // --- Threat metadata ---
    const THREATS = {
        CHAINSAW: { icon: "\u{1FAB5}", label: "Chainsaw", css: "chainsaw", color: "#ef4444" },
        GUNSHOT:  { icon: "\u{1F4A5}", label: "Gunshot",  css: "gunshot",  color: "#dc2626" },
        VEHICLE:  { icon: "\u{1F69A}", label: "Vehicle",  css: "vehicle",  color: "#f59e0b" },
        AMBIENT:  { icon: "\u{1F33F}", label: "Ambient",  css: "ambient",  color: "#22c55e" },
        UNKNOWN:  { icon: "\u{2753}", label: "Unknown",  css: "ambient",  color: "#6b7280" },
    };

    // =====================
    //  MAP INITIALIZATION
    // =====================
    let map;
    let markerLayer;

    function initMap() {
        map = L.map("map", {
            center: CONFIG.mapCenter,
            zoom: CONFIG.mapZoom,
            zoomControl: false,
            attributionControl: false,
        });

        // Dark tiles
        L.tileLayer(
            "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
            { maxZoom: 19 }
        ).addTo(map);

        L.control.zoom({ position: "topright" }).addTo(map);
        markerLayer = L.layerGroup().addTo(map);
        state.mapReady = true;
    }

    function addMapMarker(alert) {
        if (!state.mapReady) return;
        const loc = alert.location;
        if (!loc || !loc.latitude || !loc.longitude) return;

        const meta = THREATS[alert.threat?.class] || THREATS.UNKNOWN;
        const isThreat = !["AMBIENT", "UNKNOWN"].includes(alert.threat?.class);
        const markerType = isThreat ? meta.css : "heartbeat";

        const icon = L.divIcon({
            className: "",
            html: '<div class="threat-marker ' + markerType + '">' + meta.icon + "</div>",
            iconSize: [32, 32],
            iconAnchor: [16, 16],
        });

        const marker = L.marker([loc.latitude, loc.longitude], { icon: icon })
            .addTo(markerLayer);

        marker.on("click", function () {
            showOverlay(alert);
        });

        // Pan to threat
        if (isThreat) {
            map.flyTo([loc.latitude, loc.longitude], 14, { duration: 1 });
        }
    }

    function showOverlay(alert) {
        const meta = THREATS[alert.threat?.class] || THREATS.UNKNOWN;
        document.getElementById("overlay-icon").textContent = meta.icon;
        document.getElementById("overlay-label").textContent = meta.label + " Detected";

        const conf = alert.threat?.confidence || 0;
        const ts = alert.timestamp_iso || new Date(alert.timestamp * 1000).toISOString();

        document.getElementById("overlay-body").innerHTML =
            '<div class="detail-row"><span class="detail-label">Confidence</span><span class="detail-value">' + conf + '%</span></div>' +
            '<div class="detail-row"><span class="detail-label">Node</span><span class="detail-value">#' + (alert.node?.id || "?") + '</span></div>' +
            '<div class="detail-row"><span class="detail-label">Time</span><span class="detail-value">' + formatTime(ts) + '</span></div>' +
            '<div class="detail-row"><span class="detail-label">Location</span><span class="detail-value">' +
                (alert.location?.latitude?.toFixed(5) || "?") + ', ' +
                (alert.location?.longitude?.toFixed(5) || "?") +
            '</span></div>' +
            '<div class="detail-row"><span class="detail-label">Battery</span><span class="detail-value">' + (alert.node?.battery_pct || "?") + '%</span></div>';

        document.getElementById("map-overlay").style.display = "block";
    }

    // =====================
    //  TAB NAVIGATION
    // =====================
    function initTabs() {
        document.querySelectorAll(".tab-btn").forEach(function (btn) {
            btn.addEventListener("click", function () {
                var tab = btn.dataset.tab;
                document.querySelectorAll(".tab-btn").forEach(function (b) { b.classList.remove("active"); });
                document.querySelectorAll(".tab-panel").forEach(function (p) {
                    p.classList.remove("active");
                    p.style.display = "none";
                });
                btn.classList.add("active");
                var panel = document.getElementById("panel-" + tab);
                panel.style.display = "flex";
                panel.classList.add("active");

                if (tab === "map" && map) {
                    setTimeout(function () { map.invalidateSize(); }, 150);
                }
                // Re-render nodes when switching to that tab
                if (tab === "nodes") {
                    renderNodes();
                }
            });
        });

        document.getElementById("overlay-close").addEventListener("click", function () {
            document.getElementById("map-overlay").style.display = "none";
        });

        // Alert filters
        document.querySelectorAll(".filter-btn").forEach(function (btn) {
            btn.addEventListener("click", function () {
                document.querySelectorAll(".filter-btn").forEach(function (b) { b.classList.remove("active"); });
                btn.classList.add("active");
                state.filter = btn.dataset.filter;
                renderAlerts();
            });
        });
    }

    // =====================
    //  ALERT RENDERING
    // =====================
    function renderAlerts() {
        var list = document.getElementById("alert-list");
        var filtered = state.alerts;

        if (state.filter === "threats") {
            filtered = filtered.filter(function (a) {
                return !["AMBIENT", "UNKNOWN", "heartbeat"].includes(a.threat?.class) && a.msg_type !== "heartbeat";
            });
        }

        if (filtered.length === 0) {
            list.innerHTML =
                '<div class="empty-state"><p>No ' +
                (state.filter === "threats" ? "threat " : "") +
                'alerts yet.</p></div>';
            return;
        }

        list.innerHTML = "";
        filtered.forEach(function (alert, i) {
            list.appendChild(createAlertCard(alert, i === 0));
        });
    }

    function createAlertCard(alert, isNew) {
        var meta = THREATS[alert.threat?.class] || THREATS.UNKNOWN;
        var isThreat = !["AMBIENT", "UNKNOWN"].includes(alert.threat?.class) && alert.msg_type !== "heartbeat";
        var conf = alert.threat?.confidence || 0;
        var ts = alert.timestamp_iso || "";

        var card = document.createElement("div");
        card.className = "alert-card " + (isThreat ? "threat" : "heartbeat") + (isNew ? " new" : "");

        var confLevel = conf >= 80 ? "high" : conf >= 50 ? "medium" : "low";

        card.innerHTML =
            '<div class="alert-icon-wrap ' + meta.css + '">' + meta.icon + '</div>' +
            '<div class="alert-content">' +
                '<div class="alert-title">' + meta.label + (isThreat ? " Detected" : "") + '</div>' +
                '<div class="alert-meta">' +
                    '<span>Node #' + (alert.node?.id || "?") + '</span>' +
                    '<span>' + formatTime(ts) + '</span>' +
                    (isThreat ? '<span>' + conf + '% conf</span>' : '') +
                '</div>' +
                (isThreat ? '<div class="confidence-bar"><div class="confidence-fill ' + confLevel + '" style="width:' + conf + '%"></div></div>' : '') +
            '</div>';

        card.addEventListener("click", function () {
            switchToMap();
            showOverlay(alert);
            if (alert.location?.latitude) {
                map.flyTo([alert.location.latitude, alert.location.longitude], 14, { duration: 1 });
            }
        });

        return card;
    }

    function switchToMap() {
        document.querySelectorAll(".tab-btn").forEach(function (b) { b.classList.remove("active"); });
        document.querySelectorAll(".tab-panel").forEach(function (p) {
            p.classList.remove("active");
            p.style.display = "none";
        });
        document.querySelector('[data-tab="map"]').classList.add("active");
        var mapPanel = document.getElementById("panel-map");
        mapPanel.style.display = "flex";
        mapPanel.classList.add("active");
        setTimeout(function () { map.invalidateSize(); }, 150);
    }

    // =====================
    //  NODE STATUS
    // =====================
    function renderNodes() {
        var grid = document.getElementById("nodes-grid");
        var nodeIds = Object.keys(state.nodes);

        if (nodeIds.length === 0) {
            grid.innerHTML = '<div class="empty-state"><p>No nodes reporting yet.</p></div>';
            return;
        }

        grid.innerHTML = "";
        nodeIds.forEach(function (id) {
            var n = state.nodes[id];
            var age = (Date.now() / 1000) - (n.timestamp || 0);
            var online = age < 600; // 10 min timeout

            var card = document.createElement("div");
            card.className = "node-card";
            card.innerHTML =
                '<div class="node-header">' +
                    '<span class="node-name">Sentinel #' + id + '</span>' +
                    '<span class="node-status-badge ' + (online ? "online" : "offline") + '">' +
                        (online ? "Online" : "Offline") +
                    '</span>' +
                '</div>' +
                '<div class="node-stats">' +
                    '<div class="node-stat"><div class="node-stat-value" style="color:' + batteryColor(n.battery_pct) + '">' + (n.battery_pct || "?") + '%</div><div class="node-stat-label">Battery</div></div>' +
                    '<div class="node-stat"><div class="node-stat-value">' + (n.cpu_temp_c || "?") + '&deg;C</div><div class="node-stat-label">Temp</div></div>' +
                    '<div class="node-stat"><div class="node-stat-value">' + formatTimeAgo(age) + '</div><div class="node-stat-label">Last Seen</div></div>' +
                '</div>';
            grid.appendChild(card);
        });
    }

    // =====================
    //  SSE / POLLING
    // =====================
    function connectSSE() {
        try {
            var source = new EventSource(CONFIG.apiBase + CONFIG.sseEndpoint);

            source.onopen = function () {
                setConnectionStatus("connected", "Live");
                state.connected = true;
            };

            source.onmessage = function (event) {
                try {
                    var alert = JSON.parse(event.data);
                    handleNewAlert(alert);
                } catch (e) {
                    console.warn("SSE parse error:", e);
                }
            };

            source.onerror = function () {
                setConnectionStatus("error", "Disconnected");
                state.connected = false;
                source.close();
                // Reconnect after delay
                setTimeout(connectSSE, 5000);
            };
        } catch (e) {
            console.warn("SSE not available, falling back to polling");
            startPolling();
        }
    }

    function startPolling() {
        setConnectionStatus("connected", "Polling");
        fetchAlerts();
        setInterval(fetchAlerts, CONFIG.pollInterval);
    }

    function fetchAlerts() {
        fetch(CONFIG.apiBase + "/api/alerts?limit=50")
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.alerts && data.alerts.length > state.alerts.length) {
                    data.alerts.forEach(function (a) {
                        if (!state.alerts.find(function (e) { return e.timestamp === a.timestamp && e.node?.id === a.node?.id; })) {
                            handleNewAlert(a);
                        }
                    });
                }
                setConnectionStatus("connected", "Live");
            })
            .catch(function () {
                setConnectionStatus("error", "Offline");
            });
    }

    function handleNewAlert(alert) {
        state.alerts.unshift(alert);
        if (state.alerts.length > 200) state.alerts.pop();

        // Update node status
        if (alert.node?.id) {
            state.nodes[alert.node.id] = {
                battery_pct: alert.node.battery_pct,
                cpu_temp_c: alert.node.cpu_temp_c,
                timestamp: alert.timestamp,
                last_seen: alert.timestamp_iso,
            };
        }

        // Add marker
        addMapMarker(alert);

        // Update badge
        var isThreat = !["AMBIENT", "UNKNOWN"].includes(alert.threat?.class) && alert.msg_type !== "heartbeat";
        if (isThreat) {
            var badge = document.getElementById("alert-badge");
            var count = parseInt(badge.textContent || "0") + 1;
            badge.textContent = count;
            badge.style.display = "flex";
            showToast(alert);
        }

        renderAlerts();
        renderNodes();
    }

    // =====================
    //  TOAST NOTIFICATIONS
    // =====================
    function showToast(alert) {
        var meta = THREATS[alert.threat?.class] || THREATS.UNKNOWN;
        var toast = document.createElement("div");
        toast.className = "toast threat";
        toast.innerHTML = meta.icon + " " + meta.label + " detected at Node #" + (alert.node?.id || "?") + " (" + (alert.threat?.confidence || 0) + "% conf)";

        document.getElementById("toast-container").appendChild(toast);
        setTimeout(function () {
            toast.style.opacity = "0";
            toast.style.transform = "translateY(-20px)";
            toast.style.transition = "all 0.3s ease";
            setTimeout(function () { toast.remove(); }, 300);
        }, 5000);
    }

    // =====================
    //  UTILITIES
    // =====================
    function setConnectionStatus(status, text) {
        var dot = document.querySelector(".status-dot");
        var label = document.querySelector(".status-text");
        dot.className = "status-dot " + status;
        label.textContent = text;
    }

    function formatTime(iso) {
        if (!iso) return "?";
        try {
            var d = new Date(iso);
            return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
        } catch (e) { return iso; }
    }

    function formatTimeAgo(seconds) {
        if (seconds < 60) return Math.floor(seconds) + "s";
        if (seconds < 3600) return Math.floor(seconds / 60) + "m";
        return Math.floor(seconds / 3600) + "h";
    }

    function batteryColor(pct) {
        if (!pct) return "#6b7280";
        if (pct > 60) return "#22c55e";
        if (pct > 30) return "#f59e0b";
        return "#ef4444";
    }

    // =====================
    //  BOOTSTRAP
    // =====================
    function init() {
        // Hide non-active panels explicitly on init
        document.querySelectorAll(".tab-panel").forEach(function (p) {
            if (!p.classList.contains("active")) {
                p.style.display = "none";
            }
        });
        initMap();
        initTabs();
        // Force map to recalculate size after layout is ready
        setTimeout(function () {
            if (map) map.invalidateSize();
        }, 300);
        // Try SSE first, fall back to polling
        connectSSE();
        // Initial fetch
        fetchAlerts();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
