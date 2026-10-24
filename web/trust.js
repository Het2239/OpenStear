// Certificate setup page, served over plain HTTP on the LAN.
// If the phone already trusts the PC's certificate, go straight to the
// controller over HTTPS. Otherwise show install steps and keep checking.

(function () {
  const PROBE_MS = 2000;
  const $ = (id) => document.getElementById(id);

  const hash = new URLSearchParams(location.hash.slice(1));
  const token = hash.get("k");
  const port = hash.get("p");
  if (!token || !port) {
    $("checking").hidden = true;
    $("bad").hidden = false;
    return;
  }

  const base = `https://${location.hostname}:${port}`;
  const appUrl = `${base}/#k=${encodeURIComponent(token)}`;
  const ios = /iPhone|iPad|iPod/.test(navigator.userAgent) ||
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);

  // Resolves true if an HTTPS request succeeds, i.e. the certificate is trusted.
  function probe() {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 3000);
    return fetch(`${base}/health`, { mode: "no-cors", cache: "no-store", signal: ctrl.signal })
      .then(() => true, () => false)
      .finally(() => clearTimeout(timer));
  }

  async function check(manual) {
    if (await probe()) {
      location.replace(appUrl);
      return;
    }
    $("checking").hidden = true;
    $("steps").hidden = false;
    $(ios ? "ios" : "android").hidden = false;
    $("quick").hidden = ios;
    if (manual) $("still").hidden = false;
  }

  $("open-anyway").href = appUrl;
  $("continue").addEventListener("click", () => check(true));
  check(false);
  setInterval(() => { if (!document.hidden) check(false); }, PROBE_MS);
})();
