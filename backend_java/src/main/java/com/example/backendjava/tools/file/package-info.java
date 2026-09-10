// 模块说明：文件类工具子包。
//
// 包含：list_dir（列目录）、read_file（读文件）、grep_files（按关键字找）、
// glob（按路径模式找）、write_file（新建/覆盖）、edit_file（局部修改）、
// file_ops（移动/复制/删除）。
//
// 这些工具都依赖 tools 根包的公共底座：路径校验（ToolUtils/PathPolicy）、
// 读后写校验（FileGuard）、路径锁（PathLock）与统一执行关卡（ToolRuntime）。
package com.example.backendjava.tools.file;
