import asyncio
import logging
import os
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.garmin import GarminAccount, GarminSnapshot
from app.services.connector_service import decrypt_value

logger = logging.getLogger(__name__)

GARTH_TOKEN_BASE = "/tmp/garmin_tokens"

DATA_TYPES = [
    "stats",
    "sleep",
    "heart_rate",
    "body_battery",
    "stress",
    "steps",
    "hrv",
    "spo2",
    "respiration",
    "weight",
    "activities",
    "floors",
    "intensity_minutes",
    "training_readiness",
    "fitnessage",
    "maxmet",
]


def _token_dir(account_id: str) -> str:
    """Get the garth token directory for a given account."""
    path = os.path.join(GARTH_TOKEN_BASE, account_id)
    os.makedirs(path, exist_ok=True)
    return path


def _login_sync(email: str, password: str, account_id: str):
    """Login to Garmin Connect (synchronous). Returns a Garmin client."""
    from garminconnect import Garmin

    token_dir = _token_dir(account_id)
    client = Garmin()

    # Try to resume session from saved tokens
    try:
        client = Garmin()
        client.login(token_dir)
        logger.info(f"Garmin session resumed from tokens for {email}")
        return client
    except Exception:
        logger.info(f"No valid saved session for {email}, logging in fresh")

    # Fresh login
    client = Garmin(email=email, password=password)
    client.login()
    client.garth.dump(token_dir)
    logger.info(f"Garmin login successful for {email}, tokens saved")
    return client


def _fetch_data_sync(client, data_type: str, target_date: date) -> dict | None:
    """Fetch a specific data type for a date (synchronous). Returns data dict or None."""
    date_str = target_date.isoformat()
    try:
        if data_type == "stats":
            return client.get_stats(date_str)
        elif data_type == "sleep":
            return client.get_sleep_data(date_str)
        elif data_type == "heart_rate":
            return client.get_heart_rates(date_str)
        elif data_type == "body_battery":
            return client.get_body_battery(date_str)
        elif data_type == "stress":
            return client.get_stress_data(date_str)
        elif data_type == "steps":
            return client.get_steps_data(date_str)
        elif data_type == "hrv":
            return client.get_hrv_data(date_str)
        elif data_type == "spo2":
            return client.get_spo2_data(date_str)
        elif data_type == "respiration":
            return client.get_respiration_data(date_str)
        elif data_type == "weight":
            return client.get_body_composition(date_str)
        elif data_type == "activities":
            return client.get_activities_by_date(date_str, date_str, "")

        elif data_type == "floors":
            return client.get_floors(date_str)
        elif data_type == "intensity_minutes":
            return client.get_intensity_minutes_data(date_str)
        elif data_type == "training_readiness":
            return client.get_training_readiness(date_str)
        elif data_type == "fitnessage":
            return client.get_fitnessage_data(date_str)
        elif data_type == "maxmet":
            return client.get_max_metrics(date_str)
        else:
            logger.warning(f"Unknown Garmin data type: {data_type}")
            return None
    except Exception as e:
        logger.warning(f"Garmin fetch {data_type} for {date_str} failed: {e}")
        return None


def _sync_day_sync(client, account_id: str, target_date: date) -> list[dict]:
    """Fetch all data types for one day (synchronous). Returns list of result dicts."""
    results = []
    for data_type in DATA_TYPES:
        data = _fetch_data_sync(client, data_type, target_date)
        if data is not None:
            results.append({
                "data_type": data_type,
                "date": target_date,
                "data": data,
            })
    return results


async def test_login(email: str, password: str, account_id: str) -> tuple[bool, str]:
    """Test Garmin login. Returns (success, message)."""
    try:
        await asyncio.to_thread(_login_sync, email, password, account_id)
        return True, "Login successful"
    except Exception as e:
        return False, str(e)


async def sync_day(db: AsyncSession, account: GarminAccount, target_date: date) -> int:
    """Fetch all data types for one day and upsert snapshots. Returns count of snapshots upserted."""
    password = decrypt_value(account.password_encrypted)
    account_id_str = str(account.id)

    try:
        client = await asyncio.to_thread(_login_sync, account.email, password, account_id_str)
        results = await asyncio.to_thread(_sync_day_sync, client, account_id_str, target_date)
    except Exception as e:
        error_msg = f"Garmin sync failed: {e}"
        logger.error(error_msg)
        account.last_error = error_msg
        return 0

    count = 0
    for r in results:
        # Upsert: check if snapshot exists
        existing = await db.execute(
            select(GarminSnapshot).where(
                and_(
                    GarminSnapshot.account_id == account.id,
                    GarminSnapshot.date == r["date"],
                    GarminSnapshot.data_type == r["data_type"],
                )
            )
        )
        snapshot = existing.scalar_one_or_none()

        if snapshot:
            snapshot.data = r["data"]
        else:
            snapshot = GarminSnapshot(
                account_id=account.id,
                date=r["date"],
                data_type=r["data_type"],
                data=r["data"],
            )
            db.add(snapshot)
        count += 1

    account.last_sync_at = datetime.now(timezone.utc)
    account.last_error = None
    return count


async def sync_range(db: AsyncSession, account: GarminAccount, start_date: date, end_date: date) -> int:
    """Sync a range of dates. Returns total count of snapshots upserted."""
    password = decrypt_value(account.password_encrypted)
    account_id_str = str(account.id)

    try:
        client = await asyncio.to_thread(_login_sync, account.email, password, account_id_str)
    except Exception as e:
        error_msg = f"Garmin login failed: {e}"
        logger.error(error_msg)
        account.last_error = error_msg
        return 0

    total = 0
    current = start_date
    while current <= end_date:
        try:
            results = await asyncio.to_thread(_sync_day_sync, client, account_id_str, current)
            for r in results:
                existing = await db.execute(
                    select(GarminSnapshot).where(
                        and_(
                            GarminSnapshot.account_id == account.id,
                            GarminSnapshot.date == r["date"],
                            GarminSnapshot.data_type == r["data_type"],
                        )
                    )
                )
                snapshot = existing.scalar_one_or_none()

                if snapshot:
                    snapshot.data = r["data"]
                else:
                    snapshot = GarminSnapshot(
                        account_id=account.id,
                        date=r["date"],
                        data_type=r["data_type"],
                        data=r["data"],
                    )
                    db.add(snapshot)
                total += 1
        except Exception as e:
            logger.error(f"Garmin sync for {current} failed: {e}")

        current += timedelta(days=1)

    account.last_sync_at = datetime.now(timezone.utc)
    account.last_error = None
    return total


async def sync_all_accounts(db: AsyncSession) -> int:
    """Sync today's data for all enabled accounts. Returns total snapshot count."""
    result = await db.execute(
        select(GarminAccount).where(GarminAccount.enabled == True)
    )
    accounts = result.scalars().all()

    total = 0
    today = date.today()
    for account in accounts:
        count = await sync_day(db, account, today)
        if count > 0:
            logger.info(f"Garmin sync for {account.email}: {count} snapshots")
        total += count

    return total
