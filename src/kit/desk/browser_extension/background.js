// Kit's Chrome extension: tells the Kit desk app on this PC which tabs are open
// and which one Dan is looking at. It talks only to 127.0.0.1 (the desk app),
// never to the internet, and never reads page contents. Incognito windows are
// skipped. The desk app strips query strings, blanks private sites, and passes
// the rest to Kit's brain along with the window list.

const PORT = 8765;
const DESK_APP = `http://127.0.0.1:${PORT}`;
let timer = null;

function browserName() {
  const brands = (navigator.userAgentData && navigator.userAgentData.brands) || [];
  if (brands.some(b => b.brand === "Microsoft Edge")) return "Edge";
  if (brands.some(b => b.brand === "Brave")) return "Brave";
  return "Chrome";
}

async function snapshot() {
  const windows = await chrome.windows.getAll({ populate: true, windowTypes: ["normal"] });
  const tabs = [];
  let focused = null;
  for (const w of windows) {
    if (w.incognito) continue;
    for (const t of w.tabs || []) {
      const tab = {
        title: t.title || "",
        url: t.url || t.pendingUrl || "",
        active: !!t.active,
        audible: !!t.audible,
      };
      tabs.push(tab);
      if (w.focused && t.active) focused = tab;
    }
  }
  return { browser: browserName(), tabs, focused };
}

async function report() {
  timer = null;
  let ok = false;
  try {
    const r = await fetch(`${DESK_APP}/tabs`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(await snapshot()),
    });
    ok = r.ok;
  } catch (e) {
    ok = false; // the desk app isn't running; try again on the next change or alarm
  }
  await chrome.storage.session.set({ connected: ok, at: Date.now() });
}

function soon() {
  // Tab events come in bursts (open, load, title); send once they settle.
  if (timer) clearTimeout(timer);
  timer = setTimeout(report, 400);
}

chrome.tabs.onActivated.addListener(soon);
chrome.tabs.onCreated.addListener(soon);
chrome.tabs.onRemoved.addListener(soon);
chrome.tabs.onUpdated.addListener((id, change) => {
  if (change.title || change.url || change.status === "complete" || "audible" in change) soon();
});
chrome.windows.onFocusChanged.addListener(soon);
chrome.runtime.onStartup.addListener(soon);
chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create("heartbeat", { periodInMinutes: 0.5 });
  soon();
});
chrome.alarms.onAlarm.addListener(soon);
