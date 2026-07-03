# -*- encoding: utf-8 -*-

from ui.cmd import build_args, config_builder
from managers.manager import ManagerFactory

if __name__ == '__main__':

    args = build_args()

    cfg = config_builder(args)
    if args.debug:
        print(f"given config:\n{cfg}")

    # manager = SubscriptionManager(cfg=cfg)
    manager = ManagerFactory.create_manager(args.operation, cfg=cfg)
    manager.run_all()