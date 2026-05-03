from odoo import models, fields, api, _
from odoo.exceptions import UserError

class JobCard(models.Model):
    _name = 'job.card'
    _description = 'Job Card'
    _order = 'id desc'

    name = fields.Char(string='Job Card Number', required=True, default='New')
    estimate_id = fields.Many2one('estimate', string='Estimate', required=True)
    customer_id = fields.Many2one('customer', string='First Customer', required=True)  # Changed
    second_customer_id = fields.Many2one('customer', string='Second Customer (Insurance)', help='Added at final stage')  # Changed
    excess_value = fields.Float(string='Excess Value (Paid by First Customer)')
    insurance_percentage = fields.Float(string='Insurance Percentage', compute='_compute_insurance_pct', store=True)
    vehicle_id = fields.Many2one('vehicle', string='Vehicle', required=True)  # Changed
    vehicle_name = fields.Char(related='vehicle_id.name', string='Vehicle Name', readonly=True)
    vehicle_model = fields.Char(related='vehicle_id.model', string='Vehicle Model', readonly=True)
    analytic_account_id = fields.Many2one('account.analytic.account', string='Analytic Account')
    job_card_lines = fields.One2many('job.card.line', 'job_card_id', string='Job Card Lines')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('approved', 'Approved'),
        ('in_progress', 'In Progress'),
        ('requisition_started', 'Requisition Started'),
        ('completed', 'Completed')
    ], default='draft')
    total_amount = fields.Float(string='Total Amount', compute='_compute_total', store=True)

    @api.depends('excess_value', 'total_amount')
    def _compute_insurance_pct(self):
        for rec in self:
            if rec.total_amount and rec.excess_value:
                rec.insurance_percentage = 100 - ((rec.excess_value / rec.total_amount) * 100)
            else:
                rec.insurance_percentage = 0.0

    @api.depends('job_card_lines.price_total')
    def _compute_total(self):
        for rec in self:
            rec.total_amount = sum(rec.job_card_lines.filtered(lambda l: not l.display_type).mapped('price_total'))

    def action_approve_job_card(self):
        self.state = 'approved'

    def action_create_requisition(self):
        if self.state != 'approved':
            raise UserError(_('Job card must be approved before creating requisition.'))
        procurement = self.env['procurement'].create({
            'job_card_id': self.id,
        })
        self.state = 'requisition_started'
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'procurement',
            'res_id': procurement.id,
            'view_mode': 'form',
        }

    def action_finalize_job_card(self):
        if not self.second_customer_id:
            raise UserError(_('Please add Insurance Company as Second Customer before finalizing.'))
        self.state = 'completed'

class JobCardLine(models.Model):
    _name = 'job.card.line'
    _description = 'Job Card Line'
    _order = 'sequence, id'

    job_card_id = fields.Many2one('job.card', string='Job Card', ondelete='cascade', required=True)
    sequence = fields.Integer(string='Sequence', default=10)
    display_type = fields.Selection([
        ('line_section', 'Section'),
        ('line_note', 'Note'),
    ], string='Line Type', help='Choose section or note line to add headers and descriptions.')
    name = fields.Text(string='Description')
    product_id = fields.Many2one('product.product', string='Product')
    product_uom_id = fields.Many2one('uom.uom', string='Unit of Measure')
    quantity = fields.Float(string='Quantity', default=1.0)
    unit_price = fields.Float(string='Unit Price')
    tax_ids = fields.Many2many('account.tax', string='Taxes')
    discount = fields.Float(string='Discount (%)', default=0.0)

    @api.depends('quantity', 'unit_price', 'discount', 'tax_ids')
    def _compute_amount(self):
        for line in self:
            if line.display_type:
                line.price_subtotal = 0
                line.price_total = 0
            else:
                subtotal = line.quantity * line.unit_price
                if line.discount:
                    subtotal = subtotal * (1 - line.discount / 100.0)
                line.price_subtotal = subtotal
                if line.tax_ids:
                    taxes = line.tax_ids.compute_all(line.unit_price, None, line.quantity, line.product_id)
                    if line.discount:
                        for key in ['total_included', 'total_excluded']:
                            if key in taxes:
                                taxes[key] = taxes[key] * (1 - line.discount / 100.0)
                    line.price_total = taxes.get('total_included', subtotal)
                else:
                    line.price_total = subtotal

    price_subtotal = fields.Float(string='Subtotal', compute='_compute_amount', store=False)
    price_total = fields.Float(string='Amount', compute='_compute_amount', store=False)