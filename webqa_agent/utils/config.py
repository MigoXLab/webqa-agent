"""Configuration utility functions.

This module provides utilities for loading and processing configuration files.
"""

import glob
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Union

import yaml


def find_config_file(config_path=None):
    """Find configuration file with priority search.

    Args:
        config_path: Explicit path to config file (highest priority)

    Returns:
        str: Path to configuration file, or None if not found

    Raises:
        FileNotFoundError: If explicit config_path is provided but not found
    """
    # 1. Explicit path has highest priority
    if config_path:
        if os.path.isfile(config_path):
            return config_path
        else:
            raise FileNotFoundError(f'Specified config file not found: {config_path}')

    # 2. Search default locations
    current_dir = os.getcwd()
    default_paths = [
        os.path.join(current_dir, 'config.yaml'),
        os.path.join(current_dir, 'config', 'config.yaml'),
        '/app/config/config.yaml',  # Docker container
    ]

    for path in default_paths:
        if os.path.isfile(path):
            return path

    return None


def load_yaml(path):
    """Load and parse YAML configuration file.

    Args:
        path: Path to YAML file

    Returns:
        dict: Parsed YAML content

    Exits:
        Exits with error code 1 if file not found or parsing fails
    """
    if not os.path.isfile(path):
        print(f'[ERROR] Config file not found: {path}', file=sys.stderr)
        sys.exit(1)
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except Exception as e:
        print(f'[ERROR] Failed to parse YAML: {e}', file=sys.stderr)
        sys.exit(1)


def load_cookies(cookies_value):
    """Load cookies from value (list, string path, or file path).

    Args:
        cookies_value: Can be:
            - list: Direct cookie list, returned as-is
            - str: File path to JSON file containing cookies
            - None: Returns empty list

    Returns:
        list: Parsed cookies list

    Examples:
        >>> load_cookies([{"name": "session", "value": "abc"}])
        [{"name": "session", "value": "abc"}]

        >>> load_cookies("./cookies.json")
        # Reads and parses cookies.json

        >>> load_cookies(None)
        []
    """
    # If already a list, return as-is
    if isinstance(cookies_value, list):
        return cookies_value

    # If None or empty, return empty list
    if not cookies_value:
        return []

    # If string, treat as file path
    if isinstance(cookies_value, str):
        cookies_path = cookies_value.strip()

        # Check if file exists
        if not os.path.isfile(cookies_path):
            print(f'⚠️ Cookies file not found: {cookies_path}', file=sys.stderr)
            return []

        try:
            with open(cookies_path, 'r', encoding='utf-8') as f:
                content = f.read().strip()

                # Try to parse as JSON
                try:
                    cookies_list = json.loads(content)
                    if not isinstance(cookies_list, list):
                        print(f'⚠️ Cookies file must contain a JSON array, got {type(cookies_list).__name__}',
                              file=sys.stderr)
                        return []
                    print(f'✓ Loaded {len(cookies_list)} cookies from {cookies_path}')
                    return cookies_list
                except json.JSONDecodeError as e:
                    print(f'⚠️ Failed to parse cookies JSON: {e}', file=sys.stderr)
                    return []

        except Exception as e:
            print(f'⚠️ Failed to read cookies file: {e}', file=sys.stderr)
            return []

    # Unexpected type
    print(f'⚠️ Unexpected cookies type: {type(cookies_value).__name__}, expected list or str',
          file=sys.stderr)
    return []


def load_yaml_files(yaml_path: Union[str, Path]) -> List[Dict[str, Any]]:
    """Load YAML configuration(s) from file or folder.

    Args:
        yaml_path: Path to a single YAML file or a folder containing multiple YAML files

    Returns:
        List of configuration dicts, each containing 'cases' and config fields
    """
    path = Path(yaml_path)
    configs = []

    if path.is_file():
        # Single file
        with open(path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
            if config:
                config['_source_file'] = str(path)
                configs.append(config)
    elif path.is_dir():
        # Folder - load all YAML files
        yaml_files = sorted(glob.glob(str(path / '*.yaml')) + glob.glob(str(path / '*.yml')))
        for yaml_file in yaml_files:
            try:
                with open(yaml_file, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f)
                    if config:
                        config['_source_file'] = yaml_file
                        configs.append(config)
                        print(f'Loaded config from: {yaml_file}')
            except Exception as e:
                print(f'Failed to load {yaml_file}: {e}')
    else:
        raise ValueError(f'Path does not exist: {yaml_path}')

    if not configs:
        raise ValueError(f'No valid YAML configurations found in: {yaml_path}')

    print(f'Loaded {len(configs)} configuration(s) from {yaml_path}')
    return configs
