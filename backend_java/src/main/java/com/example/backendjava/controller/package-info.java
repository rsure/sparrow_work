/**
 * 接口层：只做 HTTP 协议适配（路由、参数校验、响应包装）。
 *
 * <p>本包不写业务逻辑：真正的能力由 {@code service} 包的接口提供，
 * 实现类在 {@code service.impl}。Controller 负责把请求体转成 DTO、
 * 调用 Service、再用 {@code common.ApiResponse} 包一层返回。</p>
 */
package com.example.backendjava.controller;
