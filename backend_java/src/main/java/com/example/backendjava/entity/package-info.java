/**
 * 数据实体层（当前为空，预留）。
 *
 * <p>本工程不用 ORM：表结构写死在 {@code src/main/resources/schema.sql}，
 * Service 实现需要持久化时直接注入 {@code JdbcTemplate} 读写表，
 * 因此没有 {@code @Entity} 类。若后续引入 JPA/MyBatis，实体类放本包。</p>
 */
package com.example.backendjava.entity;
