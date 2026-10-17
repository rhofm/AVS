/* AVS – een tabel direct filteren terwijl je typt of kiest.
   Gebruik: <form data-filter="id-van-tabel"> met daarin
     <input data-filter-zoek>                      vrij zoeken: elk woord moet voorkomen in data-zoek van de rij
     <select data-filter-veld="categorie">         rij moet data-categorie="<waarde>" hebben (leeg = alles)
     <select data-filter-lijst="groepen">          data-groepen van de rij is een lijst met spaties: " 3 7 "
   en optioneel <span data-filter-teller> voor "n atleten", of <span data-filter-teller="groep groepen">
   voor andere woorden (enkelvoud en meervoud).
   De server filtert dezelfde velden bij het versturen, dus zonder JavaScript werkt alles ook. */
(function () {
  function plat(t) {
    return (t || "").normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/\s+/g, " ").trim();
  }
  document.querySelectorAll("form[data-filter]").forEach(function (form) {
    var tabel = document.getElementById(form.dataset.filter);
    if (!tabel) return;
    var rijen = Array.prototype.slice.call(tabel.tBodies[0].rows);
    var zoek = form.querySelector("[data-filter-zoek]");
    var velden = form.querySelectorAll("[data-filter-veld]");
    var lijsten = form.querySelectorAll("[data-filter-lijst]");
    var teller = document.querySelector("[data-filter-teller]");
    var leeg = document.querySelector("[data-filter-leeg]");
    var telwoorden = ((teller && teller.dataset.filterTeller) || "atleet atleten").split(" ");

    function toepassen() {
      var woorden = plat(zoek ? zoek.value : "").split(" ").filter(Boolean);
      var zichtbaar = 0;
      rijen.forEach(function (r) {
        var ok = woorden.every(function (w) { return (r.dataset.zoek || "").indexOf(w) !== -1; });
        velden.forEach(function (v) { if (ok && v.value && r.dataset[v.dataset.filterVeld] !== v.value) ok = false; });
        lijsten.forEach(function (v) {
          if (ok && v.value && (" " + (r.dataset[v.dataset.filterLijst] || "") + " ").indexOf(" " + v.value + " ") === -1) ok = false;
        });
        r.hidden = !ok;
        if (ok) zichtbaar++;
      });
      if (teller) teller.textContent = zichtbaar + " " + (zichtbaar === 1 ? telwoorden[0] : telwoorden[1]);
      if (leeg) leeg.hidden = zichtbaar !== 0;
    }
    if (zoek) zoek.addEventListener("input", toepassen);
    velden.forEach(function (v) { v.addEventListener("change", toepassen); });
    lijsten.forEach(function (v) { v.addEventListener("change", toepassen); });
  });
})();
