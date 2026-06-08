import uuid
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.http import request, route as http_route
from odoo.addons.portal.controllers.portal import CustomerPortal  # type: ignore


LINE_CATEGORY_SELECTION = [
    ('parts', 'Parts'),
    ('repairs', 'Repairs'),
    ('paint', 'Paint'),
    ('fittings', 'Fittings'),
    ('labour', 'Labour'),
]


class Estimate(models.Model):
    _name = 'estimate'
    _description = 'Quotation / Quote'
    _inherit = ['job.card.backend.navigation.mixin', 'mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    def _default_name(self):
        last = self.search([], order='name desc', limit=1)
        if last and last.name and last.name.startswith('EST-'):
            last_num = int(last.name[4:])
            new_num = last_num + 1
        else:
            new_num = 1001
        return f'EST-{new_num}'

    name = fields.Char(
        string='Estimate Number',
        required=True,
        default=_default_name,
        readonly=True,
        copy=False,
    )
    customer_id = fields.Many2one('customer', string='Customer', required=True)
    vehicle_id = fields.Many2one(
        'vehicle',
        string='Vehicle Details',
        required=True,
        domain="['|', ('customer_id', '=', customer_id), ('customer_id', '=', False)]",
    )
    vehicle_reg_number = fields.Char(
        related='vehicle_id.registration_number',
        string='Vehicle REG Number',
        readonly=True,
    )
    vehicle_name = fields.Char(
        related='vehicle_id.name',
        string='Vehicle Name',
        readonly=True,
    )
    vehicle_model = fields.Char(related='vehicle_id.model', string='Vehicle Model', readonly=True)
    vehicle_make = fields.Char(related='vehicle_id.make', string='Vehicle Make', readonly=True)
    vehicle_chassis_number = fields.Char(related='vehicle_id.chassis_number', string='Vehicle Chassis', readonly=True)
    vehicle_year_of_manufacture = fields.Integer(related='vehicle_id.year_of_manufacture', string='Year of Manufacture', readonly=True)
    vehicle_display = fields.Char(
        string='Vehicle',
        compute='_compute_vehicle_display',
        readonly=True,
    )
    analytic_account_id = fields.Many2one('account.analytic.account', string='Analytic Account')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('converted', 'Converted'),
    ], default='draft')
    has_job_card = fields.Boolean(string='Job Card Opened', default=False)
    job_card_id = fields.Many2one('job.card', string='Linked Job Card')
    sale_order_id = fields.Many2one('sale.order', string='Sales Order')
    terms_and_conditions = fields.Html(
        string='Terms and Conditions',
        default=lambda self: self.env['ir.config_parameter'].sudo().get_param('job_card_management.default_terms', '')
    )
    estimate_lines = fields.One2many('estimate.line', 'estimate_id', string='Lines', copy=True)
    parts_line_ids = fields.One2many(
        'estimate.line', 'estimate_id', string='Parts Lines',
        domain=[('line_category', '=', 'parts')],
    )
    repairs_line_ids = fields.One2many(
        'estimate.line', 'estimate_id', string='Repairs Lines',
        domain=[('line_category', '=', 'repairs')],
    )
    paint_line_ids = fields.One2many(
        'estimate.line', 'estimate_id', string='Paint Lines',
        domain=[('line_category', '=', 'paint')],
    )
    fittings_line_ids = fields.One2many(
        'estimate.line', 'estimate_id', string='Fittings Lines',
        domain=[('line_category', '=', 'fittings')],
    )
    labour_line_ids = fields.One2many(
        'estimate.line', 'estimate_id', string='Labour Lines',
        domain=[('line_category', '=', 'labour')],
    )
    access_token = fields.Char('Access Token', copy=False)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if 'customer_id' in fields_list and not res.get('customer_id'):
            if self.env.context.get('default_customer_id'):
                res['customer_id'] = self.env.context['default_customer_id']
            elif (
                self.env.context.get('active_model') == 'customer'
                and self.env.context.get('active_id')
            ):
                res['customer_id'] = self.env.context['active_id']
        return res

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

    def write(self, vals):
        locked_fields = {'customer_id', 'name', 'vehicle_id'}
        if locked_fields.intersection(vals.keys()):
            for estimate in self:
                if estimate.state in ('approved', 'converted'):
                    raise UserError(_(
                        'Cannot change customer, estimate number, or vehicle on an approved '
                        'estimate. Use Redo first.'
                    ))
        return super().write(vals)

    @api.depends('estimate_lines.price_subtotal', 'estimate_lines.price_total')
    def _compute_totals(self):
        for estimate in self:
            lines = estimate.estimate_lines.filtered(lambda l: not l.display_type)
            estimate.amount_untaxed = sum(lines.mapped('price_subtotal'))
            estimate.amount_tax = sum(lines.mapped(lambda l: l.price_total - l.price_subtotal))
            estimate.amount_total = estimate.amount_untaxed + estimate.amount_tax

    amount_untaxed = fields.Float(string='Total Excl', compute='_compute_totals')
    amount_tax = fields.Float(string='Total Tax', compute='_compute_totals')
    amount_total = fields.Float(string='Total Incl', compute='_compute_totals')

    def _job_card_form_action_xmlid(self):
        return 'job_card_management.action_estimate'

    @api.depends('vehicle_id', 'vehicle_id.registration_number', 'vehicle_id.make', 'vehicle_id.model')
    def _compute_vehicle_display(self):
        Vehicle = self.env['vehicle']
        for estimate in self:
            if estimate.vehicle_id:
                estimate.vehicle_display = Vehicle._format_display_name(estimate.vehicle_id)
            else:
                estimate.vehicle_display = False

    @api.onchange('customer_id')
    def _onchange_customer_id(self):
        if self.vehicle_id and self.vehicle_id.customer_id not in (False, self.customer_id):
            self.vehicle_id = False

    def _generate_access_token(self):
        if not self.access_token:
            self.access_token = str(uuid.uuid4())

    def get_portal_url(self, suffix=None, report_type=None):
        self.ensure_one()
        if not self.access_token:
            self._generate_access_token()
        url = f'/my/estimates/{self.id}?access_token={self.access_token}'
        if suffix:
            url += f'/{suffix}'
        if report_type:
            url += f'&report_type={report_type}'
        return url

    def action_submit(self):
        self.state = 'submitted'

    def action_approve(self):
        if not self.env.user.has_group('job_card_management.group_can_approve_estimate'):
            raise UserError(_('You are not allowed to approve estimates.'))
        self.state = 'approved'
        self._generate_access_token()

        if self.customer_id.partner_id:
            sale_order = self.env['sale.order'].create({
                'partner_id': self.customer_id.partner_id.id,
                'origin': self.name,
            })
            self.sale_order_id = sale_order.id
            for line in self.estimate_lines:
                line_vals = {'order_id': sale_order.id}
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

    def action_redo(self):
        if not self.env.user.has_group('job_card_management.group_can_redo_estimate'):
            raise UserError(_('You do not have permission to redo estimates. Please contact your administrator.'))

        for estimate in self:
            if estimate.state not in ('approved', 'converted'):
                raise UserError(_('Only approved or converted estimates can be redone.'))
            if estimate.sale_order_id:
                sale_order = estimate.sale_order_id
                if sale_order.state not in ('cancel', 'done'):
                    sale_order.action_cancel()
                estimate.sale_order_id = False
            estimate.state = 'draft'

    def action_open_job_card(self):
        if not self.env.user.has_group('job_card_management.group_can_open_job_card'):
            raise UserError(_('You are not allowed to open a job.'))
        if self.has_job_card:
            raise UserError(_('Job card already opened for this estimate.'))

        today = fields.Date.today()
        job_card = self.env['job.card'].create({
            'estimate_id': self.id,
            'customer_id': self.customer_id.id,
            'vehicle_id': self.vehicle_id.id,
            'start_date': today,
        })
        for line in self.estimate_lines:
            line_vals = {
                'job_card_id': job_card.id,
                'sequence': line.sequence,
                'display_type': line.display_type,
                'name': line.name,
                'line_category': line.line_category,
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
            'state': 'converted',
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'job.card',
            'res_id': job_card.id,
            'view_mode': 'form',
        }

    def action_preview_estimate(self):
        report = self.env.ref('job_card_management.action_report_estimate')
        return {
            'type': 'ir.actions.act_url',
            'url': f'/report/pdf/{report.report_name}/{self.id}',
            'target': 'new',
        }

    def action_preview_portal(self):
        self.ensure_one()
        if not self.access_token:
            self._generate_access_token()
        return {
            'type': 'ir.actions.act_url',
            'url': self.get_portal_url(),
            'target': 'self',
        }

    def action_send_whatsapp(self):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'WhatsApp Integration',
                'message': 'WhatsApp module is not installed. Please install the WhatsApp integration module.',
                'type': 'warning',
                'sticky': False,
            },
        }

    def action_send_email(self):
        self.ensure_one()
        report = self.env.ref('job_card_management.action_report_estimate', raise_if_not_found=False)
        if not report:
            raise UserError('Estimate report not found.')

        pdf_content, _ = self.env['ir.actions.report']._render_qweb_pdf(report.report_name, [self.id])

        attachment = self.env['ir.attachment'].create({
            'name': f'{self.name}.pdf',
            'raw': pdf_content,
            'res_model': 'estimate',
            'res_id': self.id,
            'mimetype': 'application/pdf',
        })

        customer_email = self.customer_id.email
        if not customer_email:
            raise UserError('Customer does not have an email address.')

        reg = self.vehicle_reg_number or ''
        body = f"""
        <p>Dear {self.customer_id.name},</p>
        <p>Please find attached estimate <strong>{self.name}</strong> for your vehicle
        <strong>{reg}</strong> ({self.vehicle_model}).</p>
        <p>Total: <strong>${self.amount_total:,.2f}</strong></p>
        <p>Best regards,</p>
        """

        compose_ctx = {
            'default_model': 'estimate',
            'default_res_ids': [self.id],
            'default_use_template': False,
            'default_composition_mode': 'comment',
            'default_email_layout_xmlid': 'mail.mail_notification_layout',
            'default_attachment_ids': [(4, attachment.id)],
            'default_subject': f'Estimate {self.name} for {reg}',
            'default_body': body,
            'default_email_to': customer_email,
            'default_partner_ids': [],
        }
        if self.customer_id.partner_id:
            compose_ctx['default_partner_ids'] = [(4, self.customer_id.partner_id.id)]

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
    _description = 'Quotation Line'
    _order = 'sequence, id'

    estimate_id = fields.Many2one('estimate', string='Estimate', ondelete='cascade')
    sequence = fields.Integer(string='Sequence', default=10)
    line_category = fields.Selection(
        LINE_CATEGORY_SELECTION,
        string='Category',
        default='parts',
        required=True,
    )
    display_type = fields.Selection([
        ('line_section', 'Section'),
        ('line_note', 'Note'),
    ], string='Line Type')
    name = fields.Text(string='Description')
    product_id = fields.Many2one('product.product', string='Product')
    product_uom_id = fields.Many2one(
        'uom.uom',
        string='Unit of Measure',
        default=lambda self: self.env.ref('uom.product_uom_unit', raise_if_not_found=False).id,
    )
    quantity = fields.Float(string='Quantity', default=1.0)
    unit_price = fields.Float(string='Unit Price')
    tax_ids = fields.Many2many('account.tax', string='Taxes')
    discount = fields.Float(string='Discount (%)', default=0.0)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('line_category'):
                vals['line_category'] = self.env.context.get('default_line_category', 'parts')
        return super().create(vals_list)

    @api.depends('quantity', 'unit_price', 'discount', 'tax_ids')
    def _compute_amount(self):
        for line in self:
            if line.display_type:
                line.price_subtotal = 0
                line.tax_amount = 0
                line.price_total = 0
            else:
                subtotal = line.quantity * line.unit_price
                if line.discount:
                    subtotal = subtotal * (1 - line.discount / 100.0)
                line.price_subtotal = subtotal
                if line.tax_ids:
                    taxes_data = line.tax_ids.compute_all(
                        line.unit_price, None, line.quantity, line.product_id,
                    )
                    if line.discount:
                        for key in ('total_included', 'total_excluded'):
                            if key in taxes_data:
                                taxes_data[key] = taxes_data[key] * (1 - line.discount / 100.0)
                    line.price_total = taxes_data.get('total_included', subtotal)
                    line.price_subtotal = taxes_data.get('total_excluded', subtotal)
                    line.tax_amount = line.price_total - line.price_subtotal
                else:
                    line.price_total = subtotal
                    line.tax_amount = 0

    price_subtotal = fields.Float(string='Subtotal', compute='_compute_amount')
    tax_amount = fields.Float(string='Tax', compute='_compute_amount')
    price_total = fields.Float(string='Amount', compute='_compute_amount')


class EstimatePortal(CustomerPortal):

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'estimate_count' in counters:
            values['estimate_count'] = request.env['estimate'].search_count([])
        return values

    @http_route(['/my/estimates', '/my/estimates/page/<int:page>'], type='http', auth="user", website=True)
    def portal_my_estimates(self, page=1, **kw):
        estimates = request.env['estimate'].search([])
        return request.render('job_card_management.portal_my_estimates', {
            'estimates': estimates,
            'page_name': 'estimates',
        })

    @http_route(['/my/estimates/<int:estimate_id>'], type='http', auth="public", website=True)
    def portal_estimate_detail(self, estimate_id, access_token=None, **kw):
        estimate = request.env['estimate'].sudo().browse(estimate_id)
        if not estimate.exists():
            return request.not_found()
        if access_token and estimate.access_token != access_token:
            return request.not_found()
        return request.render('job_card_management.portal_estimate_detail', {
            'estimate': estimate,
            'page_name': 'estimate',
        })
