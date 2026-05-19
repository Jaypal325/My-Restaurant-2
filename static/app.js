let state = {};
let calcBill = [];
let tableBills = {};
let selectedTable = null;
let editTablesMode = false;

const COLORS = ["#176b87", "#1d7a55", "#c2412d", "#7c3aed", "#b7791f", "#2563eb", "#be185d", "#374151"];
const DEFAULT_REMINDER_MESSAGE = "Namaste {name}, your udhari of {amount} is pending at {store}. Please pay when possible.";
const rupee = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 });
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

async function api(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Request failed");
  state = data.state || data;
  render();
  return data;
}

async function loadState() {
  const response = await fetch("/api/state");
  state = await response.json();
  render();
  checkReminders();
}

function toast(message) {
  const el = $("#toast");
  el.textContent = message;
  el.classList.add("show");
  setTimeout(() => el.classList.remove("show"), 2400);
}

function total(items) {
  return items.reduce((sum, item) => sum + Number(item.price) * Number(item.qty), 0);
}

function formData(form) {
  return Object.fromEntries(new FormData(form).entries());
}

function collectExtra(area, root) {
  const extra = {};
  root.querySelectorAll(`[data-extra-area="${area}"]`).forEach((input) => {
    extra[input.name] = input.value;
  });
  return extra;
}

function fieldsFor(area) {
  return (state.custom_fields || []).filter((field) => field.area === area);
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"
  }[char]));
}

function escapeAttr(value) {
  return escapeHtml(value).replace(/"/g, "&quot;");
}

function render() {
  renderStoreName();
  renderStats();
  renderMethods();
  renderProducts();
  renderBill(calcBill, "#billItems", "#calcTotal");
  renderCustomers();
  renderStock();
  renderTables();
  renderTableBill();
  renderProfit();
  renderFields();
  renderExtraFields();
  renderColorChoices($("#productForm").elements.namedItem("color").value || COLORS[0]);
  renderProductManager();
  renderNotificationBadge();
  renderNotifications();
}

function renderStoreName() {
  $("#storeNameBtn").textContent = state.settings?.store_name || "My Restaurant";
}

function renderStats() {
  const target = $("#stats");
  if (!target) return;
  const s = state.summary || {};
  target.innerHTML = [
    ["Current amount", s.current_total],
    ["Paid income", s.income],
    ["Expenses", s.expense],
    ["Net profit", s.net_profit],
    ["Pending udhari", s.udhari_total],
  ].map(([label, value]) => `
    <article class="stat">
      <small>${label}</small>
      <strong>${rupee.format(value || 0)}</strong>
    </article>
  `).join("");
}

function renderMethods() {
  const accounts = state.summary?.accounts || [];
  const methodOptions = accounts.map((a) => `<option value="${escapeAttr(a.name.toLowerCase())}">${escapeHtml(a.name)}</option>`).join("");
  ["#calcMethod", "#stockMethod", "#tableMethod"].forEach((id) => {
    const el = $(id);
    if (el) el.innerHTML = methodOptions;
  });
  const txAccount = $("#transactionAccount");
  if (txAccount) {
    txAccount.innerHTML = accounts.map((a) => `<option value="${a.id}">${escapeHtml(a.name)}</option>`).join("");
  }
}

function renderProducts() {
  const products = state.products || [];
  const html = products.length ? products.map(productButton).join("") : `<div class="empty">Use the menu button to add Chai, Coffee, snacks, meals, or any product.</div>`;
  $("#productGrid").innerHTML = html;
  $("#tableProducts").innerHTML = html;
}

function productButton(product) {
  return `
    <div class="product-wrap">
      <button class="product-btn" data-product="${product.id}" style="background:${escapeAttr(product.color)}">
        <strong>${escapeHtml(product.name)}</strong>
        <span>${rupee.format(product.price)}</span>
      </button>
    </div>
  `;
}

function renderProductManager() {
  const list = $("#productManagerList");
  if (!list) return;
  const products = state.products || [];
  list.innerHTML = products.length ? products.map((product) => `
    <article class="manager-row" draggable="true" data-product-id="${product.id}">
      <span class="manager-dot" style="background:${escapeAttr(product.color)}"></span>
      <div>
        <strong>${escapeHtml(product.name)}</strong>
        <small>${rupee.format(product.price)}</small>
      </div>
      <button type="button" class="ghost" data-manage-edit="${product.id}">Edit</button>
      <button type="button" class="danger" data-manage-delete="${product.id}">Delete</button>
    </article>
  `).join("") : `<div class="empty">No calculator buttons yet.</div>`;
}

function defaultReminderValue() {
  const date = new Date();
  date.setDate(date.getDate() + 7);
  date.setMinutes(date.getMinutes() - date.getTimezoneOffset());
  return date.toISOString().slice(0, 16);
}

function dueCustomers() {
  const now = new Date();
  return (state.summary?.customers || []).filter((customer) => (
    customer.balance > 0 &&
    customer.reminder_at &&
    new Date(customer.reminder_at) <= now
  ));
}

function reminderTemplate() {
  return state.settings?.reminder_message || DEFAULT_REMINDER_MESSAGE;
}

function reminderMessage(customer) {
  const store = state.settings?.store_name || "My Restaurant";
  return reminderTemplate()
    .replaceAll("{name}", customer.name || "Customer")
    .replaceAll("{amount}", rupee.format(customer.balance || 0))
    .replaceAll("{store}", store)
    .replaceAll("{date}", customer.reminder_at || "");
}

function cleanPhone(phone) {
  const digits = String(phone || "").replace(/\D/g, "");
  if (digits.length === 10) return `91${digits}`;
  return digits;
}

function renderNotificationBadge() {
  const badge = $("#notificationBadge");
  const count = dueCustomers().length;
  badge.textContent = count;
  badge.classList.toggle("hidden", count === 0);
}

function renderNotifications() {
  const rows = $("#notificationRows");
  if (!rows) return;
  const due = dueCustomers();
  rows.innerHTML = due.length ? due.map((customer) => `
    <article class="notification-row">
      <div>
        <strong>${escapeHtml(customer.name)}</strong>
        <small>${escapeHtml(customer.phone || "No phone saved")} - ${rupee.format(customer.balance || 0)}</small>
        <p>${escapeHtml(reminderMessage(customer))}</p>
      </div>
      <button type="button" data-send-reminder="${customer.id}">Send reminder</button>
    </article>
  `).join("") : `<div class="empty">No due udhari reminders right now.</div>`;
}

function addProductTo(items, productId) {
  const product = (state.products || []).find((p) => p.id === Number(productId));
  if (!product) return;
  const existing = items.find((i) => i.product_id === product.id);
  if (existing) existing.qty += 1;
  else items.push({ product_id: product.id, name: product.name, price: product.price, qty: 1 });
  render();
}

function renderBill(items, listSelector, totalSelector) {
  const list = $(listSelector);
  const amount = total(items);
  $(totalSelector).textContent = rupee.format(amount);
  if (totalSelector === "#calcTotal") {
    const bpt = $("#billPanelTotal");
    if (bpt) bpt.textContent = rupee.format(amount);
  }
  if (!items.length) {
    list.className = "bill-list empty";
    list.textContent = listSelector === "#tableBillItems" && !selectedTable ? "No table selected" : "No items yet";
    return;
  }
  list.className = "bill-list";
  list.innerHTML = items.map((item, index) => `
    <div class="line-item">
      <div><strong>${escapeHtml(item.name)}</strong><br><small>${rupee.format(item.price)} each</small></div>
      <div class="qty">
        <button type="button" data-qty="${index}" data-delta="-1">-</button>
        <strong>${item.qty}</strong>
        <button type="button" data-qty="${index}" data-delta="1">+</button>
      </div>
      <strong>${rupee.format(item.price * item.qty)}</strong>
    </div>
  `).join("");
}

function renderCustomers() {
  const customers = state.summary?.customers || [];
  $("#udhariTotal").textContent = rupee.format(state.summary?.udhari_total || 0);
  $("#customers").innerHTML = customers.length ? customers.map((customer) => `
    <article class="row">
      <div class="row-top">
        <div>
          <strong>${escapeHtml(customer.name)}</strong>
          ${customer.phone ? `<div class="subtle">${escapeHtml(customer.phone)}</div>` : ''}
        </div>
        <strong>${rupee.format(customer.balance || 0)}</strong>
      </div>
      <form class="pay-form" data-pay="${customer.id}">
        <input name="note" placeholder="Payment note" />
        <input name="amount" type="number" step="0.01" min="0" placeholder="Amount" required />
        <select name="payment_method">${(state.summary?.accounts || []).map(a => `<option value="${escapeAttr(a.name.toLowerCase())}">${escapeHtml(a.name)}</option>`).join("")}</select>
        <div style="display: flex; gap: 8px;">
          <button type="button" class="ghost" data-send-reminder="${customer.id}" style="flex: 1;" aria-label="Send WhatsApp Reminder">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="vertical-align: middle;">
              <path d="M22 2L11 13"></path>
              <path d="M22 2L15 22L11 13L2 9L22 2Z"></path>
            </svg>
          </button>
          <button type="submit" style="flex: 2;">Paid</button>
        </div>
      </form>
    </article>
  `).join("") : `<div class="empty">No udhari people yet.</div>`;
}

function renderStock() {
  $("#stockRows").innerHTML = (state.stock || []).length ? state.stock.map((item) => `
    <article class="row">
      <div class="row-top">
        <div>
          <strong>${escapeHtml(item.item_name)}</strong>
          <div class="subtle">${item.quantity} ${escapeHtml(item.unit || "")} ${item.supplier ? "from " + escapeHtml(item.supplier) : ""}</div>
        </div>
        <strong>${rupee.format(item.total_cost)}</strong>
      </div>
    </article>
  `).join("") : `<div class="empty">Stock purchases will appear here and reduce profit.</div>`;
}

function renderTables() {
  const floor = $("#floor");
  floor.classList.toggle("editing", editTablesMode);
  $("#tableEditor").classList.toggle("hidden", !editTablesMode);
  $("#doneTables").classList.toggle("hidden", !editTablesMode);
  $("#editTables").classList.toggle("hidden", editTablesMode);
  const products = state.products || [];
  floor.innerHTML = (state.tables || []).map((table) => {
    const items = tableBills[table.id] || [];
    const dots = items.slice(0, 5).map((item) => {
      const product = products.find((p) => p.id === item.product_id);
      const color = product?.color || '#176b87';
      return `<span class="table-dot" style="background:${escapeAttr(color)}" title="${escapeAttr(item.name)}">${item.qty}</span>`;
    }).join("");
    return `
      <button class="table-chip ${table.status === "busy" ? "busy" : ""} ${selectedTable === table.id ? "active" : ""}"
        data-table="${table.id}" style="left:${table.x}px; top:${table.y}px">
        <span><strong>${escapeHtml(table.label)}</strong>${table.seats} seats</span>
        ${dots ? `<div class="table-dots">${dots}</div>` : ''}
      </button>
    `;
  }).join("");
}

function renderTableBill() {
  const table = (state.tables || []).find((t) => t.id === selectedTable);
  $("#tableTitle").textContent = table ? `${table.label} Order` : "Select a table";
  const items = tableBills[selectedTable] || [];
  renderBill(items, "#tableBillItems", "#tableTotal");
  renderTableSwitcher();
  const editor = $("#tableEditor");
  if (table && editTablesMode && document.activeElement?.form !== editor) {
    editor.label.value = table.label;
    editor.seats.value = table.seats;
  }
}

function renderTableSwitcher() {
  const switcher = $("#tableSwitcher");
  if (!switcher) return;
  const busyTables = (state.tables || []).filter((t) => tableBills[t.id]?.length > 0);
  if (!busyTables.length) {
    switcher.innerHTML = '';
    switcher.classList.add('hidden');
    return;
  }
  switcher.classList.remove('hidden');
  switcher.innerHTML = busyTables.map((t) => `
    <button type="button" class="table-pill ${selectedTable === t.id ? 'active' : ''}" data-table="${t.id}">
      ${escapeHtml(t.label)}
    </button>
  `).join("");
}

function renderProfit() {
  const accounts = state.summary?.accounts || [];
  $("#accounts").innerHTML = accounts.map((account) => `
    <article class="account">
      <small>${escapeHtml(account.name)}</small>
      <strong>${rupee.format(account.current_amount || 0)}</strong>
    </article>
  `).join("");
  $("#transactions").innerHTML = (state.transactions || []).length ? state.transactions.map((tx) => `
    <article class="row">
      <div class="row-top">
        <div>
          <strong>${escapeHtml(tx.title)}</strong>
          <div class="subtle">${escapeHtml(tx.source)} - ${new Date(tx.created_at * 1000).toLocaleString()}</div>
        </div>
        <strong>${tx.kind === "income" ? "+" : "-"} ${rupee.format(tx.amount)}</strong>
      </div>
    </article>
  `).join("") : `<div class="empty">Paid sales, stock purchases, udhari payments, and manual entries will appear here.</div>`;
}

function renderFields() {
  $("#fieldRows").innerHTML = (state.custom_fields || []).map((field) => `
    <span class="field-pill">${escapeHtml(field.area)} - ${escapeHtml(field.name)} - ${escapeHtml(field.field_type)}</span>
  `).join("");
}

function renderExtraFields() {
  $$(".extra-fields").forEach((wrap) => {
    const area = wrap.dataset.area;
    wrap.innerHTML = fieldsFor(area).map((field) => {
      const type = field.field_type === "number" ? "number" : field.field_type === "date" ? "date" : "text";
      return `<input data-extra-area="${area}" name="${escapeAttr(field.name)}" type="${type}" placeholder="${escapeAttr(field.name)}" />`;
    }).join("");
  });
}

function renderColorChoices(selected) {
  $("#productColorChoices").innerHTML = COLORS.map((color) => `
    <button class="color-choice ${color === selected ? "selected" : ""}" type="button" data-color="${color}" style="background:${color}" aria-label="Use color ${color}"></button>
  `).join("");
}

function openModal(id) {
  $(id).showModal();
}

function closeModalInside(element) {
  element.closest("dialog")?.close();
}

function openProductModal(product = null) {
  const form = $("#productForm");
  form.reset();
  form.elements.namedItem("id").value = product?.id || "";
  form.elements.namedItem("name").value = product?.name || "";
  form.elements.namedItem("price").value = product?.price || "";
  form.elements.namedItem("color").value = product?.color || COLORS[0];
  $("#productModalTitle").textContent = product ? "Edit Button" : "Add Button";
  $("#cancelProductEdit").classList.toggle("hidden", !product);
  renderColorChoices(form.elements.namedItem("color").value);
  renderProductManager();
  openModal("#productModal");
}

function resetProductForm() {
  const form = $("#productForm");
  form.reset();
  form.elements.namedItem("id").value = "";
  form.elements.namedItem("color").value = COLORS[0];
  $("#productModalTitle").textContent = "Add Button";
  $("#cancelProductEdit").classList.add("hidden");
  renderColorChoices(COLORS[0]);
}

async function saveSale(items, form, source, tableId = null) {
  if (!items.length) {
    toast("Add at least one item first.");
    return;
  }
  const data = formData(form);
  if (data.payment_status === "udhari" && !data.customer_name.trim()) {
    toast("Customer name is required for udhari.");
    return;
  }
  if (data.payment_status === "udhari" && !data.reminder_at) {
    data.reminder_at = defaultReminderValue();
  }
  await api("/api/sales", {
    ...data,
    source,
    table_id: tableId,
    items,
    total: total(items),
    extra_data: collectExtra("sale", form),
  });
  items.splice(0, items.length);
  if (tableId) delete tableBills[tableId];
  form.reset();
  toast("Bill saved.");
}

function checkReminders() {
  const due = dueCustomers();
  if (!due.length) return;
  const message = `${due.length} udhari reminder${due.length > 1 ? "s" : ""} pending`;
  toast(message);
  if (state.settings?.notification_enabled === "true" && "Notification" in window && Notification.permission === "granted") {
    due.slice(0, 3).forEach((person) => new Notification("Udhari pending", { body: `${person.name}: ${rupee.format(person.balance)}` }));
  }
}

document.addEventListener("click", async (event) => {
  const tab = event.target.closest("[data-tab]");
  if (tab) {
    $$(".tabs button").forEach((btn) => btn.classList.toggle("active", btn === tab));
    $$(".tab-panel").forEach((panel) => panel.classList.toggle("active", panel.id === tab.dataset.tab));
    tab.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' });
  }

  if (event.target.closest(".close-modal")) {
    closeModalInside(event.target);
  }

  const editProduct = event.target.closest("[data-manage-edit]");
  if (editProduct) {
    const product = (state.products || []).find((p) => p.id === Number(editProduct.dataset.manageEdit));
    openProductModal(product);
    return;
  }

  const deleteProduct = event.target.closest("[data-manage-delete]");
  if (deleteProduct) {
    const product = (state.products || []).find((p) => p.id === Number(deleteProduct.dataset.manageDelete));
    if (!product || !confirm(`Delete ${product.name}?`)) return;
    await api("/api/products/delete", { id: product.id });
    resetProductForm();
    toast("Button deleted.");
    return;
  }

  const reminderBtn = event.target.closest("[data-send-reminder]");
  if (reminderBtn) {
    const customer = (state.summary?.customers || []).find((item) => item.id === Number(reminderBtn.dataset.sendReminder));
    if (!customer) return;
    const message = reminderMessage(customer);
    const phone = cleanPhone(customer.phone);
    if (phone) {
      window.open(`https://wa.me/${phone}?text=${encodeURIComponent(message)}`, "_blank");
    } else if (navigator.clipboard) {
      await navigator.clipboard.writeText(message);
      toast("No phone saved. Message copied.");
    } else {
      toast("No phone saved for this person.");
    }
    return;
  }

  const product = event.target.closest("[data-product]");
  if (product) {
    const onTables = product.closest("#tableProducts");
    if (onTables) {
      if (editTablesMode) return toast("Tap Done before taking table orders.");
      if (!selectedTable) return toast("Select a table first.");
      tableBills[selectedTable] ||= [];
      addProductTo(tableBills[selectedTable], product.dataset.product);
      const table = (state.tables || []).find((t) => t.id === selectedTable);
      if (table && table.status !== "busy") await api("/api/tables/move", { id: selectedTable, x: table.x, y: table.y, status: "busy" });
    } else {
      addProductTo(calcBill, product.dataset.product);
    }
  }

  const qty = event.target.closest("[data-qty]");
  if (qty) {
    const items = qty.closest("#tableBillItems") ? (tableBills[selectedTable] || []) : calcBill;
    const index = Number(qty.dataset.qty);
    items[index].qty += Number(qty.dataset.delta);
    if (items[index].qty <= 0) items.splice(index, 1);
    render();
  }

  const table = event.target.closest("[data-table]");
  if (table) {
    selectedTable = Number(table.dataset.table);
    render();
    if (!editTablesMode) {
      openModal("#tableMenuModal");
    }
  }
});

$("#productMenuBtn").addEventListener("click", () => openProductModal());
$("#openCustomerModal").addEventListener("click", () => {
  const form = $("#customerForm");
  if (!form.elements.namedItem("reminder_at").value) {
    form.elements.namedItem("reminder_at").value = defaultReminderValue();
  }
  openModal("#customerModal");
});
$("#openStockModal").addEventListener("click", () => openModal("#stockModal"));
$("#notificationBtn").addEventListener("click", () => {
  renderNotifications();
  openModal("#notificationModal");
});
$("#globalSettingsBtn").addEventListener("click", () => {
  const form = $("#settingsForm");
  form.elements.namedItem("store_name").value = state.settings?.store_name || "";
  form.elements.namedItem("notification_enabled").checked = state.settings?.notification_enabled === "true";
  form.elements.namedItem("reminder_message").value = reminderTemplate();
  openModal("#settingsModal");
});
$("#restoreMessageBtn").addEventListener("click", () => {
  $("#settingsForm").elements.namedItem("reminder_message").value = DEFAULT_REMINDER_MESSAGE;
  toast("Message restored to default.");
});

$("#productColorChoices").addEventListener("click", (event) => {
  const color = event.target.closest("[data-color]");
  if (!color) return;
  $("#productForm").elements.namedItem("color").value = color.dataset.color;
  renderColorChoices(color.dataset.color);
});

$("#productForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const data = formData(event.currentTarget);
  await api(data.id ? "/api/products/update" : "/api/products", data);
  resetProductForm();
  toast("Button saved.");
});

$("#cancelProductEdit").addEventListener("click", resetProductForm);

$("#checkoutForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  await saveSale(calcBill, event.currentTarget, "calculator");
});

$$(".clear-bill-btn").forEach((btn) => btn.addEventListener("click", () => {
  calcBill = [];
  render();
}));

$("#customerForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const data = formData(event.currentTarget);
  data.extra_data = collectExtra("customer", event.currentTarget);
  await api("/api/customers", data);
  closeModalInside(event.currentTarget);
  event.currentTarget.reset();
  toast("Person added.");
});

$("#customers").addEventListener("submit", async (event) => {
  const form = event.target.closest("[data-pay]");
  if (!form) return;
  event.preventDefault();
  await api("/api/udhari/payment", { ...formData(form), customer_id: form.dataset.pay });
  form.reset();
  toast("Udhari payment added.");
});

$("#stockForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const data = formData(event.currentTarget);
  data.extra_data = collectExtra("stock", event.currentTarget);
  await api("/api/stock", data);
  closeModalInside(event.currentTarget);
  event.currentTarget.reset();
  toast("Stock purchase saved.");
});

$("#editTables").addEventListener("click", () => {
  editTablesMode = true;
  if (!selectedTable && (state.tables || []).length) selectedTable = state.tables[0].id;
  render();
});

$("#doneTables").addEventListener("click", () => {
  editTablesMode = false;
  render();
});

$("#addTable").addEventListener("click", async () => {
  const count = (state.tables || []).length + 1;
  await api("/api/tables", { label: `T-${count}`, x: 40 + count * 18, y: 55 + count * 14, seats: 4 });
});

$("#tableEditor").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!selectedTable) return toast("Select or add a table first.");
  const table = (state.tables || []).find((t) => t.id === selectedTable);
  await api("/api/tables/update", { ...table, ...formData(event.currentTarget) });
  toast("Table updated.");
});

$("#tableCheckoutForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!selectedTable) return toast("Select a table first.");
  await saveSale(tableBills[selectedTable] || [], event.currentTarget, "table", selectedTable);
});

$("#accountForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  await api("/api/accounts", formData(event.currentTarget));
  event.currentTarget.reset();
});

$("#transactionForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const data = formData(event.currentTarget);
  data.extra_data = collectExtra("transaction", event.currentTarget);
  await api("/api/transactions", data);
  event.currentTarget.reset();
});

$("#fieldForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  await api("/api/custom-fields", formData(event.currentTarget));
  event.currentTarget.reset();
});

$("#settingsForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const data = formData(event.currentTarget);
  if (event.currentTarget.elements.namedItem("notification_enabled").checked && "Notification" in window) {
    await Notification.requestPermission();
  }
  await api("/api/settings", { key: "store_name", value: data.store_name });
  await api("/api/settings", { key: "notification_enabled", value: event.currentTarget.elements.namedItem("notification_enabled").checked ? "true" : "false" });
  await api("/api/settings", { key: "reminder_message", value: data.reminder_message || DEFAULT_REMINDER_MESSAGE });
  closeModalInside(event.currentTarget);
  toast("Settings saved.");
});

["#checkoutForm", "#tableCheckoutForm"].forEach((selector) => {
  const form = $(selector);
  form.elements.namedItem("payment_status").addEventListener("change", (event) => {
    const reminder = form.elements.namedItem("reminder_at");
    if (event.target.value === "udhari" && !reminder.value) {
      reminder.value = defaultReminderValue();
    }
  });
});



let headerFrame = null;
let lastTopbarHeight = 0;
let headerTransitioning = false;

function updateTopbarHeight() {
  const topbar = $("#topbar");
  const h = Math.ceil(topbar.getBoundingClientRect().height);
  if (h !== lastTopbarHeight) {
    lastTopbarHeight = h;
    document.documentElement.style.setProperty("--topbar-height", `${h}px`);
  }
}

function syncHeader() {
  const topbar = $("#topbar");
  const wasCompact = topbar.classList.contains("compact");
  if (window.scrollY > 20) {
    topbar.classList.add("compact");
  } else {
    topbar.classList.remove("compact");
  }
  const isCompact = topbar.classList.contains("compact");
  if (wasCompact !== isCompact) {
    headerTransitioning = true;
    trackTransition();
  }
  updateTopbarHeight();
}

/* Continuously track --topbar-height while the header transitions */
function trackTransition() {
  updateTopbarHeight();
  if (headerTransitioning) {
    requestAnimationFrame(trackTransition);
  }
}

const topbarEl = $("#topbar");
if (topbarEl) {
  topbarEl.addEventListener("transitionend", () => {
    headerTransitioning = false;
    updateTopbarHeight();
  });
}

function scheduleHeaderSync() {
  if (headerFrame) return;
  headerFrame = requestAnimationFrame(() => {
    headerFrame = null;
    syncHeader();
  });
}

window.addEventListener("scroll", scheduleHeaderSync, { passive: true });
window.addEventListener("resize", scheduleHeaderSync);
new ResizeObserver(scheduleHeaderSync).observe($("#topbar"));

let drag = null;
$("#floor").addEventListener("pointerdown", (event) => {
  const chip = event.target.closest("[data-table]");
  if (!chip || !editTablesMode) return;
  const table = (state.tables || []).find((t) => t.id === Number(chip.dataset.table));
  selectedTable = table.id;
  drag = { id: table.id, offsetX: event.offsetX, offsetY: event.offsetY };
  chip.setPointerCapture(event.pointerId);
  render();
});

$("#floor").addEventListener("pointermove", (event) => {
  if (!drag || !editTablesMode) return;
  const rect = $("#floor").getBoundingClientRect();
  const table = (state.tables || []).find((t) => t.id === drag.id);
  table.x = Math.max(0, Math.min(rect.width - 108, event.clientX - rect.left - drag.offsetX));
  table.y = Math.max(0, Math.min(rect.height - 78, event.clientY - rect.top - drag.offsetY));
  renderTables();
});

$("#floor").addEventListener("pointerup", async () => {
  if (!drag) return;
  const table = (state.tables || []).find((t) => t.id === drag.id);
  const payload = { id: table.id, x: table.x, y: table.y, status: table.status };
  drag = null;
  await api("/api/tables/move", payload);
});

let dragItem = null;
const pmList = $("#productManagerList");
if (pmList) {
  pmList.addEventListener("dragstart", (e) => {
    dragItem = e.target.closest(".manager-row");
    if (dragItem) e.dataTransfer.effectAllowed = "move";
  });
  pmList.addEventListener("dragover", (e) => {
    e.preventDefault();
    const target = e.target.closest(".manager-row");
    if (target && target !== dragItem) {
      const rect = target.getBoundingClientRect();
      const next = (e.clientY - rect.top) / (rect.bottom - rect.top) > 0.5;
      pmList.insertBefore(dragItem, next && target.nextSibling || target);
    }
  });
  pmList.addEventListener("drop", async (e) => {
    e.preventDefault();
    if (!dragItem) return;
    const ids = Array.from(pmList.querySelectorAll(".manager-row")).map(el => Number(el.dataset.productId));
    await api("/api/products/reorder", { ids });
    dragItem = null;
  });
}

loadState();
syncHeader();
setInterval(checkReminders, 60000);

async function logout() {
  await fetch("/api/auth/logout", { method: "POST" });
  window.location.href = "/login";
}
