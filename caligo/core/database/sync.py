import logging
import sqlite3
from pathlib import Path
from typing import Optional

from pymongo import UpdateOne
from pymongo.asynchronous.database import AsyncDatabase
from pyrogram.storage.sqlite_storage import SCHEMA


async def sync_mongo_to_sqlite(
    db: AsyncDatabase,
    session_path: Path,
    log: Optional[logging.Logger] = None,
) -> bool:
    """Import session and peer data from MongoDB into local SQLite session file."""
    if log is None:
        log = logging.getLogger("DBSync")

    session_path.parent.mkdir(parents=True, exist_ok=True)
    file_existed = session_path.exists()

    sess_doc = await db["SESSION"].find_one({"_id": 0})
    if not sess_doc or not sess_doc.get("auth_key"):
        if file_existed:
            log.info("No remote session in MongoDB, keeping existing local session file")
            return False
        log.info("No session found in MongoDB to import")
        return False

    log.info("Importing session and peers from MongoDB to local SQLite (%s)...", session_path.name)

    conn = sqlite3.connect(str(session_path), timeout=30.0)
    try:
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='sessions'")
        if not cursor.fetchone():
            cursor.executescript(SCHEMA)
            cursor.execute("INSERT OR REPLACE INTO version VALUES (?)", (7,))

        cursor.execute(
            """
            INSERT OR REPLACE INTO sessions
            (dc_id, server_address, port, api_id, test_mode, auth_key, date, user_id, is_bot)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sess_doc.get("dc_id", 2),
                sess_doc.get("server_address", "149.154.167.51"),
                sess_doc.get("port", 443),
                sess_doc.get("api_id"),
                int(sess_doc.get("test_mode", 0) or 0),
                sess_doc.get("auth_key"),
                sess_doc.get("date", 0),
                sess_doc.get("user_id"),
                int(sess_doc.get("is_bot", 0) or 0),
            ),
        )

        peers = []
        async for p in db["PEERS"].find():
            peers.append(
                (
                    p["_id"],
                    p.get("access_hash"),
                    p.get("type"),
                    p.get("phone_number"),
                    p.get("last_update_on", 0),
                )
            )
        if peers:
            cursor.executemany(
                """
                INSERT OR REPLACE INTO peers
                (id, access_hash, type, phone_number, last_update_on)
                VALUES (?, ?, ?, ?, ?)
                """,
                peers,
            )

        usernames = []
        async for u in db["USERNAMES"].find():
            peer_id = u.get("peer_id")
            uname = u.get("username")
            if peer_id and uname:
                usernames.append((peer_id, uname))
        if usernames:
            cursor.executemany(
                "INSERT OR REPLACE INTO usernames (id, username) VALUES (?, ?)",
                usernames,
            )

        states = []
        async for s in db["UPDATE_STATE"].find():
            states.append(
                (
                    s["_id"],
                    s.get("pts"),
                    s.get("qts"),
                    s.get("date"),
                    s.get("seq"),
                )
            )
        if states:
            cursor.executemany(
                """
                INSERT OR REPLACE INTO update_state
                (id, pts, qts, date, seq)
                VALUES (?, ?, ?, ?, ?)
                """,
                states,
            )

        conn.commit()
        log.info(
            "Import complete: session (user_id=%s), %d peers, %d usernames, %d update states.",
            sess_doc.get("user_id"),
            len(peers),
            len(usernames),
            len(states),
        )
        return True
    except Exception as e:
        log.error("Failed to import from MongoDB to SQLite: %s", e)
        return False
    finally:
        conn.close()


async def sync_sqlite_to_mongo(
    db: AsyncDatabase,
    session_path: Path,
    log: Optional[logging.Logger] = None,
) -> bool:
    """Export local SQLite session and peer data back to MongoDB."""
    if log is None:
        log = logging.getLogger("DBSync")

    if not session_path.exists():
        log.warning("Local session file %s does not exist, skipping export", session_path)
        return False

    log.info("Exporting local session & peers from SQLite to MongoDB...")
    conn = sqlite3.connect(f"file:{session_path.resolve()}?mode=ro", uri=True, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()

        # 1. Export session
        cursor.execute("SELECT * FROM sessions LIMIT 1")
        sess_row = cursor.fetchone()
        if sess_row:
            sess_dict = dict(sess_row)
            await db["SESSION"].update_one(
                {"_id": 0},
                {
                    "$set": {
                        "dc_id": sess_dict.get("dc_id"),
                        "server_address": sess_dict.get("server_address"),
                        "port": sess_dict.get("port"),
                        "api_id": sess_dict.get("api_id"),
                        "test_mode": sess_dict.get("test_mode"),
                        "auth_key": sess_dict.get("auth_key"),
                        "date": sess_dict.get("date"),
                        "user_id": sess_dict.get("user_id"),
                        "is_bot": sess_dict.get("is_bot"),
                    }
                },
                upsert=True,
            )

        # 2. Export peers
        cursor.execute("SELECT * FROM peers")
        peer_rows = cursor.fetchall()
        if peer_rows:
            peer_ops = [
                UpdateOne(
                    {"_id": r["id"]},
                    {
                        "$set": {
                            "access_hash": r["access_hash"],
                            "type": r["type"],
                            "phone_number": r["phone_number"],
                            "last_update_on": r["last_update_on"],
                        }
                    },
                    upsert=True,
                )
                for r in peer_rows
            ]
            await db["PEERS"].bulk_write(peer_ops)

        # 3. Export usernames
        cursor.execute("SELECT * FROM usernames WHERE username IS NOT NULL")
        uname_rows = cursor.fetchall()
        if uname_rows:
            uname_ops = [
                UpdateOne(
                    {"_id": r["username"].lower()},
                    {
                        "$set": {
                            "peer_id": r["id"],
                            "username": r["username"],
                        }
                    },
                    upsert=True,
                )
                for r in uname_rows
                if r["username"]
            ]
            if uname_ops:
                await db["USERNAMES"].bulk_write(uname_ops)

        # 4. Export update_state
        cursor.execute("SELECT * FROM update_state")
        state_rows = cursor.fetchall()
        if state_rows:
            state_ops = [
                UpdateOne(
                    {"_id": r["id"]},
                    {
                        "$set": {
                            "pts": r["pts"],
                            "qts": r["qts"],
                            "date": r["date"],
                            "seq": r["seq"],
                        }
                    },
                    upsert=True,
                )
                for r in state_rows
            ]
            await db["UPDATE_STATE"].bulk_write(state_ops)

        log.info(
            "Export complete: %d peers, %d usernames, %d update states synced to MongoDB.",
            len(peer_rows),
            len(uname_rows),
            len(state_rows),
        )
        return True
    except Exception as e:
        log.error("Failed to export from SQLite to MongoDB: %s", e)
        return False
    finally:
        conn.close()
