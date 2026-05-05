import random
import string

from odoo import models, fields, api, _
from odoo.exceptions import UserError

class JobCard(models.Model):
    _name = 'job.card'
    _description = 'Job Card'
    _order = 'id desc'

    def _default_name(self):
        random_part = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        return 'JCB-%s-TEX' % random_part

    name = fields.Char(string='Job Card Number', required=True, default=_default_name)
    estimate_id = fields.Many2one('estimate', string='Estimate', required=True)
    customer_id = fields.Many2one('customer', string='First Customer', required=True)  # Changed
    second_customer_id = fields.Many2one('customer', string='Second Customer (Insurance)', help='Added at final stage')  # Changed
    excess_percentage = fields.Float(string='Excess (%)', help='Percentage paid by first customer')
    insurance_percentage = fields.Float(string='Insurance Percentage (%)', compute='_compute_insurance_pct', store=True)
    vehicle_id = fields.Many2one('vehicle', string='Vehicle', required=True)  # Changed
    vehicle_name = fields.Char(related='vehicle_id.name', string='Vehicle Name', readonly=True)
    vehicle_model = fields.Char(related='vehicle_id.model', string='Vehicle Model', readonly=True)
    vehicle_display = fields.Char(string='Vehicle', compute='_compute_vehicle_display')
    analytic_account_id = fields.Many2one('account.analytic.account', string='Analytic Account')
    start_date = fields.Date(string='Start Date Expected')
    end_date = fields.Date(string='End Date Expected')
    job_card_lines = fields.One2many('job.card.line', 'job_card_id', string='Job Card Lines')

    @api.model
    def create(self, vals):
        if isinstance(vals, list):
            for v in vals:
                if not v.get('name') or v.get('name') == 'New':
                    v['name'] = self._default_name()
        else:
            if not vals.get('name') or vals.get('name') == 'New':
                vals['name'] = self._default_name()
        return super().create(vals)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('approved', 'Approved'),
        ('in_progress', 'In Progress'),
        ('requisition_started', 'Requisition Started'),
        ('completed', 'Completed'),
        ('delivered', 'Delivered')
    ], default='draft')
    total_amount = fields.Float(string='Total Amount', compute='_compute_total', store=True)

    @api.depends('excess_percentage')
    def _compute_insurance_pct(self):
        for rec in self:
            rec.insurance_percentage = 100 - rec.excess_percentage if rec.excess_percentage else 0.0

    @api.depends('vehicle_id')
    def _compute_vehicle_display(self):
        for rec in self:
            if rec.vehicle_id:
                rec.vehicle_display = f"[{rec.vehicle_id.registration_number}] {rec.vehicle_id.name}"
            else:
                rec.vehicle_display = ""

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
        # Create procurement lines from job card lines
        for line in self.job_card_lines.filtered(lambda l: l.product_id and not l.display_type):
            self.env['procurement.line'].create({
                'procurement_id': procurement.id,
                'product_id': line.product_id.id,
                'quantity': line.quantity,
                'type': 'purchase_order',  # Assume purchase order for external procurement
            })
        self.state = 'in_progress'
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'procurement',
            'res_id': procurement.id,
            'view_mode': 'form',
        }

    def action_finalize_job_card(self):
        if not self.second_customer_id:
            raise UserError(_('Please add Insurance Company as Second Customer before finalizing.'))
        if not self.excess_percentage:
            raise UserError(_('Please set the Excess percentage.'))
        
        # Find income account
        income_account = self.env['account.account'].search([('account_type', '=', 'income')], limit=1)
        if not income_account:
            raise UserError(_('No income account configured. Please set up an income account in Accounting.'))
        
        # Create invoice for customer (excess amount)
        customer_lines = []
        for line in self.job_card_lines.filtered(lambda l: not l.display_type and l.price_total > 0):
            customer_price = line.price_total * (self.excess_percentage / 100)
            if customer_price > 0:
                customer_lines.append((0, 0, {
                    'name': line.name or (line.product_id.name if line.product_id else 'Job Card Service'),
                    'quantity': line.quantity,
                    'price_unit': customer_price / line.quantity if line.quantity > 0 else customer_price,
                    'account_id': income_account.id,
                }))
        if customer_lines and self.customer_id.partner_id:
            customer_invoice = self.env['account.move'].create({
                'move_type': 'out_invoice',
                'partner_id': self.customer_id.partner_id.id,
                'invoice_origin': self.name,
                'invoice_line_ids': customer_lines,
            })
            customer_invoice.action_post()
        
        # Create invoice for insurance (insurance portion)
        insurance_lines = []
        for line in self.job_card_lines.filtered(lambda l: not l.display_type and l.price_total > 0):
            insurance_price = line.price_total * (self.insurance_percentage / 100)
            if insurance_price > 0:
                insurance_lines.append((0, 0, {
                    'name': line.name or (line.product_id.name if line.product_id else 'Job Card Service'),
                    'quantity': line.quantity,
                    'price_unit': insurance_price / line.quantity if line.quantity > 0 else insurance_price,
                    'account_id': income_account.id,
                }))
        if insurance_lines and self.second_customer_id.partner_id:
            insurance_invoice = self.env['account.move'].create({
                'move_type': 'out_invoice',
                'partner_id': self.second_customer_id.partner_id.id,
                'invoice_origin': self.name,
                'invoice_line_ids': insurance_lines,
            })
            insurance_invoice.action_post()
        
        self.state = 'delivered'

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