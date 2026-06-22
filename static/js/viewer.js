import * as pdfjsLib from "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.6.82/pdf.min.mjs";

pdfjsLib.GlobalWorkerOptions.workerSrc =
    "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/4.6.82/pdf.worker.min.mjs";

const { docId, pdfUrl, commentsUrl, currentUserId, currentUserRole, csrfToken } = window.MUNDP;

const canvas = document.getElementById("pdf-canvas");
const ctx = canvas ? canvas.getContext("2d") : null;
const pageNumEl = document.getElementById("page-num");
const pageCountEl = document.getElementById("page-count");
const zoomLevelEl = document.getElementById("zoom-level");
const currentPageHintEl = document.getElementById("current-page-hint");
const hasPdfViewer = !!canvas;

let pdfDoc = null;
let currentPage = 1;
let scale = 1.25;
let rendering = false;
let pendingPage = null;

function renderPage(num) {
    rendering = true;
    pdfDoc.getPage(num).then((page) => {
        const viewport = page.getViewport({ scale });
        const dpr = window.devicePixelRatio || 1;
        canvas.width = viewport.width * dpr;
        canvas.height = viewport.height * dpr;
        canvas.style.width = viewport.width + "px";
        canvas.style.height = viewport.height + "px";
        const renderCtx = {
            canvasContext: ctx,
            viewport,
            transform: dpr !== 1 ? [dpr, 0, 0, dpr, 0, 0] : null,
        };
        page.render(renderCtx).promise.then(() => {
            rendering = false;
            if (pendingPage !== null) {
                const next = pendingPage;
                pendingPage = null;
                renderPage(next);
            }
        });
    });
    pageNumEl.textContent = num;
    if (currentPageHintEl) currentPageHintEl.textContent = num;
}

function queueRender(num) {
    if (rendering) pendingPage = num;
    else renderPage(num);
}

function goToPage(num) {
    if (!pdfDoc) return;
    const n = Math.max(1, Math.min(pdfDoc.numPages, Number(num)));
    currentPage = n;
    queueRender(n);
    document.getElementById("pdf-container").scrollIntoView({ behavior: "smooth", block: "start" });
}

if (hasPdfViewer) {
    document.getElementById("prev-page").addEventListener("click", () => {
        if (currentPage <= 1) return;
        currentPage--;
        queueRender(currentPage);
    });
    document.getElementById("next-page").addEventListener("click", () => {
        if (!pdfDoc || currentPage >= pdfDoc.numPages) return;
        currentPage++;
        queueRender(currentPage);
    });
    document.getElementById("zoom-in").addEventListener("click", () => {
        scale = Math.min(3.0, scale + 0.25);
        zoomLevelEl.textContent = Math.round(scale * 100) + "%";
        queueRender(currentPage);
    });
    document.getElementById("zoom-out").addEventListener("click", () => {
        scale = Math.max(0.5, scale - 0.25);
        zoomLevelEl.textContent = Math.round(scale * 100) + "%";
        queueRender(currentPage);
    });

    pdfjsLib.getDocument(pdfUrl).promise.then((pdf) => {
        pdfDoc = pdf;
        pageCountEl.textContent = pdf.numPages;
        zoomLevelEl.textContent = Math.round(scale * 100) + "%";
        renderPage(currentPage);
    }).catch((err) => {
        document.getElementById("pdf-container").innerHTML =
            `<p style="color:white;padding:20px">Failed to load PDF: ${err.message}</p>`;
    });
}

// ---------------------------------------------------------------------------
// Comments
// ---------------------------------------------------------------------------
const commentsList = document.getElementById("comments-list");
const commentForm = document.getElementById("comment-form");
const commentBody = document.getElementById("comment-body");
const attachPage = document.getElementById("attach-page");
const clauseInput = document.getElementById("amend-clause");

function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
}

function formatDate(iso) {
    return window.fmtLocal ? window.fmtLocal(iso, "short") : iso;
}

function formatLocation(c) {
    const parts = [c.clause, c.sub_clause, c.sub_sub_clause]
        .filter((p) => p && String(p).trim());
    return parts.join(" · ");
}

function renderComment(c) {
    const canDelete = currentUserRole === "admin"; // server also checks author
    const locLabel = formatLocation(c);
    const submitter = c.author_delegation || c.author_name;
    return `
        <div class="comment" data-id="${c.id}">
            <div class="comment-header">
                <span>
                    <strong>${escapeHtml(submitter)}</strong>
                    <span class="role role-${c.author_role}">${c.author_role}</span>
                </span>
                <span class="comment-meta">
                    ${c.page_number ? `<button type="button" class="comment-page-badge" data-page="${c.page_number}" title="Jump to page ${c.page_number}">p.${c.page_number}</button> ` : ""}
                    ${escapeHtml(formatDate(c.created_at))}
                </span>
            </div>
            ${locLabel ? `<div class="amend-location-pill">${escapeHtml(locLabel)}</div>` : ""}
            <div class="comment-body">${escapeHtml(c.body)}</div>
            ${canDelete ? `<button type="button" class="comment-delete" data-id="${c.id}">Delete</button>` : ""}
        </div>
    `;
}

function renderComments(items) {
    if (items.length === 0) {
        commentsList.innerHTML = `<p class="muted small">No amendments yet. Be the first to propose a change.</p>`;
        return;
    }
    commentsList.innerHTML = items.map(renderComment).join("");
    commentsList.querySelectorAll(".comment-delete").forEach((btn) => {
        btn.addEventListener("click", () => deleteComment(btn.dataset.id));
    });
    commentsList.querySelectorAll(".comment-page-badge").forEach((btn) => {
        btn.addEventListener("click", () => goToPage(btn.dataset.page));
    });
}

async function loadComments() {
    const res = await fetch(commentsUrl, { credentials: "same-origin" });
    if (!res.ok) {
        commentsList.innerHTML = `<p class="muted small">Failed to load amendments.</p>`;
        return;
    }
    renderComments(await res.json());
}

async function deleteComment(id) {
    if (!confirm("Delete this amendment?")) return;
    const res = await fetch(`${commentsUrl}/${id}`, {
        method: "DELETE",
        credentials: "same-origin",
        headers: { "X-CSRF-Token": csrfToken },
    });
    if (res.ok) loadComments();
    else alert("Could not delete amendment.");
}

if (commentForm) commentForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = commentBody.value.trim();
    const location = clauseInput ? clauseInput.value.trim() : "";
    if (!body) return;
    if (!location) {
        alert("Specify the location this amendment targets.");
        return;
    }
    const payload = {
        body,
        page_number: attachPage.checked ? currentPage : null,
        clause: location,
    };
    const res = await fetch(commentsUrl, {
        method: "POST",
        credentials: "same-origin",
        headers: {
            "Content-Type": "application/json",
            "X-CSRF-Token": csrfToken,
        },
        body: JSON.stringify(payload),
    });
    if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        alert(err.error || "Could not submit amendment.");
        return;
    }
    commentBody.value = "";
    if (clauseInput) clauseInput.value = "";
    loadComments();
});

loadComments();
// Live-sync the amendments list every 4 seconds — fetch() bypasses the
// loading overlay so it stays silent.
setInterval(loadComments, 4000);
