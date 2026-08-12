# -*- encoding: utf-8 -*-

from ui.cmd import build_args, config_builder
from managers.manager import ManagerFactory

if __name__ == '__main__':

    args = build_args()

    cfg = config_builder(args)
    if args.debug:
        print(f"given config:\n{cfg}")

    # select the operation
    if len(cfg.sessions):
        operation = cfg.sessions[0].operation
    else: operation = args.operation

    # run configured client
    ManagerFactory.execute(cfg=cfg)