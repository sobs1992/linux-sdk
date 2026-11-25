// bare-web: the device's pages (/usr/sbin/bare-web's API): one page per
// part, picked by the address' #part; uploads by XHR (its progress), jobs
// followed by server-sent events.
"use strict";

const $ = (sel, el) => (el || document).querySelector(sel);
const $$ = (sel, el) => Array.from((el || document).querySelectorAll(sel));

function h(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (k === "class") e.className = v;
    else e.setAttribute(k, v === true ? "" : v);
  }
  for (const k of kids.flat()) {
    if (k === null || k === undefined || k === false) continue;
    e.append(k instanceof Node ? k : document.createTextNode(String(k)));
  }
  return e;
}

async function api(method, url, body) {
  const opt = { method, headers: {} };
  if (body !== undefined) {
    opt.headers["Content-Type"] = "application/json";
    opt.body = JSON.stringify(body);
  }
  let r;
  try {
    r = await fetch(url, opt);
  } catch (e) {
    throw new Error("Приставка не отвечает. Проверьте кабель USB.");
  }
  let j = null;
  try { j = await r.json(); } catch (e) { /* not JSON */ }
  if (!r.ok) throw new Error((j && j.error) || ("Ошибка " + r.status));
  return j;
}

function mb(bytes) {
  if (bytes === null || bytes === undefined) return "…";
  if (bytes >= 1 << 30) return (bytes / (1 << 30)).toFixed(1).replace(".", ",") + " ГБ";
  if (bytes >= 1 << 20) return Math.round(bytes / (1 << 20)) + " МБ";
  if (bytes >= 1 << 10) return Math.round(bytes / (1 << 10)) + " КБ";
  return bytes + " Б";
}

function mib(n) {
  return n >= 1024 ? (n / 1024).toFixed(1).replace(".", ",") + " ГБ" : n + " МБ";
}

function when(t) {
  if (!t) return "—";
  return new Date(t * 1000).toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" });
}

function banner(text, bad) {
  const b = $("#banner");
  b.hidden = !text;
  b.textContent = text || "";
  b.classList.toggle("bad", !!bad);
}

function say(err) {
  banner(err.message || String(err), true);
}

// ---- pages ------------------------------------------------------------------

const pages = {};
let timer = null;

function show() {
  const name = (location.hash || "#status").slice(1);
  const p = pages[name] ? name : "status";
  $$(".page").forEach(s => { s.hidden = s.id !== "page-" + p; });
  $$("nav a").forEach(a => a.classList.toggle("on", a.getAttribute("href") === "#" + p));
  banner("");
  clearInterval(timer);
  timer = null;
  pages[p]();
}

// ---- status -----------------------------------------------------------------

function card(k, v, meter) {
  return h("div", { class: "card" }, h("div", { class: "k" }, k), h("div", { class: "v" }, v),
    meter === undefined ? null : h("div", { class: "meter" }, h("i", { style: "width:" + meter + "%" })));
}

function room(r) {
  if (!r) return ["—", undefined];
  const used = r.total_mb ? Math.round((r.total_mb - r.free_mb) * 100 / r.total_mb) : 0;
  return ["свободно " + mib(r.free_mb) + " из " + mib(r.total_mb), used];
}

async function statusPage() {
  const tick = async () => {
    let s;
    try { s = await api("GET", "/api/status"); } catch (e) { return say(e); }
    banner("");
    $("#unit").textContent = s.unit || "";
    const rel = s.release || {};
    const c = s.card || {};
    const [cardText, cardUsed] = c.usb_disk ? ["отдана компьютеру как USB-диск", undefined] :
      c.mounted ? room(c.room) : ["не вставлена", undefined];
    const [dataText, dataUsed] = room(s.data);
    const b = s.battery || {};
    let bat = b.capacity !== undefined ? b.capacity + " %" : "—";
    if (b.status === "Charging") bat += ", заряжается";
    else if (b.status === "Full") bat += ", заряжена";
    else if (b.external) bat += ", питание по кабелю";
    const ab = s.ab || {};
    const body = $("#status-body");
    body.replaceChildren(
      card("Система", (rel.BUILT || "?") + " " + (rel.SDK || "")),
      card("Работает из части памяти", ab.running ? ab.running.toUpperCase() : "—"),
      card("Карта игр", cardText, cardUsed),
      card("Память приставки (/data)", dataText, dataUsed),
      card("Батарея", bat, b.capacity),
      card("Приставка", s.unit || "ogu"));
    if (s.job && !s.job.ended)
      body.append(card("Сейчас идёт", (s.job.kind === "update" ? "обновление " : "установка ") + s.job.title));
  };
  await tick();
  timer = setInterval(tick, 5000);
}
pages.status = statusPage;

// ---- uploads ----------------------------------------------------------------

const queue = [];
let uploading = false;

function setupDrops() {
  for (const d of $$(".drop")) {
    const place = d.dataset.place;
    const input = $("input[type=file]", d);
    input.addEventListener("change", () => { addFiles(place, input.files); input.value = ""; });
    d.addEventListener("dragover", e => { e.preventDefault(); d.classList.add("over"); });
    d.addEventListener("dragleave", () => d.classList.remove("over"));
    d.addEventListener("drop", e => {
      e.preventDefault();
      d.classList.remove("over");
      // a folder is not uploaded (the device takes files by their own name)
      const got = [];
      let folders = 0;
      for (const i of Array.from(e.dataTransfer.items || [])) {
        if (i.kind !== "file") continue;
        const en = i.webkitGetAsEntry ? i.webkitGetAsEntry() : null;
        if (en && en.isDirectory) { folders++; continue; }
        const f = i.getAsFile();
        if (f) got.push(f);
      }
      if (!e.dataTransfer.items) got.push(...Array.from(e.dataTransfer.files));
      if (folders)
        banner("Папки целиком отсюда не загружаются: перетащите файлы из папки или скопируйте " +
          "папку через «USB-диск» на приставке.", true);
      addFiles(place, got);
    });
  }
}

function addFiles(place, list) {
  const box = $(".uploads[data-place=" + place + "]");
  for (const f of list) {
    if (place === "updates" && !f.name.toLowerCase().endsWith(".upd")) {
      banner("Это не файл обновления (.upd): " + f.name, true);
      continue;
    }
    const bar = h("div", { class: "meter" }, h("i", { style: "width:0%" }));
    const state = h("span", { class: "state" }, "ждёт");
    const row = h("div", { class: "up" }, h("div", { class: "name" }, h("span", null, f.name + " (" + mb(f.size) + ")"), state), bar);
    box.append(row);
    queue.push({ place, file: f, row, bar, state });
  }
  pump();
}

// one file at a time: the card writes faster so
function pump() {
  if (uploading || !queue.length) return;
  uploading = true;
  const u = queue.shift();
  const x = new XMLHttpRequest();
  const t0 = Date.now();
  x.open("PUT", "/api/upload/" + u.place + "/" + encodeURIComponent(u.file.name));
  x.upload.onprogress = e => {
    if (!e.lengthComputable) return;
    const p = Math.floor(e.loaded * 100 / e.total);
    const s = (Date.now() - t0) / 1000;
    $("i", u.bar).style.width = p + "%";
    u.state.textContent = p + " %" + (s > 1 ? ", " + (e.loaded / s / 1e6).toFixed(1).replace(".", ",") + " МБ/с" : "");
  };
  const end = (ok, text) => {
    u.row.classList.add(ok ? "ok" : "bad");
    u.state.textContent = text;
    if (ok) $("i", u.bar).style.width = "100%";
    uploading = false;
    if (!queue.length) uploaded(u.place);
    pump();
  };
  x.onload = () => {
    let j = null;
    try { j = JSON.parse(x.responseText); } catch (e) { /* not JSON */ }
    if (x.status === 200) {
      const s = j && j.seconds ? j.seconds : (Date.now() - t0) / 1000;
      end(true, "записан, " + (u.file.size / Math.max(s, 0.001) / 1e6).toFixed(1).replace(".", ",") + " МБ/с");
    } else {
      end(false, (j && j.error) || ("ошибка " + x.status));
    }
  };
  x.onerror = () => end(false, "оборвалось: приставка не отвечает (кабель?)");
  x.send(u.file);
}

function uploaded(place) {
  if (place === "install" || place === "redist") scanInstall();
  if (place === "updates") updateFiles();
}

// ---- jobs -------------------------------------------------------------------

function follow(job, box, onEnd) {
  box.hidden = false;
  box.className = "job";
  const head = h("div", null, (job.kind === "update" ? "Обновление " : "Установка ") + job.title);
  const bar = h("div", { class: "meter" }, h("i", { style: "width:0%" }));
  const text = h("div", { class: "text" }, "начинаю…");
  const skips = h("div", { class: "skips" });
  box.replaceChildren(head, bar, text, skips);
  let step = { n: 0, m: 1, text: "" };
  const src = new EventSource("/api/job/" + job.id + "/events");
  const skipped = [];
  src.onmessage = m => {
    const e = JSON.parse(m.data);
    if (e.type === "step") {
      step = e;
      text.textContent = "Шаг " + e.n + " из " + e.m + ": " + e.text;
      $("i", bar).style.width = Math.round((e.n - 1) * 100 / e.m) + "%";
    } else if (e.type === "progress") {
      text.textContent = "Шаг " + step.n + " из " + step.m + ": " + step.text + ", " + e.percent + " %";
      $("i", bar).style.width = Math.round(((step.n - 1) + e.percent / 100) * 100 / step.m) + "%";
    } else if (e.type === "skip") {
      if (e.what === "file") skipped.push(e.arg);
      else if (e.what === "prepare") skips.textContent = "Подготовка игры для приставки прошла не до конца: " +
        "игра может работать не так, как задумано.";
      if (skipped.length) skips.textContent = "Не хватает файлов: " + skipped.join(", ") +
        ". Без них игра может не запуститься: положите их в папку redist (ниже) и установите игру снова.";
    } else if (e.type === "done" || e.type === "fail") {
      src.close();
      box.classList.add(e.type);
      text.textContent = e.text;
      if (e.type === "done") $("i", bar).style.width = "100%";
      if (onEnd) onEnd(e);
    }
  };
  src.onerror = () => {
    if (src.readyState === EventSource.CLOSED) text.textContent = "Связь с приставкой потеряна.";
  };
}

async function resume(kind, box, onEnd) {
  try {
    const j = (await api("GET", "/api/job")).job;
    if (j && j.kind === kind && (!j.ended || Date.now() / 1000 - j.started < 3600)) follow(j, box, onEnd);
  } catch (e) { /* shown elsewhere */ }
}

// ---- install ----------------------------------------------------------------

const STATE = { new: ["новая", "new"], installed: ["уже установлена", "installed"],
  unknown: ["приставка не знает эту игру", "unknown"],
  installer: ["этот установщик приставка не распаковывает", "installer"] };

function entryBox(e) {
  const [stateText, stateClass] = STATE[e.state] || [e.state, ""];
  const meta = [e.kind === "installer" ? "установщик" : "папка", e.name];
  if (e.size_mb) meta.push("нужно " + mib(e.size_mb) + " места");
  const box = h("div", { class: "entry" },
    h("div", { class: "title" }, e.title, " ", h("span", { class: "tag " + stateClass }, stateText)),
    h("div", { class: "meta" }, meta.join(" · ")));
  if (e.need.length)
    box.append(h("div", { class: "need" }, "Не хватает файлов: " + e.need.join(", ") +
      ". Без них игра может не запуститься. Положите их в папку redist (ниже на этой странице)."));
  let exe = null;
  let title = null;
  if (e.state === "unknown") {
    if (e.exe.length) {
      exe = h("select", null, e.exe.map(x => h("option", { value: x }, x)));
      title = h("input", { type: "text", value: e.title });
      box.append(h("div", { class: "pick" }, h("label", null, "Программа, которая запускает игру:"), exe,
        h("label", null, "Название на главном экране:"), title));
    } else {
      box.append(h("div", { class: "need" }, "В ней не найдено программ Windows (.exe)."));
    }
  }
  const go = h("button", { disabled: e.state === "installer" || (e.state === "unknown" && !exe) },
    e.state === "installed" ? "Установить заново" : "Установить");
  go.onclick = async () => {
    const body = { path: e.path, replace: e.state === "installed", title: e.title };
    if (e.state === "installed" && !confirm("«" + e.title + "» уже есть на карте. Заменить её этой " +
        "копией? Сохранения игры останутся.")) return;
    if (e.kind === "installer" && !confirm("Установить «" + e.title + "» из установщика? Приставка " +
        "распакует его на карту" + (e.size_mb ? " (нужно " + mib(e.size_mb) + " свободного места)" : "") +
        " и настроит игру. Потом файлы установщика удалятся с карты, на компьютере они останутся.")) return;
    if (exe) { body.exe = exe.value; body.title = title.value; }
    try {
      const r = await api("POST", "/api/install/run", body);
      follow({ id: r.job, kind: "install", title: e.title }, $("#install-job"), () => scanInstall());
      $$("#install-list button").forEach(b => { b.disabled = true; });
    } catch (err) { say(err); }
  };
  const del = h("button", { class: "danger" }, "Удалить");
  del.onclick = async () => {
    if (!confirm("Удалить «" + e.name + "» из папки install на карте игр? Установленные игры это не затронет.")) return;
    try {
      const r = await api("POST", "/api/install/remove", { path: e.path });
      banner(r.text);
      scanInstall();
    } catch (err) { say(err); }
  };
  box.append(h("div", { class: "actions" }, go, del));
  return box;
}

let scanning = null;

async function scanInstall() {
  if (scanning) return scanning;
  const list = $("#install-list");
  list.replaceChildren(h("p", { class: "small" }, "Смотрю, что лежит в папке install…"));
  scanning = (async () => {
    try {
      const r = await api("GET", "/api/install/scan");
      const running = (await api("GET", "/api/job")).job;
      list.replaceChildren();
      if (r.problem) { banner(r.problem, true); return; }
      if (!r.ok && r.error) banner(r.error, true);
      if (!r.entries.length) list.append(h("p", { class: "small" }, "Пусто. Перетащите установщик игры выше."));
      for (const e of r.entries) list.append(entryBox(e));
      if (running && !running.ended) $$("#install-list button").forEach(b => { b.disabled = true; });
      $("#redist-list").textContent = r.redist && r.redist.length ? "В папке redist: " + r.redist.join(", ") : "";
      const parts = (await api("GET", "/api/files/install")).files.filter(f => f.part);
      $("#install-parts").replaceChildren(...parts.map(f => {
        const b = h("button", { class: "danger" }, "Удалить");
        b.onclick = async () => {
          try { await api("DELETE", "/api/files/install/" + encodeURIComponent(f.name)); scanInstall(); } catch (err) { say(err); }
        };
        return h("div", { class: "entry" }, h("div", { class: "meta" }, "Недогруженный файл " + f.name +
          " (" + mb(f.size) + "): загрузка оборвалась. Загрузите файл снова или удалите его."), b);
      }));
    } catch (e) {
      list.replaceChildren();
      say(e);
    } finally {
      scanning = null;
    }
  })();
  return scanning;
}

pages.install = () => {
  scanInstall();
  resume("install", $("#install-job"), () => scanInstall());
};

// ---- games and logs ---------------------------------------------------------

async function openLog(g, n) {
  const v = $("#log-view");
  try {
    const r = await fetch("/api/logs/" + encodeURIComponent(g.id) + "/" + n);
    if (!r.ok) throw new Error("Журнала нет.");
    $("#log-text").textContent = await r.text();
  } catch (e) { return say(e); }
  $("#log-title").textContent = g.name + ": журнал " + n + (n === 1 ? " (последний запуск)" : "");
  $("#log-download").href = "/api/logs/" + encodeURIComponent(g.id) + "/" + n + "?download=1";
  v.hidden = false;
  v.scrollIntoView({ behavior: "smooth" });
}

async function makeReport(game, note) {
  note.textContent = "Собираю отчёт…";
  try {
    const r = await fetch("/api/report" + (game ? "?game=" + encodeURIComponent(game) : ""));
    if (!r.ok) {
      let j = null;
      try { j = await r.json(); } catch (e) { /* not JSON */ }
      throw new Error((j && j.error) || "Отчёт не получился.");
    }
    const blob = await r.blob();
    const cd = r.headers.get("Content-Disposition") || "";
    const m = /filename\*=UTF-8''([^;]+)/.exec(cd);
    const name = m ? decodeURIComponent(m[1]) : "report.txt";
    const a = h("a", { href: URL.createObjectURL(blob), download: name });
    document.body.append(a);
    a.click();
    a.remove();
    note.textContent = "Готово: " + name + " (он же лежит на карте игр в папке reports).";
  } catch (e) {
    note.textContent = "";
    say(e);
  }
}

async function gamesPage() {
  const list = $("#games-list");
  let tries = 0;
  const load = async () => {
    let r;
    try { r = await api("GET", "/api/games"); } catch (e) { return say(e); }
    if (r.problem) banner(r.problem, true);
    const rows = r.games.map(g => {
      const logs = g.logs.map(l => h("button", { class: "secondary", onclick: () => openLog(g, l.n) }, "журнал " + l.n));
      const note = h("div", { class: "small" });
      const rep = h("button", { class: "secondary", onclick: () => makeReport(g.id, note) }, "отчёт");
      return h("tr", null, h("td", null, g.name, h("div", { class: "small" }, g.folder ? "/games/" + g.folder : "")),
        h("td", null, g.folder ? mb(g.size) : "—"), h("td", null, when(g.last)),
        h("td", null, logs.length ? logs : h("span", { class: "small" }, "не запускалась"), rep, note));
    });
    list.replaceChildren(h("table", null, h("tr", null, h("th", null, "Игра"), h("th", null, "Размер"),
      h("th", null, "Последний запуск"), h("th", null, "Журналы")), rows));
    // the sizes are worked out on the device meanwhile
    if (r.games.some(g => g.folder && g.size === null) && ++tries < 30 && location.hash === "#games")
      setTimeout(load, 2000);
  };
  $("#log-view").hidden = true;
  list.replaceChildren(h("p", { class: "small" }, "Загружаю…"));
  load();
}
pages.games = gamesPage;

// ---- reports ----------------------------------------------------------------

async function reportsPage() {
  const list = $("#reports-list");
  let r;
  try { r = await api("GET", "/api/reports"); } catch (e) { return say(e); }
  if (!r.reports.length) {
    list.replaceChildren(h("p", { class: "small" }, "Отчётов пока нет."));
    return;
  }
  list.replaceChildren(h("table", null, h("tr", null, h("th", null, "Отчёт"), h("th", null, "Где"),
    h("th", null, "Размер"), h("th", null, "")),
  r.reports.map(x => {
    const url = "/api/reports/" + x.where + "/" + encodeURIComponent(x.name);
    const del = h("button", { class: "danger" }, "удалить");
    del.onclick = async () => {
      if (!confirm("Удалить отчёт " + x.name + "?")) return;
      try { await api("DELETE", url); reportsPage(); } catch (e) { say(e); }
    };
    return h("tr", null, h("td", null, x.name, h("div", { class: "small" }, when(x.time))),
      h("td", null, x.where === "card" ? "карта игр, reports" : "память приставки"),
      h("td", null, mb(x.size)),
      h("td", null, h("a", { class: "button secondary", href: url, target: "_blank" }, "открыть"),
        h("a", { class: "button secondary", href: url + "?download=1" }, "скачать"), del));
  })));
}
pages.reports = reportsPage;

// ---- update -----------------------------------------------------------------

async function updateState() {
  const box = $("#update-state");
  try {
    const s = await api("GET", "/api/update/state");
    const run = s.ab.running;
    const other = run === "a" ? "b" : "a";
    const v = s.versions || {};
    box.replaceChildren(card("Установлена (работает)", run ? (v[run] || "?") : "не из слота A/B"),
      card("Запасная", v[other] === null && s.busy ? "идёт обновление…" : (v[other] || "нет")));
    if (s.ab.ab_try && s.ab.ab_try !== "none" && s.ab.ab_try !== run)
      box.append(card("После перезагрузки", "запустится " + (v[s.ab.ab_try] || "запасная система")));
    $("#update-switch").disabled = !v[other];
  } catch (e) { say(e); }
}

async function updateFiles() {
  const list = $("#update-list");
  try {
    const r = await api("GET", "/api/update/files");
    if (r.problem) banner(r.problem, true);
    if (!r.files.length) {
      list.replaceChildren(h("p", { class: "small" }, "Нет. Перетащите файл обновления (.upd) выше."));
      return;
    }
    list.replaceChildren(...r.files.map(f => {
      const info = h("pre", { class: "small", hidden: true });
      const ib = h("button", { class: "secondary" }, "сведения");
      ib.onclick = async () => {
        try {
          const i = await api("GET", "/api/update/info?file=" + encodeURIComponent(f.path));
          info.textContent = i.text;
          info.hidden = false;
        } catch (e) { say(e); }
      };
      const go = h("button", { disabled: !f.fits }, "Установить");
      go.onclick = async () => {
        if (!confirm("Установить обновление " + f.version + "? Нынешняя система останется: если новая " +
            "не запустится, приставка вернётся к ней.")) return;
        try {
          const r2 = await api("POST", "/api/update/run", { file: f.path });
          $$("#update-list button").forEach(b => { b.disabled = true; });
          follow({ id: r2.job, kind: "update", title: f.version || f.name }, $("#update-job"), () => {
            updateState(); updateFiles();
          });
        } catch (e) { say(e); }
      };
      const del = h("button", { class: "danger", disabled: !f.removable }, "удалить файл");
      del.onclick = async () => {
        if (!confirm("Удалить файл " + f.name + " с приставки?")) return;
        try { await api("DELETE", "/api/files/updates/" + encodeURIComponent(f.name)); updateFiles(); } catch (e) { say(e); }
      };
      return h("div", { class: "entry" }, h("div", { class: "title" }, f.version || f.name),
        h("div", { class: "meta" }, f.path + " · " + mb(f.size) +
          (f.fits ? "" : " · не для этой приставки (" + (f.firmware || "?") + ")")),
        h("div", { class: "actions" }, go, ib, del), info);
    }));
  } catch (e) { say(e); }
}

function setupUpdate() {
  $("#update-reboot").onclick = async () => {
    if (!confirm("Перезагрузить приставку сейчас?")) return;
    try { banner((await api("POST", "/api/reboot")).text); } catch (e) { say(e); }
  };
  $("#update-switch").onclick = async () => {
    if (!confirm("Перезагрузить приставку с запасной системой? Нынешняя станет запасной.")) return;
    try { banner((await api("POST", "/api/update/switch")).text); } catch (e) { say(e); }
  };
}

pages.update = () => {
  updateState();
  updateFiles();
  resume("update", $("#update-job"), () => { updateState(); updateFiles(); });
};

// ---- start ------------------------------------------------------------------

$("#install-rescan").onclick = () => scanInstall();
$("#log-close").onclick = () => { $("#log-view").hidden = true; };
$("#report-make").onclick = () => makeReport("", $("#report-note")).then(reportsPage);
setupDrops();
setupUpdate();
window.addEventListener("hashchange", show);
window.addEventListener("beforeunload", e => {
  if (uploading) { e.preventDefault(); e.returnValue = ""; }
});
show();
