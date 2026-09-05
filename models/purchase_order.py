from odoo import api, fields, models, _
from odoo.exceptions import UserError

class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'
    _order = 'id desc'

    notes = fields.Html('Terms and Conditions', default=lambda self: self.env['ir.config_parameter'].sudo().get_param('job_card_management.purchase_default_terms', default=''))
    
    closing_reason = fields.Text(string="Closing Reason", copy=False)
    is_amended = fields.Boolean(string="Is Amended", copy=False, default=False)
    has_done_picking = fields.Boolean(compute='_compute_picking_states')
    has_pending_picking = fields.Boolean(compute='_compute_picking_states')

    @api.depends('picking_ids.state')
    def _compute_picking_states(self):
        for rec in self:
            rec.has_done_picking = any(p.state == 'done' for p in rec.picking_ids)
            rec.has_pending_picking = any(p.state not in ('done', 'cancel') for p in rec.picking_ids)

    def button_approve(self):
        # Restrict approval to authorized users
        if not (self.env.user.has_group('job_card_management.group_can_approve_purchase_order') or self.env.is_superuser()):
            raise UserError(_("You do not have the required permissions to approve Purchase Orders."))
        return super(PurchaseOrder, self).button_approve()

    def button_confirm(self):
        if not (self.env.user.has_group('job_card_management.group_can_approve_purchase_order') or self.env.is_superuser()):
            raise UserError(_("You do not have permission to approve/confirm Purchase Orders. Please request approval from an authorized manager."))
        return super(PurchaseOrder, self).button_confirm()

    def button_cancel(self):
        """Override to auto-cancel related vendor bills and pickings before canceling PO"""
        for order in self:
            for inv in order.invoice_ids:
                if inv.state == 'posted':
                    inv.button_draft()
                    inv.button_cancel()
                elif inv.state != 'cancel':
                    inv.button_cancel()
            for picking in order.picking_ids:
                if picking.state not in ('done', 'cancel'):
                    picking.action_cancel()
        return super(PurchaseOrder, self).button_cancel()

    def action_return_to_supplier_before_grv(self):
        """Action for Return to Supplier before GRV (cancels PO and unreceived pickings)"""
        self.ensure_one()
        if any(picking.state == 'done' for picking in self.picking_ids):
            raise UserError(_("Items have already been received (GRV done). Please use 'Return to Supplier (After GRV)'."))
        self.button_cancel()
        self.message_post(body=_("Order returned to supplier before GRV / cancelled."), subtype_xmlid='mail.mt_note')

    def action_return_to_supplier_after_grv(self):
        """Action for Return to Supplier after GRV (opens standard stock.return.picking wizard)"""
        self.ensure_one()
        done_pickings = self.picking_ids.filtered(lambda p: p.state == 'done')
        if not done_pickings:
            raise UserError(_("No completed GRV / receipts found to return."))
        
        picking = done_pickings[-1]
        return {
            'name': _('Return to Supplier'),
            'type': 'ir.actions.act_window',
            'res_model': 'stock.return.picking',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'active_id': picking.id,
                'active_ids': [picking.id],
                'active_model': 'stock.picking',
            }
        }

    def action_manual_close(self):
        """Action to trigger the manual close wizard"""
        self.ensure_one()
        return {
            'name': _('Close Purchase Order'),
            'type': 'ir.actions.act_window',
            'res_model': 'purchase.order.close.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_purchase_order_id': self.id}
        }
        
    def action_amend_supplier(self):
        """Action to trigger the amend supplier wizard"""
        self.ensure_one()
        return {
            'name': _('Amend Supplier'),
            'type': 'ir.actions.act_window',
            'res_model': 'purchase.order.amend.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_purchase_order_id': self.id, 'default_old_partner_id': self.partner_id.id}
        }

class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    def write(self, vals):
        # Check for price hikes on approved POs
        if 'price_unit' in vals:
            for line in self:
                if line.order_id.state in ['purchase', 'done'] and vals['price_unit'] > line.price_unit:
                    # Reset PO to 'to approve'
                    line.order_id.write({'state': 'to approve'})
                    line.order_id.message_post(
                        body=_("PO reset to 'To Approve' because the price of %s was increased from %s to %s.", line.product_id.display_name, line.price_unit, vals['price_unit']),
                        subtype_xmlid='mail.mt_note'
                    )
        return super(PurchaseOrderLine, self).write(vals)
