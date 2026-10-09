"""Moduly Platform 2.0 postavené od začátku jako samostatné balíčky (`modules/<id>/`).

Starší moduly (škola, práce, finance, cíle, WoT, MFF) zůstávají na svých místech v kořeni backendu
(`<id>_integrations.py`). Nový modul má vše své v `modules/<id>/` a do sdíleného kódu přidává jen záznam
v `module_registry.py`, řádek modelů v `models.py` a migraci (docs/module-framework.md §8).
"""
