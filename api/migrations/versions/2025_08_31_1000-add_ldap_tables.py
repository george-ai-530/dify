"""add_ldap_tables

Revision ID: 2025_08_31_1000-add_ldap_tables
Revises: a45f4dfde53b
Create Date: 2025-08-31 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '2025_08_31_1000-add_ldap_tables'
down_revision = '8d289573e1da'
branch_labels = None
depends_on = None


def upgrade():
    """Create LDAP configuration and user tables"""
    
    # 创建 ldap_configs 表
    op.create_table(
        'ldap_configs',
        sa.Column('id', sa.String(255), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('tenant_id', sa.String(255), nullable=False),
        sa.Column('enabled', sa.Boolean, server_default=sa.text('false'), nullable=False),
        sa.Column('server_url', sa.String(512), nullable=False),
        sa.Column('bind_dn', sa.String(512), nullable=False),
        sa.Column('bind_password', sa.String(512), nullable=False),
        sa.Column('base_dn', sa.String(512), nullable=False),
        sa.Column('user_filter', sa.String(512), nullable=True),
        sa.Column('user_id_attribute', sa.String(64), server_default=sa.text("'uid'"), nullable=False),
        sa.Column('user_email_attribute', sa.String(64), server_default=sa.text("'mail'"), nullable=False),
        sa.Column('user_name_attribute', sa.String(64), server_default=sa.text("'cn'"), nullable=False),
        sa.Column('sync_interval', sa.Integer, server_default=sa.text('30'), nullable=False),
        sa.Column('last_sync_at', sa.DateTime, nullable=True),
        sa.Column('created_at', sa.DateTime, server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.Column('updated_at', sa.DateTime, server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.PrimaryKeyConstraint('id', name='ldap_config_pkey'),
        sa.UniqueConstraint('tenant_id', name='unique_tenant_ldap_config'),
    )
    
    # 创建 ldap_users 表
    op.create_table(
        'ldap_users',
        sa.Column('id', sa.String(255), server_default=sa.text('uuid_generate_v4()'), nullable=False),
        sa.Column('tenant_id', sa.String(255), nullable=False),
        sa.Column('account_id', sa.String(255), nullable=True),
        sa.Column('ldap_uid', sa.String(255), nullable=False),
        sa.Column('email', sa.String(255), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('ldap_dn', sa.String(512), nullable=False),
        sa.Column('enabled', sa.Boolean, server_default=sa.text('true'), nullable=False),
        sa.Column('last_sync_at', sa.DateTime, server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.Column('created_at', sa.DateTime, server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.Column('updated_at', sa.DateTime, server_default=sa.text('CURRENT_TIMESTAMP(0)'), nullable=False),
        sa.PrimaryKeyConstraint('id', name='ldap_user_pkey'),
        sa.UniqueConstraint('tenant_id', 'ldap_uid', name='unique_tenant_ldap_user'),
    )
    
    # 创建索引
    op.create_index('ldap_user_account_id_idx', 'ldap_users', ['account_id'])
    op.create_index('ldap_user_tenant_id_idx', 'ldap_users', ['tenant_id'])
    

def downgrade():
    """Drop LDAP tables"""
    op.drop_index('ldap_user_tenant_id_idx', table_name='ldap_users')
    op.drop_index('ldap_user_account_id_idx', table_name='ldap_users')
    op.drop_table('ldap_users')
    op.drop_table('ldap_configs')