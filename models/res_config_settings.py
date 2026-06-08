from odoo import fields, models

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    job_card_default_terms = fields.Html(
        string='Default Terms and Conditions',
        config_parameter='job_card_management.default_terms',
        help="Default terms and conditions added to new quotations."
    )
