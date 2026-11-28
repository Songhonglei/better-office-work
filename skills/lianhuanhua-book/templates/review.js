"use strict";

const $ = id => document.getElementById(id);
let book, pageNo = 0, shown, compared, detailId, pin, picking = false, busy = false, noticeTimer;
let queue = { worker_active: false, tasks: [] }, queueBusy = false;

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

function changePage(number) {
    if (!book.pages[number]) return;
    pageNo = number;
    shown = currentPage().selected;
    compared = undefined;
    pin = undefined;
    picking = false;
    $("message").value = "";
    history.replaceState(null, "", `#p${pageNo}`);
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
    $("pin-hint").hidden = !picking && !pin;
    $("pin-hint").textContent = picking ? "点击画面上的位置" : "保存时会记住这个位置";
    $("pins").querySelector(".draft")?.remove();
    if (pin) $("pins").append(makeMarker("＋", pin, true));
}

function renderRail() {
    const rail = $("page-list");
    const scroll = [rail.scrollTop, rail.scrollLeft];
    rail.replaceChildren(...book.pages.map(page => {
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
    $("version").replaceChildren(...page.versions.slice().reverse().map(v => option(v.id, versionLabel(page, v))));
    $("version").value = shown || "";
    $("version").disabled = !version;
    $("keep").disabled = !version || shown === page.selected || busy;
    $("comparison-label").textContent = comparing ? versionLabel(page, alternatives.find(v => v.id === compared)) : "";
    $("compared-version").replaceChildren(...alternatives.slice().reverse().map(v => option(v.id, versionLabel(page, v))));
    $("compared-version").value = compared || "";
    $("art-label").textContent = version ? `${versionLabel(page, version)}${shown === page.selected ? " · 当前审图稿" : ""}` : "本页等待出图";
    $("art").alt = version ? pageLabel(page) : "";
    if (version) $("art").src = imageUrl(page.no, shown);
    else $("art").removeAttribute("src");
    if (comparing) {
        $("comparison-art").src = imageUrl(page.no, compared);
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
    $("pick-pin").disabled = !shown;
    $("pins").replaceChildren();
    $("notes").replaceChildren(...notes.map((note, i) => {
        if (note.pin) $("pins").append(makeMarker(i + 1, note.pin));
        const li = node("li", undefined, note.resolved ? "done" : undefined);
        li.append(node("p", note.text), node("small", [note.pin ? `标点 ${i + 1}` : null, note.detail ? detailLabel(note.detail) : "整页", note.resolved ? "已处理" : "待处理"].filter(Boolean).join(" · ")));
        const button = node("button", note.resolved ? "重新打开" : "标为已处理");
        button.type = "button";
        button.disabled = busy;
        button.addEventListener("click", () => change({ action: "resolve", page: page.no, version: note.version, note: note.id, resolved: !note.resolved }, "批注状态已保存"));
        li.append(button);
        const inQueue = queue.tasks.some(task => task.annotation === note.id && task.status !== "cancelled");
        const rework = node("button", inQueue ? "已加入返工" : "转为返工任务", "add-rework");
        rework.type = "button";
        rework.disabled = inQueue;
        rework.addEventListener("click", async () => {
            if (await updateQueue({ action: "enqueue", page: page.no, version: note.version, note: note.id }, "已加入返工队列")) {
                renderNotes(currentPage());
                $("rework").scrollIntoView({ block: "nearest" });
            }
        });
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
        compared = currentPage().baseline;
        $("compare").checked = true;
        render();
        $("page-title").scrollIntoView({ block: "nearest" });
    } catch (error) {
        notify(error.message, true);
    }
}

function renderQueue() {
    const waiting = queue.tasks.filter(t => t.status === "queued").length;
    const paused = queue.tasks.some(t => t.status === "paused" || t.status === "running");
    const run = $("run-rework");
    run.textContent = paused && !queue.worker_active ? "续跑下一项" : "运行下一项";
    run.disabled = queueBusy || queue.worker_active || !(waiting || paused);
    $("rework-status").textContent = queue.worker_active ? "正在处理一页" : queue.tasks.length ? `${waiting} 项待运行` : "可从任一批注加入返工任务。";
    $("rework-tasks").replaceChildren(...queue.tasks.map(task => {
        const li = node("li", undefined, "rework-task");
        li.dataset.task = task.id;
        li.dataset.page = task.page;
        li.dataset.status = task.status;
        const text = node("div");
        text.append(node("strong", pageLabel(book.pages[task.page])), node("p", task.instruction));
        text.append(node("small", `${taskStatus[task.status] || task.status} · 优先级 ${task.priority}`));
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
    shown = e.target.value;
    pin = undefined;
    picking = false;
    $("message").value = "";
    render();
});
$("keep").addEventListener("click", () => change({ action: "select", page: pageNo, version: shown }, "审图稿已切换"));
$("compare").addEventListener("change", () => renderProof(currentPage()));
$("compared-version").addEventListener("change", e => { compared = e.target.value; renderProof(currentPage()); });
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
        const match = /^#p(\d+)$/.exec(location.hash);
        changePage(match && book.pages[Number(match[1])] ? Number(match[1]) : 0);
        renderQueue();
        setInterval(() => { if (!document.hidden) fetchQueue(); }, 1700);
    } catch (error) {
        notify(error.message || "工作台加载失败", true);
    }
}

openBook();
