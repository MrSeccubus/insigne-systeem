# Versiegeschiedenis — Insigne Systeem

Alle noemenswaardige wijzigingen per release, in omgekeerde chronologische volgorde.

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
