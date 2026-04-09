# config.py

# 线程池大小
REPLY_THREAD_POOL_SIZE = 5

# 回复处理超时时间（秒）
REPLY_PROCESSING_TIMEOUT = 30

# 事件总线相关配置示例
EVENTBUS_THREAD_POOL_SIZE = 10
EVENTBUS_ENABLE_TLS = False
EVENTBUS_SKIP_CERT_VALIDATION = True

# 其他配置信息
LOG_FILE_PATH = "/var/log/sanhua_cli.log"

# 熔断器（断路器）相关配置
CIRCUIT_BREAKER_ENABLED = True                # 是否启用熔断器
CIRCUIT_BREAKER_FAILURE_THRESHOLD = 5         # 失败阈值，允许连续失败次数
CIRCUIT_BREAKER_RECOVERY_TIMEOUT = 60         # 熔断器恢复时间（秒）
CIRCUIT_BREAKER_HALF_OPEN_SUCCESS_THRESHOLD = 3  # 半开状态下成功次数阈值，达到后恢复正常

# 最大失败率，0~1之间的小数，超过后熔断器会动作
MAX_FAILURE_RATE = 0.5
# 最大队列大小，控制任务队列容量
MAX_QUEUE_SIZE = 100
# 健康检查间隔，单位秒
HEALTH_CHECK_INTERVAL = 60
# 健康报告间隔，单位秒
HEALTH_REPORT_INTERVAL = 300  # 比如5分钟

# 请求监控间隔，单位秒
REQUEST_MONITOR_INTERVAL = 60  # 比如1分钟
