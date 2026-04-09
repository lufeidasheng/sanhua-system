from core.core2_0.sanhuatongyu.logger import get_logger  # 按你的目录结构
# 或者：from .logger import get_logger

class MinimalCLI:
    def __init__(self, system):
        self.system = system
        self.logger = get_logger("emergency_cli")

    def start(self):
        print('===== 应急命令行界面 =====')
        print("类型 'exit' 退出")
        while True:
            cmd = input('EMERGENCY> ')
            if cmd == 'exit':
                self.logger.info("emergency_cli_exit")
                break
            # 日志记录每次命令
            self.logger.info("emergency_cmd_exec", cmd=cmd)
            print(f'执行命令: {cmd}')
