package com.example.backendjava.entity;

import jakarta.persistence.*;

@Entity
@Table(name = "app_settings")
public class AppSetting {

    @Id
    @Column(name = "key", nullable = false, length = Integer.MAX_VALUE)
    private String key;

    @Column(name = "value", nullable = false, length = Integer.MAX_VALUE)
    private String value;

    @Column(name = "updated_at", nullable = false)
    private String updatedAt;

    // getters / setters
    public String getKey() { return key; }
    public void setKey(String key) { this.key = key; }
    public String getValue() { return value; }
    public void setValue(String value) { this.value = value; }
    public String getUpdatedAt() { return updatedAt; }
    public void setUpdatedAt(String updatedAt) { this.updatedAt = updatedAt; }
}