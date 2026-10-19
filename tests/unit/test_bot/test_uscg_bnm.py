"""Tests for USCG BNM formatting, card data, posting and prefill."""

from __future__ import annotations

import pytest

import prefill_uscg_bnm
from src.bot.formatting import format_uscg_bnm_notice
from src.bot.orchestrator import posting, uscg_bnm
from src.core import config
from src.data.uscg_bnm_repo import uscg_bnm_notices
from src.visualization.image_composer.card_data import bnm_card_data


def _safety(bnm_id="CGD-H BNM 0108-26", published="2026-09-25T18:24:01Z", **extra):
    return {
        "notice_key": f"SAFETY {bnm_id}",
        "bnm_id": bnm_id,
        "kind": "SAFETY",
        "region": "TX - GULF OF AMERICA - CARIBBEAN SEA",
        "title": "",
        "flight": "14",
        "mission": "STARSHIP FLIGHT 14",
        "starship": True,
        "areas": [
            {"label": "HIGH RISK HAZARD AREA", "coords": [[25.2, -92.9], [25.5, -93.8], [24.7, -92.7]]},
            {"label": "HAZARD AREA", "coords": [[25.9, -97.2], [26.0, -97.2], [19.3, -78.0]]},
        ],
        "windows": [
            ["2026-09-28T12:15:00Z", "2026-09-28T14:14:00Z"],
            ["2026-09-30T23:15:00Z", "2026-10-01T01:22:00Z"],
        ],
        "cancel_at": "2026-10-04T15:14:00Z",
        "cancels": "",
        "outcome": "",
        "published_at": published,
        "link": "https://content.govdelivery.com/accounts/USDHSCG/bulletins/42c8bcc",
        **extra,
    }


def _cancellation(bnm_id="CGD-SE BNM 9076-26", outcome="STARSHIP FLIGHT 14, SUCCESSFUL LAUNCH",
                  published="2026-09-29T16:14:59Z", **extra):
    return {
        **_safety(bnm_id, published),
        "notice_key": f"CANCELLATION {bnm_id}",
        "kind": "CANCELLATION",
        "areas": [],
        "windows": [],
        "cancel_at": "",
        "cancels": bnm_id,
        "outcome": outcome,
        **extra,
    }


# --- formatting ---------------------------------------------------------------


def test_format_safety_notice():
    text = format_uscg_bnm_notice(_safety())

    assert text.startswith("<b>⚓ Оповещение мореплавателям USCG</b>")
    assert "<b>Starship Flight 14</b>" in text
    assert "<b>Номер:</b> CGD-H BNM 0108-26 (Округ Heartland)" in text
    assert "<b>Район:</b> TX - GULF OF AMERICA - CARIBBEAN SEA" in text
    assert "<b>Зоны:</b> A — зона высокого риска, B — опасная зона" in text
    assert "• 28.09.2026 12:15–14:14" in text
    assert "• 30.09.2026 23:15–01.10.2026 01:22" in text  # crosses midnight
    assert '>Текст оповещения</a>' in text
    assert text.endswith("#SpaceUpdates #BNM #Starship #Flight14")
    assert len(text) <= 1024  # sent as a photo caption


def test_format_safety_limits_windows():
    windows = [["2026-09-%02dT12:15:00Z" % d, "2026-09-%02dT14:14:00Z" % d] for d in range(1, 15)]
    text = format_uscg_bnm_notice(_safety(windows=windows))

    assert text.count("• ") == 10
    assert "… и ещё 4" in text


def test_format_cancellation_translates_outcome():
    text = format_uscg_bnm_notice(_cancellation())

    assert "<b>⚓ Оповещение мореплавателям USCG отменено</b>" in text
    assert "<b>Отменено:</b> CGD-SE BNM 9076-26 (Округ Southeast)" in text
    assert "<b>Итог:</b> Starship Flight 14 — успешный запуск" in text
    assert "Окна" not in text


def test_format_cancellation_keeps_unknown_outcome():
    text = format_uscg_bnm_notice(
        _cancellation(outcome="STARSHIP FLIGHT 14, <MISSION COMPLETE>")
    )

    assert "<b>Итог:</b> STARSHIP FLIGHT 14, &lt;MISSION COMPLETE&gt;" in text


def test_card_data_keeps_areas_as_separate_polygons():
    card = bnm_card_data(_safety())

    assert card["title"] == "ОПОВЕЩЕНИЕ BNM"
    assert card["number"] == "BNM 0108-26"
    assert card["meta"] == "(ДЛЯ МОРСКОГО ТРАНСПОРТА) USCG CGD-H"
    assert card["details"] == "ОПАСНЫЕ ЗОНЫ ДЛЯ СУДОВ ПРИ ЗАПУСКЕ SPACEX STARSHIP FLT-14"
    assert card["coords"] == [
        [(25.2, -92.9), (25.5, -93.8), (24.7, -92.7)],
        [(25.9, -97.2), (26.0, -97.2), (19.3, -78.0)],
    ]
    assert card["windows"] == ["Сентябрь 28, 12:15 - 14:14", "Сентябрь 30, 23:15 - 01:22"]


# --- posting ------------------------------------------------------------------


@pytest.fixture
def bnm_env(initialized_db, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DB_PATH", initialized_db)
    monkeypatch.setattr(posting, "_SEND_PAUSE_SECONDS", 0)
    sent = []

    async def fake_send_message(chat_id, text):
        sent.append(("text", text))
        return len(sent)

    async def fake_send_photo(chat_id, path, caption=None):
        sent.append(("photo", caption))
        return len(sent)

    monkeypatch.setattr(posting, "send_message", fake_send_message)
    monkeypatch.setattr(posting, "send_photo", fake_send_photo)

    rendered = []

    def fake_plot(notice, out_path):
        rendered.append(notice["notice_key"])
        open(out_path, "wb").close()
        return out_path

    monkeypatch.setattr(uscg_bnm, "plot_bnm_notice", fake_plot)
    monkeypatch.setattr(uscg_bnm, "_MAPS_DIR", tmp_path / "maps")

    def set_feeds(*feeds):
        fetchers = []
        for feed in feeds:
            fetcher = type("F", (), {})()
            fetcher.fetch = (lambda f=feed: None if f is None else list(f))
            fetchers.append(fetcher)
        monkeypatch.setattr(uscg_bnm, "uscg_bnm_fetchers", fetchers)

    return sent, rendered, set_feeds


async def test_starship_notices_are_posted_in_issue_order_once(bnm_env, tmp_path):
    sent, rendered, set_feeds = bnm_env
    falcon = _safety("CGD-SE BNM 9079-26", starship=False, flight="", mission="CRS-35")
    heartland = [_safety()]
    southeast = [  # newest first, as the feed lists them
        _cancellation(),
        falcon,
        _safety("CGD-SE BNM 9076-26", published="2026-09-28T11:09:45Z"),
    ]
    set_feeds(heartland, southeast)

    await uscg_bnm.process_uscg_bnm_notices(["chat"])
    await uscg_bnm.process_uscg_bnm_notices(["chat"])

    assert [kind for kind, _ in sent] == ["photo", "photo", "text"]
    assert "CGD-H BNM 0108-26" in sent[0][1]
    assert "CGD-SE BNM 9076-26" in sent[1][1]
    assert "успешный запуск" in sent[2][1]
    assert rendered == ["SAFETY CGD-H BNM 0108-26", "SAFETY CGD-SE BNM 9076-26"]
    assert list((tmp_path / "maps").iterdir()) == []  # maps deleted after posting
    assert uscg_bnm_notices.known(["SAFETY CGD-SE BNM 9079-26"], config.DB_PATH) == set()


async def test_bare_cancellation_is_kept_only_for_a_stored_notice(bnm_env):
    sent, _, set_feeds = bnm_env
    bare = dict(starship=False, outcome="", flight="", mission="")
    set_feeds([
        _cancellation("CGD-H BNM 0108-26", published="2026-10-01T00:00:00Z", **bare),
        _cancellation("CGD-H BNM 0110-26", published="2026-10-02T00:00:00Z", **bare),
        _safety(),
    ])

    await uscg_bnm.process_uscg_bnm_notices(["chat"])

    assert len(sent) == 2
    assert "<b>Отменено:</b> CGD-H BNM 0108-26" in sent[1][1]


async def test_render_failure_falls_back_to_text(bnm_env, monkeypatch):
    sent, _, set_feeds = bnm_env

    def broken(notice, out_path):
        raise RuntimeError("cartopy")

    monkeypatch.setattr(uscg_bnm, "plot_bnm_notice", broken)
    set_feeds([_safety()])

    await uscg_bnm.process_uscg_bnm_notices(["chat"])

    assert [kind for kind, _ in sent] == ["text"]
    assert uscg_bnm_notices.needing_post(config.DB_PATH) == []


async def test_failed_feed_does_not_stop_the_others(bnm_env):
    sent, _, set_feeds = bnm_env
    set_feeds(None, [_safety()])

    await uscg_bnm.process_uscg_bnm_notices(["chat"])

    assert len(sent) == 1


# --- prefill ------------------------------------------------------------------


def test_prefill_marks_starship_notices_posted(bnm_env):
    sent, _, set_feeds = bnm_env
    set_feeds([_safety()], [_cancellation(), _safety("CGD-SE BNM 9079-26", starship=False)])

    assert uscg_bnm.prefill_uscg_bnm_notices() == 2
    assert uscg_bnm_notices.needing_post(config.DB_PATH) == []
    assert sent == []


def test_prefill_fails_when_a_feed_fails(bnm_env):
    _, _, set_feeds = bnm_env
    set_feeds([_safety()], None)

    with pytest.raises(RuntimeError):
        uscg_bnm.prefill_uscg_bnm_notices()


def test_prefill_script_if_empty_skips_known_table(bnm_env):
    _, _, set_feeds = bnm_env
    set_feeds([_safety()])
    assert prefill_uscg_bnm.main([]) == 0
    assert uscg_bnm_notices.count(config.DB_PATH) == 1

    set_feeds([_safety("CGD-H BNM 0200-26")])
    assert prefill_uscg_bnm.main(["--if-empty"]) == 0
    assert uscg_bnm_notices.count(config.DB_PATH) == 1


def test_prefill_script_reports_failure(bnm_env):
    _, _, set_feeds = bnm_env
    set_feeds(None)

    assert prefill_uscg_bnm.main([]) == 1
