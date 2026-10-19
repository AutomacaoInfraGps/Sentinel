(() => {
  "use strict";

  const canvas = document.getElementById("network");
  const ctx = canvas.getContext("2d");
  const introLogo = document.getElementById("introLogo");
  const galaxyBackground = document.getElementById("galaxyBackground");
  const galaxyNodeTexture = document.getElementById("galaxyNodeTexture");
  const normalizeCelestialName = value => String(value || "")
    .normalize("NFD").replace(/[\u0300-\u036f]/g, "").trim().toUpperCase();
  const celestialTextures = new Map(
    [...document.querySelectorAll("[data-celestial]")]
      .map(image => [normalizeCelestialName(image.dataset.celestial), image]),
  );
  const celestialRenderCache = new Map();
  let galaxyBackgroundRender = null;
  const ui = {
    toast: document.getElementById("toast"),
    metrics: document.getElementById("metrics"),
    sync: document.getElementById("syncLabel"),
    search: document.getElementById("searchInput"),
    regional: document.getElementById("regionalFilter"),
    type: document.getElementById("typeFilter"),
    connectionRank: document.getElementById("connectionRank"),
    categoryRank: document.getElementById("categoryRank"),
    legend: document.getElementById("typeLegend"),
    panel: document.getElementById("detailPanel"),
    detail: document.getElementById("detailContent"),
    table: document.getElementById("tableView"),
    tableBody: document.getElementById("tableBody"),
    exportPdf: document.getElementById("exportPdf"),
    exportXlsx: document.getElementById("exportXlsx"),
  };
  const categories = {
    links: { label: "Links", singular: "Link", color: "#22c3f6", mono: "LK" },
    firewalls: { label: "Firewalls", singular: "Firewall", color: "#ef5968", mono: "FW" },
    switches: { label: "Switches", singular: "Switch", color: "#9b7cf4", mono: "SW" },
    servidores: { label: "Servidores", singular: "Servidor", color: "#35d09f", mono: "SV" },
    vpns: { label: "VPNs", singular: "VPN", color: "#f4bd4e", mono: "VP" },
    aps: { label: "Antenas UniFi", singular: "Antena", color: "#e6edf2", mono: "AP" },
    redes_wifi: { label: "Redes Wi-Fi", singular: "Rede Wi-Fi", color: "#5bd6ff", mono: "WF" },
  };
  const planetTextures = new Map();
  const state = {
    data: null, nodes: [], edges: [], byId: new Map(), neighbors: new Map(),
    visibleNodes: [], visibleEdges: [], hover: null, selected: null,
    camera: { x: 0, y: 0, scale: 1 }, pointer: null, dragNode: null, dragging: false,
    time: 0, intro: null, stars: [], tableExpanded: new Set(),
  };
  const escapeHtml = value => String(value ?? "").replace(/[&<>'"]/g, char => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  }[char]));
  const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
  const easeOutCubic = value => 1 - Math.pow(1 - clamp(value, 0, 1), 3);
  const easeOutBack = value => {
    const p = clamp(value, 0, 1), c1 = 1.35, c3 = c1 + 1;
    return 1 + c3 * Math.pow(p - 1, 3) + c1 * Math.pow(p - 1, 2);
  };
  const isGalaxyRegional = regional => String(regional?.codigo || regional?.id || "")
    .normalize("NFD").replace(/[\u0300-\u036f]/g, "").toUpperCase() === "REG_GALAXIA";

  function celestialTexture(node) {
    if (node.tipo === "links") return celestialTextures.get("COMETA_LINK");
    if (node.tipo === "firewalls") return celestialTextures.get(firewallCelestialKey(node.nome));
    if (node.tipo === "servidores") return celestialTextures.get("ESTRELA");
    if (node.tipo === "switches") return celestialTextures.get(switchCelestialKey(node.nome));
    if (node.tipo === "vpns") return celestialTextures.get(vpnCelestialKey(node.nome));
    if (node.tipo === "aps") return celestialTextures.get(apCelestialKey(node.nome));
    if (node.tipo !== "redes_wifi") return null;
    const name = normalizeCelestialName(node.nome);
    if (["NEPTUNO", "NEPTUNE"].includes(name)) return celestialTextures.get("NETUNO");
    return celestialTextures.get(name) || null;
  }

  function firewallCelestialKey(name) {
    return stableVariantKey(name, [
      "BURACO_NEGRO_ACREACAO",
      "BURACO_NEGRO_RUBI",
      "BURACO_NEGRO_LENTE",
    ]);
  }

  function switchCelestialKey() {
    return "ASTEROIDE_ROCHOSO";
  }

  function vpnCelestialKey() {
    return "SATELITE_PAINEIS";
  }

  function apCelestialKey() {
    return "NEBULOSA_ANEL";
  }

  function stableNameHash(name) {
    const normalized = normalizeCelestialName(name);
    let hash = 2166136261;
    for (let index = 0; index < normalized.length; index += 1) {
      hash ^= normalized.charCodeAt(index);
      hash = Math.imul(hash, 16777619);
    }
    return hash >>> 0;
  }

  function stableVariantKey(name, variants) {
    return variants[stableNameHash(name) % variants.length];
  }

  function stellarFilter(name) {
    const key = normalizeCelestialName(name);
    if (["BETELGEUSE", "MIRA", "SARGAS", "DIPHDA", "HAMAL"].includes(key)) {
      return "sepia(.65) saturate(2.2) hue-rotate(325deg)";
    }
    if (["ARCTURO", "CAPELLA", "POLLUX", "ALDEBARAN", "GOMEISA"].includes(key)) {
      return "sepia(.55) saturate(1.8) hue-rotate(350deg)";
    }
    if (["RIGEL", "SIRIUS", "BELLATRIX", "ALNITAK", "ALNILAN", "MINTAKA", "SAIPH", "VEGA"].includes(key)) {
      return "saturate(1.35) hue-rotate(4deg) brightness(1.12)";
    }
    return "saturate(.8) brightness(1.04)";
  }

  function cachedCelestialTexture(image, key, width, height, filter = "none") {
    if (!image?.complete || !image.naturalWidth || !image.naturalHeight) return null;
    const cacheKey = `${key}:${width}x${height}:${filter}`;
    if (celestialRenderCache.has(cacheKey)) return celestialRenderCache.get(cacheKey);

    const surface = document.createElement("canvas");
    surface.width = width;
    surface.height = height;
    const painter = surface.getContext("2d");
    painter.imageSmoothingEnabled = true;
    painter.imageSmoothingQuality = "high";
    painter.filter = filter;
    painter.drawImage(image, 0, 0, width, height);
    painter.filter = "none";
    celestialRenderCache.set(cacheKey, surface);
    return surface;
  }

  function cachedGalaxyBackground() {
    if (!galaxyBackground.complete || !galaxyBackground.naturalWidth) return null;
    if (galaxyBackgroundRender) return galaxyBackgroundRender;

    const surface = document.createElement("canvas");
    surface.width = galaxyBackground.naturalWidth;
    surface.height = galaxyBackground.naturalHeight;
    const painter = surface.getContext("2d");
    painter.imageSmoothingEnabled = true;
    painter.imageSmoothingQuality = "high";
    painter.filter = "brightness(1.22) saturate(1.08)";
    painter.drawImage(galaxyBackground, 0, 0);
    painter.filter = "none";
    galaxyBackgroundRender = surface;
    return surface;
  }

  function seededFraction(seed) {
    const value = Math.sin(seed * 12.9898 + 78.233) * 43758.5453;
    return value - Math.floor(value);
  }

  function buildStarfield() {
    const count = clamp(Math.round(innerWidth * innerHeight / 9000), 90, 220);
    state.stars = Array.from({ length: count }, (_, index) => ({
      u: seededFraction(index * 5 + 1),
      v: seededFraction(index * 5 + 2),
      size: .45 + seededFraction(index * 5 + 3) * 1.65,
      alpha: .22 + seededFraction(index * 5 + 4) * .58,
      depth: .18 + seededFraction(index * 5 + 5) * .82,
      phase: seededFraction(index * 7 + 6) * Math.PI * 2,
    }));
  }

  function planetTexture(name) {
    const key = String(name || "REDE").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toUpperCase();
    if (planetTextures.has(key)) return planetTextures.get(key);
    const image = document.createElement("canvas");
    image.width = image.height = 112;
    const painter = image.getContext("2d");
    const palettes = {
      MARTE: ["#ffb078", "#d64b32", "#6e1d22"],
      SATURNO: ["#fff0b4", "#d9aa55", "#755233"],
      JUPITER: ["#f7d6ad", "#b86f4a", "#6e3a36"],
      NETUNO: ["#66c8ff", "#1769cc", "#132b7c"],
      ANDROMEDA: ["#eef6ff", "#8bb9ff", "#6247b6"],
    };
    const colors = palettes[key] || ["#a8ecff", "#258fbd", "#123c69"];

    painter.translate(56, 56);
    if (key === "ANDROMEDA") {
      painter.rotate(-.28);
      const glow = painter.createRadialGradient(0, 0, 2, 0, 0, 48);
      glow.addColorStop(0, "rgba(255,255,255,1)");
      glow.addColorStop(.18, "rgba(139,185,255,.9)");
      glow.addColorStop(1, "rgba(98,71,182,0)");
      painter.fillStyle = glow; painter.beginPath(); painter.arc(0, 0, 48, 0, Math.PI * 2); painter.fill();
      painter.strokeStyle = "rgba(221,235,255,.84)"; painter.lineWidth = 5;
      [-1, 1].forEach(direction => {
        painter.beginPath();
        for (let step = 0; step < 52; step += 1) {
          const angle = direction * step * .19;
          const radius = 3 + step * .74;
          const x = Math.cos(angle) * radius;
          const y = Math.sin(angle) * radius * .42;
          step ? painter.lineTo(x, y) : painter.moveTo(x, y);
        }
        painter.stroke();
      });
    } else {
      if (key === "SATURNO") {
        painter.save(); painter.rotate(-.28); painter.scale(1, .34);
        painter.strokeStyle = "rgba(244,220,155,.9)"; painter.lineWidth = 9;
        painter.beginPath(); painter.ellipse(0, 0, 48, 34, 0, 0, Math.PI * 2); painter.stroke(); painter.restore();
      }
      const sphere = painter.createRadialGradient(-13, -15, 4, 0, 0, 38);
      sphere.addColorStop(0, colors[0]); sphere.addColorStop(.52, colors[1]); sphere.addColorStop(1, colors[2]);
      painter.fillStyle = sphere; painter.beginPath(); painter.arc(0, 0, 34, 0, Math.PI * 2); painter.fill();
      painter.save(); painter.beginPath(); painter.arc(0, 0, 34, 0, Math.PI * 2); painter.clip();
      painter.globalAlpha = .34; painter.strokeStyle = colors[0]; painter.lineWidth = key === "JUPITER" ? 7 : 3;
      for (let y = -23; y <= 24; y += key === "JUPITER" ? 11 : 15) {
        painter.beginPath(); painter.moveTo(-38, y); painter.bezierCurveTo(-12, y - 5, 12, y + 5, 38, y); painter.stroke();
      }
      painter.restore();
    }
    planetTextures.set(key, image);
    return image;
  }

  function resize() {
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(innerWidth * ratio);
    canvas.height = Math.round(innerHeight * ratio);
    canvas.style.width = `${innerWidth}px`;
    canvas.style.height = `${innerHeight}px`;
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    buildStarfield();
  }

  function relaxInitialRegionalLayout(regionals) {
    for (let pass = 0; pass < 110; pass += 1) {
      for (let leftIndex = 0; leftIndex < regionals.length; leftIndex += 1) {
        for (let rightIndex = leftIndex + 1; rightIndex < regionals.length; rightIndex += 1) {
          const left = regionals[leftIndex];
          const right = regionals[rightIndex];
          let dx = right.x - left.x;
          let dy = right.y - left.y;
          let distance = Math.hypot(dx, dy);
          if (distance < .01) {
            const angle = (leftIndex + rightIndex + 1) * 1.73;
            dx = Math.cos(angle); dy = Math.sin(angle); distance = 1;
          }
          const minimum = (left.layoutRadius + right.layoutRadius) * 1.06 + 68;
          if (distance >= minimum) continue;
          const correction = (minimum - distance) * .24;
          const unitX = dx / distance;
          const unitY = dy / distance;
          if (left.isHub) {
            right.x += unitX * correction * 2;
            right.y += unitY * correction * 2;
          } else if (right.isHub) {
            left.x -= unitX * correction * 2;
            left.y -= unitY * correction * 2;
          } else {
            left.x -= unitX * correction;
            left.y -= unitY * correction;
            right.x += unitX * correction;
            right.y += unitY * correction;
          }
        }
      }
    }
    regionals.forEach(node => { node.tx = node.x; node.ty = node.y; });
  }

  function buildGraph() {
    const nodes = [];
    const edges = [];
    const regionals = state.data.regionais;
    const goldenAngle = Math.PI * (3 - Math.sqrt(5));
    const devicesByRegional = new Map();
    state.data.dispositivos.forEach(device => {
      if (!devicesByRegional.has(device.regional_id)) devicesByRegional.set(device.regional_id, []);
      devicesByRegional.get(device.regional_id).push(device);
    });

    let orbitIndex = 0;
    regionals.forEach(regional => {
      const isHub = isGalaxyRegional(regional);
      const deviceCount = (devicesByRegional.get(regional.id) || []).length;
      const deviceLayoutRadius = deviceCount ? 108 + Math.floor((deviceCount - 1) / 10) * 58 : 44;
      const layoutRadius = isHub ? Math.max(deviceLayoutRadius, 190) : deviceLayoutRadius;
      const angle = orbitIndex * goldenAngle + .35;
      const distance = 310 * Math.sqrt(orbitIndex + .95);
      const x = isHub ? 0 : Math.cos(angle) * distance * 1.16 + (Math.random() - .5) * 55;
      const y = isHub ? 0 : Math.sin(angle) * distance * .9 + (Math.random() - .5) * 50;
      if (!isHub) orbitIndex += 1;
      nodes.push({
        ...regional, kind: "regional", isHub, layoutRadius,
        radius: isHub ? 72 : 38, x, y, tx: x, ty: y,
        vx: 0, vy: 0, opacity: 0, delay: Math.random() * .35,
      });
    });
    relaxInitialRegionalLayout(nodes);

    const regionalMap = new Map(nodes.map(node => [node.id, node]));
    const galaxyNode = nodes.find(node => node.isHub);
    if (galaxyNode) {
      nodes.filter(node => node.kind === "regional" && !node.isHub).forEach(node => {
        edges.push({
          id: `backbone-${node.id}`, sourceId: galaxyNode.id, targetId: node.id,
          kind: "backbone", phase: Math.random(),
        });
      });
    }
    devicesByRegional.forEach((devices, regionalId) => {
      const parent = regionalMap.get(regionalId);
      if (!parent) return;
      devices.forEach((device, index) => {
        const ringIndex = Math.floor(index / 10);
        const ring = 108 + ringIndex * 58;
        const itemsInRing = Math.min(10, devices.length - ringIndex * 10);
        const angle = (index % 10) / Math.max(itemsInRing, 1) * Math.PI * 2 + (regionalId.length % 7) * .19;
        const x = parent.x + Math.cos(angle) * ring;
        const y = parent.y + Math.sin(angle) * ring;
        nodes.push({
          ...device, kind: "device", radius: device.tipo === "redes_wifi" ? 20 : 13, parentId: regionalId,
          offsetX: x - parent.x, offsetY: y - parent.y, x, y, tx: x, ty: y,
          vx: 0, vy: 0, opacity: 0, delay: .1 + Math.random() * .45,
        });
        edges.push({
          id: `edge-${device.id}`, sourceId: regionalId, targetId: device.id,
          type: device.tipo, phase: Math.random(),
        });
      });
    });

    state.nodes = nodes;
    state.byId = new Map(nodes.map(node => [node.id, node]));
    state.edges = edges.map(edge => ({
      ...edge, source: state.byId.get(edge.sourceId), target: state.byId.get(edge.targetId),
    })).filter(edge => edge.source && edge.target);
    state.neighbors = new Map(nodes.map(node => [node.id, new Set()]));
    state.edges.forEach(edge => {
      state.neighbors.get(edge.sourceId).add(edge.targetId);
      state.neighbors.get(edge.targetId).add(edge.sourceId);
    });
    applyFilters();
    fitGraph();
    startIntro();
  }

  function applyFilters() {
    if (!state.data) return;
    const query = ui.search.value.trim().toLocaleLowerCase("pt-BR");
    const regionalFilter = ui.regional.value;
    const typeFilter = ui.type.value;
    const allowed = new Set();
    const matchingParents = new Set();

    state.nodes.forEach(node => {
      if (node.kind !== "regional") return;
      const matchesRegional = !regionalFilter || node.id === regionalFilter;
      const matchesText = !query || `${node.nome} ${node.codigo}`.toLocaleLowerCase("pt-BR").includes(query);
      if (matchesRegional && matchesText) matchingParents.add(node.id);
    });
    state.nodes.forEach(node => {
      if (node.kind !== "device") return;
      const matchesRegional = !regionalFilter || node.regional_id === regionalFilter;
      const matchesType = !typeFilter || node.tipo === typeFilter;
      const matchesText = !query || node.nome.toLocaleLowerCase("pt-BR").includes(query);
      if (matchesRegional && matchesType && matchesText) {
        allowed.add(node.id);
        allowed.add(node.regional_id);
      }
    });
    if (!typeFilter) matchingParents.forEach(id => allowed.add(id));
    if (!query && !regionalFilter && !typeFilter) state.nodes.forEach(node => allowed.add(node.id));

    state.visibleNodes = state.nodes.filter(node => allowed.has(node.id));
    state.visibleEdges = state.edges.filter(edge => allowed.has(edge.sourceId) && allowed.has(edge.targetId));
    if (state.hover && !allowed.has(state.hover.id)) state.hover = null;
    renderTable();
  }

  function populateUi() {
    const summary = state.data.resumo;
    ui.metrics.innerHTML = [
      [summary.regionais, "Regionais"], [summary.dispositivos, "Dispositivos"],
      [summary.conexoes, "Conexões"], [summary.categorias, "Tipos"],
    ].map(([value, label]) => `<div class="metric"><strong>${value}</strong><small>${label}</small></div>`).join("");

    state.data.regionais.forEach(regional => {
      ui.regional.insertAdjacentHTML("beforeend", `<option value="${escapeHtml(regional.id)}">${escapeHtml(regional.nome)}</option>`);
    });
    Object.entries(categories).forEach(([key, item]) => {
      ui.type.insertAdjacentHTML("beforeend", `<option value="${key}">${item.label}</option>`);
    });

    const connected = [...state.data.regionais].sort((a, b) => b.dispositivos.length - a.dispositivos.length).slice(0, 7);
    renderRanking(ui.connectionRank, connected, item => item.dispositivos.length);
    ui.categoryRank.innerHTML = Object.entries(categories).map(([key, item]) => `
      <div class="category-row" data-type="${key}" style="--category:${item.color}">
        <i></i><span>${item.label}</span><b>${state.data.categorias[key] || 0}</b>
      </div>`).join("");
    ui.legend.innerHTML = Object.values(categories).map(item => `<span style="--category:${item.color}"><i></i>${item.singular}</span>`).join("");
    const stamp = state.data.source_updated_at ? new Date(state.data.source_updated_at) : new Date(state.data.generated_at);
    ui.sync.textContent = `TOPOLOGIA ATUALIZADA ${stamp.toLocaleString("pt-BR")}`;
  }

  function renderRanking(container, rows, valueFn) {
    const max = Math.max(...rows.map(valueFn), 1);
    container.innerHTML = rows.map(item => {
      const value = valueFn(item);
      return `<div class="rank-row" data-id="${escapeHtml(item.id)}"><span class="rank-name">${escapeHtml(item.nome)}</span><span class="rank-bar"><i style="width:${value / max * 100}%"></i></span><span class="rank-value">${value}</span></div>`;
    }).join("");
  }

  function renderTable() {
    if (!state.data) return;
    const query = ui.search.value.trim().toLocaleLowerCase("pt-BR");
    const regionalFilter = ui.regional.value;
    const typeFilter = ui.type.value;
    if (regionalFilter) state.tableExpanded.add(regionalFilter);

    const deviceMatchesQuery = device => !query || `${device.nome} ${device.detalhe || ""} ${(device.detalhes || []).map(item => `${item.rotulo} ${item.valor}`).join(" ")}`
      .toLocaleLowerCase("pt-BR").includes(query);
    const rows = state.data.regionais.map(regional => {
      if (regionalFilter && regional.id !== regionalFilter) return "";
      const regionalMatchesQuery = !query || `${regional.nome} ${regional.codigo} ${regional.uf || ""}`
        .toLocaleLowerCase("pt-BR").includes(query);
      const allDevices = state.data.dispositivos.filter(device => device.regional_id === regional.id);
      const devices = allDevices.filter(device => (
        (!typeFilter || device.tipo === typeFilter)
        && (regionalMatchesQuery || deviceMatchesQuery(device))
      ));
      if ((typeFilter || query) && !devices.length && !regionalMatchesQuery) return "";
      if (typeFilter && !devices.length) return "";

      const expanded = state.tableExpanded.has(regional.id);
      const filteredLabel = typeFilter ? categories[typeFilter].label : "dispositivos";
      const sections = expanded ? Object.entries(categories).map(([type, category]) => {
        if (typeFilter && type !== typeFilter) return "";
        const entries = devices.filter(device => device.tipo === type);
        if (!entries.length) return "";
        return `<section class="table-device-section" style="--category:${category.color}">
          <header><span><i></i>${category.label}</span><b>${entries.length}</b></header>
          <div class="table-device-grid">${entries.map(device => `
            <article class="table-device-card">
              <button type="button" data-device-id="${escapeHtml(device.id)}">${escapeHtml(device.nome)}</button>
              ${device.detalhe ? `<p>${escapeHtml(device.detalhe)}</p>` : ""}
              <dl>${(device.detalhes || []).length
                ? device.detalhes.map(detail => `<div><dt>${escapeHtml(detail.rotulo)}</dt><dd>${escapeHtml(detail.valor)}</dd></div>`).join("")
                : `<div><dt>Informacao</dt><dd>Sem outros dados registrados</dd></div>`}
              </dl>
            </article>`).join("")}</div>
        </section>`;
      }).join("") : "";

      return `<tr class="regional-table-row ${expanded ? "expanded" : ""}" data-table-regional="${escapeHtml(regional.id)}">
        <td><button type="button" class="table-expand" aria-expanded="${expanded}"><span>${expanded ? "-" : "+"}</span><strong>${escapeHtml(regional.nome)}</strong><small>${escapeHtml(regional.codigo)}</small></button></td>
        <td><span class="table-uf">${escapeHtml(regional.uf || "-")}</span></td>
        <td><strong>${devices.length}</strong><small class="table-filter-caption">${escapeHtml(filteredLabel)}</small></td>
        <td>${regional.status ? `<span class="table-status">${escapeHtml(regional.status)}</span>` : "-"}</td>
        <td>${escapeHtml(regional.ultima_atualizacao || "-")}</td>
      </tr>
      <tr class="regional-table-detail" data-table-detail="${escapeHtml(regional.id)}" ${expanded ? "" : "hidden"}>
        <td colspan="5"><div class="regional-table-content">
          ${regional.descricao ? `<p class="table-regional-description">${escapeHtml(regional.descricao)}</p>` : ""}
          ${sections || `<p class="table-empty">Nenhum dispositivo corresponde aos filtros atuais.</p>`}
        </div></td>
      </tr>`;
    }).join("");
    ui.tableBody.innerHTML = rows || `<tr><td colspan="5"><p class="table-empty">Nenhuma regional corresponde aos filtros atuais.</p></td></tr>`;
  }

  function exportTableRows() {
    if (!state.data) return [];
    const query = ui.search.value.trim().toLocaleLowerCase("pt-BR");
    const regionalFilter = ui.regional.value;
    const typeFilter = ui.type.value;
    const rows = [];
    state.data.regionais.forEach(regional => {
      if (regionalFilter && regional.id !== regionalFilter) return;
      const regionalMatches = !query || `${regional.nome} ${regional.codigo} ${regional.uf || ""}`
        .toLocaleLowerCase("pt-BR").includes(query);
      const devices = state.data.dispositivos.filter(device => {
        if (device.regional_id !== regional.id || typeFilter && device.tipo !== typeFilter) return false;
        const text = `${device.nome} ${device.detalhe || ""} ${(device.detalhes || []).map(item => `${item.rotulo} ${item.valor}`).join(" ")}`
          .toLocaleLowerCase("pt-BR");
        return regionalMatches || !query || text.includes(query);
      });
      if ((typeFilter || query) && !devices.length && !regionalMatches) return;
      if (typeFilter && !devices.length) return;
      const base = {
        regional: regional.nome,
        codigo: regional.codigo,
        uf: regional.uf || "",
        status: regional.status || "",
        atualizacao: regional.ultima_atualizacao || "",
      };
      if (!devices.length) {
        rows.push({ ...base, categoria: "", dispositivo: "", resumo: "", detalhes: [] });
        return;
      }
      devices.forEach(device => {
        rows.push({
          ...base,
          categoria: categories[device.tipo]?.singular || device.tipo,
          dispositivo: device.nome,
          resumo: device.detalhe || "",
          detalhes: (device.detalhes || []).map(detail => ({
            rotulo: detail.rotulo || "",
            valor: detail.valor || "",
          })),
        });
      });
    });
    return rows;
  }

  function exportFilterDescription() {
    const parts = [];
    if (ui.regional.value) parts.push(`Regional: ${ui.regional.options[ui.regional.selectedIndex]?.text || ui.regional.value}`);
    if (ui.type.value) parts.push(`Tipo: ${categories[ui.type.value]?.label || ui.type.value}`);
    if (ui.search.value.trim()) parts.push(`Busca: ${ui.search.value.trim()}`);
    return parts.length ? parts.join(" | ") : "Todas as regionais e conexoes";
  }

  function exportPdf() {
    const rows = exportTableRows();
    if (!rows.length) { toast("Nao ha dados nos filtros atuais para exportar."); return; }
    const report = window.open("", "sentinel-fluxo-neural-pdf");
    if (!report) { toast("O navegador bloqueou a janela de exportacao."); return; }
    const generatedAt = new Date().toLocaleString("pt-BR");
    report.document.write(`<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>Fluxo Neural de Redes - Sentinel</title><style>
      @page{size:A4 landscape;margin:9mm}*{box-sizing:border-box}body{margin:0;color:#173042;font:9px Arial,sans-serif}header{display:flex;justify-content:space-between;align-items:flex-end;margin-bottom:9px;border-bottom:2px solid #07517d;padding-bottom:7px}h1{margin:0;color:#07517d;font-size:18px}p{margin:3px 0 0;color:#526b7a}.report-meta{color:#6d818d;text-align:right}.report-count{display:block;margin-top:3px;color:#07517d;font-weight:700}table{width:100%;border-collapse:collapse;table-layout:fixed}thead{display:table-header-group}tr{break-inside:avoid;page-break-inside:avoid}th{padding:6px 5px;background:#07517d;color:white;text-align:left;font-size:8px}td{padding:5px;border:1px solid #cbd9e1;vertical-align:top;overflow-wrap:anywhere}tbody tr:nth-child(even) td{background:#f2f7fa}.regional strong,.device-name{display:block;color:#0b344b}.regional small,.device-summary{display:block;margin-top:2px;color:#6d818d}.status{display:inline-block;margin-top:3px;padding:2px 4px;border-radius:3px;background:#e5f6f1;color:#087354;font-size:7px}.details{display:grid;grid-template-columns:max-content minmax(0,1fr);gap:2px 7px;margin:0}.details dt{color:#526b7a;font-weight:700}.details dd{margin:0;color:#173042}.empty{color:#8799a4;font-style:italic}th:nth-child(1){width:18%}th:nth-child(2){width:4%}th:nth-child(3){width:10%}th:nth-child(4){width:18%}th:nth-child(5){width:15%}th:nth-child(6){width:35%}
    </style></head><body><header><div><h1>SENTINEL | FLUXO NEURAL DE REDES</h1><p>${escapeHtml(exportFilterDescription())}</p></div><div class="report-meta">Gerado em ${escapeHtml(generatedAt)}<span class="report-count">${rows.length} registro(s)</span></div></header><table><thead><tr><th>Regional</th><th>UF</th><th>Categoria</th><th>Dispositivo</th><th>Resumo</th><th>Detalhes</th></tr></thead><tbody>${rows.map(row => `<tr><td class="regional"><strong>${escapeHtml(row.regional)}</strong><small>${escapeHtml(row.codigo)}</small>${row.status ? `<span class="status">${escapeHtml(row.status)}</span>` : ""}<small>${escapeHtml(row.atualizacao)}</small></td><td>${escapeHtml(row.uf)}</td><td>${escapeHtml(row.categoria)}</td><td><strong class="device-name">${escapeHtml(row.dispositivo)}</strong></td><td><span class="device-summary">${escapeHtml(row.resumo)}</span></td><td>${row.detalhes.length ? `<dl class="details">${row.detalhes.map(detail => `<dt>${escapeHtml(detail.rotulo)}</dt><dd>${escapeHtml(detail.valor)}</dd>`).join("")}</dl>` : `<span class="empty">Sem outros detalhes registrados</span>`}</td></tr>`).join("")}</tbody></table><script>window.addEventListener("load",()=>{window.focus();window.print()});window.addEventListener("afterprint",()=>window.close());<\/script></body></html>`);
    report.document.close();
  }

  async function exportXlsx() {
    const rows = exportTableRows();
    if (!rows.length) { toast("Nao ha dados nos filtros atuais para exportar."); return; }
    const params = new URLSearchParams();
    if (ui.regional.value) params.set("regional", ui.regional.value);
    if (ui.type.value) params.set("tipo", ui.type.value);
    if (ui.search.value.trim()) params.set("busca", ui.search.value.trim());
    ui.exportXlsx.disabled = true;
    try {
      const response = await fetch(`/api/fluxo-neural/exportar.xlsx?${params}`, {
        credentials: "same-origin", cache: "no-store",
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const blob = await response.blob();
      const disposition = response.headers.get("Content-Disposition") || "";
      const match = disposition.match(/filename\*?=(?:UTF-8'')?"?([^";]+)"?/i);
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = decodeURIComponent(match?.[1] || "fluxo_neural_sentinel.xlsx");
      document.body.appendChild(link);
      link.click();
      const objectUrl = link.href;
      link.remove();
      setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
    } catch (error) {
      console.error(error);
      toast("Nao foi possivel exportar o arquivo XLSX.");
    } finally {
      ui.exportXlsx.disabled = false;
    }
  }

  function selectRegional(id) {
    const regional = state.data.regionais.find(item => item.id === id);
    if (!regional) return;
    state.selected = state.byId.get(id);
    const devices = state.data.dispositivos.filter(device => device.regional_id === id);
    ui.detail.innerHTML = `
      <div class="detail-kicker">${escapeHtml(regional.uf || "Regional Sentinel")}</div>
      <h2>${escapeHtml(regional.nome)}</h2><div class="detail-code">${escapeHtml(regional.codigo)}</div>
      ${regional.descricao ? `<p class="detail-description">${escapeHtml(regional.descricao)}</p>` : ""}
      ${(regional.status || regional.ultima_atualizacao) ? `<div class="detail-summary">
        ${regional.status ? `<span><small>Status</small><strong>${escapeHtml(regional.status)}</strong></span>` : ""}
        ${regional.ultima_atualizacao ? `<span><small>Atualizacao</small><strong>${escapeHtml(regional.ultima_atualizacao)}</strong></span>` : ""}
      </div>` : ""}
      <div class="detail-grid">
        ${Object.entries(categories).map(([key, item]) => `<div class="detail-item"><strong>${regional.totais[key] || 0}</strong><small>${item.label}</small></div>`).join("")}
      </div>
      ${Object.entries(categories).map(([key, item]) => {
        const entries = devices.filter(device => device.tipo === key);
        if (!entries.length) return "";
        return `<section class="device-section" style="--category:${item.color}"><h3>${item.label}</h3><div class="device-list">${entries.map(device => `<button type="button" class="device-chip" data-device-id="${escapeHtml(device.id)}">${escapeHtml(device.nome)}${device.detalhe ? `<small>${escapeHtml(device.detalhe)}</small>` : ""}</button>`).join("")}</div></section>`;
      }).join("")}`;
    ui.panel.classList.add("open");
  }

  function selectDevice(id) {
    const device = state.byId.get(id);
    if (!device || device.kind !== "device") return;
    const regional = state.data.regionais.find(item => item.id === device.regional_id);
    const category = categories[device.tipo];
    state.selected = device;
    const details = Array.isArray(device.detalhes) ? device.detalhes : [];
    ui.detail.innerHTML = `
      <div class="detail-kicker" style="color:${category.color}">${escapeHtml(category.singular)}</div>
      <h2>${escapeHtml(device.nome)}</h2>
      <button type="button" class="regional-context" data-regional-id="${escapeHtml(device.regional_id)}">
        <span>Regional</span><strong>${escapeHtml(regional?.nome || device.regional_id)}</strong>
      </button>
      ${device.detalhe ? `<p class="detail-description">${escapeHtml(device.detalhe)}</p>` : ""}
      <dl class="device-details">
        ${details.length ? details.map(item => `<div><dt>${escapeHtml(item.rotulo)}</dt><dd>${escapeHtml(item.valor)}</dd></div>`).join("") : `<div><dt>Informacao</dt><dd>Sem outros dados operacionais registrados.</dd></div>`}
      </dl>`;
    ui.panel.classList.add("open");
  }

  function focusBase() {
    return state.hover || state.selected;
  }

  function focusSet() {
    const candidate = focusBase();
    if (!candidate) return null;
    if (candidate.kind === "device") {
      return new Set([candidate.id, candidate.regional_id]);
    }
    return new Set([candidate.id, ...(state.neighbors.get(candidate.id) || [])]);
  }

  function targetPoint(node, followCurrentParent = false) {
    if (node.kind !== "device") return { x: node.tx, y: node.ty };
    const parent = state.byId.get(node.parentId);
    if (!parent) return { x: node.tx, y: node.ty };
    return {
      x: (followCurrentParent ? parent.x : parent.tx) + node.offsetX,
      y: (followCurrentParent ? parent.y : parent.ty) + node.offsetY,
    };
  }

  function fitGraph() {
    const nodes = state.visibleNodes.length ? state.visibleNodes : state.nodes;
    if (!nodes.length) return;
    const targets = nodes.map(node => targetPoint(node));
    const xs = targets.map(point => point.x), ys = targets.map(point => point.y);
    const minX = Math.min(...xs), maxX = Math.max(...xs);
    const minY = Math.min(...ys), maxY = Math.max(...ys);
    const centerX = (minX + maxX) / 2;
    const centerY = (minY + maxY) / 2;
    const width = maxX - minX + 360;
    const height = maxY - minY + 320;
    const reservedLeft = innerWidth > 760 ? 320 : 16;
    state.camera.scale = clamp(Math.min((innerWidth - reservedLeft - 30) / width, (innerHeight - 110) / height), .12, 1.25);
    const hub = nodes.find(node => node.isHub);
    const overview = !ui.search.value.trim() && !ui.regional.value && !ui.type.value;
    state.camera.x = reservedLeft / 2 - (hub && overview ? hub.tx : centerX) * state.camera.scale;
    state.camera.y = 42 - (hub && overview ? hub.ty : centerY) * state.camera.scale;
  }

  function reorganize() {
    state.nodes.forEach(node => {
      const target = targetPoint(node);
      node.x = node.isHub ? target.x : target.x + (Math.random() - .5) * (node.kind === "regional" ? 160 : 45);
      node.y = node.isHub ? target.y : target.y + (Math.random() - .5) * (node.kind === "regional" ? 130 : 45);
      node.vx = node.vy = 0;
    });
  }

  function worldPoint(clientX, clientY) {
    return {
      x: (clientX - innerWidth / 2 - state.camera.x) / state.camera.scale,
      y: (clientY - innerHeight / 2 - state.camera.y) / state.camera.scale,
    };
  }

  function nodeAt(clientX, clientY) {
    const point = worldPoint(clientX, clientY);
    return [...state.visibleNodes].reverse().find(node => {
      const celestialRadius = node.kind === "regional" && !node.isHub
        ? node.radius * 1.5
        : node.isHub ? node.radius * 1.7 : node.tipo === "redes_wifi"
        ? 30
        : ["links", "firewalls", "servidores", "switches", "vpns", "aps"].includes(node.tipo) ? 30 : node.radius;
      return Math.hypot(node.x - point.x, node.y - point.y) <= celestialRadius + 10 / state.camera.scale;
    });
  }

  function updatePhysics() {
    if (!state.data || (state.intro && !state.intro.done)) return;
    state.nodes.forEach((node, index) => {
      if (node === state.dragNode) return;
      const target = targetPoint(node, node.kind === "device");
      const driftX = node.isHub ? 0 : Math.sin(state.time * .00022 + index * 1.7) * (node.kind === "regional" ? 8 : 5);
      const driftY = node.isHub ? 0 : Math.cos(state.time * .00018 + index * 1.3) * (node.kind === "regional" ? 7 : 5);
      const spring = node.isHub ? .004 : node.kind === "regional" ? .00045 : .0032;
      const damping = node.isHub ? .9 : node.kind === "regional" ? .94 : .9;
      node.vx += (target.x + driftX - node.x) * spring;
      node.vy += (target.y + driftY - node.y) * spring;
      node.vx *= damping; node.vy *= damping; node.x += node.vx; node.y += node.vy;
    });
  }

  function drawBackground() {
    if (galaxyBackground.complete && galaxyBackground.naturalWidth) {
      const cover = Math.max(innerWidth / galaxyBackground.naturalWidth, innerHeight / galaxyBackground.naturalHeight);
      const galaxyZoom = 1.22 + clamp((state.camera.scale - 1) * .055, -.04, .08);
      const width = galaxyBackground.naturalWidth * cover * galaxyZoom;
      const height = galaxyBackground.naturalHeight * cover * galaxyZoom;
      const travelX = clamp(state.camera.x * .075, -Math.max((width - innerWidth) / 2, 0), Math.max((width - innerWidth) / 2, 0));
      const travelY = clamp(state.camera.y * .075, -Math.max((height - innerHeight) / 2, 0), Math.max((height - innerHeight) / 2, 0));
      const renderedBackground = cachedGalaxyBackground();
      if (renderedBackground) {
        ctx.save();
        ctx.globalAlpha = .92;
        ctx.drawImage(renderedBackground, (innerWidth - width) / 2 + travelX, (innerHeight - height) / 2 + travelY, width, height);
        ctx.restore();
      }
    } else {
      ctx.fillStyle = "#020810"; ctx.fillRect(0, 0, innerWidth, innerHeight);
    }
    const gradient = ctx.createRadialGradient(innerWidth * .58, innerHeight * .47, 0, innerWidth * .58, innerHeight * .47, Math.max(innerWidth, innerHeight) * .8);
    gradient.addColorStop(0, "rgba(4,16,27,.03)"); gradient.addColorStop(.55, "rgba(3,12,21,.12)"); gradient.addColorStop(1, "rgba(1,5,10,.38)");
    ctx.fillStyle = gradient; ctx.fillRect(0, 0, innerWidth, innerHeight);

    const fieldWidth = innerWidth + 160;
    const fieldHeight = innerHeight + 160;
    state.stars.forEach((star, index) => {
      const rawX = star.u * fieldWidth + state.camera.x * star.depth * .16;
      const rawY = star.v * fieldHeight + state.camera.y * star.depth * .16;
      const x = ((rawX % fieldWidth) + fieldWidth) % fieldWidth - 80;
      const y = ((rawY % fieldHeight) + fieldHeight) % fieldHeight - 80;
      const twinkle = .72 + Math.sin(state.time * (.00065 + star.depth * .00035) + star.phase) * .28;
      const radius = star.size * (.72 + star.depth * .42);
      ctx.beginPath(); ctx.arc(x, y, radius, 0, Math.PI * 2);
      ctx.globalAlpha = star.alpha * twinkle;
      ctx.fillStyle = index % 11 === 0 ? "#79d9ff" : "#e8f7ff";
      if (radius > 1.4) { ctx.shadowColor = "#54cfff"; ctx.shadowBlur = 7; }
      ctx.fill(); ctx.shadowBlur = 0;
    });
    ctx.globalAlpha = 1;
  }

  function roundedRect(x, y, width, height, radius) {
    ctx.beginPath(); ctx.roundRect(x, y, width, height, radius);
  }

  function drawGraph() {
    const focus = focusSet();
    const base = focusBase();
    ctx.save();
    ctx.translate(innerWidth / 2 + state.camera.x, innerHeight / 2 + state.camera.y);
    ctx.scale(state.camera.scale, state.camera.scale);

    state.visibleEdges.forEach((edge, index) => {
      const focused = !focus || edge.source === base || edge.target === base;
      const backbone = edge.kind === "backbone";
      const color = backbone ? "#4bbde8" : categories[edge.type].color;
      const opacity = (
        focus ? (focused ? (backbone ? .62 : .95) : state.selected ? 0 : .025) : (backbone ? .16 : .2)
      ) * Math.min(edge.source.opacity, edge.target.opacity);
      if (opacity < .01) return;
      const dx = edge.target.x - edge.source.x, dy = edge.target.y - edge.source.y;
      const length = Math.max(Math.hypot(dx, dy), 1);
      const sway = Math.sin(state.time * .00115 + edge.phase * Math.PI * 2 + index * .31) * 10;
      const bend = Math.sin(edge.phase * Math.PI * 2) * 7;
      const qx = (edge.source.x + edge.target.x) / 2 - dy / length * (sway + bend);
      const qy = (edge.source.y + edge.target.y) / 2 + dx / length * (sway + bend);
      ctx.beginPath(); ctx.moveTo(edge.source.x, edge.source.y); ctx.quadraticCurveTo(qx, qy, edge.target.x, edge.target.y);
      ctx.strokeStyle = color; ctx.globalAlpha = opacity;
      ctx.lineWidth = (backbone ? .65 : focused && focus ? 1.8 : .8) / state.camera.scale; ctx.stroke();
      if (focused && focus && !backbone) {
        for (let particle = 0; particle < 2; particle += 1) {
          const t = (state.time * .00028 + edge.phase + particle * .5 + index * .013) % 1;
          const one = 1 - t;
          const x = one * one * edge.source.x + 2 * one * t * qx + t * t * edge.target.x;
          const y = one * one * edge.source.y + 2 * one * t * qy + t * t * edge.target.y;
          ctx.beginPath(); ctx.arc(x, y, 2.4 / state.camera.scale, 0, Math.PI * 2);
          ctx.globalAlpha = .95; ctx.fillStyle = color; ctx.shadowColor = color; ctx.shadowBlur = 12 / state.camera.scale; ctx.fill(); ctx.shadowBlur = 0;
        }
      }
    });
    ctx.globalAlpha = 1;

    state.visibleNodes.forEach(node => {
      const inFocus = !focus || focus.has(node.id);
      const active = node === state.hover || node === state.selected;
      const color = node.kind === "regional" ? "#22c3f6" : categories[node.tipo].color;
      const opacity = node.opacity * (inFocus ? 1 : state.selected ? 0 : .09);
      if (opacity < .01) return;
      ctx.globalAlpha = opacity;
      const radius = node.radius * (active ? 1.14 : 1);
      let labelRadius = radius;
      const haloRadius = radius * (active ? 3.35 : 2.65);
      const halo = ctx.createRadialGradient(node.x, node.y, radius * .4, node.x, node.y, haloRadius);
      halo.addColorStop(0, `${color}${active ? "a0" : "68"}`);
      halo.addColorStop(.48, `${color}${active ? "48" : "2e"}`);
      halo.addColorStop(1, `${color}00`);
      ctx.fillStyle = halo; ctx.beginPath(); ctx.arc(node.x, node.y, haloRadius, 0, Math.PI * 2); ctx.fill();
      const earth = node.kind === "regional" && !node.isHub ? celestialTextures.get("TERRA") : null;
      if (node.isHub) {
        const width = radius * 3.8;
        const height = radius * 2.25;
        labelRadius = height / 2;
        ctx.save();
        ctx.shadowColor = "#55ccff";
        ctx.shadowBlur = (active ? 28 : 18) / state.camera.scale;
        if (galaxyNodeTexture.complete && galaxyNodeTexture.naturalWidth) {
          ctx.drawImage(galaxyNodeTexture, node.x - width / 2, node.y - height / 2, width, height);
        } else {
          const texture = planetTexture("ANDROMEDA");
          ctx.drawImage(texture, node.x - radius, node.y - radius, radius * 2, radius * 2);
        }
        ctx.restore();
      } else if (earth) {
        const width = radius * 2.9;
        const height = radius * 2.9;
        labelRadius = height / 2;
        const renderedEarth = cachedCelestialTexture(earth, "regional:earth", 176, 176);
        if (renderedEarth) {
          ctx.save();
          ctx.translate(node.x, node.y);
          ctx.rotate(Math.sin(state.time * .0002 + stableNameHash(node.id)) * .018);
          ctx.shadowColor = active ? "#8ee9ff" : "#22c3f6";
          ctx.shadowBlur = (active ? 24 : 10) / state.camera.scale;
          ctx.drawImage(renderedEarth, -width / 2, -height / 2, width, height);
          ctx.restore();
        }
      } else if (!["redes_wifi", "links", "firewalls", "servidores", "switches", "vpns", "aps"].includes(node.tipo)) {
        ctx.beginPath(); ctx.arc(node.x, node.y, radius, 0, Math.PI * 2);
        ctx.fillStyle = node.kind === "regional" ? "#e9f8ff" : "#071725";
        ctx.strokeStyle = color; ctx.lineWidth = active ? 3 / state.camera.scale : 1.5 / state.camera.scale; ctx.fill(); ctx.stroke();
      }
      const celestial = celestialTexture(node);
      if (!node.isHub && celestial) {
        const key = normalizeCelestialName(node.nome);
        const isAndromeda = key === "ANDROMEDA";
        const isSaturn = key === "SATURNO";
        const isLink = node.tipo === "links";
        const isFirewall = node.tipo === "firewalls";
        const isStar = node.tipo === "servidores";
        const isSwitch = node.tipo === "switches";
        const isVpn = node.tipo === "vpns";
        const isAp = node.tipo === "aps";
        const firewallKey = isFirewall ? firewallCelestialKey(node.nome) : "";
        const switchKey = isSwitch ? switchCelestialKey(node.nome) : "";
        const vpnKey = isVpn ? vpnCelestialKey(node.nome) : "";
        const apKey = isAp ? apCelestialKey(node.nome) : "";
        const width = radius * (isAndromeda ? 4.4 : isSaturn ? 3.8 : isLink ? 4.8 : isFirewall ? 4.2 : isAp ? 3.8 : isStar ? 3.35 : isVpn ? 3.4 : isSwitch ? 2.9 : 2.7);
        const height = radius * (isAndromeda ? 2.2 : isSaturn ? 2.55 : isLink ? 2.05 : isFirewall ? 3.2 : isAp ? 3.8 : isStar ? 3.35 : isVpn ? 3.4 : isSwitch ? 2.9 : 2.7);
        labelRadius = Math.max(labelRadius, height / 2);
        const detailThreshold = isStar ? .52 : isAp ? .48 : isFirewall ? .42 : isVpn ? .42 : isLink ? .38 : isSwitch ? .34 : 0;
        const detailedCelestial = state.camera.scale >= detailThreshold || active || (focus && inFocus);

        if (detailedCelestial) {
          const cacheWidth = isAndromeda ? 256 : isSaturn ? 256 : isLink ? 224 : isFirewall ? 192 : isAp ? 160 : isVpn ? 160 : isStar ? 128 : isSwitch ? 144 : 192;
          const cacheHeight = isAndromeda ? 128 : isSaturn ? 172 : isLink ? 76 : isFirewall ? 146 : isAp ? 160 : isVpn ? 160 : isStar ? 128 : isSwitch ? 144 : 192;
          const filter = isStar ? stellarFilter(node.nome) : "none";
          const textureKey = isStar ? `star:${filter}` : isLink ? "COMETA_LINK" : isFirewall ? firewallKey : isSwitch ? switchKey : isVpn ? vpnKey : isAp ? apKey : key;
          const renderedTexture = cachedCelestialTexture(
            celestial, textureKey, cacheWidth, cacheHeight, filter,
          );

          if (renderedTexture) {
            ctx.save();
            if (active) {
              ctx.shadowColor = isFirewall ? "#ff4d68" : isStar ? color : "#69d9ff";
              ctx.shadowBlur = 18 / state.camera.scale;
            }
            if (isLink) {
              const parent = state.byId.get(node.parentId);
              const direction = parent ? Math.atan2(node.y - parent.y, node.x - parent.x) : 0;
              const sway = Math.sin(state.time * .0012 + stableNameHash(node.nome)) * .035;
              ctx.translate(node.x, node.y);
              ctx.rotate(direction + sway);
              ctx.drawImage(renderedTexture, -width / 2, -height / 2, width, height);
            } else if (isAp) {
              const rotation = ((stableNameHash(node.nome) % 13) - 6) * .07;
              ctx.translate(node.x, node.y);
              ctx.rotate(rotation);
              ctx.drawImage(renderedTexture, -width / 2, -height / 2, width, height);
            } else {
              ctx.drawImage(renderedTexture, node.x - width / 2, node.y - height / 2, width, height);
            }
            ctx.restore();
          }
        } else {
          ctx.save();
          ctx.globalAlpha = opacity * .78;
          ctx.fillStyle = isLink || isFirewall || isSwitch || isVpn || isAp ? color : "#eaf8ff";
          ctx.beginPath();
          ctx.arc(node.x, node.y, Math.max(3.2, radius * .28), 0, Math.PI * 2);
          ctx.fill();
          ctx.restore();
        }
      } else if (!node.isHub && node.tipo === "redes_wifi") {
        const texture = planetTexture(node.nome);
        const size = radius * 2.7;
        labelRadius = size / 2;
        ctx.drawImage(texture, node.x - size / 2, node.y - size / 2, size, size);
      } else if (!node.isHub && !earth && !["links", "firewalls", "servidores", "switches", "vpns", "aps"].includes(node.tipo)) {
        ctx.fillStyle = node.kind === "regional" ? "#07517d" : color;
        ctx.textAlign = "center"; ctx.textBaseline = "middle";
        ctx.font = `${node.kind === "regional" ? 800 : 700} ${node.kind === "regional" ? 10 : 7}px Consolas, monospace`;
        ctx.fillText(node.kind === "regional" ? (node.uf || node.codigo.replace("REG_", "").slice(0, 3)) : categories[node.tipo].mono, node.x, node.y + .5);
      }

      const showLabel = node.kind === "regional" || inFocus && focus || state.camera.scale > .58;
      if (showLabel) {
        const limit = node.kind === "regional" ? 32 : 40;
        const label = node.nome.length > limit ? `${node.nome.slice(0, limit - 1)}…` : node.nome;
        ctx.font = `${node.kind === "regional" ? 650 : 600} ${node.kind === "regional" ? 10 : 8}px Segoe UI, sans-serif`;
        const width = clamp(ctx.measureText(label).width + 10, 35, 220);
        roundedRect(node.x - width / 2, node.y + labelRadius + 6, width, node.kind === "regional" ? 19 : 16, 4);
        ctx.fillStyle = "rgba(3,12,21,.88)"; ctx.fill();
        ctx.fillStyle = inFocus ? "#e5f1f7" : "#7690a1";
        ctx.fillText(label, node.x, node.y + labelRadius + (node.kind === "regional" ? 15.5 : 14));
      }
    });
    ctx.globalAlpha = 1; ctx.restore();
  }

  function createCracks() {
    const count = 10;
    const angles = Array.from({ length: count }, (_, index) => (index + .2 + Math.random() * .55) / count * Math.PI * 2);
    const rays = angles.map(angle => {
      const points = [[0, 0]]; let radius = 0;
      while (radius < 1.5) {
        radius += .12 + Math.random() * .13;
        const bend = angle + (Math.random() - .5) * .28;
        points.push([Math.cos(bend) * radius, Math.sin(bend) * radius]);
      }
      return points;
    });
    const shards = angles.map((angle, index) => {
      const next = rays[(index + 1) % count];
      return {
        polygon: [...rays[index], ...next.slice(1).reverse()], angle: angle + Math.PI / count,
        spin: (Math.random() - .5) * 2.5, speed: .75 + Math.random() * .65,
      };
    });
    return { rays, shards };
  }

  const cracks = createCracks();
  function strokePartial(points, progress, unit) {
    if (progress <= 0) return;
    const lengths = points.slice(1).map((point, index) => Math.hypot(point[0] - points[index][0], point[1] - points[index][1]));
    let remaining = progress * lengths.reduce((total, value) => total + value, 0);
    ctx.beginPath(); ctx.moveTo(points[0][0] * unit, points[0][1] * unit);
    for (let index = 1; index < points.length; index += 1) {
      const length = lengths[index - 1];
      if (remaining >= length) { ctx.lineTo(points[index][0] * unit, points[index][1] * unit); remaining -= length; }
      else {
        const ratio = remaining / length;
        ctx.lineTo((points[index - 1][0] + (points[index][0] - points[index - 1][0]) * ratio) * unit, (points[index - 1][1] + (points[index][1] - points[index - 1][1]) * ratio) * unit);
        break;
      }
    }
    ctx.stroke();
  }

  function circleClip(unit) { ctx.beginPath(); ctx.arc(0, 0, unit * .92, 0, Math.PI * 2); ctx.clip(); }

  function drawIntro() {
    if (!state.intro || state.intro.done || !introLogo.complete) return;
    const elapsed = (performance.now() - state.intro.start) / 1000;
    const size = Math.min(innerWidth, innerHeight) * .3;
    const unit = size / 2;
    const centerX = innerWidth / 2;
    const centerY = innerHeight / 2 - unit * .42;
    const crackStart = 3.35;
    const crackEnd = 5.8;
    const burst = state.intro.burst;

    if (elapsed < burst) {
      const grow = easeOutBack(elapsed / .75);
      const crackProgress = clamp((elapsed - crackStart) / (crackEnd - crackStart), 0, 1);
      const strain = clamp((elapsed - crackEnd) / (burst - crackEnd), 0, 1);
      const shake = crackProgress * 2 + strain * 7;
      ctx.save();
      ctx.translate(centerX + (Math.random() - .5) * shake, centerY + (Math.random() - .5) * shake);
      ctx.scale(grow * (1 + strain * .06), grow * (1 + strain * .06));
      const aura = ctx.createRadialGradient(0, 0, unit * .3, 0, 0, unit * 2.5);
      aura.addColorStop(0, `rgba(34,195,246,${.2 + crackProgress * .25})`); aura.addColorStop(1, "rgba(34,195,246,0)");
      ctx.fillStyle = aura; ctx.beginPath(); ctx.arc(0, 0, unit * 2.5, 0, Math.PI * 2); ctx.fill();
      ctx.drawImage(introLogo, -unit, -unit, size, size);
      if (crackProgress > 0) {
        ctx.save(); circleClip(unit); ctx.lineCap = "round"; ctx.lineJoin = "round";
        cracks.rays.forEach((ray, index) => {
          const progress = clamp((crackProgress - index / cracks.rays.length * .55) / .42, 0, 1);
          ctx.shadowColor = "#22c3f6"; ctx.shadowBlur = 16 + strain * 15;
          ctx.strokeStyle = "rgba(148,230,255,.95)"; ctx.lineWidth = 2.2 + strain * 2.5;
          strokePartial(ray, progress, unit);
        });
        ctx.restore();
      }
      ctx.restore();

      const fade = 1 - clamp((elapsed - 5.5) / .8, 0, 1);
      if (elapsed > .75 && fade > 0) {
        const titleSize = clamp(unit * .18, 18, 34);
        const titleY = centerY + unit * 1.25;
        ctx.globalAlpha = clamp((elapsed - .75) / .65, 0, 1) * fade;
        ctx.textAlign = "center"; ctx.textBaseline = "middle";
        ctx.font = `800 ${titleSize}px Segoe UI, sans-serif`;
        ctx.shadowColor = "#22c3f6"; ctx.shadowBlur = 20; ctx.fillStyle = "#f3fbff";
        ctx.fillText("SENTINEL", centerX, titleY);
        ctx.shadowBlur = 0; ctx.font = `650 ${titleSize * .55}px Segoe UI, sans-serif`; ctx.fillStyle = "#22c3f6";
        ctx.fillText("FLUXO NEURAL DE REDES", centerX, titleY + titleSize * 1.05);
        const message = "Todas as regionais e suas conexões em uma única malha.";
        const typed = Math.floor(message.length * clamp((elapsed - 1.65) / 1.6, 0, 1));
        ctx.font = `500 ${clamp(unit * .075, 12, 16)}px Segoe UI, sans-serif`; ctx.fillStyle = "#c4d8e4";
        ctx.fillText(message.slice(0, typed), centerX, titleY + titleSize * 2.05);
        if (elapsed < crackStart) {
          ctx.globalAlpha *= .65; ctx.font = "600 10px Consolas, monospace"; ctx.fillStyle = "#819cad";
          ctx.fillText("CLIQUE PARA AVANÇAR", centerX, titleY + titleSize * 2.85);
        }
        ctx.globalAlpha = 1;
      }
      return;
    }

    const progress = clamp((elapsed - burst) / 1.15, 0, 1);
    const eased = easeOutCubic(progress);
    cracks.shards.forEach(shard => {
      const distance = eased * unit * 3.4 * shard.speed;
      ctx.save();
      ctx.globalAlpha = 1 - progress * progress;
      ctx.translate(centerX + Math.cos(shard.angle) * distance, centerY + Math.sin(shard.angle) * distance + progress * progress * unit * .45);
      ctx.rotate(shard.spin * eased);
      ctx.beginPath(); shard.polygon.forEach(([x, y], index) => index ? ctx.lineTo(x * unit, y * unit) : ctx.moveTo(x * unit, y * unit)); ctx.closePath();
      ctx.save(); ctx.clip(); ctx.translate(-centerX, -centerY); ctx.drawImage(introLogo, centerX - unit, centerY - unit, size, size); ctx.restore();
      ctx.strokeStyle = `rgba(87,211,255,${1 - progress})`; ctx.lineWidth = 2; ctx.shadowColor = "#22c3f6"; ctx.shadowBlur = 12; ctx.stroke();
      ctx.restore();
    });
    const wave = easeOutCubic(progress);
    ctx.globalAlpha = 1 - progress; ctx.strokeStyle = "#22c3f6"; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.arc(centerX, centerY, unit * .8 + wave * Math.max(innerWidth, innerHeight) * .65, 0, Math.PI * 2); ctx.stroke();
    ctx.globalAlpha = 1;
  }

  function startIntro() {
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    state.intro = { start: performance.now(), burst: 6.5, duration: 1.45, done: reduce };
    if (reduce) {
      state.nodes.forEach(node => { node.x = node.tx; node.y = node.ty; node.opacity = 1; });
      document.body.classList.remove("intro-active");
      return;
    }
    state.nodes.forEach(node => { node.x = 0; node.y = 0; node.opacity = 0; });
  }

  function updateIntro() {
    if (!state.intro || state.intro.done) return;
    const elapsed = (performance.now() - state.intro.start) / 1000;
    const afterBurst = elapsed - state.intro.burst;
    state.nodes.forEach(node => {
      const progress = clamp((afterBurst - node.delay) / state.intro.duration, 0, 1);
      const eased = progress ? easeOutBack(progress) : 0;
      node.x = node.tx * eased; node.y = node.ty * eased; node.opacity = clamp(progress * 2.4, 0, 1);
    });
    if (afterBurst > state.intro.duration + .85) {
      state.intro.done = true;
      state.nodes.forEach(node => { node.x = node.tx; node.y = node.ty; node.opacity = 1; });
      document.body.classList.remove("intro-active");
    }
  }

  function draw() {
    ctx.clearRect(0, 0, innerWidth, innerHeight);
    drawBackground();
    if (state.data) drawGraph();
    drawIntro();
  }

  function loop(now) {
    state.time = now; updateIntro(); updatePhysics(); draw(); requestAnimationFrame(loop);
  }

  function toast(message) {
    ui.toast.textContent = message; ui.toast.classList.add("show");
    clearTimeout(toast.timer); toast.timer = setTimeout(() => ui.toast.classList.remove("show"), 3200);
  }

  async function load() {
    try {
      const response = await fetch("/api/fluxo-neural/dados", { credentials: "same-origin", cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      state.data = await response.json();
      if (!state.data.success) throw new Error(state.data.message || "Resposta inválida");
      populateUi(); buildGraph();
    } catch (error) {
      document.body.classList.remove("intro-active");
      toast("Não foi possível carregar a topologia do Sentinel.");
      console.error(error);
    }
  }

  [ui.search, ui.regional, ui.type].forEach(control => control.addEventListener(control.tagName === "INPUT" ? "input" : "change", () => {
    applyFilters(); fitGraph();
  }));
  document.getElementById("closePanel").addEventListener("click", () => { ui.panel.classList.remove("open"); state.selected = null; });
  ui.detail.addEventListener("click", event => {
    const deviceButton = event.target.closest("[data-device-id]");
    if (deviceButton) { selectDevice(deviceButton.dataset.deviceId); return; }
    const regionalButton = event.target.closest("[data-regional-id]");
    if (regionalButton) selectRegional(regionalButton.dataset.regionalId);
  });
  document.getElementById("tableButton").addEventListener("click", () => ui.table.classList.toggle("open"));
  document.getElementById("closeTable").addEventListener("click", () => ui.table.classList.remove("open"));
  ui.exportPdf.addEventListener("click", exportPdf);
  ui.exportXlsx.addEventListener("click", exportXlsx);
  document.getElementById("reorganizeButton").addEventListener("click", reorganize);
  document.getElementById("zoomIn").addEventListener("click", () => state.camera.scale = Math.min(2.5, state.camera.scale * 1.18));
  document.getElementById("zoomOut").addEventListener("click", () => state.camera.scale = Math.max(.08, state.camera.scale / 1.18));
  document.getElementById("fitButton").addEventListener("click", fitGraph);
  ui.connectionRank.addEventListener("click", event => {
    const row = event.target.closest("[data-id]"); if (!row) return;
    ui.regional.value = row.dataset.id; applyFilters(); fitGraph(); selectRegional(row.dataset.id);
  });
  ui.categoryRank.addEventListener("click", event => {
    const row = event.target.closest("[data-type]"); if (!row) return;
    ui.type.value = ui.type.value === row.dataset.type ? "" : row.dataset.type; applyFilters(); fitGraph();
  });
  ui.tableBody.addEventListener("click", event => {
    const deviceButton = event.target.closest("[data-device-id]");
    if (deviceButton) {
      ui.table.classList.remove("open");
      selectDevice(deviceButton.dataset.deviceId);
      return;
    }
    const row = event.target.closest("[data-table-regional]");
    if (!row) return;
    const id = row.dataset.tableRegional;
    if (state.tableExpanded.has(id)) state.tableExpanded.delete(id);
    else state.tableExpanded.add(id);
    renderTable();
  });

  canvas.addEventListener("pointerdown", event => {
    if (state.intro && !state.intro.done) {
      const elapsed = (performance.now() - state.intro.start) / 1000;
      if (elapsed < 3.6) state.intro.start = performance.now() - 3.6 * 1000;
      return;
    }
    const node = nodeAt(event.clientX, event.clientY);
    state.pointer = { x: event.clientX, y: event.clientY, cameraX: state.camera.x, cameraY: state.camera.y };
    state.dragNode = node; state.dragging = true; canvas.classList.add("dragging"); canvas.setPointerCapture(event.pointerId);
  });
  canvas.addEventListener("pointermove", event => {
    if (state.intro && !state.intro.done) return;
    if (!state.dragging || !state.pointer) {
      const node = nodeAt(event.clientX, event.clientY);
      if (node !== state.hover) { state.hover = node; canvas.classList.toggle("pointer", Boolean(node)); }
      return;
    }
    if (state.dragNode) {
      const point = worldPoint(event.clientX, event.clientY);
      const dx = point.x - state.dragNode.x, dy = point.y - state.dragNode.y;
      state.dragNode.x = point.x; state.dragNode.y = point.y;
      if (state.dragNode.kind === "regional" && !state.dragNode.isHub) {
        state.dragNode.tx += dx; state.dragNode.ty += dy;
      } else if (state.dragNode.kind !== "regional") {
        state.dragNode.offsetX += dx; state.dragNode.offsetY += dy;
      }
    } else {
      state.camera.x = state.pointer.cameraX + event.clientX - state.pointer.x;
      state.camera.y = state.pointer.cameraY + event.clientY - state.pointer.y;
    }
  });
  canvas.addEventListener("pointerup", event => {
    if (!state.pointer) return;
    const moved = Math.hypot(event.clientX - state.pointer.x, event.clientY - state.pointer.y) > 5;
    const node = nodeAt(event.clientX, event.clientY);
    if (!moved && node) {
      if (node.kind === "regional") selectRegional(node.id);
      else selectDevice(node.id);
    }
    state.dragging = false; state.dragNode = null; state.pointer = null; canvas.classList.remove("dragging");
  });
  canvas.addEventListener("pointerleave", () => { if (!state.dragging) { state.hover = null; canvas.classList.remove("pointer"); } });
  canvas.addEventListener("wheel", event => {
    event.preventDefault(); state.camera.scale = clamp(state.camera.scale * (event.deltaY > 0 ? .9 : 1.1), .08, 2.5);
  }, { passive: false });
  window.addEventListener("resize", () => { resize(); fitGraph(); });

  resize(); requestAnimationFrame(loop); load();
})();
