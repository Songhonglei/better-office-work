"use strict";

const $ = id => document.getElementById(id);
let book, pageNo = 0, shown, compared, detailId, pin, picking = false, busy = false, noticeTimer;
let queue = { worker_active: false, tasks: [] }, queueBusy = false;
let activeTask, cropView = false, dialogNote, region, dragStart;

const taskStatus = { queued: "待运行", running: "运行中", paused: "可续跑", candidate_ready: "候选稿待审",
    failed: "失败", stale: "分镜已变更", cancelled: "已撤回" };

function imageUrl(page, version, extras = {}) {
    return "/api/image?" + new URLSearchParams({ page, version, ...extras });
}

function node(tag, text, className) {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = text;
    if (className) element.className = className;
    return element;
}

function option(value, label) {
    const element = node("option", label);
    element.value = value;
    return element;
}

function notify(message, error = false) {
    clearTimeout(noticeTimer);
    $("notice").textContent = message;
    $("notice").classList.toggle("error", error);
    $("notice").hidden = !message;
    if (!error && message) noticeTimer = setTimeout(() => { $("notice").hidden = true; }, 3200);
}

function currentPage() { return book.pages[pageNo]; }

function pageLabel(p) {
    return p.no ? `第 ${p.no} 页 ${p.title}` : `封面 ${p.title}`;
}

function detailLabel(id) {
    return book.details.find(d => d.id === id)?.label || id;
}

function versionLabel(page, v) {
    const index = page.versions.indexOf(v) + 1;
    const model = /Q[46]/.exec(v.model)?.[0];
    const baseline = page.versions.find(item => item.id === page.baseline);
    const label = v.id === page.baseline ? "阅读稿" : v.digest === baseline?.digest ? "同图留档" : "归档稿";
    return [`第 ${index} 稿`, label, model].filter(Boolean).join(" / ");
}

function awaiting(task) { return task.status === "candidate_ready" && task.review === "pending"; }

function clearFocus() {
    activeTask = undefined;
    cropView = false;
    history.replaceState(null, "", `#p${pageNo}`);
}

function changePage(number) {
    if (!book.pages[number]) return;
    pageNo = number;
    shown = currentPage().selected;
    compared = undefined;
    clearFocus();
    pin = undefined;
    picking = false;
    $("message").value = "";
    render();
    if (window.matchMedia("(max-width: 670px)").matches) {
        $("page-title").scrollIntoView({ block: "nearest" });
    }
}

function makeMarker(label, point, draft = false) {
    const marker = node("span", label, draft ? "pin draft" : "pin");
    marker.style.left = `${point[0] * 100}%`;
    marker.style.top = `${point[1] * 100}%`;
    return marker;
}

function updatePin() {
    $("pick-pin").setAttribute("aria-pressed", picking ? "true" : "false");
    $("pick-pin").textContent = pin ? "清除标点" : "在画面上标点";
    $("position").classList.toggle("picking", picking);
    $("pin-hint").hidden = cropView || (!picking && !pin);
    $("pin-hint").textContent = picking ? "点击画面上的位置" : "保存时会记住这个位置";
    $("pins").querySelector(".draft")?.remove();
    if (pin && !cropView) $("pins").append(makeMarker("＋", pin, true));
}

function renderRail() {
    const rail = $("page-list");
    const scroll = [rail.scrollTop, rail.scrollLeft];
    const filter = $("page-filter").value;
    const pages = book.pages.filter(page => {
        const tasks = queue.tasks.filter(t => t.page === page.no);
        if (filter === "notes") return page.notes.some(n => !n.resolved);
        if (filter === "working") return tasks.some(t => ["queued", "running", "paused"].includes(t.status));
        if (filter === "candidate") return tasks.some(awaiting);
        return true;
    });
    rail.replaceChildren(...pages.map(page => {
        const button = node("button", undefined, "page-item");
        button.type = "button";
        button.setAttribute("aria-label", pageLabel(page));
        button.setAttribute("aria-current", page.no === pageNo ? "page" : "false");
        if (page.selected) {
            const image = node("img");
            image.src = imageUrl(page.no, page.selected, { thumb: "1" });
            image.alt = "";
            image.loading = "lazy";
            button.append(image);
        } else {
            button.append(node("span", undefined, "placeholder"));
        }
        const title = node("span", page.no ? `${page.no} ${page.title}` : "封面");
        const open = page.notes.filter(n => !n.resolved).length;
        if (open) title.append(node("small", `${open} 条批注`));
        button.append(title);
        button.addEventListener("click", () => changePage(page.no));
        return button;
    }));
    if (!pages.length) rail.append(node("p", "没有符合筛选条件的页面。"));
    [rail.scrollTop, rail.scrollLeft] = scroll;
}

function renderProof(page) {
    const version = page.versions.find(v => v.id === shown);
    const alternatives = page.versions.filter(v => v.digest !== version?.digest);
    if (!alternatives.some(v => v.id === compared)) {
        compared = alternatives.find(v => v.id === page.baseline)?.id || alternatives.at(-1)?.id;
    }
    $("compare").disabled = !alternatives.length;
    const comparing = Boolean($("compare").checked && compared);
    $("comparison-controls").hidden = !comparing;
    $("comparison-proof").hidden = !comparing;
    $("artwork").classList.toggle("side-by-side", comparing);
    const focus = activeTask?.scope === "local";
    const extras = focus && cropView ? { task: activeTask.id } : {};
    $("artwork").classList.toggle("region-focus", Boolean(extras.task));
    $("region-toolbar").hidden = !focus;
    $("toggle-region").textContent = cropView ? "看整幅" : "看圈选局部";
    $("candidate-note").textContent = focus ? activeTask.instruction : "";
    $("version").replaceChildren(...page.versions.slice().reverse().map(v => option(v.id, versionLabel(page, v))));
    $("version").value = shown || "";
    $("version").disabled = !version;
    $("keep").disabled = !version || shown === page.selected || busy;
    $("comparison-label").textContent = comparing ? versionLabel(page, alternatives.find(v => v.id === compared)) : "";
    $("compared-version").replaceChildren(...alternatives.slice().reverse().map(v => option(v.id, versionLabel(page, v))));
    $("compared-version").value = compared || "";
    $("art-label").textContent = version ? `${versionLabel(page, version)}${shown === page.selected ? " · 当前审图稿" : ""}` : "本页等待出图";
    $("art").alt = version ? pageLabel(page) : "";
    if (version) $("art").src = imageUrl(page.no, shown, extras);
    else $("art").removeAttribute("src");
    if (comparing) {
        $("comparison-art").src = imageUrl(page.no, compared, extras);
        $("comparison-art").alt = `${pageLabel(page)}对照稿`;
    } else $("comparison-art").removeAttribute("src");
    $("draft-caption").textContent = page.caption;
    $("draft-caption").hidden = !page.caption;
}

function renderNotes(page) {
    const notes = page.notes.filter(n => n.version === shown);
    const previousDetail = $("note-detail").value;
    $("annotation-count").textContent = `${notes.length} 条`;
    $("note-detail").replaceChildren(option("", "整页"), ...page.details.map(id => option(id, detailLabel(id))));
    $("note-detail").value = page.details.includes(previousDetail) ? previousDetail : "";
    $("save-note").disabled = !shown || busy;
    $("pick-pin").disabled = !shown || cropView;
    $("pins").replaceChildren();
    $("notes").replaceChildren(...notes.map((note, i) => {
        if (note.pin && !cropView) $("pins").append(makeMarker(i + 1, note.pin));
        const li = node("li", undefined, note.resolved ? "done" : undefined);
        li.append(node("p", note.text), node("small", [note.pin ? `标点 ${i + 1}` : null, note.detail ? detailLabel(note.detail) : "整页", note.resolved ? "已处理" : "待处理"].filter(Boolean).join(" · ")));
        const button = node("button", note.resolved ? "重新打开" : "标为已处理");
        button.type = "button";
        button.disabled = busy;
        button.addEventListener("click", () => change({ action: "resolve", page: page.no, version: note.version, note: note.id, resolved: !note.resolved }, "批注状态已保存"));
        li.append(button);
        const rework = node("button", "转为返工任务", "add-rework");
        rework.type = "button";
        rework.addEventListener("click", () => openScope(page, note));
        li.append(rework);
        return li;
    }));
    updatePin();
}

function renderDetails() {
    $("continuity").hidden = !book.details.length;
    if (!book.details.length) return;
    const detail = book.details.find(d => d.id === detailId) || book.details[0];
    detailId = detail.id;
    $("detail").replaceChildren(...book.details.map(d => option(d.id, d.label)));
    $("detail").value = detailId;
    $("detail-rule").textContent = detail.rule || "";
    $("detail-rule").hidden = !detail.rule;
    $("detail-pages").replaceChildren(...detail.pages.map(occurrence => {
        const page = book.pages[occurrence.no];
        const card = node("button", undefined, "detail-card");
        card.type = "button";
        if (page.selected) {
            const image = node("img");
            image.src = imageUrl(page.no, page.selected, { detail: detailId });
            image.alt = `${pageLabel(page)} ${detail.label}${occurrence.has_crop ? "局部" : ""}`;
            image.loading = "lazy";
            card.append(image);
        }
        card.append(node("strong", pageLabel(page)));
        if (occurrence.rule) card.append(node("small", occurrence.rule));
        card.addEventListener("click", () => changePage(page.no));
        return card;
    }));
}

function render() {
    const page = currentPage();
    $("page-title").textContent = pageLabel(page);
    $("previous").disabled = pageNo === 0;
    $("next").disabled = pageNo === book.pages.length - 1;
    renderRail();
    renderProof(page);
    renderNotes(page);
    renderDetails();
}

async function viewCandidate(task) {
    try {
        const response = await fetch("/api/book");
        if (!response.ok) throw new Error("读取候选稿失败");
        book = await response.json();
        changePage(task.page);
        shown = task.candidate;
        compared = task.scope === "local" ? task.source_version : currentPage().baseline;
        activeTask = task;
        cropView = task.scope === "local";
        $("compare").checked = true;
        history.replaceState(null, "", `#p${task.page}~${task.id}`);
        render();
        $(task.scope === "local" ? "region-toolbar" : "artwork").scrollIntoView({ block: "start" });
    } catch (error) {
        notify(error.message, true);
    }
}

function paintRegion() {
    const box = $("region-box");
    box.hidden = !region;
    if (region) {
        [box.style.left, box.style.top, box.style.width, box.style.height] =
            [region[0], region[1], region[2] - region[0], region[3] - region[1]].map(v => `${v * 100}%`);
    }
    const local = $("rework-scope").value === "local";
    $("region-picker").hidden = !local;
    $("add-rework-confirm").disabled = local && (!region || region[2] - region[0] < .01 || region[3] - region[1] < .01);
    $("region-status").textContent = region ? "已圈选范围，可拖动重选。" : "在图上拖动，框住要修改的部分。";
}

function openScope(page, note) {
    dialogNote = { page: page.no, version: note.version, note: note.id };
    region = dragStart = undefined;
    $("origin-note").textContent = note.text;
    $("region-image").src = imageUrl(page.no, note.version);
    $("rework-scope").value = "local";
    $("rework-preset").value = "qwen-q4";
    paintRegion();
    $("rework-dialog").showModal();
}

function regionPoint(event) {
    const rect = $("region-image").getBoundingClientRect();
    return [(event.clientX - rect.left) / rect.width, (event.clientY - rect.top) / rect.height]
        .map(value => Math.min(1, Math.max(0, value)));
}

$("region-target").addEventListener("pointerdown", e => {
    if (!$("region-image").naturalWidth) return;
    dragStart = regionPoint(e);
    region = [...dragStart, ...dragStart];
    e.currentTarget.setPointerCapture(e.pointerId);
    paintRegion();
});
$("region-target").addEventListener("pointermove", e => {
    if (!dragStart) return;
    const [x, y] = regionPoint(e);
    region = [Math.min(x, dragStart[0]), Math.min(y, dragStart[1]), Math.max(x, dragStart[0]), Math.max(y, dragStart[1])];
    paintRegion();
});
for (const event of ["pointerup", "pointercancel"]) {
    $("region-target").addEventListener(event, () => { dragStart = undefined; });
}
$("rework-scope").addEventListener("change", paintRegion);
$("clear-region").addEventListener("click", () => { region = undefined; paintRegion(); });
$("close-rework").addEventListener("click", () => $("rework-dialog").close());
$("rework-form").addEventListener("submit", async e => {
    e.preventDefault();
    const scope = $("rework-scope").value;
    const box = scope === "local" ? region?.map(n => Number(n.toFixed(6))) : null;
    $("add-rework-confirm").disabled = true;
    if (await updateQueue({ action: "enqueue", ...dialogNote, scope, box, preset: $("rework-preset").value }, "已加入返工队列")) {
        $("rework-dialog").close();
        $("rework").scrollIntoView({ block: "start" });
    } else paintRegion();
});

function renderQueue() {
    const waiting = queue.tasks.filter(t => t.status === "queued").length;
    const paused = queue.tasks.some(t => t.status === "paused" || t.status === "running");
    const run = $("run-rework");
    run.textContent = paused && !queue.worker_active ? "续跑下一项" : "运行下一项";
    run.disabled = queueBusy || queue.worker_active || !(waiting || paused);
    $("rework-status").textContent = queue.worker_active ? "正在处理一页" : queue.tasks.length ? `${waiting} 项待运行` : "可从任一批注加入返工任务。";
    const actionable = queue.tasks.filter(t => ["queued", "running", "paused"].includes(t.status) || awaiting(t)).length;
    $("queue-count").textContent = actionable ? `(${actionable})` : "";
    $("next-to-review").disabled = !queue.tasks.some(awaiting);
    $("rework-tasks").replaceChildren(...queue.tasks.map(task => {
        const li = node("li", undefined, "rework-task");
        li.dataset.task = task.id;
        li.dataset.page = task.page;
        li.dataset.status = task.status;
        const text = node("div");
        text.append(node("strong", pageLabel(book.pages[task.page])), node("p", task.instruction));
        text.append(node("small", `${taskStatus[task.status] || task.status} · ${task.scope === "local" ? "局部修订" : "整页重画"} · 优先级 ${task.priority}`));
        if (task.error) text.append(node("small", task.error));
        const controls = node("div", undefined, "task-controls");
        if (task.status === "queued") {
            const label = node("label", "优先级");
            const rank = node("select");
            rank.setAttribute("aria-label", `${pageLabel(book.pages[task.page])}优先级`);
            rank.replaceChildren(...[5, 4, 3, 2, 1].map(n => option(n, n === 5 ? "5 最先" : String(n))));
            rank.value = task.priority;
            rank.disabled = queueBusy;
            rank.addEventListener("change", e => updateQueue({ action: "priority", task: task.id, priority: Number(e.target.value) }, "优先级已保存"));
            label.append(rank);
            const cancel = node("button", "撤回");
            cancel.addEventListener("click", () => updateQueue({ action: "cancel", task: task.id }, "已撤回该任务"));
            controls.append(label, cancel);
        }
        if (task.candidate) {
            const outcome = node("button", "查看候选稿");
            outcome.addEventListener("click", () => viewCandidate(task));
            controls.append(outcome);
        }
        li.append(text, controls);
        return li;
    }));
}

async function fetchQueue() {
    if (queueBusy) return;
    try {
        const response = await fetch("/api/rework");
        if (!response.ok) throw new Error("读取返工队列失败");
        const current = await response.json();
        if (JSON.stringify(current) === JSON.stringify(queue)) return;
        queue = current;
        renderQueue();
        if ($("page-filter").value !== "all") renderRail();
    } catch (error) {
        $("rework-status").textContent = error.message;
    }
}

async function updateQueue(request, message) {
    if (queueBusy) return false;
    queueBusy = true;
    $("run-rework").disabled = true;
    try {
        const reply = await fetch("/api/rework", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(request) });
        const current = await reply.json();
        if (!reply.ok) throw new Error(current.error);
        queue = current;
        notify(message);
        return true;
    } catch (error) {
        notify(error.message, true);
        return false;
    } finally {
        queueBusy = false;
        renderQueue();
        if ($("page-filter").value !== "all") renderRail();
    }
}

async function change(request, message) {
    if (busy) return false;
    busy = true;
    $("save-note").disabled = true;
    $("keep").disabled = true;
    try {
        const response = await fetch("/api/review", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(request) });
        const result = await response.json();
        if (!response.ok) throw new Error(result.error);
        book = result;
        if (request.action === "annotate" && pageNo === request.page && shown === request.version) {
            $("message").value = "";
            pin = undefined;
            picking = false;
        }
        notify(message);
        return true;
    } catch (error) {
        notify(error.message || "保存失败，请重试", true);
        return false;
    } finally {
        busy = false;
        render();
    }
}

$("previous").addEventListener("click", () => changePage(pageNo - 1));
$("next").addEventListener("click", () => changePage(pageNo + 1));
$("version").addEventListener("change", e => {
    clearFocus();
    shown = e.target.value;
    pin = undefined;
    picking = false;
    $("message").value = "";
    render();
});
$("keep").addEventListener("click", () => change({ action: "select", page: pageNo, version: shown }, "审图稿已切换"));
$("compare").addEventListener("change", () => renderProof(currentPage()));
$("compared-version").addEventListener("change", e => { clearFocus(); compared = e.target.value; renderProof(currentPage()); renderNotes(currentPage()); });
$("detail").addEventListener("change", e => { detailId = e.target.value; renderDetails(); });
$("pick-pin").addEventListener("click", () => {
    if (pin) pin = undefined;
    else picking = !picking;
    updatePin();
});
$("position").addEventListener("click", e => {
    if (!picking) return;
    const area = $("art").getBoundingClientRect();
    if (!area.width || !area.height) return;
    pin = [(e.clientX - area.left) / area.width, (e.clientY - area.top) / area.height]
        .map(value => Math.min(1, Math.max(0, value)));
    picking = false;
    updatePin();
    $("message").focus();
});
$("note-form").addEventListener("submit", e => {
    e.preventDefault();
    change({ action: "annotate", page: pageNo, version: shown, detail: $("note-detail").value || null,
        message: $("message").value, pin }, "批注已保存");
});
$("run-rework").addEventListener("click", () => updateQueue({ action: "run" }, "已请求运行下一项"));
$("toggle-region").addEventListener("click", () => { cropView = !cropView; picking = false; renderProof(currentPage()); renderNotes(currentPage()); });
$("page-filter").addEventListener("change", renderRail);
$("next-to-review").addEventListener("click", () => {
    const candidates = queue.tasks.filter(awaiting).sort((a, b) => a.page - b.page || b.created.localeCompare(a.created));
    const next = candidates.find(t => t.page > pageNo) || candidates[0];
    if (next) viewCandidate(next);
});
for (const button of document.querySelectorAll("[data-jump]")) {
    button.addEventListener("click", () => $(button.dataset.jump).scrollIntoView({ block: "start" }));
}

async function openBook() {
    try {
        const response = await fetch("/api/book");
        book = await response.json();
        if (!response.ok) throw new Error(book.error);
        document.title = `${book.title} · 整册审图`;
        $("book-title").textContent = book.title;
        $("page-count").textContent = `${book.pages.length} 页`;
        if (book.reader) {
            $("reader").href = book.reader;
            $("reader").hidden = false;
        }
        await fetchQueue();
        $("workspace").hidden = false;
        $("work-tabs").hidden = false;
        const match = /^#p(\d+)(?:~([a-f0-9]+))?$/.exec(location.hash);
        const deepTask = match && queue.tasks.find(t => t.page === Number(match[1]) && t.id === match[2] && t.candidate);
        changePage(match && book.pages[Number(match[1])] ? Number(match[1]) : 0);
        renderQueue();
        if (deepTask) await viewCandidate(deepTask);
        setInterval(() => { if (!document.hidden) fetchQueue(); }, 1700);
    } catch (error) {
        notify(error.message || "工作台加载失败", true);
    }
}

openBook();
