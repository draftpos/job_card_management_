import logging
import uuid

from odoo.http import request, route as http_route
from odoo.addons.portal.controllers.portal import CustomerPortal

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

class JobCard(models.Model):
    _name = 'job.card'
    _description = 'Job Card'
    _inherit = ['job.card.backend.navigation.mixin']
    _order = 'id desc'

    def _default_name(self):
        last = self.search([], order='name desc', limit=1)
        if last and last.name and last.name.startswith('JOB-'):
            last_num = int(last.name[4:])  # Get everything after 'JOB-'
            new_num = last_num + 1
        else:
            new_num = 1001  # Starting point

        return f'JOB-{new_num}'  # No zero-padding, just the number

    # def _default_name(self):
    #     random_part = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    #     return 'JOB-%s-TEX' % random_part

    name = fields.Char(
        string='JOB NO:',
        required=True,
        default=_default_name,
        readonly=True,
        copy=False,
    )
    estimate_id = fields.Many2one('estimate', string='Estimate', required=True, readonly=True)
    customer_id = fields.Many2one('customer', string='First Customer', required=True)
    second_customer_id = fields.Many2one('customer', string='Insurance Company', help='Added at final stage')
    order_number = fields.Char(string='Order NO:')
    claims_number = fields.Char(string='Claims NO:')
    excess_percentage = fields.Float(string='Excess (%)', help='Percentage paid by first customer')
    excess_amount = fields.Float(string='Excess AMT', default=0.0)
    excess_warning_reason = fields.Char(string='Excess Zero Reason', help='Reason why excess amount is 0')
    insurance_percentage = fields.Float(string='Insurance Percentage (%)', compute='_compute_insurance_pct', store=True)
    insurance_amount = fields.Float(string='Insurance AMT')

    betterment_percentage = fields.Float(string='Betterment (%)', default=0.0)
    betterment_amount = fields.Float(string='Betterment AMT', default=0.0)

    billing_policy_setting = fields.Char(
        string='Billing Policy',
        compute='_compute_billing_policy_setting',
    )
    betterment_billing_policy_setting = fields.Char(
        string='Betterment Billing Policy',
        compute='_compute_billing_policy_setting',
    )
    enable_betterment_setting = fields.Boolean(
        string='Betterment Enabled',
        compute='_compute_billing_policy_setting',
    )

    @api.depends_context('uid')
    def _compute_billing_policy_setting(self):
        ICP = self.env['ir.config_parameter'].sudo()
        billing_policy = ICP.get_param('job_card_management.job_card_billing_policy', 'percentage')
        betterment_policy = ICP.get_param('job_card_management.betterment_billing_policy', 'percentage')
        enable_betterment = ICP.get_param('job_card_management.enable_betterment', 'False') == 'True'
        for rec in self:
            rec.billing_policy_setting = billing_policy
            rec.betterment_billing_policy_setting = betterment_policy
            rec.enable_betterment_setting = enable_betterment

    vehicle_id = fields.Many2one(
        'vehicle',
        string='Vehicle',
        required=True,
        domain="['|', ('customer_id', '=', customer_id), ('customer_id', '=', False)]",
    )
    vehicle_reg_number = fields.Char(
        related='vehicle_id.registration_number',
        string='REG NO:',
        readonly=True,
    )
    vehicle_model = fields.Char(related='vehicle_id.model_id.name', string='Vehicle Model', readonly=True)
    vehicle_make = fields.Char(related='vehicle_id.make_id.name', string='Vehicle Make', readonly=True)
    vehicle_display = fields.Char(string='Vehicle', compute='_compute_vehicle_display')
    analytic_account_id = fields.Many2one('account.analytic.account', string='Analytic Account')
    technician_ids = fields.Many2many(
        'job.technician',
        'job_card_technician_rel',
        'job_card_id',
        'technician_id',
        string='Technicians',
    )
    supervisor_ids = fields.Many2many(
        'job.technician',
        'job_card_supervisor_rel',
        'job_card_id',
        'technician_id',
        string='Supervisors',
        domain=[('is_supervisor', '=', True)],
    )
    start_date = fields.Date(string='Start Date Expected', required=True)
    end_date = fields.Date(string='End Date Expected')
    job_card_lines = fields.One2many('job.card.line', 'job_card_id', string='Job Card Lines', copy=True)
    parts_line_ids = fields.One2many(
        'job.card.line', 'parts_job_card_id', string='Supply Parts',
        domain=[('line_category', '=', 'parts')], copy=True
    )
    consumables_line_ids = fields.One2many(
        'job.card.line', 'consumables_job_card_id', string='Consumables',
        domain=[('line_category', '=', 'consumables')], copy=True
    )
    repairs_line_ids = fields.One2many(
        'job.card.line', 'repairs_job_card_id', string='Repair Works',
        domain=[('line_category', '=', 'repairs')], copy=True
    )
    paint_line_ids = fields.One2many(
        'job.card.line', 'paint_job_card_id', string='Paint Job',
        domain=[('line_category', '=', 'paint')], copy=True
    )
    sundries_line_ids = fields.One2many(
        'job.card.line', 'sundries_job_card_id', string='Sundries',
        domain=[('line_category', '=', 'sundries')], copy=True
    )
    fittings_line_ids = fields.One2many(
        'job.card.line', 'fittings_job_card_id', string='Fittings',
        domain=[('line_category', '=', 'fittings')], copy=True
    )
    
    # Invoice tracking fields
    invoice_created = fields.Boolean(string='Invoice Created', default=False)
    customer_invoice_id = fields.Many2one('account.move', string='Customer Invoice')
    insurance_invoice_id = fields.Many2one('account.move', string='Insurance Invoice')
    auto_create_invoices = fields.Boolean(string='Auto Create Invoices', default=True,
                                          help='Automatically create invoices when job card is created')
    # Split sale orders linked from the estimate
    customer_sale_order_id = fields.Many2one('sale.order', string='Customer Sale Order')
    insurance_sale_order_id = fields.Many2one('sale.order', string='Insurance Sale Order')
    
    # Add this field
    access_token = fields.Char('Access Token', copy=False)

    # In the JobCard class, replace the _generate_access_token method:
    def _generate_access_token(self):
        """Generate a unique access token for portal access"""
        if not self.access_token:
            self.access_token = str(uuid.uuid4())

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        
        if self.env.context.get('skip_default_lines'):
            return res
            
        cons_prod = self.env['product.product'].search([('name', '=', 'Consumables')], limit=1)
        if not cons_prod:
            cons_prod = self.env['product.product'].create({'name': 'Consumables', 'type': 'service'})
            
        sundries_prod = self.env['product.product'].search([('name', '=', 'Sundries')], limit=1)
        if not sundries_prod:
            sundries_prod = self.env['product.product'].create({'name': 'Sundries', 'type': 'service'})

        cons_lines = res.get('consumables_line_ids', [])
        cons_lines.append((0, 0, {
            'line_category': 'consumables',
            'product_id': cons_prod.id,
            'name': cons_prod.name,
            'quantity': 1.0,
        }))
        res['consumables_line_ids'] = cons_lines

        sundries_lines = res.get('sundries_line_ids', [])
        sundries_lines.append((0, 0, {
            'line_category': 'sundries',
            'product_id': sundries_prod.id,
            'name': sundries_prod.name,
            'quantity': 1.0,
        }))
        res['sundries_line_ids'] = sundries_lines
        
        return res

    def get_portal_url(self, suffix=None, report_type=None):
        """Get the portal URL for this job card"""
        self.ensure_one()
        if not self.access_token:
            self._generate_access_token()
        url = f'/my/jobcards/{self.id}?access_token={self.access_token}'
        if suffix:
            url += f'/{suffix}'
        if report_type:
            url += f'&report_type={report_type}'
        return url

    def _job_card_form_action_xmlid(self):
        return 'job_card_management.action_job_card'

    def _check_schedule_dates(self):
        for rec in self:
            if not rec.start_date:
                raise UserError(_(
                    'Start Date Expected is required before '
                    'saving, confirming, or printing this job card.'
                ))
            if rec.end_date and rec.end_date <= rec.start_date:
                raise UserError(_('End Date Expected must be after Start Date Expected.'))

    def action_preview_job_card(self):
        self._check_schedule_dates()
        report = self.env.ref('job_card_management.report_job_card')
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

    def action_preview_pick_slip(self):
        self._check_schedule_dates()
        report = self.env.ref('job_card_management.report_job_card_pick_slip')
        return {
            'type': 'ir.actions.act_url',
            'url': f'/report/pdf/{report.report_name}/{self.id}',
            'target': 'new',
        }

    @api.model
    def create(self, vals):
        if isinstance(vals, list):
            for v in vals:
                if not v.get('name') or v.get('name') == 'New':
                    v['name'] = self._default_name()
        else:
            if not vals.get('name') or vals.get('name') == 'New':
                vals['name'] = self._default_name()
        
        # Create the job card
        job_card = super().create(vals)
        
        for rec in job_card:
            # NEW: Fetch and assign analytic account after creation
            analytic_account = rec._fetch_analytic_account()
            if analytic_account:
                rec.analytic_account_id = analytic_account.id
            
            # Check if created from estimate
            is_from_estimate = False
            if isinstance(vals, dict) and vals.get('estimate_id'):
                is_from_estimate = True
            elif rec.estimate_id:
                is_from_estimate = True
                
            if not is_from_estimate:
                # Auto-populate Consumables product line
                consumables_product = self.env['product.product'].search(
                    [('name', 'ilike', 'Consumables')], limit=1
                )
                if not consumables_product:
                    consumables_product = self.env['product.product'].create({
                        'name': 'Consumables',
                        'type': 'service'
                    })
                    
                if consumables_product:
                    self.env['job.card.line'].create({
                        'job_card_id': rec.id,
                        'consumables_job_card_id': rec.id,
                        'line_category': 'consumables',
                        'product_id': consumables_product.id,
                        'name': consumables_product.name,
                        'quantity': 1.0,
                        'unit_price': 0.0,
                    })
                    
                # Auto-populate Sundries product line
                sundries_product = self.env['product.product'].search(
                    [('name', 'ilike', 'Sundries')], limit=1
                )
                if not sundries_product:
                    sundries_product = self.env['product.product'].create({
                        'name': 'Sundries',
                        'type': 'service',
                        'default_code': 'SUND',
                    })
                    
                if sundries_product:
                    self.env['job.card.line'].create({
                        'job_card_id': rec.id,
                        'sundries_job_card_id': rec.id,
                        'line_category': 'sundries',
                        'product_id': sundries_product.id,
                        'name': sundries_product.name,
                        'quantity': 1.0,
                        'unit_price': 0.0,
                    })

        job_card._organize_lines()
        return job_card


    def write(self, vals):
        res = super().write(vals)
        self._organize_lines()
        return res

    def _organize_lines(self):
        categories = ['parts', 'consumables', 'repairs', 'paint', 'sundries', 'fittings']
        from .estimate import LINE_CATEGORY_SELECTION
        category_names = dict(LINE_CATEGORY_SELECTION)
        base_seq = {'parts': 1000, 'consumables': 1500, 'repairs': 2000, 'paint': 3000, 'sundries': 3500, 'fittings': 4000}

        for record in self:
            lines = record.job_card_lines
            for cat in categories:
                cat_lines = lines.filtered(lambda l: l.line_category == cat and not l.display_type)
                cat_notes = lines.filtered(lambda l: l.line_category == cat and l.display_type == 'line_note')
                
                if cat_lines or cat_notes:
                    section = lines.filtered(lambda l: l.line_category == cat and l.display_type == 'line_section')
                    if not section:
                        section = self.env['job.card.line'].create({
                            'job_card_id': record.id,
                            'line_category': cat,
                            'display_type': 'line_section',
                            'name': category_names[cat],
                            'sequence': base_seq[cat]
                        })
                    else:
                        section[0].sequence = base_seq[cat]
                    
                    seq = base_seq[cat] + 1
                    for line in (cat_lines + cat_notes).sorted(key=lambda x: getattr(x, 'id', 0) if isinstance(getattr(x, 'id', 0), int) else 0):
                        line.sequence = seq
                        seq += 1
                else:
                    section = lines.filtered(lambda l: l.line_category == cat and l.display_type == 'line_section')
                    if section:
                        section.unlink()





    # NEW: Method to fetch analytic account
    def _fetch_analytic_account(self):
        """
        Create a new analytic account for this job card using the job card number.
        """
        try:
            # Get the default analytic plan
            try:
                project_plan, _other_plans = self.env['account.analytic.plan']._get_all_plans()
            except UserError:
                # If no project plan is configured, create one or use the first available plan
                project_plan = self.env['account.analytic.plan'].search([], limit=1)
                if not project_plan:
                    project_plan = self.env['account.analytic.plan'].create({'name': 'Default'})
            
            if not project_plan:
                _logger.warning("No analytic plan found. Cannot create analytic account.")
                return None
            
            # Create a new analytic account with the job card name
            analytic_account = self.env['account.analytic.account'].create({
                'name': self.name,
                'plan_id': project_plan.id,
            })
            
            return analytic_account
        except Exception as e:
            _logger.error(f"Error creating analytic account for job card {self.name}: {str(e)}")
            return None

    # NEW: Method to create invoices
    def _create_invoices(self):
        """Create invoices for both customer and insurance"""
        if self.invoice_created:
            return False
        
        if not self.second_customer_id:
            raise UserError(_('Please add Insurance Company as Second Customer before creating invoices.'))
        if not self.excess_percentage:
            raise UserError(_('Please set the Excess percentage.'))
        
        # Find income account
        income_account = self.env['account.account'].search([('account_type', '=', 'income')], limit=1)
        if not income_account:
            raise UserError(_('No income account configured. Please set up an income account in Accounting.'))
        
        # Get current date for invoice
        invoice_date = fields.Date.today()
        
        # Create invoice for customer (excess amount)
        customer_lines = self._prepare_invoice_lines('customer', income_account)
        if customer_lines and self.customer_id and self.customer_id.partner_id:
            customer_terms = self.env['ir.config_parameter'].sudo().get_param('job_card_management.customer_invoice_default_terms', default='')
            narration = customer_terms if customer_terms else f"Customer portion of Job Card {self.name}"
            
            customer_invoice = self.env['account.move'].create({
                'move_type': 'out_invoice',
                'partner_id': self.customer_id.partner_id.id,
                'invoice_origin': self.name,
                'invoice_line_ids': customer_lines,
                'invoice_date': invoice_date,
                'narration': narration,
                'ref': f"Job Card: {self.name} - Customer Portion",
            })
            customer_invoice.action_post()
            self.customer_invoice_id = customer_invoice.id
        
        # Create invoice for insurance (insurance portion)
        insurance_lines = self._prepare_invoice_lines('insurance', income_account)
        if insurance_lines and self.second_customer_id and self.second_customer_id.partner_id:
            insurance_terms = self.env['ir.config_parameter'].sudo().get_param('job_card_management.insurance_invoice_default_terms', default='')
            narration = insurance_terms if insurance_terms else f"Insurance portion of Job Card {self.name}"
            
            insurance_invoice = self.env['account.move'].create({
                'move_type': 'out_invoice',
                'is_insurance_invoice': True,
                'partner_id': self.second_customer_id.partner_id.id,
                'invoice_origin': self.name,
                'invoice_line_ids': insurance_lines,
                'invoice_date': invoice_date,
                'narration': narration,
                'ref': f"Job Card: {self.name} - Insurance Portion",
            })
            insurance_invoice.action_post()
            self.insurance_invoice_id = insurance_invoice.id
        
        self.invoice_created = True
        return True

    # NEW: Helper method to prepare invoice lines
    def _prepare_invoice_lines(self, invoice_type, income_account):
        """Prepare invoice lines for either customer or insurance, including sections"""
        lines = []
        
        for line in self.job_card_lines:
            # Include section headers and notes as-is
            if line.display_type:
                invoice_line_vals = {
                    'display_type': line.display_type,
                    'name': line.name,
                }
                lines.append((0, 0, invoice_line_vals))
            # Include product lines with split amounts
            elif line.price_total > 0:
                if invoice_type == 'customer':
                    price = line.price_total * (self.excess_percentage / 100)
                    price_unit = price / line.quantity if line.quantity > 0 else price
                else:  # insurance
                    price = line.quantity * line.rate_2
                    price_unit = line.rate_2
                
                if price > 0:
                    invoice_line_vals = {
                        'name': line.name or (line.product_id.name if line.product_id else 'Job Card Service'),
                        'quantity': line.quantity,
                        'price_unit': price_unit,
                        'account_id': income_account.id,
                    }
                    
                    # Assign analytic account to invoice line if available
                    if self.analytic_account_id:
                        invoice_line_vals['analytic_distribution'] = {
                            str(self.analytic_account_id.id): 100.0
                        }
                    
                    lines.append((0, 0, invoice_line_vals))
        
        return lines

    is_cash = fields.Boolean(string='Cash Payment', default=False)
    cash_receipt_ref = fields.Char(string='Receipt/Reference No.')

    inventory_issue_ids = fields.One2many('job.inventory.issue', 'job_card_id', string='Inventory Issues')
    inventory_issue_count = fields.Integer(string='Inventory Issues Count', compute='_compute_inventory_issue_count')
    all_inventory_issued = fields.Boolean(string='All Inventory Issued', compute='_compute_all_inventory_issued', store=True)

    consumable_issue_ids = fields.One2many('job.consumable.issue', 'job_card_id', string='Consumable Issues')
    consumable_issue_count = fields.Integer(string='Consumable Issues Count', compute='_compute_consumable_issue_count')
    all_consumables_issued = fields.Boolean(string='All Consumables Issued', tracking=True, default=False)

    @api.depends('consumable_issue_ids', 'consumable_issue_ids.state')
    def _compute_consumable_issue_count(self):
        for rec in self:
            rec.consumable_issue_count = len(rec.consumable_issue_ids.filtered(lambda i: i.state == 'issued'))

    @api.depends('inventory_issue_ids', 'inventory_issue_ids.state')
    def _compute_inventory_issue_count(self):
        for rec in self:
            rec.inventory_issue_count = len(rec.inventory_issue_ids.filtered(lambda i: i.state == 'issued'))

    @api.depends('parts_line_ids', 'parts_line_ids.quantity', 'parts_line_ids.product_id',
                 'consumables_line_ids', 'consumables_line_ids.quantity', 'consumables_line_ids.product_id',
                 'paint_line_ids', 'paint_line_ids.quantity', 'paint_line_ids.product_id',
                 'sundries_line_ids', 'sundries_line_ids.quantity', 'sundries_line_ids.product_id',
                 'fittings_line_ids', 'fittings_line_ids.quantity', 'fittings_line_ids.product_id',
                 'repairs_line_ids', 'repairs_line_ids.quantity', 'repairs_line_ids.product_id',
                 'inventory_issue_ids.state', 'inventory_issue_ids.issue_line_ids.issued_qty')
    def _compute_all_inventory_issued(self):
        allow_service = self.env['ir.config_parameter'].sudo().get_param('job_card_management.allow_service_requisition', 'False') == 'True'
        for rec in self:
            all_lines = (
                rec.parts_line_ids |
                rec.consumables_line_ids |
                rec.paint_line_ids |
                rec.sundries_line_ids |
                rec.fittings_line_ids |
                rec.repairs_line_ids
            ).filtered(
                lambda l: not l.display_type and l.product_id
            )
            
            if not allow_service:
                all_lines = all_lines.filtered(lambda l: l.product_id.type in ('product', 'consu'))
                
            if not all_lines:
                rec.all_inventory_issued = True
                continue

            active_issues = rec.inventory_issue_ids.filtered(lambda i: i.state in ('issued', 'partially_issued'))
            completed_procurements = self.env['procurement'].search([
                ('job_card_id', '=', rec.id),
                ('state', '=', 'purchase_order_created')
            ])

            all_issued = True
            for product in all_lines.mapped('product_id'):
                required_qty = sum(all_lines.filtered(lambda l: l.product_id == product).mapped('quantity'))
                issued_qty = sum(
                    active_issues.mapped('issue_line_ids')
                    .filtered(lambda il: il.product_id == product)
                    .mapped('issued_qty')
                )
                
                # Only count internal transfers that have actually been marked delivered
                delivered_transfer_qty = sum(
                    completed_procurements.mapped('procurement_lines')
                    .filtered(lambda pl: pl.type == 'internal_transfer' and pl.receipt_status == 'delivered' and pl.product_id.id == product.id)
                    .mapped('quantity')
                )
                issued_qty += delivered_transfer_qty
                
                if issued_qty < required_qty:
                    all_issued = False
                    break
                    
            rec.all_inventory_issued = all_issued

    def action_issue_inventory(self):
        self.ensure_one()
        all_lines = (
            self.parts_line_ids |
            self.consumables_line_ids |
            self.paint_line_ids |
            self.sundries_line_ids |
            self.fittings_line_ids |
            self.repairs_line_ids
        ).filtered(lambda l: l.display_type not in ('line_section', 'line_note') and l.product_id)
        if not all_lines:
            raise UserError(_('There are no product lines to issue for this job card.'))

        existing = self.inventory_issue_ids.filtered(lambda i: i.state in ('draft', 'confirmed', 'partially_issued'))[:1]
        if existing:
            existing._onchange_source_location()
            return {
                'type': 'ir.actions.act_window',
                'name': _('Issue Inventory'),
                'res_model': 'job.inventory.issue',
                'res_id': existing.id,
                'view_mode': 'form',
                'target': 'current',
            }

        issue = self.env['job.inventory.issue'].create({
            'job_card_id': self.id,
        })
        issue.action_populate_from_job_card()
            
        return {
            'type': 'ir.actions.act_window',
            'name': _('Issue Inventory'),
            'res_model': 'job.inventory.issue',
            'res_id': issue.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_issue_consumables(self):
        self.ensure_one()
        all_lines = (
            self.consumables_line_ids |
            self.paint_line_ids |
            self.sundries_line_ids |
            self.parts_line_ids
        ).filtered(lambda l: l.display_type not in ('line_section', 'line_note') and l.product_id)
        if not all_lines:
            raise UserError(_('There are no consumable lines to issue.'))

        issue = self.env['job.consumable.issue'].create({
            'job_card_id': self.id,
        })
        issue.action_populate_from_job_card()
            
        return {
            'type': 'ir.actions.act_window',
            'name': _('Issue Consumables'),
            'res_model': 'job.consumable.issue',
            'res_id': issue.id,
            'view_mode': 'form',
            'target': 'current',
        }
            
    state = fields.Selection([
        ('draft', 'Draft'),
        ('approved', 'Approved'),
        ('pending_inventory', 'Pending Inventory Issue'),
        ('inventory_issued', 'Inventory Issued'),
        ('pending_items', 'Pending Items'),
        ('in_progress', 'In Progress'),
        ('requisition_started', 'Requisition Started'),
        ('completed', 'Completed'),
        ('delivered', 'Delivered')
    ], default='draft')
    total_amount = fields.Float(string='Total Amount', compute='_compute_total', store=True)

    payment_state = fields.Selection([
        ('not_paid', 'Not Paid'),
        ('in_payment', 'In Payment'),
        ('paid', 'Paid'),
        ('partial', 'Partially Paid'),
        ('reversed', 'Reversed'),
        ('invoicing_legacy', 'Invoicing App Legacy'),
    ], string='Payment Status', tracking=True, default='not_paid')
    
    authorization_type = fields.Selection([
        ('file', 'File'),
        ('link', 'Link')
    ], string='Authorization Type', default='file')
    authorization_letter = fields.Binary(string='Authorization Letter')
    authorization_letter_filename = fields.Char(string='Authorization Letter Filename')
    authorization_link = fields.Char(string='Authorization Link')


    amount_untaxed = fields.Float(string='Total Excl', compute='_compute_total', store=True)
    amount_tax = fields.Float(string='Total Tax', compute='_compute_total', store=True)
    amount_total = fields.Float(string='Total Incl', compute='_compute_total', store=True)

    job_cost_count = fields.Integer(string='Job Cost', compute='_compute_job_cost_count')
    job_cost_total = fields.Float(string='Job Cost Total', compute='_compute_job_cost_count')

    def _compute_job_cost_count(self):
        JobCost = self.env['job.cost']
        for rec in self:
            cost = JobCost.search([('job_card_id', '=', rec.id)], limit=1)
            rec.job_cost_count = 1 if cost else 0
            
            # Dynamically compute the expected total cost so it's always up-to-date on the smart button
            total = 0.0
            for line in rec.job_card_lines.filtered(lambda l: not l.display_type):
                cost_price = JobCost._get_latest_cost(line.product_id)
                total += line.quantity * cost_price
                
            issued_consumables = rec.consumable_issue_ids.filtered(lambda i: i.state == 'issued')
            for issue in issued_consumables:
                for issue_line in issue.issue_line_ids.filtered(lambda l: l.issued_qty > 0):
                    cost_price = issue_line.product_id.standard_price
                    total += issue_line.issued_qty * cost_price
                    
            rec.job_cost_total = total

    def action_view_inventory_issues(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Inventory Issues'),
            'res_model': 'job.inventory.issue',
            'view_mode': 'list,form',
            'domain': [('job_card_id', '=', self.id)],
            'context': {'default_job_card_id': self.id},
        }

    def action_view_consumables_issues(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Consumable Issues'),
            'res_model': 'job.consumable.issue.line',
            'view_mode': 'list,form',
            'domain': [('issue_id.job_card_id', '=', self.id), ('issue_id.state', '=', 'issued')],
        }

    def action_view_job_cost(self):
        self.ensure_one()
        cost = self.env['job.cost'].search([('job_card_id', '=', self.id)], limit=1)
        if not cost:
            cost = self.env['job.cost'].create({'job_card_id': self.id})
        cost.compute_costs()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Job Cost'),
            'res_model': 'job.cost',
            'res_id': cost.id,
            'view_mode': 'form',
            'target': 'current',
        }

# Workflow actions with validations - function to reopen job card added at the end
    def action_reopen(self):
        """Reopen a completed or delivered job card back to draft"""
        # Check permission
        if not self.env.user.has_group('job_card_management.group_can_reopen_job_card'):
            raise UserError(_('You do not have permission to reopen job cards. Please contact your administrator.'))
        
        for rec in self:
            if rec.state not in ('completed', 'delivered'):
                raise UserError(_('Only completed or delivered job cards can be reopened.'))
            if rec.estimate_id and rec.estimate_id.sale_order_id:
                sale_order = rec.estimate_id.sale_order_id
                if sale_order.state not in ('cancel', 'done'):
                    sale_order.action_cancel()
            rec.state = 'draft'

    @api.depends('excess_amount', 'betterment_amount', 'amount_total', 'second_customer_id')
    def _compute_insurance_pct(self):
        for rec in self:
            amount = rec.amount_total or 0.0
            if not rec.second_customer_id:
                rec.insurance_amount = 0.0
                rec.insurance_percentage = 0.0
            else:
                rec.insurance_amount = amount - (rec.excess_amount + rec.betterment_amount)
                if amount > 0:
                    rec.insurance_percentage = (rec.insurance_amount / amount) * 100.0
                else:
                    rec.insurance_percentage = 0.0

    @api.onchange('second_customer_id')
    def _onchange_insurance_company_defaults(self):
        if not self.second_customer_id:
            self.excess_amount = 0.0
            self.betterment_amount = 0.0

    @api.depends('vehicle_id', 'vehicle_id.registration_number', 'vehicle_id.make_id.name', 'vehicle_id.model_id.name')
    def _compute_vehicle_display(self):
        for rec in self:
            if rec.vehicle_id:
                reg = rec.vehicle_id.registration_number or ''
                make_model = ' '.join(
                    p for p in [rec.vehicle_id.make_id.name, rec.vehicle_id.model_id.name] if p
                )
                rec.vehicle_display = f"[{reg}] {make_model}".strip()
            else:
                rec.vehicle_display = ""

    @api.onchange('betterment_percentage', 'amount_total')
    def _onchange_betterment_percentage(self):
        if self.betterment_billing_policy_setting == 'percentage':
            if self.amount_total:
                self.betterment_amount = (self.betterment_percentage / 100) * self.amount_total
            else:
                self.betterment_amount = 0.0

    @api.constrains('authorization_letter_filename')
    def _check_authorization_file_extension(self):
        for rec in self:
            if rec.authorization_letter_filename:
                allowed_extensions = ('.pdf', '.txt', '.doc', '.docx')
                if not rec.authorization_letter_filename.lower().endswith(allowed_extensions):
                    raise ValidationError("The authorization letter must be a PDF, TXT, DOC, or DOCX file.")

    @api.constrains('excess_amount', 'betterment_amount', 'amount_total')
    def _check_insurance_amounts(self):
        for rec in self:
            if rec.excess_amount < 0 or rec.betterment_amount < 0:
                raise ValidationError("Excess and Betterment amounts must be positive.")
            if round(rec.excess_amount + rec.betterment_amount, 2) > round(rec.amount_total, 2):
                raise ValidationError("The sum of Excess and Betterment amounts cannot exceed the Total Invoice amount.")

    @api.depends(
        'job_card_lines.price_total', 'job_card_lines.price_subtotal', 'job_card_lines.tax_amount',
        'parts_line_ids.price_subtotal', 'parts_line_ids.price_total', 'parts_line_ids.tax_amount',
        'consumables_line_ids.price_subtotal', 'consumables_line_ids.price_total', 'consumables_line_ids.tax_amount',
        'repairs_line_ids.price_subtotal', 'repairs_line_ids.price_total', 'repairs_line_ids.tax_amount',
        'paint_line_ids.price_subtotal', 'paint_line_ids.price_total', 'paint_line_ids.tax_amount',
        'sundries_line_ids.price_subtotal', 'sundries_line_ids.price_total', 'sundries_line_ids.tax_amount',
        'fittings_line_ids.price_subtotal', 'fittings_line_ids.price_total', 'fittings_line_ids.tax_amount'
    )
    def _compute_total(self):
        import logging
        _logger = logging.getLogger(__name__)
        for rec in self:
            all_lines = rec.job_card_lines | rec.parts_line_ids | rec.consumables_line_ids | rec.repairs_line_ids | rec.paint_line_ids | rec.sundries_line_ids | rec.fittings_line_ids
            lines = all_lines.filtered(lambda l: not l.display_type)
            _logger.info("COMPUTE TOTAL CALLED! parts: %s, all: %s", len(rec.parts_line_ids), len(all_lines))
            for l in lines:
                _logger.info("LINE ID: %s, subtotal: %s", l.id, l.price_subtotal)
            rec.amount_untaxed = sum(lines.mapped('price_subtotal'))
            rec.amount_tax = sum(lines.mapped('tax_amount'))
            rec.amount_total = rec.amount_untaxed + rec.amount_tax
            rec.total_amount = rec.amount_total

    def _organize_sections(self):
        categories = ['parts', 'consumables', 'repairs', 'paint', 'sundries', 'fittings']
        from .estimate import LINE_CATEGORY_SELECTION
        category_names = dict(LINE_CATEGORY_SELECTION)
        base_seq = {'parts': 1000, 'consumables': 1500, 'repairs': 2000, 'paint': 3000, 'sundries': 3500, 'fittings': 4000}
        
        for rec in self:
            for cat in categories:
                # Get lines from the specific category tab
                cat_lines = getattr(rec, f'{cat}_line_ids').filtered(lambda l: l.display_type != 'line_section')
                if cat_lines:
                    # Link them to the main order lines
                    for line in cat_lines:
                        line.job_card_id = rec.id

                    section = rec.job_card_lines.filtered(lambda l: l.line_category == cat and l.display_type == 'line_section')
                    if not section:
                        self.env['job.card.line'].create({
                            'job_card_id': rec.id,
                            'line_category': cat,
                            'display_type': 'line_section',
                            'name': category_names[cat],
                            'sequence': base_seq[cat]
                        })
                    else:
                        section.sequence = base_seq[cat]
                    
                    seq = base_seq[cat] + 1
                    for line in cat_lines:
                        line.sequence = seq
                        seq += 1

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._organize_sections()
        return records

    def write(self, vals):
        res = super().write(vals)
        self._organize_sections()
        return res

    def _build_so_lines_from_job(self, price_multiplier=1.0):
        """Build sale order lines from job card lines, applying a price multiplier for splits."""
        lines = []
        for line in self.job_card_lines:
            line_vals = {}
            if line.display_type:
                line_vals['display_type'] = line.display_type
                line_vals['name'] = line.name
            else:
                line_vals['name'] = line.name or (line.product_id.name if line.product_id else '')
                line_vals['product_uom_qty'] = line.quantity
                line_vals['price_unit'] = line.unit_price * price_multiplier
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
            lines.append(line_vals)
        return lines

    def action_approve_job_card(self):
        for rec in self:
            # Soft excess warning: if insurance company is set but excess is 0
            if rec.second_customer_id and not rec.excess_amount and not rec.excess_warning_reason:
                return {
                    'type': 'ir.actions.act_window',
                    'name': 'Excess Amount Warning',
                    'res_model': 'job.card.excess.warning.wizard',
                    'view_mode': 'form',
                    'target': 'new',
                    'context': {
                        'default_job_card_id': rec.id,
                    }
                }

            rec.state = 'pending_inventory'
            if not rec.access_token:
                rec._generate_access_token()

            # Create Sales Orders if not already created
            if not rec.customer_sale_order_id:
                has_insurance = bool(
                    rec.second_customer_id and
                    rec.second_customer_id.partner_id
                )
                
                # Fetch settings
                billing_policy = self.env['ir.config_parameter'].sudo().get_param('job_card_management.job_card_billing_policy', 'percentage')
                enable_betterment = self.env['ir.config_parameter'].sudo().get_param('job_card_management.enable_betterment', 'False') == 'True'
                betterment_policy = self.env['ir.config_parameter'].sudo().get_param('job_card_management.betterment_billing_policy', 'percentage')

                # Helper to get/create product
                def get_service_product(name):
                    product = self.env['product.product'].search([('name', '=', name)], limit=1)
                    if not product:
                        product = self.env['product.product'].create({'name': name, 'type': 'service'})
                    return product

                excess_product = get_service_product('Excess')
                betterment_product = get_service_product('Betterment')

                # Total Job Card Amount for percentage calculations
                total_amount = rec.amount_total

                if has_insurance:
                    if billing_policy == 'percentage':
                        excess_value = total_amount * (rec.excess_percentage / 100.0)
                        insurance_value = total_amount * (rec.insurance_percentage / 100.0)
                        excess_factor = rec.excess_percentage / 100.0
                        insurance_factor = rec.insurance_percentage / 100.0
                    else:
                        excess_value = rec.excess_amount
                        insurance_value = rec.insurance_amount
                        excess_factor = (excess_value / total_amount) if total_amount else 0.0
                        insurance_factor = (insurance_value / total_amount) if total_amount else 0.0

                    if enable_betterment:
                        if betterment_policy == 'percentage':
                            betterment_value = total_amount * (rec.betterment_percentage / 100.0)
                        else:
                            betterment_value = rec.betterment_amount
                    else:
                        betterment_value = 0.0

                    # Customer SO
                    customer_so = self.env['sale.order'].create({
                        'partner_id': rec.customer_id.partner_id.id,
                        'user_id': self.env.user.id,
                        'origin': f"{rec.name} (Customer)",
                        'note': f"Customer portion of Job Card {rec.name}",
                    })
                    rec.customer_sale_order_id = customer_so.id
                    
                    # Create Excess Line
                    self.env['sale.order.line'].create({
                        'order_id': customer_so.id,
                        'product_id': excess_product.id,
                        'name': excess_product.name,
                        'product_uom_qty': 1.0,
                        'price_unit': excess_value,
                    })
                    
                    # Create Betterment Line if > 0
                    if enable_betterment and betterment_value > 0:
                        self.env['sale.order.line'].create({
                            'order_id': customer_so.id,
                            'product_id': betterment_product.id,
                            'name': betterment_product.name,
                            'product_uom_qty': 1.0,
                            'price_unit': betterment_value,
                        })
                        
                    customer_so.action_confirm()

                    # Insurance SO
                    insurance_so = self.env['sale.order'].create({
                        'partner_id': rec.second_customer_id.partner_id.id,
                        'user_id': customer_so.user_id.id or self.env.user.id,
                        'origin': f"{rec.name} (Insurance)",
                        'note': f"Insurance portion of Job Card {rec.name}",
                    })
                    rec.insurance_sale_order_id = insurance_so.id
                    for line_vals in rec._build_so_lines_from_job(price_multiplier=insurance_factor):
                        self.env['sale.order.line'].create(dict(line_vals, order_id=insurance_so.id))
                    insurance_so.action_confirm()
                else:
                    # No Insurance: single SO, customer pays all
                    total_amount = rec.amount_total
                    if enable_betterment:
                        if betterment_policy == 'percentage':
                            betterment_value = total_amount * (rec.betterment_percentage / 100.0)
                        else:
                            betterment_value = rec.betterment_amount
                    else:
                        betterment_value = 0.0

                    sale_order = self.env['sale.order'].create({
                        'partner_id': rec.customer_id.partner_id.id,
                        'user_id': self.env.user.id,
                        'origin': rec.name,
                    })
                    rec.customer_sale_order_id = sale_order.id
                    
                    # Create Excess Line (which is 100% of the cost here)
                    self.env['sale.order.line'].create({
                        'order_id': sale_order.id,
                        'product_id': excess_product.id,
                        'name': "Job Card Total",
                        'product_uom_qty': 1.0,
                        'price_unit': total_amount,
                    })
                    
                    # Create Betterment Line if > 0
                    if enable_betterment and betterment_value > 0:
                        self.env['sale.order.line'].create({
                            'order_id': sale_order.id,
                            'product_id': betterment_product.id,
                            'name': betterment_product.name,
                            'product_uom_qty': 1.0,
                            'price_unit': betterment_value,
                        })
                    sale_order.action_confirm()
            
            # Auto-create invoices if enabled
            if rec.auto_create_invoices:
                try:
                    rec._generate_linked_invoices()
                except UserError as e:
                    _logger.warning(f"Could not auto-create invoices for job card {rec.name}: {str(e)}")

    def action_start_job(self):
        self._check_schedule_dates()
        self.state = 'in_progress'
        return True

    def action_create_requisition(self):
        if self.state in ['completed', 'delivered']:
            raise UserError(_('You cannot create a requisition for a completed job.'))
        self._check_schedule_dates()
        
        if not self.analytic_account_id:
            self.analytic_account_id = self._fetch_analytic_account()
        
        procurement = self.env['procurement'].create({
            'job_card_id': self.id,
            'analytic_account_id': self.analytic_account_id.id if self.analytic_account_id else False,
        })
        # Create procurement lines from supply parts lines only
        for line in self.parts_line_ids:
            if line.display_type:
                self.env['procurement.line'].create({
                    'procurement_id': procurement.id,
                    'sequence': line.sequence,
                    'display_type': line.display_type,
                    'name': line.name,
                    'type': 'purchase_order',
                    'quantity': 0.0,
                })
            elif line.product_id:
                self.env['procurement.line'].create({
                    'procurement_id': procurement.id,
                    'sequence': line.sequence,
                    'product_id': line.product_id.id,
                    'product_uom_id': line.product_uom_id.id if line.product_uom_id else False,
                    'quantity': line.quantity,
                    'buying_price': line.product_id.standard_price or 0.0,
                    'selling_price': line.unit_price or line.product_id.lst_price or 0.0,
                    'type': 'purchase_order',
                })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'procurement',
            'res_id': procurement.id,
            'view_mode': 'form',
        }

    def _generate_linked_invoices(self):
        """Generate invoices from linked SOs or standalone."""
        if self.invoice_created:
            return

        if self.customer_sale_order_id:
            # Invoice customer SO
            if self.customer_sale_order_id.invoice_status in ('to invoice', 'no'):
                customer_invoices = self.customer_sale_order_id._create_invoices()
                customer_invoices.action_post()
                if customer_invoices:
                    self.customer_invoice_id = customer_invoices[0].id

            # Invoice insurance SO (if exists)
            if self.insurance_sale_order_id and self.insurance_sale_order_id.invoice_status in ('to invoice', 'no'):
                insurance_invoices = self.insurance_sale_order_id._create_invoices()
                insurance_invoices.write({'is_insurance_invoice': True})
                insurance_invoices.action_post()
                if insurance_invoices:
                    self.insurance_invoice_id = insurance_invoices[0].id

            self.invoice_created = True

    def action_finalize_job_card(self):
        if not self.second_customer_id:
            raise UserError(_('Please add Insurance Company as Second Customer before finalizing.'))
        if not self.excess_percentage and self.billing_policy_setting == 'percentage':
            raise UserError(_('Please set the Excess percentage.'))
        if not self.all_inventory_issued:
            raise UserError(_('You cannot finalize the job until all parts have been issued or requisitioned.'))
        if self.consumables_line_ids and not self.all_consumables_issued:
            raise UserError(_('You cannot finalize the job until all Consumables have been issued.'))

        # Ensure invoices are created (if not already created at open)
        self._generate_linked_invoices()

        self.state = 'delivered'
        return self.action_view_invoices()
    
    def action_view_invoices(self):
        """Action to view created invoices (from linked SOs or standalone)"""
        # Collect invoices from linked SOs
        invoice_ids = set()
        if self.customer_invoice_id:
            invoice_ids.add(self.customer_invoice_id.id)
        if self.insurance_invoice_id:
            invoice_ids.add(self.insurance_invoice_id.id)
        # Also pull invoices from linked sale orders
        for so in (self.customer_sale_order_id | self.insurance_sale_order_id):
            invoice_ids.update(so.invoice_ids.ids)

        if not invoice_ids:
            raise UserError(_('No invoices have been created for this job card yet.'))

        return {
            'type': 'ir.actions.act_window',
            'name': _('Invoices'),
            'res_model': 'account.move',
            'domain': [('id', 'in', list(invoice_ids))],
            'view_mode': 'list,form',
            'target': 'current',
        }
    
    # NEW: Manual action to create invoices
    def action_manually_create_invoices(self):
        """Manual action to create invoices"""
        if self.invoice_created:
            raise UserError(_('Invoices have already been created for this job card.'))
        
        if not self.analytic_account_id:
            self.analytic_account_id = self._fetch_analytic_account()
        
        self._create_invoices()
        
        return self.action_view_invoices()
    
    @api.model
    def get_dashboard_data(self, user_id=None, date_from=None, date_to=None):
        """Return all dashboard statistics - called from JS"""
        dashboard = self.env['job.card.dashboard']
        return dashboard.get_dashboard_data(
            user_id=user_id, date_from=date_from, date_to=date_to
        )

    @api.model
    def get_overdue_jobs(self, user_id=None, date_from=None, date_to=None):
        """Return overdue job cards - called from JS"""
        dashboard = self.env['job.card.dashboard']
        return dashboard.get_overdue_jobs(
            user_id=user_id, date_from=date_from, date_to=date_to
        )
    

class JobCardLine(models.Model):
    _name = 'job.card.line'
    _description = 'Job Card Line'
    _order = 'sequence, id'

    job_card_id = fields.Many2one('job.card', string='Job Card', ondelete='cascade', index=True)
    parts_job_card_id = fields.Many2one('job.card', string='Job Card (Parts)', ondelete='cascade')
    consumables_job_card_id = fields.Many2one('job.card', string='Job Card (Consumables)', ondelete='cascade')
    repairs_job_card_id = fields.Many2one('job.card', string='Job Card (Repairs)', ondelete='cascade')
    paint_job_card_id = fields.Many2one('job.card', string='Job Card (Paint)', ondelete='cascade')
    sundries_job_card_id = fields.Many2one('job.card', string='Job Card (Sundries)', ondelete='cascade')
    fittings_job_card_id = fields.Many2one('job.card', string='Job Card (Fittings)', ondelete='cascade')
    sequence = fields.Integer(string='Sequence', default=10)
    line_category = fields.Selection(
        [
            ('parts', 'Supply Parts'),
            ('consumables', 'Consumables'),
            ('repairs', 'Repair Works'),
            ('paint', 'Paint Job'),
            ('sundries', 'Sundries'),
            ('fittings', 'Fittings'),
        ],
        string='Category',
        default='parts',
        required=True,
    )
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

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('line_category'):
                vals['line_category'] = self.env.context.get('default_line_category', 'parts')
        return super().create(vals_list)

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.name = self.product_id.display_name or self.product_id.name
            self.unit_price = self.product_id.lst_price
            if self.product_id.uom_id:
                self.product_uom_id = self.product_id.uom_id
            self.tax_ids = self.product_id.taxes_id


    def unlink(self):
        for line in self:
            line.write({'tax_ids': [(5, 0, 0)]})
        return super().unlink()

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
                    taxes = line.tax_ids.compute_all(line.unit_price, None, line.quantity, line.product_id)
                    if line.discount:
                        for key in ['total_included', 'total_excluded']:
                            if key in taxes:
                                taxes[key] = taxes[key] * (1 - line.discount / 100.0)
                    line.price_total = taxes.get('total_included', subtotal)
                    line.price_subtotal = taxes.get('total_excluded', subtotal)
                    line.tax_amount = line.price_total - line.price_subtotal
                else:
                    line.price_total = subtotal
                    line.tax_amount = 0

    price_subtotal = fields.Float(string='Subtotal', compute='_compute_amount', store=True)
    tax_amount = fields.Float(string='Tax', compute='_compute_amount', store=True)
    price_total = fields.Float(string='Amount', compute='_compute_amount', store=True)
    rate_2 = fields.Float(string='Rate 2', compute='_compute_rate_2', store=True)

    @api.depends('unit_price', 'job_card_id.amount_total', 'job_card_id.insurance_amount',
                 'parts_job_card_id.amount_total', 'parts_job_card_id.insurance_amount',
                 'consumables_job_card_id.amount_total', 'consumables_job_card_id.insurance_amount',
                 'repairs_job_card_id.amount_total', 'repairs_job_card_id.insurance_amount',
                 'paint_job_card_id.amount_total', 'paint_job_card_id.insurance_amount',
                 'sundries_job_card_id.amount_total', 'sundries_job_card_id.insurance_amount',
                 'fittings_job_card_id.amount_total', 'fittings_job_card_id.insurance_amount')
    def _compute_rate_2(self):
        for line in self:
            parent = (line.job_card_id or line.parts_job_card_id or line.consumables_job_card_id or 
                      line.repairs_job_card_id or line.paint_job_card_id or line.sundries_job_card_id or 
                      line.fittings_job_card_id)
            if parent and parent.amount_total > 0:
                line.rate_2 = (line.unit_price / parent.amount_total) * parent.insurance_amount
            else:
                line.rate_2 = 0.0



class JobCardPortal(CustomerPortal):
    
    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'job_card_count' in counters:
            values['job_card_count'] = request.env['job.card'].search_count([])
        return values
    
    @http_route(['/my/jobcards', '/my/jobcards/page/<int:page>'], type='http', auth="user", website=True)
    def portal_my_jobcards(self, page=1, **kw):
        job_cards = request.env['job.card'].search([])
        return request.render('job_card_management.portal_my_jobcards', {
            'job_cards': job_cards,
            'page_name': 'jobcards',
        })
    
    @http_route(['/my/jobcards/<int:job_card_id>'], type='http', auth="public", website=True)
    def portal_jobcard_detail(self, job_card_id, access_token=None, **kw):
        job_card = request.env['job.card'].sudo().browse(job_card_id)
        if not job_card.exists():
            return request.not_found()
        # If access_token is provided, validate it
        if access_token and job_card.access_token != access_token:
            return request.not_found()
        return request.render('job_card_management.portal_jobcard_detail', {
            'job_card': job_card,
            'page_name': 'jobcard',
        })