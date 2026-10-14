(() => {
  "use strict";

  const canvas = document.getElementById("network");
  const ctx = canvas.getContext("2d");
  const ui = {
    loading: document.getElementById("loading"),
    toast: document.getElementById("toast"),
    metrics: document.getElementById("metrics"),
    sync: document.getElementById("syncLabel"),
    search: document.getElementById("searchInput"),
    uf: document.getElementById("ufFilter"),
    status: document.getElementById("statusFilter"),
    connectionRank: document.getElementById("connectionRank"),
    alertRank: document.getElementById("alertRank"),
    panel: document.getElementById("detailPanel"),
    detail: document.getElementById("detailContent"),
    table: document.getElementById("tableView"),
    tableBody: document.getElementById("tableBody"),
    failureButton: document.getElementById("failureButton"),
    failureBanner: document.getElementById("failureBanner"),
  };
  const palette = {
    online: "#35d09f", warning: "#f4b942", offline: "#ee5261",
    alert: "#ee5261", unknown: "#7892a4", cyan: "#20bdf2", blue: "#1479d2",
  };
  const groupLabels = {
    servidores: "Servidores", switches: "Switches", links: "Links",
    aps: "Access points", vpns: "VPNs", firewalls: "Firewalls",
  };
  const state = {
    data: null, nodes: [], edges: [], visibleNodes: [], visibleEdges: [],
    view: "regionals", selected: null, simulated: new Set(), failureMode: false,
    camera: { x: 0, y: 0, scale: 1 }, pointer: null, dragNode: null,
    dragging: false, last: performance.now(), time: 0,
  };

  const escapeHtml = value => String(value ?? "").replace(/[&<>'"]/g, char => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  }[char]));
  const totalOf = (regional, group) => regional.totais[group]?.total || 0;
  const problemsOf = (regional, group) => {
    const values = regional.totais[group] || {};
    return values.alerta || (values.offline || 0) + (values.warning || 0);
  };

  function resize() {
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(innerWidth * ratio);
    canvas.height = Math.round(innerHeight * ratio);
    canvas.style.width = `${innerWidth}px`;
    canvas.style.height = `${innerHeight}px`;
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  }

  function buildGraph() {
    const regionals = state.data.regionais;
    const radius = Math.max(330, regionals.length * 13);
    const core = { ...state.data.hub, kind: "core", x: 0, y: 0, vx: 0, vy: 0, radius: 48 };
    const nodes = [core];
    regionals.forEach((regional, index) => {
      const angle = (index / Math.max(regionals.length, 1)) * Math.PI * 2 - Math.PI / 2;
      const ring = index % 2 ? radius : radius * .68;
      nodes.push({
        ...regional, kind: "regional", radius: 24,
        x: Math.cos(angle) * ring + (Math.random() - .5) * 35,
        y: Math.sin(angle) * ring + (Math.random() - .5) * 35,
        vx: 0, vy: 0,
      });
      nodes[nodes.length - 1].homeX = nodes[nodes.length - 1].x;
      nodes[nodes.length - 1].homeY = nodes[nodes.length - 1].y;
      Object.entries(regional.totais).forEach(([group, totals], groupIndex) => {
        if (!totals.total) return;
        const theta = angle + (groupIndex - 2.5) * .15;
        nodes.push({
          id: `${regional.id}:${group}`, parentId: regional.id, kind: "infra", group,
          nome: groupLabels[group], quantidade: totals.total,
          status: problemsOf(regional, group) ? "alert" : "online",
          x: Math.cos(theta) * (ring + 105), y: Math.sin(theta) * (ring + 105),
          vx: 0, vy: 0, radius: 10,
        });
      });
    });
    const nodeMap = new Map(nodes.map(node => [node.id, node]));
    const edges = state.data.conexoes.map(edge => ({
      ...edge, source: nodeMap.get(edge.origem), target: nodeMap.get(edge.destino), kind: "connection",
    })).filter(edge => edge.source && edge.target);
    nodes.filter(node => node.kind === "infra").forEach(node => edges.push({
      id: `infra:${node.id}`, source: nodeMap.get(node.parentId), target: node,
      kind: "infra", tipo: node.group, status: node.status, quantidade: node.quantidade,
    }));
    state.nodes = nodes;
    state.edges = edges;
    applyFilters();
    fitGraph();
  }

  function applyFilters() {
    const query = ui.search.value.trim().toLocaleLowerCase("pt-BR");
    const uf = ui.uf.value;
    const status = ui.status.value;
    const allowed = new Set(["sentinel-core"]);
    state.nodes.forEach(node => {
      if (node.kind !== "regional") return;
      const matches = (!query || `${node.nome} ${node.codigo}`.toLocaleLowerCase("pt-BR").includes(query))
        && (!uf || node.uf === uf) && (!status || node.status === status);
      if (matches) allowed.add(node.id);
    });
    if (state.view === "infra") {
      state.nodes.filter(node => node.kind === "infra" && allowed.has(node.parentId)).forEach(node => allowed.add(node.id));
    }
    state.visibleNodes = state.nodes.filter(node => allowed.has(node.id));
    state.visibleEdges = state.edges.filter(edge => allowed.has(edge.source.id) && allowed.has(edge.target.id));
    renderTable();
  }

  function populateUi() {
    const summary = state.data.resumo;
    ui.metrics.innerHTML = [
      [summary.regionais, "Regionais", ""], [summary.conexoes, "Conexões", ""],
      [summary.ativos, "Ativos", ""], [summary.com_alerta, "Em atenção", "alert"],
    ].map(([value, label, css]) => `<div class="metric ${css}"><strong>${value}</strong><small>${label}</small></div>`).join("");

    [...new Set(state.data.regionais.map(item => item.uf).filter(Boolean))].sort().forEach(uf => {
      ui.uf.insertAdjacentHTML("beforeend", `<option value="${escapeHtml(uf)}">${escapeHtml(uf)}</option>`);
    });
    renderRanking(ui.connectionRank, [...state.data.regionais]
      .sort((a, b) => (totalOf(b, "vpns") + totalOf(b, "links")) - (totalOf(a, "vpns") + totalOf(a, "links")))
      .slice(0, 6), item => totalOf(item, "vpns") + totalOf(item, "links"));
    ui.alertRank.classList.add("alerts");
    renderRanking(ui.alertRank, [...state.data.regionais].filter(item => item.alertas)
      .sort((a, b) => b.alertas - a.alertas).slice(0, 6), item => item.alertas);
    const stamp = state.data.source_updated_at ? new Date(state.data.source_updated_at) : new Date(state.data.generated_at);
    ui.sync.textContent = `TOPOLOGIA ATUALIZADA ${stamp.toLocaleString("pt-BR")}`;
  }

  function renderRanking(container, rows, valueFn) {
    if (!rows.length) { container.innerHTML = '<div class="empty">Nenhuma ocorrência</div>'; return; }
    const max = Math.max(...rows.map(valueFn), 1);
    container.innerHTML = rows.map(item => {
      const value = valueFn(item);
      return `<div class="rank-row" data-id="${escapeHtml(item.id)}"><span class="rank-name">${escapeHtml(item.nome)}</span><span class="rank-bar"><i style="width:${value / max * 100}%"></i></span><span class="rank-value">${value}</span></div>`;
    }).join("");
  }

  function renderTable() {
    if (!state.data) return;
    const visible = new Set(state.visibleNodes.filter(node => node.kind === "regional").map(node => node.id));
    ui.tableBody.innerHTML = state.data.regionais.filter(item => visible.has(item.id)).map(item => `
      <tr data-id="${escapeHtml(item.id)}">
        <td><strong>${escapeHtml(item.nome)}</strong><br><small>${escapeHtml(item.codigo)}</small></td>
        <td>${escapeHtml(item.uf || "-")}</td>
        <td><span class="table-status ${item.status}">${item.status === "alert" ? `${item.alertas} alerta(s)` : "Normal"}</span></td>
        ${["vpns", "links", "servidores", "switches", "aps", "firewalls"].map(group => `<td>${totalOf(item, group)}</td>`).join("")}
      </tr>`).join("");
  }

  function showDetails(id) {
    const regional = state.data.regionais.find(item => item.id === id);
    if (!regional) return;
    state.selected = regional.id;
    ui.detail.innerHTML = `
      <div class="detail-kicker">${escapeHtml(regional.uf || "Regional Sentinel")}</div>
      <h2>${escapeHtml(regional.nome)}</h2>
      <div class="detail-code">${escapeHtml(regional.codigo)}</div>
      <div class="status-pill ${regional.status}">${regional.status === "alert" ? `${regional.alertas} alerta(s) operacional(is)` : "Operação normal"}</div>
      <div class="detail-grid">
        ${Object.keys(groupLabels).map(group => `<div class="detail-item"><strong>${totalOf(regional, group)}</strong><small>${groupLabels[group]}</small>${problemsOf(regional, group) ? `<span>${problemsOf(regional, group)} em atenção</span>` : ""}</div>`).join("")}
      </div>`;
    ui.panel.classList.add("open");
  }

  function fitGraph() {
    const nodes = state.visibleNodes.filter(node => node.kind !== "infra" || state.view === "infra");
    if (!nodes.length) return;
    const xs = nodes.map(node => node.x), ys = nodes.map(node => node.y);
    const width = Math.max(...xs) - Math.min(...xs) + 220;
    const height = Math.max(...ys) - Math.min(...ys) + 220;
    const availableWidth = innerWidth - (innerWidth > 760 ? 330 : 30);
    const availableHeight = innerHeight - 120;
    state.camera.scale = Math.max(.28, Math.min(1, availableWidth / width, availableHeight / height));
    state.camera.x = (innerWidth > 760 ? 150 : 0);
    state.camera.y = 35;
  }

  function worldPoint(clientX, clientY) {
    return {
      x: (clientX - innerWidth / 2 - state.camera.x) / state.camera.scale,
      y: (clientY - innerHeight / 2 - state.camera.y) / state.camera.scale,
    };
  }

  function nodeAt(x, y) {
    const point = worldPoint(x, y);
    return [...state.visibleNodes].reverse().find(node => Math.hypot(node.x - point.x, node.y - point.y) <= node.radius + 8);
  }

  function simulate() {
    if (!state.data) return;
    const active = state.visibleNodes;
    for (let i = 0; i < active.length; i += 1) {
      const a = active[i];
      if (a.kind === "core") continue;
      const parent = a.kind === "infra" ? state.nodes.find(node => node.id === a.parentId) : null;
      if (parent) {
        const dx = parent.x - a.x, dy = parent.y - a.y;
        const distance = Math.max(Math.hypot(dx, dy), 1);
        const force = (distance - 82) * .00045;
        a.vx += dx / distance * force; a.vy += dy / distance * force;
      } else {
        a.vx += (a.homeX - a.x) * .0015;
        a.vy += (a.homeY - a.y) * .0015;
      }
      for (let j = i + 1; j < active.length; j += 1) {
        const b = active[j];
        const dx = a.x - b.x, dy = a.y - b.y;
        const distance2 = Math.max(dx * dx + dy * dy, 120);
        const force = (a.kind === "infra" || b.kind === "infra" ? 2 : 7) / distance2;
        a.vx += dx * force; a.vy += dy * force;
        b.vx -= dx * force; b.vy -= dy * force;
      }
      if (a !== state.dragNode) {
        a.vx *= .93; a.vy *= .93; a.x += a.vx; a.y += a.vy;
      }
    }
  }

  function roundedRect(x, y, width, height, radius) {
    ctx.beginPath(); ctx.roundRect(x, y, width, height, radius);
  }

  function draw() {
    ctx.clearRect(0, 0, innerWidth, innerHeight);
    if (!state.data) return;
    ctx.save();
    ctx.translate(innerWidth / 2 + state.camera.x, innerHeight / 2 + state.camera.y);
    ctx.scale(state.camera.scale, state.camera.scale);

    state.visibleEdges.forEach((edge, index) => {
      const isFailed = state.simulated.has(edge.target.id);
      const color = isFailed ? palette.offline : palette[edge.status] || palette.blue;
      ctx.beginPath(); ctx.moveTo(edge.source.x, edge.source.y); ctx.lineTo(edge.target.x, edge.target.y);
      ctx.strokeStyle = color; ctx.globalAlpha = edge.kind === "infra" ? .24 : .52;
      ctx.lineWidth = edge.kind === "infra" ? 1 : Math.min(3, 1 + edge.quantidade * .12); ctx.stroke();
      if (edge.kind === "connection") {
        const phase = (state.time * .00012 * (edge.tipo === "vpns" ? 1.15 : .8) + index * .17) % 1;
        const x = edge.source.x + (edge.target.x - edge.source.x) * phase;
        const y = edge.source.y + (edge.target.y - edge.source.y) * phase;
        ctx.beginPath(); ctx.arc(x, y, 2.8 / state.camera.scale, 0, Math.PI * 2);
        ctx.globalAlpha = .95; ctx.fillStyle = color; ctx.shadowColor = color; ctx.shadowBlur = 12; ctx.fill(); ctx.shadowBlur = 0;
      }
    });
    ctx.globalAlpha = 1;

    state.visibleNodes.forEach(node => {
      const failed = state.simulated.has(node.id);
      const color = failed ? palette.offline : (node.kind === "core" ? palette.cyan : palette[node.status] || palette.cyan);
      if (node.kind === "core") {
        const pulse = 5 + Math.sin(state.time * .003) * 3;
        ctx.beginPath(); ctx.arc(node.x, node.y, node.radius + pulse, 0, Math.PI * 2);
        ctx.strokeStyle = "rgba(32,189,242,.22)"; ctx.lineWidth = 2; ctx.stroke();
      }
      ctx.beginPath(); ctx.arc(node.x, node.y, node.radius, 0, Math.PI * 2);
      ctx.fillStyle = node.kind === "core" ? "#d9f5ff" : "#0b2030";
      ctx.strokeStyle = color; ctx.lineWidth = node.id === state.selected ? 4 : 2;
      ctx.shadowColor = color; ctx.shadowBlur = node.kind === "infra" ? 8 : 18; ctx.fill(); ctx.stroke(); ctx.shadowBlur = 0;
      ctx.fillStyle = node.kind === "core" ? "#083354" : color;
      ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.font = node.kind === "core" ? "800 15px Segoe UI" : node.kind === "infra" ? "700 8px Consolas" : "700 10px Consolas";
      ctx.fillText(node.kind === "core" ? "S" : node.kind === "infra" ? String(node.quantidade) : (node.uf || node.codigo.replace("REG_", "").slice(0, 3)), node.x, node.y);
      if (node.kind !== "infra") {
        const label = node.kind === "core" ? "SENTINEL" : node.nome;
        ctx.font = "650 11px Segoe UI"; const width = Math.min(170, ctx.measureText(label).width + 14);
        roundedRect(node.x - width / 2, node.y + node.radius + 7, width, 22, 5);
        ctx.fillStyle = "rgba(4,14,24,.88)"; ctx.fill();
        ctx.fillStyle = "#dcecf5"; ctx.fillText(label.length > 23 ? `${label.slice(0, 22)}…` : label, node.x, node.y + node.radius + 18);
      }
    });
    ctx.restore();
  }

  function loop(now) {
    state.time = now; simulate(); draw(); state.last = now; requestAnimationFrame(loop);
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
      setTimeout(() => ui.loading.classList.add("hidden"), 350);
    } catch (error) {
      ui.loading.classList.add("hidden");
      toast("Não foi possível carregar a topologia do Sentinel.");
      console.error(error);
    }
  }

  document.querySelectorAll("[data-view]").forEach(button => button.addEventListener("click", () => {
    document.querySelectorAll("[data-view]").forEach(item => item.classList.toggle("active", item === button));
    state.view = button.dataset.view; applyFilters(); fitGraph();
  }));
  [ui.search, ui.uf, ui.status].forEach(control => control.addEventListener(control.tagName === "INPUT" ? "input" : "change", applyFilters));
  document.getElementById("closePanel").addEventListener("click", () => ui.panel.classList.remove("open"));
  document.getElementById("tableButton").addEventListener("click", () => ui.table.classList.toggle("open"));
  document.getElementById("closeTable").addEventListener("click", () => ui.table.classList.remove("open"));
  document.getElementById("zoomIn").addEventListener("click", () => state.camera.scale = Math.min(2.5, state.camera.scale * 1.18));
  document.getElementById("zoomOut").addEventListener("click", () => state.camera.scale = Math.max(.2, state.camera.scale / 1.18));
  document.getElementById("fitButton").addEventListener("click", fitGraph);
  ui.failureButton.addEventListener("click", () => {
    state.failureMode = !state.failureMode; ui.failureButton.classList.toggle("active", state.failureMode);
    ui.failureBanner.classList.toggle("open", state.failureMode);
  });
  document.getElementById("cancelFailure").addEventListener("click", () => {
    state.failureMode = false; state.simulated.clear(); ui.failureButton.classList.remove("active"); ui.failureBanner.classList.remove("open");
  });
  document.querySelectorAll(".ranking").forEach(list => list.addEventListener("click", event => {
    const row = event.target.closest("[data-id]"); if (row) showDetails(row.dataset.id);
  }));
  ui.tableBody.addEventListener("click", event => {
    const row = event.target.closest("[data-id]"); if (row) { ui.table.classList.remove("open"); showDetails(row.dataset.id); }
  });

  canvas.addEventListener("pointerdown", event => {
    const node = nodeAt(event.clientX, event.clientY);
    state.pointer = { x: event.clientX, y: event.clientY, cameraX: state.camera.x, cameraY: state.camera.y };
    state.dragNode = node; state.dragging = true; canvas.classList.add("dragging"); canvas.setPointerCapture(event.pointerId);
  });
  canvas.addEventListener("pointermove", event => {
    if (!state.dragging || !state.pointer) return;
    if (state.dragNode && state.dragNode.kind !== "core") {
      const point = worldPoint(event.clientX, event.clientY); state.dragNode.x = point.x; state.dragNode.y = point.y; state.dragNode.vx = 0; state.dragNode.vy = 0;
    } else {
      state.camera.x = state.pointer.cameraX + event.clientX - state.pointer.x;
      state.camera.y = state.pointer.cameraY + event.clientY - state.pointer.y;
    }
  });
  canvas.addEventListener("pointerup", event => {
    const moved = state.pointer && Math.hypot(event.clientX - state.pointer.x, event.clientY - state.pointer.y) > 5;
    const node = nodeAt(event.clientX, event.clientY);
    if (!moved && node?.kind === "regional") {
      if (state.failureMode) { state.simulated.has(node.id) ? state.simulated.delete(node.id) : state.simulated.add(node.id); }
      else showDetails(node.id);
    }
    state.dragging = false; state.dragNode = null; state.pointer = null; canvas.classList.remove("dragging");
  });
  canvas.addEventListener("wheel", event => {
    event.preventDefault(); state.camera.scale = Math.max(.2, Math.min(2.5, state.camera.scale * (event.deltaY > 0 ? .9 : 1.1)));
  }, { passive: false });
  window.addEventListener("resize", () => { resize(); fitGraph(); });

  resize(); requestAnimationFrame(loop); load();
})();
