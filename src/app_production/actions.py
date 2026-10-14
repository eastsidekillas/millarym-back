from app_auth.permissions import no_right_message

from .models import Item, Stage
from .services import MOVE_RIGHT, NEXT, stage_label


def _action(user, code: str, label: str, right: str, **extra) -> dict:
    allowed = user.has_perm(f"app_auth.{right}")
    return {
        "code": code,
        "label": label,
        "allowed": allowed,
        "reason": "" if allowed else no_right_message(right),
        **extra,
    }


def available_actions(user, item: Item) -> list[dict]:
    if item.in_trash:
        return [_action(user, "restore", "Восстановить", "restore")]

    actions = []
    nxt = NEXT.get(item.stage)
    if nxt:
        actions.append(
            _action(
                user,
                "move",
                f"→ {stage_label(nxt)}",
                MOVE_RIGHT[nxt],
                to=nxt,
                needs_team=nxt == Stage.WORK,
            )
        )
    if item.stage == Stage.ORDERS and not item.fabric_arrived_at:
        actions.append(_action(user, "fabric_arrived", "Ткань пришла", "marks"))
    if item.stage == Stage.CUT:
        if not item.sew_at:
            actions.append(_action(user, "sew", "В шитьё", "marks"))
        if not item.cover_ready_at:
            actions.append(_action(user, "cover_ready", "Чехол готов", "marks"))
    if item.stage == Stage.FG:
        actions.append(_action(user, "ship", "Отгрузить", "ship"))
        actions.append(_action(user, "return_to_work", "↩ Вернуть в работу", "return_to_work"))
    actions += [
        _action(user, "move_any", "Переместить в…", "move_any"),
        _action(user, "reserve", "Резерв", "reserve"),
        _action(user, "edit", "Изменить", "edit"),
        _action(user, "copy", "Копировать", "edit"),
        _action(user, "trash", "Удалить", "trash"),
    ]
    return actions
