// 模块说明：命令执行工具子包。
//
// 目前只有 run_command：在本机执行一条已获授权的命令（跑测试、类型检查、脚本）。
// 安全依赖根包的 PathPolicy（工作目录囚笼）与 ToolRuntime（每次调用需确认）。
package com.example.backendjava.tools.exec;
