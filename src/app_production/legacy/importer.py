"""Перенос живых изделий из старых «Резервов» и открытых заказов из старых «Заказов»."""

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, time

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from app_catalog.models import Fabric, ProductModel, Team

from ..models import LEGACY_PERIOD, EventKind, FabricSlot, Item, ItemEvent, ItemFabric, Stage
from ..services import stage_label
from . import text as t
from .fabrics import FabricMatcher

User = get_user_model()

RESERV_STAGE = {"4": Stage.CUT, "2": Stage.COVER, "3": Stage.WORK, "1": Stage.FG}
RESERV_SLOTS = [("main_tex", FabricSlot.MAIN), ("sec_tex", FabricSlot.COMP1), ("third_tex", FabricSlot.COMP2)]
ORDER_SLOTS = [
    ("goods_main_tex", FabricSlot.MAIN),
    ("goods_sec_tex", FabricSlot.COMP1),
    ("goods_third_tex", FabricSlot.COMP2),
]
CANCELLED = re.compile(r"\bснят|\bотмен|\bаннулир", re.IGNORECASE)
LEGACY_USER = "legacy"
# прежние фамилии сотрудников в старых базах → логин в новой системе
OLD_SURNAMES = {"филина": "postnikova"}
SEP = " · "
ORDER_SEQ_BASE = 10_000_000


@dataclass
class FabricPlan:
    slot: str
    name: str
    meters: float | None = None


@dataclass
class ItemPlan:
    number: str
    seq: int
    legacy_number: str
    source: str
    original_name: str
    model: ProductModel | None
    custom_name: str
    extra: str
    reserve: str
    stage: str
    manager_name: str
    created: date | None
    reserved: date | None = None
    stage_date: date | None = None
    fabric_arrived: date | None = None
    sew: date | None = None
    cover_ready: date | None = None
    work: date | None = None
    team_name: str = ""
    fabrics: list[FabricPlan] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class Report:
    reserv_total: int = 0
    orders_total: int = 0
    skipped: Counter = field(default_factory=Counter)
    stages: Counter = field(default_factory=Counter)
    linked: int = 0
    no_model: Counter = field(default_factory=Counter)
    new_fabrics: Counter = field(default_factory=Counter)
    similar_fabrics: Counter = field(default_factory=Counter)
    new_teams: Counter = field(default_factory=Counter)
    unknown_managers: Counter = field(default_factory=Counter)
    cut_without_unit: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    no_date: int = 0

    def lines(self, plans: list[ItemPlan], dry_run: bool) -> list[str]:
        out = []
        head = "ПРОВЕРКА — в базу ничего не записано." if dry_run else "Перенос выполнен."
        out.append(head)
        out.append(f"Резервы: строк {self.reserv_total}. Заказы: строк {self.orders_total}.")
        out.append(f"Будет заведено изделий: {len(plans)}" if dry_run else f"Заведено изделий: {len(plans)}")
        for stage in Stage.values:
            if self.stages[stage]:
                out.append(f"  {stage_label(stage)}: {self.stages[stage]}")
        out.append(f"  из них связано с заказом из старых «Заказов»: {self.linked}")
        if self.skipped:
            out.append("Не переносим:")
            for reason, n in self.skipped.most_common():
                out.append(f"  {reason}: {n}")
        if self.cut_without_unit:
            out.append(
                f"Заказы 2026 года раскроены, но в «Резервах» нет изделия с их номером ({len(self.cut_without_unit)}) — "
                "не переносим, проверьте вручную (отгружены или заведены в резервах без номера):"
            )
            out.append("  " + ", ".join(self.cut_without_unit))
        if self.conflicts:
            out.append("Уже перенесено ранее, но в старой базе изменилось — проверьте вручную:")
            out.extend(f"  {c}" for c in self.conflicts)
        if self.no_model:
            out.append(
                f"Модель не найдена в справочнике — изделие заведено «вне справочника» ({sum(self.no_model.values())}). "
                "Если модель нужна, добавьте её в справочник и запустите перенос заново до начала работы:"
            )
            out.extend(f"  {n} × {name}" for name, n in self.no_model.most_common())
        if self.similar_fabrics:
            out.append(
                f"Ткани сопоставлены по похожему названию ({len(self.similar_fabrics)}) — проверьте, что верно "
                "(старое имя файла → ткань в справочнике):"
            )
            out.extend(f"  {n} × {old} → {new}" for (old, new), n in self.similar_fabrics.most_common())
        if self.new_fabrics:
            out.append(
                f"Тканей нет в справочнике — заведены скрытыми, без фото ({len(self.new_fabrics)}), "
                "у изделий ткань сохранится, в выборе при заведении их не будет:"
            )
            out.extend(f"  {n} × {name}" for name, n in self.new_fabrics.most_common())
        if self.new_teams:
            out.append("Новые бригады (из поля бригадира): " + ", ".join(f"{k} ({v})" for k, v in self.new_teams.items()))
        if self.unknown_managers:
            out.append(
                "Менеджер не найден среди пользователей — «завёл: Старая система» "
                "(можно указать --manager \"Имя в старой базе=логин\"): "
                + ", ".join(f"{k} ({v})" for k, v in self.unknown_managers.most_common())
            )
        if self.no_date:
            out.append(f"Без известной даты этапа (на этапе «с даты переноса»): {self.no_date}")
        return out


def first_word(name: str) -> str:
    return t.clean(name).split(" ")[0].strip(".,").lower().replace("ё", "е")


class Importer:
    def __init__(self, reserv_rows, order_rows, since: date, manager_map: dict[str, str] | None = None):
        self.reserv_rows = reserv_rows
        self.orders = {}
        for o in order_rows:
            try:
                self.orders[int(o["order_id"])] = o
            except (TypeError, ValueError):
                continue
        self.since = since
        self.manager_map = {k.strip().lower(): v.strip() for k, v in (manager_map or {}).items()}
        self.report = Report(reserv_total=len(reserv_rows), orders_total=len(self.orders))
        self.matcher = t.ModelMatcher(ProductModel.objects.all())
        self.fabrics = FabricMatcher(Fabric.objects.all())
        self.teams = {}
        for team in Team.objects.all():
            for key in (first_word(team.name), first_word(team.foreman)):
                if key:
                    self.teams.setdefault(key, team)
        self.users = list(User.objects.filter(is_superuser=False).exclude(username=LEGACY_USER))
        self.existing = self._existing_legacy()

    @staticmethod
    def _existing_legacy() -> Counter:
        tokens = Counter()
        for value in Item.all_objects.exclude(legacy_number="").values_list("legacy_number", flat=True):
            for token in value.split(SEP):
                tokens[token.strip()] += 1
        return tokens

    def _name(self, plan_name: str, is_order: bool = False):
        model, rest = self.matcher.match(plan_name)
        if model:
            return model, "", t.extra_from(rest)
        # в заказе «- 2 штуки» — количество изделий, в резервах «2 шт.» — часть названия
        custom = t.custom_name_from(plan_name, strip_qty=is_order) or "Без названия"
        self.report.no_model[custom] += 1
        return None, custom, ""

    def _fabric(self, value, slot, meters=None) -> FabricPlan | None:
        name = t.fabric_name(value)
        if not name:
            return None
        fabric, loose = self.fabrics.find(name)
        if fabric is None:
            self.report.new_fabrics[name] += 1
        elif loose:
            self.report.similar_fabrics[(name, fabric.name)] += 1
        return FabricPlan(slot, name[:150], meters)

    @staticmethod
    def _meters(value) -> float | None:
        try:
            m = float(str(value).replace(",", "."))
        except (TypeError, ValueError):
            return None
        return round(m, 2) if 0 < m < 1000 else None

    def _resolve_manager(self, name: str) -> User | None:
        name = t.clean(name)
        if not name:
            return None
        login = self.manager_map.get(name.lower())
        if login:
            return next((u for u in self.users if u.username == login), None)
        words = {w.lower().replace("ё", "е") for w in name.replace(".", " ").split()}
        for surname, login in OLD_SURNAMES.items():
            if surname in words:
                return next((u for u in self.users if u.username == login), None)
        for user in self.users:
            if user.last_name and user.last_name.lower().replace("ё", "е") in words:
                return user
        return None

    def plan(self) -> list[ItemPlan]:
        plans: list[ItemPlan] = []
        referenced: set[int] = set()

        for r in sorted(self.reserv_rows, key=lambda r: int(r.get("id") or 0)):
            rid = str(r.get("id") or "").strip()
            status = (r.get("status") or "").strip()
            if status not in RESERV_STAGE:
                self.report.skipped["резервы без склада (старые записи, в старой системе не видны)"] += 1
                continue
            if "стоп" in (r.get("reserv") or "").lower():
                self.report.skipped["резервы со «СТОП»"] += 1
                continue
            refs = t.order_refs(r.get("product_name") or "")
            referenced.update(refs)
            if self.existing[rid]:
                self.report.skipped["уже перенесено раньше (резервы)"] += 1
                continue
            plan = self._from_reserv(r, refs)
            for ref in refs:
                key = f"{ref}/ЗАК"
                if self.existing[key]:
                    self.report.conflicts.append(
                        f"резерв {rid}: заказ {key} уже перенесён отдельным изделием — в новую базу не добавлено"
                    )
                    plan = None
                    break
            if plan:
                plans.append(plan)

        for oid, o in sorted(self.orders.items()):
            created = t.unix_date(o.get("add_date"))
            if not created or created < self.since:
                continue
            if (o.get("shipped") or "").strip() == "on":
                continue
            if oid in referenced:
                continue
            key = f"{oid}/ЗАК"
            if any(CANCELLED.search(t.clean(o.get(f))) for f in ("add_comment", "price", "advanced", "tex_comment")):
                self.report.skipped["заказы, снятые (в комментарии «снят»/«отмена»)"] += 1
                continue
            if t.unix_date(o.get("cut_date")):
                self.report.cut_without_unit.append(key)
                continue
            qty = t.quantity(o.get("goods_name") or "")
            have = self.existing[key]
            if have >= qty:
                self.report.skipped["уже перенесено раньше (заказы)"] += 1
                continue
            for index in range(have, qty):
                plans.append(self._from_order(o, key, index))

        new_team_names: dict[str, str] = {}
        for p in plans:
            self.report.stages[p.stage] += 1
            if not p.stage_date:
                self.report.no_date += 1
            if p.manager_name and not self._resolve_manager(p.manager_name):
                self.report.unknown_managers[p.manager_name] += 1
            key = first_word(p.team_name)
            if key and key not in self.teams:
                new_team_names.setdefault(key, t.clean(p.team_name))
                self.report.new_teams[new_team_names[key]] += 1
        return plans

    def _from_reserv(self, r: dict, refs: list[int]) -> ItemPlan:
        rid = str(r["id"]).strip()
        order = next((self.orders[n] for n in refs if n in self.orders), None)
        if refs:
            self.report.linked += 1
        legacy = SEP.join([rid] + [f"{n}/ЗАК" for n in refs])
        original = t.clean(r.get("product_name"))
        model, custom, extra = self._name(original)
        stage = RESERV_STAGE[r["status"].strip()]
        sew, ready = t.sewing_dates(r.get("comment") or "")
        reserve = t.clean(r.get("reserv"))
        work = t.text_date(r.get("work_datetime"))
        store = t.text_date(r.get("store_date"))

        manager_name = t.clean(order.get("goods_man")) if order else ""
        created = t.unix_date(order.get("add_date")) if order else None
        cut = t.unix_date(order.get("cut_date")) if order else None
        # дата в названии («Клинт диван16,10,26») — когда изделие отметили в резервах
        name_date = t.text_date(original)
        known = [d for d in (created, cut, sew, ready, work, store, name_date) if d]
        created = created or (min(known) if known else None)
        stage_date = {
            Stage.CUT: cut or created,
            Stage.COVER: ready or sew or name_date,
            Stage.WORK: work or name_date,
            Stage.FG: store or work or name_date,
        }[stage]

        plan = ItemPlan(
            number=rid,
            seq=int(rid),
            legacy_number=legacy[:40],
            source=f"резервы {rid}",
            original_name=original,
            model=model,
            custom_name=custom,
            extra=extra,
            reserve=reserve[:300],
            stage=stage,
            manager_name=manager_name,
            created=created,
            reserved=t.text_date(r.get("reserv_date")) if reserve else None,
            stage_date=stage_date,
            fabric_arrived=t.unix_date(order.get("tex_date")) if order else None,
            sew=sew,
            cover_ready=ready,
            work=work if stage in (Stage.WORK, Stage.FG) else None,
            team_name=t.clean(r.get("work_date")),
        )
        order_meters = {}
        if order:
            for col, slot in ORDER_SLOTS:
                order_meters[slot] = (t.fabric_key(t.fabric_name(order.get(col))), self._meters(order.get(col + "_m")))
        for col, slot in RESERV_SLOTS:
            f = self._fabric(r.get(col), slot)
            if f:
                key, meters = order_meters.get(slot, ("", None))
                if key and key == t.fabric_key(f.name):
                    f.meters = meters
                plan.fabrics.append(f)
        self._skin(plan, r.get("skin"))

        comment = t.clean(r.get("comment"))
        if comment and not (sew and ready and t.only_sewing(comment)):
            plan.notes.append(comment)
        if order:
            plan.notes += self._order_notes(order)
        return plan

    def _from_order(self, o: dict, key: str, index: int = 0) -> ItemPlan:
        original = t.clean(o.get("goods_name"))
        model, custom, extra = self._name(original, is_order=True)
        reserve = t.clean(o.get("goods_ip"))
        created = t.unix_date(o.get("add_date"))
        oid = int(o["order_id"])
        plan = ItemPlan(
            number=key if index == 0 else f"{key}-{index + 1}",
            # отдельный диапазон, чтобы не совпасть с номерами из резервов
            seq=ORDER_SEQ_BASE + oid * 100 + index,
            legacy_number=key,
            source=f"заказы {key}",
            original_name=original,
            model=model,
            custom_name=custom,
            extra=extra,
            reserve=reserve[:300],
            stage=Stage.ORDERS if reserve else Stage.CUT,
            manager_name=t.clean(o.get("goods_man")),
            created=created,
            reserved=created if reserve else None,
            stage_date=created,
            fabric_arrived=t.unix_date(o.get("tex_date")),
        )
        for col, slot in ORDER_SLOTS:
            f = self._fabric(o.get(col), slot, self._meters(o.get(col + "_m")))
            if f:
                plan.fabrics.append(f)
        self._skin(plan, o.get("goods_skin"), self._meters(o.get("goods_skin_m")))
        if t.quantity(original) > 1:
            plan.notes.append("В старом заказе несколько штук — каждая заведена отдельным изделием")
        plan.notes += self._order_notes(o)
        if (o.get("tex_none") or "").strip() == "on":
            plan.notes.append("В старой системе отмечено: ткань отсутствует")
        return plan

    def _skin(self, plan: ItemPlan, value, meters=None) -> None:
        """Кожзам в новой системе — не отдельное место: в свободный компаньон, иначе в комментарий."""
        name = t.fabric_name(value)
        if not name:
            return
        taken = {f.slot for f in plan.fabrics}
        free = next((s for s in (FabricSlot.COMP1, FabricSlot.COMP2) if s not in taken), None)
        if free:
            f = self._fabric(value, free, meters)
            plan.fabrics.append(f)
        else:
            plan.notes.append(f"Кожзам: {name}")

    @staticmethod
    def _order_notes(o: dict) -> list[str]:
        notes = []
        for label, col in (("Комментарий менеджера", "price"), ("Комментарий", "add_comment"), ("Дополнительно", "advanced")):
            value = t.clean(o.get(col))
            if value and value not in t.EMPTY and not value.isdigit():
                notes.append(f"{label}: {value}")
        return notes

    @transaction.atomic
    def apply(self, plans: list[ItemPlan]) -> list[Item]:
        if not plans:
            return []
        legacy_user = self._legacy_user()
        now = timezone.now()
        items = []
        events: list[tuple[ItemEvent, datetime]] = []
        for plan in sorted(plans, key=self._order_key):
            manager = self._resolve_manager(plan.manager_name) or legacy_user
            created = aware(plan.created) or now
            team = self._team(plan.team_name)
            item = Item.objects.create(
                period=LEGACY_PERIOD,
                seq=plan.seq,
                number=plan.number,
                legacy_number=plan.legacy_number,
                model=plan.model,
                custom_name=plan.custom_name if not plan.model else "",
                extra=plan.extra[:500],
                comment="\n".join(plan.notes)[:5000],
                reserve=plan.reserve,
                reserved_at=aware(plan.reserved) or (created if plan.reserve else None),
                stage=plan.stage,
                stage_since=aware(plan.stage_date) or now,
                team=team,
                fabric_arrived_at=plan.fabric_arrived,
                sew_at=plan.sew or (plan.cover_ready if plan.stage != Stage.CUT else None),
                cover_ready_at=plan.cover_ready,
                work_at=plan.work,
                manager=manager,
                created_at=created,
            )
            seen = set()
            fabrics = []
            for f in plan.fabrics:
                if f.slot in seen:
                    continue
                seen.add(f.slot)
                fabrics.append(ItemFabric(item=item, slot=f.slot, fabric=self._fabric_obj(f.name), meters=f.meters))
            ItemFabric.objects.bulk_create(fabrics)
            events += self._events(item, plan, legacy_user, created, now)
            items.append(item)
        created_events = ItemEvent.objects.bulk_create([e for e, _ in events])
        for event, (_, at) in zip(created_events, events):
            event.at = at
        ItemEvent.objects.bulk_update(created_events, ["at"], batch_size=500)
        return items

    @staticmethod
    def _order_key(plan: ItemPlan):
        return (plan.created or date.max, plan.legacy_number)

    def _events(self, item, plan: ItemPlan, user, created, now):
        def ev(kind, text, at, **data):
            return (ItemEvent(item=item, user=user, kind=kind, text=text[:500], data={"legacy": True, **data}), at)

        out = [ev(EventKind.CREATED, f"Заведено в старой системе ({plan.source}): «{plan.original_name}»", created)]
        if plan.fabric_arrived:
            out.append(ev(EventKind.FABRIC, "Ткань пришла", aware(plan.fabric_arrived)))
        if plan.sew:
            out.append(ev(EventKind.SEW, "Выдано в шитьё", aware(plan.sew)))
        if plan.cover_ready:
            out.append(ev(EventKind.COVER_READY, "Отшит", aware(plan.cover_ready)))
        if plan.work:
            text = "→ В работе" + (f", бригада {item.team.name}" if item.team else "")
            out.append(ev(EventKind.MOVE, text, aware(plan.work), to=Stage.WORK))
        if plan.reserve and plan.reserved:
            out.append(ev(EventKind.RESERVE, f"Резерв: «{plan.reserve}»", aware(plan.reserved)))
        out.append(ev(EventKind.EDIT, f"Перенесено из старой системы → {stage_label(plan.stage)}", now))
        return out

    def _legacy_user(self):
        user, made = User.objects.get_or_create(
            username=LEGACY_USER, defaults={"last_name": "Старая система", "first_name": "", "is_active": False}
        )
        if made:
            user.set_unusable_password()
            user.save(update_fields=["password"])
        return user

    def _team(self, name: str):
        key = first_word(name)
        if not key:
            return None
        team = self.teams.get(key)
        if team is None:
            team, _ = Team.objects.get_or_create(name=t.clean(name)[:120], defaults={"foreman": t.clean(name)[:120]})
            self.teams[key] = team
        return team

    def _fabric_obj(self, name: str) -> Fabric:
        fabric, _ = self.fabrics.find(name)
        if fabric is None:
            fabric = Fabric.objects.create(name=name, active=False)
            self.fabrics.add(fabric)
        return fabric


def aware(d: date | None) -> datetime | None:
    if not d:
        return None
    return timezone.make_aware(datetime.combine(d, time(12, 0)))
