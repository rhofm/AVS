-- Atleet Volg Systeem - leerlijnen.db, basisschema (versie 1)
-- De leerlijnen en leerdoelen van de club, per onderdeel en leeftijdscategorie.
-- Bevat GEEN persoonsgegevens: dit is de 'catalogus'. Hoe ver een atleet is
-- met een leerdoel staat in leerdoelscores.db.
--
-- Bronnen:
--   'NA' = Leerlijn baanatletiek jeugd, Nijmegen Atletiek (2025) - leidend
--   'AU' = Atletiekunie, Leerlijnen binnen de atletiek (december 2013) - aanvulling
--          voor wat de NA-leerlijn niet dekt (U18/U20, en onderdelen zoals
--          estafette, (midden)lange afstand, hinkstap, polsstok, kogelslingeren)
--   'eigen' = later door de club toegevoegd
--
-- categorie = de categorie waarin een leerdoel voor het eerst aan bod komt. Een
-- leerdoel blijft daarna gelden (de leerlijnen zijn doorlopend): een U14-atleet
-- werkt ook aan de U10- en U12-doelen die hij nog niet beheerst.
--
-- AU-fasen (LTAD) -> categorie: fundament -> U10, leren trainen -> U12,
-- trainen voor omvang -> U14/U16, trainen op niveau -> U18/U20. Stabiele
-- elementen (de eindvorm van de techniek) staan bij U18, tenzij ze eerder vallen.
--
-- id = '<LEERLIJN>-<CATEGORIE>-<NR>', bijv. 'SPR-U10-01'. Een id wordt NOOIT
-- hergebruikt of hernummerd: leerdoelscores.db verwijst ernaar. Een leerdoel
-- schrappen = actief op 0 zetten.
--
-- Latere wijzigingen (nieuwe of aangepaste leerdoelen) NIET hier, maar in
-- migrations/leerlijnen/NNN_beschrijving.sql.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_version (
    versie       INTEGER NOT NULL,
    toegepast_op TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS categorie (
    code      TEXT PRIMARY KEY,                -- 'U10' ... 'U20'
    volgorde  INTEGER NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS leerlijn (
    code      TEXT PRIMARY KEY CHECK (length(code) = 3),   -- bijv. 'SPR'
    naam      TEXT NOT NULL UNIQUE,                        -- bijv. 'Sprint'
    volgorde  INTEGER NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS leerdoel (
    id                  TEXT PRIMARY KEY
                        CHECK (id GLOB '[A-Z][A-Z][A-Z]-U[0-9][0-9]-[0-9][0-9]'),
    leerlijn            TEXT    NOT NULL REFERENCES leerlijn(code),
    categorie           TEXT    NOT NULL REFERENCES categorie(code),
    volgorde            INTEGER NOT NULL,      -- binnen leerlijn + categorie
    omschrijving        TEXT    NOT NULL,      -- 'De atleet kan ...'
    bron                TEXT    NOT NULL CHECK (bron IN ('NA', 'AU', 'eigen')),
    fase                TEXT    CHECK (fase IN ('fundament', 'leren_trainen', 'trainen_omvang',
                                                'trainen_niveau', 'stabiel_element')),  -- alleen bij AU
    alleen_specialisten INTEGER NOT NULL DEFAULT 0 CHECK (alleen_specialisten IN (0, 1)),
    actief              INTEGER NOT NULL DEFAULT 1 CHECK (actief IN (0, 1)),
    UNIQUE (leerlijn, categorie, volgorde)
);
CREATE INDEX IF NOT EXISTS idx_leerdoel_categorie ON leerdoel(categorie, leerlijn);

-- Betekenis van de scores 1-5 in leerdoelscores.db.
CREATE TABLE IF NOT EXISTS scoreschaal (
    score         INTEGER PRIMARY KEY CHECK (score BETWEEN 1 AND 5),
    label         TEXT NOT NULL,
    omschrijving  TEXT NOT NULL
);

INSERT INTO categorie (code, volgorde) VALUES
('U10', 1),
('U12', 2),
('U14', 3),
('U16', 4),
('U18', 5),
('U20', 6);

INSERT INTO leerlijn (code, naam, volgorde) VALUES
('SPR', 'Sprint', 1),
('HOR', 'Hordelopen', 2),
('EST', 'Estafette', 3),
('MLA', 'Midden- en lange afstand', 4),
('VER', 'Verspringen', 5),
('HSS', 'Hinkstapspringen', 6),
('HOO', 'Hoogspringen', 7),
('POL', 'Polsstokspringen', 8),
('KOG', 'Medicinebal/kogelstoten', 9),
('DIS', 'Slingeren/discuswerpen', 10),
('SPE', 'Vortex-/speerwerpen', 11),
('SLI', 'Kogelslingeren', 12);

INSERT INTO scoreschaal (score, label, omschrijving) VALUES
(1, 'Nog niet',        'Laat het nog niet zien.'),
(2, 'Beginnend',       'Lukt af en toe, met veel hulp of een vereenvoudigde vorm.'),
(3, 'In ontwikkeling', 'Lukt regelmatig, met aanwijzingen van de trainer.'),
(4, 'Zelfstandig',     'Lukt meestal, zonder aanwijzingen.'),
(5, 'Beheerst',        'Lukt altijd, ook op snelheid en in de wedstrijd.');

-- 215 leerdoelen: U10 45, U12 49, U14 46, U16 30, U18 29, U20 16
INSERT INTO leerdoel (id, leerlijn, categorie, volgorde, omschrijving, bron, fase, alleen_specialisten) VALUES
('SPR-U10-01', 'SPR', 'U10', 1, 'De atleet weet waar de start is, en waar de finish is.', 'NA', NULL, 0),
('SPR-U10-02', 'SPR', 'U10', 2, 'De atleet weet wat de commando''s zijn bij het starten.', 'NA', NULL, 0),
('SPR-U10-03', 'SPR', 'U10', 3, 'De atleet kan vanuit een staande start wegsprinten.', 'NA', NULL, 0),
('SPR-U10-04', 'SPR', 'U10', 4, 'De atleet kijkt vooruit tijdens het lopen.', 'NA', NULL, 0),
('SPR-U10-05', 'SPR', 'U10', 5, 'De atleet kan de hele race binnen zijn baan blijven.', 'NA', NULL, 0),
('SPR-U10-06', 'SPR', 'U10', 6, 'De atleet kan snel reageren op verschillende signalen (tactiel, akoestisch, visueel).', 'AU', 'fundament', 0),
('SPR-U10-07', 'SPR', 'U10', 7, 'De atleet kan vanuit verschillende starthoudingen (zonder startblok) wegsprinten.', 'AU', 'fundament', 0),
('SPR-U10-08', 'SPR', 'U10', 8, 'De atleet kan op hoge frequentie bewegen in verschillende richtingen.', 'AU', 'fundament', 0),
('HOR-U10-01', 'HOR', 'U10', 1, 'De atleet kan zonder te stoppen over lage hordes heen.', 'NA', NULL, 0),
('HOR-U10-02', 'HOR', 'U10', 2, 'De atleet kan met behoud van ritme over verschillende soorten hindernissen en tussenafstanden lopen.', 'AU', 'fundament', 0),
('HOR-U10-03', 'HOR', 'U10', 3, 'De atleet kan met een 1-pas (ta-dam) op snelheid over lage hindernissen lopen.', 'AU', 'fundament', 0),
('HOR-U10-04', 'HOR', 'U10', 4, 'De atleet heeft een voorkeursbeen ontwikkeld (zelf gekozen in de bewegingssituatie).', 'AU', 'fundament', 0),
('EST-U10-01', 'EST', 'U10', 1, 'De atleet kan vanuit lage snelheid verschillend materiaal doorgeven (kring-, pendel- en omloopestafette).', 'AU', 'fundament', 0),
('MLA-U10-01', 'MLA', 'U10', 1, 'De atleet kan minimaal 4 minuten aaneengesloten lopen.', 'AU', 'fundament', 0),
('MLA-U10-02', 'MLA', 'U10', 2, 'De atleet kan langere tijd een gematigde, constante snelheid lopen (volhouden gaat voor de snelste zijn).', 'AU', 'fundament', 0),
('VER-U10-01', 'VER', 'U10', 1, 'De atleet weet waar hij moet afzetten voor een geldige sprong.', 'NA', NULL, 0),
('VER-U10-02', 'VER', 'U10', 2, 'De atleet kan met 1 been afzetten en met 2 benen landen.', 'NA', NULL, 0),
('VER-U10-03', 'VER', 'U10', 3, 'De atleet kent de regels omtrent het springen.', 'NA', NULL, 0),
('VER-U10-04', 'VER', 'U10', 4, 'De atleet kan veel verschillende ritmische sprongvormen (ta-dam) maken op, over en naar materialen.', 'AU', 'fundament', 0),
('HOO-U10-01', 'HOO', 'U10', 1, 'De atleet weet aan welke kant hij moet beginnen met de aanloop.', 'NA', NULL, 0),
('HOO-U10-02', 'HOO', 'U10', 2, 'De atleet kan met 1 been afzetten.', 'NA', NULL, 0),
('HOO-U10-03', 'HOO', 'U10', 3, 'De atleet kan op zijn voeten landen op de mat (schotse sprong is verplicht).', 'NA', NULL, 0),
('HOO-U10-04', 'HOO', 'U10', 4, 'De atleet kan in een rechte lijn aanlopen.', 'NA', NULL, 0),
('HOO-U10-05', 'HOO', 'U10', 5, 'De atleet kan zijn afzetvoet richting de mat laten wijzen.', 'NA', NULL, 0),
('HOO-U10-06', 'HOO', 'U10', 6, 'De atleet kent de regels omtrent het springen.', 'NA', NULL, 0),
('POL-U10-01', 'POL', 'U10', 1, 'De atleet springt met de ''stalen stoktechniek'' volgens de 3R-regel (rechterhand boven, rechterknie, rechts langs de stok, of alles links).', 'AU', 'fundament', 0),
('POL-U10-02', 'POL', 'U10', 2, 'De atleet kan actief hangen met lange armen (touw, ringen, rekstok).', 'AU', 'fundament', 0),
('POL-U10-03', 'POL', 'U10', 3, 'De atleet kan met de stok van hoog naar laag springen (polsstokverspringen).', 'AU', 'fundament', 0),
('POL-U10-04', 'POL', 'U10', 4, 'De atleet kan in drie à vier passen vloeiend insteken, met de bovenste arm gestrekt.', 'AU', 'fundament', 0),
('POL-U10-05', 'POL', 'U10', 5, 'De atleet kan een koprol achterover, een handstand en een borstwaartsom maken.', 'AU', 'fundament', 0),
('KOG-U10-01', 'KOG', 'U10', 1, 'De atleet weet hoe hij een medicinebal op correcte wijze moet vasthouden met twee handen.', 'NA', NULL, 0),
('KOG-U10-02', 'KOG', 'U10', 2, 'De atleet kent de basisregels omtrent het kogelstoten (incl. commando''s).', 'NA', NULL, 0),
('KOG-U10-03', 'KOG', 'U10', 3, 'De atleet kan globaal een standstoot uitvoeren (frontaal of kwartdraai).', 'NA', NULL, 0),
('KOG-U10-04', 'KOG', 'U10', 4, 'De atleet kan met een duwbeweging een medicinebal werpen.', 'NA', NULL, 0),
('KOG-U10-05', 'KOG', 'U10', 5, 'De atleet stoot (en werpt niet) met divers materiaal, van tweehandig naar eenhandig.', 'AU', 'fundament', 0),
('KOG-U10-06', 'KOG', 'U10', 6, 'De atleet kan over iets heen stoten, met een goede afstoothoek.', 'AU', 'fundament', 0),
('DIS-U10-01', 'DIS', 'U10', 1, 'De atleet weet hoe hij een fietsband op correcte wijze moet vasthouden.', 'NA', NULL, 0),
('DIS-U10-02', 'DIS', 'U10', 2, 'De atleet kent de basisregels omtrent het slingeren (incl. commando''s).', 'NA', NULL, 0),
('DIS-U10-03', 'DIS', 'U10', 3, 'De atleet kan globaal een slingerbeweging uitvoeren.', 'NA', NULL, 0),
('DIS-U10-04', 'DIS', 'U10', 4, 'De atleet slingert met een ''grote omweg'' en eindigt in een trotse eindhouding.', 'AU', 'fundament', 0),
('SPE-U10-01', 'SPE', 'U10', 1, 'De atleet weet hoe hij een vortex op correcte wijze moet vasthouden.', 'NA', NULL, 0),
('SPE-U10-02', 'SPE', 'U10', 2, 'De atleet kent de basisregels omtrent het werpen (incl. commando''s).', 'NA', NULL, 0),
('SPE-U10-03', 'SPE', 'U10', 3, 'De atleet kan globaal een bovenhandse strekworp uitvoeren uit stand (1-pas).', 'NA', NULL, 0),
('SPE-U10-04', 'SPE', 'U10', 4, 'De atleet kan met divers materiaal slagwerpen op hoogte (juiste afwerphoek).', 'AU', 'fundament', 0),
('SPE-U10-05', 'SPE', 'U10', 5, 'De atleet kan een uitstaptechniek uitvoeren: eerst uitstappen met het goede been voor, dan werpen.', 'AU', 'fundament', 0),
('SPR-U12-01', 'SPR', 'U12', 1, 'De atleet kan vanuit een startblok weg starten.', 'NA', NULL, 0),
('SPR-U12-02', 'SPR', 'U12', 2, 'De atleet weet hoe hij correct in driepuntstartblokken moet zitten.', 'NA', NULL, 0),
('SPR-U12-03', 'SPR', 'U12', 3, 'De atleet weet wat hij moet doen bij een valse start.', 'NA', NULL, 0),
('SPR-U12-04', 'SPR', 'U12', 4, 'De atleet weet wat zijn voorkeursbeen is.', 'NA', NULL, 0),
('SPR-U12-05', 'SPR', 'U12', 5, 'De atleet ondersteunt zijn loopbeweging met zijn armen.', 'NA', NULL, 0),
('SPR-U12-06', 'SPR', 'U12', 6, 'De atleet kan vanuit een vallende start of knielstart actief in de juiste richting strekken en van laag naar hoog weglopen.', 'AU', 'leren_trainen', 0),
('HOR-U12-01', 'HOR', 'U12', 1, 'De atleet kan zonder snelheid te minderen voor de horde, over de lage hordes heen.', 'NA', NULL, 0),
('HOR-U12-02', 'HOR', 'U12', 2, 'De atleet kan een vast ritme tussen twee hindernissen langere tijd aanhouden (3-, 4-, of 5-pas).', 'NA', NULL, 0),
('HOR-U12-03', 'HOR', 'U12', 3, 'De atleet heeft kennis gemaakt met hordes van 50 cm.', 'NA', NULL, 0),
('HOR-U12-04', 'HOR', 'U12', 4, 'De atleet zet ver voor de horde af en landt kort erachter.', 'AU', 'leren_trainen', 0),
('HOR-U12-05', 'HOR', 'U12', 5, 'De atleet valt de horde actief aan (''naar de horde toe'').', 'AU', 'leren_trainen', 0),
('HOR-U12-06', 'HOR', 'U12', 6, 'De atleet kan zowel met zijn voorkeurs- als met zijn niet-voorkeursbeen over de horde.', 'AU', 'leren_trainen', 0),
('EST-U12-01', 'EST', 'U12', 1, 'De atleet kan een estafettestok op snelheid doorgeven (keerpuntestafette).', 'AU', 'leren_trainen', 0),
('EST-U12-02', 'EST', 'U12', 2, 'De atleet kan wisselen binnen een aangegeven ruimte.', 'AU', 'leren_trainen', 0),
('MLA-U12-01', 'MLA', 'U12', 1, 'De atleet kan minimaal 6 minuten aaneengesloten lopen.', 'AU', 'leren_trainen', 0),
('MLA-U12-02', 'MLA', 'U12', 2, 'De atleet heeft tempogevoel: hij kan bewust verschillende loopsnelheden kiezen en volhouden.', 'AU', 'leren_trainen', 0),
('MLA-U12-03', 'MLA', 'U12', 3, 'De atleet kan zijn eigen mogelijkheden inschatten bij het verdelen van zijn krachten.', 'AU', 'leren_trainen', 0),
('VER-U12-01', 'VER', 'U12', 1, 'De atleet weet met welk been hij het best kan afzetten.', 'NA', NULL, 0),
('VER-U12-02', 'VER', 'U12', 2, 'De atleet kan aanlopen zonder snelheid te minderen voor de balk.', 'NA', NULL, 0),
('VER-U12-03', 'VER', 'U12', 3, 'De atleet loopt na de landing via de zijkant of achterkant uit de bak.', 'NA', NULL, 0),
('VER-U12-04', 'VER', 'U12', 4, 'De atleet kan zijn knie inzetten om meer uit de sprong te halen.', 'NA', NULL, 0),
('VER-U12-05', 'VER', 'U12', 5, 'De atleet kan afzetten binnen een klein afzetvlak, met zowel voorkeurs- als niet-voorkeursbeen.', 'AU', 'leren_trainen', 0),
('HSS-U12-01', 'HSS', 'U12', 1, 'De atleet kan ritmische meervoudige sprongen maken vanuit een lage aanloopsnelheid.', 'AU', 'leren_trainen', 0),
('HSS-U12-02', 'HSS', 'U12', 2, 'De atleet kan een stapstapsprong maken met een niet te grote eerste stap.', 'AU', 'leren_trainen', 0),
('HOO-U12-01', 'HOO', 'U12', 1, 'De atleet weet met welk been hij het best kan afzetten.', 'NA', NULL, 0),
('HOO-U12-02', 'HOO', 'U12', 2, 'De atleet kan aanlopen zonder snelheid te minderen voor de afzet.', 'NA', NULL, 0),
('HOO-U12-03', 'HOO', 'U12', 3, 'De atleet kan zijn knie inzetten om meer uit de sprong te halen.', 'NA', NULL, 0),
('HOO-U12-04', 'HOO', 'U12', 4, 'De atleet kan zijn arm inzetten om meer uit de sprong te halen (appel plukken i.p.v. naar de mat strekken).', 'NA', NULL, 0),
('HOO-U12-05', 'HOO', 'U12', 5, 'De atleet kan vanuit een schuinrechte aanloop een schaarsprong/schotse sprong maken met een verticale afzet.', 'AU', 'leren_trainen', 0),
('POL-U12-01', 'POL', 'U12', 1, 'De atleet kan met de stok van hoog naar hoog en van laag naar hoog springen.', 'AU', 'leren_trainen', 0),
('POL-U12-02', 'POL', 'U12', 2, 'De atleet zet actief af richting de stok, in plaats van in de stok te gaan hangen.', 'AU', 'leren_trainen', 0),
('POL-U12-03', 'POL', 'U12', 3, 'De atleet kiest een veilige greephoogte.', 'AU', 'leren_trainen', 0),
('POL-U12-04', 'POL', 'U12', 4, 'De atleet kan in de zandbak springen met een (beginnende) volledige stokpresentatie.', 'AU', 'leren_trainen', 0),
('KOG-U12-01', 'KOG', 'U12', 1, 'De atleet kan een (rubberen) kogel op correcte wijze vasthouden met één hand.', 'NA', NULL, 0),
('KOG-U12-02', 'KOG', 'U12', 2, 'De atleet kan met een duwbeweging een kogel stoten.', 'NA', NULL, 0),
('KOG-U12-03', 'KOG', 'U12', 3, 'De atleet kan bij de standworp zijn schouders een halve draai indraaien.', 'NA', NULL, 0),
('KOG-U12-04', 'KOG', 'U12', 4, 'De atleet kan met een aansluitpas snelheid opbouwen.', 'NA', NULL, 0),
('KOG-U12-05', 'KOG', 'U12', 5, 'De atleet maakt de draaistrekbeweging: eerst draaien, dan lang maken (lang naar achter kijken).', 'AU', 'leren_trainen', 0),
('DIS-U12-01', 'DIS', 'U12', 1, 'De atleet kan een AC-discus op correcte wijze vasthouden met één hand.', 'NA', NULL, 0),
('DIS-U12-02', 'DIS', 'U12', 2, 'De atleet kan een discus over zijn vingertoppen laten rollen (de correcte kant op).', 'NA', NULL, 0),
('DIS-U12-03', 'DIS', 'U12', 3, 'De atleet kan met een slingerbeweging een AC-discus werpen.', 'NA', NULL, 0),
('DIS-U12-04', 'DIS', 'U12', 4, 'De atleet kan bij de standworp zijn schouders een halve draai indraaien.', 'NA', NULL, 0),
('DIS-U12-05', 'DIS', 'U12', 5, 'De atleet kan met de standworp snelheid opbouwen.', 'NA', NULL, 0),
('DIS-U12-06', 'DIS', 'U12', 6, 'De atleet kan met divers materiaal om zijn lengteas draaien (oriëntatiegevoel).', 'AU', 'leren_trainen', 0),
('SPE-U12-01', 'SPE', 'U12', 1, 'De atleet kan een aansluitpas maken om snelheid op te bouwen (3-pas).', 'NA', NULL, 0),
('SPE-U12-02', 'SPE', 'U12', 2, 'De atleet kan tijdens de aansluitpas zijn werparm achter houden.', 'NA', NULL, 0),
('SPE-U12-03', 'SPE', 'U12', 3, 'De atleet kan met langer materiaal werpen in de richting van het voorwerp.', 'AU', 'leren_trainen', 0),
('SLI-U12-01', 'SLI', 'U12', 1, 'De atleet houdt het werpmateriaal met twee handen vast en start met de rug naar de werprichting.', 'AU', 'leren_trainen', 0),
('SLI-U12-02', 'SLI', 'U12', 2, 'De atleet kan tweehandig slingeren met een explosieve draaistrekbeweging vanuit stand.', 'AU', 'leren_trainen', 0),
('SPR-U14-01', 'SPR', 'U14', 1, 'De atleet weet hoe hij correct verstelbare startblokken moet klaarzetten.', 'NA', NULL, 0),
('SPR-U14-02', 'SPR', 'U14', 2, 'De atleet kan in het startblok een vallende houding aannemen.', 'NA', NULL, 0),
('SPR-U14-03', 'SPR', 'U14', 3, 'De atleet loopt recht op tijdens het maximaal sprinten.', 'NA', NULL, 0),
('SPR-U14-04', 'SPR', 'U14', 4, 'De atleet loopt reactief: voet in neutrale stand (''tenen op''), kort grondcontact.', 'AU', 'trainen_omvang', 0),
('HOR-U14-01', 'HOR', 'U14', 1, 'De atleet heeft kennis gemaakt met hordes van 76 cm.', 'NA', NULL, 0),
('HOR-U14-02', 'HOR', 'U14', 2, 'De atleet kent het verschil tussen aanvals- en bijtrekbeen.', 'NA', NULL, 0),
('HOR-U14-03', 'HOR', 'U14', 3, 'De atleet kan het aanvalsbeen (gebogen) recht vooruit over de horde bewegen.', 'NA', NULL, 0),
('HOR-U14-04', 'HOR', 'U14', 4, 'De atleet kan vanuit het startblok de eerste horde aanvallen.', 'AU', 'trainen_omvang', 0),
('EST-U14-01', 'EST', 'U14', 1, 'De atleet kent de regels van aanloopvak en wisselvak (wedstrijdreglement).', 'AU', 'trainen_omvang', 0),
('EST-U14-02', 'EST', 'U14', 2, 'De atleet vertrekt als ontvangende loper op het juiste moment.', 'AU', 'trainen_omvang', 0),
('EST-U14-03', 'EST', 'U14', 3, 'De atleet beheerst een wisseltechniek (onderhands of bovenhands).', 'AU', 'trainen_omvang', 0),
('EST-U14-04', 'EST', 'U14', 4, 'De atleet kan als ontvangende loper een specifieke starthouding aannemen.', 'AU', 'trainen_omvang', 0),
('MLA-U14-01', 'MLA', 'U14', 1, 'De atleet loopt met een efficiënte looptechniek (loopeconomie).', 'AU', 'trainen_omvang', 0),
('MLA-U14-02', 'MLA', 'U14', 2, 'De atleet kan extensieve intervaltrainingen en duurlopen op verschillende ondergronden volbrengen.', 'AU', 'trainen_omvang', 0),
('VER-U14-01', 'VER', 'U14', 1, 'De atleet kan aanlopen zonder naar de balk te kijken.', 'NA', NULL, 0),
('VER-U14-02', 'VER', 'U14', 2, 'De atleet heeft een persoonlijke aanloop (ong. 12-pas).', 'NA', NULL, 0),
('VER-U14-03', 'VER', 'U14', 3, 'De atleet beheerst de schredeverte techniek (tegengestelde knie-arm inzet).', 'NA', NULL, 0),
('VER-U14-04', 'VER', 'U14', 4, 'De atleet maakt zijn voorlaatste pas langer zodat zijn laatste pas kort en krachtig kan zijn (pam-padam).', 'NA', NULL, 0),
('VER-U14-05', 'VER', 'U14', 5, 'De atleet plaatst de laatste pas actief en strekt snel bij de afzet.', 'AU', 'trainen_omvang', 0),
('HSS-U14-01', 'HSS', 'U14', 1, 'De atleet kan een hinkstapsprong maken (van stapstap- naar hinkstapsprong).', 'AU', 'trainen_omvang', 0),
('HSS-U14-02', 'HSS', 'U14', 2, 'De atleet heeft de hink onder controle: een vlakke eerste zweeffase.', 'AU', 'trainen_omvang', 0),
('HOO-U14-01', 'HOO', 'U14', 1, 'De atleet kan aanlopen in een bocht.', 'NA', NULL, 0),
('HOO-U14-02', 'HOO', 'U14', 2, 'De atleet heeft een persoonlijke aanloop (ong. 6-, 7- of 8-pas).', 'NA', NULL, 0),
('HOO-U14-03', 'HOO', 'U14', 3, 'De atleet beheerst de Floptechniek (correcte toepassing hol-bol).', 'NA', NULL, 0),
('HOO-U14-04', 'HOO', 'U14', 4, 'De atleet maakt zijn voorlaatste pas langer zodat zijn laatste pas kort en krachtig kan zijn (pam-padam).', 'NA', NULL, 0),
('POL-U14-01', 'POL', 'U14', 1, 'De atleet maakt de overgang van de stalen naar de buigende stoktechniek.', 'AU', 'trainen_omvang', 0),
('POL-U14-02', 'POL', 'U14', 2, 'De atleet kan aanlopen met een stabiele stokhouding.', 'AU', 'trainen_omvang', 0),
('POL-U14-03', 'POL', 'U14', 3, 'De atleet springt in de insteekbak op het bed (in plaats van in de zandbak).', 'AU', 'trainen_omvang', 0),
('POL-U14-04', 'POL', 'U14', 4, 'De atleet zet naar voren gericht af met een gestrekte bovenarm en een snelle, gestrekte zwaaibeenactie.', 'AU', 'trainen_omvang', 0),
('KOG-U14-01', 'KOG', 'U14', 1, 'De atleet kan een blok zetten met zijn bovenlichaam tijdens de afstoot.', 'NA', NULL, 0),
('KOG-U14-02', 'KOG', 'U14', 2, 'De atleet kan een 2-pas inzetten.', 'NA', NULL, 0),
('KOG-U14-03', 'KOG', 'U14', 3, 'De atleet kan een aanglij inzetten.', 'NA', NULL, 0),
('DIS-U14-01', 'DIS', 'U14', 1, 'De atleet kan een echte discus op correcte wijze vasthouden.', 'NA', NULL, 0),
('DIS-U14-02', 'DIS', 'U14', 2, 'De atleet kan een blok zetten met zijn bovenlichaam tijdens de afworp.', 'NA', NULL, 0),
('DIS-U14-03', 'DIS', 'U14', 3, 'De atleet kan een halve draai inzetten.', 'NA', NULL, 0),
('DIS-U14-04', 'DIS', 'U14', 4, 'De atleet kan zijn arm achter houden tijdens de draai.', 'NA', NULL, 0),
('DIS-U14-05', 'DIS', 'U14', 5, 'De atleet kan een discus vlak werpen.', 'NA', NULL, 0),
('DIS-U14-06', 'DIS', 'U14', 6, 'De atleet komt bij de draai uit in een open voetenstand.', 'AU', 'trainen_omvang', 0),
('SPE-U14-01', 'SPE', 'U14', 1, 'De atleet kan een speer op correcte wijze vasthouden.', 'NA', NULL, 0),
('SPE-U14-02', 'SPE', 'U14', 2, 'De atleet kan een blok zetten met zijn onderlichaam tijdens de afworp.', 'NA', NULL, 0),
('SPE-U14-03', 'SPE', 'U14', 3, 'De atleet kent de gevaren en regels van het sporten met een speer.', 'NA', NULL, 0),
('SPE-U14-04', 'SPE', 'U14', 4, 'De atleet kan een 3-pas inzetten om snelheid op te bouwen, waarbij hij voorlangs kruist met zijn benen.', 'NA', NULL, 0),
('SPE-U14-05', 'SPE', 'U14', 5, 'De atleet kan een 5-pas inzetten om snelheid op te bouwen, waarbij hij voorlangs kruist met zijn benen.', 'NA', NULL, 0),
('SPE-U14-06', 'SPE', 'U14', 6, 'De atleet start de aanloop met de speer al achter en houdt de arm ontspannen, ver en hoog achter.', 'AU', 'trainen_omvang', 0),
('SLI-U14-01', 'SLI', 'U14', 1, 'De atleet kan met divers materiaal om zijn lengteas draaien terwijl het materiaal om hem heen draait.', 'AU', 'trainen_omvang', 0),
('SLI-U14-02', 'SLI', 'U14', 2, 'De atleet kent de veiligheidsafspraken bij kogelslingeren (twee handen vast, starten met de rug naar de werprichting).', 'AU', 'trainen_omvang', 0),
('SPR-U16-01', 'SPR', 'U16', 1, 'De atleet kan een actieve voetplaatsing toepassen.', 'NA', NULL, 0),
('SPR-U16-02', 'SPR', 'U16', 2, 'De atleet is in staat om 3 fases te onderscheiden: startfase, acceleratiefase en maximale snelheid.', 'NA', NULL, 0),
('HOR-U16-01', 'HOR', 'U16', 1, 'De atleet kan het bijtrekbeen langs zich halen in plaats van onder zich door.', 'NA', NULL, 0),
('HOR-U16-02', 'HOR', 'U16', 2, 'De atleet is in staat om een 3-pas tussen de horden te lopen.', 'NA', NULL, 1),
('HOR-U16-03', 'HOR', 'U16', 3, 'De atleet zet 2/3 van zijn totale hordepassage voor de horde af, en landt 1/3 na de horde.', 'NA', NULL, 1),
('HOR-U16-04', 'HOR', 'U16', 4, 'De atleet weet tijdens zijn vluchtfase zijn lichaamszwaartepunt zo min mogelijk te laten stijgen.', 'NA', NULL, 1),
('HOR-U16-05', 'HOR', 'U16', 5, 'De atleet heeft kennis gemaakt met 300/400 m horden.', 'AU', 'trainen_omvang', 0),
('HOR-U16-06', 'HOR', 'U16', 6, 'De atleet loopt op (of richting) wedstrijdhoogte en -afstanden.', 'AU', 'trainen_omvang', 0),
('EST-U16-01', 'EST', 'U16', 1, 'De atleet kan de Frankfurter wissel (binnen-buitenwissel) toepassen bij de 4x100 m.', 'AU', 'trainen_omvang', 0),
('EST-U16-02', 'EST', 'U16', 2, 'De atleet kent de tactische keuzes: wisselmethode, volgorde van lopers en plaats in het aanloopvak.', 'AU', 'trainen_omvang', 0),
('MLA-U16-01', 'MLA', 'U16', 1, 'De atleet kan een wedstrijd van meer dan 400 m in een constant tempo lopen.', 'AU', 'trainen_omvang', 0),
('VER-U16-01', 'VER', 'U16', 1, 'De atleet neemt zijn armen op correcte wijze mee in de sprong (voor- én achterlangs inzetten).', 'NA', NULL, 0),
('VER-U16-02', 'VER', 'U16', 2, 'De atleet stelt zijn landing uit door zijn voeten zo lang mogelijk hoog te houden.', 'NA', NULL, 0),
('VER-U16-03', 'VER', 'U16', 3, 'De atleet kan de drie fasen van de aanloop apart laten zien (snelheid opbouwen-controleren-naar de afzet).', 'NA', NULL, 0),
('VER-U16-04', 'VER', 'U16', 4, 'De atleet kan de drie fasen van de vlucht correct laten zien (afzet/stijgen-zweven-landing/dalen).', 'NA', NULL, 0),
('HSS-U16-01', 'HSS', 'U16', 1, 'De atleet kan zijn aanloopsnelheid vergroten met behoud van een vlakke hink.', 'AU', 'trainen_omvang', 0),
('HOO-U16-01', 'HOO', 'U16', 1, 'De atleet kan afzetten door een blok in te zetten met het afzetbeen.', 'NA', NULL, 0),
('HOO-U16-02', 'HOO', 'U16', 2, 'De atleet kan de drie fasen van de aanloop apart laten zien (snelheid opbouwen-frequentie in de bocht-naar de afzet).', 'NA', NULL, 0),
('HOO-U16-03', 'HOO', 'U16', 3, 'De atleet kan de drie fasen van de vlucht correct laten zien (afzet/stijgen-hol-bol).', 'NA', NULL, 0),
('POL-U16-01', 'POL', 'U16', 1, 'De atleet brengt zijn lichaam na de afzet in de C-positie.', 'AU', 'trainen_omvang', 0),
('POL-U16-02', 'POL', 'U16', 2, 'De atleet kan inrollen.', 'AU', 'trainen_omvang', 0),
('KOG-U16-01', 'KOG', 'U16', 1, 'De atleet weet welke manier van snelheid opbouwen het best bij hem past (stand/2-stap/aanglij).', 'NA', NULL, 0),
('KOG-U16-02', 'KOG', 'U16', 2, 'De atleet heeft kennis gemaakt met een complexere techniek, zoals de O''Brien- of rotatietechniek.', 'AU', 'trainen_omvang', 0),
('DIS-U16-01', 'DIS', 'U16', 1, 'De atleet kan een South African (SA) draai inzetten.', 'NA', NULL, 0),
('DIS-U16-02', 'DIS', 'U16', 2, 'De atleet kan een achterwaartse draai inzetten (hele draai).', 'NA', NULL, 0),
('DIS-U16-03', 'DIS', 'U16', 3, 'De atleet weet welke manier van snelheid opbouwen het best bij hem past (stand/SA/hele draai).', 'NA', NULL, 0),
('SPE-U16-01', 'SPE', 'U16', 1, 'De atleet kan een 7-pas inzetten om snelheid op te bouwen, waarbij hij voorlangs kruist met zijn benen.', 'NA', NULL, 0),
('SPE-U16-02', 'SPE', 'U16', 2, 'De atleet weet welke manier van snelheid opbouwen het best bij hem past (stand/3-pas/5-pas/7-pas).', 'NA', NULL, 0),
('SLI-U16-01', 'SLI', 'U16', 1, 'De atleet kan de versnellingsbaan verlengen met draaibewegingen (bijv. instaptechniek, halve draai).', 'AU', 'trainen_omvang', 0),
('SLI-U16-02', 'SLI', 'U16', 2, 'De atleet versnelt de slingerkogel met enkele voorzwaaien, met lange en ontspannen armen.', 'AU', 'stabiel_element', 0),
('SPR-U18-01', 'SPR', 'U18', 1, 'In de klaar-houding heeft de atleet druk op de startblokken, schouders boven of iets voor de handen, heupen boven de schouders en kijkt hij naar de startlijn.', 'AU', 'stabiel_element', 0),
('SPR-U18-02', 'SPR', 'U18', 2, 'De atleet strekt zich explosief na het startsignaal en kijkt schuin naar voren bij het verlaten van het startblok.', 'AU', 'stabiel_element', 0),
('SPR-U18-03', 'SPR', 'U18', 3, 'De atleet maakt snelle, maar ruime, naar voren gerichte eerste passen.', 'AU', 'stabiel_element', 0),
('SPR-U18-04', 'SPR', 'U18', 4, 'De atleet laat bij maximale snelheid de stabiele elementen van het lopen zien: rechtop, ''tenen op'' en een snelle schaarbeweging.', 'AU', 'stabiel_element', 0),
('HOR-U18-01', 'HOR', 'U18', 1, 'De atleet maakt van de landing een actieve fase: het begin van de sprint naar de volgende horde.', 'AU', 'stabiel_element', 0),
('HOR-U18-02', 'HOR', 'U18', 2, 'De atleet loopt met hetzelfde ritme over de volledige wedstrijdafstand op wedstrijdhoogte.', 'AU', 'stabiel_element', 0),
('EST-U18-01', 'EST', 'U18', 1, 'De atleet wisselt op hoge snelheid met zoveel mogelijk ruimtewinst (dynamisch principe).', 'AU', 'stabiel_element', 0),
('MLA-U18-01', 'MLA', 'U18', 1, 'De atleet kan tactiek toepassen in een race, bijvoorbeeld tempowisselingen.', 'AU', 'trainen_niveau', 0),
('VER-U18-01', 'VER', 'U18', 1, 'De atleet is bij de afzet (nagenoeg) rechtop en maakt zich lang.', 'AU', 'stabiel_element', 0),
('VER-U18-02', 'VER', 'U18', 2, 'De atleet maakt bij de afzet een snelle zwaaibeenactie en een harde voetplaatsing.', 'AU', 'stabiel_element', 0),
('HSS-U18-01', 'HSS', 'U18', 1, 'De atleet blijft in alle zweeffasen groot en rechtop en zet afzet/landing zo laat mogelijk in.', 'AU', 'stabiel_element', 0),
('HSS-U18-02', 'HSS', 'U18', 2, 'De atleet behoudt zijn aanloopsnelheid door de verticale verplaatsing te beperken (vlakke sprongen).', 'AU', 'stabiel_element', 0),
('HOO-U18-01', 'HOO', 'U18', 1, 'De atleet is rechtop bij en na de afzet en zwaait het zwaaibeen snel, van de mat af.', 'AU', 'stabiel_element', 0),
('HOO-U18-02', 'HOO', 'U18', 2, 'De atleet heeft een passieve zweeffase tot de heup voorbij de lat is en brengt dan de knieën naar de borst.', 'AU', 'stabiel_element', 0),
('HOO-U18-03', 'HOO', 'U18', 3, 'De atleet kan vanuit een ruimere curve met een hogere aanloopsnelheid springen.', 'AU', 'trainen_niveau', 0),
('POL-U18-01', 'POL', 'U18', 1, 'De atleet presenteert de stok in de laatste drie à vier passen en steekt hoog voor zich in.', 'AU', 'stabiel_element', 0),
('POL-U18-02', 'POL', 'U18', 2, 'De atleet kan zijn aanloopsnelheid verhogen met behoud van stokhouding en afzet.', 'AU', 'trainen_niveau', 0),
('KOG-U18-01', 'KOG', 'U18', 1, 'De atleet klemt de kogel in de hals (''als een vioolspeler'') en houdt de elleboog hoog, achter de kogel.', 'AU', 'stabiel_element', 0),
('KOG-U18-02', 'KOG', 'U18', 2, 'De atleet stoot de kogel van laag achter naar hoog met een snelle draaistrekbeweging, van onder naar boven ingezet.', 'AU', 'stabiel_element', 0),
('KOG-U18-03', 'KOG', 'U18', 3, 'De atleet plaatst de laatste voet snel (ta-dam), zet pas dan de draaistrekbeweging in en draait op de bal van de voet.', 'AU', 'stabiel_element', 0),
('KOG-U18-04', 'KOG', 'U18', 4, 'De atleet maakt zich lang bij de uitstoot (trotse, rechte eindhouding).', 'AU', 'stabiel_element', 0),
('DIS-U18-01', 'DIS', 'U18', 1, 'De atleet maakt een ruime zwaai (discus ver van het lichaam, lange arm in het verlengde van de schouder) en houdt de discus lang achter.', 'AU', 'stabiel_element', 0),
('DIS-U18-02', 'DIS', 'U18', 2, 'De atleet slingert de discus van ver achter naar zij-voor met een snelle draaistrekbeweging, van onder naar boven ingezet.', 'AU', 'stabiel_element', 0),
('DIS-U18-03', 'DIS', 'U18', 3, 'De atleet plaatst de laatste voet snel (ta-dam) en draait op de bal van de voet.', 'AU', 'stabiel_element', 0),
('SPE-U18-01', 'SPE', 'U18', 1, 'De atleet werpt de speer van ver hoog achter naar ver hoog voor, hoger dan zijn hoofd.', 'AU', 'stabiel_element', 0),
('SPE-U18-02', 'SPE', 'U18', 2, 'De atleet maakt een actieve kruispas (voorlangs) en plaatst de laatste voet snel, nagenoeg gelijk met de voorlaatste.', 'AU', 'stabiel_element', 0),
('SPE-U18-03', 'SPE', 'U18', 3, 'De atleet kan op hogere snelheid aanlopen en brengt de speer tijdens de aanloop naar achter.', 'AU', 'trainen_niveau', 0),
('SLI-U18-01', 'SLI', 'U18', 1, 'De atleet vormt na de voorzwaai met gestrekte armen een gelijkbenige driehoek met de schouderas.', 'AU', 'stabiel_element', 0),
('SLI-U18-02', 'SLI', 'U18', 2, 'De atleet versnelt de kogel vanuit de benen in één tot vijf draaien, met het laagste punt tegengesteld aan en het hoogste punt in de werprichting.', 'AU', 'stabiel_element', 0),
('SPR-U20-01', 'SPR', 'U20', 1, 'De atleet kan zijn snelheid vasthouden over de wedstrijdafstand (sprintuithoudingsvermogen).', 'AU', 'trainen_niveau', 0),
('HOR-U20-01', 'HOR', 'U20', 1, 'De atleet verfijnt zijn hordetechniek op basis van zijn individuele mogelijkheden.', 'AU', 'trainen_niveau', 0),
('EST-U20-01', 'EST', 'U20', 1, 'De atleet verfijnt zijn wisseltechniek op basis van zijn individuele mogelijkheden.', 'AU', 'trainen_niveau', 0),
('MLA-U20-01', 'MLA', 'U20', 1, 'De atleet traint met een individueel, specifiek programma op vermogen én capaciteit, gestuurd met tests.', 'AU', 'trainen_niveau', 0),
('VER-U20-01', 'VER', 'U20', 1, 'De atleet zet bewegingen vroegtijdig in door voor- en vormspanning, voor een maximale afzetimpuls.', 'AU', 'trainen_niveau', 0),
('HSS-U20-01', 'HSS', 'U20', 1, 'De atleet zet bewegingen vroegtijdig in door voor- en vormspanning, voor een maximale afzetimpuls.', 'AU', 'trainen_niveau', 0),
('HOO-U20-01', 'HOO', 'U20', 1, 'De atleet zet bewegingen vroegtijdig in door voor- en vormspanning, voor een maximale afzetimpuls.', 'AU', 'trainen_niveau', 0),
('POL-U20-01', 'POL', 'U20', 1, 'De atleet werkt toe naar complexere technieken, met effectiever gebruik van (schijn)rotaties.', 'AU', 'trainen_niveau', 0),
('KOG-U20-01', 'KOG', 'U20', 1, 'De atleet verfijnt een complexere techniek, waarbij de afstootsnelheid van de kogel maximaal is.', 'AU', 'trainen_niveau', 0),
('KOG-U20-02', 'KOG', 'U20', 2, 'De atleet zet bewegingen vroegtijdig in door voor- en vormspanning, voor een maximale werpimpuls.', 'AU', 'trainen_niveau', 0),
('DIS-U20-01', 'DIS', 'U20', 1, 'De atleet verlengt de versnellingsbaan verder en verfijnt zijn techniek, waarbij de afwerpsnelheid maximaal is.', 'AU', 'trainen_niveau', 0),
('DIS-U20-02', 'DIS', 'U20', 2, 'De atleet zet bewegingen vroegtijdig in door voor- en vormspanning, voor een maximale werpimpuls.', 'AU', 'trainen_niveau', 0),
('SPE-U20-01', 'SPE', 'U20', 1, 'De atleet verfijnt een complexere techniek, waarbij de afwerpsnelheid van de speer maximaal is.', 'AU', 'trainen_niveau', 0),
('SPE-U20-02', 'SPE', 'U20', 2, 'De atleet zet bewegingen vroegtijdig in door voor- en vormspanning, voor een maximale werpimpuls.', 'AU', 'trainen_niveau', 0),
('SLI-U20-01', 'SLI', 'U20', 1, 'De atleet verlengt de versnellingsbaan en verfijnt zijn techniek, waarbij de afwerpsnelheid van de kogel maximaal is.', 'AU', 'trainen_niveau', 0),
('SLI-U20-02', 'SLI', 'U20', 2, 'De atleet zet bewegingen vroegtijdig in door voor- en vormspanning, voor een maximale werpimpuls.', 'AU', 'trainen_niveau', 0);

INSERT INTO schema_version (versie) VALUES (1);
