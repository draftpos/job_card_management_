import random
import string

from odoo import models, fields, api, _
from odoo.exceptions import UserError

class Procurement(models.Model):
    _name = 'procurement'
    _description = 'Procurement / Requisition'
    _order = 'id desc'

    def _default_name(self):
        random_part = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        return 'PRC-%s-TEX' % random_part

    name = fields.Char(string='Requisition Number', required=True, default=_default_name)
    job_card_id = fields.Many2one('job.card', string='Job Card', required=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted_for_approval', 'Submit for Approval'),
        ('approved', 'Approved'),
        ('purchase_order_created', 'Purchase Order Created')
    ], default='draft')

    procurement_lines = fields.One2many('procurement.line', 'procurement_id', string='Items')
    total_amount = fields.Float(string='Total Amount', related='job_card_id.total_amount', store=False, readonly=True)

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
                self.env['purchase.order.line'].create({
                    'order_id': po.id,
                    'product_id': line.product_id.id,
                    'product_qty': line.quantity,
                })
            po.button_confirm()
            line.write({'purchase_order_created': True})

        # Internal transfers (type = internal_transfer)
        for line in self.procurement_lines.filtered(lambda l: l.type == 'internal_transfer'):
            line.write({'internal_transfer_created': True})

        self.state = 'purchase_order_created'

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

    procurement_id = fields.Many2one('procurement', string='Procurement')
    product_id = fields.Many2one('product.product', string='Product', required=True)
    quantity = fields.Float(string='Quantity', default=1.0)
    type = fields.Selection([
        ('internal_transfer', 'Internal Transfer'),
        ('purchase_order', 'Purchase Order')
    ], string='Type', required=True)
    vendor_id = fields.Many2one('customer', string='Vendor', help='Editable only after requisition approved', domain="[('customer_type', '=', 'main')]")
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