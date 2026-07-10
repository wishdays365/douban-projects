import os
import logging
import logging.handlers

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

def setup_logging(config_path=None):
    config_path = config_path or os.path.join(ROOT_DIR, "config.toml")
    cfg = {}
    try:
        import toml
        if os.path.exists(config_path):
            cfg = toml.load(config_path)
    except Exception:
        cfg = {}

    log_cfg = cfg.get("logging", {})
    level_name = log_cfg.get("level", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    fmt = log_cfg.get("format", "%(asctime)s %(levelname)s [%(name)s] %(message)s")

    handlers = [logging.StreamHandler()]

    log_file = log_cfg.get("file")
    if log_file:
        full_log_path = os.path.join(ROOT_DIR, log_file)
        os.makedirs(os.path.dirname(full_log_path), exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            filename=full_log_path,
            maxBytes=int(log_cfg.get("max_bytes", 10 * 1024 * 1024)),
            backupCount=int(log_cfg.get("backup_count", 5)),
            encoding="utf-8",
        )
        handlers.append(fh)

    logging.basicConfig(level=level, format=fmt, handlers=handlers)
    return logging.getLogger("douban_top250")
