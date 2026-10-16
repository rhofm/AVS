/* AVS – tabellen sorteren door op een kolomkop te klikken.
   Gebruik: <table class="sorteerbaar">, in elke kolomkop een <button class="sorteer">.
   Kolomkop: data-soort="getal" of "tekst"; data-eerst="af" = eerste klik hoog naar laag
   (standaard laag naar hoog); aria-sort op de kop waar de tabel al op staat.
   Cellen: data-sort met de waarde; zonder (of leeg) = gaat altijd onderaan.
   Alleen <tbody> wordt gesorteerd; een <tfoot> (bijv. gemiddelden) blijft staan.
   Zonder JavaScript blijft de tabel in de volgorde van de server. */
(function () {
  document.querySelectorAll("table.sorteerbaar").forEach(function (tabel) {
    var koppen = Array.prototype.slice.call(tabel.tHead.rows[0].cells);
    var body = tabel.tBodies[0];
    var oorspronkelijk = Array.prototype.slice.call(body.rows);
    koppen.forEach(function (kop, k) {
      var knop = kop.querySelector("button.sorteer");
      if (!knop) return;
      knop.addEventListener("click", function () {
        var huidig = kop.getAttribute("aria-sort");
        var eerst = kop.dataset.eerst === "af" ? "descending" : "ascending";
        var richting = !huidig || huidig === "none" ? eerst : (huidig === "ascending" ? "descending" : "ascending");
        koppen.forEach(function (x) { x.removeAttribute("aria-sort"); });
        kop.setAttribute("aria-sort", richting);
        var getal = kop.dataset.soort === "getal", teken = richting === "ascending" ? 1 : -1;
        var rijen = oorspronkelijk.slice();       /* stabiel: gelijke waarden houden de oorspronkelijke volgorde */
        rijen.sort(function (a, b) {
          var x = a.cells[k].dataset.sort, y = b.cells[k].dataset.sort;
          var xl = x === undefined || x === "", yl = y === undefined || y === "";
          if (xl || yl) return xl === yl ? 0 : (xl ? 1 : -1);
          if (getal) return teken * (parseFloat(x) - parseFloat(y));
          return teken * x.localeCompare(y, "nl");
        });
        rijen.forEach(function (r) { body.appendChild(r); });
      });
    });
  });
})();
