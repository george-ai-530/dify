"""
LDAP 用户同步定时任务
每 30 秒执行一次用户同步
"""
import logging
from datetime import datetime

from celery import shared_task

from extensions.ext_database import db
from models.account import LdapConfig
from services.ldap_service import LdapService

logger = logging.getLogger(__name__)


@shared_task(queue='dataset')
def sync_ldap_users_task():
    """
    LDAP 用户同步任务
    遍历所有启用的 LDAP 配置，执行用户同步
    """
    logger.info("开始执行 LDAP 用户同步任务")
    
    try:
        # 获取所有启用的 LDAP 配置
        configs = db.session.query(LdapConfig).filter_by(enabled=True).all()
        
        if not configs:
            logger.info("未找到启用的 LDAP 配置，跳过同步")
            return
        
        total_synced = 0
        total_errors = 0
        
        for config in configs:
            try:
                logger.info(f"开始同步租户 {config.tenant_id} 的 LDAP 用户")
                
                # 执行同步
                stats = LdapService.sync_ldap_users(config.tenant_id)
                total_synced += stats.get('total', 0)
                
                logger.info(f"租户 {config.tenant_id} 同步完成: {stats}")
                
            except Exception as e:
                total_errors += 1
                logger.error(f"租户 {config.tenant_id} LDAP 同步失败: {str(e)}", exc_info=True)
                continue
        
        logger.info(f"LDAP 用户同步任务完成 - 总计: {total_synced} 用户, {total_errors} 错误")
        
    except Exception as e:
        logger.error(f"LDAP 用户同步任务执行失败: {str(e)}", exc_info=True)
        raise


@shared_task(queue='dataset')
def sync_single_tenant_ldap_users_task(tenant_id: str):
    """
    单个租户的 LDAP 用户同步任务
    
    Args:
        tenant_id: 租户ID
    """
    logger.info(f"开始执行租户 {tenant_id} 的 LDAP 用户同步任务")
    
    try:
        stats = LdapService.sync_ldap_users(tenant_id)
        logger.info(f"租户 {tenant_id} LDAP 用户同步完成: {stats}")
        return stats
        
    except Exception as e:
        logger.error(f"租户 {tenant_id} LDAP 用户同步失败: {str(e)}", exc_info=True)
        raise


@shared_task(queue='dataset')
def test_ldap_connection_task(tenant_id: str):
    """
    测试 LDAP 连接任务
    
    Args:
        tenant_id: 租户ID
    
    Returns:
        dict: 测试结果
    """
    logger.info(f"开始测试租户 {tenant_id} 的 LDAP 连接")
    
    try:
        config = LdapService.get_ldap_config(tenant_id)
        if not config:
            return {"success": False, "message": "未找到 LDAP 配置"}
        
        success, message = LdapService.test_ldap_connection(config)
        result = {"success": success, "message": message}
        
        logger.info(f"租户 {tenant_id} LDAP 连接测试完成: {result}")
        return result
        
    except Exception as e:
        error_msg = f"LDAP 连接测试失败: {str(e)}"
        logger.error(f"租户 {tenant_id} {error_msg}", exc_info=True)
        return {"success": False, "message": error_msg}