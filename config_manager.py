# loads yaml configs - each data source gets its own file with rules, thresholds, and which checks to run or skip.

import os
import yaml


class ConfigManager:

    # fallback config if no YAML file is provided--class level defaults that can be overridden by user config files
    DEFAULTS = {
        "data_source": "unknown",
        "checks": {"enabled": [], "disabled": []},
        "ranges": {},
        "thresholds": {"max_missing_pct": 5.0, "max_duplicate_pct": 1.0},
    }

    def __init__(self, config_dir="configs"):
        self.config_dir = config_dir

    def load(self, config_path=None):
        # if no path provided, return defaults
        if config_path is None:
            return dict(self.DEFAULTS)

        if not os.path.exists(config_path):
            print(f"Warning: config file '{config_path}' not found, using defaults")
            return dict(self.DEFAULTS)

        with open(config_path) as f:
            user_config = yaml.safe_load(f) or {} # converts the YAML into a Python dict

        # merge user config on top of defaults
        merged = self._deep_merge(dict(self.DEFAULTS), user_config)
        return merged

    def _deep_merge(self, base, override):
        # recursively merge two dicts, with override takes precedence
        result = dict(base)
        for k, v in override.items():
            if k in result and isinstance(result[k], dict) and isinstance(v, dict):
                result[k] = self._deep_merge(result[k], v)
            else:
                result[k] = v
        return result

    def list_configs(self):
        if not os.path.exists(self.config_dir):
            return []
        return [f for f in os.listdir(self.config_dir) if f.endswith((".yaml", ".yml"))]
