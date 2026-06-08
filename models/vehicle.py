from odoo import api, fields, models
from odoo.exceptions import ValidationError


class Vehicle(models.Model):
    _name = 'vehicle'
    _description = 'Vehicle Master'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'job.card.backend.navigation.mixin']
    _order = 'registration_number, name'

    name = fields.Char(
        string='Vehicle Name',
        help='Optional nickname for the vehicle.',
    )
    registration_number = fields.Char(string='Registration Number', required=True)
    chassis_number = fields.Char(string='Chassis / VIN Number')
    engine_number = fields.Char(string='Engine Number')
    make_id = fields.Many2one('vehicle.make', string='Make', required=True)
    model_id = fields.Many2one(
        'vehicle.model',
        string='Model',
        domain="[('make_id', '=', make_id)]",
        required=True
    )

    def _compute_display_name(self):
        for vehicle in self:
            parts = [vehicle.registration_number]
            if vehicle.make_id and vehicle.model_id:
                parts.append(f"({vehicle.make_id.name} {vehicle.model_id.name})")
            vehicle.display_name = " ".join(filter(None, parts))
    year_of_manufacture = fields.Integer(string='Year of Manufacture')
    color = fields.Char(string='Color')

    @api.constrains('chassis_number', 'engine_number', 'year_of_manufacture', 'color')
    def _check_required_fields(self):
        IrConfigParam = self.env['ir.config_parameter'].sudo()
        req_chassis = IrConfigParam.get_param('job_card_management.vehicle_require_chassis') == 'True'
        req_engine = IrConfigParam.get_param('job_card_management.vehicle_require_engine') == 'True'
        req_year = IrConfigParam.get_param('job_card_management.vehicle_require_year') == 'True'
        req_color = IrConfigParam.get_param('job_card_management.vehicle_require_color') == 'True'
        
        for record in self:
            if req_chassis and not record.chassis_number:
                raise ValidationError("Chassis Number is required as per settings.")
            if req_engine and not record.engine_number:
                raise ValidationError("Engine Number is required as per settings.")
            if req_year and not record.year_of_manufacture:
                raise ValidationError("Year of Manufacture is required as per settings.")
            if req_color and not record.color:
                raise ValidationError("Color is required as per settings.")

    engine_type_code = fields.Char(string='Engine Type/Code')
    transmission = fields.Selection([
        ('manual', 'Manual'),
        ('automatic', 'Automatic'),
        ('cvt', 'CVT'),
        ('other', 'Other'),
    ], string='Transmission')
    drive_type = fields.Selection([
        ('fwd', 'Front Wheel Drive'),
        ('rwd', 'Rear Wheel Drive'),
        ('awd', 'All Wheel Drive'),
        ('4wd', '4 Wheel Drive'),
    ], string='Drive Type')
    fuel_type = fields.Selection([
        ('petrol', 'Petrol'),
        ('diesel', 'Diesel'),
        ('electric', 'Electric'),
        ('hybrid', 'Hybrid'),
        ('cng', 'CNG'),
        ('lpg', 'LPG'),
    ], string='Fuel Type')
    odometer_reading = fields.Float(string='Odometer Reading (km/miles)')

    reason_for_service = fields.Text(string='Reason for Service')
    last_service_date = fields.Date(string='Last Service Date')
    last_service_mileage = fields.Float(string='Last Service Mileage')
    known_repairs = fields.Text(string='Known Repairs or Modifications')
    specific_concerns = fields.Text(string='Any Specific Concerns')

    customer_id = fields.Many2one('customer', string='Owner Customer')
    insurance_customer_id = fields.Many2one('customer', string='Insurance Customer')

    completed_job_cards = fields.One2many(
        'job.card', compute='_compute_completed_job_cards', string='Completed Job Cards',
    )

    def _job_card_form_action_xmlid(self):
        return 'job_card_management.action_vehicle'

    @api.depends()
    def _compute_completed_job_cards(self):
        for vehicle in self:
            vehicle.completed_job_cards = self.env['job.card'].search([
                ('vehicle_id', '=', vehicle.id),
                ('state', '=', 'delivered'),
            ], order='create_date desc')

    @api.onchange('make_id')
    def _onchange_make_id(self):
        self.model_id = False

    @api.onchange('model_id')
    def _onchange_model_id(self):
        if self.model_id and self.model_id.fuel_type:
            self.fuel_type = self.model_id.fuel_type
        if self.model_id and self.model_id.year_to:
            self.year_of_manufacture = self.model_id.year_to

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') and vals.get('registration_number'):
                vals['name'] = vals['registration_number']
        return super().create(vals_list)

    @api.model
    def _format_display_name(self, vehicle):
        reg = (vehicle.registration_number or 'N/A').strip()
        make_model = ' '.join(p for p in [vehicle.make, vehicle.model] if p)
        if make_model:
            return f'({reg}) {make_model}'
        return f'({reg})'

    def name_get(self):
        return [(vehicle.id, self._format_display_name(vehicle)) for vehicle in self]

    @api.model
    def _name_search(self, name='', args=None, operator='ilike', limit=100, name_get_uid=None):
        args = list(args or [])
        if name:
            domain = [
                '|', '|', '|', '|',
                ('registration_number', operator, name),
                ('make', operator, name),
                ('model', operator, name),
                ('name', operator, name),
                ('chassis_number', operator, name),
            ]
            return self._search(domain + args, limit=limit, access_rights_uid=name_get_uid)
        return super()._name_search(name, args, operator, limit, name_get_uid)

    def action_preview_vehicle_history(self):
        report = self.env.ref('job_card_management.action_report_vehicle_history')
        return {
            'type': 'ir.actions.act_url',
            'url': f'/report/pdf/{report.report_name}/{self.id}',
            'target': 'new',
        }
