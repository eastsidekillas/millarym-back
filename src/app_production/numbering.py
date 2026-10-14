from django.db import transaction
from django.utils import timezone

from .models import NumberSequence


def take_numbers(qty: int) -> tuple[int, list[int]]:
    period = timezone.localdate().year
    with transaction.atomic():
        NumberSequence.objects.get_or_create(period=period)
        sequence = NumberSequence.objects.select_for_update().get(period=period)
        start = sequence.last_value + 1
        sequence.last_value += qty
        sequence.save(update_fields=["last_value"])
    return period, list(range(start, start + qty))
