import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import CommandError, call_command
from django.test import TestCase
from openpyxl import Workbook

from app_catalog.models import Category, ProductModel


class ImportModelsTest(TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def run_cmd(self, *args, **kwargs):
        out = StringIO()
        call_command("import_models", *args, stdout=out, **kwargs)
        return out.getvalue()

    def csv(self, text: str, encoding="utf-8-sig") -> str:
        path = self.dir / "models.csv"
        path.write_bytes(text.encode(encoding))
        return str(path)

    def test_csv_with_categories(self):
        ProductModel.objects.create(name="Бостон БД", category=Category.objects.get(name="Прямые диваны"))
        path = self.csv("Название;Категория\nБостон  БД;Прямые диваны\nДуглас диван;Прямые диваны\nдуглас ДИВАН;Прямые диваны\nЛион;Кровати\nЗонт;Зонтики\n;\n")
        out = self.run_cmd(path)
        self.assertIn("Новых моделей: 2, уже были: 1", out)
        self.assertIn("повтор в файле: 1", out)
        self.assertIn("Зонт (Зонтики)", out)
        self.assertTrue(ProductModel.objects.filter(name="Лион", category__name="Кровати").exists())

    def test_dry_run_writes_nothing(self):
        out = self.run_cmd(self.csv("name,category\nРио,Малогабаритные диваны\n"), dry_run=True)
        self.assertIn("Проверка без записи", out)
        self.assertFalse(ProductModel.objects.exists())

    def test_cp1251_and_create_categories(self):
        path = self.csv("Модель;Категория\nКомод;Корпусная\n", encoding="cp1251")
        self.run_cmd(path, create_categories=True)
        self.assertTrue(ProductModel.objects.filter(name="Комод", category__name="Корпусная").exists())

    def test_xlsx_and_default_category(self):
        wb = Workbook()
        wb.active.append(["Наименование"])
        wb.active.append(["Кресло Дубай"])
        wb.active.append(["Кресло Куба"])
        path = self.dir / "models.xlsx"
        wb.save(path)
        with self.assertRaises(CommandError):
            self.run_cmd(str(path))
        self.run_cmd(str(path), category="Кресла")
        self.assertEqual(ProductModel.objects.filter(category__name="Кресла").count(), 2)

    def test_update_category(self):
        ProductModel.objects.create(name="Лион", category=Category.objects.get(name="Пуфы"))
        self.run_cmd(self.csv("Название;Категория\nЛион;Кровати\n"), update_category=True)
        self.assertEqual(ProductModel.objects.get(name="Лион").category.name, "Кровати")
