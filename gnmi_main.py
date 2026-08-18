# -*- encoding: utf-8 -*-

from ui.cmd import build_args, config_builder
from managers.manager import ManagerFactory

from modules.logger import setup_logger
import logging
import sys

if __name__ == '__main__':

    args = build_args()
    cfg = config_builder(args)

    # setup logger
    log_level = "DEBUG" if cfg.debug else cfg.log_level
    setup_logger(log_level=log_level, syslog_server=cfg.syslog_server, log_file=cfg.log_file)

    logger = logging.getLogger(__name__)
    logger.info("Initializing gNMI Client engine...")
    logger.debug(f"Configuration loaded: sessions({len(cfg.sessions)})")

    if args.debug:
        print(f"given config:\n{cfg}")

    # run configured client
    try:
        ManagerFactory.execute(cfg=cfg)
    except Exception as e:
        logger.error(f"Fatal Engine error: {e}", exc_info=True)
        sys.exit(1)