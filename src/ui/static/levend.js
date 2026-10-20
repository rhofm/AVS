/* Levensduur van AVS (zie src/ui/levensduur.py).
   Deze pagina laat weten dat ze open is (/levend, bij het laden en daarna elke paar seconden)
   en dat ze verlaten wordt (/weg). Is er geen AVS-pagina meer open, dan stopt AVS vanzelf. */
(function () {
  var script = document.currentScript;
  var hartslag = parseInt((script && script.dataset.hartslag) || "15000", 10);
  var id = (window.crypto && crypto.randomUUID) ? crypto.randomUUID()
         : String(Date.now()) + String(Math.random()).slice(2);

  function levend() {
    try {
      fetch("/levend", { method: "POST", body: id, keepalive: true,
                         headers: { "Content-Type": "text/plain" } }).catch(function () {});
    } catch (e) { /* AVS is al gestopt: niets aan te doen */ }
  }

  levend();
  setInterval(levend, hartslag);
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible") levend();       // terug naar dit tabblad
  });
  window.addEventListener("pageshow", function (e) {
    if (e.persisted) levend();                                   // terug via de knop 'Vorige'
  });
  window.addEventListener("pagehide", function () {
    if (navigator.sendBeacon) navigator.sendBeacon("/weg", id);  // tabblad dicht of andere pagina
  });
})();
