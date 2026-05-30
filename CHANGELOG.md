# Versiegeschiedenis — Insigne Systeem

Alle noemenswaardige wijzigingen per release, in omgekeerde chronologische volgorde.

PR's voegen hun wijzigingen toe onder `## [Unreleased]`. Bij een release wordt
deze sectie geconsolideerd in een nieuwe `## [vX.Y.Z]` sectie en `[Unreleased]`
weer leeg gemaakt.

---

## [Unreleased]

### Beveiliging

- **Strictere validatie op jaarinsigne-2026-inclusie-import** (sluit #124) — defence-in-depth op de import-tak die v1.0.1 toevoegde voor de jaarinsigne-2026-inclusies. Een handmatig bewerkte export-YAML met niet-int `level_index`/`step_index` of een `badge_slug` buiten de toegestane categorieën (`gewoon`/`buitengewoon`) leidde alleen tot self-inflicted 500's op latere pagina-aanroepen van de uploader zelf (geen cross-user impact, geen score-inflatie). De import valideert nu types via `int(...)` met `TypeError/ValueError` opvangen, en de `badge_slug` wordt gecontroleerd tegen `jaarinsigne_2026.get_eligible_badges()` — zelfde checks als de canonical `toggle_inclusion` write-path. 4 nieuwe tests.
- **Auth-helpers retourneren alleen data — geen `RedirectResponse`** (sluit #100) — re-verificatie van de 46 gedismisste `py/reflective-xss` CodeQL-bevindingen wees uit dat ze allemaal hetzelfde patroon waren: `_require_user` / `_require_admin` retourneerden `(user, RedirectResponse | None)` en aanroepers deden `return redirect`. CodeQL's taint-analyse kon door de uniontype niet zien dat de redirect altijd een constante URL gebruikt, dus elke `return redirect` werd als reflective-XSS gemarkeerd. In plaats van de 46 dismissals te herbevestigen, is dezelfde refactor toegepast als in PR #116 (CodeQL #87): `_require_user` retourneert nu enkel `User | None`, `_require_admin` retourneert `(current_user, admin)` waar beide `User | None` zijn, en de 51 aanroeplocaties bouwen hun eigen `RedirectResponse` op uit string-literals (`"/login"` of `"/"`). CodeQL's volgende scan moet de dismissals naar "fixed" promoten of leeggemaakt achterlaten.

### Verbeteringen

- **Auto-inklappen van het "Explorers"-blok op de homepage** (sluit #110) — ingelogde scouts die niet in een explorers-speltak zitten (welpen, scouts, roverscouts, plusscouts) zien het "Explorers"-blok op `/` nu standaard ingeklapt als `<details>`-element. Explorers zelf én anonieme bezoekers krijgen het blok zoals voorheen direct uitgeklapt onder een `<h2>`. Geen wijziging aan andere categorieën. `current_user_speltak_type` toegevoegd aan de homepage-template-context.

---

## [v1.0.1] — 2026-05-19

### Patchrelease — jaarinsigne-rendering en export/import

Een korte patch op v1.0.0 om de jaarinsigne-weergave op de homepage, de leider-scoutpagina en de PDF-export te corrigeren (per-niveau in plaats van één niveau), om de jaarinsigne-2026-selecties netjes mee te nemen in export/import, om het bladicoon ook op gewone step-cards te tonen, en om een paar kleinere UX-haakjes uit v1.0.0 op te lossen.

#### Opgelost

- **Speltaktype-prompt op peer-signoff speltakken zonder type** (sluit #118) — een speltak met `peer_signoff=True` en zonder `speltak_type` toonde alleen "Volwassenen speltak — leden mogen voor elkaar aftekenen", zonder de leider erop te wijzen dat het type nog niet ingesteld was (en zonder edit-link). De else-tak van speltak_detail.html werd voor niet-peer-signoff speltakken wel met een "stel het speltak type in"-link weergegeven, voor peer-signoff niet. Beide ontbrekende-type-branches komen nu samen: ze laten zien dat het type ontbreekt en bieden de leider (`can_manage`) een directe link om het type in te stellen.
- **Jaarinsigne-2026 niveau-wissel herberekent eis-statussen** — wisselde een scout in de editor van speltak-niveau (bv. van welpen naar scouts), dan bleven de eis-checkboxes op het nieuwe niveau op "none" staan tot er handmatig een inclusie werd toe/afgeroepen. De per-niveau drempels (`punten`, `groen`, `niveau2`, `niveau3`, `insignes`, `leiding_bepaald`) zijn echter wél anders per speltak, dus de bestaande inclusies vinden tegen het nieuwe niveau soms wel/niet een drempel. `progress_svc.set_jaarinsigne_level` roept nu, alleen voor `jaarinsigne_2026`, direct na het persistenten van het niveau `jaarinsigne_2026.update_progress_entries` aan voor het nieuwe niveau, zodat de checkboxes meteen kloppen. 3 nieuwe service-tests.
- **Jaarinsigne-weergave volgens scout-voortgang** (sluit #122) — de homepage en PDF-export toonden een jaarinsigne altijd op precies één niveau (het door `resolve_jaarinsigne_level_index` gekozen "scout-speltak"-niveau). Daardoor verdween informatie zodra een scout op meerdere speltakken voortgang had, en in de PDF werden jaarinsignes met het reguliere 5-eis × 3-niveau raster gerenderd dat niet bij hun structuur past. Nieuwe regel: één kaart/sectie per niveau waar de scout *enige* `ProgressEntry` heeft; bij geen voortgang valt de weergave terug op het opgeloste niveau van de scout's eigen speltak. Gedeelde helper `insigne.badges.jaarinsigne_levels_for_scout` toegepast op `api/main.py:index`, `api/routers/html_badges.py:_build_badge_catalogue` en de PDF-renderer in `progress_export.to_pdf`. De PDF heeft nu ook per jaarinsigne-niveau een eigen mini-tabel (rijen = eisen, één kolom = status) in plaats van het verkeerde 3-niveau-raster. Voor jaarinsigne_2026 (meta-insigne) toont de PDF nu de geselecteerde inclusies (Insigne / Niveau / Eis), wat tegelijk gebruikmaakt van de nieuwe `jaarinsigne_2026_inclusions` exportsleutel uit #111. Ook `user.primary_speltak_type` is aan de export-YAML toegevoegd zodat de PDF de scout's speltak kent voor de fallback.
- **Jaarinsigne-2026-selecties verloren bij export/import** (sluit #111) — de scout maakt in de jaarinsigne-2026-editor een keuze welke eisen van *gewone* en *buitengewone* insignes meetellen. Die rijen leven in een eigen tabel (`Jaarinsigne2026Inclusion`) en werden door `progress_export.export_data` en `progress_export.import_progress` niet meegenomen. Wie zijn voortgang exporteerde en op een ander account importeerde, raakte z'n meta-insigne-inclusies kwijt. Exportversie verhoogd naar `3` met een nieuwe top-level `jaarinsigne_2026_inclusions` lijst; import is idempotent (controleert op de bestaande unique-constraint) en blijft v1/v2-exports zonder deze sleutel gewoon accepteren.

#### Verbeteringen

- **Blad-icoon op "groene" eisen ook in step-cards** (sluit #108) — het inline Font Awesome bladicoon dat tot nu toe alleen in de jaarinsigne-2026-editor groene eisen markeerde, verschijnt nu ook in de gewone step-card-weergave. Het icoon staat verticaal gestapeld onder de Nx-indicator (geen horizontale ruimte gebruikt — voorkomt dat step-cards in de overzichtsgrid te smal worden). Voor gedeeltelijk-groene eisen (\`==tekst==\` binnen een zin) verschijnt het bladicoon via een pure-CSS \`::before\` regel op elke \`<span class="eis-groen">\`, met een data-URI SVG (geen wijziging aan de render-pipeline).

---

## [v1.0.0] — 2026-05-18

### Eerste stabiele release — jaarinsignes, batch sign-off en gebruikersfavorieten

Drie kwartalen aan ontwikkeling stabiliseren in deze eerste 1.0-release. De jaarinsigne-architectuur (één badge met aparte eisen per speltak), het meta-insigne Jaarinsigne 2026 (afgeleid van bestaande voortgang), batch-aftekenen, een complete JSON-API voor jaarinsigne-2026 en persoonlijke insignefavorieten zitten allemaal in dit pakket. Daarnaast is de hele schrijfflow voor mentor- en uitnodigingse-mails ge-audit: alleen geldige adressen kunnen nog `User`-rijen aanmaken, en aftekenverzoeken zijn gescoped op de daadwerkelijke speltak- en groepslidmaatschappen van de scout.

#### Nieuw

- **Persoonlijke favoriete insignes** (#90) — naast de bestaande speltak- en groepsfavorieten kun je nu ook per gebruiker insignes "sterren" via de homepagina. De ster-knop verschijnt alleen op de homepage (`/`) — nooit op een leider-overzicht. Een ★/☆-toggle bovenaan filtert de homepage op je eigen favorieten. Voorkeur blijft bewaard onafhankelijk van speltak- of groepslidmaatschap.
  - Nieuw `UserFavoriteBadge` model + Alembic-migratie.
  - Nieuwe service-functies `get_user_favorite_slugs` / `toggle_user_favorite_badge`.
  - JSON-endpoint `GET /api/users/me/favorite-badges` en `POST /api/users/me/favorite-badges/{slug}/toggle`.
- **Voortgangsfilter "lopende insignes"** (#91) — 🏃 (Font Awesome person-running SVG) toggle-knop op de homepage, scout-voortgangspagina (`/scouts/{id}`) en speltak-voortgangspagina toont alleen insignes waar al voortgang op is. De nieuwe filter combineert met de bestaande ★-favorietenfilter; de query-parameters `only_favorites` en `only_in_progress` worden onafhankelijk van elkaar bewaard bij toggle.
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

#### Verbeteringen

- **Loop-icoon vervangt emoji** (#91) — de eerder gebruikte 🏃-emoji is vervangen door een inline Font Awesome SVG, voor consistentere rendering op alle platforms en mailclients.
- **Lege-staat berichten voor filtercombinaties** (#91) — bij actieve filters maar geen resultaten was er voorheen een lege pagina; nu staat er per combinatie een duidelijke melding:
  - ★ alleen, geen favorieten ingesteld → uitleg en uitnodiging om favorieten toe te voegen.
  - ★ alleen, favorieten bestaan maar geen match in deze categorie/speltak.
  - 🏃 alleen, geen lopende voortgang.
  - 🏃 + ★ samen, geen overlap.
- **`render_eis` gedeeld** — markdown-naar-inline-HTML-routine verplaatst naar `lib/insigne/eis_render.py` met een `render_eis_email` variant die `==…==` als inline groen rendert (mailclients negeren `<style>`-blokken). Reguliere insigne-e-mails pikken dezelfde fix op.
- **Step-check tickboxes** in de jaarinsigne-2026-editor synchroniseren live mee met de inclusies via een HTMX-bodyswap.
- **Compacte eis-rendering** in de editor cards — markdown wordt gestript behalve `==…==` groene accenten; te lange teksten krijgen een "Toon volledige eis"-toggle die de volledige markdown laat zien.
- **Sortering** in beide editorkolommen volgt `badges.yml`-volgorde → niveau → eisnummer.
- **Uitnodigingen** (sluit #92) — de uitnodigingsmail voor nieuwe groepsleiders en speltakleden bevat geen 1 uur geldige bevestigingscode meer; in plaats daarvan staat er een link naar `/register?email=<adres>` waar de uitnodigde de standaard registratieflow doorloopt op eigen tempo. De pending User-rij en lidmaatschappen worden bij uitnodiging aangemaakt (zodat de leider de openstaande uitnodiging blijft zien) zonder bijbehorende ConfirmationToken. Ook de mentor-uitnodigingsmails voor zowel reguliere step-signoffs als jaarinsigne-2026 batch-signoffs gebruiken nu dezelfde `/register?email=<adres>` link, zodat het ingevulde adres meteen voorgevuld in het registratieformulier staat.
- **Aanmeldverzoeken** (sluit #92) — bij openstaande aanmeldverzoeken voor een speltak ziet de speltakleider nu zowel de naam als het e-mailadres van de aanvrager, zodat onbekende namen makkelijker te herkennen zijn.

#### Opgelost

- **Numerieke query-parameters met aangehangen leestekens** (sluit #93) — URL's die uit tekst tussen haakjes worden gekopieerd (zoals `(https://…?niveau=1)`) bevatten soms de afsluitende `)`. De HTML-routes voor `niveau` en `only_in_progress` accepteren nu een leidende numerieke waarde en strippen aangehangen niet-numerieke tekens, zodat zulke URL's gewoon de juiste pagina openen in plaats van een 422-foutmelding te tonen.
- **Step-check dropdown positionering** (#96, sluit #95) — drie aparte bugs in de leider-aftekendropdown:
  - **Verkeerde positie na HTMX-swap**: de `<details>`-summary kreeg een Alpine.js `@toggle`-handler die `getBoundingClientRect()` leest en `top`/`left` op de dropdown zet wanneer deze `position: fixed` is. Mobile-layout (`position: absolute`) blijft onaangetast.
  - **Meerdere dropdowns tegelijk open**: globale `click`-handler op `document` sluit alle andere open `.step-check-wrapper`-elementen wanneer een wrapper wordt aangeklikt; klikken buiten elke wrapper sluit alles.
  - **Dropdown blijft zichtbaar bij scrollen**: globale `scroll`-handler (met `capture: true`) sluit alle open dropdowns zodra de pagina scrollt — voorkomt dat de dropdown midden op het scherm "zweeft" wanneer de trigger is weggescrolld.
- **Self in autocomplete** — `list_previous_mentors` filtert defensief de scout zelf weg, zodat een per ongeluk ontstane "self-signoff"-rij niet meer in de mentor-suggesties opduikt.
- **UUID-tak van direct-aftekenen** stuurde een verouderde signatuur naar de jaarinsigne-2026 batch-mail-helper en gooide een `NameError` **nadat** de SignoffRequest-rijen al gecommit waren — fix + regressietest toegevoegd.
- **Zelf-verwerping** op `reject_jaarinsigne_2026_signoff` heeft nu net als `confirm_*` een expliciete `mentor_id != scout_id`-controle (was alleen impliciet via een data-invariant).
- **Dode code verwijderd** — het `dedicated_api`-vlaggetje dat speculatief tijdens het jaarinsigne-design was toegevoegd, werd nergens gebruikt; weggehaald uit `BadgeCatalogue`, alle routers en templates.

#### Beveiliging

- **Self-signoff foutmelding** in de directe-aftekenen flow — een scout die zijn eigen e-mail invult krijgt nu een inline foutmelding in plaats van een stilte zonder bevestiging.
- **Validatie van e-mailadressen bij aftekenverzoeken en uitnodigingen** (sluit #98, #106) — alle flows die op basis van een formulierveld een nieuwe `User`-rij konden aanmaken controleren het adresformaat nu eerst met dezelfde `email-validator` als Pydantic's `EmailStr`. Het HTML-formulier toont *"Geef een geldig e-mailadres op."* inline; JSON-endpoints geven `422`. Voorkomt vervuiling van de `users`-tabel via een formulierveld. Aangepaste plekken:
  - Per-eis directe aftekenen (`POST /progress/{id}/request-signoff`) — `progress_svc.request_signoff` gooit `Conflict("invalid_email")`.
  - Jaarinsigne-2026 batch directe aftekenen (`POST /badges/jaarinsigne_2026/request-signoff`) — `progress_svc.request_jaarinsigne_2026_signoff` gooit `Conflict("invalid_email")`.
  - Groepsleider- en speltakuitnodigingen (`POST /groups/{slug}/members/invite`, `POST /groups/{g}/speltakken/{s}/members/invite`) — `users_svc.get_or_create_pending_user` gooit `ValueError("invalid_email")`; de HTML-handlers vangen dit en renderen een inline foutmelding.
- **Scoping van mentor- en speltak-input bij aftekenverzoeken** (sluit #97) — de speltak- en members-aanvraag-endpoints (`/signoff-speltak`, `/signoff-members` per eis én de jaarinsigne-2026 batch-equivalenten) accepteerden tot nu toe willekeurige `speltak_id` / `mentor_ids` waardes uit een formulier zonder enige relatie te eisen tussen de scout en de doel-speltak of doel-mentor. Dat liet zich misbruiken als spam- en informatielek-primitief: een scout kon zo aftekenmail laten verzenden naar leiders van vreemde speltakken, of peer-leden in andere groepen op de hoogte stellen van eigen voortgang. Beide paden krijgen nu een controle vooraf:
  - **Speltak-pad** — `progress_svc.request_signoff_for_speltak` / `request_jaarinsigne_2026_signoff_speltak` gooien `Forbidden("not_member")` als de scout geen actieve `SpeltakMembership` (`approved=True, withdrawn=False`) voor de doel-speltak heeft. HTML-flow toont *"Je bent geen lid van die speltak."* inline; JSON-API geeft `403`.
  - **Members-pad** — `progress_svc.request_signoff_from_members` / `request_jaarinsigne_2026_signoff_members` filteren `mentor_ids` via `groups_svc.filter_mentor_ids_sharing_speltak` zodat alleen mentoren die een actieve speltakgenoot van de scout zijn doorkomen. Resterend lege lijst → bestaande `NotFound("no_eligible_mentors")` (geen informatie over de gefilterde mentoren in de respons).
- **CodeQL open-redirect bevindingen op jaarinsigne `set-level` handlers verholpen** (CodeQL #82) — de twee `set-level` handlers die met PR #94 zijn toegevoegd interpoleerden de ruwe URL-padparameters `slug` en `scout_id` in hun `RedirectResponse`. Beide redirects gebruiken nu een server-afgeleide waarde (`badge["slug"]` uit de catalogus, `scout.id` uit de DB-lookup van `_require_scout_access`); een onbekende `slug` of `scout_id` valt nu terug op een constante URL. Mocht een toekomstige CHANGELOG-sweep dezelfde patronen elders introduceren, dan is de afspraak: nooit een functie-argument (URL-padparameter) in een `RedirectResponse` f-string interpoleren — altijd een DB-row attribuut of catalogue-dict waarde uit een lookup. CodeQL's taint-analyse ziet die als untainted.
- **CodeQL reflective-XSS bevinding op `_require_scout_access` verholpen** (CodeQL #87) — de helper retourneerde tot nu toe ofwel `(User, User)` (succes) ofwel `(None, RedirectResponse)` (toegangsweigering). CodeQL's taint-analyse kon door die uniontype niet door dat `scout_or_redirect` op de falende tak altijd een `RedirectResponse` met constante URL was, en beschouwde het hele scout_id-pad als reflective-XSS. De helper retourneert nu `(User|None, User|None)`: het tweede element is altijd hetzelfde type, en de aanroeper bouwt zelf een `RedirectResponse` op uit string-literals (`"/"` of `"/login"`) zonder dat scout_id-data het pad raakt. Vier aanroeplocaties (`scout_progress_home`, `scout_badge_detail`, `scout_set_jaarinsigne_level`, `scout_niveau_checks`) zijn op de nieuwe vorm gebracht. Hetzelfde idee als de CodeQL #82-fix uitgebreid: niet alleen URL-content moet uit DB komen, ook het *response-object zelf* mag niet uit een functie komen die getainted input verwerkt.
- Security-champion review uitgevoerd; geen High/Medium bevindingen. Drie pre-existing observaties op tracking-issues gezet (#97 scope mentor/speltak-input, #98 e-mailvalidatie, #99 CSRF-houding).

#### Onderhoud

- Frontend-stack documentatie (Jinja2 + HTMX + Alpine.js + inline Font Awesome SVG) toegevoegd aan `CLAUDE.md`.
- Jaarinsigne-specifieke structuurtests (`TestJaarinsigneStructure`, `TestJaarinsigne2026Structure`) toegevoegd om gaten te dichten waar de generieke `TestBadgeStructure` jaarinsignes oversloeg.
- Totaal aantal tests: 1255 (was 1099 aan het begin van deze cyclus).

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
