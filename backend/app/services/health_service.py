"""健康检查业务逻辑：service 层不感知 HTTP 协议。"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# platform：读操作系统类型/版本与 Python 版本，返回给前端做环境排查
import platform
# sys.executable：告诉用户后端实际跑的是哪个 Python 解释器（多虚拟环境排错用）
import sys
# time.monotonic：取单调时钟算进程已运行秒数，不受系统时间被调整的影响
import time
# datetime/timezone：生成带时区的"服务器当前时间"字符串
from datetime import datetime, timezone

# 项目内：全局配置（应用名 app_name、版本 version、运行环境 env）
from app.config import settings
# 项目内：健康检查返回体模型（字段与前端 HealthData 类型一一对应）
from app.schemas.health import HealthData

# 进程启动时间，用于计算 uptime
_STARTED_AT = time.monotonic()


class HealthService:
    """返回进程/运行时的健康快照。"""

    def get_health(self) -> HealthData:
        """采集当前进程与运行时的健康快照，供 GET /api/health 使用。

        :return: 状态（当前恒为 "ok"）、应用名/版本/环境、Python 版本、平台串、
                 进程已运行秒数（保留 3 位小数）与本机当前时间（ISO8601 带时区）
        """
        return HealthData(
            status="ok",
            service=settings.app_name,
            version=settings.version,
            env=settings.env,
            python_version=platform.python_version(),
            platform=f"{platform.system()} {platform.release()} ({sys.executable})",
            uptime_seconds=round(time.monotonic() - _STARTED_AT, 3),
            server_time=datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        )


# 模块级单例：控制器直接 import 这个对象调用，避免每次请求都新建实例
health_service = HealthService()
