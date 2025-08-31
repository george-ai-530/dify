# LDAP 模块使用指南

## 概述

Dify LDAP 模块提供了与 LDAP 服务器集成的完整解决方案，包括：
- LDAP 用户自动同步（30秒间隔）
- LDAP 用户认证
- 用户启用/禁用管理
- 完整的管理 API

## 功能特性

### 1. 自动用户同步
- 每 30 秒自动从 LDAP 服务器同步用户
- 支持新用户创建、现有用户更新
- 自动禁用 LDAP 中已删除的用户

### 2. LDAP 认证
- 无缝集成到现有登录流程
- 先尝试传统认证，失败后自动尝试 LDAP 认证
- 自动创建和关联本地账户

### 3. 用户管理
- 支持启用/禁用 LDAP 用户
- 用户状态实时同步
- 完整的用户信息管理

## 配置说明

### 环境变量配置

在 `.env` 文件中添加以下配置：

```bash
# 启用 LDAP 同步任务
ENABLE_LDAP_SYNC_TASK=true

# LDAP 服务器配置
LDAP_SERVER_URL=ldap://your-ldap-server:389
LDAP_BIND_DN=cn=admin,dc=example,dc=com
LDAP_BIND_PASSWORD=your-bind-password
LDAP_BASE_DN=dc=example,dc=com

# 用户过滤和属性映射
LDAP_USER_FILTER=(objectClass=person)
LDAP_USER_ID_ATTRIBUTE=uid
LDAP_USER_EMAIL_ATTRIBUTE=mail
LDAP_USER_NAME_ATTRIBUTE=cn

# 同步间隔（秒）
LDAP_SYNC_INTERVAL=30
```

### 数据库迁移

运行以下命令创建 LDAP 相关表：

```bash
cd api
flask db upgrade
```

## API 端点

### 1. LDAP 配置管理

#### 获取 LDAP 配置
```
GET /console/api/workspaces/current/ldap-config
```

#### 创建/更新 LDAP 配置
```
POST /console/api/workspaces/current/ldap-config
Content-Type: application/json

{
  "enabled": true,
  "server_url": "ldap://your-ldap-server:389",
  "bind_dn": "cn=admin,dc=example,dc=com",
  "bind_password": "your-password",
  "base_dn": "dc=example,dc=com",
  "user_filter": "(objectClass=person)",
  "user_id_attribute": "uid",
  "user_email_attribute": "mail",
  "user_name_attribute": "cn",
  "sync_interval": 30
}
```

#### 测试 LDAP 连接
```
POST /console/api/workspaces/current/ldap-config/test
```

### 2. 用户管理

#### 获取 LDAP 用户列表
```
GET /console/api/workspaces/current/ldap-users?enabled_only=false&page=1&limit=20
```

#### 更新用户状态
```
PUT /console/api/workspaces/current/ldap-users/{user_id}/status
Content-Type: application/json

{
  "enabled": true
}
```

### 3. 同步管理

#### 手动触发同步
```
POST /console/api/workspaces/current/ldap-sync
```

#### 获取同步统计
```
GET /console/api/workspaces/current/ldap-stats
```

## 部署说明

### 1. 安装依赖
确保 `ldap3` 包已安装（已添加到 pyproject.toml）

### 2. 启动服务
按照正常流程启动 Dify 服务，LDAP 功能将自动加载。

### 3. 启用 Celery Beat
如果使用自动同步功能，确保 Celery Beat 服务正在运行：

```bash
celery -A app.celery beat --loglevel=info
```

## 安全注意事项

1. **密码安全**: LDAP 绑定密码存储在数据库中，建议使用加密存储
2. **网络安全**: 建议使用 LDAPS（LDAP over SSL）连接
3. **权限控制**: 只有管理员和所有者可以配置 LDAP 设置
4. **日志记录**: 所有 LDAP 操作都会记录日志，便于审计

## 故障排除

### 常见问题

1. **连接失败**
   - 检查 LDAP 服务器 URL 和端口
   - 验证网络连通性
   - 确认绑定 DN 和密码正确

2. **用户同步失败**
   - 检查用户过滤器语法
   - 验证用户属性映射
   - 确认基础 DN 设置正确

3. **认证失败**
   - 确认用户在 LDAP 中存在
   - 检查用户密码是否正确
   - 验证用户 DN 路径

### 日志查看

检查应用日志中的 LDAP 相关信息：

```bash
grep -i ldap /path/to/app.log
```

## 扩展功能

模块设计支持以下扩展：

1. **LDAP 组同步**: 可扩展支持 LDAP 组到租户角色的映射
2. **SSO 集成**: 可与 SAML/OIDC 等 SSO 方案集成
3. **多 LDAP 服务器**: 支持配置多个 LDAP 服务器
4. **高级属性映射**: 支持更复杂的用户属性映射规则

## 支持

如有问题，请查看：
1. 应用日志文件
2. Celery 任务日志
3. LDAP 服务器日志