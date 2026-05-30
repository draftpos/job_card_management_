import random
import string

from odoo import models, fields, api, _
from odoo.exceptions import UserError

class Procurement(models.Model):
    _name = 'procurement'
    _description = 'Procurement / Requisition'
    _order = 'id desc'

    def _default_name(self):
        last = self.search([], order='name desc', limit=1)
        if last and last.name and last.name.startswith('JOB-'):
            last_num = int(last.name[4:])  # Get everything after 'JOB-'
            new_num = last_num + 1
        else:
            new_num = 1001  # Starting point

        return f'JOB-{new_num}'  # No zero-padding, just the number
    
    name = fields.Char(string='Requisition Number', required=True, default=_default_name)
    job_card_id = fields.Many2one('job.card', string='Job Card', required=True)
    analytic_account_id = fields.Many2one('account.analytic.account', string='Analytic Account')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted_for_approval', 'Submit for Requisition Approval'),
        ('approved', 'Requisition Approved'),
        ('purchase_order_created', 'Purchase Order Created')
    ], default='draft')

    procurement_lines = fields.One2many('procurement.line', 'procurement_id', string='Items')
    total_amount = fields.Float(string='Total Amount', compute='_compute_total_amount', store=False, readonly=True)
    purchase_order_created_count = fields.Integer(string='Purchase Orders Created', compute='_compute_procurement_stats')
    internal_transfer_created_count = fields.Integer(string='Internal Transfers Created', compute='_compute_procurement_stats')
    receipt_delivered_count = fields.Integer(string='Delivered Items', compute='_compute_procurement_stats')
    
    @api.depends('job_card_id')
    def _compute_total_amount(self):
        for record in self:
            if record.job_card_id:
                record.total_amount = record.job_card_id.total_amount
            else:
                record.total_amount = 0.0
            
    

    @api.depends('procurement_lines.purchase_order_created', 'procurement_lines.internal_transfer_created', 'procurement_lines.receipt_status')
    def _compute_procurement_stats(self):
        for record in self:
            record.purchase_order_created_count = sum(1 for line in record.procurement_lines if line.purchase_order_created)
            record.internal_transfer_created_count = sum(1 for line in record.procurement_lines if line.internal_transfer_created)
            record.receipt_delivered_count = sum(1 for line in record.procurement_lines if line.receipt_status == 'delivered')

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

    def action_submit_for_approval(self):
        self.state = 'submitted_for_approval'

    def action_approve_requisition(self):
        if not self.env.user.has_group('job_card_management.group_can_approve_procurement'):
            raise UserError(_('You are not allowed to approve requisitions.'))
        self.state = 'approved'

    def action_create_purchase_order(self):
        if self.state != 'approved':
            raise UserError(_('Requisition must be approved before creating purchase orders.'))

        purchase_lines = self.procurement_lines.filtered(
            lambda l: not l.display_type and l.type == 'purchase_order'
        )
        missing_vendor_lines = purchase_lines.filtered(
            lambda l: (
                not l.vendor_id
                or not l.vendor_id.partner_id
                or not l.vendor_id.partner_id.is_supplier
            )
        )
        if missing_vendor_lines:
            raise UserError(_('Please set a valid supplier/vendor on all purchase-order lines before creating a purchase order.'))
        
        # Group by vendor
        vendor_lines = {}
        for line in self.procurement_lines:
            if line.type == 'purchase_order' and line.vendor_id and line.vendor_id.partner_id:
                if line.vendor_id.id not in vendor_lines:
                    vendor_lines[line.vendor_id.id] = []
                vendor_lines[line.vendor_id.id].append(line)

        # Create Purchase Orders in Odoo
        for vendor_id, lines in vendor_lines.items():
            vendor = self.env['customer'].browse(vendor_id)
            po = self.env['purchase.order'].create({
                'partner_id': vendor.partner_id.id,
                'origin': self.name,
            })
            for line in lines:
                po_line_vals = {
                    'order_id': po.id,
                    'product_id': line.product_id.id,
                    'product_qty': line.quantity,
                    'product_uom_id': line.product_uom_id.id or (line.product_id.uom_id.id if line.product_id else False),
                    'price_unit': line.buying_price or 0.0,
                    'date_planned': fields.Datetime.now(),
                }
                analytic_account = self.analytic_account_id or self.job_card_id.analytic_account_id
                if analytic_account:
                    po_line_vals['analytic_distribution'] = {str(analytic_account.id): 100.0}
                self.env['purchase.order.line'].create(po_line_vals)
            po.button_confirm()
            for line in lines:
                line.write({'purchase_order_created': True})

        # Internal transfers (type = internal_transfer)
        for line in self.procurement_lines.filtered(lambda l: l.type == 'internal_transfer'):
            line.write({'internal_transfer_created': True})

        self.state = 'purchase_order_created'

    def action_view_purchase_orders(self):
        self.ensure_one()
        purchase_orders = self.env['purchase.order'].search([('origin', '=', self.name)])
        return {
            'type': 'ir.actions.act_window',
            'name': _('Purchase Orders'),
            'res_model': 'purchase.order',
            'view_mode': 'list,form',
            'domain': [('id', 'in', purchase_orders.ids)],
        }

    def action_view_internal_transfers(self):
        self.ensure_one()
        pickings = self.env['stock.picking'].search([
            ('origin', '=', self.name),
            ('picking_type_code', '=', 'internal'),
        ])
        return {
            'type': 'ir.actions.act_window',
            'name': _('Internal Transfers'),
            'res_model': 'stock.picking',
            'view_mode': 'list,form',
            'domain': [('id', 'in', pickings.ids)],
        }

    def action_view_delivered_items(self):
        self.ensure_one()
        pickings = self.env['stock.picking'].search([
            ('origin', '=', self.name),
            ('picking_type_code', '=', 'incoming'),
            ('state', '=', 'done'),
        ])
        return {
            'type': 'ir.actions.act_window',
            'name': _('Delivered Items'),
            'res_model': 'stock.picking',
            'view_mode': 'list,form',
            'domain': [('id', 'in', pickings.ids)],
        }

    def action_create_grv(self):
        # Update receipt statuses
        for line in self.procurement_lines:
            if line.type == 'purchase_order' and line.purchase_order_created:
                # Check stock moves for this product from linked POs
                po_lines = self.env['purchase.order.line'].search([
                    ('product_id', '=', line.product_id.id),
                    ('order_id.origin', '=', self.name)
                ])
                total_received = 0.0
                for po_line in po_lines:
                    received = sum(po_line.move_ids.filtered(lambda m: m.state == 'done').mapped('move_line_ids.qty_done'))
                    total_received += received
                if total_received >= line.quantity:
                    line.receipt_status = 'delivered'
                elif total_received > 0:
                    line.receipt_status = 'partial'
                else:
                    line.receipt_status = 'open'
        
        # Open GRV (Goods Receipt Vouchers) - stock pickings for incoming
        purchase_orders = self.env['purchase.order'].search([('origin', '=', self.name)])
        picking_ids = purchase_orders.mapped('picking_ids').filtered(lambda p: p.picking_type_code == 'incoming').ids
        if picking_ids:
            return {
                'type': 'ir.actions.act_window',
                'name': 'Goods Receipt Vouchers',
                'res_model': 'stock.picking',
                'view_mode': 'list,form',
                'domain': [('id', 'in', picking_ids)],
            }
        else:
            raise UserError(_('No incoming pickings found for this procurement.'))

class ProcurementLine(models.Model):
    _name = 'procurement.line'
    _description = 'Procurement Line'
    _order = 'sequence, id'

    procurement_id = fields.Many2one('procurement', string='Procurement')
    sequence = fields.Integer(string='Sequence', default=10)
    display_type = fields.Selection([
        ('line_section', 'Section'),
        ('line_note', 'Note'),
    ], string='Line Type', help='Choose section or note line to add headers and descriptions.')
    name = fields.Text(string='Description')
    product_id = fields.Many2one('product.product', string='Product')
    product_uom_id = fields.Many2one('uom.uom', string='Unit of Measure', default=lambda self: self.env.ref('uom.product_uom_unit', raise_if_not_found=False).id if self.env.ref('uom.product_uom_unit', raise_if_not_found=False) else False)
    quantity = fields.Float(string='Quantity', default=1.0)
    buying_price = fields.Float(string='Buying Price')
    selling_price = fields.Float(string='Selling Price')
    profit = fields.Float(string='Profit', compute='_compute_profitability', store=False)
    markup_percent = fields.Float(string='Markup %', compute='_compute_profitability', store=False)
    type = fields.Selection([
        ('internal_transfer', 'Internal Transfer'),
        ('purchase_order', 'Purchase Order')
    ], string='Type', required=True, default='purchase_order')
    vendor_id = fields.Many2one(
        'customer',
        string='Vendor',
        help='Editable only after requisition approved',
        domain="[('customer_type', '=', 'main'), ('partner_id.is_supplier', '=', True)]",
    )
    receipt_status = fields.Selection([
        ('open', 'Open'),
        ('partial', 'Partial'),
        ('delivered', 'Delivered')
    ], string='Receipt Status', default='open')
    purchase_order_created = fields.Boolean(string='PO Created', default=False)
    internal_transfer_created = fields.Boolean(string='Internal Transfer Created', default=False)

    @api.onchange('type')
    def _onchange_type(self):
        if self.type == 'internal_transfer':
            self.vendor_id = False

    @api.onchange('product_id')
    def _onchange_product_id_prices(self):
        if self.product_id:
            self.buying_price = self.product_id.standard_price or 0.0
            self.selling_price = self.product_id.lst_price or 0.0

    @api.depends('buying_price', 'selling_price', 'quantity')
    def _compute_profitability(self):
        for line in self:
            line.profit = (line.selling_price - line.buying_price) * (line.quantity or 0.0)
            if line.buying_price:
                line.markup_percent = ((line.selling_price - line.buying_price) / line.buying_price) * 100.0
            else:
                line.markup_percent = 0.0