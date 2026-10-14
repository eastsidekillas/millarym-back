from django.db import migrations

CATEGORIES = [
    "Угловые диваны",
    "Прямые диваны",
    "Малогабаритные диваны",
    "Комплекты мягкой мебели",
    "Кресла",
    "Пуфы",
    "Кровати",
]
KIT = ["Левый угол", "Правый угол", "Накладки венге", "Накладки белые", "Накладки серые"]


def seed(apps, schema_editor):
    Category = apps.get_model("app_catalog", "Category")
    KitOption = apps.get_model("app_catalog", "KitOption")
    Deadlines = apps.get_model("app_catalog", "Deadlines")
    for i, name in enumerate(CATEGORIES, 1):
        Category.objects.get_or_create(name=name, defaults={"sort": i * 10})
    for i, name in enumerate(KIT, 1):
        KitOption.objects.get_or_create(name=name, defaults={"sort": i * 10})
    Deadlines.objects.get_or_create(pk=1)


class Migration(migrations.Migration):
    dependencies = [("app_catalog", "0001_initial")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
