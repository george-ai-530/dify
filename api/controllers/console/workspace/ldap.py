"""
LDAP 管理控制器
提供 LDAP 配置和用户管理的 API 端点
"""
import logging
from typing import Dict, List

from flask import request
from flask_restx import Resource, fields, reqparse
from sqlalchemy.exc import IntegrityError
from werkzeug.exceptions import BadRequest, Forbidden, NotFound

from controllers.console import api
from controllers.console.workspace.error import AccountNotFoundError
from controllers.console.wraps import account_initialization_required, cloud_edition_billing_resource_check
from libs.login import login_required
from models.account import LdapConfig, LdapUser
from services.errors.account import NoPermissionError
from services.ldap_service import LdapService, LdapServiceError
from tasks.ldap_sync_task import sync_single_tenant_ldap_users_task, test_ldap_connection_task

logger = logging.getLogger(__name__)

# API 模型定义
ldap_config_model = api.model('LdapConfig', {
    'enabled': fields.Boolean(required=True, description='是否启用 LDAP'),
    'server_url': fields.String(required=True, description='LDAP 服务器 URL'),
    'bind_dn': fields.String(required=True, description='绑定 DN'),
    'bind_password': fields.String(required=True, description='绑定密码'),
    'base_dn': fields.String(required=True, description='基础 DN'),
    'user_filter': fields.String(required=False, description='用户过滤器'),
    'user_id_attribute': fields.String(required=False, description='用户 ID 属性', default='uid'),
    'user_email_attribute': fields.String(required=False, description='用户邮箱属性', default='mail'),
    'user_name_attribute': fields.String(required=False, description='用户姓名属性', default='cn'),
    'sync_interval': fields.Integer(required=False, description='同步间隔（秒）', default=30),
})

ldap_config_response_model = api.model('LdapConfigResponse', {
    'id': fields.String(description='配置 ID'),
    'tenant_id': fields.String(description='租户 ID'),
    'enabled': fields.Boolean(description='是否启用'),
    'server_url': fields.String(description='LDAP 服务器 URL'),
    'bind_dn': fields.String(description='绑定 DN'),
    'base_dn': fields.String(description='基础 DN'),
    'user_filter': fields.String(description='用户过滤器'),
    'user_id_attribute': fields.String(description='用户 ID 属性'),
    'user_email_attribute': fields.String(description='用户邮箱属性'),
    'user_name_attribute': fields.String(description='用户姓名属性'),
    'sync_interval': fields.Integer(description='同步间隔（秒）'),
    'last_sync_at': fields.DateTime(description='最后同步时间'),
    'created_at': fields.DateTime(description='创建时间'),
    'updated_at': fields.DateTime(description='更新时间'),
})

ldap_user_model = api.model('LdapUser', {
    'id': fields.String(description='用户 ID'),
    'ldap_uid': fields.String(description='LDAP 用户标识'),
    'email': fields.String(description='邮箱'),
    'name': fields.String(description='姓名'),
    'enabled': fields.Boolean(description='是否启用'),
    'account_id': fields.String(description='关联账户 ID'),
    'last_sync_at': fields.DateTime(description='最后同步时间'),
    'created_at': fields.DateTime(description='创建时间'),
})

ldap_test_result_model = api.model('LdapTestResult', {
    'success': fields.Boolean(description='测试是否成功'),
    'message': fields.String(description='测试结果消息'),
})

ldap_sync_stats_model = api.model('LdapSyncStats', {
    'total': fields.Integer(description='总用户数'),
    'created': fields.Integer(description='新创建用户数'),
    'updated': fields.Integer(description='更新用户数'),
    'disabled': fields.Integer(description='禁用用户数'),
})


@api.route('/workspaces/current/ldap-config')
class LdapConfigResource(Resource):
    """LDAP 配置管理"""

    @login_required
    @account_initialization_required
    def get(self):
        """获取当前工作空间的 LDAP 配置"""
        from flask_login import current_user
        
        if not current_user.is_admin_or_owner:
            raise NoPermissionError()
        
        config = LdapService.get_ldap_config(current_user.current_tenant_id)
        if not config:
            return {'enabled': False}, 200
        
        return {
            'id': config.id,
            'tenant_id': config.tenant_id,
            'enabled': config.enabled,
            'server_url': config.server_url,
            'bind_dn': config.bind_dn,
            'base_dn': config.base_dn,
            'user_filter': config.user_filter,
            'user_id_attribute': config.user_id_attribute,
            'user_email_attribute': config.user_email_attribute,
            'user_name_attribute': config.user_name_attribute,
            'sync_interval': config.sync_interval,
            'last_sync_at': config.last_sync_at.isoformat() if config.last_sync_at else None,
            'created_at': config.created_at.isoformat(),
            'updated_at': config.updated_at.isoformat(),
        }, 200

    @login_required
    @account_initialization_required
    @api.expect(ldap_config_model)
    @api.marshal_with(ldap_config_response_model)
    def post(self):
        """创建或更新 LDAP 配置"""
        from flask_login import current_user
        
        if not current_user.is_admin_or_owner:
            raise NoPermissionError()
        
        try:
            data = request.get_json()
            config = LdapService.create_or_update_ldap_config(current_user.current_tenant_id, data)
            
            return {
                'id': config.id,
                'tenant_id': config.tenant_id,
                'enabled': config.enabled,
                'server_url': config.server_url,
                'bind_dn': config.bind_dn,
                'base_dn': config.base_dn,
                'user_filter': config.user_filter,
                'user_id_attribute': config.user_id_attribute,
                'user_email_attribute': config.user_email_attribute,
                'user_name_attribute': config.user_name_attribute,
                'sync_interval': config.sync_interval,
                'last_sync_at': config.last_sync_at.isoformat() if config.last_sync_at else None,
                'created_at': config.created_at.isoformat(),
                'updated_at': config.updated_at.isoformat(),
            }, 200
            
        except Exception as e:
            logger.error(f"创建/更新 LDAP 配置失败: {str(e)}")
            raise BadRequest(f"配置失败: {str(e)}")


@api.route('/workspaces/current/ldap-config/test')
class LdapConfigTestResource(Resource):
    """LDAP 连接测试"""

    @login_required
    @account_initialization_required
    @api.marshal_with(ldap_test_result_model)
    def post(self):
        """测试 LDAP 连接"""
        from flask_login import current_user
        
        if not current_user.is_admin_or_owner:
            raise NoPermissionError()
        
        try:
            # 使用 Celery 任务进行异步测试
            task = test_ldap_connection_task.delay(current_user.current_tenant_id)
            result = task.get(timeout=30)  # 30秒超时
            
            return result, 200
            
        except Exception as e:
            logger.error(f"LDAP 连接测试失败: {str(e)}")
            return {
                'success': False,
                'message': f"测试失败: {str(e)}"
            }, 500


@api.route('/workspaces/current/ldap-users')
class LdapUsersResource(Resource):
    """LDAP 用户管理"""

    @login_required
    @account_initialization_required
    def get(self):
        """获取 LDAP 用户列表"""
        from flask_login import current_user
        
        if not current_user.is_admin_or_owner:
            raise NoPermissionError()
        
        parser = reqparse.RequestParser()
        parser.add_argument('enabled_only', type=bool, default=False, help='仅显示启用的用户')
        parser.add_argument('page', type=int, default=1, help='页码')
        parser.add_argument('limit', type=int, default=20, help='每页数量')
        args = parser.parse_args()
        
        try:
            users = LdapService.get_ldap_users(current_user.current_tenant_id, args['enabled_only'])
            
            # 简单分页
            start = (args['page'] - 1) * args['limit']
            end = start + args['limit']
            page_users = users[start:end]
            
            result = []
            for user in page_users:
                result.append({
                    'id': user.id,
                    'ldap_uid': user.ldap_uid,
                    'email': user.email,
                    'name': user.name,
                    'enabled': user.enabled,
                    'account_id': user.account_id,
                    'last_sync_at': user.last_sync_at.isoformat(),
                    'created_at': user.created_at.isoformat(),
                })
            
            return {
                'users': result,
                'total': len(users),
                'page': args['page'],
                'limit': args['limit'],
                'has_more': end < len(users)
            }, 200
            
        except Exception as e:
            logger.error(f"获取 LDAP 用户列表失败: {str(e)}")
            raise BadRequest(f"获取用户列表失败: {str(e)}")


@api.route('/workspaces/current/ldap-users/<string:user_id>/status')
class LdapUserStatusResource(Resource):
    """LDAP 用户状态管理"""

    @login_required
    @account_initialization_required
    def put(self, user_id):
        """更新 LDAP 用户启用/禁用状态"""
        from flask_login import current_user
        
        if not current_user.is_admin_or_owner:
            raise NoPermissionError()
        
        parser = reqparse.RequestParser()
        parser.add_argument('enabled', type=bool, required=True, help='是否启用用户')
        args = parser.parse_args()
        
        try:
            user = LdapService.update_ldap_user_status(
                current_user.current_tenant_id, 
                user_id, 
                args['enabled']
            )
            
            return {
                'id': user.id,
                'ldap_uid': user.ldap_uid,
                'email': user.email,
                'name': user.name,
                'enabled': user.enabled,
                'account_id': user.account_id,
                'last_sync_at': user.last_sync_at.isoformat(),
                'created_at': user.created_at.isoformat(),
            }, 200
            
        except Exception as e:
            logger.error(f"更新 LDAP 用户状态失败: {str(e)}")
            raise BadRequest(f"更新用户状态失败: {str(e)}")


@api.route('/workspaces/current/ldap-sync')
class LdapSyncResource(Resource):
    """LDAP 同步管理"""

    @login_required
    @account_initialization_required
    @api.marshal_with(ldap_sync_stats_model)
    def post(self):
        """手动触发 LDAP 用户同步"""
        from flask_login import current_user
        
        if not current_user.is_admin_or_owner:
            raise NoPermissionError()
        
        try:
            # 使用 Celery 任务进行异步同步
            task = sync_single_tenant_ldap_users_task.delay(current_user.current_tenant_id)
            stats = task.get(timeout=300)  # 5分钟超时
            
            return stats, 200
            
        except Exception as e:
            logger.error(f"LDAP 用户同步失败: {str(e)}")
            raise BadRequest(f"同步失败: {str(e)}")


@api.route('/workspaces/current/ldap-stats')
class LdapStatsResource(Resource):
    """LDAP 统计信息"""

    @login_required
    @account_initialization_required
    def get(self):
        """获取 LDAP 同步统计信息"""
        from flask_login import current_user
        
        if not current_user.is_admin_or_owner:
            raise NoPermissionError()
        
        try:
            stats = LdapService.get_sync_stats(current_user.current_tenant_id)
            return stats, 200
            
        except Exception as e:
            logger.error(f"获取 LDAP 统计信息失败: {str(e)}")
            raise BadRequest(f"获取统计信息失败: {str(e)}")