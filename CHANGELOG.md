# Versiegeschiedenis — Insigne Systeem

Alle noemenswaardige wijzigingen per release, in omgekeerde chronologische volgorde.

PR's voegen hun wijzigingen toe onder `## [Unreleased]`. Bij een release wordt
deze sectie geconsolideerd in een nieuwe `## [vX.Y.Z]` sectie en `[Unreleased]`
weer leeg gemaakt.

---

## [Unreleased]

### Nieuw

- **Jaarinsigne-ondersteuning** (sluit #73) — algemeen mechanisme voor jaarinsignes (één badge met aparte eisen per speltak), inclusief twee concrete jaarinsignes:
  - **Jaarinsigne 2025 — Wijs met drinkwater**: standaardflow per eis, gebruikt het bestaande step-card-pad.
  - **Jaarinsigne 2026 — Nieuwe Insignes**: meta-insigne waarbij voortgang wordt afgeleid van afgetekende eisen van *gewone* en *buitengewone* insignes. Scouts selecteren in een tweekoloms-editor welke eisen meetellen; het systeem berekent de eis-statussen tegen de drempels (`punten`, `groen`, `niveau2`, `niveau3`, `insignes`, `leiding_bepaald`) en zet ze programmatisch.
- **Speltak-type op `Speltak`** — speltakken kunnen nu getagd worden als `bevers` / `welpen` / `scouts` / `explorers` / `roverscouts` / `plusscouts`. JSON-API: veld in `SpeltakResponse`, valideert op `422`. HTML: dropdown in de speltak-edit-form; `peer_signoff` schakelt automatisch om voor roverscouts/plusscouts. Tonen in groep- en speltak-detailpagina's.
- **`POST /api/badges/{slug}/set-level`** en **`POST /api/scouts/{id}/badges/{slug}/set-level`** — scout zet eigen jaarinsigne-speltak; leider kan voor een scout overschrijven. HTML- en JSON-varianten beide.
- **Include / exclude editor** op `/badges/jaarinsigne_2026` — twee kolommen ("Meegeteld" + "Beschikbaar") met cards getiteld `{Insigne} — Niveau N — Eis M`, een puntenbadge, inline Font Awesome blad-icoon voor groene eisen, en statistieken (punten / groen / insignes / per-niveau-pillen) per kolom. Toggle-knoppen verplaatsen kaarten via HTMX zonder paginaherlaad.
- **Batch-aftekenen voor jaarinsigne 2026** — één **Aftekenen…**-knop verplaatst alle eisen tegelijk naar `pending_signoff`. De knop is uitgeschakeld tot alle eisen `work_done` zijn; eenmaal actief opent dezelfde mentor-keuze (speltakleiders / peer-leden / direct e-mail) als de bestaande step-card flow. De scout kan het verzoek intrekken; tijdens "pending" is de editor vergrendeld.
- **Gegroepeerde mentor-inbox** — `/signoff-requests` toont alle jaarinsigne-2026-aanvragen van één scout als één kaart. Mentor ziet de geselecteerde insigne-eisen ("Behaalde eisen"), de drempel-eisen met scoreregels (`10 punten behaald (minimaal 8)`, `2 "groene" eisen behaald (minimaal 1)`, …) en één paar Aftekenen / Afwijzen-knoppen dat alle eisen in één transactie afhandelt.
- **JSON-API voor jaarinsigne 2026** (10 endpoints) — afspiegeling van de HTML-flow zodat externe consumenten (mobiele apps, scripts) hetzelfde kunnen. Inclusies (`GET/POST /api/users/me/jaarinsigne_2026/inclusions{,/available,/toggle}`), score (`GET /score`), batch-aftekenen (`POST /signoff{,-speltak,-members}`, `DELETE /signoff`), en mentor-acties (`POST /api/scouts/{id}/jaarinsigne_2026/{confirm,reject}-signoff`).
- **Dedicated jaarinsigne e-mail templates** — verzoek / uitnodiging / afgetekend / afgewezen met correcte labels (Insigne / Speltak / Eis(en) met de echte eisnummer + titel). Eisteksten worden nu door de markdown-renderer gehaald: `**vet**`, lijsten en `==groen==` accenten komen door, ruwe markdown-tekens niet meer.

### Verbeteringen

- **`render_eis` gedeeld** — markdown-naar-inline-HTML-routine verplaatst naar `lib/insigne/eis_render.py` met een `render_eis_email` variant die `==…==` als inline groen rendert (mailclients negeren `<style>`-blokken). Reguliere insigne-e-mails pikken dezelfde fix op.
- **Step-check tickboxes** in de jaarinsigne-2026-editor synchroniseren live mee met de inclusies via een HTMX-bodyswap.
- **Compacte eis-rendering** in de editor cards — markdown wordt gestript behalve `==…==` groene accenten; te lange teksten krijgen een "Toon volledige eis"-toggle die de volledige markdown laat zien.
- **Sortering** in beide editorkolommen volgt `badges.yml`-volgorde → niveau → eisnummer.

### Opgelost

- **Self in autocomplete** — `list_previous_mentors` filtert defensief de scout zelf weg, zodat een per ongeluk ontstane "self-signoff"-rij niet meer in de mentor-suggesties opduikt.
- **UUID-tak van direct-aftekenen** stuurde een verouderde signatuur naar de jaarinsigne-2026 batch-mail-helper en gooide een `NameError` **nadat** de SignoffRequest-rijen al gecommit waren — fix + regressietest toegevoegd.
- **Zelf-verwerping** op `reject_jaarinsigne_2026_signoff` heeft nu net als `confirm_*` een expliciete `mentor_id != scout_id`-controle (was alleen impliciet via een data-invariant).
- **Dode code verwijderd** — het `dedicated_api`-vlaggetje dat speculatief tijdens het jaarinsigne-design was toegevoegd, werd nergens gebruikt; weggehaald uit `BadgeCatalogue`, alle routers en templates.

### Beveiliging

- **Self-signoff foutmelding** in de directe-aftekenen flow — een scout die zijn eigen e-mail invult krijgt nu een inline foutmelding in plaats van een stilte zonder bevestiging.
- **Step-check dropdown** in mentor-cell positionering (al gemerged via #96).
- Security-champion review uitgevoerd; geen High/Medium bevindingen. Drie pre-existing observaties op tracking-issues gezet (#97 scope mentor/speltak-input, #98 e-mailvalidatie, #99 CSRF-houding).

### Onderhoud

- Frontend-stack documentatie (Jinja2 + HTMX + Alpine.js + inline Font Awesome SVG) toegevoegd aan `CLAUDE.md`.
- `CHANGELOG.md` workflow gewijzigd: voortaan per PR onder `[Unreleased]` bijwerken, consolideren bij release.
- Jaarinsigne-specifieke structuurtests (`TestJaarinsigneStructure`, `TestJaarinsigne2026Structure`) toegevoegd om gaten te dichten waar de generieke `TestBadgeStructure` jaarinsignes oversloeg.
- Totaal aantal tests: 1210 (was 1099 voor deze PR).

---

## [v0.12.1] — 2026-05-12

### Beveiligingsrelease — CodeQL-bevindingen opgelost

#### Opgelost

- **Path injection geëlimineerd** (`py/path-injection`, meldingen #28, #29, #75) — badge-YAML-bestanden worden nu eenmalig bij opstarten ingeladen via `BadgeCatalogue`. Er bereikt geen door de gebruiker aangeleverde waarde meer een `Path()`-aanroep tijdens een verzoek; de kwetsbaarheid is architectureel onmogelijk geworden.
- **Open redirect via ruwe URL-parameters** (`py/url-redirection`, meldingen #2–#27) — alle `RedirectResponse`-aanroepen in `html_badges.py` en `html_groups.py` (26 locaties) gebruiken nu DB-gevalideerde waarden (`scout.id`, `group.slug`, `speltak.slug`) in plaats van ruwe URL-padparameters.
- **XSS in ruwe HTMLResponse** (`py/reflective-xss`, melding #73) — gebruikersdata die in een `HTMLResponse`-string werd geïnterpoleerd, is nu omgeven door `html.escape()`.
- **Padtraversal (defence-in-depth)** (`py/path-injection`, melding #28) — extra controle via `resolve()` en `is_relative_to()` toegevoegd als aanvullende maatregel naast de reeds bestaande slug-validatie (vervangen door `BadgeCatalogue`-architectuur).

#### Beveiliging

Alle 84 CodeQL-bevindingen zijn beoordeeld. Echte kwetsbaarheden zijn verholpen; valse positieven (redirects vanuit hardgecodeerde `_require_*`-helpers) zijn gedocumenteerd gedismisst.

---

## [v0.12.0] — 2026-05-12

### Explorer Jaarbadge en verbeterde testinfrastructuur

#### Nieuw

- **Explorer Jaarbadge** — nieuw insignetype met drie jaren (J1, J2, J3) en acht eisgroepen.
  - Eigen `niveau_label` ("Jaarbadge") en compacte `niveau_label_kort` ("J") voor mobiel.
  - Lege eisen tellen niet mee: Jaarbadge 1 en 2 tonen 7 vakjes, Jaarbadge 3 telt 8.
  - Insigneafbeeldingen met transparante achtergrond en dunne witte hexagonale rand.
- **`niveau_label_kort`** — nieuw veld in badge-YAML voor het compacte label in stapkaarten en mobiele navigatie. Standaardwaarde `N`, Explorer-specifiek `J`.

#### Verbeteringen

- **Exportversie verhoogd naar v2** — export-YAML bevat nu `version: 2`. Importfunctie weigert bestanden van een hogere versie dan het systeem aankan; v1-bestanden blijven backwards compatible.
- **Testinfrastructuur** — tests gesplitst in `tests/unit/` en `tests/integration/` met twee aparte CI-jobs (`unit-tests` en `integration-tests`), zodat elke job afzonderlijk vereist kan worden in branch protection.
- **Branch protection** — `main` vereist nu dat beide CI-jobs slagen voor een merge.
- **Pytest-waarschuwingen onderdrukt** — `pytest.ini` filtert DeprecationWarnings en ResourceWarnings van third-party bibliotheken (Starlette, PyMuPDF, SQLAlchemy).

#### Tests

- 7 nieuwe unit tests voor de Explorer Jaarbadge (categorie, niveau_label, eisgroepen, lege stappen).
- 4 nieuwe integratietests voor rendering van de Explorer Jaarbadge in HTML.
- 3 nieuwe PDF-tests (Explorers-kopregel, Jaarbadge-labels, Niveau-labels).
- Tests voor versiebeveiliging: afwijzing van toekomstige versies en backwards compatibility met v1.

---

## [v0.11.0] — 2026-05-07

### Beheerderspaneel met statistieken en voortgang exporteren/importeren

#### Nieuw

- **Beheerderspaneel** — admins zien nu een dashboardpagina (`/admin/dashboard`) met interactieve statistieken:
  - Gebruikers over tijd, aftekeningactiviteit en groepsgrootte als lijngrafiek met dagelijkse granulariteit, zoom/pan en volledig scherm.
  - Verdeling van gebruikers over groepen en speltakken als twee cirkeldiagrammen naast elkaar.
  - Sleepselectie om een tijdsbereik in te zoomen; Ctrl+sleep om te verschuiven.
- **Gebruikers verwijderen** — admins kunnen accounts verwijderen vanuit het beheerderspaneel.
  - Bij verwijdering ontvangt de gebruiker een bevestigingsmail.
  - Admins kunnen geen adminaccount verwijderen; de adminrechten moeten eerst worden ingetrokken.
  - De verwijderknop wordt grijs en toont "Bezig met verwijderen…" tijdens de actie.
  - Zelf-verwijdering via `/profile` stuurt ook een bevestigingsmail.
- **Voortgang exporteren** — scouts kunnen hun volledige voortgang downloaden als YAML of PDF via het nieuwe scherm *Importeren/exporteren* (bereikbaar via het gebruikersmenu).
  - De PDF toont per insigne een raster van 5 eisgroepen × 3 niveaus met de insigneafbeeldingen als kolomkoppen en statuskleurcodering.
  - De PDF bevat een ingebedde YAML-bijlage die als paperclip-annotatie zichtbaar is in macOS Preview; de PDF-metadata (titel, auteur, onderwerp, aanmaakdatum) is correct ingesteld.
  - Bestandsnaam: `insignesysteem_export_<naam>-<jjjjmmdd>.pdf`.
- **Voortgang importeren** — scouts kunnen een eerder geëxporteerd YAML- of PDF-bestand uploaden om voortgang te herstellen.
  - Bestaande voortgang wordt nooit verlaagd; een hogere status wint altijd.
  - Openstaande aftekenverzoeken worden niet hersteld.
  - De naam van de aftekener wordt bewaard (geen e-mailadres); bij import wordt een gedeelde naamhouder aangemaakt of hergebruikt.
  - Drag-and-drop uploadzone op de importpagina.
- **Gebruikersmenu** — de navigatiebalk toont nu een dropdown met de naam van de ingelogde gebruiker, met submenu-items: *Profiel bewerken*, *Importeren/exporteren* en *Uitloggen*.

#### Verbeteringen

- Uitloggen is verplaatst van de profielpagina naar het navigatiemenu.
- Seed-script werkt correct wanneer groepen of speltakken al bestaan.

#### Tests

- 34 nieuwe tests voor de export/import-service en bijbehorende API-endpoints, inclusief volledige roundtrip-tests (YAML en PDF op verschillende gebruikers).

---

## [v0.10.0] — 2026-04-29

### Mobielvriendelijke interface, privacybeleid en e-mailprivacy

#### Nieuw

- **Mobielvriendelijke interface** — het systeem is volledig herschreven voor gebruik op smartphones en tablets. Insignebadges worden getoond als honingraatkaarten met voortgangsbollen; de niveauselectie op de detailpagina werkt via tabknoppen in plaats van een dropdownmenu; speltakleiders kunnen ook op mobiel de voortgang van scouts inline bewerken.
- **Privacybeleid** — er is een privacybeleidpagina toegevoegd die beheerders kunnen aanpassen. Zolang het standaardbeleid niet is aangepast, ziet de beheerder een banner bovenaan elke pagina als herinnering.
- **GitHub-link in de footer** — directe link naar de broncode op GitHub.

#### Verbeteringen

- Uitloggen is verplaatst van de navigatiebalk naar de profielpagina (rode knop onderaan), zodat de navigatie overzichtelijker is.
- Gebruikersnaamlink in de navigatiebalk verwijderd (was overbodig naast de systeemtitel).
- Overbodige "Niveau X."-kopregel verwijderd uit alle 22 insignedefinities; de tekst loopt nu direct door.
- Versiecontrole op beschikbare GitHub-releases werkt nu op de achtergrond en wordt elk uur vernieuwd.
- E-mailadressen van uitgenodigde scouts die nog geen naam hebben ingesteld, worden nu correct getoond in het voortgangsoverzicht en de speltak-detailpagina.
- Voeterelementen netjes gescheiden met `|`-tekens.

#### Privacyverbeteringen

- E-mailadressen van scouts worden niet meer getoond in uitnodigings-datalists; in plaats daarvan wordt de naam weergegeven en het UUID transparant doorgegeven.
- E-mailadressen zijn verwijderd uit de respons van niet-geverifieerde e-mailwijzigingsendpoints.
- E-mailadres verborgen in het directe aftekeningsdialoogvenster bij de status "klaar".

---

## [v0.9.0] — 2026-04-28

### Scout-voortgang per speltak, versieweergave en beveiligingsverbeteringen

#### Nieuw

- **Voortgang per scout** — speltakleiders kunnen vanuit het voortgangsoverzicht op de naam van een scout klikken om een detailpagina te zien met alle insignes en stappen van die scout.
- **Versieweergave in de footer** — de huidige versie staat altijd onderaan de pagina. In ontwikkelmodus wordt het aantal commits na de laatste release getoond (bijv. `v0.9.0+3`). Is er een nieuwere release beschikbaar op GitHub, dan verschijnt een oranje melding met de versie en uitleg hoe te updaten.
- **`GET /api/version`** — nieuw JSON-endpoint dat de huidige versie en eventuele nieuwere release teruggeeft.
- **`INSIGNE_MOCK_NEWER_RELEASE`** — omgevingsvariabele waarmee de "nieuwe versie beschikbaar"-melding gesimuleerd kan worden zonder een echte GitHub-release.

#### Verbeteringen

- Scoutnamen in het voortgangsoverzicht en de speltak-detailpagina zijn nu duidelijk klikbaar (blauw, onderstreept bij hover).

#### Beveiligingsfixes

- Groepspagina's en speltakpagina's vereisen nu een actieve inlogsessie; niet-ingelogde bezoekers worden doorgestuurd naar de inlogpagina.
- Het `niveau-checks`-gedeelte geeft een 401-fout terug wanneer de gebruiker niet is ingelogd, zodat voortgangsdata niet openbaar opvraagbaar is.

---

## [v0.8.0] — 2026-04-24

### Groepsbeheer en aftekening via speltak

Deze release voegt volledige ondersteuning toe voor scoutinggroepen, speltakken en speltak-gerichte aftekening.

#### Nieuw

- **Groepen en speltakken beheren** — groepsleiders kunnen groepen aanmaken, speltakken toevoegen en leden uitnodigen of beheren.
- **Rollenstelsel** — onderscheid tussen groepsleiders, speltakleiders en scouts; admins worden ingesteld via de configuratie.
- **Lidmaatschapsverzoeken** — scouts kunnen een verzoek indienen om lid te worden van een groep; groepsleiders keuren dit goed of af.
- **Speltak-gerichte aftekening** — scouts kunnen voor een gewone speltak alle speltakleiders tegelijk uitnodigen om af te tekenen; voor een volwassenenspeltak (peer-aftekening) kunnen ze één of meerdere mede-leden selecteren.
- **Zelfaftekening geblokkeerd** — het is niet mogelijk jezelf af te tekenen.
- **Voortgang beheren als speltakleider** — speltakleiders kunnen de voortgang van scouts in hun speltak bijhouden en aanpassen via het voortgangsoverzicht.
- **Scout samenvoegen bij uitnodiging** — wanneer een scout zonder account een uitnodiging accepteert en al een account blijkt te hebben, kan de voortgang worden samengevoegd.
- **E-mailadres wijzigen** — scouts kunnen hun e-mailadres wijzigen; een bevestigingsmail maakt de wijziging definitief.
- **Contactformulier** — openbaar contactformulier met wiskundig captcha voor niet-ingelogde bezoekers.
- **Insignelint** — afgetekende insigneniveaus worden als honingraatlint weergegeven op de homepagina.
- **Databasemigraties** — Alembic beheert het databaseschema zodat upgrades soepel verlopen.
- **Favoriete insignes** — speltakleiders kunnen insignes markeren als favoriet en het voortgangsoverzicht filteren.

#### Verbeteringen

- Navigatieteller voor openstaande aftekeenverzoeken werkt nu direct bij na bevestigen of afwijzen.
- Aftekenen in het voortgangsraster vereist een motivatie wanneer een afgetekende stap wordt teruggedraaid.
- Afwijzen van een aftekeenverzoek verwijdert alleen het verzoek van de afwijzende mentor; het voortgangsitem keert terug naar "klaar" zodra er geen openstaande verzoeken meer zijn.
- Emailloze scouts worden verborgen in de ledenlijst zodra er een openstaande uitnodiging bestaat.

---

## [v0.5.0] — 2026-04-21

### Initiële release — individuele scouts

De eerste werkende release van het Insigne Systeem, gericht op individuele scouts die zelfstandig hun insignevoortgang bijhouden.

#### Functionaliteiten

- **Registratie en inloggen** — account aanmaken via e-mailbevestiging, wachtwoord instellen, inloggen met cookie-gebaseerde sessie.
- **Insignecatalogus** — 20 insignedefinities (gewone en buitengewone insignes) met afbeeldingen en eisen per niveau.
- **Voortgang bijhouden** — per eis de status instellen: bezig, klaar of afgetekend.
- **Aftekenstroom** — een mentor uitnodigen via e-mail, bevestigen of afwijzen met een toelichting; de scout ontvangt een notificatie per e-mail.
- **Aftekening annuleren** — scout kan een openstaand aftekeenverzoek zelf intrekken.
- **Productieklare installatie** — systemd user service met `insigne-ctl` beheerscript; configureerbare host, poort en keep-alive instellingen.
- **JSON API** — volledige REST API naast de HTML-interface.
- **Testdekking** — >95% testdekking met unit- en integratietests.

---

[v0.10.0]: https://github.com/MrSeccubus/insigne-systeem/releases/tag/v0.10.0
[v0.9.0]: https://github.com/MrSeccubus/insigne-systeem/releases/tag/v0.9.0
[v0.8.0]: https://github.com/MrSeccubus/insigne-systeem/releases/tag/v0.8.0
[v0.5.0]: https://github.com/MrSeccubus/insigne-systeem/releases/tag/v0.5.0
