import os
import asyncio
from typing import Optional
import html
from datetime import datetime, timezone, timedelta
import asyncio
import os

import telegram

from fetch_starbase_closures import get_starbase_status

# load environment from .env using python-dotenv
try:
    from dotenv import load_dotenv
    _dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
    load_dotenv(dotenv_path=_dotenv_path)
except Exception:
    # if dotenv isn't installed, environment variables must be set externally
    pass

from fetch_faa_advisory import parse_faa_advisory
from notam_logging import logger
from notam_request import search_notams_selenium
from notam_db import get_beach_alerts_needing_post, get_notams_needing_images, get_road_alerts_needing_post, get_road_alerts_needing_post, mark_beach_posted, mark_image_generated, init_db, get_faa_activities_needing_post, mark_faa_activity_posted, mark_road_posted, save_beach_alert, save_road_alert
import visualize_notams

from telegram import Bot, InputFile
from telegram.error import Forbidden
import json


TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
# support comma-separated list of chat ids
RAW_CHAT_IDS = os.environ.get('TELEGRAM_CHAT_ID', '')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')
CHAT_IDS = [c.strip() for c in RAW_CHAT_IDS.split(',') if c.strip()]
# path for persisting discovered chats and update offset
STATE_PATH = os.path.join(os.path.dirname(__file__), 'telegram_chats.json')

BOT = Bot(token=TELEGRAM_BOT_TOKEN)

DEST_TRANSLATION = {
    "Production": "Starfactory",
    "Pad": "Пусковые площадки",
    "Masseys": "Мэссис",
    "Huddleston": "Хаддлстон",
    "Port": "Порт"
}

def translate_place(name: str) -> str:
    if not name:
        return "Неизвестно"
    return DEST_TRANSLATION.get(name, name)


def _load_state():
    try:
        if os.path.exists(STATE_PATH):
            with open(STATE_PATH, 'r', encoding='utf-8') as fh:
                return json.load(fh)
    except Exception:
        logger.exception('Failed to load Telegram chats state')
    return {'chats': [], 'last_update_id': None}


def _save_state(state: dict):
    try:
        with open(STATE_PATH, 'w', encoding='utf-8') as fh:
            json.dump(state, fh)
    except Exception:
        logger.exception('Failed to save Telegram chats state')


def _get_combined_chat_ids():
    state = _load_state()
    persisted = [str(c) for c in state.get('chats', [])]
    # union of env-provided and persisted chat ids
    combined = list(dict.fromkeys(persisted + CHAT_IDS))
    return combined


KEYWORD = os.environ.get('NOTAM_KEYWORD', 'STARSHIP')
DB_PATH = os.environ.get('NOTAM_DB_PATH')
RUNS_PER_HOUR = int(os.getenv("RUNS_PER_HOUR", "2"))


async def async_send_photo(token: str, chat_id: str, photo_path: str, caption: Optional[str] = None) -> bool:
    try:
        bot = BOT
        with open(photo_path, 'rb') as fh:
            input_file = InputFile(fh)
            # send caption as HTML to allow basic formatting (bold, italics, links)
            logger.info(
                f'Caption text: {caption if caption else "(no caption)"}')
            await bot.send_photo(chat_id=chat_id, photo=input_file, caption=caption, parse_mode='HTML')
        return True
    except Forbidden as e:
        # Bot was blocked by the user or removed from the chat. Remove from persisted state
        try:
            state = _load_state()
            persisted = [str(c) for c in state.get('chats', [])]
            if str(chat_id) in persisted:
                persisted = [c for c in persisted if c != str(chat_id)]
                state['chats'] = persisted
                _save_state(state)
                logger.info(
                    f'Removed blocked chat {chat_id} from persisted Telegram state')
            else:
                logger.info(
                    f'Chat {chat_id} blocked the bot (not present in persisted state)')
        except Exception:
            logger.exception(
                'Failed to update persisted Telegram state after Forbidden error')
        logger.warning(
            f'Failed to send photo {photo_path} to {chat_id}: bot was blocked by the user')
        return False
    except Exception as e:
        logger.exception(
            f"Failed to send photo {photo_path} via python-telegram-bot to {chat_id}: {e}")
        return False


async def async_send_message(token: str, chat_id: str, text: str) -> Optional[int]:
    while True:
        try:
            bot = BOT
            message = await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode='HTML',
                disable_web_page_preview=True
            )
            return message.message_id
        except Forbidden:
            logger.warning(f'Bot blocked in chat {chat_id}')
            return None
        except telegram.error.TimedOut as e:
            logger.warning(f'Failed to send message to {chat_id}: Timed out')
        except Exception as e:
            logger.exception(f'Failed to send message to {chat_id}: {e}')
            return None


def ensure_setup():
    if not TELEGRAM_BOT_TOKEN:
        logger.error('TELEGRAM_BOT_TOKEN must be set in environment')
        raise SystemExit(1)
    # ensure DB exists/initialized
    init_db(DB_PATH)


async def refresh_known_chats():
    """Fetch recent updates and persist any new chat IDs the bot sees.

    This uses getUpdates to discover chats the bot is in. It stores
    discovered chat ids and the last processed update id to avoid
    re-processing the same updates repeatedly.
    """
    state = _load_state()
    last_update_id = state.get('last_update_id')
    bot = BOT
    try:
        # offset should be last_update_id + 1 to fetch only new updates
        offset = (last_update_id + 1) if (last_update_id is not None) else None
        updates = None
        while updates is None:
            try:
                updates = await bot.get_updates(timeout=30, offset=offset)
            except telegram.error.TimedOut:
                logger.warning('get_updates timed out; retrying')
                await asyncio.sleep(5)
            except Exception:
                logger.exception('Failed to get_updates from Telegram bot')
                return _get_combined_chat_ids()
        if not updates:
            return _get_combined_chat_ids()

        new_chats = set(str(c) for c in state.get('chats', []))
        max_update = last_update_id if last_update_id is not None else -1
        for upd in updates:
            try:
                # prefer message (normal), fallback to edited_message
                msg = getattr(upd, 'message', None) or getattr(
                    upd, 'edited_message', None)
                if msg and getattr(msg, 'chat', None):
                    new_chats.add(str(msg.chat.id))
                if hasattr(upd, 'update_id') and upd.update_id is not None:
                    if upd.update_id > max_update:
                        max_update = upd.update_id
            except Exception:
                logger.exception(
                    'Failed to parse update while refreshing chats')

        state['chats'] = list(new_chats)
        if max_update >= 0:
            state['last_update_id'] = max_update
        _save_state(state)
    except Exception:
        logger.exception(
            'Failed to refresh known Telegram chats via get_updates')
    return _get_combined_chat_ids()


def format_faa_activity(activity: dict) -> str:
    from datetime import datetime

    def convert_faa_time(s: str):
        # "06/24/26 0248Z-0531Z"
        date_part, times = s.split()
        start, end = times.split("-")

        dt = datetime.strptime(date_part, "%m/%d/%y")

        start_fmt = f"{start[:2]}:{start[2:]}"[:-1]  # remove trailing Z
        end_fmt = f"{end[:2]}:{end[2:]}"[:-1]  # remove trailing Z

        return f"{dt.strftime('%d.%m.%Y')} {start_fmt}–{end_fmt} UTC"

    mission = activity.get("mission", "Unknown mission")
    primary = activity.get("primary_window", "")
    backup = activity.get("backup_window", "")

    parts = []
    parts.append("<b>FAA Planned Activity</b>")
    parts.append(f"<b>Миссия:</b> {html.escape(mission)}")

    if primary:
        parts.append(
            f"<b>Основное окно:</b> {html.escape(convert_faa_time(primary))}")

    if backup:
        parts.append(
            f"<b>Запасное окно:</b> {html.escape(convert_faa_time(backup))}")

    return "\n\n".join(parts)


def format_road_alert(alert: dict) -> str:
    def fmt_time(iso_str: str):
        # expects ISO UTC like "2026-06-25T04:59:00+00:00"
        from datetime import datetime
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%d.%m.%Y %H:%M UTC")

    origin = translate_place(alert.get("origin"))
    destination = translate_place(alert.get("destination"))

    parts = []
    parts.append("<b>🚧 Ограничение движения</b>")
    parts.append(f"<b>Маршрут:</b> {html.escape(origin)} → {html.escape(destination)}")

    if alert.get("start_utc") and alert.get("end_utc"):
        parts.append(
            f"<b>Время:</b> {html.escape(fmt_time(alert['start_utc']))} – {html.escape(fmt_time(alert['end_utc']))}"
        )

    return "\n\n".join(parts)


def format_beach_alert(alert: dict) -> str:
    from datetime import datetime
    import html
    import json

    def fmt_time(iso_str: str):
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%d.%m.%Y %H:%M UTC")

    def period_text(period: dict) -> str:
        start_utc = period.get("start_utc")
        end_utc = period.get("end_utc")
        if start_utc and end_utc:
            return f"{fmt_time(start_utc)} – {fmt_time(end_utc)}"

        raw_date = period.get("raw_date")
        return html.escape(str(raw_date)) if raw_date else ""

    periods = alert.get("periods_json")

    if isinstance(periods, str):
        try:
            periods = json.loads(periods)
        except Exception:
            periods = []
    if not isinstance(periods, list):
        periods = []

    primary_period = periods[0] if periods else {
        "start_utc": alert.get("start_utc"),
        "end_utc": alert.get("end_utc"),
        "raw_date": alert.get("raw_date"),
    }
    secondary_period = periods[1] if len(periods) > 1 else None

    parts = []
    parts.append("<b>🏖️ Перекрытие пляжа</b>")

    primary_text = period_text(primary_period)
    if primary_text:
        parts.append(f"<b>Основной период:</b> {primary_text}")

    if secondary_period:
        secondary_text = period_text(secondary_period)
        if secondary_text:
            parts.append(f"<b>Запасной период:</b> {secondary_text}")

    return "\n\n".join(parts)


def build_notam_caption(name: str, parsed: dict) -> str:
    parts = []
    parts.append('<b>Новый NOTAM</b>')
    # display name/title: strip any trailing .json then replace underscores
    raw_name = str(name or '')
    if raw_name.lower().endswith('.json'):
        raw_name = raw_name[:-5]
    display_name = raw_name.replace('_', '/')
    parts.append(f"<b>Код NOTAM:</b> {html.escape(display_name)}")

    def _fmt_dt(s):
        if not s:
            return ''
        try:
            s_str = str(s).strip()
            if s_str.endswith('Z'):
                s_str = s_str[:-1]
            s_iso = s_str.replace('T', ' ')
            try:
                dt = datetime.fromisoformat(s_iso)
                if dt.tzinfo is not None:
                    dt_utc = dt.astimezone(timezone.utc)
                else:
                    dt_utc = dt
                return dt_utc.strftime('%d.%m.%Y %H:%M UTC')
            except Exception:
                return s_iso
        except Exception:
            return str(s)

    # Dates (B and C)
    b_fmt = _fmt_dt(parsed.get('B') or '')
    c_fmt = _fmt_dt(parsed.get('C') or '')
    if b_fmt or c_fmt:
        parts.append(f"<b>Даты:</b> {html.escape(b_fmt)} → {html.escape(c_fmt)}")

    # Details (E) as blockquote
    if parsed.get('E'):
        details_raw = parsed.get('E')
        details_clean = str(details_raw).replace('%0', ' ')
        details_escaped = html.escape(details_clean)
        parts.append('Подробности:')
        expandable_bq = f"<blockquote expandable>{details_escaped}</blockquote>"
        parts.append(expandable_bq)

    caption = '\n\n'.join(parts)
    if len(caption) > 1024:
        closing = '</blockquote>'
        if '<blockquote' in caption:
            truncated = caption[:1024 - len(closing)]
            return truncated + closing
        return caption[:1024]
    return caption


async def _refresh_notams_from_source() -> None:
    try:
        logger.info('Running NOTAM request for keyword: starship')
        await asyncio.to_thread(search_notams_selenium, 'starship')
        
        logger.info('Running NOTAM request for keyword: spacex brownsville')
        await asyncio.to_thread(search_notams_selenium, 'spacex brownsville')
    except Exception:
        logger.exception('NOTAM request failed')


async def _get_chat_list_with_fallback() -> list[str]:
    try:
        return await refresh_known_chats()
    except Exception:
        logger.exception('Failed to refresh known chats; falling back to env chat ids')
        return CHAT_IDS


async def _process_notam_images(chat_list: list[str]) -> None:
    pending = get_notams_needing_images(DB_PATH)
    if not pending:
        logger.info('No NOTAMs needing images at this time')
        return

    logger.info(f'Found {len(pending)} NOTAMs needing images')
    maps_dir = os.path.join(os.path.dirname(__file__), 'maps')
    os.makedirs(maps_dir, exist_ok=True)

    for name, parsed in pending:
        try:
            e_text = parsed.get('E') or ''
            coords = visualize_notams.parse_coords_from_text(e_text)
            if not coords:
                logger.info(f'No coords parsed for {name}; skipping image generation')
                # still mark as generated so it won't retry endlessly
                mark_image_generated(name, DB_PATH)
                continue

            outpath = os.path.join(maps_dir, f'{name}_map.png')
            try:
                # visualize_notams.plot_single_notam is blocking (matplotlib) — run in thread
                fname_display = f'{name}.json' if not str(name).lower().endswith('.json') else name
                await asyncio.to_thread(
                    visualize_notams.plot_single_notam,
                    fname_display,
                    parsed,
                    coords,
                    outpath,
                    None,
                )
                logger.info(f'Generated image for {name} -> {outpath}')
            except Exception:
                logger.exception(f'Failed to generate image for {name}')
                continue

            success_any = False
            caption = build_notam_caption(name, parsed)
            for chat_id in chat_list:
                try:
                    sent = await async_send_photo(
                        TELEGRAM_BOT_TOKEN,
                        chat_id,
                        outpath,
                        caption=caption,
                    )
                    if sent:
                        success_any = True
                    # small pause to reduce likelihood of rate limiting
                    await asyncio.sleep(0.2)
                except Exception:
                    logger.exception(f'Error sending image to chat {chat_id}')

            if success_any:
                logger.info(f'Sent image for {name} to Telegram; marking in DB and deleting file')
                try:
                    mark_image_generated(name, DB_PATH)
                except Exception:
                    logger.exception(f'Failed to mark image_generated for {name}')
                try:
                    os.remove(outpath)
                except Exception:
                    logger.exception(f'Failed to delete image {outpath}')
            else:
                logger.error(f'Failed to send image for {name} to any configured chat; keeping file for retry')

        except Exception:
            logger.exception(f'Unhandled error while processing {name}')


async def _process_faa_activities(chat_list: list[str]) -> None:
    logger.info('Refreshing FAA activities needing Telegram post')
    try:
        logger.info('Getting FAA activities')
        parse_faa_advisory()  # this will fetch and save any new activities to the DB
    except Exception:
        logger.exception('Failed to fetch and parse FAA advisory')

    faa_pending = get_faa_activities_needing_post(DB_PATH)
    if len(faa_pending) == 0:
        logger.info('No FAA activities needing Telegram post at this time')
        return

    logger.info(f'Found {len(faa_pending)} FAA activities needing post to Telegram')
    for activity in faa_pending:
        try:
            text = format_faa_activity(activity)

            message_ids = []
            for chat_id in chat_list:
                message_id = await async_send_message(
                    TELEGRAM_BOT_TOKEN,
                    chat_id,
                    text,
                )
                if message_id:
                    logger.info(f'Sent FAA activity to chat {chat_id}')
                    message_ids.append(message_id)
                else:
                    logger.warning(f'Failed to send FAA activity to chat {chat_id}')

                await asyncio.sleep(5)

            logger.info(f'Marking FAA activity as posted: {activity}')
            try:
                mark_faa_activity_posted(activity['mission'], ','.join(str(id) for id in message_ids), DB_PATH)
            except Exception as e:
                logger.exception(f'Failed to mark FAA activity as posted: {activity}, reason: {e}')

        except Exception:
            logger.exception(f'Failed to send FAA activity {activity}')


def _ingest_starbase_alerts() -> None:
    logger.info('Refreshing Starbase alerts needing Telegram post')
    try:
        logger.info('Fetching Starbase status')
        data = get_starbase_status()
        # ingest into DB
        if data.get('beach'):
            save_beach_alert(data['beach'])
        for r in data.get('road_delays', []):
            save_road_alert(r)
    except Exception:
        logger.exception('Failed to fetch and parse Starbase alerts')


async def _process_beach_alerts(chat_list: list[str]) -> None:
    beach_pending = get_beach_alerts_needing_post(DB_PATH)

    if len(beach_pending) == 0:
        logger.info('No beach alerts needing Telegram post')
        return

    logger.info(f'Found {len(beach_pending)} beach alerts to post')

    for alert in beach_pending:
        try:
            text = format_beach_alert(alert)
            message_ids = []
            for chat_id in chat_list:
                message_id = await async_send_message(
                    TELEGRAM_BOT_TOKEN,
                    chat_id,
                    text,
                )
                if message_id:
                    logger.info(f'Sent beach alert to chat {chat_id}')
                    message_ids.append(message_id)
                else:
                    logger.warning(f'Failed to send beach alert to chat {chat_id}')

                await asyncio.sleep(5)

            logger.info(f'Marking beach alert as posted: {alert}')

            try:
                mark_beach_posted(alert['alert_key'], DB_PATH)
            except Exception as e:
                logger.exception(f'Failed to mark beach alert: {alert}, reason: {e}')

        except Exception:
            logger.exception(f'Failed to send beach alert {alert}')

async def _process_road_alerts(chat_list: list[str]) -> None:
    road_pending = get_road_alerts_needing_post(DB_PATH)

    if len(road_pending) == 0:
        logger.info('No road alerts needing Telegram post')
        return

    logger.info(f'Found {len(road_pending)} road alerts to post')

    for alert in road_pending:
        try:
            text = format_road_alert(alert)
            message_ids = []
            for chat_id in chat_list:
                message_id = await async_send_message(
                    TELEGRAM_BOT_TOKEN,
                    chat_id,
                    text,
                )

                if message_id:
                    logger.info(f'Sent road alert to chat {chat_id}')
                    message_ids.append(message_id)
                else:
                    logger.warning(f'Failed to send road alert to chat {chat_id}')

                await asyncio.sleep(5)

            logger.info(f'Marking road alert as posted: {alert}')

            try:
                mark_road_posted(alert['alert_key'], DB_PATH)
            except Exception as e:
                logger.exception(f'Failed to mark road alert: {alert}, reason: {e}')

        except Exception:
            logger.exception(f'Failed to send road alert {alert}')

async def generate_and_send(chat_list: Optional[list[str]] = None) -> None:
    await _refresh_notams_from_source()
    chat_list = await _get_chat_list_with_fallback()
    await _process_notam_images(chat_list)
    await _process_faa_activities(chat_list)
    _ingest_starbase_alerts()
    await _process_beach_alerts(chat_list)
    await _process_road_alerts(chat_list)

async def sleep_until_next_run():
    interval_minutes = 60 / RUNS_PER_HOUR

    now = datetime.now()

    minutes_since_hour = now.minute + now.second / 60

    next_slot = (
        int(minutes_since_hour // interval_minutes) + 1
    ) * interval_minutes

    next_run = now.replace(minute=0, second=0, microsecond=0)

    if next_slot >= 60:
        next_run += timedelta(hours=1)
    else:
        next_run += timedelta(minutes=next_slot)

    sleep_seconds = (next_run - now).total_seconds()

    logger.info(
        f"Next run scheduled for {next_run:%Y-%m-%d %H:%M:%S} "
        f"(sleeping {sleep_seconds:.0f}s)"
    )

    await asyncio.sleep(sleep_seconds)

async def main_loop():
    ensure_setup()
    logger.info('Starting Telegram NOTAM bot loop (python-telegram-bot)')
    # refresh known chats (discover groups the bot was added to)
    try:
        chat_list = await refresh_known_chats()
    except Exception:
        logger.exception(
            'Failed to refresh known chats; falling back to env chat ids')
        chat_list = CHAT_IDS

    for chat_id in chat_list:
        message_id = await async_send_message(
            TELEGRAM_BOT_TOKEN,
            chat_id,
            "NOTAM bot has started and is monitoring for updates."
        )
        if message_id is None:
            logger.info(f'Sent startup message to chat {chat_id}')
        # pause between activities to reduce likelihood of rate limiting
        await asyncio.sleep(5)

    try:
        while True:
            try:
                await generate_and_send(chat_list)
            except Exception:
                logger.exception("Error in generate_and_send")

            await sleep_until_next_run()

    except asyncio.CancelledError:
        logger.info("Telegram NOTAM bot stopped")

if __name__ == '__main__':
    asyncio.run(main_loop())
