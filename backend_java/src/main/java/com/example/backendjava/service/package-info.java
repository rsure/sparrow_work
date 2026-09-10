/**
 * 业务层：Service 接口与跨域共享的业务契约。
 *
 * <p>接口在这里声明，实现类放在 {@code service.impl}；调用方只依赖接口。
 * Agent 运行时、工具契约、模型工厂等跨模块的业务契约也归本层，
 * 因为它们描述的是「后端能做什么」，与 HTTP 协议无关。</p>
 */
package com.example.backendjava.service;
