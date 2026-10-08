# Šablona Linear issue

Zdroj pro šablonu v Linearu (Settings → Templates → Issue, tým MRK). Linear API šablony vytvářet
neumí, proto ji zkopíruj ručně. Workflow a handoff: [../AGENTS.md](../AGENTS.md).

Titulek: krátký, v rozkazovacím způsobu („Add …“, „Fix …“). Štítky: typ (Bug / Improvement /
Feature) + jeden **Area**. Milník podle roadmapy.

```markdown
## Kontext
Proč to děláme. U bugu: kde se projevil, vstup → aktuální výsledek → očekávaný výsledek.

## Scope
- …

## Mimo scope
- …

## Akceptační kritéria
- [ ] …
- [ ] …

## Jak ověřit
Testy, ui-check (desktop + 390 px), ruční kroky. Co musí ověřit Standa lokálně
(reálná DB, Windows, mobil).

## Odkazy
Design / docs / související issues / branch.
```
