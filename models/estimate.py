import random
import string

from odoo import models, fields, api, _
from odoo.exceptions import UserError


class Estimate(models.Model):
    _name = 'estimate'
    _description = 'Estimate / Quote'
    _order = 'id desc'
    
    def _default_name(self):
        last = self.search([], order='name desc', limit=1)
        if last and last.name and last.name.startswith('JOB-'):
            last_num = int(last.name[4:])
            new_num = last_num + 1
        else:
            new_num = 1001  

        return f'JOB-{new_num}' 

    name = fields.Char(string='Estimate Number', required=True, default=_default_name, help='Unique reference for this estimate')
    customer_id = fields.Many2one('customer', string='Customer', required=True, help='Select the customer for this estimate')
    vehicle_id = fields.Many2one('vehicle', string='Vehicle Details', required=True, domain="[('customer_id', '=', customer_id)]", help='Pick a vehicle owned by the selected customer')
    vehicle_name = fields.Char(related='vehicle_id.name', string='Vehicle Name', readonly=True, help='The name of the selected vehicle')
    vehicle_model = fields.Char(related='vehicle_id.model', string='Vehicle Model', readonly=True, help='The model of the selected vehicle')
    analytic_account_id = fields.Many2one('account.analytic.account', string='Analytic Account', help='Optional analytic account for this estimate')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('converted', 'Converted')
    ], default='draft')
    has_job_card = fields.Boolean(string='Job Card Opened', default=False)
    job_card_id = fields.Many2one('job.card', string='Linked Job Card')
    sale_order_id = fields.Many2one('sale.order', string='Sales Order')

    estimate_lines = fields.One2many('estimate.line', 'estimate_id', string='Lines')

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

    @api.depends('estimate_lines.price_subtotal', 'estimate_lines.price_total')
    def _compute_totals(self):
        for estimate in self:
            estimate.amount_untaxed = sum(line.price_subtotal for line in estimate.estimate_lines if not line.display_type)
            estimate.amount_tax = sum(line.price_total - line.price_subtotal for line in estimate.estimate_lines if not line.display_type)
            estimate.amount_total = estimate.amount_untaxed + estimate.amount_tax

    amount_untaxed = fields.Float(string='Untaxed Amount', compute='_compute_totals', store=False)
    amount_tax = fields.Float(string='Tax Amount', compute='_compute_totals', store=False)
    amount_total = fields.Float(string='Total', compute='_compute_totals', store=False)

    @api.onchange('customer_id')
    def _onchange_customer_id(self):
        self.vehicle_id = False

    def action_submit(self):
        self.state = 'submitted'

    def action_approve(self):
        if not self.env.user.has_group('job_card_management.group_can_approve_estimate'):
            raise UserError(_('You are not allowed to approve estimates.'))
        self.state = 'approved'
        
        if self.customer_id.partner_id:
            sale_order = self.env['sale.order'].create({
                'partner_id': self.customer_id.partner_id.id,
                'origin': self.name,
            })
            self.sale_order_id = sale_order.id
            for line in self.estimate_lines:
                line_vals = {
                    'order_id': sale_order.id,
                }
                if line.display_type:
                    line_vals['display_type'] = line.display_type
                    line_vals['name'] = line.name
                else:
                    line_vals['name'] = line.name or (line.product_id.name if line.product_id else '')
                    line_vals['product_uom_qty'] = line.quantity
                    line_vals['price_unit'] = line.unit_price
                    if line.product_id:
                        line_vals['product_id'] = line.product_id.id
                    if line.product_uom_id:
                        line_vals['product_uom_id'] = line.product_uom_id.id
                    if line.tax_ids:
                        line_vals['tax_ids'] = [(6, 0, line.tax_ids.ids)]
                    if line.discount:
                        line_vals['discount'] = line.discount
                    if self.analytic_account_id:
                        line_vals['analytic_distribution'] = {str(self.analytic_account_id.id): 100.0}
                self.env['sale.order.line'].create(line_vals)
            sale_order.action_confirm()
        else:
            raise UserError(_('Customer has no linked partner. Please save the customer again.'))

    def action_open_job_card(self):
        if not self.env.user.has_group('job_card_management.group_can_open_job_card'):
            raise UserError(_('You are not allowed to open a job.'))
        if self.has_job_card:
            raise UserError(_('Job card already opened for this estimate.'))
        
        job_card = self.env['job.card'].create({
            'estimate_id': self.id,
            'customer_id': self.customer_id.id,
            'vehicle_id': self.vehicle_id.id,
        })
        for line in self.estimate_lines:
            line_vals = {
                'job_card_id': job_card.id,
                'sequence': line.sequence,
                'display_type': line.display_type,
                'name': line.name,
                'product_id': line.product_id.id if line.product_id else False,
                'product_uom_id': line.product_uom_id.id if line.product_uom_id else False,
                'quantity': line.quantity,
                'unit_price': line.unit_price,
                'discount': line.discount,
            }
            if line.tax_ids:
                line_vals['tax_ids'] = [(6, 0, line.tax_ids.ids)]
            self.env['job.card.line'].create(line_vals)
        self.write({
            'has_job_card': True,
            'job_card_id': job_card.id,
            'state': 'converted'
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'job.card',
            'res_id': job_card.id,
            'view_mode': 'form',
        }

    def action_preview_estimate(self):
        return {
            'type': 'ir.actions.act_url',
            'url': f'/job_card_management/report/view/estimate/{self.id}/job_card_management.action_report_estimate/Estimate%20Report',
            'target': 'self',
        }

    # ============================================================
    # NEW: WhatsApp Share
    # ============================================================
    def action_send_whatsapp(self):
        """Show notification that WhatsApp module is not installed"""
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('WhatsApp PDF Module Not Installed'),
                'message': _('module is not installed.'),
                'type': 'warning',
                'sticky': False,
            }
        }

    # ============================================================
    # NEW: Email Estimate
    def action_send_email(self):
        """Open the email compose wizard with estimate PDF attached"""
        self.ensure_one()
        
        # Get the report
        report = self.env.ref('job_card_management.action_report_estimate', raise_if_not_found=False)
        if not report:
            raise UserError('Estimate report not found.')
        
        # Generate PDF
        pdf_content, _ = self.env['ir.actions.report']._render_qweb_pdf(
            report.report_name, [self.id]
        )
        
        # Create attachment
        attachment = self.env['ir.attachment'].create({
            'name': f'{self.name}.pdf',
            'raw': pdf_content,
            'res_model': 'estimate',
            'res_id': self.id,
            'mimetype': 'application/pdf',
        })
        
        # Get customer email
        customer_email = self.customer_id.email
        if not customer_email:
            raise UserError('Customer does not have an email address. Please add an email to the customer record.')
        
        # Build email body
        body = f"""
        <p>Dear {self.customer_id.name},</p>
        <p>Please find attached the estimate <strong>{self.name}</strong> for your vehicle <strong>{self.vehicle_name}</strong> ({self.vehicle_model}).</p>
        <p>Total Amount: <strong>${self.amount_total:,.2f}</strong></p>
        <p>If you have any questions, please don't hesitate to contact us.</p>
        <p>Best regards,</p>
        """
        
        # Open mail compose wizard
        compose_ctx = {
            'default_model': 'estimate',
            'default_res_ids': [self.id],
            'default_use_template': False,
            'default_composition_mode': 'comment',
            'default_email_layout_xmlid': 'mail.mail_notification_layout',
            'default_attachment_ids': [(4, attachment.id)],
            'default_subject': f'Estimate {self.name} for {self.vehicle_name}',
            'default_body': body,
        }
        
        # Add customer email if available
        if customer_email:
            compose_ctx['default_email_to'] = customer_email
        
        return {
            'type': 'ir.actions.act_window',
            'name': 'Send Estimate by Email',
            'res_model': 'mail.compose.message',
            'view_mode': 'form',
            'view_id': self.env.ref('mail.email_compose_message_wizard_form').id,
            'target': 'new',
            'context': compose_ctx,
        }

class EstimateLine(models.Model):
    _name = 'estimate.line'
    _description = 'Estimate Line'
    _order = 'sequence, id'

    estimate_id = fields.Many2one('estimate', string='Estimate', ondelete='cascade')
    sequence = fields.Integer(string='Sequence', default=10)
    display_type = fields.Selection([
        ('line_section', 'Section'),
        ('line_note', 'Note'),
    ], string='Line Type', help='Choose section or note line to add headers and descriptions.')
    name = fields.Text(string='Description')
    product_id = fields.Many2one('product.product', string='Product')
    product_uom_id = fields.Many2one('uom.uom', string='Unit of Measure', default=lambda self: self.env.ref('uom.product_uom_unit', raise_if_not_found=False).id if self.env.ref('uom.product_uom_unit', raise_if_not_found=False) else False)
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
                    taxes_data = line.tax_ids.compute_all(
                        line.unit_price,
                        None,
                        line.quantity,
                        line.product_id
                    )
                    if line.discount:
                        for key in ['total_included', 'total_excluded']:
                            if key in taxes_data:
                                taxes_data[key] = taxes_data[key] * (1 - line.discount / 100.0)
                    line.price_total = taxes_data.get('total_included', subtotal)
                else:
                    line.price_total = subtotal
    
    price_subtotal = fields.Float(string='Subtotal', compute='_compute_amount', store=False)
    price_total = fields.Float(string='Amount', compute='_compute_amount', store=False)