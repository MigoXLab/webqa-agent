import logging
import os
from datetime import datetime
from logging import WARNING, FileHandler
from logging.handlers import TimedRotatingFileHandler


class GetLog:
    logger = None

    @classmethod
    def get_log(cls, save_locally=False, shared_log_folder=None):
        """Get logger and initialize logging system.

        Args:
            save_locally (bool): Whether to save screenshots locally, default is False
            shared_log_folder (str): Shared log folder path for concurrent testing
        """
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
            cls.logger.setLevel(logging.INFO)

            # Get handler - main log file handler
            log_file = os.path.join(cls.log_folder, "log.log")
            th = TimedRotatingFileHandler(
                filename=log_file,
                when="midnight",
                interval=1,
                backupCount=3,
                encoding="utf-8",
            )
            # Set handler level
            th.setLevel(logging.INFO)

            # Get ERROR log handler - error log file handler
            error_log_file = os.path.join(cls.log_folder, "error.log")
            error_handler = FileHandler(filename=error_log_file, encoding="utf-8")
            # Set handler 2 level
            error_handler.setLevel(WARNING)

            # Get formatter, add case_name to format
            fmt = "%(asctime)s %(levelname)s [%(name)s] [%(filename)s (%(funcName)s:%(lineno)d)] - %(message)s"
            # Use custom SafeCaseFormatter instead of standard Formatter
            fm = logging.Formatter(fmt)

            # Add formatter to handler
            th.setFormatter(fm)
            # Add handler to logger
            cls.logger.addHandler(th)

            # Add formatter to handler2
            error_handler.setFormatter(fm)
            # 将处理器2添加到日志器
            cls.logger.addHandler(error_handler)

            # Create console handler
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)

            # Add formatter to console handler
            console_handler.setFormatter(fm)
            # Add console handler to logger
            cls.logger.addHandler(console_handler)

        # Return logger
        return cls.logger
