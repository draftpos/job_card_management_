from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class JobInventoryIssue(models.Model):
    _name = 'job.inventory.issue'
    _description = 'Job Inventory Issue'
    _order = 'id desc'
    _rec_name = 'name'

    name = fields.Char(string='Reference', readonly=True, copy=False, default='New')

    job_card_id = fields.Many2one(
        'job.card', string='Job Card', required=True,
        domain="[('state', 'not in', ('draft', 'delivered', 'cancelled')), ('all_inventory_issued', '=', False)]"
    )
    customer_id = fields.Many2one(related='job_card_id.customer_id', string='Customer', store=True)
    vehicle_id = fields.Many2one(related='job_card_id.vehicle_id', string='Vehicle', store=True)

    @api.model
    def _default_source_location(self):
        warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.env.company.id)], limit=1)
        if warehouse:
            return warehouse.lot_stock_id.id
        return False

    @api.model
    def _default_dest_location(self):
        production = self.env['stock.location'].search([
            ('usage', '=', 'production'),
            ('company_id', 'in', [self.env.company.id, False])
        ], limit=1)
        return production.id or False

    source_location_id = fields.Many2one(
        'stock.location', string='Source Location',
        domain=[('usage', '=', 'internal')],
        required=True,
        default=_default_source_location
    )
    dest_location_id = fields.Many2one(
        'stock.location', string='Destination Location',
        domain=[('usage', 'in', ['internal', 'production'])],
        required=True,
        default=_default_dest_location
    )

    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('partially_issued', 'Partially Issued'),
        ('issued', 'Issued'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft')

    issue_line_ids = fields.One2many('job.inventory.issue.line', 'issue_id', string='Lines')
    stock_picking_id = fields.Many2one('stock.picking', string='Transfer', readonly=True)
    notes = fields.Text(string='Notes')
    issue_date = fields.Date(string='Issue Date', default=fields.Date.today)

    all_issued = fields.Boolean(string='All Issued', compute='_compute_all_issued', store=True)

    @api.depends('issue_line_ids.issued_qty', 'issue_line_ids.required_qty')
    def _compute_all_issued(self):
        for rec in self:
            rec.all_issued = all(l.issued_qty >= l.required_qty for l in rec.issue_line_ids) if rec.issue_line_ids else False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('inventory.issue') or _('New')
        return super().create(vals_list)

    @api.onchange('job_card_id')
    def _onchange_job_card_id(self):
        if self.job_card_id and not self.issue_line_ids:
            self.action_populate_from_job_card()

    def action_populate_from_job_card(self):
        self.ensure_one()
        if not self.job_card_id:
            raise UserError(_('Please select a Job Card first.'))
        self.issue_line_ids.unlink()
        allow_service = self.env['ir.config_parameter'].sudo().get_param('job_card_management.allow_service_requisition', 'False') == 'True'
        lines_to_create = []
        job = self.job_card_id
        all_job_lines = (
            job.parts_line_ids |
            job.consumables_line_ids |
            job.paint_line_ids |
            job.sundries_line_ids |
            job.fittings_line_ids |
            job.repairs_line_ids
        )
        job_lines = all_job_lines.filtered(
            lambda l: l.display_type not in ('line_section', 'line_note') and l.product_id
        )
        for line in job_lines:
            product = line.product_id
            is_service = product.type == 'service'
            
            if not allow_service and is_service:
                continue
                
            available_qty = 0.0
            if not is_service:
                if self.source_location_id:
                    quants = self.env['stock.quant'].search([
                        ('product_id', '=', product.id),
                        ('location_id', 'child_of', self.source_location_id.id),
                    ])
                    available_qty = sum(quants.mapped('quantity'))
                if not available_qty:
                    available_qty = product.qty_available or 0.0
            lines_to_create.append({
                'issue_id': self.id,
                'product_id': product.id,
                'job_card_line_id': line.id,
                'required_qty': line.quantity,
                'issued_qty': 0.0,
                'available_qty': available_qty,
                'uom_id': line.product_uom_id.id if line.product_uom_id else product.uom_id.id,
                'is_service': is_service,
            })
        if lines_to_create:
            self.env['job.inventory.issue.line'].create(lines_to_create)

    def action_confirm(self):
        self.ensure_one()
        if not self.issue_line_ids:
            raise UserError(_('No lines to issue. Click "Populate from Job Card" first.'))
        for line in self.issue_line_ids:
            if not line.is_service and line.issued_qty == 0:
                line.issued_qty = min(line.required_qty, max(line.available_qty, 0.0))
        self.state = 'confirmed'

    def action_issue(self):
        self.ensure_one()
        if self.state not in ('confirmed', 'partially_issued'):
            raise UserError(_('Confirm the issue before issuing inventory.'))

        lines_to_transfer = self.issue_line_ids.filtered(
            lambda l: not l.is_service and (l.issued_qty - l.transferred_qty) > 0
        )
        if not lines_to_transfer and not any(l.issued_qty > 0 for l in self.issue_line_ids):
            raise UserError(_('No stockable items with issued quantity > 0.'))

        # Check stock levels accurately before issuing
        for line in lines_to_transfer:
            delta_qty = line.issued_qty - line.transferred_qty
            quants = self.env['stock.quant'].search([
                ('product_id', '=', line.product_id.id),
                ('location_id', 'child_of', self.source_location_id.id),
            ])
            loc_qty = sum(quants.mapped('quantity'))
            actual_stock = max(loc_qty, line.product_id.qty_available)
            if delta_qty > actual_stock:
                raise UserError(_(
                    "Insufficient stock for '%s'. Requested issue: %s, Total available on hand: %s."
                ) % (line.product_id.display_name, delta_qty, actual_stock))

        picking = False
        if lines_to_transfer:
            pick_type = self.env['stock.picking.type'].search(
                [('code', '=', 'internal'), ('warehouse_id.company_id', 'in', [self.env.company.id, False])], limit=1
            )
            if not pick_type:
                pick_type = self.env['stock.picking.type'].search([('code', '=', 'internal')], limit=1)
            if not pick_type:
                raise UserError(_('No internal transfer operation type found.'))

            moves = [(0, 0, {
                'product_id': line.product_id.id,
                'product_uom_qty': line.issued_qty - line.transferred_qty,
                'product_uom': line.uom_id.id or line.product_id.uom_id.id,
                'location_id': self.source_location_id.id,
                'location_dest_id': self.dest_location_id.id,
            }) for line in lines_to_transfer]

            picking = self.env['stock.picking'].create({
                'picking_type_id': pick_type.id,
                'location_id': self.source_location_id.id,
                'location_dest_id': self.dest_location_id.id,
                'origin': f"Inventory Issue {self.name} - Job {self.job_card_id.name}",
                'move_ids': moves,
            })
            picking.action_confirm()

            for move in picking.move_ids:
                move.quantity = move.product_uom_qty
                move.picked = True

            try:
                picking.button_validate()
            except Exception:
                pass

            for line in lines_to_transfer:
                line.transferred_qty = line.issued_qty

            self.stock_picking_id = picking.id

        if self.all_issued:
            self.state = 'issued'
        else:
            self.state = 'partially_issued'

        self._update_job_card_inventory_state()
        if picking:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'stock.picking',
                'res_id': picking.id,
                'view_mode': 'form',
            }

    @api.onchange('source_location_id')
    def _onchange_source_location(self):
        if not self.source_location_id:
            for line in self.issue_line_ids:
                line.available_qty = 0.0
            return

        for line in self.issue_line_ids:
            if line.is_service:
                line.available_qty = 0.0
                continue
                
            quants = self.env['stock.quant'].search([
                ('product_id', '=', line.product_id.id),
                ('location_id', 'child_of', self.source_location_id.id),
            ])
            loc_qty = sum(quants.mapped('quantity'))
            line.available_qty = loc_qty if loc_qty else (line.product_id.qty_available or 0.0)

    def _update_job_card_inventory_state(self):
        job = self.job_card_id
        if not job:
            return
        job._compute_all_inventory_issued()
        if job.all_inventory_issued:
            if job.state in ('pending_inventory', 'approved', 'pending_items'):
                job.state = 'inventory_issued'
        else:
            if job.state in ('pending_inventory', 'approved'):
                job.state = 'pending_items'

    def action_create_requisitions(self):
        self.ensure_one()
        allow_service = self.env['ir.config_parameter'].sudo().get_param('job_card_management.allow_service_requisition', 'False') == 'True'
        
        if allow_service:
            short_lines = self.issue_line_ids.filtered(lambda l: l.shortage_qty > 0)
        else:
            short_lines = self.issue_line_ids.filtered(lambda l: not l.is_service and l.shortage_qty > 0)
            
        if not short_lines:
            raise UserError(_('No items are short in stock.'))
        requisition_lines = [(0, 0, {
            'product_id': l.product_id.id,
            'product_qty': l.shortage_qty,
            'product_uom_id': l.uom_id.id or l.product_id.uom_id.id,
        }) for l in short_lines]
        requisition = self.env['purchase.requisition'].create({
            'line_ids': requisition_lines,
        })
        self.job_card_id.state = 'requisition_started'
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'purchase.requisition',
            'res_id': requisition.id,
            'view_mode': 'form',
        }

    def action_cancel(self):
        self.ensure_one()
        if self.state == 'issued':
            raise UserError(_('Cannot cancel an already issued inventory issue.'))
        self.state = 'cancelled'

    def action_reset_draft(self):
        self.ensure_one()
        self.state = 'draft'

    def action_view_picking(self):
        self.ensure_one()
        if not self.stock_picking_id:
            raise UserError(_('No transfer linked to this issue.'))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'stock.picking',
            'res_id': self.stock_picking_id.id,
            'view_mode': 'form',
        }


class JobInventoryIssueLine(models.Model):
    _name = 'job.inventory.issue.line'
    _description = 'Job Inventory Issue Line'

    issue_id = fields.Many2one('job.inventory.issue', string='Issue', ondelete='cascade')
    job_card_line_id = fields.Many2one('job.card.line', string='Job Card Line')
    product_id = fields.Many2one('product.product', string='Product', required=True)
    uom_id = fields.Many2one('uom.uom', string='Unit of Measure')
    required_qty = fields.Float(string='Required Qty', default=1.0)
    available_qty = fields.Float(string='Available in Stock', readonly=True)
    issued_qty = fields.Float(string='Issued Qty', default=0.0)
    transferred_qty = fields.Float(string='Transferred Qty', default=0.0)
    balance_qty = fields.Float(string='Balance', compute='_compute_balance', store=True)
    shortage_qty = fields.Float(string='Shortage', compute='_compute_shortage', store=True)
    is_service = fields.Boolean(string='Service Item', default=False)

    @api.depends('required_qty', 'issued_qty')
    def _compute_balance(self):
        for rec in self:
            rec.balance_qty = max(rec.required_qty - rec.issued_qty, 0)

    @api.depends('required_qty', 'available_qty')
    def _compute_shortage(self):
        for rec in self:
            rec.shortage_qty = max(rec.required_qty - rec.available_qty, 0)

    @api.constrains('issued_qty', 'required_qty')
    def _check_issued_qty(self):
        for rec in self:
            if rec.issued_qty < 0:
                raise ValidationError(_('Issued quantity cannot be negative.'))
            if rec.issued_qty > rec.required_qty:
                raise ValidationError(
                    _('Issued qty (%s) cannot exceed required qty (%s) for %s.') % (
                        rec.issued_qty, rec.required_qty, rec.product_id.name
                    )
                )
