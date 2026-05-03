{
    'name': 'Job Card Management',
    'version': '1.0',
    'category': 'Services',
    'depends': ['sale', 'purchase', 'stock', 'account', 'mail'],
    'data': [
        'security/job_card_groups.xml',
        'security/ir.model.access.csv',
        'views/customer_views.xml',
        'views/vehicle_views.xml',
        'views/estimate_views.xml',
        'views/job_card_views.xml',
        'views/procurement_views.xml',
        'views/menu_views.xml',
    ],
    'installable': True,
    'application': True,
    # 'post_init_hook': 'create_access_rights',
}