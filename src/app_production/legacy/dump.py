"""Чтение строк из дампа phpMyAdmin (MySQL) без сервера MySQL."""

import re
from pathlib import Path

INSERT = re.compile(r"INSERT INTO `(\w+)` \(([^)]*)\) VALUES\s*")
BARE = re.compile(r"[^,)]+")
ESCAPES = {"n": "\n", "r": "\r", "t": "\t", "0": "\0", "Z": "\x1a"}


class DumpError(Exception):
    pass


def _rows(text: str, i: int) -> tuple[list[list[str | None]], int]:
    rows = []
    try:
        while True:
            while text[i] in " \r\n\t,":
                i += 1
            if text[i] == ";":
                return rows, i + 1
            if text[i] != "(":
                raise DumpError(f"не разобрать дамп около: {text[i:i + 40]!r}")
            i += 1
            row: list[str | None] = []
            while True:
                while text[i] in " \r\n\t":
                    i += 1
                if text[i] == "'":
                    i += 1
                    buf = []
                    while True:
                        c = text[i]
                        if c == "\\":
                            buf.append(ESCAPES.get(text[i + 1], text[i + 1]))
                            i += 2
                        elif c == "'" and text[i + 1] == "'":
                            buf.append("'")
                            i += 2
                        elif c == "'":
                            i += 1
                            break
                        else:
                            buf.append(c)
                            i += 1
                    row.append("".join(buf))
                else:
                    m = BARE.match(text, i)
                    token = m.group(0).strip()
                    i = m.end()
                    row.append(None if token.upper() == "NULL" else token)
                while text[i] in " \r\n\t":
                    i += 1
                if text[i] == ",":
                    i += 1
                    continue
                if text[i] == ")":
                    i += 1
                    break
                raise DumpError(f"не разобрать дамп около: {text[i:i + 40]!r}")
            rows.append(row)
    except IndexError:
        raise DumpError("дамп обрывается на середине — файл выгружен не полностью") from None


def read_tables(path: str | Path, tables: set[str]) -> dict[str, list[dict]]:
    """Строки нужных таблиц как словари {колонка: значение}."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    result: dict[str, list[dict]] = {t: [] for t in tables}
    pos = 0
    while m := INSERT.search(text, pos):
        table = m.group(1)
        columns = [c.strip(" `") for c in m.group(2).split(",")]
        rows, pos = _rows(text, m.end())
        if table in tables:
            result[table].extend(dict(zip(columns, row)) for row in rows)
    return result
