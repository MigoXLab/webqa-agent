import logging
import os
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler


LEVEL = {
    'debug': logging.DEBUG,
    'info': logging.INFO,
    'warning': logging.WARNING,
    'error': logging.ERROR,
    'critical': logging.CRITICAL,
}

COLORS = {
    'DEBUG': '\033[1;34m',  # blue
    'INFO': '\033[1;32m',  # green
    'WARNING': '\033[1;33m',  # yellow
    'ERROR': '\033[1;31m',  # red
    'CRITICAL': '\033[1;31m',  # red
    'ENDC': '\033[0m'  # reset
}

class ColoredFormatter(logging.Formatter):
    def format(self, record):
        levelname = record.levelname
        if levelname in COLORS:
            record.levelname = f"{COLORS[levelname]}{levelname:>8}{COLORS['ENDC']}"
            record.msg = f"{COLORS[levelname]}{record.msg}{COLORS['ENDC']}"
        return super().format(record)


class GetLog:
    logger: logging.Logger = None

    @classmethod
    def get_log(cls, log_level: str = "info", save_locally: bool=False, shared_log_folder: str=None):
        """Get logger and initialize logging system.

        Args:
            log_level(str):
            save_locally (bool): Whether to save screenshots locally, default is False
            shared_log_folder (str): Shared log folder path for concurrent testing
        """
        logging.getLogger("httpx").setLevel(logging.ERROR)
        logging.getLogger("httpcore").setLevel(logging.ERROR)
        logging.getLogger("openai").setLevel(logging.ERROR)
        if log_level not in log_level:
            raise ValueError(f"Invalid log level: {log_level}")

        # Set global screenshot save parameter
        cls.save_screenshots_locally = save_locally

        if cls.logger is None:
            # If shared log folder is provided, use it
            if shared_log_folder:
                cls.log_folder = shared_log_folder
            else:
                # Get current time and create corresponding log directory
                log_dir = "./logs"
                current_time = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                cls.log_folder = os.path.join(log_dir, current_time)

                # Store timestamp in environment variable
                os.environ["WEBQA_TIMESTAMP"] = current_time

            # Create log directory if it doesn't exist
            if not os.path.exists(cls.log_folder):
                os.makedirs(cls.log_folder)

            # Get logger
            cls.logger = logging.getLogger()
            # Set log level
            cls.logger.setLevel(LEVEL[log_level])

            # Get handler - main log file handler
            log_file = os.path.join(cls.log_folder, "log.log")
            th = TimedRotatingFileHandler(
                filename=log_file,
                when="midnight",
                interval=1,
                backupCount=3,
                encoding="utf-8",
            )
            th.name = "file"
            th.setLevel(LEVEL[log_level])

            # Get ERROR log handler - error log file handler
            error_log_file = os.path.join(cls.log_folder, "error.log")
            eh = logging.FileHandler(filename=error_log_file, encoding="utf-8")
            eh.name = "error"
            eh.setLevel(LEVEL["warning"])

            fmt = "%(asctime)s - %(levelname)s - %(message)s"
            if log_level == "debug":
                fmt = "%(asctime)s %(levelname)s [%(name)s] [%(filename)s (%(funcName)s:%(lineno)d)] - %(message)s"
            fm = logging.Formatter(fmt)
            console_fm = ColoredFormatter(fmt)

            th.setFormatter(fm)
            eh.setFormatter(fm)

            cls.logger.addHandler(th)
            cls.logger.addHandler(eh)

            ch = logging.StreamHandler()
            ch.name = "stream"
            ch.setLevel(LEVEL[log_level])

            ch.setFormatter(console_fm)
            cls.logger.addHandler(ch)

        # Return logger
        return cls.logger
