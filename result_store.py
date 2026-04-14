"""SQLite storage for quality check results. Feeds Power BI and future ML pipeline."""

import sqlite3
import json
import os
from datetime import datetime
from typing import Optional
from checks.base_check import CheckResult


class ResultStore:
    # Handles all interactions with the SQLite database to store and retrieve quality check results.

    def __init__(self, db_path: str = "db/quality_results.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    def _init_db(self):
        # Initializing the database and create tables if they don't exist.
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS runs (
                run_id          INTEGER PRIMARY KEY AUTOINCREMENT,
                file_name       TEXT NOT NULL,
                data_source     TEXT,
                run_timestamp   TEXT NOT NULL,
                row_count       INTEGER,
                column_count    INTEGER,
                overall_score   REAL,
                grade           TEXT,
                total_issues    INTEGER
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS check_results (
                result_id       INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id          INTEGER NOT NULL,
                check_name      TEXT NOT NULL,
                category        TEXT,
                severity        TEXT,
                passed          INTEGER,
                issue_count     INTEGER,
                total_checked   INTEGER,
                issue_pct       REAL,
                details         TEXT,
                recommendation  TEXT,
                action_type     TEXT,
                FOREIGN KEY (run_id) REFERENCES runs(run_id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS flagged_records (
                flag_id         INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id          INTEGER NOT NULL,
                check_name      TEXT NOT NULL,
                row_index       INTEGER,
                primary_key     TEXT,
                column_name     TEXT,
                value           TEXT,
                rule            TEXT,
                expected        TEXT,
                severity        TEXT,
                action_type     TEXT,
                context         TEXT,
                deviation       REAL,
                FOREIGN KEY (run_id) REFERENCES runs(run_id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS column_profiles (
                profile_id      INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id          INTEGER NOT NULL,
                column_name     TEXT NOT NULL,
                dtype           TEXT,
                total_count     INTEGER,
                null_count      INTEGER,
                unique_count    INTEGER,
                mean            REAL,
                std             REAL,
                min_val         REAL,
                max_val         REAL,
                top_values      TEXT,
                FOREIGN KEY (run_id) REFERENCES runs(run_id)
            )
        """)

        conn.commit()
        conn.close()

    def save_run(self, file_name: str, data_source: str, row_count: int,
                 column_count: int, overall_score: float, grade: str,
                 total_issues: int, results: list[CheckResult],
                 profiles: list = None) -> int:
        # Save a run with all its metadata, check results, flagged records, and column profiles. Returns the run_id.
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO runs (file_name, data_source, run_timestamp, row_count,
                              column_count, overall_score, grade, total_issues)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            file_name,
            data_source,
            datetime.now().isoformat(),
            row_count,
            column_count,
            overall_score,
            grade,
            total_issues,
        ))

        run_id = cursor.lastrowid

        for result in results:
            cursor.execute("""
                INSERT INTO check_results (run_id, check_name, category, severity,
                                           passed, issue_count, total_checked,
                                           issue_pct, details, recommendation, action_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                run_id,
                result.check_name,
                result.category,
                result.severity,
                1 if result.passed else 0,
                int(result.issue_count),
                int(result.total_checked),
                float(result.issue_percentage),
                json.dumps(result.details),
                result.recommendation,
                result.action_type,
            ))

            # store flagged records
            for flag in result.flagged_records:
                cursor.execute("""
                    INSERT INTO flagged_records (run_id, check_name, row_index,
                        primary_key, column_name, value, rule, expected,
                        severity, action_type, context, deviation)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    run_id,
                    result.check_name,
                    flag.row_index,
                    json.dumps(flag.primary_key),
                    flag.column,
                    str(flag.value) if flag.value is not None else None,
                    flag.rule,
                    flag.expected,
                    flag.severity,
                    flag.action_type,
                    json.dumps(flag.context),
                    flag.deviation,
                ))

        # store column profiles
        if profiles:
            for p in profiles:
                cursor.execute("""
                    INSERT INTO column_profiles (run_id, column_name, dtype,
                        total_count, null_count, unique_count,
                        mean, std, min_val, max_val, top_values)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    run_id,
                    p.column_name,
                    p.dtype,
                    p.total_count,
                    p.null_count,
                    p.unique_count,
                    p.mean,
                    p.std,
                    p.min_val,
                    p.max_val,
                    json.dumps(p.top_values) if p.top_values else None,
                ))

        conn.commit()
        conn.close()
        return run_id

    def get_run_history(self, file_name: Optional[str] = None,
                        limit: int = 20) -> list[dict]:
        # Get past run history for a specific file or all files, for UI display. 
        # Returns list of dicts with run metadata and scores.
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        if file_name:
            cursor.execute(
                "SELECT * FROM runs WHERE file_name = ? ORDER BY run_timestamp DESC LIMIT ?",
                (file_name, limit),
            )
        else:
            cursor.execute(
                "SELECT * FROM runs ORDER BY run_timestamp DESC LIMIT ?",
                (limit,),
            )

        columns = [desc[0] for desc in cursor.description]
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
        conn.close()
        return rows

    def get_check_results(self, run_id: int) -> list[dict]:
        # Get detailed check results for a specific run, including flagged records and recommendations.
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute(
            "SELECT * FROM check_results WHERE run_id = ? ORDER BY check_name",
            (run_id,),
        )

        columns = [desc[0] for desc in cursor.description]
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
        conn.close()
        return rows

    def get_trend_data(self, file_name: str, check_name: Optional[str] = None) -> list[dict]:
        # Get trend data for a specific file (and optionally a specific check).
        #Designed for Power BI time-series charts.
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        if check_name:
            cursor.execute("""
                SELECT r.run_timestamp, r.overall_score, cr.check_name,
                       cr.issue_count, cr.issue_pct
                FROM runs r
                JOIN check_results cr ON r.run_id = cr.run_id
                WHERE r.file_name = ? AND cr.check_name = ?
                ORDER BY r.run_timestamp
            """, (file_name, check_name))
        else:
            cursor.execute("""
                SELECT run_timestamp, overall_score, total_issues
                FROM runs
                WHERE file_name = ?
                ORDER BY run_timestamp
            """, (file_name,))

        columns = [desc[0] for desc in cursor.description]
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
        conn.close()
        return rows