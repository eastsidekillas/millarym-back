from django.db import migrations

INDEXES = {
    "item_reserve_trgm": ("app_production_item", "reserve"),
    "item_extra_trgm": ("app_production_item", "extra"),
    "fabric_name_trgm": ("app_catalog_fabric", "name"),
    "productmodel_name_trgm": ("app_catalog_productmodel", "name"),
}


def create(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    for name, (table, column) in INDEXES.items():
        schema_editor.execute(
            f"CREATE INDEX IF NOT EXISTS {name} ON {table} USING gin (UPPER({column}) gin_trgm_ops)"
        )


def drop(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    for name in INDEXES:
        schema_editor.execute(f"DROP INDEX IF EXISTS {name}")


class Migration(migrations.Migration):
    dependencies = [
        ("app_production", "0001_initial"),
        ("app_catalog", "0002_seed"),
    ]

    operations = [migrations.RunPython(create, drop)]
