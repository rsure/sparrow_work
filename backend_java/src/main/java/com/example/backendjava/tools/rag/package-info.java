// 模块说明：知识库（RAG）类工具子包。
//
// 包含：list_indexed_docs（列文档）、index_path（导入文件/文件夹）、
// delete_index（删除导入记录）、rag_search（语义检索），以及共享的
// IndexedDocSupport（按路径/文件名把用户说法换算成知识库记录）。
//
// 依赖 service.RagService；该服务尚未实现时，工具通过 ObjectProvider 取不到 Bean，
// 返回可读的 FAIL，而不是让应用启动失败。
package com.example.backendjava.tools.rag;
