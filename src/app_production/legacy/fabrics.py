"""Сопоставление тканей из старых баз со справочником.

В старых базах ткань — имя файла фото («manila 01 001.jpg», «kioto dove (4).jpg»), а в справочнике фото
загружены с нормальными названиями («Manila 01», «Kioto 4 dove»). Поэтому сначала ищем точное совпадение,
потом — по сути названия без служебных хвостов, потом — те же слова в другом порядке, и последним —
с одной опечаткой в слове («safary chestnut» → «Safary chesnut»), если такая ткань одна.
"""

import re
from collections import defaultdict

from . import text as t

NOISE_TOKEN = re.compile(r"^(\d+[kpfeк]|web|\d+x\d+|00\d|\d{8})$")


def _words(name: str, keep_numbered: bool) -> list[str]:
    s = t.clean(name).lower().replace("ё", "е")
    s = re.sub(r"\.(jpe?g|png|gif|webp|bmp)\b", " ", s)
    if not keep_numbered:
        s = re.sub(r"\(\s*\d+\s*\)", " ", s)
    s = re.sub(r"[_\-.,()/+«»\"']", " ", s)
    words = []
    for token in s.split():
        if NOISE_TOKEN.match(token):
            continue
        for part in re.findall(r"[^\W\d]+|\d+", token):
            if part == "web":
                continue
            words.append(str(int(part)) if part.isdigit() else part)
    return words


def loose_key(name: str) -> str:
    return " ".join(_words(name, keep_numbered=False))


def set_key(name: str) -> tuple[str, ...]:
    """«kioto dove (4)» и «Kioto 4 dove» — одни и те же слова в другом порядке."""
    return tuple(sorted(_words(name, keep_numbered=True)))


def _one_typo(a: str, b: str) -> bool:
    if a == b or a.isdigit() or b.isdigit() or min(len(a), len(b)) < 4 or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        diff = [i for i in range(len(a)) if a[i] != b[i]]
        return len(diff) == 1 or (len(diff) == 2 and diff[1] == diff[0] + 1 and a[diff[0]] == b[diff[1]] and a[diff[1]] == b[diff[0]])
    short, long_ = sorted((a, b), key=len)
    return any(long_[:i] + long_[i + 1:] == short for i in range(len(long_)))


def _near(key: tuple[str, ...], other: tuple[str, ...]) -> bool:
    if len(key) != len(other):
        return False
    rest_a, rest_b = list(key), list(other)
    for word in key:
        if word in rest_b:
            rest_a.remove(word)
            rest_b.remove(word)
    return len(rest_a) == 1 and _one_typo(rest_a[0], rest_b[0])


class FabricMatcher:
    def __init__(self, fabrics):
        self.exact = {}
        self.loose = defaultdict(list)
        self.sets = defaultdict(list)
        for f in fabrics:
            self.add(f)

    def add(self, fabric) -> None:
        self.exact.setdefault(t.fabric_key(fabric.name), fabric)
        key = loose_key(fabric.name)
        if key and fabric not in self.loose[key]:
            self.loose[key].append(fabric)
        words = set_key(fabric.name)
        if words and fabric not in self.sets[words]:
            self.sets[words].append(fabric)

    def find(self, name: str):
        """(ткань или None, True — нашлась только по похожему названию)."""
        fabric = self.exact.get(t.fabric_key(name))
        if fabric:
            return fabric, False
        words = set_key(name)
        for candidates in (
            self.loose.get(loose_key(name), []),
            self.sets.get(words, []),
            [f for key, fabrics in self.sets.items() if _near(words, key) for f in fabrics],
        ):
            if len(candidates) > 1:
                # несколько похожих — берём ту, что с фото или в справочнике, если такая одна
                candidates = [f for f in candidates if f.photo or f.active]
            if len(candidates) == 1:
                return candidates[0], True
            if candidates:
                return None, False
        return None, False
