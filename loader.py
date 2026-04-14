# handles loading data from various sources into a DataFrame

# TODO: adding PostgreSQL support - psycopg2 + sqlalchemy
# something like: engine = create_engine(conn_string) -> pd.read_sql(query, engine) find a way to integrate it
import os
import json
import pandas as pd


class DataLoader:

    SUPPORTED = {".csv", ".xlsx", ".xls", ".json"}

    def load(self, filepath):
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"File not found: {filepath}")

        ext = os.path.splitext(filepath)[1].lower()
        if ext not in self.SUPPORTED:
            raise ValueError(f"Can't handle '{ext}' files. Supported: {self.SUPPORTED}")

        if ext == ".csv":
            return pd.read_csv(filepath)
        elif ext in (".xlsx", ".xls"):
            return pd.read_excel(filepath)
        elif ext == ".json":
            return self._load_json(filepath)

    def _load_json(self, filepath):
        with open(filepath) as f:
            data = json.load(f)

        # handling both list-of-dicts and nested dict formats
        if isinstance(data, list):
            return pd.DataFrame(data)
        elif isinstance(data, dict):
            # try json_normalize for nested structures
            return pd.json_normalize(data)
        else:
            raise ValueError("JSON must be a list of objects or a dict")
