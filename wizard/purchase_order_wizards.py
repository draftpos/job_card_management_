from odoo import api, fields, models, _

class PurchaseOrderCloseWizard(models.TransientModel):
    _name = 'purchase.order.close.wizard'
    _description = 'Manual Purchase Order Close Wizard'

    purchase_order_id = fields.Many2one('purchase.order', string="Purchase Order", required=True)
    reason = fields.Text(string="Reason for Closing", required=True)

    def action_confirm_close(self):
        self.ensure_one()
        po = self.purchase_order_id
        po.closing_reason = self.reason
        po.message_post(body=_("PO Manually Closed. Reason: %s") % self.reason, subtype_xmlid='mail.mt_note')
        # Setting state to cancel releases quantities and budget
        po.button_cancel()
        return {'type': 'ir.actions.act_window_close'}


class PurchaseOrderAmendWizard(models.TransientModel):
    _name = 'purchase.order.amend.wizard'
    _description = 'Purchase Order Supplier Amendment Wizard'

    purchase_order_id = fields.Many2one('purchase.order', string="Original Purchase Order", required=True)
    old_partner_id = fields.Many2one('res.partner', string="Current Supplier", readonly=True)
    new_partner_id = fields.Many2one('res.partner', string="New Supplier", required=True)
    reason = fields.Text(string="Reason for Amendment", required=True)

    def action_confirm_amend(self):
        self.ensure_one()
        old_po = self.purchase_order_id
        
        # 1. Duplicate the PO with the new supplier
        new_po = old_po.copy({
            'partner_id': self.new_partner_id.id,
            'is_amended': True,
            'origin': old_po.name,
            'state': 'draft',
        })
        
        # 2. Check if price on new PO is higher than old PO
        price_higher = new_po.amount_total > old_po.amount_total
        if price_higher:
            new_po.state = 'to approve'
            new_po.message_post(
                body=_("Price increased from %s to %s with supplier %s. This PO requires manager approval.") % (
                    old_po.amount_total, new_po.amount_total, self.new_partner_id.name
                ),
                subtype_xmlid='mail.mt_note'
            )
        
        # 3. Cancel the old PO (auto-canceling vendor bills and pickings)
        old_po.closing_reason = _("Amended to new supplier %s. Reason: %s") % (self.new_partner_id.name, self.reason)
        old_po.button_cancel()
        old_po.message_post(
            body=_("Supplier amended to %s. This PO is cancelled and replaced by %s") % (self.new_partner_id.name, new_po._get_html_link()),
            subtype_xmlid='mail.mt_note'
        )
        
        # 4. Post message on the new PO
        new_po.message_post(
            body=_("This PO was generated as an amendment of %s. Reason: %s") % (old_po._get_html_link(), self.reason),
            subtype_xmlid='mail.mt_note'
        )
        
        # 5. Redirect to the new PO
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'purchase.order',
            'res_id': new_po.id,
            'view_mode': 'form',
            'target': 'current'
        }
