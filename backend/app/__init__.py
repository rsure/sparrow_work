"""后端包入口。"""

# 项目内：全局配置单例（应用名、端口、CORS 白名单、向量模型参数等）。
# 在这里再导出一次，使调用方可以 `from app import settings` 拿到同一份配置
from app.config import settings

# 本包的公开导出清单：`from app import *` 时只会带出 settings，避免误导出其它符号
__all__ = ["settings"]
