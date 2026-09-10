/**
 * Java 后端根包：只放启动类。
 *
 * <p>分层约定（与 Python 侧 api → controllers → services → schemas 一一对应）：</p>
 * <ul>
 *   <li>{@code controller}：HTTP 接口层，只做协议适配；</li>
 *   <li>{@code service} / {@code service.impl}：业务接口与实现；</li>
 *   <li>{@code dto}：请求/响应结构（每域一个 XxxDtos 容器 + 少量共享结构）；</li>
 *   <li>{@code entity}：数据实体（当前为空，表结构在 schema.sql）；</li>
 *   <li>{@code config}：配置属性与基础设施 Bean；</li>
 *   <li>{@code common}：统一响应、异常、分页、工具安全策略；</li>
 *   <li>{@code util}：与业务无关的静态工具。</li>
 * </ul>
 *
 * <p>当前工程是“可启动的骨架”：健康检查与 /api/llm/providers 已完整可用，
 * 其它 Service 接口留给学习者按文档逐步实现。</p>
 */
package com.example.backendjava;
