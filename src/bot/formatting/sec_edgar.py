"""SpaceX SEC EDGAR filing messages."""

from __future__ import annotations

import html
from datetime import datetime

from src.bot.formatting._common import TAG_COMMON, fmt_utc, hashtag_line


_TAGS_SEC_EDGAR = (TAG_COMMON, "#SEC", "#SPCX")

# Russian names of the posted form types (amendments, "/A", are labelled as
# such); unknown forms are shown by their code alone.
_FORMS = {
    "8-K": "Существенное событие",
    "10-Q": "Квартальный отчёт",
    "10-K": "Годовой отчёт",
    "NT 10-Q": "Уведомление о задержке квартального отчёта",
    "NT 10-K": "Уведомление о задержке годового отчёта",
    "S-1": "Регистрация ценных бумаг",
    "S-3": "Регистрация ценных бумаг (упрощённая)",
}
_PROSPECTUS = "Проспект выпуска"  # 424B1 … 424B8

# 8-K item codes (Form 8-K General Instructions); unknown codes are shown as
# the bare number.
_ITEMS = {
    "1.01": "Заключение существенного соглашения",
    "1.02": "Расторжение существенного соглашения",
    "1.03": "Банкротство или внешнее управление",
    "1.04": "Безопасность на шахтах",
    "1.05": "Существенный инцидент кибербезопасности",
    "2.01": "Завершение приобретения или продажи активов",
    "2.02": "Результаты деятельности и финансовое положение",
    "2.03": "Новое прямое финансовое обязательство",
    "2.04": "Ускорение погашения финансового обязательства",
    "2.05": "Затраты на выход из бизнеса или продажу активов",
    "2.06": "Существенное обесценение активов",
    "3.01": "Уведомление о делистинге",
    "3.02": "Продажа незарегистрированных акций",
    "3.03": "Изменение прав держателей ценных бумаг",
    "4.01": "Смена аудитора",
    "4.02": "Отказ от ранее опубликованной отчётности",
    "5.01": "Смена контроля над компанией",
    "5.02": "Уход или назначение директоров и руководителей",
    "5.03": "Изменение устава или финансового года",
    "5.04": "Приостановка торговли в пенсионных планах",
    "5.05": "Изменение кодекса этики",
    "5.06": "Изменение статуса компании-оболочки",
    "5.07": "Итоги голосования акционеров",
    "5.08": "Выдвижение директоров акционерами",
    "7.01": "Раскрытие по Regulation FD",
    "8.01": "Прочие события",
    "9.01": "Финансовая отчётность и приложения",
}


def _form_name(form: str) -> str:
    """``"10-Q/A"`` -> ``"Квартальный отчёт (поправка)"``; ``""`` if unknown."""
    base, amended = (form[:-2], True) if form.endswith("/A") else (form, False)
    name = _PROSPECTUS if base.startswith("424B") else _FORMS.get(base, "")
    if name and amended:
        name += " (поправка)"
    return name


def _fmt_iso_date(value: str) -> str:
    """Format an ISO date (``2026-08-14``) as ``14.08.2026``; other text is kept."""
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%d.%m.%Y")
    except ValueError:
        return value


def _fmt_accepted(value: str) -> str:
    """``2026-08-14T12:23:02.000Z`` -> ``14.08.2026 12:23 UTC``; other text is kept."""
    try:
        return fmt_utc(value)
    except ValueError:
        return value


def _link(url: str, text: str) -> str:
    return f'<a href="{html.escape(url, quote=True)}">{html.escape(text)}</a>'


def format_sec_edgar_filing(item: dict) -> str:
    """Format a new SpaceX SEC EDGAR filing into a Russian HTML string.

    Shows the form and its Russian name, the 8-K items it reports, when it
    was filed, the event date (8-K) or period end (10-Q/10-K), and links to
    the primary document and the filing's index page. All site-supplied text
    is passed through ``html.escape``.
    """
    def _field(key: str) -> str:
        return str(item.get(key) or "").strip()

    form = _field("form")
    parts = ["<b>🏛 SEC EDGAR: новая отчётность SpaceX</b>"]
    if form:
        name = _form_name(form)
        parts.append(f"<b>{html.escape(form + (f' — {name}' if name else ''))}</b>")

    codes = [c for c in _field("items").split(",") if c]
    if codes:
        lines = ["<b>Пункты 8-K:</b>"]
        for code in codes:
            name = _ITEMS.get(code)
            lines.append(f"• {html.escape(code)}" + (f" — {name}" if name else ""))
        parts.append("\n".join(lines))

    details = []
    description = _field("description")
    if description and description.upper() != form.upper():
        details.append(f"<b>Описание:</b> {html.escape(description)}")
    accepted = _field("acceptance_datetime")
    filed = _fmt_accepted(accepted) if accepted else _fmt_iso_date(_field("filing_date"))
    if filed:
        details.append(f"<b>Подана:</b> {html.escape(filed)}")
    report_date = _field("report_date")
    base_form = form.removesuffix("/A")
    if report_date and base_form == "8-K":
        details.append(f"<b>Дата события:</b> {html.escape(_fmt_iso_date(report_date))}")
    elif report_date and base_form in ("10-Q", "10-K"):
        details.append(
            f"<b>Отчётный период до:</b> {html.escape(_fmt_iso_date(report_date))}"
        )
    if details:
        parts.append("\n".join(details))

    links = []
    document_url = _field("document_url")
    if document_url:
        links.append(_link(document_url, "Открыть документ"))
    index_url = _field("index_url")
    if index_url:
        links.append(_link(index_url, "Все файлы"))
    if links:
        parts.append(" | ".join(links))

    form_tag = "".join(ch for ch in base_form if ch.isalnum())
    parts.append(hashtag_line(*_TAGS_SEC_EDGAR, f"#{form_tag}" if form_tag else ""))

    return "\n\n".join(parts)
