"""Catalogue loading and v1→v2 migration.

Public surface:
  - `load_catalogue(path, project_path)` -> LoadedCatalogue
  - `migrate_v1_to_v2(v1_doc)` -> v2_doc
  - `load_mapping_pack(path)` -> MappingPack
"""
from server.catalogue.loader import (
    LoadedCatalogue,
    LoadedMappingPack,
    load_catalogue,
    load_mapping_pack,
)
from server.catalogue.migrate_v1 import migrate_v1_to_v2, MigrationReport

__all__ = [
    "LoadedCatalogue",
    "LoadedMappingPack",
    "load_catalogue",
    "load_mapping_pack",
    "migrate_v1_to_v2",
    "MigrationReport",
]
