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

// every request that changes anything says it comes from this page (the
// server refuses such requests of other sites' forms and images)
const FROM_PAGE = { "X-Requested-With": "bare-web" };

async function api(method, url, body) {
  const opt = { method, headers: Object.assign({}, FROM_PAGE) };
  if (body !== undefined) {
    opt.headers["Content-Type"] = "application/json";
    opt.body = JSON.stringify(body);
  }
  let r;
  try {
    r = await fetch(url, opt);
  } catch (e) {
    throw new Error("Приставка не отвечает. Проверьте кабель USB или Wi-Fi.");
  }
  // over Wi-Fi: the session of the PIN is over (a new PIN, 24 h, a restart):
  // the page asks for it again
  if (r.status === 401) location.reload();
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
  // #part, or #game/FOLDER: a game's page
  const [name, ...rest] = (location.hash || "#status").slice(1).split("/");
  const p = pages[name] ? name : "status";
  $$(".page").forEach(s => { s.hidden = s.id !== "page-" + p; });
  $$("nav a").forEach(a => a.classList.toggle("on", a.getAttribute("href") === "#" + (p === "game" ? "workshop" : p)));
  banner("");
  clearInterval(timer);
  timer = null;
  stopCheck();
  pages[p](decodeURIComponent(rest.join("/")));
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
    if (place === "saves" && !/^saves-.+\.zip$/i.test(f.name)) {
      banner("Это не копия сохранений (saves-….zip): " + f.name, true);
      continue;
    }
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
  x.open("PUT", (u.place === "saves" ? "/api/saves/upload/" : "/api/upload/" + u.place + "/") +
    encodeURIComponent(u.file.name));
  x.setRequestHeader("X-Requested-With", FROM_PAGE["X-Requested-With"]);
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
  if (place === "saves") savesPage();
}

// ---- jobs -------------------------------------------------------------------

function follow(job, box, onEnd) {
  box.hidden = false;
  box.className = "job";
  const head = h("div", null, ({ update: "Обновление ", delete: "Удаление " }[job.kind] || "Установка ") + job.title);
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
  showHeal(g, n);
  v.hidden = false;
  v.scrollIntoView({ behavior: "smooth" });
}

// what the device can fix of a Windows game's last launch (stage 8): a library
// from the redist folder, a path of the game made writable; then a new launch
async function showHeal(g, n) {
  const box = $("#log-heal");
  box.hidden = true;
  box.replaceChildren();
  if (n !== 1 || g.kind !== "wine.ini" || !g.folder) return;
  let r;
  try { r = await api("GET", "/api/heal/" + encodeURIComponent(g.folder)); } catch (e) { return; }
  if (!r.suggestions.length) return;
  const note = h("div", { class: "small" });
  const run = h("button", { class: "secondary", hidden: true }, "Запустить игру ещё раз");
  run.onclick = async () => {
    try { await api("POST", "/api/game/" + encodeURIComponent(g.folder) + "/launch"); note.textContent = "Игра запускается на приставке."; }
    catch (e) { say(e); }
  };
  const buttons = r.suggestions.map(sg => {
    const b = h("button", null, "Исправить: " + sg.text);
    b.title = sg.line;
    b.onclick = async () => {
      b.disabled = true;
      note.textContent = "Исправляю…";
      try {
        const x = await api("POST", "/api/heal/" + encodeURIComponent(g.folder), { kind: sg.kind, arg: sg.arg });
        note.textContent = x.text;
        run.hidden = false;
      } catch (e) { note.textContent = ""; b.disabled = false; say(e); }
    };
    return b;
  });
  box.replaceChildren(h("p", null, "В журнале найдена ошибка, которую приставка может исправить сама:"),
    h("div", { class: "actions" }, ...buttons, run), note);
  box.hidden = false;
}

// a file of the device downloaded by the browser (the server says its name)
function download(url) {
  const a = h("a", { href: url + (url.includes("?") ? "&" : "?") + "download=1", download: "" });
  document.body.append(a);
  a.click();
  a.remove();
}

async function makeReport(game, note) {
  note.textContent = "Собираю отчёт…";
  try {
    const r = await api("POST", "/api/report", game ? { game } : {});
    download("/api/reports/" + r.where + "/" + encodeURIComponent(r.name));
    note.textContent = "Готово: " + r.name + " (он же лежит " +
      (r.where === "card" ? "на карте игр в папке reports" : "в памяти приставки, /data/reports") + ").";
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
      // a game of its own folder on the card (not a built-in one): deleted as on the device
      const del = g.folder && g.kind !== "built-in" ?
        h("button", { class: "danger", onclick: () => deleteGame(g, load) }, "удалить") : null;
      return h("tr", null, h("td", null, g.name, h("div", { class: "small" }, g.folder ? "/games/" + g.folder : "")),
        h("td", null, g.folder ? mb(g.size) : "—"), h("td", null, when(g.last)),
        h("td", null, logs.length ? logs : h("span", { class: "small" }, "не запускалась"), rep, del, note));
    });
    list.replaceChildren(h("table", null, h("tr", null, h("th", null, "Игра"), h("th", null, "Размер"),
      h("th", null, "Последний запуск"), h("th", null, "Журналы")), rows));
    // the sizes are worked out on the device meanwhile
    if (r.games.some(g => g.folder && g.size === null) && ++tries < 30 && location.hash === "#games")
      setTimeout(load, 2000);
  };
  $("#log-view").hidden = true;
  $("#games-job").hidden = true;
  list.replaceChildren(h("p", { class: "small" }, "Загружаю…"));
  load();
  resume("delete", $("#games-job"), () => load());
}
pages.games = gamesPage;

// a game deleted from the card: the device's words (i18n S_OPT_DEL_GAME_ASK_FMT),
// then a job of the device (big folders on exFAT take tens of seconds)
async function deleteGame(g, reload) {
  const size = g.size === null || g.size === undefined ? "размер ещё считается" : mb(g.size);
  if (!confirm("Удалить игру «" + g.name + "» с карты игр (/games/" + g.folder + ", " + size + ")? " +
    "Сохранения останутся в памяти приставки и вернутся, если поставить игру снова. " +
    "Правки Мастерской останутся в /games/recipes.")) return;
  try {
    const r = await api("POST", "/api/game/" + encodeURIComponent(g.folder) + "/delete");
    follow({ id: r.job, kind: "delete", title: g.name }, $("#games-job"), () => reload());
  } catch (e) { say(e); }
}

// ---- the workshop: the games' recipes (#workshop) ---------------------------

// 1 ключ, 2 ключа, 5 ключей
function keysWord(n) {
  const t = n % 10, hh = n % 100;
  return n + (t === 1 && hh !== 11 ? " ключ" : t >= 2 && t <= 4 && (hh < 12 || hh > 14) ? " ключа" : " ключей");
}

const RECIPE_KIND = { "wine.ini": "Windows", "game.ini": "своя программа", "built-in": "встроенная" };

async function workshopPage() {
  const list = $("#workshop-list"), search = $("#workshop-search");
  let games = [];
  const fill = () => {
    const q = search.value.trim().toLowerCase();
    const shown = games.filter(g => !q || g.name.toLowerCase().includes(q) || (g.folder || g.id).toLowerCase().includes(q));
    const rows = shown.map(g => {
      const go = () => { location.hash = "#game/" + encodeURIComponent(g.id); };
      const edits = g.kind === "built-in" ? "—" : g.layer_keys === null ? "не читаются" :
        g.layer_keys ? "есть, " + keysWord(g.layer_keys) : "нет";
      return h("tr", { class: "link", onclick: go },
        h("td", null, h("a", { href: "#game/" + encodeURIComponent(g.id) }, g.name),
          h("div", { class: "small" }, g.folder ? "/games/" + g.folder : "")),
        h("td", null, RECIPE_KIND[g.kind] || g.kind), h("td", null, edits), h("td", null, when(g.last)),
        h("td", null, g.running ? h("span", { class: "tag new" }, "идёт сейчас") : ""));
    });
    list.replaceChildren(shown.length ? h("table", null, h("tr", null, h("th", null, "Игра"), h("th", null, "Рецепт"),
      h("th", null, "Правки"), h("th", null, "Последний запуск"), h("th", null, "")), rows) :
      h("p", { class: "small" }, games.length ? "Ничего не нашлось." : "Игр нет."));
  };
  search.oninput = fill;
  list.replaceChildren(h("p", { class: "small" }, "Загружаю…"));
  try {
    const r = await api("GET", "/api/games");
    if (r.problem) banner(r.problem, true);
    games = r.games;
  } catch (e) { return say(e); }
  fill();
}
pages.workshop = workshopPage;

// ---- the workshop: a game's recipe and the check of it (#game/FOLDER) ----------

const W = { folder: null, r: null, schema: null, edits: {}, tab: "controls", hintTouched: false, stop: [] };
const LISTS = ["reg", "modes", "saves", "needs"];
const TABS = { controls: "Управление", screen: "Экран", fine: "Тонкое", check: "Проверка", export: "Экспорт" };
const GROUPS = { key: "клавиша", mouse: "мышь", pad: "геймпад", special: "особое" };

function isList(sec, key) { return sec === "" && LISTS.includes(key); }
function clone(o) { return JSON.parse(JSON.stringify(o || {})); }

// a value of the ini as it is in the game's recipe, in its layer (the edits), after both
function baseVal(sec, key) { const s = (W.r.base || {})[sec]; return s ? s[key] : undefined; }
function editVal(sec, key) { const s = W.edits[sec]; return s ? s[key] : undefined; }
function defVal(sec, key) { const s = (W.r.defaults || {})[sec]; return s ? s[key] : undefined; }
function curVal(sec, key) {
  const e = editVal(sec, key);
  if (e === undefined) return baseVal(sec, key);
  if (e === "" || (Array.isArray(e) && !e.length)) return undefined;
  return e;
}
function setEdit(sec, key, v) {
  if (v === undefined) {
    if (W.edits[sec]) { delete W.edits[sec][key]; if (!Object.keys(W.edits[sec]).length) delete W.edits[sec]; }
  } else (W.edits[sec] = W.edits[sec] || {})[key] = v;
  dirty(true);
  renderEdits();
}
function savedVal(sec, key) { const s = (W.r.layer || {})[sec]; return s ? s[key] : undefined; }
function sameVal(a, b) { return JSON.stringify(a) === JSON.stringify(b); }

// the tab a key is edited on (renderTab() of it)
function tabOf(sec, key) {
  if (W.r.kind !== "wine") return "fine";
  if (SCREEN_KEYS.some(([s, k]) => s === sec && k === key)) return "screen";
  const e = schemaOf(sec, key);
  if (e) return e.tab === "controls" ? "controls" : "fine";
  return "fine";
}

// its tab opened, its field focused (its block of "Тонкое" opened, the search there cleared)
function focusKey(sec, key) {
  W.tab = tabOf(sec, key);
  if (W.tab === "fine") { W.fineQuery = ""; W.fineOnly = false; (W.fineOpen = W.fineOpen || {})[blockOf(sec, key)] = true; }
  renderTab();
  const el = $$("#game-body .edit").find(x => x.dataset.key === sec + "/" + key);
  if (!el) {
    const e = schemaOf(sec, key);
    return banner("Поле " + (sec ? "[" + sec + "] " : "") + key + " сейчас не показывается" +
      (e && (e.tab === "controls" || W.r.kind === "native") ? " (оно зависит от других ключей, например крестовины или стика)." : "."));
  }
  const d = el.closest("details");
  if (d) d.open = true;
  el.scrollIntoView({ block: "center" });
  el.focus();
}

// "Мои правки": every key of the layer, the saved and the not saved ones
function renderEdits() {
  const box = $("#game-edits");
  if (!W.r || !W.r.editable) { box.hidden = true; return; }
  box.hidden = false;
  const items = [];
  const seen = new Set();
  for (const src of [W.edits, W.r.layer || {}])
    for (const [sec, keys] of Object.entries(src))
      for (const key of Object.keys(keys)) {
        if (seen.has(sec + "/" + key)) continue;
        seen.add(sec + "/" + key);
        items.push([sec, key]);
      }
  const line = ([sec, key]) => {
    const ev = editVal(sec, key), sv = savedVal(sec, key);
    const unsaved = !sameVal(ev, sv);
    const name = (sec ? "[" + sec + "] " : "") + key;
    const what = ev === undefined ? " — вернётся как в рецепте" :
      ev === "" || (Array.isArray(ev) && !ev.length) ? " — убран из рецепта" : " = " + shown(ev);
    // a field to go to: an edit, a key of the schema or of the recipe (a key known
    // to neither, taken away by its cross, has none until it is saved)
    const field = ev !== undefined || schemaOf(sec, key) || baseVal(sec, key) !== undefined;
    return h("li", { class: unsaved ? "unsaved" : null },
      field ? h("a", { href: "#", onclick: e => { e.preventDefault(); focusKey(sec, key); } }, h("code", null, name)) :
        h("code", null, name), what,
      unsaved ? h("span", { class: "small" }, " (не сохранено)") : null,
      ev === undefined ? null : h("button", { class: "x", title: "как в рецепте", "aria-label": "как в рецепте",
        onclick: () => { setEdit(sec, key, undefined); renderTab(); } }, "×"));
  };
  box.replaceChildren(h("div", { class: "row-head" }, h("h3", null, "Мои правки")),
    items.length ? h("ul", null, items.map(line)) : h("p", { class: "small" }, "правок нет"));
}
function shown(v) {
  if (v === undefined || v === null) return "—";
  return Array.isArray(v) ? (v.length ? v.join("; ") : "(пусто)") : (v === "" ? "(пусто)" : v);
}

function schemaOf(sec, key) {
  const list = W.r.kind === "native" ? W.schema.game : W.schema.wine;
  return list.find(e => e.section === sec && e.key === key);
}

// why a value would be refused (bare_web.py value_problem() says the same), "" if not
function problem(sec, key, v) {
  if (v === "") return "";
  if (/[\x00-\x1f]/.test(v)) return "управляющие символы";
  if (/^[;#]|\s[;#]/.test(v)) return "«;» или «#» после пробела — это комментарий";
  const e = schemaOf(sec, key);
  if (!e) return "";
  if (e.type === "enum" && !e.values.includes(v)) return "одно из: " + e.values.join(", ");
  if (e.type === "int" || e.type === "float") {
    if ((e.also || []).includes(v)) return "";
    const n = Number(v);
    if (v.trim() === "" || isNaN(n) || (e.type === "int" && !Number.isInteger(n))) return e.type === "int" ? "целое число" : "число";
    if ((e.min !== undefined && n < e.min) || (e.max !== undefined && n > e.max)) return "от " + e.min + " до " + e.max;
  }
  if (e.type === "bool" && !/^(yes|no|true|false|1|0)$/i.test(v)) return "yes или no";
  if (e.type === "text" && e.pattern && !new RegExp(e.pattern).test(v)) return "не в том виде (пример: " + (e.example || "") + ")";
  if (e.type === "list" && e.item_pattern && !new RegExp(e.item_pattern).test(v)) return "не в том виде";
  if (e.type === "list" && e.item === "reg" && !/^[^=]*[^\\=]\\[^\\=]+=/.test(v)) return "нужно KEY\\NAME=DATA";
  const acts = W.schema.actions || [];
  if (e.type === "stick" && acts.length) {
    const ok = acts.filter(a => a.group === "stick" && (a.takes || []).includes(key)).map(a => a.name);
    if (!ok.includes(v)) return "одно из: " + ok.join(", ");
  }
  if (e.type === "keys" && acts.length) {
    if (acts.some(a => a.name === v && a.group !== "key" && a.group !== "stick")) return "";
    const keys = new Set(acts.filter(a => a.group === "key").map(a => a.name));
    const parts = actionKeys(v);
    if (!parts || !parts.length || parts.length > 4 || !parts.every(p => keys.has(p.toLowerCase())))
      return "не клавиша и не действие";
  }
  return "";
}

// keys joined by "+" as bare_app_wine splits them (kp+ is a key)
function actionKeys(v) {
  const out = [];
  let i = 0;
  while (i < v.length) {
    let j = v.indexOf("+", i);
    if (j < 0) j = v.length;
    if (j - i === 2 && v.slice(i, j) === "kp" && j < v.length) j++;
    if (j < v.length && v[j] !== "+") return null;
    if (j > i) out.push(v.slice(i, j));
    i = j + 1;
  }
  return out;
}

// the edit of one value: an input (select, text, lines), the recipe's and the default value beside it
function editor(sec, key, opts) {
  opts = opts || {};
  const e = schemaOf(sec, key) || { type: "text", hint: "Ключа нет в схеме: записывается как текст." };
  const list = isList(sec, key);
  const ev = editVal(sec, key), bv = baseVal(sec, key);
  const note = h("div", { class: "err" });
  const check = v => {
    if (v === undefined) { note.textContent = ""; return true; }
    const bad =(Array.isArray(v) ? v : [v]).map(x => problem(sec, key, x)).find(x => x);
    note.textContent = bad || "";
    return !bad;
  };
  let input;
  const changed = v => { check(v); setEdit(sec, key, v); if (opts.onchange) opts.onchange(v); };
  if (list) {
    input = h("textarea", { rows: 2, placeholder: "как в рецепте" });
    input.value = Array.isArray(ev) ? ev.join("\n") : "";
    input.oninput = () => {
      const lines = input.value.split("\n").map(x => x.trim()).filter(x => x);
      changed(lines.length ? lines : (drop.checked ? [] : undefined));
    };
  } else if (e.type === "enum" || e.type === "stick" || e.type === "bool") {
    let vals = e.values || [];
    if (e.type === "stick") vals = (W.schema.actions || []).filter(a => a.group === "stick" && (a.takes || []).includes(key)).map(a => a.name);
    if (e.type === "bool") vals = ["yes", "no"];
    input = h("select", null, h("option", { value: "\u0001" }, "как в рецепте"),
      vals.map(v => h("option", { value: v }, v)));
    input.value = ev === undefined || ev === "" ? "\u0001" : ev;
    if (ev !== undefined && ev !== "" && !vals.includes(ev)) input.append(h("option", { value: ev }, ev));
    input.value = ev === undefined || ev === "" ? "\u0001" : ev;
    input.onchange = () => changed(input.value === "\u0001" ? (drop.checked ? "" : undefined) : input.value);
  } else {
    input = h("input", { type: "text", placeholder: "как в рецепте", list: e.type === "keys" ? "actions-list" : null });
    input.value = ev === undefined ? "" : ev;
    input.oninput = () => changed(input.value.trim() === "" ? (drop.checked ? "" : undefined) : input.value.trim());
  }
  // a key of the recipe taken away: "key =" in the layer
  const drop = h("input", { type: "checkbox" });
  drop.checked = ev === "" || (Array.isArray(ev) && !ev.length);
  drop.onchange = () => {
    if (drop.checked) { if (input.tagName === "SELECT") input.value = "\u0001"; else input.value = ""; changed(list ? [] : ""); }
    else changed(undefined);
  };
  const dropBox = bv !== undefined ? h("label", { class: "small drop-key" }, drop, " убрать из рецепта") : null;
  if (ev !== undefined && ev !== "") check(ev);
  const dv = defVal(sec, key);
  input.classList.add("edit");
  input.dataset.key = sec + "/" + key;
  return h("div", { class: "field" },
    h("div", { class: "vals small" }, "умолч.: ", h("b", null, shown(dv)), "  ·  рецепт: ", h("b", null, shown(bv))),
    input, dropBox, note);
}

function fieldRow(sec, key) {
  const e = schemaOf(sec, key);
  return h("tr", null, h("td", { class: "key" }, h("code", null, (sec ? "[" + sec + "] " : "") + key),
    e && e.hint ? h("div", { class: "small" }, e.hint) : null), h("td", null, editor(sec, key)));
}

// what the player changed on the device (controls.<key>): button A is B for the game
function playerOf(key) {
  const p = (W.r.player_controls || {}).pairs || [];
  const x = p.find(q => q.from === key);
  if (!x) return "";
  return x.to === "-" ? "ничего" : "как " + x.to.toUpperCase();
}

// the controls hint out of the labels: "L stick  cursor    A  click…", F5/F6 last
function buildHint(ru) {
  const sec = ru ? "labels.ru" : "labels";
  const first = [], second = [];
  for (const c of W.schema.controls) {
    if (c.nolabel || (c.device === "start_select" && !W.schema.start_select)) continue;
    const l = curVal(sec, c.key);
    if (!l) continue;
    (/^f\d$/.test(c.key) ? second : first).push((ru ? c.ru : c.en) + "  " + l);
  }
  second.push(ru ? "F5  свернуть    F6 (держать)  выход" : "F5  minimise    F6 (hold)  quit");
  return first.join("    ") + "\\n" + second.join("    ");
}

function hintBox() {
  const box = h("div");
  const fill = () => {
    box.replaceChildren(h("h3", null, "Подсказка при старте"),
      h("p", { class: "small" }, "Собирается из подписей сама, пока вы её не правили. «\\n» — новая строка."),
      h("table", null, ["hint.ru", "hint"].map(k => {
        const ed = editor("", k, { onchange: () => { W.hintTouched = true; } });
        return h("tr", null, h("td", { class: "key" }, h("code", null, k)), h("td", null, ed));
      })),
      h("div", { class: "actions" }, h("button", { class: "secondary", onclick: () => { regen(true); } },
        "Собрать из подписей")));
  };
  // force: both (the button); else the one of the labels' language changed
  const regen = (force, ru) => {
    if (W.hintTouched && !force) return;
    if (force || !ru) setEdit("", "hint", buildHint(false));
    if (force || ru) setEdit("", "hint.ru", buildHint(true));
    fill();
  };
  W.regenHint = regen;
  fill();
  return box;
}

function controlsTab() {
  const rows = W.schema.controls.filter(c => {
    if (c.device === "start_select" && !W.schema.start_select && baseVal("keys", c.key) === undefined) return false;
    for (const [k, v] of Object.entries(c.needs || {})) if ((curVal("keys", k) || defVal("keys", k)) !== v) return false;
    return true;
  }).map(c => {
    const label = sec => c.nolabel ? h("span", { class: "small" }, "—") :
      editor(sec, c.key, { onchange: () => W.regenHint && W.regenHint(false, sec === "labels.ru") });
    return h("tr", null,
      h("td", { class: "key" }, h("b", null, c.ru), c.note ? h("div", { class: "small" }, c.note) : null),
      h("td", null, editor("keys", c.key, { onchange: () => { if (c.kind === "stick") renderTab(); } })),
      h("td", null, label("labels.ru")), h("td", null, label("labels")),
      h("td", { class: "small" }, playerOf(c.key)));
  });
  const pc = W.r.player_controls || {};
  return [
    h("p", { class: "hint" }, "Действие: клавиша (esc, enter, ctrl+s — вместе через +), мышь (lbutton, rbutton, " +
      "wheelup…), кнопка геймпада (pad_a…), magnify (лупа) или none. Подписи показываются на экране «Управление» " +
      "приставки (X на плитке игры). Пустое поле — как в рецепте."),
    h("table", { class: "ctl" }, h("tr", null, h("th", null, "Кнопка"), h("th", null, "Действие"),
      h("th", null, "Подпись (рус.)"), h("th", null, "Подпись (англ.)"), h("th", null, "У игрока")), rows),
    pc.value ? h("p", { class: "small" }, "Своя перестановка кнопок игрока на приставке: ", h("code", null, pc.value),
      ". Её можно перенести в рецепт кнопкой внизу.") : null,
    hintBox()];
}

const SCREEN_KEYS = [["", "mode"], ["", "modes"], ["", "rows"], ["", "scale"], ["", "cursor"],
  ["keys", "cursor_speed"], ["", "fps_limit"], ["", "gamma"]];

function screenTab() {
  return [h("table", null, SCREEN_KEYS.map(([s, k]) => fieldRow(s, k)))];
}

function envPresets() {
  return h("div", { class: "presets" }, h("h3", null, "Заготовки env"),
    (W.schema.env_presets || []).map(p => h("div", { class: "preset" },
      h("button", { class: "secondary", onclick: () => {
        const cur = (editVal("", "env") !== undefined ? editVal("", "env") : baseVal("", "env") || "").split(/\s+/).filter(x => x);
        const names = p.value.split(/\s+/).map(t => t.split("=")[0]);
        const out = cur.filter(t => !names.includes(t.split("=")[0])).concat(p.value.split(/\s+/));
        setEdit("", "env", out.join(" "));
        renderTab();
      } }, "добавить"), " ", h("b", null, p.name), h("div", { class: "small" }, h("code", null, p.value), " — ", p.hint))));
}

const OTHER = "\u0001other";	// the block of the keys the schema does not know

// the block of "Тонкое" a key is in: its section, or OTHER
function blockOf(sec, key) { return schemaOf(sec, key) ? sec : OTHER; }

// the keys of "Тонкое" by block, in the schema's order, the unknown ones last
function fineKeys() {
  const list = W.r.kind === "native" ? W.schema.game : W.schema.wine;
  const shownKeys = new Set(W.r.kind === "native" ? [] : SCREEN_KEYS.map(x => x.join("/")));
  const blocks = new Map();
  const add = (b, sec, key, e) => { if (!blocks.has(b)) blocks.set(b, []); blocks.get(b).push({ sec, key, e }); };
  for (const e of list) {
    if (e.hidden || shownKeys.has(e.section + "/" + e.key)) continue;
    if (W.r.kind !== "native" && (e.tab === "controls")) continue;
    add(e.section, e.section, e.key, e);
  }
  // what the recipe or the layer has that the schema does not know
  const known = new Set(list.map(e => e.section + "/" + e.key));
  for (const src of [W.r.base || {}, W.edits])
    for (const [s, keys] of Object.entries(src))
      for (const k of Object.keys(keys))
        if (!known.has(s + "/" + k)) { known.add(s + "/" + k); add(OTHER, s, k, null); }
  if (blocks.has(OTHER)) { const o = blocks.get(OTHER); blocks.delete(OTHER); blocks.set(OTHER, o); }
  return blocks;
}

function fineTab() {
  W.fineOpen = W.fineOpen || {};
  const body = h("div");
  const search = h("input", { type: "search", class: "search", placeholder: "Поиск по ключу, разделу, подсказке",
    autocomplete: "off" });
  search.value = W.fineQuery || "";
  const only = h("input", { type: "checkbox" });
  only.checked = !!W.fineOnly;
  const presets = W.r.kind === "native" ? null : envPresets();
  const fill = () => {
    const q = (W.fineQuery || "").toLowerCase();
    const set = (sec, key) => baseVal(sec, key) !== undefined || editVal(sec, key) !== undefined;
    const out = [];
    for (const [b, keys] of fineKeys()) {
      const rows = keys.filter(({ sec, key, e }) => (!W.fineOnly || set(sec, key)) && (!q ||
        key.toLowerCase().includes(q) || sec.toLowerCase().includes(q) || ("[" + sec + "]").includes(q) ||
        (e && e.hint && e.hint.toLowerCase().includes(q))));
      if (!rows.length) continue;
      const title = b === OTHER ? "Прочее (ключей нет в схеме)" : b ? "[" + b + "]" : "Основные ключи (без раздела)";
      const d = h("details", null, h("summary", null, title, h("span", { class: "small" }, "  " + rows.length)),
        h("table", null, rows.map(({ sec, key }) => fieldRow(sec, key))));
      d.open = q ? true : W.fineOpen[b] !== undefined ? W.fineOpen[b] : keys.some(({ sec, key }) => set(sec, key));
      d.ontoggle = () => { if (!q) W.fineOpen[b] = d.open; };
      out.push(d);
    }
    body.replaceChildren(...(out.length ? out : [h("p", { class: "small" }, "Ничего не нашлось.")]));
    if (presets) presets.hidden = !!q;	// the env presets: not while searching
  };
  search.oninput = () => { W.fineQuery = search.value.trim(); fill(); };
  only.onchange = () => { W.fineOnly = only.checked; fill(); };
  fill();
  return [h("div", { class: "actions" }, search, h("label", { class: "small" }, only, " только заданные (в рецепте или правках)")),
    body, presets];
}

let checkTimer = null, checkStream = null;

function stopCheck() {
  clearTimeout(checkTimer);
  checkTimer = null;
  if (checkStream) { checkStream.close(); checkStream = null; }
  for (const f of W.stop.splice(0)) f();
}

function padButton(name, label) {
  let down = false;
  const send = d => {
    if (d === down) return;
    down = d;
    api("POST", "/api/pad", { button: name, down: d }).catch(say);
  };
  const b = h("button", { class: "pad secondary" }, label || name.toUpperCase());
  b.addEventListener("pointerdown", e => { e.preventDefault(); b.setPointerCapture(e.pointerId); send(true); });
  for (const ev of ["pointerup", "pointercancel", "lostpointercapture"]) b.addEventListener(ev, () => send(false));
  W.stop.push(() => send(false));
  return b;
}

function stickButton(stick, x, y, label) {
  let held = null;
  const push = () => api("POST", "/api/stick", { stick, x, y, ms: 300 }).catch(e => { say(e); release(); });
  const release = () => { clearInterval(held); held = null; };
  const b = h("button", { class: "pad secondary" }, label);
  b.addEventListener("pointerdown", e => {
    e.preventDefault(); b.setPointerCapture(e.pointerId);
    if (held) return;
    push(); held = setInterval(push, 300);
  });
  for (const ev of ["pointerup", "pointercancel", "lostpointercapture"]) b.addEventListener(ev, release);
  W.stop.push(release);
  return b;
}

// the picture of the check: the stream (mpegts.js, MSE) or a snapshot a second
const STREAM_OK = () => !!(window.mpegts && mpegts.isSupported());
const STREAM_NO_FRAME_MS = 8000;	// no picture in that time: back to snapshots
// why the stream has none of the game's sound (state.json stream.sound false):
// a game takes the sound's way when it starts (bare_app audio/route.h)
const SOUND_LATE = "Звука нет: игра запущена до включения потока. Перезапустите игру; чтобы звук был в потоке " +
  "сразу, включите на приставке настройку «Трансляция (RTSP)» (Настройки → Интернет).";
const SOUND_DIRECT = "Звука нет: игры Windows играют прямо в динамик приставки, мимо потока.";

function checkTab() {
  const img = h("img", { class: "shot", alt: "экран приставки" });
  const video = h("video", { class: "shot", muted: "", autoplay: "", playsinline: "" });
  video.muted = true;	// autoplay with sound is cut by browsers: sound by the button
  const shotNote = h("div", { class: "small" });
  const soundBtn = h("button", { class: "secondary", type: "button" }, "Включить звук");
  const soundNote = h("div", { class: "small bad", hidden: "" });
  const modeStream = h("input", { type: "radio", name: "check-mode", value: "stream" });
  const modeShot = h("input", { type: "radio", name: "check-mode", value: "shot" });
  const view = h("div", { class: "view" });
  const st = h("div", { class: "cards" });
  const logPre = h("pre", { class: "live" });
  const f = encodeURIComponent(W.folder);
  let player = null, mode = null, noFrame = null, ended = false, noAudio = false, soundWhy = null;
  // the button and the line under the picture as the stream's sound is
  const soundShow = () => {
    soundNote.hidden = !(mode === "stream" && soundWhy);
    soundNote.textContent = soundWhy || "";
    soundBtn.disabled = noAudio || !!soundWhy;
    soundBtn.title = soundWhy || "";
    if (noAudio) soundBtn.textContent = "Без звука";
    else soundBtn.textContent = video.muted ? "Включить звук" : "Выключить звук";
  };
  const lag = () => video.buffered.length ? video.buffered.end(video.buffered.length - 1) - video.currentTime : null;
  const streamStop = askOff => {
    clearTimeout(noFrame);
    noFrame = null;
    if (player) {
      try { player.pause(); player.unload(); player.detachMediaElement(); player.destroy(); } catch (e) { /* gone */ }
      player = null;
      if (askOff) api("POST", "/api/stream", { on: false }).catch(() => {});
    }
  };
  const showShots = why => {
    streamStop(true);
    mode = "shot";
    modeShot.checked = true;
    view.replaceChildren(img);
    soundBtn.hidden = true;
    soundShow();
    shotNote.textContent = why || "Снимок экрана обновляется раз в секунду, пока открыта эта вкладка.";
    if (why) shotNote.classList.add("bad"); else shotNote.classList.remove("bad");
  };
  const showStream = async () => {
    if (!STREAM_OK()) return showShots("Этот браузер не показывает поток (нет Media Source Extensions): снимки.");
    streamStop(false);
    mode = "stream";
    ended = false;
    modeStream.checked = true;
    shotNote.classList.remove("bad");
    shotNote.textContent = "Поток запускается…";
    view.replaceChildren(video);
    soundBtn.hidden = false;
    noAudio = false;
    soundShow();
    try { await api("POST", "/api/stream", { on: true }); }
    catch (e) { return showShots("Поток не запустился (" + e.message + "): снимки раз в секунду."); }
    if (mode !== "stream" || W.tab !== "check") return;
    player = mpegts.createPlayer({ type: "mpegts", isLive: true, url: "/api/stream.ts" }, {
      enableWorker: false, enableStashBuffer: false, lazyLoad: false, autoCleanupSourceBuffer: true,
      liveBufferLatencyChasing: true, liveBufferLatencyMaxLatency: 1.0, liveBufferLatencyMinRemain: 0.2,
      liveSync: true, liveSyncMaxLatency: 1.0, liveSyncTargetLatency: 0.4 });
    const p = player;
    p.on(mpegts.Events.ERROR, (type, detail, info) => {
      if (p !== player) return;
      showShots("Поток прервался (" + [type, detail, info && (info.msg || info.code)].filter(x => x).join(", ") +
        "): снимки раз в секунду. «Поток» — попробовать снова.");
    });
    p.on(mpegts.Events.LOADING_COMPLETE, () => {
      if (p !== player) return;
      ended = true;
      showShots("Поток закончился (приставка его остановила): снимки раз в секунду. «Поток» — снова.");
    });
    p.on(mpegts.Events.MEDIA_INFO, mi => {
      if (p !== player || !mi) return;
      if (mi.hasAudio === false) { noAudio = true; soundShow(); }
    });
    p.attachMediaElement(video);
    p.load();
    const played = video.play();
    if (played && played.catch) played.catch(() => {});
    noFrame = setTimeout(() => {
      if (p === player && !(video.readyState >= 2 && video.currentTime > 0))
        showShots("Поток не показал ни кадра за " + STREAM_NO_FRAME_MS / 1000 + " с: снимки раз в секунду.");
    }, STREAM_NO_FRAME_MS);
  };
  soundBtn.onclick = () => {
    video.muted = !video.muted;
    if (!video.muted) video.play().catch(() => {});
    soundShow();
  };
  modeStream.onchange = () => { if (modeStream.checked) { localStorage.setItem("checkMode", "stream"); showStream(); } };
  modeShot.onchange = () => { if (modeShot.checked) { localStorage.setItem("checkMode", "shot"); showShots(); } };
  W.stop.push(() => { mode = null; streamStop(true); });
  const loop = async () => {
    try {
      const s = await api("GET", "/api/state");
      const run = s.running, sm = s.stream || {};
      st.replaceChildren(
        card("Игра", run ? (run === W.folder ? "идёт" : "идёт другая: " + run) + (s.minimized ? " (свёрнута)" : "") : "не запущена"),
        card("Кадров в секунду", run && s.fps !== null ? String(s.fps).replace(".", ",") : "—"),
        card("CPU игры", run && s.cpu_pct !== null ? s.cpu_pct + " % одного ядра" : "—"),
        card("GPU", run && s.gpu_pct !== null ? s.gpu_pct + " %" + (s.gpu_mhz ? ", " + s.gpu_mhz + " МГц" : "") : "—"),
        card("Память игры", run && s.mem_mb !== null ? s.mem_mb + " МБ" : "—"),
        card("Поток", sm.running ? "зрителей " + sm.viewers + ", " + sm.kbps + " кбит/с" : "не идёт"));
      // a game runs, the stream too, and its sound is not in it (an older
      // bare_app says nothing of it: no line)
      soundWhy = run && sm.running && sm.sound === false ? (sm.sound_direct ? SOUND_DIRECT : SOUND_LATE) : null;
      soundShow();
    } catch (e) { /* the next second */ }
    if (mode === "stream" && player) {
      const l = lag();
      if (video.readyState >= 2 && video.currentTime > 0)
        shotNote.textContent = "Поток" + (l !== null ? ": в буфере " + l.toFixed(2).replace(".", ",") + " с" : "") +
          (video.muted ? ", звук выключен" : "") + ".";
    } else if (mode === "shot") {
      await new Promise(res => {
        const next = h("img");
        next.onload = () => {
          if (mode === "shot") { img.src = next.src; if (!shotNote.classList.contains("bad")) shotNote.textContent = "Снимок: " + new Date().toLocaleTimeString("ru-RU"); }
          res();
        };
        next.onerror = () => {
          if (mode === "shot" && !shotNote.classList.contains("bad")) shotNote.textContent = "Снимок не получился (bare_app не отвечает?).";
          res();
        };
        next.src = "/api/shot.png?w=480&t=" + Date.now();
      });
    }
    if (W.tab === "check" && location.hash.startsWith("#game/")) checkTimer = setTimeout(loop, 1000);
  };
  const act = what => async () => {
    try { const r = await api("POST", "/api/game/" + f + "/" + what); if (r.already) banner("Игра уже идёт."); }
    catch (e) { say(e); }
  };
  checkStream = new EventSource("/api/logs/" + f + "/live");
  checkStream.onmessage = m => {
    const e = JSON.parse(m.data);
    if (e.reset) logPre.textContent = "— новый запуск —\n";
    else logPre.textContent = (logPre.textContent + e.line + "\n").split("\n").slice(-500).join("\n");
    logPre.scrollTop = logPre.scrollHeight;
  };
  if (STREAM_OK() && localStorage.getItem("checkMode") !== "shot") showStream();
  else showShots(STREAM_OK() ? null : "Этот браузер не показывает поток: снимки раз в секунду.");
  if (!STREAM_OK()) modeStream.disabled = true;
  loop();
  const ss = W.schema.start_select;
  const dirs = (stick) => h("div", { class: "stick" }, h("div", { class: "small" }, stick === "stick" ? "Левый стик" : "Правый стик"),
    h("div", { class: "cross" }, h("span"), stickButton(stick, 0, -1, "▲"), h("span"),
      stickButton(stick, -1, 0, "◀"), h("span"), stickButton(stick, 1, 0, "▶"),
      h("span"), stickButton(stick, 0, 1, "▼"), h("span")));
  return [
    h("div", { class: "actions" },
      h("button", { onclick: act("launch") }, "Запустить"),
      h("button", { class: "secondary", onclick: act("quit") }, "Выйти из игры"),
      h("button", { class: "secondary", onclick: act("options") }, "Опции игры на приставке")),
    st,
    h("div", { class: "check" },
      h("div", null,
        h("div", { class: "actions mode" },
          h("label", null, modeStream, " Поток"), h("label", null, modeShot, " Снимок раз в секунду"), soundBtn),
        view, soundNote, shotNote),
      h("div", { class: "gamepad" },
        h("div", { class: "row" }, padButton("l2", "L2"), padButton("l1", "L1"), padButton("r1", "R1"), padButton("r2", "R2")),
        h("div", { class: "row" },
          h("div", { class: "cross" }, h("span"), padButton("up", "▲"), h("span"), padButton("left", "◀"), h("span"),
            padButton("right", "▶"), h("span"), padButton("down", "▼"), h("span")),
          h("div", { class: "cross" }, h("span"), padButton("x", "X"), h("span"), padButton("y", "Y"), h("span"),
            padButton("a", "A"), h("span"), padButton("b", "B"), h("span"))),
        h("div", { class: "row" }, ["f1", "f2", "f3", "f4", "f5", "f6"].map(n => padButton(n, n.toUpperCase())),
          ss ? padButton("select", "Select") : null, ss ? padButton("start", "Start") : null),
        h("div", { class: "row" }, dirs("stick"), dirs("rstick")),
        h("p", { class: "small" }, "Кнопка нажата, пока её держит мышь. F6 надо держать 2 с, чтобы выйти из игры; " +
          "стик держится в стороне, пока нажата стрелка."))),
    h("h3", null, "Журнал запуска (живьём)"), logPre];
}

// the recipe of the game as a zip for the SDK (scripts/recipe-import.py on the PC)
function exportTab() {
  const note = h("span", { class: "small" });
  const b = h("button", null, "Скачать рецепт (zip)");
  b.onclick = async () => {
    if (isDirty && !confirm("На странице есть несохранённые правки: в рецепт попадёт только сохранённое. Продолжить?")) return;
    b.disabled = true;
    note.textContent = "Собираю…";
    try {
      let r;
      try {
        r = await fetch("/api/recipe/" + encodeURIComponent(W.folder) + "/export",
          { method: "POST", headers: Object.assign({}, FROM_PAGE) });
      } catch (e) { throw new Error("Приставка не отвечает. Проверьте кабель USB."); }
      if (!r.ok) {
        let j = null;
        try { j = await r.json(); } catch (e) { /* not JSON */ }
        throw new Error((j && j.error) || ("Ошибка " + r.status));
      }
      const cd = r.headers.get("Content-Disposition") || "";
      const m = cd.match(/filename\*=UTF-8''([^;]+)/);
      const name = m ? decodeURIComponent(m[1]) : "recipe-" + W.folder + ".zip";
      const url = URL.createObjectURL(await r.blob());
      const a = h("a", { href: url, download: name });
      document.body.append(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 10000);
      note.textContent = "Скачан " + name + ".";
    } catch (e) { note.textContent = ""; say(e); }
    b.disabled = false;
  };
  return [
    h("p", null, "Рецепт игры для репозитория SDK: действующий " + (W.r.ini || "ini") +
      " (рецепт с сохранёнными правками), обложка, заготовка README.md, секция для games.manifest, " +
      "файлы с компьютера, которые рецепт берёт (needs.txt), и журнал последнего запуска."),
    h("p", { class: "small" }, "На компьютере: python3 scripts/recipe-import.py ФАЙЛ.zip в каталоге SDK — разложит " +
      "файлы в games/" + W.folder + "/ и допишет секцию в games/games.manifest; source и README заполняются руками."),
    h("div", { class: "actions" }, b, note)];
}

function renderTab() {
  stopCheck();
  renderEdits();
  const t = W.tab;
  $$("#game-tabs button").forEach(b => b.classList.toggle("on", b.dataset.tab === t));
  const body = t === "controls" ? controlsTab() : t === "screen" ? screenTab() : t === "fine" ? fineTab() :
    t === "export" ? exportTab() : checkTab();
  $("#game-body").replaceChildren(...body.filter(x => x));
  $("#game-bar").hidden = t === "check" || t === "export" || !W.r.editable;
}

let isDirty = false;
function dirty(v) {
  isDirty = v;
  const n = $("#game-note");
  if (n) n.textContent = v ? "Есть несохранённые правки." : "";
}

function gameHead() {
  const r = W.r;
  const kinds = { wine: "игра Windows (wine.ini)", native: "своя программа (game.ini)", "built-in": "встроенная игра" };
  $("#game-title").textContent = r.name;
  $("#game-meta").textContent = kinds[r.kind] + (r.base_path ? " · рецепт " + r.base_path : "") +
    (r.layer ? " · правки " + r.layer_path : " · правок нет") + (r.running ? " · идёт сейчас" : "");
  if (r.layer_problem) banner("Файл правок не читается (" + r.layer_problem + "): сохраните заново или сбросьте.", true);
  else if (r.layer_state === "broken") banner("bare_app не принял правки: " + (r.layer_error || "?"), true);
  const tabs = r.kind === "wine" ? ["controls", "screen", "fine", "check", "export"] :
    r.kind === "native" ? ["fine", "check", "export"] : ["check"];
  if (!tabs.includes(W.tab)) W.tab = tabs[0];
  $("#game-tabs").replaceChildren(...tabs.map(t => {
    const b = h("button", { class: "tab" }, TABS[t]);
    b.dataset.tab = t;
    b.onclick = () => { W.tab = t; renderTab(); };
    return b;
  }));
  // only buttons move into [keys] (not an axis, a stick's sensitivity, the gyro)
  const buttons = W.schema.controls.filter(c => c.kind === "button" && !c.nolabel).map(c => c.key);
  $("#game-adopt").hidden = !(r.kind === "wine" && ((r.player_controls || {}).pairs || []).some(p =>
    buttons.includes(p.from) && (p.to === "-" || buttons.includes(p.to))));
}

async function loadGame(folder) {
  stopCheck();
  W.folder = folder;
  $("#game-edits").hidden = true;
  $("#game-body").replaceChildren(h("p", { class: "small" }, "Загружаю…"));
  try {
    if (!W.schema) {
      W.schema = await api("GET", "/api/schema");
      $("#actions-list").replaceChildren(...(W.schema.actions || []).filter(a => a.group !== "stick")
        .map(a => h("option", { value: a.name, label: (GROUPS[a.group] || a.group) + ": " + a.name })));
    }
    W.r = await api("GET", "/api/recipe/" + encodeURIComponent(folder));
  } catch (e) { return say(e); }
  W.edits = clone(W.r.layer);
  W.hintTouched = editVal("", "hint") !== undefined;
  W.fineQuery = ""; W.fineOnly = false; W.fineOpen = {};
  dirty(false);
  gameHead();
  renderTab();
}

async function saveGame() {
  // every edit, also those of the tabs not shown
  const bad = [];
  for (const [sec, keys] of Object.entries(W.edits))
    for (const [key, v] of Object.entries(keys))
      for (const x of Array.isArray(v) ? v : [v]) {
        const p = problem(sec, key, String(x));
        if (p) bad.push((sec ? "[" + sec + "] " : "") + key + ": " + p);
      }
  if (bad.length) return say(new Error("Исправьте поля с ошибками: " + bad.join("; ")));
  try {
    const r = await api("PUT", "/api/recipe/" + encodeURIComponent(W.folder) + "/layer", { sections: W.edits });
    banner("Сохранено: " + (r.lines ? r.lines + " строк правок" : "правок нет, рецепт как есть") +
      (r.reloaded ? "" : " (bare_app не запущен: применится при его запуске)") +
      ((r.warnings || []).length ? ". Замечания: " + r.warnings.join("; ") : "") + ". Действует со следующего запуска игры.");
    W.r = r;
    W.edits = clone(r.layer);
    dirty(false);
    gameHead();
    renderTab();
  } catch (e) { say(e); }
}

async function resetGame() {
  if (!confirm("Сбросить все правки рецепта " + W.r.name + "? Останется рецепт прошивки.")) return;
  try {
    W.r = await api("DELETE", "/api/recipe/" + encodeURIComponent(W.folder) + "/layer");
    W.edits = {};
    dirty(false);
    banner("Правки сброшены.");
    gameHead();
    renderTab();
  } catch (e) { say(e); }
}

async function adoptGame() {
  const pc = W.r.player_controls || {};
  if (!confirm("Перенести перестановку кнопок игрока (" + pc.value + ") в правки рецепта? Кнопки и подписи " +
    "перепишутся в [keys] и [labels], а своя перестановка игрока на приставке будет очищена " +
    "(инверсия осей и чувствительность стиков останутся у игрока). Несохранённые правки на странице пропадут.")) return;
  try {
    const r = await api("POST", "/api/recipe/" + encodeURIComponent(W.folder) + "/adopt-controls");
    banner("Перенесено: " + r.moved.map(p => p.from + "→" + p.to).join(", ") +
      (r.kept.length ? "; осталось у игрока: " + r.kept.map(p => p.from + "=" + p.to).join(", ") : ""));
    W.r = r;
    W.edits = clone(r.layer);
    dirty(false);
    gameHead();
    renderTab();
  } catch (e) { say(e); }
}

// #game/FOLDER[/TAB]
function gamePage(arg) {
  const [folder, tab] = arg.split("/");
  if (!folder) { location.hash = "#games"; return; }
  if (TABS[tab]) W.tab = tab;
  loadGame(folder);
}
pages.game = gamePage;

// ---- saved games -----------------------------------------------------------

// a copy of saved games made on the device (game: a folder or "all"), then
// downloaded by the browser
async function makeCopy(game, note, busyText, doneText) {
  note.textContent = busyText;
  try {
    const r = await api("POST", "/api/saves/backup", { game });
    download("/api/saves/copy/" + r.where + "/" + encodeURIComponent(r.name));
    note.textContent = doneText(r.name);
    return r.name;
  } catch (e) {
    note.textContent = "";
    say(e);
    return null;
  }
}

const WHERE = { card: "карта игр, backups", data: "память приставки, backups" };

async function restoreCopy(c) {
  let m;
  try { m = await api("POST", "/api/saves/info", { where: c.where, name: c.name }); } catch (e) { return say(e); }
  const names = (m.games || []).map(g => g.name || g.folder).join(", ");
  const from = (m.unit ? "приставка " + m.unit + ", " : "") + (m.date || "").replace("T", " ").slice(0, 16);
  if (!confirm("Восстановить из копии " + c.name + " (" + from + "):\n" + names + "?\n\n" +
    "Нынешние сохранения " + (m.games && m.games.length > 1 ? "этих игр" : "этой игры") +
    " будут заменены сохранениями из копии. Игра не должна быть запущена.")) return;
  banner("Восстанавливаю…");
  try {
    const r = await api("POST", "/api/saves/restore", { where: c.where, name: c.name });
    banner("Восстановлено: " + (r.restored || []).join(", ") +
      ((r.warnings || []).length ? ". Замечания: " + r.warnings.join("; ") : ""));
    savesPage();
  } catch (e) { say(e); }
}

async function savesPage() {
  const list = $("#saves-list"), copies = $("#saves-copies");
  let r;
  try { r = await api("GET", "/api/saves"); } catch (e) { return say(e); }
  if (r.error) banner(r.error, true);
  const byGame = {};
  for (const c of r.copies) (byGame[c.folder] = byGame[c.folder] || []).push(c);
  const rows = r.games.filter(g => g.size || (byGame[g.folder] || []).length || g.available).map(g => {
    const note = h("div", { class: "small" });
    const n = (byGame[g.folder] || []).length;
    const dl = h("button", { class: "secondary", disabled: !g.size && !g.has_layer },
      "скачать копию");
    dl.onclick = () => makeCopy(g.folder, note,
      "Делаю копию…", name => "Готово: " + name + " (она же лежит в папке backups)").then(savesPage);
    return h("tr", null,
      h("td", null, g.name, h("div", { class: "small" }, g.folder + (r.running === g.folder ? " — запущена" : ""))),
      h("td", null, g.size ? mb(g.size) + " (" + g.files + " ф.)" : "нет данных"),
      h("td", null, n ? n + " шт." : "—"),
      h("td", null, dl, note));
  });
  list.replaceChildren(rows.length ? h("table", null, h("tr", null, h("th", null, "Игра"),
    h("th", null, "Сохранения"), h("th", null, "Копий"), h("th", null, "")), rows)
    : h("p", { class: "small" }, "Игр с сохранениями нет."));
  const all = r.copies.slice().sort((a, b) => (b.date + b.name).localeCompare(a.date + a.name));
  copies.replaceChildren(all.length ? h("table", null, h("tr", null, h("th", null, "Копия"), h("th", null, "Где"),
    h("th", null, "Размер"), h("th", null, "")),
  all.map(c => {
    const url = "/api/saves/copy/" + c.where + "/" + encodeURIComponent(c.name);
    const del = h("button", { class: "danger" }, "удалить");
    del.onclick = async () => {
      if (!confirm("Удалить копию " + c.name + "?")) return;
      try { await api("DELETE", url); savesPage(); } catch (e) { say(e); }
    };
    const back = h("button", { class: "secondary" }, "восстановить");
    back.onclick = () => restoreCopy(c);
    return h("tr", null, h("td", null, c.name, h("div", { class: "small" }, c.auto ? "сделана сама после игры" : "")),
      h("td", null, WHERE[c.where] || c.where), h("td", null, mb(c.size)),
      h("td", null, h("a", { class: "button secondary", href: url }, "скачать"), back, del));
  })) : h("p", { class: "small" }, "Копий пока нет."));
}
pages.saves = savesPage;

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
$("#game-save").onclick = saveGame;
$("#game-reset").onclick = resetGame;
$("#game-adopt").onclick = adoptGame;
$("#saves-all").onclick = () => makeCopy("all", $("#saves-note"), "Делаю копию всей приставки…",
  name => "Готово: " + name + " (она же лежит в папке backups)").then(savesPage);
$("#report-make").onclick = () => makeReport("", $("#report-note")).then(reportsPage);
setupDrops();
setupUpdate();
window.addEventListener("hashchange", show);
window.addEventListener("beforeunload", e => {
  if (uploading || isDirty) { e.preventDefault(); e.returnValue = ""; }
});
show();
