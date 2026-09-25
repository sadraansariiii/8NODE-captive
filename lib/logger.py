#!/usr/bin/env python3
"""
logger.py - لاگ مشترک
"""
import os
import sys
import logging
from logging.handlers import RotatingFileHandler
from typing import Optional

from . import config

_LOGGERS = {}
_INITIALIZED = False


def _init_root():
    global _INITIALIZED
    if _INITIALIZED:
        return
    
    level_name = str(config.get("LOG_LEVEL", "INFO")).upper()
    level = getattr(logging, level_name, logging.INFO)
    
    root = logging.getLogger("cp")
    root.setLevel(level)
    
    if root.handlers:
        _INITIALIZED = True
        return
    
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(logging.Formatter(
        "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    ))
    root.addHandler(console)
    
    log_dir = config.get("LOG_DIR", "/var/log/captive-portal")
    try:
        os.makedirs(log_dir, exist_ok=True)
        file_handler = RotatingFileHandler(
            os.path.join(log_dir, "portal.log"),
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        ))
        root.addHandler(file_handler)
    except Exception:
        pass
    
    _INITIALIZED = True


def get(name: str) -> logging.Logger:
    _init_root()
    if name not in _LOGGERS:
        _LOGGERS[name] = logging.getLogger(f"cp.{name}")
    return _LOGGERS[name]
