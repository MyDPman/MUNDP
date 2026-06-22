/* Custom country picker. Apply by giving an element the class `country-picker`
   and putting a <input type="hidden" name="..."> inside it (optionally with a
   pre-selected value). Initialised on DOMContentLoaded. */

class CountryPicker {
    constructor(el) {
        this.el = el;
        this.input = el.querySelector('input[type="hidden"]');
        this.button = el.querySelector(".country-picker-button");
        this.flagImg = this.button.querySelector(".country-flag");
        this.labelEl = this.button.querySelector(".country-picker-label");
        this.popup = el.querySelector(".country-picker-popup");
        this.search = el.querySelector(".country-picker-search");
        this.list = el.querySelector(".country-picker-list");
        this.placeholder = el.dataset.placeholder || "Select a country…";
        this.includeChairboard = el.dataset.includeChairboard === "true";

        this.render();
        this.attach();
        if (this.input.value) this.select(this.input.value, { silent: true });
        else this.clear({ silent: true });
    }

    render() {
        let html = "";
        if (this.includeChairboard) {
            html += `
                <li role="option" data-name="Chairboard" data-iso="" class="picker-chairboard">
                    <span class="chairboard-icon" aria-hidden="true">
                        <svg viewBox="0 0 24 24" width="20" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M5 6v9a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V6"/><path d="M9 10h6"/><path d="M9 14h4"/></svg>
                    </span>
                    <span><strong>Chairboard</strong> <span class="muted small">— goes to chairs</span></span>
                </li>
                <li class="picker-divider" aria-hidden="true"></li>
            `;
        }
        html += window.COUNTRIES.map(
            (c) => `
                <li role="option" data-name="${c.name}" data-iso="${c.iso}">
                    <span>${c.name}</span>
                </li>
            `
        ).join("");
        this.list.innerHTML = html;
    }

    attach() {
        this.button.addEventListener("click", (e) => {
            e.stopPropagation();
            this.toggle();
        });
        this.search.addEventListener("input", () => this.filter());
        this.search.addEventListener("keydown", (e) => {
            if (e.key === "Escape") this.close();
            if (e.key === "Enter") {
                e.preventDefault();
                const visible = this.list.querySelector("li:not([hidden])");
                if (visible) this.select(visible.dataset.name);
            }
        });
        this.list.addEventListener("click", (e) => {
            const li = e.target.closest("li");
            if (li) this.select(li.dataset.name);
        });
        document.addEventListener("click", (e) => {
            // Close on outside-button clicks — but the popup may now live in
            // <body>, so check it explicitly as well.
            if (this.el.contains(e.target)) return;
            if (this.popup.contains(e.target)) return;
            if (this.backdrop && this.backdrop.contains(e.target)) return;
            this.close();
        });
    }

    toggle() {
        if (this.popup.hidden) this.open();
        else this.close();
    }

    open() {
        // Move popup to <body> so it escapes any card stacking context and
        // becomes a true centered modal. Add a click-to-dismiss backdrop.
        if (!this.backdrop) {
            this.backdrop = document.createElement("div");
            this.backdrop.className = "country-picker-backdrop";
            this.backdrop.addEventListener("click", () => this.close());
        }
        document.body.appendChild(this.backdrop);
        document.body.appendChild(this.popup);
        this.popup.classList.add("country-picker-popup-modal");
        this.popup.hidden = false;
        this.el.classList.add("open");
        this.search.value = "";
        this.filter();
        setTimeout(() => this.search.focus(), 0);
        // Esc to close
        this._escHandler = (e) => { if (e.key === "Escape") this.close(); };
        document.addEventListener("keydown", this._escHandler);
    }

    close() {
        this.popup.hidden = true;
        this.el.classList.remove("open");
        this.popup.classList.remove("country-picker-popup-modal");
        // Reattach the popup to the picker element so the markup stays tidy.
        if (this.popup.parentNode === document.body) {
            this.el.appendChild(this.popup);
        }
        if (this.backdrop && this.backdrop.parentNode) {
            this.backdrop.parentNode.removeChild(this.backdrop);
        }
        if (this._escHandler) {
            document.removeEventListener("keydown", this._escHandler);
            this._escHandler = null;
        }
    }

    filter() {
        const q = this.search.value.trim().toLowerCase();
        Array.from(this.list.children).forEach((li) => {
            // Dividers and the chairboard row stay visible while searching unless
            // the search clearly doesn't match "chairboard".
            if (li.classList.contains("picker-divider")) {
                li.hidden = !!q;
                return;
            }
            const name = (li.dataset.name || "").toLowerCase();
            const match = !q || name.includes(q);
            li.hidden = !match;
        });
    }

    select(name, { silent } = {}) {
        if (name === "Chairboard") {
            this.input.value = "Chairboard";
            this.labelEl.textContent = "Chairboard";
            this.flagImg.hidden = true;
            this.flagImg.removeAttribute("src");
            this.el.classList.add("has-value", "is-chairboard");
            if (!silent) { this.close(); this._emitChange(); }
            return;
        }
        const c = window.COUNTRY_BY_NAME[name];
        if (!c) return;
        this.input.value = name;
        this.labelEl.textContent = name;
        this.el.classList.add("has-value");
        this.el.classList.remove("is-chairboard");
        if (!silent) { this.close(); this._emitChange(); }
    }

    _emitChange() {
        // Let forms react to a selection (the hidden input's value changes
        // programmatically, which doesn't fire a native event on its own).
        this.input.dispatchEvent(new Event("change", { bubbles: true }));
    }

    clear({ silent } = {}) {
        this.input.value = "";
        this.labelEl.textContent = this.placeholder;
        this.flagImg.removeAttribute("src");
        this.flagImg.hidden = true;
        this.el.classList.remove("has-value", "is-chairboard");
        if (!silent) { this.close(); this._emitChange(); }
    }
}

window.CountryPicker = CountryPicker;
document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll(".country-picker").forEach((el) => new CountryPicker(el));
});
