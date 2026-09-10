// 模块说明：联网类工具子包。
//
// 包含：web_search（搜索）、web_fetch（抓网页正文）、http_request（通用 HTTP 请求），
// 以及两个共享实现：NetGuard（URL/SSRF 校验 + 外部内容围栏）、HtmlUtils（HTML→纯文本）。
//
// 所有联网工具默认关闭，需要用户打开设置 tools.allow_web；响应体一律按不可信数据处理。
package com.example.backendjava.tools.net;
