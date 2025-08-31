"""
LDAP 用户同步服务
提供 LDAP 连接、用户同步、认证等功能
"""
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import ldap3
from ldap3 import ALL, Connection, Server
from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from extensions.ext_database import db
from libs.datetime_utils import naive_utc_now
from models.account import Account, AccountStatus, LdapConfig, LdapUser, Tenant, TenantAccountJoin, TenantAccountRole
from services.account_service import AccountService
from services.errors.account import AccountNotFoundError

logger = logging.getLogger(__name__)


class LdapServiceError(Exception):
    """LDAP 服务异常基类"""
    pass


class LdapConnectionError(LdapServiceError):
    """LDAP 连接异常"""
    pass


class LdapAuthError(LdapServiceError):
    """LDAP 认证异常"""
    pass


class LdapUserNotFoundError(LdapServiceError):
    """LDAP 用户未找到异常"""
    pass


class LdapService:
    """LDAP 服务类"""

    @staticmethod
    def get_ldap_config(tenant_id: str) -> Optional[LdapConfig]:
        """获取租户的 LDAP 配置"""
        return db.session.query(LdapConfig).filter_by(tenant_id=tenant_id, enabled=True).first()

    @staticmethod
    def create_or_update_ldap_config(tenant_id: str, config_data: Dict) -> LdapConfig:
        """创建或更新 LDAP 配置"""
        config = db.session.query(LdapConfig).filter_by(tenant_id=tenant_id).first()
        
        if config:
            # 更新现有配置
            for key, value in config_data.items():
                if hasattr(config, key):
                    setattr(config, key, value)
            config.updated_at = naive_utc_now()
        else:
            # 创建新配置
            config = LdapConfig(
                tenant_id=tenant_id,
                **config_data
            )
            db.session.add(config)
        
        db.session.commit()
        return config

    @staticmethod
    def test_ldap_connection(config: LdapConfig) -> Tuple[bool, str]:
        """测试 LDAP 连接"""
        try:
            server = Server(config.server_url, get_info=ALL)
            conn = Connection(server, config.bind_dn, config.bind_password, auto_bind=True)
            conn.unbind()
            return True, "连接成功"
        except Exception as e:
            logger.error(f"LDAP 连接测试失败: {str(e)}")
            return False, f"连接失败: {str(e)}"

    @staticmethod
    def _create_ldap_connection(config: LdapConfig) -> Connection:
        """创建 LDAP 连接"""
        try:
            server = Server(config.server_url, get_info=ALL)
            conn = Connection(server, config.bind_dn, config.bind_password, auto_bind=True)
            return conn
        except Exception as e:
            logger.error(f"创建 LDAP 连接失败: {str(e)}")
            raise LdapConnectionError(f"无法连接到 LDAP 服务器: {str(e)}")

    @staticmethod
    def search_ldap_users(config: LdapConfig) -> List[Dict]:
        """从 LDAP 搜索用户"""
        conn = LdapService._create_ldap_connection(config)
        
        try:
            # 构建搜索过滤器
            search_filter = config.user_filter or "(objectClass=person)"
            
            # 搜索用户
            conn.search(
                search_base=config.base_dn,
                search_filter=search_filter,
                attributes=[
                    config.user_id_attribute,
                    config.user_email_attribute,
                    config.user_name_attribute,
                    'dn'
                ]
            )
            
            users = []
            for entry in conn.entries:
                user_data = {
                    'uid': str(getattr(entry, config.user_id_attribute, '')),
                    'email': str(getattr(entry, config.user_email_attribute, '')),
                    'name': str(getattr(entry, config.user_name_attribute, '')),
                    'dn': str(entry.entry_dn)
                }
                
                # 验证必需字段
                if user_data['uid'] and user_data['email']:
                    users.append(user_data)
                else:
                    logger.warning(f"跳过无效用户: {user_data}")
            
            return users
            
        except Exception as e:
            logger.error(f"搜索 LDAP 用户失败: {str(e)}")
            raise LdapServiceError(f"搜索用户失败: {str(e)}")
        finally:
            conn.unbind()

    @staticmethod
    def sync_ldap_users(tenant_id: str) -> Dict[str, int]:
        """同步 LDAP 用户到本地数据库"""
        config = LdapService.get_ldap_config(tenant_id)
        if not config:
            raise LdapServiceError("未找到启用的 LDAP 配置")

        # 获取 LDAP 用户
        ldap_users = LdapService.search_ldap_users(config)
        
        stats = {
            'total': len(ldap_users),
            'created': 0,
            'updated': 0,
            'disabled': 0
        }
        
        # 获取当前存在的 LDAP 用户
        existing_users = db.session.query(LdapUser).filter_by(tenant_id=tenant_id).all()
        existing_uids = {user.ldap_uid for user in existing_users}
        current_uids = {user['uid'] for user in ldap_users}
        
        # 同步用户
        for user_data in ldap_users:
            ldap_user = db.session.query(LdapUser).filter_by(
                tenant_id=tenant_id,
                ldap_uid=user_data['uid']
            ).first()
            
            if ldap_user:
                # 更新现有用户
                ldap_user.email = user_data['email']
                ldap_user.name = user_data['name']
                ldap_user.ldap_dn = user_data['dn']
                ldap_user.last_sync_at = naive_utc_now()
                ldap_user.updated_at = naive_utc_now()
                
                # 如果用户之前被禁用，重新启用
                if not ldap_user.enabled:
                    ldap_user.enabled = True
                
                stats['updated'] += 1
            else:
                # 创建新用户
                ldap_user = LdapUser(
                    tenant_id=tenant_id,
                    ldap_uid=user_data['uid'],
                    email=user_data['email'],
                    name=user_data['name'],
                    ldap_dn=user_data['dn'],
                    enabled=True,
                    last_sync_at=naive_utc_now()
                )
                db.session.add(ldap_user)
                stats['created'] += 1
        
        # 禁用不再存在的用户
        for uid in existing_uids - current_uids:
            ldap_user = db.session.query(LdapUser).filter_by(
                tenant_id=tenant_id,
                ldap_uid=uid
            ).first()
            if ldap_user and ldap_user.enabled:
                ldap_user.enabled = False
                ldap_user.updated_at = naive_utc_now()
                stats['disabled'] += 1
        
        # 更新同步时间
        config.last_sync_at = naive_utc_now()
        config.updated_at = naive_utc_now()
        
        db.session.commit()
        
        logger.info(f"LDAP 用户同步完成: {stats}")
        return stats

    @staticmethod
    def authenticate_ldap_user(tenant_id: str, email: str, password: str) -> Optional[Account]:
        """LDAP 用户认证"""
        config = LdapService.get_ldap_config(tenant_id)
        if not config:
            raise LdapServiceError("未找到启用的 LDAP 配置")

        # 查找 LDAP 用户
        ldap_user = db.session.query(LdapUser).filter_by(
            tenant_id=tenant_id,
            email=email,
            enabled=True
        ).first()
        
        if not ldap_user:
            raise LdapUserNotFoundError("LDAP 用户不存在或已被禁用")

        # 尝试 LDAP 认证
        try:
            server = Server(config.server_url, get_info=ALL)
            conn = Connection(server, ldap_user.ldap_dn, password, auto_bind=True)
            conn.unbind()
        except Exception as e:
            logger.warning(f"LDAP 认证失败 - 用户: {email}, 错误: {str(e)}")
            raise LdapAuthError("LDAP 认证失败")

        # 创建或获取本地账户
        account = LdapService._get_or_create_local_account(ldap_user, tenant_id)
        return account

    @staticmethod
    def _get_or_create_local_account(ldap_user: LdapUser, tenant_id: str) -> Account:
        """获取或创建本地账户"""
        if ldap_user.account_id:
            # 尝试获取现有账户
            account = db.session.query(Account).filter_by(id=ldap_user.account_id).first()
            if account:
                return account

        # 查找邮箱是否已存在
        existing_account = db.session.query(Account).filter_by(email=ldap_user.email).first()
        if existing_account:
            # 关联现有账户
            ldap_user.account_id = existing_account.id
            ldap_user.updated_at = naive_utc_now()
            db.session.commit()
            return existing_account

        # 创建新账户
        account = Account(
            name=ldap_user.name,
            email=ldap_user.email,
            status=AccountStatus.ACTIVE.value,
            initialized_at=naive_utc_now()
        )
        db.session.add(account)
        db.session.flush()  # 获取 account.id

        # 关联 LDAP 用户
        ldap_user.account_id = account.id
        ldap_user.updated_at = naive_utc_now()

        # 添加到租户
        tenant_join = TenantAccountJoin(
            tenant_id=tenant_id,
            account_id=account.id,
            role=TenantAccountRole.NORMAL.value
        )
        db.session.add(tenant_join)
        
        db.session.commit()
        return account

    @staticmethod
    def get_ldap_users(tenant_id: str, enabled_only: bool = False) -> List[LdapUser]:
        """获取租户的 LDAP 用户列表"""
        query = db.session.query(LdapUser).filter_by(tenant_id=tenant_id)
        if enabled_only:
            query = query.filter_by(enabled=True)
        return query.order_by(LdapUser.name).all()

    @staticmethod
    def update_ldap_user_status(tenant_id: str, ldap_user_id: str, enabled: bool) -> LdapUser:
        """更新 LDAP 用户启用/禁用状态"""
        ldap_user = db.session.query(LdapUser).filter_by(
            id=ldap_user_id,
            tenant_id=tenant_id
        ).first()
        
        if not ldap_user:
            raise LdapUserNotFoundError("LDAP 用户不存在")

        ldap_user.enabled = enabled
        ldap_user.updated_at = naive_utc_now()
        db.session.commit()
        
        return ldap_user

    @staticmethod
    def get_sync_stats(tenant_id: str) -> Dict:
        """获取同步统计信息"""
        config = LdapService.get_ldap_config(tenant_id)
        if not config:
            return {}

        total_users = db.session.query(func.count(LdapUser.id)).filter_by(tenant_id=tenant_id).scalar()
        enabled_users = db.session.query(func.count(LdapUser.id)).filter_by(
            tenant_id=tenant_id, enabled=True
        ).scalar()
        
        return {
            'total_users': total_users,
            'enabled_users': enabled_users,
            'disabled_users': total_users - enabled_users,
            'last_sync_at': config.last_sync_at.isoformat() if config.last_sync_at else None,
            'sync_interval': config.sync_interval
        }