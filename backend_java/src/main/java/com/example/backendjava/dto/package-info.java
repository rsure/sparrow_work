/**
 * 数据传输对象：接口的请求体与响应体。
 *
 * <p>每个业务域一个 {@code XxxDtos} 容器类，内部用 {@code record} 声明若干 DTO，
 * 避免为几十个小结构各建一个文件。JSON 字段一律 {@code snake_case}，
 * 用 {@code @JsonProperty} 与 Java 驼峰字段对应。</p>
 */
package com.example.backendjava.dto;
