// 模块说明：设置声明层（对应 Python 侧 app/services/settings_registry.py）。
//
// 这一层只描述「有哪些设置项、值是什么类型、允许取什么范围」，不含任何业务动作：
//   - SettingKind      值类型（bool/int/float/string/json/select）与写入校验；
//   - SettingDefinition 一条设置声明（键 + 类型 + 默认值 + 区间/候选 + 展示信息）；
//   - BuiltinSettings  内置的 67 条声明，启动时一次性装进注册表；
//   - SettingsRegistry 注册表本体：读取、批量写入、变更事件发布；
//   - SettingRowStore  app_settings 表的读写封装（注册表与密钥库共用）；
//   - SecretStore      密钥库（AES/GCM 加密后存进 app_settings，不进普通设置接口）；
//   - SettingsRedactor 导出配置时的敏感值脱敏。
//
// 为什么单独成包而不是塞进 service：注册表是「被所有模块共享的基础设施」，
// 业务 Service 依赖它，它不该反过来依赖业务 Service，否则会绕成循环依赖。
package com.example.backendjava.settings;
