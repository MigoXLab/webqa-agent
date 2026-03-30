"""Logging utilities for WebQA Agent.

Provides centralized logging configuration with support for:
- File logging (with rotation)
- Console output with colored formatting
- Context-aware logging for parallel test execution
- Optional file-less mode for containerized environments
"""

import contextvars
import logging
import os
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler

# Context variable for parallel test execution logging
test_id_var = contextvars.ContextVar('test_id', default='default')

LEVEL = {
    'debug': logging.DEBUG,
    'info': logging.INFO,
    'warning': logging.WARNING,
    'error': logging.ERROR,
    'critical': logging.CRITICAL,
}

COLORS = {
    'DEBUG': '\033[1;34m',     # blue
    'INFO': '\033[1;32m',      # green
    'WARNING': '\033[1;33m',   # yellow
    'ERROR': '\033[1;31m',     # red
    'CRITICAL': '\033[1;31m',  # red
    'ENDC': '\033[0m'          # reset
}


class ColoredFormatter(logging.Formatter):
    """Formatter that adds ANSI color codes to log messages."""

    def format(self, record):
        levelname = record.levelname
        if levelname in COLORS:
            record.levelname = f"{COLORS[levelname]}{levelname:>8}{COLORS['ENDC']}"
            record.msg = f"{COLORS[levelname]}{record.msg}{COLORS['ENDC']}"
        return super().format(record)


class ContextFilter(logging.Filter):
    """Filter that adds test_id from contextvars to log records.

    Enables tracking logs from parallel test executions by injecting the
    current test context into each log record.
    """

    def filter(self, record):
        record.test_id = test_id_var.get()
        return True


class GetLog:
    """Singleton logger factory with configurable output modes.

    Attributes:
        logger: The shared logger instance
        stdout: Whether file logging is disabled
        log_folder: Path to the log directory (when file logging is enabled)
        save_screenshots_locally: Whether to save screenshots locally
    """

    logger: logging.Logger = None
    stdout: bool = False

    @classmethod
    def get_log(cls, log_level: str = 'info', save_locally: bool = False,
                shared_log_folder: str = None, stdout: bool = False):
        """Initialize and return the logger instance.

        Args:
            log_level: Log level (debug, info, warning, error, critical)
            save_locally: Whether to save screenshots locally
            shared_log_folder: Custom log folder path for concurrent testing
            stdout: Disable file logging, output to stdout only.

        Returns:
            Configured logging.Logger instance

        Raises:
            ValueError: If log_level is not valid
        """
        # Suppress noisy third-party loggers
        logging.getLogger('httpx').setLevel(logging.ERROR)
        logging.getLogger('httpcore').setLevel(logging.ERROR)
        logging.getLogger('openai').setLevel(logging.ERROR)

        if log_level not in LEVEL:
            raise ValueError(f'Invalid log level: {log_level}')

        cls.save_screenshots_locally = save_locally
        cls.stdout = stdout

        if cls.logger is None:
            cls.logger = logging.getLogger()
            cls.logger.setLevel(LEVEL[log_level])

            # Configure log format
            fmt = '%(asctime)s - %(levelname)s - [%(test_id)s] %(message)s'
            if log_level == 'debug':
                fmt = '%(asctime)s %(levelname)s [%(test_id)s] [%(name)s] [%(filename)s (%(funcName)s:%(lineno)d)] - %(message)s'

            plain_formatter = logging.Formatter(fmt)
            colored_formatter = ColoredFormatter(fmt)
            context_filter = ContextFilter()

            # File handlers (only when file logging is enabled)
            if not stdout:
                if shared_log_folder:
                    cls.log_folder = shared_log_folder
                else:
                    log_dir = './logs'
                    current_time = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
                    cls.log_folder = os.path.join(log_dir, current_time)
                    os.environ['WEBQA_TIMESTAMP'] = current_time

                if not os.path.exists(cls.log_folder):
                    os.makedirs(cls.log_folder)

                # Main log file handler (with daily rotation)
                log_file = os.path.join(cls.log_folder, 'log.log')
                file_handler = TimedRotatingFileHandler(
                    filename=log_file,
                    when='midnight',
                    interval=1,
                    backupCount=3,
                    encoding='utf-8',
                )
                file_handler.name = 'file'
                file_handler.setLevel(LEVEL[log_level])
                file_handler.addFilter(context_filter)
                file_handler.setFormatter(plain_formatter)
                cls.logger.addHandler(file_handler)

                # Error log file handler (warnings and above)
                error_log_file = os.path.join(cls.log_folder, 'error.log')
                error_handler = logging.FileHandler(filename=error_log_file, encoding='utf-8')
                error_handler.name = 'error'
                error_handler.setLevel(LEVEL['warning'])
                error_handler.addFilter(context_filter)
                error_handler.setFormatter(plain_formatter)
                cls.logger.addHandler(error_handler)

            # Stream handler (always enabled for stdout and Display capture)
            stream_handler = logging.StreamHandler()
            stream_handler.name = 'stream'
            stream_handler.setLevel(LEVEL[log_level])
            stream_handler.addFilter(context_filter)
            stream_handler.setFormatter(colored_formatter)
            cls.logger.addHandler(stream_handler)

        return cls.logger
