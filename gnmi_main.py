# -*- encoding: utf-8 -*-

from gnmi_manager import SubscriptionManager
from ui.cmd import build_args, config_builder

if __name__ == '__main__':

    args = build_args()

    cfg = config_builder(args)
    print(f'Config built: {cfg}')

    manager = SubscriptionManager(cfg=cfg)
    manager.run_all()