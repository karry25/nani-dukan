"use strict";
const $app = document.getElementById("app");
let CSRF = "", ME = null, PAGE = "sleep";
const rs = n => "Rs " + Number(n).toLocaleString("en-IN");
function h(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "on") for (const [ev, fn] of Object.entries(v)) e.addEventListener(ev, fn);
    else if (k === "class") e.className = v; else e.setAttribute(k, v);
  }
  for (const c of kids.flat()) if (c != null && c !== false) e.append(c.nodeType ? c : document.createTextNode(String(c)));
  return e;
}
async function api(method, path, body) {
  const r = await fetch("/api/" + path, {method, headers: {"Content-Type": "application/json", "X-CSRF": CSRF}, body: body ? JSON.stringify(body) : undefined});
  const j = await r.json().catch(() => ({}));
  if (r.status === 401 && path !== "login") { ME = null; return login(); }
  if (!r.ok) throw new Error(j.error || "Error");
  return j;
}
function mount(el, ...kids) { el.replaceChildren(...kids.flat(Infinity).filter(c => c != null && c !== false).map(c => c.nodeType ? c : document.createTextNode(String(c)))); }
const guard = (el, fn) => async (...a) => { try { await fn(...a); } catch (e) { alert(e.message); } };

function login(msg) {
  const u = h("input", {placeholder: "username", autocomplete: "username"}), p = h("input", {type: "password", placeholder: "password (8+ characters)"}), s = h("input", {placeholder: "shop name (new accounts)"});
  const err = h("div", {class: "err"}, msg || "");
  const go = path => async () => { try { const j = await api("POST", path, {username: u.value, password: p.value, shop_name: s.value}); CSRF = j.csrf; boot(); } catch (e) { err.textContent = e.message; } };
  mount($app, h("div", {class: "auth"}, h("h1", {}, "Nani Dukan"), h("div", {class: "sub"}, "Your shop's helper. It drafts, you decide. It never sends anything."), u, p, s, err,
    h("div", {class: "row"}, h("button", {class: "pri", on: {click: go("login")}}, "Sign in"), h("button", {on: {click: go("register")}}, "Create account"), h("button", {on: {click: go("demo")}}, "Try demo"))));
}

const PAGES = [["sleep", "While you sleep"], ["sale", "Quick bill"], ["stock", "Stock check"], ["today", "Tonight's check-in"], ["chats", "Customer chats"], ["udhaar", "Udhaar"], ["bills", "Bills inbox"], ["month", "Month-end"], ["rules", "Rulebook"], ["shop", "Shop & prices"], ["activity", "Activity"]];
async function boot() {
  try { ME = await api("GET", "me"); CSRF = ME.csrf; } catch { return login(); }
  render();
}
async function render() {
  const nav = h("div", {class: "side"}, h("h3", {}, ME.shop.name), h("div", {class: "sec"}, "Pages"),
    PAGES.map(([k, t]) => h("div", {class: "nav" + (k === PAGE ? " on" : ""), on: {click: () => { PAGE = k; render(); }}}, t, k === "today" && !ME.checkin.done ? h("span", {class: "badge"}, "due") : null)),
    h("div", {style: "flex:1"}), h("div", {class: "sec"}, "AI use today"), h("div", {class: "sub", style: "margin:0 8px"}, ME.usage.used + " of " + ME.usage.cap),
    h("div", {class: "nav", on: {click: guard(null, async () => { await api("POST", "logout", {}); login(); })}}, "Sign out"));
  const main = h("div", {class: "main"});
  mount($app, nav, main, chatPanel());
  try { await VIEWS[PAGE](main); } catch (e) { main.append(h("div", {class: "callout bad"}, e.message)); }
}
const title = (m, t, s) => m.append(h("h1", {}, t), h("div", {class: "sub"}, s));
const refreshMe = async () => { ME = await api("GET", "me"); };

const VIEWS = {
  async sleep(m) {
    title(m, "While you sleep", "The helper checks your books and stock and shows only what needs you.");
    const d = await api("GET", "digest");
    m.append(d.all_clear ? h("div", {class: "callout ok"}, "All clear. Nothing needs you. Good night!") :
      h("div", {class: "card"}, h("b", {}, d.needs_you.length + " things need you"), d.needs_you.map(x => h("div", {class: "callout"}, x))));
  },
  async sale(m) {
    title(m, "Quick bill", "Type or dictate one line. Example: Ramesh ko 10 SIM, 5 recharge card, paid 300. Prices come from your list.");
    const t = h("textarea", {placeholder: "Ramesh ko 10 SIM, 5 recharge card, paid 300"}), out = h("div", {});
    m.append(t, h("div", {class: "row"}, h("button", {class: "pri", on: {click: guard(null, async () => {
      const d = await api("POST", "sale/parse", {text: t.value});
      const cust = h("input", {placeholder: "customer (needed if unpaid)", value: d.customer || ""}), paid = h("input", {type: "number", value: d.paid ?? d.total});
      mount(out, d.unknown.length ? h("div", {class: "callout bad"}, "Not in your price list: " + d.unknown.join(", ") + ". Add them in Shop & prices.") : null,
        h("table", {}, h("tr", {}, ["Item", "Qty", "Price", "Amount"].map(x => h("th", {}, x))), d.lines.map(l => h("tr", {}, h("td", {}, l.name), h("td", {}, l.qty), h("td", {}, rs(l.price)), h("td", {}, rs(l.amount))))),
        h("div", {}, h("b", {}, "Total " + rs(d.total))), h("div", {class: "row"}, "Customer ", cust, " Paid now ", paid),
        d.lines.length ? h("button", {class: "pri", on: {click: guard(null, async () => {
          const r = await api("POST", "sale/confirm", {customer: cust.value, lines: d.lines, paid: paid.value});
          mount(out, h("div", {class: "callout ok"}, "Bill saved. Total " + rs(r.total) + (r.due ? ", " + rs(r.due) + " added to udhaar." : ".")));
        })}}, "Confirm bill") : null);
    })}}, "Make the bill")), out);
  },
  async stock(m) {
    title(m, "Stock check", "Send a photo of a shelf (or type counts). The helper counts, then your ledger is compared. You decide what to fix.");
    const items = (await api("GET", "stock")).items, out = h("div", {});
    const file = h("input", {type: "file", accept: "image/*", capture: "environment"}), note = h("input", {placeholder: "or type: SIM 48, recharge card 20"});
    const send = guard(null, async () => {
      let data = null;
      if (file.files[0]) data = await new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(r.result.split(",")[1]); r.onerror = rej; r.readAsDataURL(file.files[0]); });
      const d = await api("POST", "stock/count", {data, text: note.value});
      const boxes = {};
      mount(out, !d.readable ? h("div", {class: "callout bad"}, "I could not read the photo. Try a closer, brighter one.") : h("div", {class: "callout"}, "These counts are AI counts. Please confirm before fixing."),
        h("table", {}, h("tr", {}, ["Item", "Ledger", "Counted", "Result", "Fix ledger"].map(x => h("th", {}, x))), d.rows.map(r => {
          if (r.counted != null) boxes[r.item_id] = h("input", {type: "checkbox"});
          return h("tr", {}, h("td", {}, r.name), h("td", {}, r.expected), h("td", {}, r.counted ?? "-"),
            h("td", {}, r.status === "match" ? "Match" : r.status === "short" ? "Short by " + -r.diff : r.status === "extra" ? "Extra " + r.diff : "Not seen"), h("td", {}, boxes[r.item_id] || ""));
        })), d.unknown.length ? h("div", {class: "sub"}, "Counted but not in your list: " + d.unknown.map(u => u.name + " " + u.qty).join(", ")) : null,
        h("button", {class: "pri", on: {click: guard(null, async () => {
          const fixes = d.rows.filter(r => boxes[r.item_id] && boxes[r.item_id].checked).map(r => ({item_id: r.item_id, counted: r.counted}));
          const r = await api("POST", "stock/count/confirm", {fixes}); mount(out, h("div", {class: "callout ok"}, r.adjusted + " items updated in the ledger.")); render();
        })}}, "Update ticked items"));
    });
    m.append(h("div", {class: "row"}, file, note, h("button", {class: "pri", on: {click: send}}, "Check stock")), out);
    const pf = h("input", {type: "file", accept: "image/*", capture: "environment"}), pn = h("input", {placeholder: "or paste: SIM 100, Recharge card 50"}), pout = h("div", {});
    m.append(h("h2", {}, "Stock came in? Send the supplier bill"), h("div", {class: "sub"}, "Photo or text. You tick what is right, then it is added to stock."), h("div", {class: "row"}, pf, pn, h("button", {class: "pri", on: {click: guard(null, async () => {
      let data = null;
      if (pf.files[0]) data = await new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(r.result.split(",")[1]); r.onerror = rej; r.readAsDataURL(pf.files[0]); });
      const d = await api("POST", "purchase/parse", {data, text: pn.value});
      const qs = d.lines.map(l => h("input", {type: "number", value: l.qty}));
      mount(pout, !d.readable ? h("div", {class: "callout bad"}, "I could not read the bill. Try a closer photo.") : null,
        h("table", {}, h("tr", {}, ["Item", "Qty to add"].map(x => h("th", {}, x))), d.lines.map((l, i) => h("tr", {}, h("td", {}, l.name), h("td", {}, qs[i])))),
        d.unknown.length ? h("div", {class: "sub"}, "Not in your price list (add them first): " + d.unknown.map(u => u.name + " " + u.qty).join(", ")) : null,
        d.lines.length ? h("button", {class: "pri", on: {click: guard(null, async () => {
          const r = await api("POST", "purchase/confirm", {lines: d.lines.map((l, i) => ({item_id: l.item_id, qty: Number(qs[i].value)}))});
          mount(pout, h("div", {class: "callout ok"}, r.added + " items added to stock.")); render();
        })}}, "Add to stock") : null);
    })}}, "Read bill")), pout);
    const q = h("input", {type: "number", placeholder: "qty"}), sel = h("select", {}, items.map(i => h("option", {value: i.id}, i.name))), kind = h("select", {}, h("option", {value: "opening"}, "opening stock"), h("option", {value: "purchase"}, "bought stock"));
    m.append(h("h2", {}, "Ledger stock"), h("table", {}, h("tr", {}, ["Item", "In ledger"].map(x => h("th", {}, x))), items.map(i => h("tr", {}, h("td", {}, i.name), h("td", {}, i.expected)))),
      items.length ? h("div", {class: "row"}, sel, kind, q, h("button", {on: {click: guard(null, async () => { await api("POST", "stock/move", {item_id: Number(sel.value), qty: Number(q.value), kind: kind.value}); render(); })}}, "Add")) : h("div", {class: "sub"}, "Add items in Shop & prices first."));
  },
  async today(m) {
    title(m, "Tonight's check-in", "Type your night note the way you would tell Nani. Nothing is saved until you confirm.");
    const t = h("textarea", {placeholder: "aaj sale 5200, kharcha 800, cash 6100, thread khatam, Anjali ne 300 diye, Pooja ko 450 udhaar"});
    const out = h("div", {});
    const doParse = guard(null, async () => {
      const d = await api("POST", "checkin/parse", {text: t.value});
      const f = {};
      const num = k => { f[k] = h("input", {type: "number", value: d[k] ?? "", placeholder: "needed"}); return h("td", {}, f[k]); };
      const miss = ["cash", "sales", "expenses"].filter(k => d[k] == null);
      mount(out, 
        miss.length ? h("div", {class: "callout"}, "I could not find: " + miss.join(", ") + ". Please fill it in. I do not guess numbers.") : null,
        h("table", {}, h("tr", {}, h("th", {}, "Cash in hand"), h("th", {}, "Sales"), h("th", {}, "Expenses")), h("tr", {}, num("cash"), num("sales"), num("expenses"))),
        h("div", {class: "row"}, "Gave on udhaar: ", d.udhaar_given.map(e => h("span", {class: "tag"}, e.name + " " + rs(e.amount))), d.udhaar_given.length ? "" : "none"),
        h("div", {class: "row"}, "Got back: ", d.udhaar_received.map(e => h("span", {class: "tag"}, e.name + " " + rs(e.amount))), d.udhaar_received.length ? "" : "none"),
        h("div", {class: "row"}, "Running low: ", d.low_stock.map(e => h("span", {class: "tag"}, e)), d.low_stock.length ? "" : "nothing"),
        h("button", {class: "pri", on: {click: guard(null, async () => {
          for (const k of ["cash", "sales", "expenses"]) d[k] = f[k].value === "" ? null : Number(f[k].value);
          await api("POST", "checkin/save", {data: d, raw: t.value}); await refreshMe(); mount(out, h("div", {class: "callout ok"}, "Saved. Good night!")); render();
        })}}, "Confirm and save"));
    });
    m.append(t, h("div", {class: "row"}, h("button", {class: "pri", on: {click: doParse}}, "Read my note")), out);
    const days = (await api("GET", "checkins")).days;
    m.append(h("h2", {}, "Recent nights"), h("table", {}, h("tr", {}, ["Day", "Cash", "Sales", "Expenses", "Low stock"].map(x => h("th", {}, x))),
      days.slice(0, 10).map(d => h("tr", {}, h("td", {}, d.day), h("td", {}, rs(d.cash)), h("td", {}, rs(d.sales)), h("td", {}, rs(d.expenses)), h("td", {}, d.low_stock.join(", "))))));
  },
  async chats(m) {
    title(m, "Customer chats", "Paste what a customer wrote. You get a draft. Copy it and send it yourself.");
    const t = h("textarea", {placeholder: "Paste a customer message"});
    m.append(t, h("div", {class: "row"}, h("button", {class: "pri", on: {click: guard(null, async () => { await api("POST", "chats", {text: t.value}); render(); })}}, "Draft a reply")));
    for (const c of (await api("GET", "chats")).chats) {
      const ed = h("textarea", {}); ed.value = c.final || c.draft || "";
      m.append(h("div", {class: "card"}, h("span", {class: "tag"}, c.category), h("span", {class: "tag"}, "urgency " + c.urgency), h("div", {class: "sub"}, c.text),
        c.flags.map(f => h("div", {class: "callout bad"}, f)),
        c.draft ? [h("div", {class: "sub"}, "Draft (edit it to what you really send):"), ed,
          h("div", {class: "row"}, h("button", {on: {click: guard(null, async () => { await navigator.clipboard.writeText(ed.value); })}}, "Copy"),
            h("button", {on: {click: guard(null, async () => { await api("POST", `chats/${c.id}/edit`, {final: ed.value}); render(); })}}, "I sent this"))] : h("div", {class: "sub"}, "Marked as spam. No reply drafted."),
        c.pending_rule ? h("div", {class: "callout"}, "Noticed from your edit: ", h("b", {}, c.pending_rule), h("div", {class: "row"},
          h("button", {class: "pri", on: {click: guard(null, async () => { await api("POST", `chats/${c.id}/rule`, {keep: true}); render(); })}}, "Keep this rule"),
          h("button", {on: {click: guard(null, async () => { await api("POST", `chats/${c.id}/rule`, {keep: false}); render(); })}}, "No"))) : null));
    }
  },
  async udhaar(m) {
    title(m, "Udhaar", "Who owes you. Reminders are drafts for you to send.");
    const n = h("input", {placeholder: "customer"}), a = h("input", {type: "number", placeholder: "amount"}), k = h("select", {}, h("option", {value: "credit"}, "took on udhaar"), h("option", {value: "payment"}, "paid back"));
    m.append(h("div", {class: "row"}, n, a, k, h("button", {class: "pri", on: {click: guard(null, async () => { await api("POST", "ledger", {name: n.value, amount: Number(a.value), kind: k.value}); render(); })}}, "Add")));
    const cs = (await api("GET", "udhaar")).customers, box = h("div", {});
    m.append(h("table", {}, h("tr", {}, ["Customer", "Owes", "Last entry", ""].map(x => h("th", {}, x))), cs.map(c => h("tr", {}, h("td", {}, c.name), h("td", {}, rs(c.owed)), h("td", {}, c.last_day || ""),
      h("td", {}, c.owed > 0 ? h("button", {on: {click: guard(null, async () => { const r = await api("POST", `udhaar/${c.id}/nudge`, {}); mount(box, h("div", {class: "card"}, h("b", {}, "Draft for " + r.customer), h("div", {class: "draft"}, r.draft))); })}}, "Draft reminder") : "")))), box);
  },
  async bills(m) {
    title(m, "Bills inbox", "Drop many bill photos. They get read, sorted and totalled. Anything unclear waits for you.");
    const f = h("input", {type: "file", accept: "image/png,image/jpeg,image/webp", multiple: "multiple"}), t = h("textarea", {placeholder: "or paste bill text"});
    const rd = file => new Promise(r => { const x = new FileReader(); x.onload = () => r(x.result.split(",")[1]); x.readAsDataURL(file); });
    m.append(f, t, h("div", {class: "row"}, h("button", {class: "pri", on: {click: guard(null, async () => {
      for (const file of f.files) await api("POST", "bills", {filename: file.name, data: await rd(file)});
      if (t.value.trim()) await api("POST", "bills", {text: t.value}); render(); })}}, "Sort these")));
    const bl = (await api("GET", "bills")).bills, total = bl.filter(b => ["sorted", "confirmed"].includes(b.status)).reduce((s, b) => s + (b.amount || 0), 0);
    m.append(h("div", {class: "callout ok"}, "Total of sorted bills: " + rs(total)),
      h("table", {}, h("tr", {}, ["Vendor", "Date", "Amount", "Type", "Status", ""].map(x => h("th", {}, x))), bl.map(b => {
        const v = h("input", {value: b.vendor || "", size: 8}), d = h("input", {value: b.bill_date || "", size: 8, placeholder: "YYYY-MM-DD"}), a = h("input", {type: "number", value: b.amount ?? "", style: "width:80px"});
        const c = h("select", {}, ["stock_purchase", "electricity", "rent", "transport", "salary", "packaging", "other"].map(x => h("option", {value: x, selected: x === b.category ? "selected" : null}, x)));
        const review = b.status === "needs_review" || b.status === "duplicate";
        return h("tr", {}, review ? [h("td", {}, v), h("td", {}, d), h("td", {}, a), h("td", {}, c)] : [h("td", {}, b.vendor || ""), h("td", {}, b.bill_date || ""), h("td", {}, b.amount == null ? "" : rs(b.amount)), h("td", {}, b.category)],
          h("td", {}, h("span", {class: "tag"}, b.status.replace("_", " "))),
          h("td", {}, review ? h("button", {on: {click: guard(null, async () => { await api("POST", `bills/${b.id}/confirm`, {vendor: v.value, bill_date: d.value, amount: a.value, category: c.value}); render(); })}}, "Confirm") : ""));
      })));
  },
  async month(m) {
    const mon = new Date().toISOString().slice(0, 7), inp = h("input", {value: mon, size: 8}), out = h("div", {});
    title(m, "Month-end", "Numbers are added up by the app, never guessed. The checklist is what is left to do.");
    const go = guard(null, async () => {
      const r = await api("GET", "month/" + inp.value), t = r.totals;
      mount(out, h("div", {class: "tot"}, [["Sales", rs(t.sales)], ["Expenses (night notes)", rs(t.expenses)], ["Bills sorted", rs(t.bills_total)], ["Udhaar pending", rs(t.udhaar_outstanding)], ["Check-ins", t.checkin_days + "/" + t.days_in_month]].map(([a, b]) => h("div", {}, a, h("b", {}, b)))),
        h("h2", {}, "Summary"), h("div", {class: "draft"}, r.summary), h("h2", {}, "Closing checklist"),
        r.checklist.length ? r.checklist.map(c => h("div", {class: "callout"}, c)) : h("div", {class: "callout ok"}, "Nothing pending. Ready to close."),
        h("h2", {}, "Bills by type"), h("table", {}, Object.entries(r.bills_by_category).map(([k, v]) => h("tr", {}, h("td", {}, k), h("td", {}, rs(v))))));
    });
    m.append(h("div", {class: "row"}, inp, h("button", {class: "pri", on: {click: go}}, "Prepare")), out); go();
  },
  async rules(m) {
    title(m, "Rulebook", "Habits the helper learned from your edits. Only rules you kept are here. Delete any time.");
    const rl = (await api("GET", "rules")).rules;
    m.append(rl.length ? h("table", {}, h("tr", {}, ["Rule", "Learned from", "Used", ""].map(x => h("th", {}, x))), rl.map(r => h("tr", {}, h("td", {}, r.text), h("td", {}, r.source), h("td", {}, r.uses),
      h("td", {}, h("button", {on: {click: guard(null, async () => { await api("DELETE", "rules/" + r.id); render(); })}}, "Delete"))))) : h("div", {class: "callout"}, "No rules yet. Edit a draft and you will be asked."));
  },
  async shop(m) {
    title(m, "Shop & prices", "The helper only quotes prices from this list.");
    const n = h("input", {placeholder: "item"}), p = h("input", {type: "number", placeholder: "price"}), pol = h("textarea", {placeholder: "Shop policy, e.g. no returns on earrings. Delivery 40 Rs."}); pol.value = ME.shop.policy || "";
    const items = (await api("GET", "catalog")).items;
    m.append(h("div", {class: "row"}, n, p, h("button", {class: "pri", on: {click: guard(null, async () => { await api("POST", "catalog", {name: n.value, price: Number(p.value)}); render(); })}}, "Add")),
      h("table", {}, items.map(i => h("tr", {}, h("td", {}, i.name), h("td", {}, rs(i.price)), h("td", {}, h("button", {on: {click: guard(null, async () => { await api("DELETE", "catalog/" + i.id); render(); })}}, "Remove"))))),
      h("h2", {}, "Policy"), pol, h("div", {class: "row"}, h("button", {on: {click: guard(null, async () => { await api("POST", "shop", {name: ME.shop.name, language: ME.shop.language, policy: pol.value}); await refreshMe(); alert("Saved"); })}}, "Save policy"),
        h("button", {on: {click: guard(null, async () => { if (confirm("Delete your account and all data?")) { await api("DELETE", "account"); login(); } })}}, "Delete my account")));
  },
  async activity(m) {
    title(m, "Activity", "Everything the helper did, and everything you did.");
    m.append(h("table", {}, (await api("GET", "activity")).activity.map(a => h("tr", {}, h("td", {}, a.ts.replace("T", " ")), h("td", {}, h("span", {class: "tag"}, a.actor)), h("td", {}, a.action), h("td", {}, a.detail)))));
  }
};
function chatPanel() {
  const box = h("div", {class: "msgs"}, h("div", {class: "m"}, "Namaste. Paste a customer message and I will draft a reply. I never send anything."));
  const i = h("input", {placeholder: "Paste customer message", style: "flex:1"});
  const f = h("form", {on: {submit: async ev => { ev.preventDefault(); const t = i.value; if (!t) return; i.value = ""; box.append(h("div", {class: "m me"}, t));
    try { const c = await api("POST", "chats", {text: t}); box.append(h("div", {class: "m"}, c.draft || "Looks like spam. No reply."), ...c.flags.map(x => h("div", {class: "callout bad"}, x))); } catch (e) { box.append(h("div", {class: "m"}, e.message)); } box.scrollTop = 1e9; }}}, i, h("button", {class: "pri"}, "Go"));
  return h("div", {class: "chat"}, box, f);
}
boot();
