"""扫描相关的业务异常定义。"""


class ScanException(Exception):
    """业务异常:携带 HTTP 状态码与提示信息,由全局异常处理器转换为响应。"""

    def __init__(self, code: int, message: str):
        """构造业务异常，供 controller 在业务失败时抛出。

        场景：如 `raise ScanException(404, "任务不存在")`，
        由 main.py 注册的全局异常处理器接住并转成统一 JSON 响应。

        :param code: 要返回给前端的 HTTP 状态码，如 404=资源不存在、422=参数或内容不可处理
        :param message: 错误提示文案，会原样放进响应的 message 字段
        """
        super().__init__(message)
        # HTTP 状态码：全局处理器用它作为响应的 status_code，同时回填 body 里的 code
        self.code = code
        # 错误提示文案：前端可直接展示给用户
        self.message = message
