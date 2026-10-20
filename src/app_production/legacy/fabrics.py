"""Сопоставление тканей из старых баз со справочником.

В старых базах ткань — имя файла фото («manila 01 001.jpg», «kioto dove (4).jpg»), а в справочнике фото
загружены с нормальными названиями («Manila 01», «Kioto Dove»). Поэтому сначала ищем точное совпадение,
потом — по сути названия без служебных хвостов.
"""

import re
from collections import defaultdict

from . import text as t

NOISE_TOKEN = re.compile(r"^(\d+[kpfeк]|web|\d+x\d+|00\d|\d{8})$")


def loose_key(name: str) -> str:
    s = t.clean(name).lower().replace("ё", "е")
    s = re.sub(r"\.(jpe?g|png|gif|webp|bmp)\b", " ", s)
    s = re.sub(r"\(\s*\d+\s*\)", " ", s)
    s = re.sub(r"[_\-.,()/+«»\"']", " ", s)
    words = []
    for token in s.split():
        if NOISE_TOKEN.match(token):
            continue
        for part in re.findall(r"[^\W\d]+|\d+", token):
            words.append(str(int(part)) if part.isdigit() else part)
    return " ".join(words)


class FabricMatcher:
    def __init__(self, fabrics):
        self.exact = {}
        self.loose = defaultdict(list)
        for f in fabrics:
            self.add(f)

    def add(self, fabric) -> None:
        self.exact.setdefault(t.fabric_key(fabric.name), fabric)
        key = loose_key(fabric.name)
        if key and fabric not in self.loose[key]:
            self.loose[key].append(fabric)

    def find(self, name: str):
        """(ткань или None, True — нашлась только по похожему названию)."""
        fabric = self.exact.get(t.fabric_key(name))
        if fabric:
            return fabric, False
        candidates = self.loose.get(loose_key(name), [])
        if len(candidates) > 1:
            # несколько похожих — берём ту, что с фото или в справочнике, если такая одна
            candidates = [f for f in candidates if f.photo or f.active]
        if len(candidates) == 1:
            return candidates[0], True
        return None, False
