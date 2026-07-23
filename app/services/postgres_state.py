import copy
import json
import os
from loguru import logger
from app.models import const
from app.services.state import BaseState

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False

try:
    import pg8000.native
    HAS_PG8000 = True
except ImportError:
    HAS_PG8000 = False


class PostgresState(BaseState):
    """
    PostgreSQL-backed task state for Neon DB and serverless deployments.
    """

    def __init__(self, db_url: str):
        self.db_url = db_url
        if self.db_url.startswith("postgres://"):
            self.db_url = self.db_url.replace("postgres://", "postgresql://", 1)
        self._init_db()

    def _get_connection(self):
        if HAS_PSYCOPG2:
            return psycopg2.connect(self.db_url)
        elif HAS_PG8000:
            # Parse connection parameters for pg8000 if psycopg2 is not installed
            from urllib.parse import urlparse
            url = urlparse(self.db_url)
            return pg8000.native.Connection(
                user=url.username,
                password=url.password,
                host=url.hostname,
                port=url.port or 5432,
                database=url.path.lstrip('/')
            )
        else:
            raise RuntimeError("Neither psycopg2 nor pg8000 is installed. Cannot connect to PostgreSQL.")

    def _init_db(self):
        try:
            conn = self._get_connection()
            if HAS_PSYCOPG2:
                with conn.cursor() as cur:
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS mpt_tasks (
                            task_id VARCHAR(255) PRIMARY KEY,
                            state INT NOT NULL,
                            progress INT NOT NULL DEFAULT 0,
                            data JSONB NOT NULL DEFAULT '{}'::jsonb,
                            updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                        );
                    """)
                conn.commit()
                conn.close()
            else:
                conn.run("""
                    CREATE TABLE IF NOT EXISTS mpt_tasks (
                        task_id VARCHAR(255) PRIMARY KEY,
                        state INT NOT NULL,
                        progress INT NOT NULL DEFAULT 0,
                        data JSONB NOT NULL DEFAULT '{}'::jsonb,
                        updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                    );
                """)
                conn.close()
            logger.info("Successfully initialized PostgreSQL tasks table on Neon DB.")
        except Exception as e:
            logger.error(f"Failed to initialize PostgreSQL table: {e}")

    def get_all_tasks(self, page: int, page_size: int):
        offset = (page - 1) * page_size
        tasks = []
        total = 0
        try:
            conn = self._get_connection()
            if HAS_PSYCOPG2:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("SELECT COUNT(*) FROM mpt_tasks")
                    total = cur.fetchone()['count']

                    cur.execute(
                        "SELECT task_id, state, progress, data FROM mpt_tasks ORDER BY updated_at DESC LIMIT %s OFFSET %s",
                        (page_size, offset)
                    )
                    rows = cur.fetchall()
                    for row in rows:
                        task_dict = dict(row['data'] or {})
                        task_dict['task_id'] = row['task_id']
                        task_dict['state'] = row['state']
                        task_dict['progress'] = row['progress']
                        tasks.append(task_dict)
                conn.close()
            else:
                res_count = conn.run("SELECT COUNT(*) FROM mpt_tasks")
                total = res_count[0][0] if res_count else 0

                rows = conn.run(
                    "SELECT task_id, state, progress, data FROM mpt_tasks ORDER BY updated_at DESC LIMIT :limit OFFSET :offset",
                    limit=page_size, offset=offset
                )
                for row in rows:
                    task_id, state, progress, raw_data = row[0], row[1], row[2], row[3]
                    task_dict = json.loads(raw_data) if isinstance(raw_data, str) else dict(raw_data or {})
                    task_dict['task_id'] = task_id
                    task_dict['state'] = state
                    task_dict['progress'] = progress
                    tasks.append(task_dict)
                conn.close()
        except Exception as e:
            logger.error(f"PostgresState get_all_tasks failed: {e}")
        return tasks, total

    def update_task(
        self,
        task_id: str,
        state: int = const.TASK_STATE_PROCESSING,
        progress: int = 0,
        **kwargs,
    ):
        progress = int(progress)
        if progress > 100:
            progress = 100

        data_payload = json.dumps(kwargs)
        try:
            conn = self._get_connection()
            if HAS_PSYCOPG2:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO mpt_tasks (task_id, state, progress, data, updated_at)
                        VALUES (%s, %s, %s, %s::jsonb, CURRENT_TIMESTAMP)
                        ON CONFLICT (task_id) DO UPDATE
                        SET state = EXCLUDED.state,
                            progress = EXCLUDED.progress,
                            data = mpt_tasks.data || EXCLUDED.data,
                            updated_at = CURRENT_TIMESTAMP;
                    """, (task_id, state, progress, data_payload))
                conn.commit()
                conn.close()
            else:
                conn.run("""
                    INSERT INTO mpt_tasks (task_id, state, progress, data, updated_at)
                    VALUES (:task_id, :state, :progress, :data::jsonb, CURRENT_TIMESTAMP)
                    ON CONFLICT (task_id) DO UPDATE
                    SET state = EXCLUDED.state,
                        progress = EXCLUDED.progress,
                        data = mpt_tasks.data || EXCLUDED.data,
                        updated_at = CURRENT_TIMESTAMP;
                """, task_id=task_id, state=state, progress=progress, data=data_payload)
                conn.close()
        except Exception as e:
            logger.error(f"PostgresState update_task failed for task {task_id}: {e}")

    def get_task(self, task_id: str):
        try:
            conn = self._get_connection()
            task = None
            if HAS_PSYCOPG2:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute("SELECT task_id, state, progress, data FROM mpt_tasks WHERE task_id = %s", (task_id,))
                    row = cur.fetchone()
                    if row:
                        task = dict(row['data'] or {})
                        task['task_id'] = row['task_id']
                        task['state'] = row['state']
                        task['progress'] = row['progress']
                conn.close()
            else:
                rows = conn.run("SELECT task_id, state, progress, data FROM mpt_tasks WHERE task_id = :task_id", task_id=task_id)
                if rows:
                    row = rows[0]
                    task_id_val, state_val, progress_val, raw_data = row[0], row[1], row[2], row[3]
                    task = json.loads(raw_data) if isinstance(raw_data, str) else dict(raw_data or {})
                    task['task_id'] = task_id_val
                    task['state'] = state_val
                    task['progress'] = progress_val
                conn.close()
            return task
        except Exception as e:
            logger.error(f"PostgresState get_task failed for task {task_id}: {e}")
            return None

    def patch_task(self, task_id: str, **kwargs) -> bool:
        if not kwargs:
            return False

        data_payload = json.dumps(kwargs)
        try:
            conn = self._get_connection()
            updated = False
            if HAS_PSYCOPG2:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE mpt_tasks
                        SET data = data || %s::jsonb,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE task_id = %s;
                    """, (data_payload, task_id))
                    updated = cur.rowcount > 0
                conn.commit()
                conn.close()
            else:
                conn.run("""
                    UPDATE mpt_tasks
                    SET data = data || :data::jsonb,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE task_id = :task_id;
                """, data=data_payload, task_id=task_id)
                updated = True
                conn.close()
            return updated
        except Exception as e:
            logger.error(f"PostgresState patch_task failed for task {task_id}: {e}")
            return False

    def delete_task(self, task_id: str):
        try:
            conn = self._get_connection()
            if HAS_PSYCOPG2:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM mpt_tasks WHERE task_id = %s", (task_id,))
                conn.commit()
                conn.close()
            else:
                conn.run("DELETE FROM mpt_tasks WHERE task_id = :task_id", task_id=task_id)
                conn.close()
        except Exception as e:
            logger.error(f"PostgresState delete_task failed for task {task_id}: {e}")
