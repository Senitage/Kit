const status = document.getElementById("status");
// POST, because Chrome only sends the extension's Origin (which the desk app
// checks) on a POST from an extension page.
fetch("http://127.0.0.1:8765/ping", { method: "POST" })
  .then(r => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
  .then(info => {
    status.textContent = info.watching
      ? "Connected. Kit can see your tabs."
      : "Connected, but you've paused watching in Kit's tray menu.";
  })
  .catch(() => {
    status.textContent = "Kit's desk app isn't running on this PC.";
    status.className = "bad";
  });
