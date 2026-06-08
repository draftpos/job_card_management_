from odoo import api, fields, models

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    job_card_default_terms = fields.Html(
        string='Default Terms and Conditions',
        help="Default terms and conditions added to new quotations."
    )
    
    # Quotation Print Settings
    print_customer_full_details = fields.Boolean(
        string='Print Full Customer Details on Quotations',
        config_parameter='job_card_management.print_customer_full_details',
        default=False
    )
    print_customer_tin = fields.Boolean(
        string='Show TIN Number',
        config_parameter='job_card_management.print_customer_tin',
        default=True
    )
    print_customer_phone = fields.Boolean(
        string='Show Phone',
        config_parameter='job_card_management.print_customer_phone',
        default=True
    )
    print_customer_email = fields.Boolean(
        string='Show Email',
        config_parameter='job_card_management.print_customer_email',
        default=True
    )
    print_customer_address = fields.Boolean(
        string='Show Address',
        config_parameter='job_card_management.print_customer_address',
        default=True
    )

    # Vehicle Required Settings
    vehicle_require_chassis = fields.Boolean(
        string='Require Chassis Number',
        config_parameter='job_card_management.vehicle_require_chassis',
        default=False
    )
    vehicle_require_engine = fields.Boolean(
        string='Require Engine Number',
        config_parameter='job_card_management.vehicle_require_engine',
        default=False
    )
    vehicle_require_year = fields.Boolean(
        string='Require Year of Manufacture',
        config_parameter='job_card_management.vehicle_require_year',
        default=False
    )
    vehicle_require_color = fields.Boolean(
        string='Require Color',
        config_parameter='job_card_management.vehicle_require_color',
        default=False
    )

    @api.model
    def get_values(self):
        res = super(ResConfigSettings, self).get_values()
        res.update(
            job_card_default_terms=self.env['ir.config_parameter'].sudo().get_param('job_card_management.default_terms', default='')
        )
        return res

    def set_values(self):
        super(ResConfigSettings, self).set_values()
        self.env['ir.config_parameter'].sudo().set_param('job_card_management.default_terms', self.job_card_default_terms or '')
