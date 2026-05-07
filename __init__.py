from . import models

def create_access_rights(env):
    """Create access rights after module installation"""
    
    models = ['customer', 'vehicle', 'estimate', 'estimate.line', 'job.card', 'job.card.line', 'procurement', 'procurement.line']
    group_user = env.ref('base.group_user')
    
    # Get or create groups if they exist
    group_open_job = env.ref('job_card_management.group_can_open_job_card', raise_if_not_found=False)
    group_approve_estimate = env.ref('job_card_management.group_can_approve_estimate', raise_if_not_found=False)
    group_approve_procurement = env.ref('job_card_management.group_can_approve_procurement', raise_if_not_found=False)
    
    for model_name in models:
        model = env['ir.model'].search([('model', '=', model_name)], limit=1)
        if model:
            # Basic user access
            existing = env['ir.model.access'].search([('model_id', '=', model.id), ('group_id', '=', group_user.id)], limit=1)
            if existing:
                # UPDATE existing access to ensure all permissions are True
                existing.write({
                    'perm_read': True,
                    'perm_write': True,
                    'perm_create': True,
                    'perm_unlink': True,
                })
            else:
                # CREATE new access
                env['ir.model.access'].create({
                    'name': f'{model_name}_user_access',
                    'model_id': model.id,
                    'group_id': group_user.id,
                    'perm_read': True,
                    'perm_write': True,
                    'perm_create': True,
                    'perm_unlink': True,
                })
            
            # Special group access for job.card
            if model_name == 'job.card' and group_open_job:
                existing = env['ir.model.access'].search([('model_id', '=', model.id), ('group_id', '=', group_open_job.id)], limit=1)
                if existing:
                    existing.write({
                        'perm_read': True,
                        'perm_write': True,
                        'perm_create': True,
                        'perm_unlink': True,
                    })
                else:
                    env['ir.model.access'].create({
                        'name': 'job_card_opener',
                        'model_id': model.id,
                        'group_id': group_open_job.id,
                        'perm_read': True,
                        'perm_write': True,
                        'perm_create': True,
                        'perm_unlink': True,
                    })
            
            # Special group access for job.card.line
            if model_name == 'job.card.line' and group_open_job:
                existing = env['ir.model.access'].search([('model_id', '=', model.id), ('group_id', '=', group_open_job.id)], limit=1)
                if existing:
                    existing.write({
                        'perm_read': True,
                        'perm_write': True,
                        'perm_create': True,
                        'perm_unlink': True,
                    })
                else:
                    env['ir.model.access'].create({
                        'name': 'job_card_line_opener',
                        'model_id': model.id,
                        'group_id': group_open_job.id,
                        'perm_read': True,
                        'perm_write': True,
                        'perm_create': True,
                        'perm_unlink': True,
                    })
            
            # Special group access for estimate
            if model_name == 'estimate' and group_approve_estimate:
                existing = env['ir.model.access'].search([('model_id', '=', model.id), ('group_id', '=', group_approve_estimate.id)], limit=1)
                if existing:
                    existing.write({
                        'perm_read': True,
                        'perm_write': True,
                        'perm_create': True,
                        'perm_unlink': True,
                    })
                else:
                    env['ir.model.access'].create({
                        'name': 'estimate_approver',
                        'model_id': model.id,
                        'group_id': group_approve_estimate.id,
                        'perm_read': True,
                        'perm_write': True,
                        'perm_create': True,
                        'perm_unlink': True,
                    })
            
            # Special group access for procurement
            if model_name == 'procurement' and group_approve_procurement:
                existing = env['ir.model.access'].search([('model_id', '=', model.id), ('group_id', '=', group_approve_procurement.id)], limit=1)
                if existing:
                    existing.write({
                        'perm_read': True,
                        'perm_write': True,
                        'perm_create': True,
                        'perm_unlink': True,
                    })
                else:
                    env['ir.model.access'].create({
                        'name': 'procurement_approver',
                        'model_id': model.id,
                        'group_id': group_approve_procurement.id,
                        'perm_read': True,
                        'perm_write': True,
                        'perm_create': True,
                        'perm_unlink': True,
                    })