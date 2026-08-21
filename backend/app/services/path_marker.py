# app/services/path_marker.py
"""路径标记协议：把 AI 回答里的文件路径包成可解析的标记，并生成结构化文件清单。

为什么用"标记 + JSON 载荷"而不是前端正则：
    Windows 路径里有反斜杠、空格、中文标点，用正则抠必然误判（D:\\a\\b.md 的 \\b 是转义序列）。
    把路径放进 JSON 字符串里，转义规则由 JSON 负责，解析就变成一次 json.loads，可靠得多。
"""

# 让类型注解延迟求值（PEP 563）
from __future__ import annotations

# 标准库：解析标记里的 JSON 载荷
import json
# 标准库：正则用于定位标记与清洗非法标记
import re

# 标记起止符：成对出现，中间是 JSON。起止符本身不会出现在正常中文里，不会误伤正文
MARKER_OPEN = "⟦path:"
MARKER_CLOSE = "⟧"

# 匹配合法标记；载荷只允许 {"p": "..."} 这一种形状，其它形状一律不认（宁可不识别，也不要瞎猜）
_MARKER_RE = re.compile(r"⟦path:(\{\"p\":\s*\"(?:[^\"\\]|\\.)*\"\})⟧")

# 清洗非法标记：起止符残片（模型写坏了）直接删掉，避免它们显示给用户
_STRAY_RE = re.compile(r"⟦path:|⟧")


def wrap(path: str) -> str:
    """把路径包成标记（供后端在拼装回答时调用）。

    :param path: 文件绝对路径
    :return: 形如 ⟦path:{"p":"D:\\\\docs\\\\a.md"}⟧ 的标记
    """
    return f"{MARKER_OPEN}{json.dumps({'p': path}, ensure_ascii=False)}{MARKER_CLOSE}"


def parse(text: str) -> tuple[str, list[str]]:
    """把回答里的路径标记取出，并返回"纯文本 + 路径列表"。

    :param text: 含标记的完整回答
    :return: (去掉标记后的纯文本, 按出现顺序去重的路径列表)
    """
    found: list[str] = []

    def _sub(m: re.Match[str]) -> str:
        """替换回调：记录路径并原地留空（前端会把纯文本按位置切成可点击片段）。"""
        try:
            payload = json.loads(m.group(1))
            p = str(payload.get("p", "")).strip()
            if p:
                found.append(p)
        except json.JSONDecodeError:
            # 解析失败就当它不是标记（理论上 _MARKER_RE 已保证 JSON 合法，这里只是兜底）
            pass
        return ""

    plain = _MARKER_RE.sub(_sub, text)
    # 清掉模型写坏留下的残片，否则界面会出现奇怪的 ⟦path: 字样
    plain = _STRAY_RE.sub("", plain)
    # 去重但保持出现顺序（同一文件可能被提到多次）
    uniq = list(dict.fromkeys(found))
    return plain, uniq