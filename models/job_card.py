import random
import string
import logging

from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

class JobCard(models.Model):
    _name = 'job.card'
    _description = 'Job Card'
    _order = 'id desc'

    def _default_name(self):
        return 'JOB-1%03d' % (int(self.search([], order='name desc', limit=1).name[4:] or 0) + 1 if self.search([], order='name desc', limit=1) and self.search([], order='name desc', limit=1).name and self.search([], order='name desc', limit=1).name.startswith('JOB-') else 1)

    # def _default_name(self):
    #     random_part = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    #     return 'JOB-%s-TEX' % random_part

    name = fields.Char(string='Job Card Number', required=True, default=_default_name)
    estimate_id = fields.Many2one('estimate', string='Estimate', required=True)
    customer_id = fields.Many2one('customer', string='First Customer', required=True)  # Changed
    second_customer_id = fields.Many2one('customer', string='Insurance Company', help='Added at final stage')  # Changed
    excess_percentage = fields.Float(string='Excess (%)', help='Percentage paid by first customer')
    insurance_percentage = fields.Float(string='Insurance Percentage (%)', compute='_compute_insurance_pct', store=True)
    vehicle_id = fields.Many2one('vehicle', string='Vehicle', required=True)  # Changed
    vehicle_name = fields.Char(related='vehicle_id.name', string='Vehicle Name', readonly=True)
    vehicle_model = fields.Char(related='vehicle_id.model', string='Vehicle Model', readonly=True)
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
    start_date = fields.Date(string='Start Date Expected')
    end_date = fields.Date(string='End Date Expected')
    job_card_lines = fields.One2many('job.card.line', 'job_card_id', string='Job Card Lines')
    
    # NEW: Invoice tracking fields
    invoice_created = fields.Boolean(string='Invoice Created', default=False)
    customer_invoice_id = fields.Many2one('account.move', string='Customer Invoice')
    insurance_invoice_id = fields.Many2one('account.move', string='Insurance Invoice')
    auto_create_invoices = fields.Boolean(string='Auto Create Invoices', default=True, 
                                          help='Automatically create invoices when job card is created')

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
        
        # NEW: Fetch and assign analytic account after creation
        analytic_account = job_card._fetch_analytic_account()
        if analytic_account:
            job_card.analytic_account_id = analytic_account.id
        
        # NEW: Auto-create invoices if enabled
        if job_card.auto_create_invoices and job_card.second_customer_id and job_card.excess_percentage:
            try:
                job_card._create_invoices()
            except UserError as e:
                _logger.warning(f"Could not auto-create invoices for job card {job_card.name}: {str(e)}")
        
        return job_card

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
            customer_invoice = self.env['account.move'].create({
                'move_type': 'out_invoice',
                'partner_id': self.customer_id.partner_id.id,
                'invoice_origin': self.name,
                'invoice_line_ids': customer_lines,
                'invoice_date': invoice_date,
                'ref': f"Job Card: {self.name} - Customer Portion",
            })
            customer_invoice.action_post()
            self.customer_invoice_id = customer_invoice.id
            
            # Update analytic account name with invoice number
            if self.analytic_account_id:
                self.analytic_account_id.name = customer_invoice.name
        
        # Create invoice for insurance (insurance portion)
        insurance_lines = self._prepare_invoice_lines('insurance', income_account)
        if insurance_lines and self.second_customer_id and self.second_customer_id.partner_id:
            insurance_invoice = self.env['account.move'].create({
                'move_type': 'out_invoice',
                'partner_id': self.second_customer_id.partner_id.id,
                'invoice_origin': self.name,
                'invoice_line_ids': insurance_lines,
                'invoice_date': invoice_date,
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
                else:  # insurance
                    price = line.price_total * (self.insurance_percentage / 100)
                
                if price > 0:
                    invoice_line_vals = {
                        'name': line.name or (line.product_id.name if line.product_id else 'Job Card Service'),
                        'quantity': line.quantity,
                        'price_unit': price / line.quantity if line.quantity > 0 else price,
                        'account_id': income_account.id,
                    }
                    
                    # Assign analytic account to invoice line if available
                    if self.analytic_account_id:
                        invoice_line_vals['analytic_distribution'] = {
                            str(self.analytic_account_id.id): 100.0
                        }
                    
                    lines.append((0, 0, invoice_line_vals))
        
        return lines

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

    def action_start_job(self):
        """Start job with validation for start and end dates"""
        if not self.start_date:
            raise UserError(_('Please set the Start Date before starting the job.'))
        if not self.end_date:
            raise UserError(_('Please set the End Date before starting the job.'))
        if self.end_date <= self.start_date:
            raise UserError(_('End Date must be after Start Date.'))
        
        self.state = 'in_progress'
        return True

    def action_create_requisition(self):
        if self.state not in ['approved', 'in_progress']:
            raise UserError(_('Job card must be approved or in progress before creating requisition.'))
        
        # Validate start and end dates before creating requisition
        if not self.start_date:
            raise UserError(_('Please set the Start Date before creating requisition.'))
        if not self.end_date:
            raise UserError(_('Please set the End Date before creating requisition.'))
        if self.end_date <= self.start_date:
            raise UserError(_('End Date must be after Start Date.'))
        
        procurement = self.env['procurement'].create({
            'job_card_id': self.id,
            'analytic_account_id': self.analytic_account_id.id,
        })
        # Create procurement lines from job card lines, keeping sections and notes
        for line in self.job_card_lines:
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
        
        # Create split invoices (customer and insurance)
        if not self.invoice_created:
            self._create_invoices()
        
        self.state = 'delivered'
        return self.action_view_invoices()
    
    # NEW: Action to view created invoices
    def action_view_invoices(self):
        """Action to view created invoices"""
        invoices = self.customer_invoice_id + self.insurance_invoice_id
        if not invoices:
            raise UserError(_('No invoices have been created for this job card yet.'))
        
        return {
            'type': 'ir.actions.act_window',
            'name': _('Invoices'),
            'res_model': 'account.move',
            'domain': [('id', 'in', invoices.ids)],
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