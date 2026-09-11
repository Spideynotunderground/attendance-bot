"""Russian dates and plural forms.

Formatted by hand rather than through strftime/locale: a container rarely has
a Russian locale installed, and strftime would silently fall back to English.
"""

WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня",
              "июля", "августа", "сентября", "октября", "ноября", "декабря"]
MONTHS_SHORT = ["янв", "фев", "мар", "апр", "мая", "июн",
                "июл", "авг", "сен", "окт", "ноя", "дек"]


def plural(n: int, one: str, few: str, many: str) -> str:
    """plural(5, "день", "дня", "дней") -> "дней"."""
    n = abs(n)
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def days(n: int) -> str:
    return f"{n} {plural(n, 'день', 'дня', 'дней')}"


def school_days(n: int) -> str:
    return f"{n} {plural(n, 'учебный день', 'учебных дня', 'учебных дней')}"


def date_long(d) -> str:
    """11 сентября 2026"""
    return f"{d.day} {MONTHS_GEN[d.month - 1]} {d.year}"


def day_full(d) -> str:
    """Пятница, 11 сентября 2026"""
    return f"{WEEKDAYS[d.weekday()].capitalize()}, {date_long(d)}"


def date_short(d, year: bool = True) -> str:
    """11 сен 2026"""
    text = f"{d.day} {MONTHS_SHORT[d.month - 1]}"
    return f"{text} {d.year}" if year else text


def stamp(dt) -> str:
    """11 сен 2026, 10:40"""
    return f"{date_short(dt)}, {dt.strftime('%H:%M')}"
